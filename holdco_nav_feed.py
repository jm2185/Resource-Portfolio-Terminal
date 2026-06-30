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
    "FIELDS", "HARD_FLOOR_ARGS", "STALE_AFTER_DAYS", "QUALITY_FIELDS",
    "read_inputs", "feed_staleness", "assess_from_cache", "field_for", "read_quality_inputs",
    "fair_value_inputs_from_cache",
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

# quality_lenses_for() input  ->  research_cache field. OBJECTIVE sourced facts (counts, fractions,
# dilution rates, coverage ratios) — never a judgment score. net_liquid_to_mktcap is DERIVED below
# from the already-fed net-liquid + a live price×shares, so it isn't a stored field.
QUALITY_FIELDS: dict[str, str] = {
    "producing_royalty_count": "quality_producing_royalty_count",   # royalty: cash-flowing royalties (count)
    "asset_count":             "quality_asset_count",               # holdco: total properties + royalties (count)
    "tier1_operator_fraction": "quality_tier1_operator_fraction",   # royalty: share of producers on major operators
    "top_line_fraction":       "quality_top_line_fraction",         # royalty: NSR/stream (top-line) share vs cost-exposed
    "share_growth_rate":       "quality_share_growth_rate",         # both: annual dilution (inverse => accretion discipline)
    "cashflow_coverage":       "quality_cashflow_coverage",         # both: recurring revenue / corporate G&A
}

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


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


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
    # the development-pipeline assets (the risked-NAV / upside layer) live in one cache field as a list
    # [{name, npv, stage}]; absent ⇒ risked NAV == hard floor (no upside underwritten), reported honestly.
    pipe_entry = _get(cache, ticker, "holdco_pipeline_assets")
    pipeline_assets = pipe_entry.get("value") if (pipe_entry and isinstance(pipe_entry.get("value"), list)) else None
    res = holdco_nav.assess(name=name or ticker, price=price, sourced=rd["sourced"],
                            config=config, pipeline_assets=pipeline_assets, **rd["inputs"])
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
        "pipeline_sourced": bool(pipeline_assets),     # risked NAV carries a real upside layer (not == floor)
        "data_quality": dq,
    }
    return res


def fair_value_inputs_from_cache(cache: Any, ticker: str) -> dict:
    """Raw NATIVE-currency inputs for ``holdco_nav.central_fair_value`` (the archetype-aware fair-value
    anchor). For a royalty the anchor is TANGIBLE book — so we read ``total_equity`` (+ its confidence)
    and ``goodwill`` (absent ⇒ the consumer takes the conservative default-haircut path, capped MED).
    For a holdco/PG the anchor is net-liquid + risked pipeline + a peer portfolio mark, so we also pass
    the pipeline assets and ``holdco_peer_portfolio_value``. Shares + currency come along for the FX +
    per-share conversion the consumer does. Every field absent ⇒ None — never invented. Pure."""
    def _v(field: str) -> Any:
        e = _get(cache, ticker, field)
        return (e or {}).get("value")
    te = _get(cache, ticker, "total_equity")
    sh = _get(cache, ticker, FIELDS["shares"]) or _get(cache, ticker, "shares_out")
    pipe = _get(cache, ticker, "holdco_pipeline_assets")
    assets = pipe.get("value") if (pipe and isinstance(pipe.get("value"), list)) else None
    rer = _get(cache, ticker, "royalty_book_rerated_value")     # sourced metal-rerate of the cost book (gated)
    _ver = (rer or {}).get("verified")                          # an independent verifier's receipt (or absent)
    rerated_verified = (str(_ver.get("verdict", "")).strip().lower() in ("confirmed", "verified")
                        if isinstance(_ver, dict) else bool(_ver))   # only a CONFIRMED verdict counts as verified
    return {
        "total_equity": (te or {}).get("value"),
        "equity_confidence": (te or {}).get("confidence") or "high",
        "goodwill": _v("goodwill"),                              # absent ⇒ default-haircut path
        "shares": (sh or {}).get("value"),
        "currency": _v("currency"),
        "pipeline_assets": assets,                              # holdco floor+pipeline base
        "peer_portfolio_value": _v("holdco_peer_portfolio_value"),  # holdco optionality (absent ⇒ pipeline-only)
        "rerated_book_value": (rer or {}).get("value"),         # royalty cost-book re-rated to current metal
        "rerated_confidence": (rer or {}).get("confidence") or "med",
        "rerated_verified": rerated_verified,                   # verify-before-wire: unverified ⇒ held back
    }


def read_quality_inputs(cache: Any, ticker: str, *, price: Any = None, shares: Any = None) -> dict:
    """Read the archetype-native QUALITY inputs (objective sourced facts) for ``quality_lenses_for``,
    from the same provenance store as the NAV inputs. Also DERIVES ``net_liquid_to_mktcap`` — the
    balance-sheet lens — from the already-fed net-liquid + a live price×shares (shares falls back to the
    fed share count). A fact that isn't fed is simply absent, so quality_lenses drops that lens and
    renormalizes; nothing is invented. Returns ``{inputs, provenance}``. Pure (no I/O beyond the cache)."""
    inputs: dict[str, Any] = {}
    provenance: dict[str, dict] = {}
    for arg, field in QUALITY_FIELDS.items():
        entry = _get(cache, ticker, field)
        if entry is not None and entry.get("value") is not None:
            inputs[arg] = entry.get("value")
            provenance[arg] = {"value": entry.get("value"), "source": entry.get("source"),
                               "as_of": entry.get("as_of"), "confidence": entry.get("confidence")}
    # derived balance-sheet lens: net liquid as a fraction of market cap (cash + securities − debt vs
    # the equity value the market assigns). Needs the fed net-liquid + a live price + shares.
    nl_entry = _get(cache, ticker, FIELDS["net_liquid_assets"])
    nlv = _num(nl_entry.get("value")) if nl_entry else None
    sh = _num(shares)
    if sh is None:
        sh_entry = _get(cache, ticker, FIELDS["shares"])
        sh = _num(sh_entry.get("value")) if sh_entry else None
    P = _num(price)
    derived = None
    if nlv is not None and P and sh and P > 0 and sh > 0:
        mktcap = P * sh
        if mktcap > 0:
            derived = round(nlv / mktcap, 4)
    if derived is not None:                              # LIVE (moves with price) — preferred when a
        inputs["net_liquid_to_mktcap"] = derived          # native price is supplied
        provenance["net_liquid_to_mktcap"] = {
            "value": derived, "source": "derived: net_liquid_assets / (price × shares)",
            "as_of": (nl_entry or {}).get("as_of"), "confidence": "med"}
    else:                                               # fall back to a STORED static mark (FX-safe:
        st = _get(cache, ticker, "quality_net_liquid_to_mktcap")   # no live price/FX needed)
        sv = _num(st.get("value")) if st else None
        if sv is not None:
            inputs["net_liquid_to_mktcap"] = sv
            provenance["net_liquid_to_mktcap"] = {"value": sv, "source": st.get("source"),
                                                  "as_of": st.get("as_of"), "confidence": st.get("confidence")}
    return {"inputs": inputs, "provenance": provenance}
