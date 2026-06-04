"""
Provenance-aware, cache-first market-data resolver for CommodityEx.

Desk principles encoded here:
  * NO hardcoded values — if a field cannot be sourced it is simply absent and its source is
    recorded as "unavailable". Absence is honest; a fabricated default is not.
  * Source hierarchy: Yahoo (primary, direct HTTP — no yfinance dependency) → FMP free tier
    (secondary, via the engine-shared FMPClient cache). Filings-derived fundamentals
    (in-ground oz, AISC, NAV) are NOT here — they come from the agent web-search fallback,
    persisted in research_cache.py.
  * Minimal API calls — every field is served from a disk cache with a per-field TTL; a network
    call happens only on a cold/stale cache.

Every value carries provenance: results expose {fields, sources, as_of}. Stdlib only, so it is
import-light and unit-testable on its own; the engine consumes it as its market spine instead of
scattering yfinance/FMP calls (and hardcoded snapshots) through the codebase.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

_YH = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"
_UA = {"User-Agent": "Mozilla/5.0 (CommodityEx market-data resolver)"}


def _http_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (trusted finance hosts)
        return json.loads(r.read().decode("utf-8"))


class MarketData:
    """Cache-first resolver. Pass an FMPClient for the secondary tier (optional)."""

    def __init__(self, fmp=None, cache_path: str | None = None, price_ttl: float = 600.0):
        self.fmp = fmp
        self.price_ttl = price_ttl
        self.cache_path = cache_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "market_cache.json")
        self._cache = self._load()

    def _load(self) -> dict:
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    # ---- Yahoo (primary): live price + previous close (for the day move) ----
    def yahoo_quote(self, ticker: str) -> dict | None:
        key = f"yh:{ticker}"
        e = self._cache.get(key)
        if e and (time.time() - e.get("ts", 0)) < self.price_ttl:
            return {**e["data"], "cached": True, "age_s": round(time.time() - e["ts"], 1)}
        try:
            d = _http_json(_YH.format(sym=urllib.parse.quote(ticker)))
            m = (((d.get("chart") or {}).get("result") or [{}])[0]).get("meta") or {}
            price = m.get("regularMarketPrice")
            if price is None:
                return None
            data = {"price": price, "currency": m.get("currency"),
                    "previous_close": m.get("chartPreviousClose") or m.get("previousClose")}
            self._cache[key] = {"ts": time.time(), "data": data}
            self._save()
            return {**data, "cached": False, "age_s": 0.0}
        except Exception:
            return None

    # ---- the public snapshot: each field provenance-tagged, never faked ----
    def snapshot(self, ticker: str) -> dict:
        out: dict = {"ticker": ticker, "fields": {}, "sources": {}, "as_of": time.time()}

        def put(field, value, source):
            if value is not None and value != "":
                out["fields"][field] = value
                out["sources"][field] = source

        yq = self.yahoo_quote(ticker)
        fmp = None
        if self.fmp is not None:
            try:
                fmp = (self.fmp.profile(ticker) or {}).get("data") or None
            except Exception:
                fmp = None

        if yq and yq.get("price") is not None:
            put("price", yq["price"], "yahoo")
            put("currency", yq.get("currency"), "yahoo")
            pc = yq.get("previous_close")
            if pc:
                put("change_pct", round((yq["price"] / pc - 1.0) * 100.0, 2), "yahoo")
        elif fmp and fmp.get("price") is not None:
            put("price", fmp["price"], "fmp")
            put("currency", fmp.get("currency"), "fmp")
            put("change_pct", fmp.get("changePercentage"), "fmp")

        if fmp:
            put("market_cap", fmp.get("marketCap"), "fmp")
            put("beta", fmp.get("beta"), "fmp")
            put("range_52w", fmp.get("range"), "fmp")
            put("sector", fmp.get("sector"), "fmp")
            put("exchange", fmp.get("exchange"), "fmp")
            put("company_name", fmp.get("companyName"), "fmp")
            if "change_pct" not in out["fields"]:
                put("change_pct", fmp.get("changePercentage"), "fmp")
            mc, px = fmp.get("marketCap"), out["fields"].get("price")
            if mc and px:
                put("shares_out", round(mc / px), "derived(fmp mcap / price)")

        for field in ("price", "market_cap", "shares_out", "range_52w", "currency"):
            out["sources"].setdefault(field, "unavailable")
        return out
