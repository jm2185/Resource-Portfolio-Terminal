"""
Discovery screen — systematic, reproducible discovery (Phase 6 of docs/VALIDATION_FLYWHEEL_PLAN.md).

@scout used to lean on web search as the discovery itself ("what did the model surface today").
This module puts a quantitative screen IN FRONT of it, over a maintained candidate universe
(``data/candidate_universe.json``): hard gates in a fixed order, each kill logged with its reason,
so a scout run is repeatable and auditable. Web search then ENRICHES survivors (catalysts,
management, story) instead of being the funnel.

Gate order (slot-fit FIRST — the same mandate the rotation gate enforces, applied to discovery):
  1. slot-fit          — the thesis-slot taxonomy (CLAUDE.md / council.slot_gate / scout.md D2)
  2. stage window      — per slot (a spear candidate must be PEA-or-earlier, etc.)
  3. jurisdiction      — Fraser-tier minimum
  4. market-cap band
  5. survival          — cash runway + dilution history (the JSF/death-spiral lens, coarse)
  6. REP-floor coverage— (cash + stressed in-ground value) vs EV, coarse margin-of-safety

Missing-data policy (documented, deliberate): the IDENTITY gates (slot, stage) fail closed — a
candidate that can't state what it is doesn't survive. The NUMERIC gates (3–6) pass a candidate
with missing data but stamp the gap into ``data_gaps`` — at the top of a discovery funnel,
killing on absent free-feed data would empty the universe; the gaps are visible and @verifier /
@anti-scout must close them before graduation (Phase 7 makes that gate mandatory).

Every survivor carries its base-rate anchor (``calibration.candidate_anchor``, stage-conditioned)
— the outside view attached before any narrative.

Pure stdlib; the universe file is data, maintained by the operator/@scout.
"""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_UNIVERSE_PATH = "data/candidate_universe.json"

#: thesis-slot taxonomy → what fits (mirrors CLAUDE.md / scout.md; vehicle = what the security IS).
SLOT_RULES: dict = {
    "silver-spear": {
        "vehicles": {"explorer", "developer", "operator"},
        "commodities": {"silver", "ag", "ag_polymetallic", "polymetallic"},
        "stages": {"grassroots", "exploration", "delineation", "pre_pea", "pea"},
        "stage_note": "convex Ag junior; PEA-or-earlier (option-convexity)",
    },
    "gold-royalty-ballast": {
        "vehicles": {"royalty", "streamer"},
        "commodities": {"gold", "au"},
        "stages": None,                                # cash flow matters, not project stage
        "stage_note": "producing / near-producing royalty cash flow",
    },
    "project-generator-holdco": {
        "vehicles": {"holdco", "project_generator", "royalty_generator"},
        "commodities": None,                           # diversified by design
        "stages": None,
        "stage_note": "diversified discovery optionality, T1/T1-CAN",
    },
    "electrification-royalty": {
        "vehicles": {"royalty", "streamer", "physical"},
        "commodities": {"uranium", "u", "copper", "cu", "cobalt", "co", "nickel", "ni",
                        "lithium", "li", "grid"},
        "stages": None,
        "stage_note": "royalty/streamer/physical on electrification metals; NOT an operator",
    },
}

#: slot → the archetype whose published base rate anchors its candidates' outside view.
SLOT_ARCHETYPE = {"silver-spear": "option_convexity",
                  "gold-royalty-ballast": "asset_light_yield",
                  "project-generator-holdco": "option_convexity",
                  "electrification-royalty": "asset_light_yield"}

#: numeric gate defaults — overridable per call (and from the universe file's screen_config).
DEFAULT_GATES: dict = {
    "fraser_min": 60.0,                # Fraser Investment Attractiveness floor (T1-ish)
    "mcap_band_cad_m": [5.0, 500.0],   # junior territory: big enough to live, small enough to move
    "runway_min_months": 6.0,          # the engine's own survival flag threshold
    "dilution_max_annual": 0.25,       # >25%/yr share growth = death-spiral territory for a junior
    "rep_floor_coverage_min": 0.40,    # (cash + stressed in-ground) ≥ 40% of EV, coarse
}

GATE_ORDER = ("slot_fit", "stage_window", "jurisdiction", "mcap_band", "survival",
              "rep_floor_coverage")


def _num(x) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _norm(s) -> str:
    return str(s or "").strip().lower().replace(" ", "_").replace("-", "_")


def load_universe(path: str = DEFAULT_UNIVERSE_PATH) -> dict:
    """The maintained candidate universe: {"candidates": [...], "screen_config": {...}, ...}."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"candidates": []}


def slot_fit(candidate: dict, slot: str) -> tuple:
    """(fits: bool, reason: str). Slot-fit is identity, so it FAILS CLOSED on missing fields —
    a candidate that can't say what vehicle/commodity it is doesn't fit any slot."""
    rules = SLOT_RULES.get(slot)
    if not rules:
        return False, f"unknown slot {slot!r}"
    tagged = {_norm(s) for s in (candidate.get("slots") or [])}
    if tagged and _norm(slot) not in tagged and "none" not in tagged:
        return False, f"tagged for {sorted(tagged)}, not {slot}"
    vehicle = _norm(candidate.get("vehicle"))
    if not vehicle:
        return False, "vehicle unstated (fail-closed: identity gate)"
    if rules["vehicles"] and vehicle not in rules["vehicles"]:
        return False, f"vehicle {vehicle!r} doesn't fit {slot} ({sorted(rules['vehicles'])})"
    if rules["commodities"]:
        commodities = {_norm(c) for c in (candidate.get("commodities") or [candidate.get("commodity")])
                       if c}
        if not commodities:
            return False, "commodity unstated (fail-closed: identity gate)"
        if not commodities & rules["commodities"]:
            return False, f"commodities {sorted(commodities)} don't fit {slot}"
    return True, "fits"


def _gate_stage(candidate: dict, slot: str) -> tuple:
    rules = SLOT_RULES.get(slot) or {}
    window = rules.get("stages")
    if window is None:
        return True, "no stage window for this slot", None
    stage = _norm(candidate.get("stage"))
    if not stage:
        return False, "stage unstated (fail-closed: identity gate)", None
    if stage not in window:
        return False, f"stage {stage!r} outside the {slot} window ({rules.get('stage_note')})", None
    return True, "in window", None


def _gate_numeric(value, *, lo=None, hi=None, label: str = "") -> tuple:
    """(passed, reason, gap). Missing value ⇒ pass with a named data gap (funnel policy above)."""
    v = _num(value)
    if v is None:
        return True, None, label                       # data gap, not a kill
    if lo is not None and v < lo:
        return False, f"{label} {v:g} < {lo:g}", None
    if hi is not None and v > hi:
        return False, f"{label} {v:g} > {hi:g}", None
    return True, None, None


def screen(universe: list, *, slot: str, gates: Optional[dict] = None,
           anchor_fn=None) -> dict:
    """Run the gate cascade over a candidate list for one thesis slot. Returns survivors (each
    with its ``data_gaps`` and base-rate ``anchor``) + the kill log (ticker · gate · reason) —
    the whole funnel auditable, not a vibe.

    ``anchor_fn`` overrides the base-rate anchor source (tests); default =
    ``calibration.candidate_anchor`` (stage-conditioned, lazy import, optional)."""
    g = dict(DEFAULT_GATES)
    g.update(gates or {})
    if anchor_fn is None:
        def anchor_fn(arch, stage, commodity):         # lazy, optional — never a hard dep
            try:
                import calibration
                return calibration.candidate_anchor(arch, stage=stage, commodity=commodity)
            except Exception:
                return {}

    survivors, killed = [], []
    for cand in universe or []:
        tkr = cand.get("ticker") or "?"
        gaps: list = []

        # 1 — slot-fit (the mandated first screen)
        ok, reason = slot_fit(cand, slot)
        if not ok:
            killed.append({"ticker": tkr, "gate": "slot_fit", "reason": reason})
            continue
        # 2 — stage window
        ok, reason, gap = _gate_stage(cand, slot)
        if not ok:
            killed.append({"ticker": tkr, "gate": "stage_window", "reason": reason})
            continue
        # 3 — jurisdiction (Fraser tier)
        ok, reason, gap = _gate_numeric(cand.get("fraser_index"), lo=g["fraser_min"],
                                        label="fraser_index")
        if not ok:
            killed.append({"ticker": tkr, "gate": "jurisdiction", "reason": reason})
            continue
        if gap:
            gaps.append(gap)
        # 4 — market-cap band
        lo, hi = g["mcap_band_cad_m"]
        ok, reason, gap = _gate_numeric(cand.get("mcap_cad_m"), lo=lo, hi=hi, label="mcap_cad_m")
        if not ok:
            killed.append({"ticker": tkr, "gate": "mcap_band", "reason": reason})
            continue
        if gap:
            gaps.append(gap)
        # 5 — survival (runway + dilution history; the JSF lens, coarse)
        ok, reason, gap = _gate_numeric(cand.get("runway_months"), lo=g["runway_min_months"],
                                        label="runway_months")
        if not ok:
            killed.append({"ticker": tkr, "gate": "survival", "reason": reason})
            continue
        if gap:
            gaps.append(gap)
        ok, reason, gap = _gate_numeric(cand.get("dilution_annual"),
                                        hi=g["dilution_max_annual"], label="dilution_annual")
        if not ok:
            killed.append({"ticker": tkr, "gate": "survival", "reason": reason})
            continue
        if gap:
            gaps.append(gap)
        # 6 — REP-floor coverage (coarse margin of safety)
        cash = _num(cand.get("cash_cad_m"))
        stressed = _num(cand.get("stressed_in_ground_cad_m"))
        ev = _num(cand.get("ev_cad_m"))
        if ev is not None and ev > 0 and (cash is not None or stressed is not None):
            coverage = ((cash or 0.0) + (stressed or 0.0)) / ev
            if coverage < g["rep_floor_coverage_min"]:
                killed.append({"ticker": tkr, "gate": "rep_floor_coverage",
                               "reason": f"coverage {coverage:.2f} < {g['rep_floor_coverage_min']:g}"})
                continue
            cand = dict(cand)
            cand["rep_floor_coverage"] = round(coverage, 3)
        else:
            gaps.append("rep_floor_coverage")

        survivor = dict(cand)
        if gaps:
            survivor["data_gaps"] = gaps               # visible — @verifier closes these pre-graduation
        anchor = anchor_fn(SLOT_ARCHETYPE.get(slot), _norm(cand.get("stage")) or None,
                           _norm(cand.get("commodity")) or None)
        if anchor:
            survivor["anchor"] = anchor                # the outside view, attached before narrative
        survivors.append(survivor)

    return {"slot": slot, "gates": g, "gate_order": list(GATE_ORDER),
            "n_in": len(universe or []), "n_survivors": len(survivors),
            "survivors": survivors, "killed": killed,
            "note": ("screen-first discovery: web search ENRICHES these survivors "
                     "(catalysts/management/story); it is no longer the funnel. data_gaps must be "
                     "closed by @verifier/@anti-scout before graduation (the Phase-7 gate).")}
