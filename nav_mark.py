"""
Mark-NAV-to-Spot (V1 — the valuation flagship): a NAV per share recomputed each cycle from
STRUCTURED INVENTORY × live spot × live FX, replacing the static hand-entered
``nav_adj_per_share`` for asset-light / passive names that carry physical commodity inventory
at IFRS lower-of-cost/NRV (URC.TO uranium today; generalizes to any physical sleeve).

Why: a hand-stamped NAV is stale the moment spot moves — the URC.TO 3.26 was derived at
US$86.10/lb and silently kept pricing the book at that mark through every spot swing. This
module makes the derivation LIVE and the staleness VISIBLE.

Two-tier spot, decided up front:
  * **live** — commodities the engine already fetches (gold GC=F, silver SI=F, copper HG=F):
    the live USD spot is passed in and the mark breathes with the tape.
  * **stamped** — uranium has NO free spot feed, so the spot is an analyst-stamped
    ``spot_usd`` + ``spot_as_of`` inside the inventory record; the mark carries an age and a
    staleness flag the confidence ribbon widens on. NEVER invented: a missing stamp for a
    non-live commodity yields no mark at all (the engine falls back to the static value).

The NRV floor: IFRS carries the inventory at lower-of-cost/NRV, so the uplift is
``max(0, units × spot_cad − carrying_cad)`` — when spot trades BELOW carrying the accounting
value already reflects the impairment and the uplift is zero, never negative (the carrying
value is the floor, exactly the conservatism the filings give us).

Pure stdlib — the engine supplies live spots + FX; this module never fetches. Fully testable
(tests/test_nav_mark.py).
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Optional

#: commodities the engine has a live USD feed for (the caller maps its own price cache onto
#: these keys). Anything else needs an analyst-stamped spot inside the inventory record.
LIVE_COMMODITIES = ("gold", "silver", "copper")

#: a stamped spot older than this is STALE — the ribbon widens and the cockpit shows it.
STALE_AFTER_DAYS = 45.0


def _num(x) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _age_days(as_of: Optional[str], now: Optional[float] = None) -> Optional[float]:
    if not as_of:
        return None
    try:
        d = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    today = date.fromtimestamp(now) if now is not None else date.today()
    return float((today - d).days)


def resolve_spot(commodity: str, *, live_spots: Optional[dict] = None,
                 stamped_usd: Any = None, stamped_as_of: Optional[str] = None,
                 stale_after_days: float = STALE_AFTER_DAYS,
                 now: Optional[float] = None) -> Optional[dict]:
    """Two-tier USD spot for a commodity: prefer the LIVE feed when one exists, else the
    analyst-stamped figure with explicit staleness. Returns ``{spot_usd, tier, as_of,
    age_days, stale}`` or None when neither tier has a usable number (grounded-or-silent)."""
    c = str(commodity or "").strip().lower()
    live = _num((live_spots or {}).get(c))
    if c in LIVE_COMMODITIES and live is not None and live > 0:
        return {"spot_usd": live, "tier": "live", "as_of": None, "age_days": 0.0, "stale": False}
    stamped = _num(stamped_usd)
    if stamped is not None and stamped > 0:
        age = _age_days(stamped_as_of, now)
        # >= not >: "45-day window" means day 45 IS stale — the old strict > let the stamp ride a
        # 46th day before the flag tripped (2026-07-08 reassessment, TF3 clock-item precision).
        stale = (age is None) or (age >= float(stale_after_days))  # an undated stamp is stale by definition
        return {"spot_usd": stamped, "tier": "stamped", "as_of": stamped_as_of,
                "age_days": age, "stale": stale}
    return None


def nav_from_inventory(inv: dict, *, live_spots: Optional[dict] = None,
                       usd_to_cad: Any = None, stale_after_days: float = STALE_AFTER_DAYS,
                       now: Optional[float] = None) -> Optional[dict]:
    """Compute the spot-marked NAV per share from a structured inventory record.

    ``inv`` (the research-cache ``nav_inventory`` value):
      total_equity_cad   IFRS equity (CAD) — the accounting base
      phy_units          physical inventory units (e.g. lbs U3O8)
      carrying_cad       what those units are carried at on the balance sheet (cost/NRV)
      shares_out         share count for the per-share divide
      commodity          drives the spot tier (live feed vs stamped)
      spot_usd / spot_as_of   the analyst stamp (used only when no live feed exists)

    Returns ``{nav_per_share, uplift_cad, spot:{...}, fx_usd_cad, computed_at}`` or None when
    any required input is missing/non-positive — the caller falls back to the static mark
    (ships dark; never a fake number)."""
    if not isinstance(inv, dict):
        return None
    equity = _num(inv.get("total_equity_cad"))
    units = _num(inv.get("phy_units"))
    carrying = _num(inv.get("carrying_cad"))
    shares = _num(inv.get("shares_out"))
    fx = _num(usd_to_cad)
    if None in (equity, units, carrying, shares, fx) or shares <= 0 or units <= 0 or fx <= 0:
        return None
    spot = resolve_spot(inv.get("commodity"), live_spots=live_spots,
                        stamped_usd=inv.get("spot_usd"), stamped_as_of=inv.get("spot_as_of"),
                        stale_after_days=stale_after_days, now=now)
    if spot is None:
        return None
    spot_cad = spot["spot_usd"] * fx
    # NRV floor: carrying already reflects any impairment below cost — uplift is never negative.
    uplift = max(0.0, units * spot_cad - carrying)
    nav_ps = (equity + uplift) / shares
    return {
        "nav_per_share": round(nav_ps, 4),
        "uplift_cad": round(uplift, 0),
        "spot": spot,
        "spot_cad": round(spot_cad, 4),
        "fx_usd_cad": fx,
        "commodity": str(inv.get("commodity") or "").lower(),
        "computed_at": now if now is not None else time.time(),
        "method": ("nav = (equity + max(0, units × spot_cad − carrying)) / shares "
                   "(carrying = NRV floor)"),
    }


def quality_note(mark: Optional[dict]) -> Optional[str]:
    """One human line for the cockpit / Story Card drivers — the mark's tier and freshness."""
    if not mark:
        return None
    sp = mark.get("spot") or {}
    if sp.get("tier") == "live":
        return f"NAV marked to LIVE {mark.get('commodity')} spot ${sp.get('spot_usd'):g}"
    age = sp.get("age_days")
    age_txt = f"{age:.0f}d old" if age is not None else "undated"
    flag = " ⚠STALE" if sp.get("stale") else ""
    return (f"NAV marked to STAMPED {mark.get('commodity')} spot ${sp.get('spot_usd'):g} "
            f"({age_txt}{flag})")
