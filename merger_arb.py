"""
Merger-arb read for a held name under a fixed-ratio all-share deal — pure, stdlib, tested.

The 2026-09-02 reassessment found the spear (AGA.V) signed into a fixed-ratio all-share
acquisition (0.1724 BNKR per AGA share, announced 2026-08-21) with **zero code readers** of the
fact: no acquirer feed, no ratio-implied mark, no spread. The desk computed all of it by hand in
Living Memory. This module makes those facts engine facts.

Config contract (``portfolio_metadata[<target>].merger_terms``)::

    {"acquirer": "BNKR.TO", "ratio": 0.1724, "announced": "2026-08-21",
     "undisturbed_close": 0.67, "vote_by": "2026-11-15", "source": "<url>"}

``read(cfg, prices, prices_stale)`` returns one entry per target with a live-or-flagged read; a
missing acquirer price yields an honest ``None`` implied value with ``stale: True`` — never a
fabricated spread.
"""
from __future__ import annotations

from typing import Optional


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def implied_consideration(ratio, acquirer_px) -> Optional[float]:
    """Value of one target share in acquirer stock at the fixed ratio."""
    r, a = _num(ratio), _num(acquirer_px)
    if r is None or a is None or r <= 0 or a <= 0:
        return None
    return round(r * a, 4)


def spread_pct(target_px, implied) -> Optional[float]:
    """Gross spread: how far the target trades BELOW its implied consideration (positive = discount)."""
    t, i = _num(target_px), _num(implied)
    if t is None or i is None or t <= 0 or i <= 0:
        return None
    return round((i / t - 1.0) * 100.0, 2)


def premium_pct(implied, undisturbed_close) -> Optional[float]:
    """Premium of the implied consideration over the target's undisturbed (pre-announcement) close."""
    i, u = _num(implied), _num(undisturbed_close)
    if i is None or u is None or u <= 0:
        return None
    return round((i / u - 1.0) * 100.0, 2)


def zero_premium_acquirer_px(undisturbed_close, ratio) -> Optional[float]:
    """The acquirer price at which the fixed ratio delivers exactly the undisturbed close — below
    it, holders hand over the assets for less than the market paid before the deal."""
    u, r = _num(undisturbed_close), _num(ratio)
    if u is None or r is None or r <= 0:
        return None
    return round(u / r, 4)


def read_one(target: str, terms: dict, prices: dict, prices_stale: Optional[dict] = None) -> dict:
    """One target's merger-arb read. Prices absent or stale are flagged, never filled."""
    stale = prices_stale or {}
    acq = str((terms or {}).get("acquirer") or "").upper()
    ratio = _num((terms or {}).get("ratio"))
    a_px = _num((prices or {}).get(acq)) if acq else None
    t_px = _num((prices or {}).get(target))
    implied = implied_consideration(ratio, a_px)
    out = {
        "target": target, "acquirer": acq or None, "ratio": ratio,
        "acquirer_px": a_px, "target_px": t_px,
        "implied": implied,
        "spread_pct": spread_pct(t_px, implied),
        "premium_pct": premium_pct(implied, (terms or {}).get("undisturbed_close")),
        "zero_premium_acquirer_px": zero_premium_acquirer_px((terms or {}).get("undisturbed_close"), ratio),
        "announced": (terms or {}).get("announced"),
        "vote_by": (terms or {}).get("vote_by"),
        "source": (terms or {}).get("source"),
        "stale": bool(a_px is None or t_px is None
                      or stale.get(acq) or stale.get(target)),
    }
    if out["stale"]:
        out["stale_reason"] = ("no acquirer price" if a_px is None else
                               "no target price" if t_px is None else "stale mark")
    return out


def targets(cfg: dict) -> dict:
    """``{target: merger_terms}`` for every portfolio_metadata name carrying ``merger_terms``."""
    pm = (cfg or {}).get("portfolio_metadata") or {}
    out = {}
    for tkr, meta in pm.items():
        if str(tkr).startswith("_") or not isinstance(meta, dict):
            continue
        mt = meta.get("merger_terms")
        if isinstance(mt, dict) and mt.get("acquirer") and _num(mt.get("ratio")):
            out[str(tkr)] = mt
    return out


def acquirer_tickers(cfg: dict) -> list:
    """Acquirer symbols the price worker must fetch (so the implied mark is never fabricated)."""
    return sorted({str(t["acquirer"]).upper() for t in targets(cfg).values()})


def read(cfg: dict, prices: dict, prices_stale: Optional[dict] = None) -> dict:
    return {t: read_one(t, terms, prices, prices_stale) for t, terms in targets(cfg).items()}
