"""
Price sources for the matrix (Forge-Matrix) — day-change % for the crawl, the bench, and the cards.

Two pluggable fetchers, both returning {ticker: {last, change_pct}}, cached, and DEGRADING to {} on any
failure (missing library / offline / unresolved microcap) so the renderer falls back to price-only:

  * yfinance_price_fetcher — handles TSX/TSX-V (.V / .TO), which is what the engine + the device's native
    system use. The reliable default for the Canadian book (incl. the microcaps). Slower.
  * finnhub_price_fetcher  — Finnhub's FREE /quote carries `dp` (day change %) directly; fast, but may
    not resolve TSX-V microcaps. Great for the liquid names. Needs FINNHUB_API_KEY.

Slow cadence by design (this is an ambient panel, not a trading feed): both cache per-ticker. The
orchestrator injects one of these as its price_fetcher.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

_YF_CACHE: dict = {}
_FH_CACHE: dict = {}
_HIST_CACHE: dict = {}
_OHLC_CACHE: dict = {}


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def env_key(name: str) -> str:
    """Read an API key from the environment or a gitignored repo-root .env (KEY=value), like fmp_client."""
    key = os.environ.get(name, "").strip()
    if key:
        return key
    env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        with open(env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{name}=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _fi_get(fi, *keys):
    for k in keys:
        try:
            v = fi[k]
            if v is not None:
                return v
        except Exception:
            v = getattr(fi, k, None)
            if v is not None:
                return v
    return None


def yfinance_price_fetcher(tickers: List[str], ttl: float = 300.0) -> Dict[str, dict]:
    """{ticker: {last, change_pct}} via yfinance fast_info (last_price / previous_close). Handles .V/.TO.
    Cached ``ttl`` seconds; degrades to {} if yfinance is absent or a symbol fails."""
    out: Dict[str, dict] = {}
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return out
    now = time.time()
    for tk in tickers:
        if not tk:
            continue
        c = _YF_CACHE.get(tk)
        if c and now - c[0] < ttl:
            out[tk] = c[1]
            continue
        try:
            fi = yf.Ticker(tk).fast_info
            last = _f(_fi_get(fi, "last_price", "lastPrice"))
            prev = _f(_fi_get(fi, "previous_close", "previousClose"))
            chg = round((last - prev) / prev * 100.0, 2) if (last and prev) else None
            rec = {"last": last, "change_pct": chg}
            _YF_CACHE[tk] = (now, rec)
            out[tk] = rec
        except Exception:
            continue
    return out


def yfinance_history(ticker: str, period: str = "1mo", ttl: float = 3600.0) -> List[float]:
    """Recent daily closes (for the detail-card sparkline) via yfinance. Handles .V/.TO. Cached ``ttl``s;
    degrades to [] if yfinance is absent or the symbol fails."""
    if not ticker:
        return []
    c = _HIST_CACHE.get((ticker, period))
    if c and time.time() - c[0] < ttl:
        return c[1]
    try:
        import yfinance as yf  # type: ignore
        hist = yf.Ticker(ticker).history(period=period)
        closes = [float(v) for v in hist["Close"].tolist() if v == v]   # drop NaN
    except Exception:
        return []
    _HIST_CACHE[(ticker, period)] = (time.time(), closes)
    return closes


def yfinance_ohlc(ticker: str, period: str = "1mo", ttl: float = 3600.0) -> List[tuple]:
    """Recent daily (open, high, low, close) bars for the candlestick chart, via yfinance. Handles
    .V/.TO. Cached ``ttl``s; degrades to [] on absence/failure."""
    if not ticker:
        return []
    c = _OHLC_CACHE.get((ticker, period))
    if c and time.time() - c[0] < ttl:
        return c[1]
    try:
        import yfinance as yf  # type: ignore
        h = yf.Ticker(ticker).history(period=period)
        rows = [(float(o), float(hi), float(lo), float(cl))
                for o, hi, lo, cl in zip(h["Open"], h["High"], h["Low"], h["Close"])
                if o == o and cl == cl]   # drop NaN rows
    except Exception:
        return []
    _OHLC_CACHE[(ticker, period)] = (time.time(), rows)
    return rows


def finnhub_price_fetcher(tickers: List[str], key: Optional[str] = None, ttl: float = 120.0) -> Dict[str, dict]:
    """{ticker: {last, change_pct}} via Finnhub /quote (free; `c` = current, `dp` = day change %). Fast,
    but may not resolve TSX-V microcaps. No key / failure -> {}."""
    key = key or env_key("FINNHUB_API_KEY")
    if not key:
        return {}
    out: Dict[str, dict] = {}
    now = time.time()
    for tk in tickers:
        if not tk:
            continue
        c = _FH_CACHE.get(tk)
        if c and now - c[0] < ttl:
            out[tk] = c[1]
            continue
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={urllib.parse.quote(tk)}&token={key}"
            with urllib.request.urlopen(url, timeout=8) as r:   # noqa: S310
                d = json.loads(r.read().decode("utf-8"))
            rec = {"last": _f(d.get("c")), "change_pct": _f(d.get("dp"))}
            if rec["last"]:
                _FH_CACHE[tk] = (now, rec)
                out[tk] = rec
        except Exception:
            continue
    return out
