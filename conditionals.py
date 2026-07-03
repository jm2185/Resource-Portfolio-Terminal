"""
Conditional-action layer (action-plan P4) — "what do I DO about it".

P1–P3 tell you the state of the world (tailwind, signals, scenario weights). This layer turns that
into STANDING, pre-committed conditional actions — so the desk acts on rules set in the cold light of
day, not on the day's adrenaline. Three gates, all pure consumers of the upstream layers (they read
the scenario weights + SENTINEL flags + posture; they never re-compute them):

  4.1 **AGA proportional-add gate** — the spear is the convex bet; adding to it is the easiest way to
      blow up a concentrated book. Three conditions must ALL hold to add: (1) thesis intact (not
      invalidated, JSF not severe), (2) entry not extended (LOAD/SCALE-IN, not WAIT/AVOID-EXTENDED),
      (3) regime supportive (posture not DEFENSIVE and the spear-favorable A+B scenario weight is
      adequate). The add is PROPORTIONAL — room-to-ceiling × condition-strength × posture cap — and
      the structural 60% spear ceiling is a hard, read-only invariant (mirrored from calculate_sizing).

  4.2 **per-thesis invalidation / stop lines** — each holding carries named invalidation lines, wired
      to the SENTINEL flags (P2.3) and per-name forensics. A hard line tripping ⇒ INVALIDATED (exit /
      rotate); a soft flag touching ⇒ WATCH (tighten / scout the hedge). Tailwind flags (a firing
      bear-steepener) are NOT stops — they're recorded as context so a tailwind is never misread as a
      breakdown.

  4.3 **dry-powder deployment** — WHERE the powder waits (the USD/CAD carry tilt from P2.3) and WHETHER
      to deploy: HOLD under a defensive posture, DEPLOY into names with a clean entry, STAGGER
      otherwise; reserve a convexity tranche when the crisis (B) weight is rich.

Pure + dependency-free; tunables under `conditionals.*` (proposal-gated). No eval(); graceful on thin
inputs (an unverifiable condition never green-lights an add).
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_CONDITIONALS_CONFIG", "CONDITIONALS_GLOSSARY", "conditionals_tooltip",
           "SPEAR_CEILING", "SLOT_INVALIDATION_LINES", "aga_add_gate", "invalidation_status",
           "dry_powder", "assess"]

#: The structural 60% spear ceiling — a NON-configurable invariant in calculate_sizing, mirrored here
#: read-only so the add gate can never propose past it. (Not a tunable; do not move it from config.)
from book_invariants import SPEAR_CEILING  # the 60% invariant — one shared source of truth

DEFAULT_CONDITIONALS_CONFIG: dict[str, Any] = {
    "spear_favorable_min": 0.45,        # weights[A]+weights[B] must clear this for the regime condition
    "add_entry_ok": ["LOAD", "SCALE-IN"],   # entry labels that clear the entry condition
    "entry_strength": {"LOAD": 1.0, "SCALE-IN": 0.6},   # proportional kick by entry quality
    "defensive_postures": ["DEFENSIVE"],
    "ceiling_eps": 0.005,               # treat spear within this of the ceiling as "at ceiling"
    "convexity_reserve_bweight": 0.30,  # crisis (B) weight at/above this ⇒ reserve a convexity tranche
}

#: Standing invalidation lines per thesis slot (some auto-tripped by flags/forensics, some monitored).
SLOT_INVALIDATION_LINES: dict[str, list[str]] = {
    "silver-spear":             ["REP floor breached", "JSF forensic gate severe", "binary catalyst (43-101 / PEA) fails"],
    "gold-royalty-ballast":     ["royalty cash-flow impairment", "JSF accrual breach", "counterparty mine halt"],
    "project-generator-holdco": ["holdco / NAV discount blowout", "JSF accrual breach", "discovery pipeline stalls"],
    "electrification-royalty":  ["uranium term market rolls over", "vehicle breaks structure (operator / spot-beta)", "JSF accrual breach"],
}

#: SENTINEL/scenario flag id → which thesis it touches and how hard. Tailwind/context flags are
#: deliberately absent (a bear-steepener is a spear tailwind, never a stop).
FLAG_INVALIDATION_MAP: dict[str, dict[str, Any]] = {
    "uranium_term_invalidation": {"slot": "electrification-royalty", "severity": "hard",
                                  "line": "uranium term market rolls over"},
    "scenario_c_hole": {"slot": "electrification-royalty", "severity": "watch",
                        "line": "scenario-C under-hedged — size / scout the slot"},
    "debasement_at_risk": {"slots": ["silver-spear", "gold-royalty-ballast"], "severity": "watch",
                           "line": "AI-productivity broadening — debasement premium at risk"},
}
#: Flags that are tailwinds/context, recorded but never treated as a stop.
CONTEXT_FLAGS = {"bear_steepener": "spear / crisis-hedge tailwind",
                 "oil_supply_risk": "energy-royalty breakdown watch armed (5.4)"}

CONDITIONALS_GLOSSARY: dict[str, dict[str, str]] = {
    "aga_add_gate": {
        "what": "The proportional-add gate for the convex spear (AGA.V) — three conditions (thesis intact · entry not extended · regime supportive) that must ALL hold to add, sized proportionally and hard-capped at the 60% spear ceiling.",
        "scale": "ADD (all pass, room left) · HOLD (a condition fails) · BLOCKED (at ceiling or invalidated).",
        "influence": "Gates discretionary spear adds; the proposed size scales with condition strength and the posture cap.",
        "edge": "An unverifiable condition (no entry read) does NOT green-light an add — silence fails closed.",
    },
    "invalidation_status": {
        "what": "Per-thesis invalidation / stop lines wired to the SENTINEL flags + per-name forensics.",
        "scale": "INTACT · WATCH (a soft flag touches the thesis) · INVALIDATED (a hard line tripped — exit / rotate).",
        "influence": "Turns a firing flag into a name-level stop action; tailwind flags are context, never stops.",
    },
    "dry_powder": {
        "what": "Dry-powder deployment — WHERE powder waits (USD/CAD carry tilt) and WHETHER to deploy.",
        "scale": "HOLD (defensive) · DEPLOY (clean entry present) · STAGGER (ladder in). Convexity tranche reserved when crisis (B) weight is rich.",
        "influence": "The standing cash-deployment rule, fed by the carry tilt (P2.3) and the scenario weights (P3).",
    },
}


def conditionals_tooltip(key: str) -> str:
    e = CONDITIONALS_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _cfg(config: Optional[dict]) -> dict:
    cfg = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
           for k, v in DEFAULT_CONDITIONALS_CONFIG.items()}
    block = (config or {}).get("conditionals", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def _posture_label(posture: Optional[dict]) -> Optional[str]:
    if not isinstance(posture, dict):
        return None
    return posture.get("label") or posture.get("code")


def aga_add_gate(*, spear_weight: Any = None, weights: Optional[dict] = None,
                 posture: Optional[dict] = None, entry: Any = None, aga_status: Any = None,
                 jsf_severe: bool = False, config: Optional[dict] = None) -> dict:
    """The AGA proportional-add gate. ``spear_weight`` = current spear book weight (drifts with price);
    ``weights`` = scenario weights (P3); ``posture`` = {label, cap}; ``entry`` = an entry label
    (LOAD/SCALE-IN/WAIT/AVOID-EXTENDED); ``aga_status`` = the spear's invalidation status. All optional
    (missing inputs fail the relevant condition closed)."""
    cfg = _cfg(config)
    sw = _num(spear_weight)
    room = None if sw is None else max(0.0, SPEAR_CEILING - sw)

    # condition 1 — thesis intact
    intact = (not jsf_severe) and (str(aga_status or "").upper() != "INVALIDATED")
    # condition 2 — entry not extended
    ent = str(entry or "").upper().replace("_", "-") if entry else None
    entry_ok = ent in [e.upper() for e in cfg["add_entry_ok"]]
    # condition 3 — regime supportive
    plabel = (_posture_label(posture) or "").upper()
    not_defensive = plabel not in [p.upper() for p in cfg["defensive_postures"]]
    ab = None
    if isinstance(weights, dict):
        a, b = _num(weights.get("A")), _num(weights.get("B"))
        ab = (a or 0.0) + (b or 0.0) if (a is not None or b is not None) else None
    regime_ok = bool(not_defensive and ab is not None and ab >= float(cfg["spear_favorable_min"]))

    conditions = [
        {"name": "thesis_intact", "pass": bool(intact),
         "detail": "JSF severe" if jsf_severe else (f"status {aga_status}" if aga_status else "no invalidation")},
        {"name": "entry_not_extended", "pass": bool(entry_ok),
         "detail": f"entry {ent}" if ent else "entry unverified"},
        {"name": "regime_supportive", "pass": bool(regime_ok),
         "detail": (f"posture {plabel or '—'}, A+B {ab:.0%}" if ab is not None else f"posture {plabel or '—'}, A+B n/a")},
    ]
    all_pass = all(c["pass"] for c in conditions)

    # decision + proportional size
    cap = _num((posture or {}).get("cap")) if isinstance(posture, dict) else None
    proposed_add = 0.0
    target_weight = sw
    if room is not None and room <= float(cfg["ceiling_eps"]):
        decision = "BLOCKED"; reason = f"at the {SPEAR_CEILING:.0%} spear ceiling (weight {sw:.0%})"
    elif not intact:
        decision = "BLOCKED"; reason = "spear thesis invalidated / JSF severe"
    elif all_pass:
        es = float(cfg["entry_strength"].get(ent, 0.0))
        rs = _clamp((ab - float(cfg["spear_favorable_min"])) / max(1e-9, 1.0 - float(cfg["spear_favorable_min"]))) if ab is not None else 0.0
        strength = _clamp(0.5 * es + 0.5 * (0.5 + 0.5 * rs))   # entry quality + regime tailwind
        size_mult = _clamp(cap if cap is not None else 1.0, 0.0, 1.25)
        proposed_add = round(min(room, room * strength * size_mult), 4) if room is not None else None
        target_weight = round(sw + proposed_add, 4) if (sw is not None and proposed_add is not None) else None
        decision = "ADD" if (proposed_add and proposed_add > 0) else "HOLD"
        reason = (f"all 3 conditions met — proportional add {proposed_add:.1%} toward target {target_weight:.0%} "
                  f"(room {room:.1%}, ×{size_mult:.2f} cap)" if proposed_add else "conditions met but no room/strength")
    else:
        decision = "HOLD"
        failed = [c["name"] for c in conditions if not c["pass"]]
        reason = "conditions not all met: " + ", ".join(failed)

    return {"decision": decision, "conditions": conditions, "all_conditions_met": all_pass,
            "spear_weight": sw, "ceiling": SPEAR_CEILING, "room_to_ceiling": (round(room, 4) if room is not None else None),
            "proposed_add": proposed_add, "target_weight": target_weight, "reason": reason}


def _gather_flags(*sources) -> list:
    out = []
    for src in sources:
        for f in (src or []):
            if isinstance(f, dict) and f.get("active") and f.get("id"):
                out.append(f)
    return out


def invalidation_status(holdings: Optional[list], *, flags: Optional[list] = None,
                        name_signals: Optional[dict] = None, config: Optional[dict] = None) -> dict:
    """Per-thesis invalidation status. ``flags`` = active SENTINEL/scenario flags; ``name_signals`` =
    {ticker: {jsf_severe, floor_breached}} per-name forensics. Returns a per-name status (INTACT /
    WATCH / INVALIDATED) with the tripped lines and their source."""
    flags = flags or []
    name_signals = name_signals or {}
    # index flags by what they touch
    by_slot_hard, by_slot_watch, context = {}, {}, []
    for f in flags:
        fid = f.get("id")
        if fid in CONTEXT_FLAGS:
            context.append({"flag": fid, "note": CONTEXT_FLAGS[fid]})
            continue
        m = FLAG_INVALIDATION_MAP.get(fid)
        if not m:
            continue
        slots = m.get("slots") or ([m["slot"]] if m.get("slot") else [])
        bucket = by_slot_hard if m.get("severity") == "hard" else by_slot_watch
        for s in slots:
            bucket.setdefault(s, []).append({"line": m.get("line"), "flag": fid})

    rows = []
    for h in (holdings or []):
        if not isinstance(h, dict) or not h.get("ticker"):
            continue
        tkr = h["ticker"]
        slot = h.get("slot") or h.get("thesis_slot")
        sig = name_signals.get(tkr, {}) if isinstance(name_signals.get(tkr), dict) else {}
        lines = []
        for ln in SLOT_INVALIDATION_LINES.get(slot, []):
            tripped, severity, source = False, "standing", None
            low = ln.lower()
            if "jsf" in low and sig.get("jsf_severe"):
                tripped, severity, source = True, "hard", "jsf_severe"
            elif "rep floor" in low and sig.get("floor_breached"):
                tripped, severity, source = True, "hard", "floor_breached"
            else:
                for hf in by_slot_hard.get(slot, []):
                    if hf["line"] and hf["line"].lower()[:18] in low:
                        tripped, severity, source = True, "hard", hf["flag"]; break
            lines.append({"line": ln, "tripped": tripped, "severity": severity, "source": source})
        # soft watch lines added by flags (not in the standing list)
        watch_hits = []
        for wf in by_slot_watch.get(slot, []):
            watch_hits.append({"line": wf["line"], "tripped": True, "severity": "watch", "source": wf["flag"]})
        lines.extend(watch_hits)

        hard_tripped = [l for l in lines if l["tripped"] and l["severity"] == "hard"]
        watch_tripped = [l for l in lines if l["tripped"] and l["severity"] == "watch"]
        if hard_tripped:
            status, action = "INVALIDATED", "EXIT / rotate the slot"
        elif watch_tripped:
            status, action = "WATCH", "tighten / scout the hedge"
        else:
            status, action = "INTACT", "hold"
        rows.append({"ticker": tkr, "slot": slot, "status": status, "stop_action": action,
                     "lines": lines, "tripped": [l["line"] for l in (hard_tripped + watch_tripped)]})

    return {"names": rows, "context_flags": context,
            "invalidated": [r["ticker"] for r in rows if r["status"] == "INVALIDATED"],
            "watch": [r["ticker"] for r in rows if r["status"] == "WATCH"]}


def dry_powder(*, usdcad: Optional[dict] = None, weights: Optional[dict] = None,
               posture: Optional[dict] = None, entries: Optional[dict] = None,
               config: Optional[dict] = None) -> dict:
    """Dry-powder deployment rule. ``usdcad`` = the carry read (P2.3); ``entries`` = {ticker: entry
    label}. Returns where powder waits + a DEPLOY/HOLD/STAGGER stance + the names with a clean entry."""
    cfg = _cfg(config)
    tilt = (usdcad or {}).get("tilt")
    carry = (usdcad or {}).get("carry_pp")
    plabel = (_posture_label(posture) or "").upper()
    defensive = plabel in [p.upper() for p in cfg["defensive_postures"]]

    ok = [e.upper() for e in cfg["add_entry_ok"]]
    targets = [t for t, lab in (entries or {}).items()
               if str(lab or "").upper().replace("_", "-") in ok]
    if defensive:
        stance = "HOLD"; why = "defensive posture — hold powder, deploy only on a real dislocation"
    elif targets:
        stance = "DEPLOY"; why = f"clean entry on {', '.join(targets)} — deploy into them"
    else:
        stance = "STAGGER"; why = "no compelling entry — ladder in, don't chase"

    b = _num((weights or {}).get("B"))
    reserve_convexity = bool(b is not None and b >= float(cfg["convexity_reserve_bweight"]))
    powder_note = (f"hold dry powder in {tilt} (carry {carry:+.2f}pp)" if tilt and carry is not None
                   else (f"hold dry powder in {tilt}" if tilt else "currency tilt n/a"))
    return {"currency_tilt": tilt, "currency_carry_pp": carry, "powder_currency": powder_note,
            "stance": stance, "targets": targets, "reserve_convexity_tranche": reserve_convexity,
            "reason": why + ("; reserve a convexity tranche (crisis weight rich)" if reserve_convexity else "")}


def assess(holdings: Optional[list], *, scenario: Optional[dict] = None, sentinel: Optional[dict] = None,
           posture: Optional[dict] = None, usdcad: Optional[dict] = None, spear_weight: Any = None,
           name_signals: Optional[dict] = None, entries: Optional[dict] = None,
           config: Optional[dict] = None) -> dict:
    """Run all three gates and consolidate. Pulls scenario weights from ``scenario`` and the active
    flags from ``sentinel``+``scenario``; everything degrades gracefully when an input is absent."""
    weights = (scenario or {}).get("weights")
    flags = _gather_flags((sentinel or {}).get("flags"), (scenario or {}).get("flags"))
    sw = spear_weight
    if sw is None:
        for h in (holdings or []):
            if isinstance(h, dict) and h.get("ticker") == "AGA.V":
                sw = h.get("weight"); break
    nsig = name_signals or {}
    aga_sig = nsig.get("AGA.V", {}) if isinstance(nsig.get("AGA.V"), dict) else {}

    inval = invalidation_status(holdings, flags=flags, name_signals=nsig, config=config)
    aga_inv = next((r["status"] for r in inval["names"] if r["ticker"] == "AGA.V"), None)
    add = aga_add_gate(spear_weight=sw, weights=weights, posture=posture,
                       entry=(entries or {}).get("AGA.V"), aga_status=aga_inv,
                       jsf_severe=bool(aga_sig.get("jsf_severe")), config=config)
    powder = dry_powder(usdcad=usdcad, weights=weights, posture=posture, entries=entries, config=config)

    action_flags = []
    for t in inval["invalidated"]:
        action_flags.append({"id": "invalidation", "active": True, "level": "risk",
                             "text": f"{t} INVALIDATED — exit / rotate the slot", "ticker": t})
    if add["decision"] == "ADD":
        action_flags.append({"id": "aga_add", "active": True, "level": "good",
                             "text": add["reason"], "ticker": "AGA.V"})

    return {"aga_add": add, "invalidation": inval, "dry_powder": powder,
            "flags": action_flags, "glossary": {k: conditionals_tooltip(k) for k in CONDITIONALS_GLOSSARY},
            "note": "standing conditional actions — pre-committed rules over the live state, not discretionary calls"}
