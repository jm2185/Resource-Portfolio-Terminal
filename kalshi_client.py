"""
kalshi_client.py — read-only client for Kalshi's OFFICIAL public market-data API.

Wealthsimple Predict is a routed front-end to Kalshi (WS → clearing agent → Kalshi), so the true
executable book for every contract a Canadian will see in Predict lives on Kalshi's public,
unauthenticated market-data endpoints (~30 req/s allowed; we stay far under). This client is the
PREDICT scanner's only network surface — and it is read-only BY CONSTRUCTION: no auth, no order
endpoints, nothing to leak and nothing that can trade. The pure math lives in
``predict_arb_monitor``; this module only fetches and NORMALIZES.

Normalization matters because the API has two vintages in the wild: the current ``*_dollars``
string fields ("0.1300") + ``orderbook_fp`` dollar levels, and the legacy integer-cent fields
(yes_bid=13) + ``orderbook`` cent levels. ``parse_market`` / ``parse_orderbook`` accept either and
emit plain floats in probability space (0.0–1.0), so the monitor never sees the wire format.

Stdlib only (urllib; honors HTTPS(S)_PROXY env). Every fetch is rate-limited (min interval between
requests) and TTL-cached; failures degrade to ``None``/stamped errors, never raise out of
``build_snapshot``. Tests inject a ``transport`` callable — no live network in the suite.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

__all__ = ["KalshiPublicClient", "parse_market", "parse_orderbook", "build_snapshot",
           "DEFAULT_BASE_URL", "DEFAULT_SERIES"]

DEFAULT_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

#: Curated default series universe — the CIRO-shaped slice (economic indicators · financial
#: markets · climate) that maps onto what Wealthsimple Predict is authorized to distribute in
#: Canada. Config (`predict_arb_monitor.series`) overrides; the scout for new series is the
#: operator, not this list.
DEFAULT_SERIES: tuple = (
    "KXFED",        # Fed funds upper bound after each FOMC meeting (threshold ladder)
    "KXFEDDECISION",  # the per-meeting decision partition (hike/hold/cut)
    "KXCPI",        # CPI month-over-month brackets
    "KXCPIYOY",     # CPI year-over-year threshold ladder
    "KXGDP",        # GDP growth brackets
    "KXPAYROLLS",   # nonfarm payrolls brackets
    "KXU3",         # unemployment-rate ladder
    "KXNASDAQ100Y", # Nasdaq-100 year-end range partition
    "KXINXY",       # S&P 500 year-end range partition
    "KXHIGHNY",     # NYC daily high temp (climate ladder — liquid, fast-settling)
)


def _num(x: Any) -> Optional[float]:
    """Tolerant float coercion (mirrors monitor_protocol.num; local so this module stays free of
    repo imports and usable standalone)."""
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _price(m: dict, dollars_key: str, cents_key: str) -> Optional[float]:
    """One quote field → probability-space float. Prefers the current ``*_dollars`` string field,
    falls back to the legacy integer-cents field. 0 / missing / garbage → None (an unquoted side
    is information, not a zero)."""
    v = _num((m or {}).get(dollars_key))
    if v is None:
        c = _num((m or {}).get(cents_key))
        v = (c / 100.0) if c is not None else None
    if v is None or v <= 0.0 or v > 1.0:
        return None
    return round(v, 4)


def parse_market(m: dict) -> dict:
    """Normalize one wire-format market to the flat float dict the monitor consumes. Never raises;
    a thin market simply carries Nones. Prices are probability-space (0–1); sizes are contracts."""
    m = m or {}
    yes_bid = _price(m, "yes_bid_dollars", "yes_bid")
    yes_ask = _price(m, "yes_ask_dollars", "yes_ask")
    no_bid = _price(m, "no_bid_dollars", "no_bid")
    no_ask = _price(m, "no_ask_dollars", "no_ask")
    # In Kalshi's complementary book no_ask ≡ 1 − yes_bid; fill the gap when only one side came over
    # the wire so the monitor's parity/ladder math always has both sides of a quoted market.
    if no_ask is None and yes_bid is not None and 0.0 < 1.0 - yes_bid <= 1.0:
        no_ask = round(1.0 - yes_bid, 4)
    if no_bid is None and yes_ask is not None and 0.0 < 1.0 - yes_ask <= 1.0:
        no_bid = round(1.0 - yes_ask, 4)
    return {
        "ticker": str(m.get("ticker") or ""),
        "event_ticker": str(m.get("event_ticker") or ""),
        "market_type": str(m.get("market_type") or ""),
        "title": str(m.get("title") or ""),
        "yes_sub_title": str(m.get("yes_sub_title") or ""),
        "strike_type": str(m.get("strike_type") or ""),
        "floor_strike": _num(m.get("floor_strike")),
        "cap_strike": _num(m.get("cap_strike")),
        "status": str(m.get("status") or ""),
        "close_time": str(m.get("close_time") or ""),
        "yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask,
        "yes_bid_size": _num(m.get("yes_bid_size_fp")) or _num(m.get("yes_bid_size")),
        "yes_ask_size": _num(m.get("yes_ask_size_fp")) or _num(m.get("yes_ask_size")),
        "last_price": _price(m, "last_price_dollars", "last_price"),
        "liquidity": _num(m.get("liquidity_dollars")) or _num(m.get("liquidity")),
        "volume_24h": _num(m.get("volume_24h_fp")) or _num(m.get("volume_24h")),
        "open_interest": _num(m.get("open_interest_fp")) or _num(m.get("open_interest")),
    }


def parse_orderbook(ob: dict) -> dict:
    """Normalize an orderbook reply to ``{"yes": [(price, size), …], "no": [(price, size), …]}``
    (each side = resting BIDS at that price, best first, probability-space floats). Accepts the
    current ``orderbook_fp`` (dollar strings) and the legacy ``orderbook`` (integer cents)."""
    ob = ob or {}
    body = ob.get("orderbook_fp") or ob.get("orderbook") or ob
    out: dict = {"yes": [], "no": []}
    for side, keys in (("yes", ("yes_dollars", "yes")), ("no", ("no_dollars", "no"))):
        levels = None
        for k in keys:
            if isinstance(body, dict) and isinstance(body.get(k), list):
                levels = body[k]
                scale = 1.0 if k.endswith("_dollars") else 0.01
                break
        if levels is None:
            continue
        parsed = []
        for lv in levels:
            try:
                p, q = _num(lv[0]), _num(lv[1])
            except (TypeError, IndexError):
                continue
            if p is None or q is None or q <= 0:
                continue
            p *= scale
            if 0.0 < p < 1.0:
                parsed.append((round(p, 4), q))
        parsed.sort(key=lambda x: -x[0])          # bids: best (highest) first
        out[side] = parsed
    return out


class KalshiPublicClient:
    """Thin rate-limited GET client over the public endpoints. ``transport`` (url → parsed JSON
    dict) is injectable for tests; the default uses urllib with the env proxy settings."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, *, min_interval_s: float = 0.35,
                 cache_ttl_s: float = 20.0, timeout_s: float = 10.0,
                 transport: Optional[Callable[[str], dict]] = None):
        self.base_url = base_url.rstrip("/")
        self.min_interval_s = float(min_interval_s)
        self.cache_ttl_s = float(cache_ttl_s)
        self.timeout_s = float(timeout_s)
        self._transport = transport or self._default_transport
        self._cache: dict = {}                    # url -> (ts, payload)
        self._last_req = 0.0

    def _default_transport(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "commodityex-predict-scanner/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 (public API)
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path: str, params: dict) -> Optional[dict]:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "", False)})
        url = f"{self.base_url}{path}" + (f"?{qs}" if qs else "")
        hit = self._cache.get(url)
        now = time.time()
        if hit and (now - hit[0]) < self.cache_ttl_s:
            return hit[1]
        wait = self.min_interval_s - (now - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()
        try:
            payload = self._transport(url)
        except Exception:
            return None
        self._cache[url] = (time.time(), payload)
        return payload

    # -- public endpoints (market data only; there are deliberately no order/portfolio methods) --

    def get_events(self, *, series_ticker: str = "", status: str = "open", limit: int = 200,
                   cursor: str = "", with_nested_markets: bool = True) -> Optional[dict]:
        return self._get("/events", {"series_ticker": series_ticker, "status": status,
                                     "limit": limit, "cursor": cursor,
                                     "with_nested_markets": "true" if with_nested_markets else ""})

    def get_series_events(self, series_ticker: str, *, status: str = "open",
                          max_pages: int = 5) -> list:
        """All open events for one series (cursor-paged), nested markets included."""
        out, cursor = [], ""
        for _ in range(max(1, int(max_pages))):
            page = self.get_events(series_ticker=series_ticker, status=status, cursor=cursor)
            if not page:
                break
            out.extend(page.get("events") or [])
            cursor = str(page.get("cursor") or "")
            if not cursor:
                break
        return out

    def get_orderbook(self, ticker: str, *, depth: int = 16) -> Optional[dict]:
        if not ticker:
            return None
        return self._get(f"/markets/{urllib.parse.quote(ticker)}/orderbook", {"depth": depth})


def build_snapshot(client: KalshiPublicClient, *, series: Any = None, status: str = "open",
                   orderbook_tickers: Any = None, now_ts: Optional[float] = None) -> dict:
    """Assemble the plain-dict snapshot the pure monitor consumes: normalized events + markets for
    each series, plus (optionally) normalized orderbooks for named tickers — the two-stage flow is
    quotes-first, then depth only for candidate violations. Per-series failures are stamped into
    ``errors`` and the rest of the snapshot still lands (degrade, never crash)."""
    series = list(series or DEFAULT_SERIES)
    events_out: list = []
    errors: list = []
    for s in series:
        try:
            evs = client.get_series_events(s, status=status)
        except Exception as e:                    # transport is already guarded; belt & braces
            evs, _ = [], errors.append({"series": s, "error": str(e)[:200]})
        if not evs:
            errors.append({"series": s, "error": "no open events returned"})
            continue
        for e in evs:
            events_out.append({
                "event_ticker": str(e.get("event_ticker") or ""),
                "series_ticker": str(e.get("series_ticker") or s),
                "title": str(e.get("title") or ""),
                "category": str(e.get("category") or ""),
                "mutually_exclusive": bool(e.get("mutually_exclusive")),
                "available_on_brokers": bool(e.get("available_on_brokers")),
                "markets": [parse_market(m) for m in (e.get("markets") or [])],
            })
    books: dict = {}
    for tk in list(orderbook_tickers or []):
        ob = client.get_orderbook(tk)
        if ob is not None:
            books[tk] = parse_orderbook(ob)
    return {"ts": float(now_ts if now_ts is not None else time.time()),
            "source": client.base_url, "series": series,
            "events": events_out, "orderbooks": books, "errors": errors}
