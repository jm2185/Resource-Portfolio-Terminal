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
  3. listing           — US + Canada only (the book trades NA listings; foreign suffixes killed)
  4. jurisdiction      — Fraser-tier minimum
  5. market-cap band
  6. survival          — cash runway + dilution history (the JSF/death-spiral lens, coarse)
  7. REP-floor coverage— (cash + stressed in-ground value) vs EV, coarse margin-of-safety

Missing-data policy (documented, deliberate): the IDENTITY gates (slot, stage, listing) fail closed — a
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
import time
from typing import Optional

DEFAULT_UNIVERSE_PATH = "data/candidate_universe.json"

#: thesis-slot taxonomy → what fits (mirrors CLAUDE.md / scout.md; vehicle = what the security IS).
#: This is the SEED — the four built-in slots. User-created slots (data/thesis_slots.json) merge ON TOP
#: of it at load, so the taxonomy is runtime-extensible without a code change. The seed four are
#: immutable foundations (add_slot refuses to clobber them).
_SEED_SLOT_RULES: dict = {
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
        "vehicles": {"royalty", "streamer", "physical", "holdco", "royalty_generator"},
        "commodities": {"uranium", "u", "copper", "cu", "cobalt", "co", "nickel", "ni",
                        "lithium", "li", "grid"},
        "stages": None,
        "stage_note": "royalty/streamer/physical/diversified-holdco on electrification metals; NOT an operator",
    },
}

#: slot → the archetype whose published base rate anchors its candidates' outside view AND which the
#: engine's T/Q/V weights rate a held/eval name by. A new slot MUST map to one of these known
#: archetypes so the engine can rate names in it (see ARCHETYPES / archetype_for_vehicle).
_SEED_SLOT_ARCHETYPE = {"silver-spear": "option_convexity",
                        "gold-royalty-ballast": "asset_light_yield",
                        "project-generator-holdco": "option_convexity",
                        "electrification-royalty": "asset_light_yield"}

#: the archetypes the ENGINE knows how to rate (it carries T/Q/V weights per archetype — all FIVE in
#: archetypes.ARCHETYPE_DNA, not just the spear+ballast pair the funnel used to expose). A new slot's
#: archetype is constrained to these so its candidates are gradeable, not orphaned.
ARCHETYPES = ("option_convexity", "capital_margin", "commodity_cyclical",
              "asset_light_yield", "pure_macro_delta")

#: numeric gate defaults — overridable per call (and from the universe file's screen_config).
DEFAULT_GATES: dict = {
    "fraser_min": 60.0,                # Fraser Investment Attractiveness floor (T1-ish)
    "mcap_band_cad_m": [5.0, 500.0],   # junior territory: big enough to live, small enough to move
    "runway_min_months": 6.0,          # the engine's own survival flag threshold
    "dilution_max_annual": 0.25,       # >25%/yr share growth = death-spiral territory for a junior
    "rep_floor_coverage_min": 0.40,    # (cash + stressed in-ground) ≥ 40% of EV, coarse
    # the book trades US + Canada only. Canadian suffixes (.V/.TO/.TSXV/.TSX TSX-V & TSX,
    # .CN CSE, .NE Cboe Canada/NEO) + US OTC (.OTC); a bare ticker = US NYSE/Nasdaq. Anything
    # else (.L/AIM, .AX/ASX, .HK, .PA, .F, .MI) is a foreign primary listing and is killed.
    "allowed_ticker_suffixes": ["V", "TO", "TSXV", "TSX", "CN", "NE", "OTC"],
}

GATE_ORDER = ("slot_fit", "stage_window", "listing", "jurisdiction", "mcap_band", "survival",
              "rep_floor_coverage")


def _num(x) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _norm(s) -> str:
    return str(s or "").strip().lower().replace(" ", "_").replace("-", "_")


# --- runtime-extensible slot taxonomy: SEED four + user-created slots (data/thesis_slots.json) ----
#: where runtime-created slots persist. CEX_SLOTS_PATH redirects it (test isolation). Tracked book
#: state, like v5_config — a new slot is part of the book's definition, not ephemeral runtime.
SLOT_TAXONOMY_PATH = os.environ.get("CEX_SLOTS_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "thesis_slots.json")


def _slot_key(name) -> str:
    """Canonical slot key: lowercased, hyphenated (matches the seed style 'silver-spear')."""
    return _norm(name).replace("_", "-").strip("-")


def _setify(v):
    """JSON stores lists; the rules use sets (membership). None stays None (= 'any')."""
    if v is None:
        return None
    seq = v if isinstance(v, (list, tuple, set)) else [v]
    return {_norm(x) for x in seq if _norm(x)}


def archetype_for_vehicle(vehicle) -> str:
    """Map a security's vehicle → a KNOWN engine archetype, so a candidate is gradeable on the SAME
    basis the engine rates by (all five archetypes, not just the spear+ballast pair):
      royalty / streamer / holdco / royalty_generator → asset_light_yield (recurring, asset-light)
      physical (trust / ETP)                          → pure_macro_delta  (passive spot beta, NOT yield)
      operator / producer                             → commodity_cyclical (spot margin, cost curve)
      explorer / developer (or unknown)               → option_convexity   (pre-revenue, convex)
    capital_margin has no clean vehicle tell — it is reached only via an explicit archetype.
    The physical→pure_macro_delta split is the U-UN.TO lesson: a physical trust in the ballast slot
    must read as spot-beta, never as stable royalty yield."""
    v = _norm(vehicle)
    if v in ("royalty", "streamer", "holdco", "royalty_generator"):
        return "asset_light_yield"
    if v == "physical":
        return "pure_macro_delta"
    if v in ("operator", "producer"):
        return "commodity_cyclical"
    return "option_convexity"


def _load_user_slots(path=None) -> dict:
    """User-created slots (created from the TUI), merged on top of the seed. Missing/corrupt file →
    {} (seed only). Never raises."""
    try:
        with open(path or SLOT_TAXONOMY_PATH, encoding="utf-8") as f:
            return (json.load(f) or {}).get("slots") or {}
    except Exception:
        return {}


def slot_taxonomy(path=None) -> dict:
    """The full LIVE taxonomy — the seed four + any user-created slots — with rules as sets, ready for
    slot_fit/_gate_stage. User slots can't overwrite a seed slot."""
    merged = {k: dict(v) for k, v in _SEED_SLOT_RULES.items()}
    for name, rule in _load_user_slots(path).items():
        key = _slot_key(name)
        if key in _SEED_SLOT_RULES or not key:
            continue                                   # seed slots are immutable; skip blanks
        merged[key] = {"vehicles": _setify(rule.get("vehicles")) or set(),
                       "commodities": _setify(rule.get("commodities")),
                       "stages": _setify(rule.get("stages")),
                       "stage_note": str(rule.get("stage_note") or "")}
    return merged


def _archetype_map(path=None) -> dict:
    m = dict(_SEED_SLOT_ARCHETYPE)
    for name, rule in _load_user_slots(path).items():
        arch = _norm(rule.get("archetype"))
        if arch in ARCHETYPES:
            m[_slot_key(name)] = arch
    return m


#: the live, merged taxonomy the screen reads. reload_slots() refreshes after a slot is created.
SLOT_RULES = slot_taxonomy()
SLOT_ARCHETYPE = _archetype_map()


def reload_slots(path=None) -> dict:
    """Re-merge the taxonomy after a slot is created, so the screen / chooser / rotation gate see it
    immediately (no restart)."""
    global SLOT_RULES, SLOT_ARCHETYPE
    SLOT_RULES = slot_taxonomy(path)
    SLOT_ARCHETYPE = _archetype_map(path)
    return SLOT_RULES


def add_slot(name, *, vehicles, commodities=None, stages=None, stage_note="", archetype=None,
             source="operator", path=None) -> dict:
    """Persist a NEW user slot to the taxonomy file, then reload so it's live. Vehicles/commodities/
    stages take lists or sets (stored as sorted lists). The archetype is constrained to a KNOWN engine
    archetype (so the slot's candidates are gradeable); defaults from the first vehicle. Refuses to
    clobber a seed slot. Returns the stored entry."""
    key = _slot_key(name)
    if not key:
        raise ValueError("a slot needs a name")
    if key in _SEED_SLOT_RULES:
        raise ValueError(f"{key!r} is a built-in slot — pick a new name")
    veh = sorted(_setify(vehicles) or set())
    if not veh:
        raise ValueError("a slot needs at least one vehicle (what the security IS)")
    arch = _norm(archetype)
    if arch not in ARCHETYPES:
        arch = archetype_for_vehicle(veh[0])           # keep it gradeable
    entry = {"vehicles": veh,
             "commodities": (sorted(_setify(commodities)) if commodities is not None else None),
             "stages": (sorted(_setify(stages)) if stages is not None else None),
             "stage_note": str(stage_note or ""),
             "archetype": arch, "source": str(source), "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    p = path or SLOT_TAXONOMY_PATH
    try:
        data = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    except Exception:
        data = {}
    data.setdefault("slots", {})[key] = entry
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, p)
    reload_slots(path)
    return {"name": key, **entry}


def draft_slot_from_candidate(cand: dict) -> dict:
    """Infer a slot DRAFT from a screened candidate (the ◆ 'new slot from this' chip) — name from its
    commodity+vehicle, rules + a gradeable archetype from its stated fields. Returns kwargs ready for
    add_slot (after the operator confirms). Pure."""
    cand = cand or {}
    vehicle = _norm(cand.get("vehicle")) or "operator"
    commodity = _norm(cand.get("commodity"))
    base = commodity or _norm(cand.get("archetype")) or "satellite"
    arch = _norm(cand.get("archetype"))
    return {
        "name": _slot_key(f"{base}-{vehicle}"),
        "vehicles": [vehicle],
        "commodities": ([commodity] if commodity else None),
        "stages": None,                                # no stage window by default — refine on confirm
        "stage_note": (f"{(commodity or 'off-slot').replace('_', ' ')} "
                       f"{vehicle.replace('_', ' ')}"
                       + (f" · seeded from {cand.get('ticker')}" if cand.get("ticker") else "")),
        "archetype": arch if arch in ARCHETYPES else archetype_for_vehicle(vehicle),
    }


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


def _gate_listing(candidate: dict, allowed_suffixes) -> tuple:
    """(passed, reason). Identity gate — the book trades US + Canada only. A bare ticker is a US
    NYSE/Nasdaq line (pass); a suffixed ticker passes only if the suffix is in the allowed set
    (Canada + US OTC). Foreign primaries (.L/AIM, .AX/ASX, .HK, …) fail closed; so does a missing
    ticker (can't confirm the listing)."""
    tkr = str(candidate.get("ticker") or "").strip().upper()
    if not tkr:
        return False, "ticker unstated (fail-closed: can't confirm US/Canada listing)"
    if "." not in tkr:
        return True, "US listing (no suffix)"            # NYSE / Nasdaq
    suffix = tkr.rsplit(".", 1)[1]
    allowed = {str(s).strip().upper().lstrip(".") for s in (allowed_suffixes or [])}
    if suffix in allowed:
        return True, f".{suffix} (US/Canada)"
    return False, f"foreign listing .{suffix} (book trades US + Canada only)"


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


#: The OFF-SLOT / "satellite" screen — find calculated asymmetric bets that DON'T fit a thesis slot
#: (new sleeves / satellite plays outside the barbell). It SKIPS the two slot-IDENTITY gates (slot-fit
#: + stage window) — the whole point is names off the slot taxonomy — while keeping every QUALITY gate
#: (listing · jurisdiction · mcap band · survival · REP-floor coverage). The discipline stays; only the
#: slot constraint drops. Survivors are off-slot candidates: promote one to a new slot, or hold as a
#: satellite.
SATELLITE_SLOT = "satellite"
OFF_SLOT_ALIASES = frozenset({"satellite", "off-slot", "offslot", "off_slot", "none", "any", "freeform"})


def is_off_slot(slot) -> bool:
    """True when the requested screen is the slot-agnostic satellite screen (skip the identity gates)."""
    return _norm(slot) in OFF_SLOT_ALIASES


def screen(universe: list, *, slot: str, gates: Optional[dict] = None,
           anchor_fn=None) -> dict:
    """Run the gate cascade over a candidate list for one thesis slot. Returns survivors (each
    with its ``data_gaps`` and base-rate ``anchor``) + the kill log (ticker · gate · reason) —
    the whole funnel auditable, not a vibe.

    ``slot`` may be a thesis slot OR the off-slot ``satellite`` mode (see ``OFF_SLOT_ALIASES``): the
    latter skips the slot-fit + stage IDENTITY gates and keeps every quality gate, so it surfaces
    asymmetric bets that don't fit the current barbell slots.

    ``anchor_fn`` overrides the base-rate anchor source (tests); default =
    ``calibration.candidate_anchor`` (stage-conditioned, lazy import, optional)."""
    off_slot = is_off_slot(slot)
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

        # The two slot-IDENTITY gates (1 slot-fit, 2 stage window) are SKIPPED in off-slot/satellite
        # mode — by design: a satellite play doesn't fit a thesis slot. Every quality gate below stays.
        if not off_slot:
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
        # 3 — listing (US + Canada only; identity gate, fails closed on a foreign suffix)
        ok, reason = _gate_listing(cand, g.get("allowed_ticker_suffixes"))
        if not ok:
            killed.append({"ticker": tkr, "gate": "listing", "reason": reason})
            continue
        # 4 — jurisdiction (Fraser tier)
        ok, reason, gap = _gate_numeric(cand.get("fraser_index"), lo=g["fraser_min"],
                                        label="fraser_index")
        if not ok:
            killed.append({"ticker": tkr, "gate": "jurisdiction", "reason": reason})
            continue
        if gap:
            gaps.append(gap)
        # 5 — market-cap band
        lo, hi = g["mcap_band_cad_m"]
        ok, reason, gap = _gate_numeric(cand.get("mcap_cad_m"), lo=lo, hi=hi, label="mcap_cad_m")
        if not ok:
            killed.append({"ticker": tkr, "gate": "mcap_band", "reason": reason})
            continue
        if gap:
            gaps.append(gap)
        # 6 — survival (runway + dilution history; the JSF lens, coarse)
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
        # 7 — REP-floor coverage (coarse margin of safety)
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
        # off-slot has no fixed slot archetype — anchor on the candidate's own stated archetype (if any)
        anchor_arch = (_norm(cand.get("archetype")) or None) if off_slot else SLOT_ARCHETYPE.get(slot)
        anchor = anchor_fn(anchor_arch, _norm(cand.get("stage")) or None,
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
