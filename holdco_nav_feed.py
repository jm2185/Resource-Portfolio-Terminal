"""
holdco_nav_feed.py — the QUARTERLY feed bridge between the provenance store and the layered-NAV engine.

`holdco_nav.assess()` is pure: it takes input numbers. This module is where those numbers COME FROM —
**not hardcoded in the engine**, but read each cycle from `research_cache` (the same provenance-stamped,
point-in-time store the in-ground-ounce inputs already live in). To refresh a holdco/royalty-company
each quarter you drop its new filing figures into research_cache:

    cache.set("GROY", "holdco_producing_royalty_cf", 18_400_000,
              source="https://…/Q1-2026-MDA", as_of="2026-03-31", confidence="high")

and that's it — the prior quarter is preserved in `history` (point-in-time), staleness becomes visible
(`as_of` / `age_days`), and a layer that was never sourced stays ABSENT (reported NOT SOURCED, never a
fake default). No code change, no redeploy: a holdco's NAV inputs are DATA, fed on the reporting cadence.

This module is pure orchestration — it does no I/O of its own beyond the ResearchCache you hand it, and
keeps `holdco_nav.py` free of any store dependency (pure helper + thin consumer, the house pattern).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import holdco_nav

__all__ = [
    "FIELDS", "HARD_FLOOR_ARGS", "STALE_AFTER_DAYS",
    "read_inputs", "feed_staleness", "assess_from_cache", "field_for",
]

# holdco_nav.assess() kwarg  ->  research_cache field name. The cache field is namespaced `holdco_*`
# so these never collide with the in-ground-ounce / AISC fields a name may also carry. Each is sourced
# and dated INDEPENDENTLY (G&A from the income statement, net-liquid from the balance sheet, shares from
# the cover page) so you can refresh just the line that moved.
FIELDS: dict[str, str] = {
    "producing_royalty_cf":  "holdco_producing_royalty_cf",   # annual cash flow from CASH-FLOWING royalties only, $
    "corporate_g_and_a":     "holdco_corporate_g_and_a",       # annual corporate G&A (the burn the floor nets out), $
    "net_liquid_assets":     "holdco_net_liquid_assets",       # cash + marketable securities − debt, $
    "shares":                "holdco_shares_outstanding",      # shares outstanding (fully diluted if material), count
    "risked_pipeline_value": "holdco_risked_pipeline_value",   # development pipeline at RISKED NPV (NPV×P), $ — upside layer
    "optionality_value":     "holdco_optionality_value",       # exploration tail / management premium, $ — upside layer
}

# The four layers the HARD FLOOR + per-share read need. Missing any ⇒ the floor is PENDING, not faked.
HARD_FLOOR_ARGS = ("producing_royalty_cf", "corporate_g_and_a", "net_liquid_assets", "shares")

# A quarterly filer is current for ~one reporting cycle: ~45d filing lag + ~91d quarter ≈ 136d. Past
# this the next quarterly should have superseded it, so we flag a refresh as due. Tunable, not a fake.
STALE_AFTER_DAYS = 136


def field_for(arg: str) -> Optional[str]:
    """The research_cache field name backing a holdco_nav input (or None if not a fed input)."""
    return FIELDS.get(arg)


def _get(cache: Any, ticker: str, field: str) -> Optional[dict]:
    try:
        entry = cache.get(ticker, field)
    except Exception:
        return None
    return entry if isinstance(entry, dict) else None


def _age_days(as_of: Any, today: Optional[date]) -> Optional[int]:
    if not as_of:
        return None
    try:
        d = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return ((today or date.today()) - d).days


def read_inputs(cache: Any, ticker: str, *, shares_override: Any = None) -> dict:
    """Pull a name's holdco-NAV inputs out of the provenance store. Returns the inputs keyed by
    ``holdco_nav.assess`` kwarg, plus per-layer ``sourced`` flags, ``as_of`` dates, full ``provenance``,
    and ``missing_for_floor`` (hard-floor layers not yet sourced). A layer absent from the cache is
    simply not returned (assess defaults it to 0 and marks it NOT SOURCED) — never invented.

    ``shares_override`` (e.g. a market-data fundamentals share count) is used ONLY when no sourced share
    count exists, and is flagged ``sourced=False`` so the read stays honest about provenance."""
    inputs: dict[str, Any] = {}
    sourced: dict[str, bool] = {}
    as_of: dict[str, Optional[str]] = {}
    provenance: dict[str, dict] = {}
    for arg, field in FIELDS.items():
        entry = _get(cache, ticker, field)
        if entry is not None and entry.get("value") is not None:
            inputs[arg] = entry.get("value")
            sourced[arg] = True
            as_of[arg] = entry.get("as_of")
            provenance[arg] = {"value": entry.get("value"), "source": entry.get("source"),
                               "as_of": entry.get("as_of"), "confidence": entry.get("confidence"),
                               "note": entry.get("note")}
        else:
            sourced[arg] = False
    if not sourced.get("shares") and shares_override is not None:
        try:
            sh = float(shares_override)
        except (TypeError, ValueError):
            sh = None
        if sh and sh > 0:
            inputs["shares"] = sh
            sourced["shares"] = False          # market data, not a filing — stays flagged
            provenance["shares"] = {"value": sh, "source": "market data (fundamentals)",
                                    "as_of": None, "confidence": "low"}
    missing = [a for a in HARD_FLOOR_ARGS if not sourced.get(a)]
    return {"inputs": inputs, "sourced": sourced, "as_of": as_of,
            "provenance": provenance, "missing_for_floor": missing}


def feed_staleness(as_of: dict, *, today: Optional[date] = None,
                   stale_after_days: int = STALE_AFTER_DAYS) -> dict:
    """Freshness of the HARD-FLOOR layers — the oldest as_of among them is the binding constraint
    (the floor is only as current as its stalest input). Returns the oldest date, its age in days, and
    ``refresh_due`` once that age crosses one reporting cycle."""
    dates = [as_of.get(a) for a in HARD_FLOOR_ARGS if as_of.get(a)]
    ages = [(d, _age_days(d, today)) for d in dates]
    ages = [(d, a) for d, a in ages if a is not None]
    if not ages:
        return {"oldest_as_of": None, "age_days": None, "refresh_due": False}
    oldest_date, oldest_age = max(ages, key=lambda t: t[1])     # largest age = stalest
    return {"oldest_as_of": oldest_date, "age_days": oldest_age,
            "refresh_due": bool(oldest_age > stale_after_days)}


def assess_from_cache(cache: Any, ticker: str, *, price: Any = None, shares_override: Any = None,
                      name: str = "", config: Optional[dict] = None, today: Optional[date] = None,
                      stale_after_days: int = STALE_AFTER_DAYS) -> dict:
    """The single call the engine/cockpit makes: read a name's fed inputs from research_cache, run the
    layered NAV, and attach the feed metadata (provenance, per-layer as_of, staleness, a one-line
    data-quality read). When the hard floor's layers aren't all sourced yet the result carries
    ``available`` from assess but the ``feed.data_quality`` line says exactly what's pending — so a
    half-fed name degrades loudly instead of printing a confident-looking but unfounded floor."""
    rd = read_inputs(cache, ticker, shares_override=shares_override)
    res = holdco_nav.assess(name=name or ticker, price=price, sourced=rd["sourced"],
                            config=config, **rd["inputs"])
    stale = feed_staleness(rd["as_of"], today=today, stale_after_days=stale_after_days)
    missing = rd["missing_for_floor"]
    if missing:
        dq = "PENDING — hard floor not yet sourced: " + ", ".join(missing) + " (NOT SOURCED — feed the latest filing)"
    elif stale["refresh_due"]:
        dq = (f"sourced, but stalest layer is {stale['oldest_as_of']} ({stale['age_days']}d old) — "
              f"quarterly refresh due")
    else:
        dq = f"hard floor fully sourced (as of {stale['oldest_as_of']})"
    res["feed"] = {
        "ticker": ticker, "as_of": rd["as_of"], "provenance": rd["provenance"],
        "sourced": rd["sourced"], "missing_for_floor": missing,
        "oldest_as_of": stale["oldest_as_of"], "age_days": stale["age_days"],
        "refresh_due": stale["refresh_due"], "floor_sourced": not missing,
        "data_quality": dq,
    }
    return res
