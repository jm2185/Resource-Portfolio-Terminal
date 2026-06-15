"""
Engine /state -> MatrixState adapter (Forge-Matrix M0, engine-specific boundary).

Pure function: a published ``/state`` dict in, a frozen ``MatrixState`` out. No HTTP, no engine import,
no I/O — the orchestrator (M5) does the ``GET {ENGINE_URL}/state`` (exactly like
``mcp_server/core.py::_http_get_json``) and the optional ``catalyst_calendar`` read, then hands the raw
dicts here. That keeps the mapping unit-testable with a fixture and keeps the renderer free of engine
internals.

THE MAPPING (verified against engine.py; mirrors the Sentinel's STATE_FIELDS.md discipline):

  MatrixState field   <- /state path                                              status
  -----------------   -------------------------------------------------------     ----------------------
  net_tilt            <- macro_tape.net_tilt  (RISK-ON|RISK-OFF|BALANCED)          present
  mri                 <- mri  (root, raw Macro Regime Index)                       present
  regime_label        <- posture.label  (SPEAR EXPLOIT|BALANCED|DEFENSIVE)         present (engine.py:5044)
  posture_cap         <- posture.cap                                              present
  stress[]            <- macro_tape.signals[] {label, value, bias->state, read}    present
  watchlist[].symbol  <- conviction_mode.baskets[].ticker  (engine order)          present (abbreviated)
  watchlist[].last    <- nodes.<TK>.price  (fallback: basket.ladder.price)         present
  watchlist[].change_pct  <- nodes.<TK>.change_pct (future) | injected `changes`    GAP -> inject (FMP)
  watchlist[].rating/directive  <- basket.rating / basket.directive                present
  watchlist[].rho/floor_coverage  <- basket.pillars.V.{rho, floor_coverage}        present
  spear_pct/ballast_pct   <- nodes.<TK> {price*shares} bucketed by role            derived (unused now)
  next_catalyst       <- injected `catalysts` (catalyst_calendar.query)            GAP in /state -> None
  stale               <- freshness.*.stale (any True)                              present

Every degradation is toward caution and honesty: a missing field is None, never invented.
"""
from __future__ import annotations

import time
from typing import Any, Optional, Tuple

from .contract import CatalystRef, MatrixState, StressIndex, WatchItem


def _num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _bias_to_state(bias: Any) -> str:
    """Engine per-signal bias -> the renderer's colour state. The ENGINE owns the bucketing; we only
    re-express its three-valued tilt as a book-relative stress colour (risk_on tailwind = green/calm,
    neutral = amber/elevated, risk_off headwind = red/stress)."""
    b = str(bias or "").strip().lower().replace("-", "_")
    if b == "risk_on":
        return "calm"
    if b == "risk_off":
        return "stress"
    return "elevated"  # neutral / unknown -> amber (never guessed as calm)


def _abbrev(ticker: str) -> str:
    """64px display symbol: drop the exchange suffix (AGA.V->AGA, GMX.TO->GMX, URC.TO->URC; GROY->GROY).
    TODO(engine): an explicit portfolio_metadata[ticker].matrix_symbol would move this next to the data
    (the contract's intent), e.g. for a name whose abbreviation isn't just the pre-dot stem."""
    tk = str(ticker or "").strip().upper()
    return tk.split(".")[0] if "." in tk else tk


def _node_price(nodes: dict, ticker: str) -> Optional[float]:
    nd = nodes.get(ticker) if isinstance(nodes, dict) else None
    return _num(nd.get("price")) if isinstance(nd, dict) else None


def _ladder_price(basket: dict) -> Optional[float]:
    lad = basket.get("ladder") if isinstance(basket, dict) else None
    return _num(lad.get("price")) if isinstance(lad, dict) else None


def _asym(basket: dict, key: str) -> Optional[float]:
    """Read an asymmetry pillar value (ρ / φ) from a RAW /state basket: pillars.V.<key>. (The agent-
    facing projection flattens these to asymmetry.<key>, but /state carries the raw pillar shape.)"""
    pillars = basket.get("pillars") if isinstance(basket, dict) else None
    v = pillars.get("V") if isinstance(pillars, dict) else None
    return _num(v.get(key)) if isinstance(v, dict) else None


def _barbell_split(nodes: dict) -> Tuple[Optional[float], Optional[float]]:
    """Live spear/ballast split from node MARKET VALUE (price*shares) bucketed by role. This is the
    actual current split (honest), distinct from the structural 60/40 target in config — which can be
    added later as an enrichment. Returns (spear_pct, ballast_pct) or (None, None) if no MV is known."""
    if not isinstance(nodes, dict):
        return None, None
    spear_mv = ballast_mv = 0.0
    for nd in nodes.values():
        if not isinstance(nd, dict):
            continue
        price, shares = _num(nd.get("price")), _num(nd.get("shares"))
        if price is None or shares is None:
            continue
        mv = price * shares
        role = str(nd.get("role") or "").lower()
        if "spear" in role:
            spear_mv += mv
        elif "ballast" in role:
            ballast_mv += mv
    total = spear_mv + ballast_mv
    if total <= 0:
        return None, None
    return round(spear_mv / total * 100.0, 1), round(ballast_mv / total * 100.0, 1)


def _first_catalyst(catalysts: Any) -> Optional[CatalystRef]:
    """Map the soonest injected catalyst (catalyst_calendar.query(..., soonest-first)) to a CatalystRef.
    Catalysts are a GAP in /state, so the orchestrator fetches them and passes them in; absent -> None."""
    if not catalysts:
        return None
    first = catalysts[0] if isinstance(catalysts, (list, tuple)) else catalysts
    if not isinstance(first, dict):
        return None
    label = (first.get("label") or first.get("title") or first.get("macro_kind")
             or first.get("kind") or "CATALYST")
    days = first.get("days")
    if days is None:
        days = first.get("_days_to_start")
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None
    return CatalystRef(label=str(label)[:16].upper(), days=max(0, days))


def _is_stale(state: dict) -> bool:
    """True if any tracked feed is stale. Honours an explicit top-level flag, else scans freshness.*."""
    if state.get("stale") is True or state.get("any_stale") is True:
        return True
    fresh = state.get("freshness")
    if isinstance(fresh, dict):
        for v in fresh.values():
            if isinstance(v, dict) and v.get("stale"):
                return True
    return False


def build_matrix_state(state: Optional[dict], *, catalysts: Any = None,
                       changes: Any = None, now: Optional[float] = None) -> MatrixState:
    """Map one published engine ``/state`` to a MatrixState.

    ``catalysts``: optional pre-fetched catalyst list (GAP in /state). ``changes``: optional
    {ticker: day_change_pct} the orchestrator supplies (engine node field or FMP) until day-change is
    surfaced per-node in /state. Degrades gracefully: a None/empty state yields a safe BALANCED frame
    marked ``stale=True``.
    """
    if not state:
        return MatrixState(stale=True, generated_at=(now if now is not None else time.time()))

    tape = state.get("macro_tape") or {}
    posture = state.get("posture") or {}
    nodes = state.get("nodes") or {}
    baskets = ((state.get("conviction_mode") or {}).get("baskets")) or []

    # regime band ----------------------------------------------------------------------------------
    net_tilt = str(tape.get("net_tilt") or "BALANCED").upper()
    mri = _num(state.get("mri"))
    regime_label = str(posture.get("label") or posture.get("code") or "")
    posture_cap = _num(posture.get("cap"))

    # stress complex -------------------------------------------------------------------------------
    stress = tuple(
        StressIndex(
            label=str(s.get("label") or s.get("key") or "?"),
            value=_num(s.get("value")),
            state=_bias_to_state(s.get("bias")),
            read=s.get("read"),
        )
        for s in (tape.get("signals") or []) if isinstance(s, dict)
    )

    # watchlist ------------------------------------------------------------------------------------
    changes = changes or {}

    def _change(tk: str, nd: Optional[dict]) -> Optional[float]:
        chg = _num(nd.get("change_pct")) if isinstance(nd, dict) else None     # future engine node field
        return chg if chg is not None else _num(changes.get(tk))               # else orchestrator-injected

    watch = []
    if baskets:
        for b in baskets:
            if not isinstance(b, dict):
                continue
            tk = b.get("ticker")
            if not tk:
                continue
            nd = nodes.get(tk) if isinstance(nodes, dict) else None
            last = _num(nd.get("price")) if isinstance(nd, dict) else None
            if last is None:
                last = _ladder_price(b)
            watch.append(WatchItem(
                symbol=_abbrev(tk), last=last, change_pct=_change(tk, nd),
                rating=_num(b.get("rating")), directive=b.get("directive"),
                rho=_asym(b, "rho"), floor_coverage=_asym(b, "floor_coverage")))
    else:  # fallback: nodes alone (no conviction ordering available)
        for tk, nd in nodes.items():
            if isinstance(nd, dict):
                watch.append(WatchItem(symbol=_abbrev(tk), last=_num(nd.get("price")),
                                       change_pct=_change(tk, nd)))

    spear_pct, ballast_pct = _barbell_split(nodes)

    return MatrixState(
        net_tilt=net_tilt,
        mri=mri,
        regime_label=regime_label,
        posture_cap=posture_cap,
        stress=stress,
        watchlist=tuple(watch),
        spear_pct=spear_pct,
        ballast_pct=ballast_pct,
        next_catalyst=_first_catalyst(catalysts),
        stale=_is_stale(state),
        generated_at=(now if now is not None else time.time()),
    )
