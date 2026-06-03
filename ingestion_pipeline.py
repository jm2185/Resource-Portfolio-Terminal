"""
ingestion_pipeline.py — Phase 6: Open-Source Ingestion Engine (Adapter Layer).

A standalone adapter layer that pulls macro / fundamental / sentiment metrics from
free, open endpoints, maps them into the exact ``data_payload`` schema consumed by
``archetypes.PolymorphicRouter.get_valuation`` (via ``engine._archetype_payload``),
and caches the result to ``data/ingestion_cache.json``.

Design constraints (Phase 6):
  * Strict isolation — all endpoint / parsing logic lives here. This module imports
    nothing from ``engine.py``; ``archetypes.py`` is untouched. The only symbol the
    engine imports back is :func:`load_ingestion_cache` (one-directional, no cycle).
  * No new dependencies — reuses the in-repo idiom (``requests`` + stdlib parsing)
    already proven in ``engine.py`` for the keyless FRED CSV endpoint. ``requests``
    and ``yfinance`` are imported defensively so this module always loads; a missing
    dependency simply makes the affected adapter unavailable (graceful degradation).
  * Config-driven & extensible — providers are registered in :data:`ADAPTER_REGISTRY`
    and wired from the ``ingestion`` block of ``v5_config.json``. Adding a new provider
    (Alpha Vantage, Polygon, a brokerage API, ...) is: (1) write a ``@register_adapter``
    subclass of :class:`BaseAdapter`; (2) add one entry to ``ingestion.providers``.
    No change to the pipeline, cache, mapper, or engine seam.
  * Graceful degradation everywhere — a dead endpoint omits a key, and the archetype's
    ``_safe_leg`` / ``_num`` helpers renormalize the confidence-tilted blend around the
    surviving legs. Missing/stale cache on the engine side is a no-op.

CLI:
    python ingestion_pipeline.py --tickers AGA.V,URC.TO,GROY,GMX.TO
    python ingestion_pipeline.py --providers fred --verbose
    python ingestion_pipeline.py --enable-sentiment
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import os
import re
import time
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger("ingestion_pipeline")

# Phase 8: catalyst classification/dedup helpers (one-directional import; catalyst_engine
# never imports this module). Guarded so a missing file just disables the news/filing classifier.
try:
    from catalyst_engine import classify_headline, match_ticker, attribute, clean_title, dedupe_events
except Exception:  # pragma: no cover
    classify_headline = match_ticker = attribute = clean_title = dedupe_events = None

# --------------------------------------------------------------------------- #
#  Optional heavy deps — guarded so the module always imports.
# --------------------------------------------------------------------------- #
try:
    import requests
except Exception:  # pragma: no cover - exercised only when requests is absent
    requests = None


def _import_yfinance():
    """Import yfinance lazily so the module loads (and tests run) without it."""
    try:
        import yfinance as yf
        return yf
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Constants & built-in defaults (so the pipeline runs even with no config block)
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1
DEFAULT_CONFIG_PATH = "v5_config.json"
DEFAULT_CACHE_PATH = "data/ingestion_cache.json"
DEFAULT_TTL_SECONDS = 86_400  # 24h
DEFAULT_USER_AGENT = "CommodityEx-QuantMonitor/5.3 (research; contact@example.com)"

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# US-GAAP XBRL tags (SEC EDGAR CompanyFacts)
CASH_TAG = "CashAndCashEquivalentsAtCarryingValue"
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"
SHARES_TAG = "CommonStockSharesOutstanding"

# Capability tags — the contract between adapters and the merge/mapping layer.
CAP_MACRO = "macro"
CAP_FIN = "financials"
CAP_COMPS = "comps"
CAP_CONV = "conviction_signals"
CAP_PRICING = "pricing"
CAP_CATALYSTS = "catalysts"   # Phase 8: real-world events (drill/financing/permitting/catalyst)

DEFAULT_TICKERS = ["AGA.V", "URC.TO", "GROY", "GMX.TO"]
DEFAULT_FRED_SERIES = {
    "real_yield": "REAINTRATREARAT10Y",  # 10-Year real interest rate
    "sofr": "SOFR",                      # Secured Overnight Financing Rate
    "m2v": "M2V",                        # M2 money velocity
    "ted": "TEDRATE",                    # TED spread
}
# Highest-precedence first. A manual analyst override always wins; SEC (US filers)
# is authoritative where it exists; yfinance is the base layer that covers the
# TSX / TSX-V names SEC EDGAR does not.
DEFAULT_PRECEDENCE = {
    CAP_FIN: ["manual_override", "sec_edgar", "yfinance_fundamentals"],
}
DEFAULT_PROVIDERS = [
    {"name": "fred", "enabled": True, "params": {}},
    {"name": "sec_edgar", "enabled": True, "params": {}},
    {"name": "yfinance_fundamentals", "enabled": True, "params": {}},
    {"name": "manual_override", "enabled": True, "params": {}},
    {"name": "sentiment", "enabled": False, "params": {}},
]
# Canadian / foreign exchange suffixes — never resolved against SEC EDGAR (US only),
# both because they will not be found and to avoid matching a same-named US ticker.
FOREIGN_SUFFIXES = {"V", "TO", "CN", "NE", "AX", "L", "HK", "SS", "SZ", "TSX", "TSXV"}


# --------------------------------------------------------------------------- #
#  Small numeric / serialization helpers
# --------------------------------------------------------------------------- #
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _to_float(x: Any) -> Optional[float]:
    """Best-effort float, returning None for missing / non-finite / unparseable."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _usable(v: Any) -> bool:
    """A value worth merging — not None and not a non-finite float."""
    if v is None:
        return False
    if isinstance(v, float) and not math.isfinite(v):
        return False
    return True


def _json_default(o: Any) -> str:
    return str(o)


def _load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load config %s: %s — using built-in defaults", path, exc)
        return {}


# --------------------------------------------------------------------------- #
#  HTTP helpers — the single network boundary (patched wholesale in tests).
# --------------------------------------------------------------------------- #
def _http_get_text(url: str, *, timeout: float = 15.0, user_agent: str = DEFAULT_USER_AGENT) -> Optional[str]:
    if requests is None:
        logger.debug("requests unavailable; cannot GET %s", url)
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        logger.warning("GET %s -> HTTP %s", url, resp.status_code)
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
    return None


def _http_get_json(url: str, *, timeout: float = 15.0, user_agent: str = DEFAULT_USER_AGENT) -> Optional[dict]:
    if requests is None:
        logger.debug("requests unavailable; cannot GET %s", url)
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent, "Accept": "application/json"}, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("GET %s -> HTTP %s", url, resp.status_code)
    except Exception as exc:
        logger.warning("GET %s failed: %s", url, exc)
    return None


def _parse_fred_csv(text: Optional[str], series_id: Optional[str] = None) -> Optional[float]:
    """Return the latest non-missing observation from a FRED ``fredgraph.csv`` body.
    FRED encodes a missing value as a literal ``.`` — those rows are skipped."""
    if not text:
        return None
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return None
    header = rows[0]
    if series_id and series_id in header:
        val_idx = header.index(series_id)
    else:
        val_idx = 1 if len(header) >= 2 else 0
    latest: Optional[float] = None
    for row in rows[1:]:
        if len(row) <= val_idx:
            continue
        v = _to_float(row[val_idx])
        if v is not None:
            latest = v
    return latest


# --------------------------------------------------------------------------- #
#  Provider registry (extensibility core)
# --------------------------------------------------------------------------- #
ADAPTER_REGISTRY: dict[str, type["BaseAdapter"]] = {}


def register_adapter(name: str):
    """Class decorator: register an adapter under ``name`` for config-driven wiring."""
    def _decorator(cls: type["BaseAdapter"]) -> type["BaseAdapter"]:
        cls.name = name
        ADAPTER_REGISTRY[name] = cls
        return cls
    return _decorator


class BaseAdapter(ABC):
    """Uniform, drop-in provider contract.

    Subclasses declare a registry ``name`` (via :func:`register_adapter`) and the
    ``provides`` capability tags they emit, implement :meth:`from_config` and
    :meth:`fetch`. ``fetch`` returns a *fragment*::

        {"provider": <name>, "fragments": {<capability>: <payload>}}

    where the ``macro`` payload is a flat ``{field: value}`` dict and per-ticker
    capabilities (``financials`` / ``comps`` / ``conviction_signals``) are keyed
    ``{ticker: {field: value}}``.
    """

    name: str = "base"
    provides: tuple = ()

    @classmethod
    def from_config(cls, params: dict) -> "BaseAdapter":
        return cls()

    @abstractmethod
    def fetch(self, tickers: list[str]) -> dict:
        ...

    def is_available(self) -> bool:
        return True


# --------------------------------------------------------------------------- #
#  Macro — FRED (keyless CSV endpoint, proven in engine.py)
# --------------------------------------------------------------------------- #
@register_adapter("fred")
class FredMacroAdapter(BaseAdapter):
    provides = (CAP_MACRO,)

    def __init__(self, series_map: Optional[dict] = None, *,
                 api_key_file: str = "FRED_API_KEY", timeout: float = 15.0) -> None:
        self.series_map = dict(series_map or DEFAULT_FRED_SERIES)
        self.api_key_file = api_key_file
        self.timeout = timeout

    @classmethod
    def from_config(cls, params: dict) -> "FredMacroAdapter":
        return cls(params.get("series_map"),
                   api_key_file=params.get("api_key_file", "FRED_API_KEY"),
                   timeout=params.get("timeout", 15.0))

    def fetch_series(self, series_id: str) -> Optional[float]:
        text = _http_get_text(FRED_CSV_URL.format(series_id=series_id), timeout=self.timeout)
        return _parse_fred_csv(text, series_id)

    def fetch(self, tickers: Optional[list[str]] = None) -> dict:
        macro: dict[str, float] = {}
        for field, series_id in self.series_map.items():
            try:
                value = self.fetch_series(series_id)
            except Exception as exc:
                logger.warning("FRED fetch failed for %s (%s): %s", field, series_id, exc)
                value = None
            if _usable(value):
                macro[field] = value
        return {"provider": self.name, "fragments": ({CAP_MACRO: macro} if macro else {})}


# --------------------------------------------------------------------------- #
#  Fundamentals — SEC EDGAR CompanyFacts (US filers only)
# --------------------------------------------------------------------------- #
@register_adapter("sec_edgar")
class SecEdgarAdapter(BaseAdapter):
    provides = (CAP_FIN,)

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT,
                 ticker_cik_map: Optional[dict] = None, timeout: float = 15.0) -> None:
        self.user_agent = user_agent
        self.ticker_cik_map = dict(ticker_cik_map or {})
        self.timeout = timeout
        self._cik_index: Optional[dict] = None

    @classmethod
    def from_config(cls, params: dict) -> "SecEdgarAdapter":
        return cls(user_agent=params.get("user_agent", DEFAULT_USER_AGENT),
                   ticker_cik_map=params.get("ticker_cik_map"),
                   timeout=params.get("timeout", 15.0))

    def _load_cik_index(self) -> dict:
        if self._cik_index is not None:
            return self._cik_index
        data = _http_get_json(SEC_TICKERS_URL, timeout=self.timeout, user_agent=self.user_agent) or {}
        index: dict[str, int] = {}
        rows = data.values() if isinstance(data, dict) else []
        for row in rows:
            ticker = str(row.get("ticker", "")).upper()
            cik = row.get("cik_str")
            if ticker and cik is not None:
                index[ticker] = int(cik)
        self._cik_index = index
        return index

    def resolve_cik(self, ticker: str) -> Optional[str]:
        t = ticker.upper()
        for key, cik in self.ticker_cik_map.items():       # explicit override wins
            if key.upper() == t:
                return str(cik)
        if "." in t:
            base, suffix = t.rsplit(".", 1)
            if suffix in FOREIGN_SUFFIXES:                 # not a US filer — skip
                return None
            t = base
        cik = self._load_cik_index().get(t)
        return str(cik) if cik is not None else None

    def fetch_company_facts(self, cik: str) -> Optional[dict]:
        try:
            cik_int = int(cik)
        except (TypeError, ValueError):
            return None
        return _http_get_json(SEC_FACTS_URL.format(cik=cik_int),
                              timeout=self.timeout, user_agent=self.user_agent)

    @staticmethod
    def extract_us_gaap(facts: dict, tag: str) -> list:
        """Return ``[(end_date, value, form), ...]`` (ascending by end) for a us-gaap
        tag, choosing the unit with the most observations."""
        node = ((facts or {}).get("facts", {}).get("us-gaap", {}) or {}).get(tag)
        if not node:
            return []
        best: list = []
        for _unit, points in (node.get("units", {}) or {}).items():
            rows = []
            for p in points:
                end, val = p.get("end"), _to_float(p.get("val"))
                if end is None or val is None:
                    continue
                rows.append((end, val, p.get("form")))
            if len(rows) > len(best):
                best = rows
        best.sort(key=lambda r: r[0])
        return best

    def fetch(self, tickers: list[str]) -> dict:
        out: dict[str, dict] = {}
        for ticker in tickers:
            try:
                cik = self.resolve_cik(ticker)
            except Exception as exc:
                logger.warning("CIK resolve failed for %s: %s", ticker, exc)
                cik = None
            if not cik:
                logger.debug("%s: no SEC CIK (non-US filer or unlisted) — deferring to fallback", ticker)
                continue
            try:
                facts = self.fetch_company_facts(cik)
            except Exception as exc:
                logger.warning("SEC companyfacts failed for %s (CIK %s): %s", ticker, cik, exc)
                facts = None
            if not facts:
                continue
            fin = FundamentalsMapper.from_company_facts(facts, extractor=self.extract_us_gaap)
            if fin:
                out[ticker] = fin
        return {"provider": self.name, "fragments": ({CAP_FIN: out} if out else {})}


# --------------------------------------------------------------------------- #
#  Fundamentals — yfinance (covers TSX / TSX-V + US cross-check)
# --------------------------------------------------------------------------- #
@register_adapter("yfinance_fundamentals")
class YFinanceFundamentalsAdapter(BaseAdapter):
    provides = (CAP_FIN,)

    def __init__(self, *, timeout: float = 15.0) -> None:
        self.timeout = timeout

    @classmethod
    def from_config(cls, params: dict) -> "YFinanceFundamentalsAdapter":
        return cls(timeout=params.get("timeout", 15.0))

    def is_available(self) -> bool:
        return _import_yfinance() is not None

    def fetch_financials(self, ticker: str) -> dict:
        yf = _import_yfinance()
        if yf is None:
            return {}
        out: dict[str, float] = {}
        try:
            info = getattr(yf.Ticker(ticker), "info", None) or {}
            for field, key in (("cash", "totalCash"), ("shares_t0", "sharesOutstanding"),
                               ("ebitda", "ebitda"), ("net_debt", "totalDebt")):
                v = _to_float(info.get(key))
                if v is not None:
                    out[field] = v
            ocf = _to_float(info.get("operatingCashflow"))
            if ocf is not None:
                out["curr_burn"] = abs(ocf) if ocf < 0 else 0.0
                if ocf < 0:
                    out["monthly_burn"] = abs(ocf) / 12.0
        except Exception as exc:
            logger.warning("yfinance fundamentals failed for %s: %s", ticker, exc)
        return out

    def fetch(self, tickers: list[str]) -> dict:
        out: dict[str, dict] = {}
        for ticker in tickers:
            fin = self.fetch_financials(ticker)
            if fin:
                out[ticker] = fin
        return {"provider": self.name, "fragments": ({CAP_FIN: out} if out else {})}


# --------------------------------------------------------------------------- #
#  Manual analyst overrides (offline CSV, highest precedence)
# --------------------------------------------------------------------------- #
@register_adapter("manual_override")
class ManualOverrideAdapter(BaseAdapter):
    provides = (CAP_FIN, CAP_COMPS, CAP_CONV)

    def __init__(self, *, path: str = "data/manual_overrides.csv") -> None:
        self.path = path

    @classmethod
    def from_config(cls, params: dict) -> "ManualOverrideAdapter":
        return cls(path=params.get("path", "data/manual_overrides.csv"))

    def _read_rows(self) -> list:
        try:
            with open(self.path, newline="") as fh:
                return list(csv.DictReader(fh))
        except OSError:
            return []

    def fetch(self, tickers: list[str]) -> dict:
        wanted = set(tickers)
        fragments: dict[str, dict] = {}
        for row in self._read_rows():
            ticker = (row.get("ticker") or "").strip()
            capability = (row.get("capability") or "").strip()
            field = (row.get("field") or "").strip()
            if not ticker or ticker.startswith("#") or not capability or not field:
                continue
            if ticker not in wanted:
                continue
            raw = row.get("value", "")
            value = _to_float(raw)
            if value is None:
                value = raw.strip() if isinstance(raw, str) else raw
            fragments.setdefault(capability, {}).setdefault(ticker, {})[field] = value
        return {"provider": self.name, "fragments": fragments}


# --------------------------------------------------------------------------- #
#  Catalysts — Phase 8: real-world junior-miner events (drill / financing / permitting)
# --------------------------------------------------------------------------- #
@register_adapter("catalyst_manual")
class CatalystManualAdapter(BaseAdapter):
    """Analyst-editable catalyst source: a CSV of events (same spirit as
    ``manual_override``). Columns: ticker,date,type,headline,impact,magnitude,
    share_change_pct,stage_to,p_discovery_delta. Missing file -> no events (graceful).
    Numeric fields are coerced; unknown columns are ignored. This is the dependency-free
    base layer; a future ``CatalystNewsAdapter`` (RSS/news API) can register alongside it."""

    provides = (CAP_CATALYSTS,)
    _NUM = ("impact", "magnitude", "share_change_pct", "p_discovery_delta")

    def __init__(self, *, path: str = "data/catalysts.csv") -> None:
        self.path = path

    @classmethod
    def from_config(cls, params: dict) -> "CatalystManualAdapter":
        return cls(path=params.get("path", "data/catalysts.csv"))

    def is_available(self) -> bool:
        return os.path.exists(self.path)

    def fetch(self, tickers: list[str]) -> dict:
        wanted = set(tickers)
        events: list[dict] = []
        try:
            with open(self.path, newline="") as fh:
                rows = list(csv.DictReader(fh))
        except OSError:
            rows = []
        for row in rows:
            ticker = (row.get("ticker") or "").strip()
            if not ticker or ticker.startswith("#") or ticker not in wanted:
                continue
            ev: dict = {"ticker": ticker}
            for k, v in row.items():
                if k in (None, "ticker") or v is None or str(v).strip() == "":
                    continue
                ev[k] = _to_float(v) if k in self._NUM else str(v).strip()
            if ev.get("type"):
                events.append(ev)
        return {"provider": self.name, "fragments": ({CAP_CATALYSTS: {"events": events}} if events else {})}


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: Optional[str]) -> str:
    """Sanitize a feed fragment to plain text. Prefers BeautifulSoup (robust against malformed
    markup / scripts); falls back to a defensive regex strip when bs4 is unavailable."""
    if not s:
        return ""
    try:
        from bs4 import BeautifulSoup  # type: ignore
        return BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    except Exception:
        return _TAG_RE.sub("", s).replace("&amp;", "&").replace("&#39;", "'").replace("&nbsp;", " ").strip()


def _parse_feed_entries(text: Optional[str]) -> list[dict]:
    """Tolerant RSS 2.0 / Atom parse, returning [{title, link, summary, published}].
    Parser precedence (best practice): ``feedparser`` -> ``fastfeedparser`` -> stdlib
    ElementTree. Each tier is defensive so a malformed feed or missing library degrades to the
    next without raising."""
    if not text:
        return []

    def _from_lib(entries) -> list[dict]:
        out = []
        for e in entries:
            get = (lambda k: e.get(k) if isinstance(e, dict) else getattr(e, k, None))
            out.append({
                "title": _strip_html(get("title") or ""),
                "link": (get("link") or "") or "",
                "summary": _strip_html(get("summary") or get("description") or get("content") or ""),
                "published": get("published") or get("updated") or get("pubDate") or get("date"),
            })
        return out

    for libname in ("feedparser", "fastfeedparser"):                # preferred tolerant parsers
        try:
            lib = __import__(libname)
            d = lib.parse(text)
            entries = getattr(d, "entries", None) or (d.get("entries") if isinstance(d, dict) else None)
            if entries:
                return _from_lib(entries)
        except Exception:
            continue

    import xml.etree.ElementTree as ET                              # final fallback: stdlib
    out: list[dict] = []
    try:
        root = ET.fromstring(text.strip())
    except Exception:
        return out

    def tag(el):
        return el.tag.split("}")[-1].lower()

    for el in root.iter():
        if tag(el) not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "summary": "", "published": None}
        for ch in list(el):
            t = tag(ch)
            if t == "title":
                rec["title"] = _strip_html(ch.text)
            elif t == "link":
                rec["link"] = (ch.text or ch.attrib.get("href") or "").strip()
            elif t in ("description", "summary", "content"):
                rec["summary"] = _strip_html(ch.text)
            elif t in ("pubdate", "published", "updated", "date"):
                rec["published"] = (ch.text or "").strip()
        if rec["title"]:
            out.append(rec)
    return out


def _normalize_pub_date(s: Optional[str]) -> Optional[str]:
    """Best-effort RFC-822 / ISO date -> ISO 'YYYY-MM-DD'. None on failure (graceful)."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


@register_adapter("rss_news")
class RssNewsAdapter(BaseAdapter):
    """SECONDARY catalyst source (broad coverage / speed): aggregates company + mining-news RSS
    feeds, classifies each headline (drill / financing / permitting / resource / catalyst), matches
    it to a portfolio ticker via alias map, dedupes by link, and tags low trust so structured
    filings win on conflict. Graceful: no network / no entries / classifier missing -> []."""

    provides = (CAP_CATALYSTS,)

    def __init__(self, *, feeds: Optional[list] = None, aliases: Optional[dict] = None,
                 trust: int = 1, timeout: float = 12.0, min_relevance: float = 0.5,
                 min_title_len: int = 6) -> None:
        self.feeds = feeds or []
        self.aliases = aliases or {}
        self.trust = trust
        self.timeout = timeout
        self.min_relevance = min_relevance
        self.min_title_len = min_title_len

    @classmethod
    def from_config(cls, params: dict) -> "RssNewsAdapter":
        return cls(feeds=params.get("feeds", []), aliases=params.get("ticker_aliases", {}),
                   trust=int(params.get("trust", 1)), timeout=float(params.get("timeout", 12.0)),
                   min_relevance=float(params.get("min_relevance", 0.5)),
                   min_title_len=int(params.get("min_title_len", 6)))

    def is_available(self) -> bool:
        return bool(self.feeds) and classify_headline is not None

    def fetch(self, tickers: list[str]) -> dict:
        if not self.is_available():
            return {"provider": self.name, "fragments": {}}
        wanted = set(tickers)
        events: list[dict] = []
        for feed in self.feeds:
            url = feed.get("url") if isinstance(feed, dict) else feed
            hint = feed.get("ticker") if isinstance(feed, dict) else None
            text = _http_get_text(url, timeout=self.timeout) if url else None
            for entry in _parse_feed_entries(text):
                # NO FABRICATION: require an exact, usable source title or drop the item.
                title = clean_title(entry.get("title"))
                if len(title) < self.min_title_len:
                    continue
                # Attribution: a per-feed company hint is trusted (relevance 1.0); otherwise score
                # the match and DROP weak/generic ones (generic sector news stays unattributed).
                if hint:
                    tkr, rel = hint, 1.0
                else:
                    tkr, rel = attribute(f"{title} {entry.get('summary', '')}", self.aliases)
                if tkr not in wanted or rel < self.min_relevance:
                    continue
                ev = classify_headline(title, entry.get("summary", ""))
                ev["headline"] = title                     # exact source title, never rewritten
                ev.update({"ticker": tkr, "relevance": round(rel, 2),
                           "date": _normalize_pub_date(entry.get("published")),
                           "link": entry.get("link") or "", "_source": "rss", "_trust": self.trust})
                events.append(ev)
        events = dedupe_events(events) if dedupe_events else events
        return {"provider": self.name, "fragments": ({CAP_CATALYSTS: {"events": events}} if events else {})}


@register_adapter("edgar_filings")
class EdgarFilingsAdapter(BaseAdapter):
    """PRIMARY catalyst source (authoritative) for US filers: data.sec.gov recent submissions.
    Maps material forms -> event types (8-K -> catalyst, S-1/424B/F-1 -> financing/dilution).
    Skips foreign-suffixed tickers (.V/.TO) — those are SEDAR+ (see SedarFilingsAdapter). High trust
    so it wins over RSS on the forensic-relevant types. Graceful when offline / not a US filer."""

    provides = (CAP_CATALYSTS,)
    _FORM_MAP = {
        "8-K": ("catalyst", 0.2, 0.4), "6-K": ("catalyst", 0.2, 0.4),
        "S-1": ("financing", -0.4, 0.6), "F-1": ("financing", -0.4, 0.6),
        "424B": ("financing", -0.45, 0.7), "424B5": ("financing", -0.45, 0.7),
        "S-3": ("financing", -0.3, 0.5),
    }

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT, trust: int = 3,
                 max_filings: int = 12, timeout: float = 15.0) -> None:
        self.user_agent = user_agent
        self.trust = trust
        self.max_filings = max_filings
        self.timeout = timeout
        self._sec = SecEdgarAdapter(user_agent=user_agent)   # reuse CIK resolution

    @classmethod
    def from_config(cls, params: dict) -> "EdgarFilingsAdapter":
        return cls(user_agent=params.get("user_agent", DEFAULT_USER_AGENT),
                   trust=int(params.get("trust", 3)), max_filings=int(params.get("max_filings", 12)))

    def fetch(self, tickers: list[str]) -> dict:
        events: list[dict] = []
        for ticker in tickers:
            cik = None
            try:
                cik = self._sec.resolve_cik(ticker)          # skips .V/.TO foreign suffixes
            except Exception:
                cik = None
            if not cik:
                continue
            url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
            data = _http_get_json(url, timeout=self.timeout, user_agent=self.user_agent)
            recent = (((data or {}).get("filings") or {}).get("recent") or {}) if data else {}
            forms = recent.get("form", []) or []
            dates = recent.get("filingDate", []) or []
            descs = recent.get("primaryDocDescription", []) or []
            for i, form in enumerate(forms[: self.max_filings]):
                key = next((k for k in self._FORM_MAP if str(form).upper().startswith(k)), None)
                if not key:
                    continue
                etype, impact, mag = self._FORM_MAP[key]
                # Headline = the EXACT filing description (the source's own text). The form code is a
                # short, factual prefix from the same record; if there is no description, discard
                # rather than fabricate a headline. (CIK resolution already guarantees attribution.)
                desc = (clean_title(descs[i]) if i < len(descs) else "")
                if not desc:
                    continue
                ev = {"ticker": ticker, "type": etype, "impact": impact, "magnitude": mag,
                      "headline": f"[{form}] {desc}", "form": str(form), "relevance": 1.0,
                      "date": dates[i] if i < len(dates) else None,
                      "_source": "edgar", "_trust": self.trust}
                events.append(ev)
        return {"provider": self.name, "fragments": ({CAP_CATALYSTS: {"events": events}} if events else {})}


@register_adapter("sedar_filings")
class SedarFilingsAdapter(BaseAdapter):
    """PRIMARY catalyst source (authoritative) for Canadian filers (SEDAR+). SEDAR+ exposes no
    stable free/keyless API, so this ships as a graceful, pluggable stub: ``is_available`` is False
    unless a ``params.endpoint`` (a proxy/mirror the operator supplies) is configured. The Canadian
    barbell names (AGA.V / URC.TO / GMX.TO) therefore rely on the RSS source for breadth until a
    SEDAR+ access path exists — documented in PHASE8_CATALYSTS.md. Trust is high when active."""

    provides = (CAP_CATALYSTS,)

    def __init__(self, *, endpoint: Optional[str] = None, trust: int = 3, timeout: float = 15.0) -> None:
        self.endpoint = endpoint
        self.trust = trust
        self.timeout = timeout

    @classmethod
    def from_config(cls, params: dict) -> "SedarFilingsAdapter":
        return cls(endpoint=params.get("endpoint"), trust=int(params.get("trust", 3)))

    def is_available(self) -> bool:
        return bool(self.endpoint)                           # no free public API -> off unless configured

    def fetch(self, tickers: list[str]) -> dict:
        if not self.is_available():
            return {"provider": self.name, "fragments": {}}
        events: list[dict] = []
        for ticker in tickers:
            data = _http_get_json(f"{self.endpoint.rstrip('/')}/{ticker}", timeout=self.timeout)
            for f in (data or {}).get("filings", []) if isinstance(data, dict) else []:
                if classify_headline is None:
                    break
                ev = classify_headline(str(f.get("title", "")), str(f.get("summary", "")))
                ev.update({"ticker": ticker, "date": f.get("date"),
                           "link": f.get("link", ""), "_source": "sedar", "_trust": self.trust})
                events.append(ev)
        return {"provider": self.name, "fragments": ({CAP_CATALYSTS: {"events": events}} if events else {})}


#: Authoritative types: structured filings supersede RSS for these (forensic-gate relevant).
_AUTHORITATIVE_TYPES = ("financing", "permitting", "resource_expansion")


def _collapse_by_source_precedence(events: list) -> list:
    """Second dedup pass realizing the primary/fallback model: for forensic-relevant types, keep
    only the highest-trust event per (ticker, type, year-month) so an authoritative SEC/SEDAR
    filing supersedes an RSS rumor of the same raise/permit; other types pass through."""
    keep: dict = {}
    passthrough: list = []
    for ev in events:
        if ev.get("type") in _AUTHORITATIVE_TYPES:
            ym = (ev.get("date") or "")[:7]
            key = (ev.get("ticker"), ev.get("type"), ym)
            cur = keep.get(key)
            if cur is None or ev.get("_trust", 0) > cur.get("_trust", 0):
                keep[key] = ev
        else:
            passthrough.append(ev)
    return list(keep.values()) + passthrough


def write_catalyst_feed(events: list, *, path: str = "data/catalysts.json",
                        source: str = "ingestion", ttl_seconds: float = 86400) -> dict:
    """Persist a catalyst-feed envelope (atomic), the canonical feed ``catalyst_engine``
    reads. Mirrors :class:`IngestionCache` semantics."""
    # Strip internal bookkeeping (_source/_trust) and drop empty fields before persisting.
    clean = []
    for ev in (events or []):
        if isinstance(ev, dict):
            clean.append({k: v for k, v in ev.items() if not k.startswith("_") and v is not None})
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.fromtimestamp(time.time()).isoformat(timespec="seconds"),
        "ttl_seconds": ttl_seconds,
        "source": source,
        "events": clean,
    }
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(envelope, fh, indent=2, default=_json_default)
    os.replace(tmp, path)
    return envelope


def load_attribution_overrides(path: str) -> list:
    """Load the high-priority manual attribution-override CSV. Columns: ``pattern`` (case-insensitive
    substring of an item's link or headline) and ``ticker`` (the correct ticker, or ``DROP`` to
    discard the item). Lets an analyst permanently correct or kill a persistent misattribution.
    Missing file -> [] (graceful)."""
    rows = []
    try:
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                pat = (r.get("pattern") or "").strip().lower()
                tkr = (r.get("ticker") or "").strip()
                if pat and not pat.startswith("#"):
                    rows.append((pat, tkr))
    except OSError:
        pass
    return rows


def _apply_attribution_overrides(events: list, overrides: list) -> list:
    """Apply manual overrides to auto-feed events (analyst ``catalyst_manual`` events are left as-is):
    a matching pattern either reassigns the ticker or drops the item (``DROP``/empty)."""
    if not overrides:
        return events
    out = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("_source") == "manual":
            out.append(ev); continue
        hay = f"{ev.get('link', '')} {ev.get('headline', '')}".lower()
        hit = next((tkr for pat, tkr in overrides if pat in hay), None)
        if hit is None:
            out.append(ev)
        elif hit.upper() in ("DROP", "", "NONE"):
            continue                                        # analyst killed this misattributed item
        else:
            ev = dict(ev); ev["ticker"] = hit; ev["_override"] = True
            out.append(ev)
    return out


def refresh_catalyst_feed(config: Optional[dict] = None, *, tickers: Optional[list] = None,
                          path: Optional[str] = None) -> dict:
    """Run the configured catalyst providers and (re)write the canonical feed. If no provider
    yields events, the existing feed is left untouched (graceful no-op) so a missing CSV never
    wipes a hand-seeded feed. Returns a small status dict."""
    cfg = (config or {}).get("catalysts", {}) if config else {}
    feed_path = path or cfg.get("feed_path", "data/catalysts.json")
    tickers = tickers or (config or {}).get("portfolio_metadata") and \
        [t for t in (config or {})["portfolio_metadata"] if not str(t).startswith("_")] or DEFAULT_TICKERS
    specs = cfg.get("providers", [{"name": "catalyst_manual", "enabled": True, "params": {}}])
    events: list = []
    used = []
    # Providers run in config order (primary filings first, then RSS); each event is trust-tagged
    # by its adapter so dedup keeps the authoritative copy.
    for spec in specs:
        if not spec.get("enabled", True):
            continue
        cls = ADAPTER_REGISTRY.get(spec.get("name"))
        if cls is None or CAP_CATALYSTS not in getattr(cls, "provides", ()):
            continue
        try:
            adapter = cls.from_config(spec.get("params", {}))
            if not adapter.is_available():
                continue
            frag = adapter.fetch(tickers).get("fragments", {}).get(CAP_CATALYSTS, {})
            got = frag.get("events", [])
            if got:
                events.extend(got)
                used.append(spec.get("name"))
        except Exception as e:                              # one bad provider never breaks refresh
            logger.warning("catalyst provider %s failed (non-fatal): %s", spec.get("name"), e)
    if not events:
        return {"status": "noop", "reason": "no provider events; existing feed preserved",
                "path": feed_path, "providers": used}
    # High-priority manual attribution overrides (reassign or DROP persistent misattributions).
    overrides = load_attribution_overrides(cfg.get("manual_override_path", "data/catalyst_overrides.csv"))
    events = _apply_attribution_overrides(events, overrides)
    # Dedup (exact link, else ticker+normalized-headline+date; higher trust wins) then collapse
    # authoritative types so a structured filing supersedes an RSS rumor of the same event.
    if dedupe_events is not None:
        events = dedupe_events(events)
    events = _collapse_by_source_precedence(events)
    events.sort(key=lambda e: (e.get("date") or ""), reverse=True)
    write_catalyst_feed(events, path=feed_path, source="+".join(used) or "ingestion")
    return {"status": "written", "count": len(events), "path": feed_path,
            "providers": used, "overrides_applied": len(overrides)}


# --------------------------------------------------------------------------- #
#  Sentiment — OPT-IN, best-effort, structured sources only (no HTML scraping)
# --------------------------------------------------------------------------- #
@register_adapter("sentiment")
class SentimentAdapter(BaseAdapter):
    provides = (CAP_CONV,)
    FIELDS = ("insider_net_buying", "catalyst_momentum", "institutional_flow", "short_interest_pressure")

    def __init__(self, *, enabled: bool = False, timeout: float = 10.0) -> None:
        self.enabled = enabled
        self.timeout = timeout

    @classmethod
    def from_config(cls, params: dict) -> "SentimentAdapter":
        # Built only when its provider spec is enabled, so default to active here;
        # an explicit params {"enabled": false} still wins.
        return cls(enabled=bool(params.get("enabled", True)), timeout=params.get("timeout", 10.0))

    def is_available(self) -> bool:
        return self.enabled

    def fetch_conviction(self, ticker: str) -> dict:
        """Best-effort conviction signals. No structured free source is wired by
        default, so this returns safe neutral defaults — override in a subclass or
        future provider to source from a structured/JSON endpoint."""
        return {field: 0.0 for field in self.FIELDS}

    def fetch(self, tickers: list[str]) -> dict:
        if not self.enabled:
            return {"provider": self.name, "fragments": {}}
        out: dict[str, dict] = {}
        for ticker in tickers:
            clamped: dict[str, float] = {}
            for key, value in (self.fetch_conviction(ticker) or {}).items():
                fv = _to_float(value)
                if fv is None:
                    continue
                lo = 0.0 if key == "short_interest_pressure" else -1.0
                clamped[key] = clamp(fv, lo, 1.0)
            if clamped:
                out[ticker] = clamped
        return {"provider": self.name, "fragments": ({CAP_CONV: out} if out else {})}


# --------------------------------------------------------------------------- #
#  Fundamental primitives (SEC/yfinance fields -> archetype-facing metrics)
# --------------------------------------------------------------------------- #
class FundamentalsMapper:
    @staticmethod
    def runway_months(cash: Any, monthly_burn: Any) -> Optional[float]:
        c, b = _to_float(cash), _to_float(monthly_burn)
        if c is None or b is None or b <= 0:
            return None
        return c / b

    @staticmethod
    def cash_burn_acceleration(curr_burn: Any, prev_burn: Any) -> Optional[float]:
        c, p = _to_float(curr_burn), _to_float(prev_burn)
        if c is None or p is None or p == 0:
            return None
        return (c - p) / abs(p)

    @staticmethod
    def dilution_velocity(shares_t0: Any, shares_t1: Any, periods: float = 1.0) -> Optional[float]:
        s0, s1 = _to_float(shares_t0), _to_float(shares_t1)
        if s0 is None or s1 is None or s1 == 0 or periods == 0:
            return None
        return (s0 - s1) / s1 / periods

    @staticmethod
    def from_company_facts(facts: dict, *, extractor=None) -> dict:
        """Map SEC CompanyFacts -> {cash, monthly_burn, curr_burn, prev_burn,
        shares_t0, shares_t1}. Operating cash flow < 0 is treated as a burn;
        annual (10-K) observations are preferred for burn and share counts."""
        extract = extractor or SecEdgarAdapter.extract_us_gaap
        out: dict[str, float] = {}

        cash = extract(facts, CASH_TAG)
        if cash:
            out["cash"] = cash[-1][1]

        ocf = extract(facts, OCF_TAG)
        annual_ocf = [r for r in ocf if r[2] == "10-K"] or ocf
        if annual_ocf:
            last = annual_ocf[-1][1]
            out["curr_burn"] = abs(last) if last < 0 else 0.0
            if last < 0:
                out["monthly_burn"] = abs(last) / 12.0
            if len(annual_ocf) >= 2:
                prev = annual_ocf[-2][1]
                out["prev_burn"] = abs(prev) if prev < 0 else 0.0

        shares = extract(facts, SHARES_TAG)
        annual_sh = [r for r in shares if r[2] == "10-K"] or shares
        if annual_sh:
            out["shares_t0"] = annual_sh[-1][1]
            if len(annual_sh) >= 2:
                out["shares_t1"] = annual_sh[-2][1]
        return out


# --------------------------------------------------------------------------- #
#  Capability merge (generic; FundamentalsResolver = precedence over "financials")
# --------------------------------------------------------------------------- #
def merge_by_capability(fragments: list, *, precedence: Optional[dict] = None) -> dict:
    """Compose adapter fragments into ``{"macro": {...}, "tickers": {t: {cap: {...}}}}``.

    Within each capability, fields are resolved at field granularity by provider
    precedence (highest first); the first provider that supplies a usable value
    wins. ``precedence`` maps a capability -> ordered provider list; capabilities
    without an entry fall back to fragment (insertion) order.
    """
    precedence = precedence or {}
    by_provider = {f.get("provider"): f.get("fragments", {}) or {} for f in fragments}
    insertion_order = [f.get("provider") for f in fragments]

    capabilities: set = set()
    for frags in by_provider.values():
        capabilities.update(frags.keys())

    merged_macro: dict = {}
    merged_tickers: dict = {}

    for cap in capabilities:
        order = list(precedence.get(cap) or insertion_order)
        for prov in insertion_order:                       # append any not explicitly ordered
            if prov not in order:
                order.append(prov)
        providers = [p for p in order if cap in by_provider.get(p, {})]

        if cap == CAP_MACRO:
            for prov in providers:                         # highest first; setdefault keeps it
                for key, value in by_provider[prov][cap].items():
                    if _usable(value):
                        merged_macro.setdefault(key, value)
        else:
            for prov in providers:
                for ticker, fields in by_provider[prov][cap].items():
                    dst = merged_tickers.setdefault(ticker, {}).setdefault(cap, {})
                    for key, value in fields.items():
                        if _usable(value):
                            dst.setdefault(key, value)

    return {"macro": merged_macro, "tickers": merged_tickers}


# --------------------------------------------------------------------------- #
#  Schema mapper — emit data_payload dicts mirroring router.get_valuation
# --------------------------------------------------------------------------- #
class PayloadMapper:
    def __init__(self, config: dict) -> None:
        self.config = config or {}

    def _currency(self, ticker: str) -> str:
        bv = self.config.get("ballast_valuation", {}).get(ticker, {})
        if bv.get("currency"):
            return bv["currency"]
        meta = self.config.get("portfolio_metadata", {}).get(ticker, {})
        if meta.get("currency"):
            return meta["currency"]
        return "CAD" if ticker.upper().endswith((".V", ".TO", ".CN")) else "USD"

    def build_ticker_payload(self, ticker: str, tdata: dict, macro_block: dict) -> dict:
        fin = dict(tdata.get(CAP_FIN, {}) or {})
        comps = dict(tdata.get(CAP_COMPS, {}) or {})
        conv = dict(tdata.get(CAP_CONV, {}) or {})

        payload: dict = {
            "currency": self._currency(ticker),
            "macro": dict(macro_block or {}),
            "comps": comps,
            "financials": fin,
        }
        if conv:
            payload[CAP_CONV] = conv

        shares = fin.get("shares_t0")
        if shares is None and ticker == "AGA.V":
            shares = self.config.get("aga_shares_out")
        if _usable(shares):
            payload["shares_out"] = shares

        # Derived primitives — surfaced for the cockpit; archetypes ignore unknown keys.
        runway = FundamentalsMapper.runway_months(fin.get("cash"), fin.get("monthly_burn"))
        if runway is not None:
            fin["runway_months"] = runway
        accel = FundamentalsMapper.cash_burn_acceleration(fin.get("curr_burn"), fin.get("prev_burn"))
        if accel is not None:
            fin["cash_burn_acceleration"] = accel
        dilution = FundamentalsMapper.dilution_velocity(fin.get("shares_t0"), fin.get("shares_t1"))
        if dilution is not None:
            fin["dilution_velocity"] = dilution

        return payload

    def build_all(self, tickers: list[str], merged: dict) -> dict:
        macro = dict(merged.get("macro", {}) or {})
        per_ticker = merged.get("tickers", {}) or {}
        out = {t: self.build_ticker_payload(t, per_ticker.get(t, {}), macro) for t in tickers}
        return {"macro": macro, "tickers": out}


# --------------------------------------------------------------------------- #
#  Cache (staleness-aware, atomic write; mirrors the .cache envelope convention)
# --------------------------------------------------------------------------- #
class IngestionCache:
    def __init__(self, path: str = DEFAULT_CACHE_PATH) -> None:
        self.path = path

    def write(self, data: dict, *, sources_meta: dict, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> dict:
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": time.time(),
            "ttl_seconds": ttl_seconds,
            "sources": sources_meta,
            "data": data,
        }
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp.{os.getpid()}"
        with open(tmp, "w") as fh:
            json.dump(envelope, fh, indent=2, default=_json_default)
        os.replace(tmp, self.path)                         # atomic
        return envelope

    def read(self) -> Optional[dict]:
        try:
            with open(self.path, "r") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def is_stale(envelope: dict, max_age_seconds: float) -> bool:
        if not isinstance(envelope, dict):
            return True
        generated_at = envelope.get("generated_at")
        if generated_at is None:
            return True
        return (time.time() - generated_at) > max_age_seconds


def load_ingestion_cache(path: str = DEFAULT_CACHE_PATH, *, max_age_seconds: Optional[float] = None) -> Optional[dict]:
    """Read the ingestion cache envelope for the engine. Returns ``None`` (graceful)
    when the file is missing, unreadable, or — if ``max_age_seconds`` is given —
    stale. The engine treats ``None`` as "rely on live feeds + ``_safe_leg``"."""
    envelope = IngestionCache(path).read()
    if envelope is None:
        logger.debug("ingestion cache missing/unreadable at %s", path)
        return None
    if max_age_seconds is not None and IngestionCache.is_stale(envelope, max_age_seconds):
        logger.warning("ingestion cache at %s is stale (> %ss); ignoring", path, max_age_seconds)
        return None
    return envelope


# --------------------------------------------------------------------------- #
#  Orchestrator
# --------------------------------------------------------------------------- #
class IngestionPipeline:
    def __init__(self, *, config: Optional[dict] = None, cache_path: str = DEFAULT_CACHE_PATH) -> None:
        self.config = config or {}
        ingestion_cfg = self.config.get("ingestion", {})
        self.cache_path = ingestion_cfg.get("cache_path", cache_path)
        self.ttl_seconds = ingestion_cfg.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        self.precedence = ingestion_cfg.get("capability_precedence", DEFAULT_PRECEDENCE)
        self.provider_specs = ingestion_cfg.get("providers", DEFAULT_PROVIDERS)
        self.mapper = PayloadMapper(self.config)
        self.cache = IngestionCache(self.cache_path)
        self.adapters = self._build_adapters(self.provider_specs)

    @classmethod
    def from_config(cls, config_path: str = DEFAULT_CONFIG_PATH, *,
                    cache_path: str = DEFAULT_CACHE_PATH) -> "IngestionPipeline":
        return cls(config=_load_config(config_path), cache_path=cache_path)

    @staticmethod
    def _build_adapters(specs: list) -> list:
        adapters = []
        for spec in specs:
            if not spec.get("enabled", True):
                continue
            name = spec.get("name")
            cls = ADAPTER_REGISTRY.get(name)
            if cls is None:
                logger.warning("Unknown ingestion provider %r — skipping", name)
                continue
            try:
                adapters.append(cls.from_config(spec.get("params", {})))
            except Exception as exc:
                logger.warning("Provider %r failed to initialize: %s", name, exc)
        return adapters

    def _default_tickers(self) -> list:
        return list(self.config.get("portfolio_metadata", {}).keys()) or list(DEFAULT_TICKERS)

    def run(self, tickers: Optional[list[str]] = None, *, providers: Optional[list[str]] = None) -> dict:
        tickers = list(tickers) if tickers else self._default_tickers()
        fragments: list = []
        sources_meta: dict = {}
        for adapter in self.adapters:
            if providers and adapter.name not in providers:
                continue
            fetched_at, status = time.time(), "ok"
            try:
                fragment = adapter.fetch(tickers)
                if not fragment.get("fragments"):
                    status = "empty"
                fragments.append(fragment)
            except Exception as exc:
                status = "failed"
                logger.warning("Provider %r fetch failed: %s", adapter.name, exc)
                fragments.append({"provider": adapter.name, "fragments": {}})
            sources_meta[adapter.name] = {"fetched_at": fetched_at, "status": status}

        merged = merge_by_capability(fragments, precedence=self.precedence)
        data = self.mapper.build_all(tickers, merged)
        self.cache.write(data, sources_meta=sources_meta, ttl_seconds=self.ttl_seconds)
        return {
            "written": self.cache_path,
            "tickers": tickers,
            "sources": sources_meta,
            "macro_keys": sorted(data.get("macro", {})),
            "ticker_count": len(data.get("tickers", {})),
        }

    def refresh(self, capability: str, tickers: Optional[list[str]] = None) -> dict:
        """Run only the providers that emit ``capability`` (e.g. 'macro')."""
        names = [a.name for a in self.adapters if capability in getattr(a, "provides", ())]
        return self.run(tickers, providers=names)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def _enable_sentiment(config: dict) -> None:
    providers = config.setdefault("ingestion", {}).setdefault("providers", list(DEFAULT_PROVIDERS))
    found = False
    for spec in providers:
        if spec.get("name") == "sentiment":
            spec["enabled"] = True
            spec.setdefault("params", {})["enabled"] = True
            found = True
    if not found:
        providers.append({"name": "sentiment", "enabled": True, "params": {"enabled": True}})


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 6 open-source ingestion pipeline.")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: portfolio_metadata).")
    parser.add_argument("--providers", help="Comma-separated provider names to run (default: all enabled).")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--cache-path", default=DEFAULT_CACHE_PATH)
    parser.add_argument("--enable-sentiment", action="store_true", help="Enable the opt-in sentiment provider.")
    parser.add_argument("--catalysts", action="store_true",
                        help="Phase 8: refresh the catalyst feed (data/catalysts.json) from catalyst providers and exit.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = _load_config(args.config)
    if args.enable_sentiment:
        _enable_sentiment(config)

    if args.catalysts:                                  # Phase 8: catalyst-feed refresh path
        tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
        print(json.dumps(refresh_catalyst_feed(config, tickers=tickers), indent=2, default=str))
        return 0

    pipeline = IngestionPipeline(config=config, cache_path=args.cache_path)
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    providers = [p.strip() for p in args.providers.split(",")] if args.providers else None
    summary = pipeline.run(tickers, providers=providers)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
