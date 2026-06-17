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

import datetime
import json
import os
import time
import urllib.parse
import urllib.request

_YH = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"
_YH_SERIES = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
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
            return {**e["data"], "cached": True, "stale": False,
                    "age_s": round(time.time() - e["ts"], 1)}
        try:
            d = _http_json(_YH.format(sym=urllib.parse.quote(ticker)))
            m = (((d.get("chart") or {}).get("result") or [{}])[0]).get("meta") or {}
            price = m.get("regularMarketPrice")
            if price is None:
                raise ValueError("no regularMarketPrice in chart meta")
            data = {"price": price, "currency": m.get("currency"),
                    "previous_close": m.get("chartPreviousClose") or m.get("previousClose")}
            self._cache[key] = {"ts": time.time(), "data": data}
            self._save()
            return {**data, "cached": False, "stale": False, "age_s": 0.0}
        except Exception:
            # explicit last-good fallback: an EXPIRED cache entry is better than nothing for the
            # cockpit, but only when it says so — stale:True + its age, never dressed as fresh.
            if e:
                return {**e["data"], "cached": True, "stale": True,
                        "age_s": round(time.time() - e.get("ts", 0), 1)}
            return None

    # ---- price-series momentum (regime proxy: uranium has no clean spot feed) ----
    def price_series(self, ticker: str, rng: str = "1mo", ttl: float = 21600.0):
        key = f"ser:{ticker}:{rng}"
        e = self._cache.get(key)
        if e and (time.time() - e.get("ts", 0)) < ttl:
            return e["data"]
        try:
            d = _http_json(_YH_SERIES.format(sym=urllib.parse.quote(ticker), rng=rng))
            res = (((d.get("chart") or {}).get("result") or [{}])[0])
            closes = [c for c in (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
                      if c is not None]
            if len(closes) < 2:
                return None
            self._cache[key] = {"ts": time.time(), "data": closes}
            self._save()
            return closes
        except Exception:
            return None

    def momentum(self, ticker: str, rng: str = "1mo", full_move: float = 0.10):
        """Normalized period return ∈ [-1,1]: a `full_move` (default ±10%) over the window = ±1."""
        s = self.price_series(ticker, rng)
        if not s or len(s) < 2 or not s[0]:
            return None
        ret = s[-1] / s[0] - 1.0
        return max(-1.0, min(1.0, round(ret / full_move, 3)))

    def uranium_momentum(self):
        """Uranium regime proxy, no clean U3O8 spot feed: Sprott Physical Uranium → miners ETFs."""
        for sym in ("U.UN.TO", "URNM", "URA"):
            m = self.momentum(sym)
            if m is not None:
                return {"value": m, "source": f"yahoo:{sym}"}
        return None

    # ---- the public snapshot: each field provenance-tagged, never faked ----
    def snapshot(self, ticker: str) -> dict:
        out: dict = {"ticker": ticker, "fields": {}, "sources": {}, "as_of": time.time()}

        def put(field, value, source):
            if value is not None and value != "":
                out["fields"][field] = value
                out["sources"][field] = source

        yq = self.yahoo_quote(ticker)
        yh_src = "yahoo (STALE cache)" if (yq or {}).get("stale") else "yahoo"
        fmp, fmp_src = None, "fmp"
        if self.fmp is not None:
            try:
                resp = self.fmp.profile(ticker) or {}
                fmp = resp.get("data") or None
                # propagate the FMP staleness envelope into provenance — budget-exhausted or
                # error-fallback data must never read as a fresh source in the snapshot.
                if resp.get("stale") or resp.get("budget_exhausted"):
                    fmp_src = "fmp (STALE cache)"
            except Exception:
                fmp = None

        if yq and yq.get("price") is not None:
            put("price", yq["price"], yh_src)
            put("currency", yq.get("currency"), yh_src)
            pc = yq.get("previous_close")
            if pc:
                put("change_pct", round((yq["price"] / pc - 1.0) * 100.0, 2), yh_src)
        elif fmp and fmp.get("price") is not None:
            put("price", fmp["price"], fmp_src)
            put("currency", fmp.get("currency"), fmp_src)
            put("change_pct", fmp.get("changePercentage"), fmp_src)

        if fmp:
            put("market_cap", fmp.get("marketCap"), fmp_src)
            put("beta", fmp.get("beta"), fmp_src)
            put("range_52w", fmp.get("range"), fmp_src)
            put("sector", fmp.get("sector"), fmp_src)
            put("exchange", fmp.get("exchange"), fmp_src)
            put("company_name", fmp.get("companyName"), fmp_src)
            if "change_pct" not in out["fields"]:
                put("change_pct", fmp.get("changePercentage"), fmp_src)
            mc, px = fmp.get("marketCap"), out["fields"].get("price")
            if mc and px:
                put("shares_out", round(mc / px), "derived(fmp mcap / price)")

        for field in ("price", "market_cap", "shares_out", "range_52w", "currency"):
            out["sources"].setdefault(field, "unavailable")
        return out


def resolve_freshness(*, daily_closes, intraday=None, last_good=None, today=None):
    """Pick the freshest TRUSTWORTHY current price for a holding, with provenance — the fix for the
    silent-stale price bug.

    The daily bulk bar lags a session and is frequently NaN on the latest day for an individual
    name, so taking ``df['Close'].dropna().iloc[-1]`` served a 1-2 day-old close as if it were live.
    Here the sources are tried in order and the result is FLAGGED, never silently presented as fresh:

      1. ``intraday`` — the live ``regularMarketPrice`` (always "today"); preferred because it is
         populated even when the daily bar is missing/NaN.
      2. the most recent daily close — FRESH only if its date == ``today``; otherwise returned but
         ``stale=True`` with its real ``as_of`` date (so the desk sees "as of <date>", not a frozen
         number dressed as live).
      3. ``last_good`` — the last cached good mark ({"price","as_of"}), returned ``stale=True``.

    ``daily_closes`` is a chronological list of ``(date, close)`` (NaN already dropped). Returns
    ``{price, as_of, stale, source}``; ``price`` is ``None`` only when nothing is available (honest
    absence — the caller decides whether to use a hardcoded last resort).
    """
    today = today or datetime.date.today()

    def _pos(x):
        try:
            f = float(x)
            return f == f and f not in (float("inf"), float("-inf")) and f > 0.0
        except (TypeError, ValueError):
            return False

    if _pos(intraday):
        return {"price": float(intraday), "as_of": today.isoformat(), "stale": False,
                "source": "yahoo:intraday"}

    if daily_closes:
        d, c = daily_closes[-1]
        if _pos(c):
            as_of = d.isoformat() if hasattr(d, "isoformat") else str(d)
            is_today = bool(hasattr(d, "isoformat") and d == today)
            return {"price": float(c), "as_of": as_of, "stale": not is_today,
                    "source": "yahoo:daily"}

    if last_good and _pos(last_good.get("price")):
        return {"price": float(last_good["price"]), "as_of": last_good.get("as_of"),
                "stale": True, "source": "cache:last-good"}

    return {"price": None, "as_of": None, "stale": True, "source": "unavailable"}
