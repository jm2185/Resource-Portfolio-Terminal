"""
coherence_check.py — the terminal must never argue with itself, enforced at runtime (F3a).

The signal-coherence law is documented (ROADMAP §"Signal coherence") but nothing polices it live:
each surface (directive, posture, council verdict, memory pins) is individually correct while the
COMPOSITION quietly contradicts. This module encodes the known contradiction patterns as pure
deterministic checks over the engine's own state — the crystallized layer; anything semantic it
can't express stays with the dial-gated model pass, and a recurring model finding gets added HERE
as a new pattern.

Patterns (each finding: ``{id, ticker, level, signals, why}``):
  * ``rich_below_floor``          — an avoid-side directive (TRIM / RICH / DE-RISK) on a name
                                    trading BELOW its own stressed liquidation floor: the engine
                                    calls it rich under its own floor. One of the two is wrong.
  * ``severe_gate_bullish``       — a severe forensic gate (cap ≤ 5, the same bar council.reconcile
                                    uses to cap the Bull) beside an accumulate-side directive.
  * ``press_missing_cap_note``    — a PRESS / RE-AFFIRM verdict recorded under a sub-1x posture
                                    with no posture composition on it (the cap was dropped in the
                                    hand-off; reconcile always stamps it).
  * ``verdict_flip_unnamed``      — a recorded verdict whose stance opposes the engine directive
                                    with NO tension and NO caveats: reconcile always names the
                                    dissent, so a bare flip is a broken record, not a judgment.
  * ``stale_pinned_memory``       — a pinned Living-Memory entry that has been superseded: the desk
                                    is displaying a conclusion the record already corrected.
  * ``diversifier_cut_on_narrative`` — an avoid-side directive on a name the book's OWN correlation
                                    read scores as one of its least-correlated holdings. book_factor
                                    already alarms when a ballast drifts to ρ→1 (it stopped
                                    diversifying); this is the missing INVERSE — the measured
                                    diversifier being cut on a taxonomy argument.
  * ``cap_loosened_as_mri_rose``  — (cycle delta) the posture cap LOOSENED while MRI deteriorated
                                    materially in the same cycle: the dial moved against its own
                                    driver.

Decision-support ONLY (the cockpit_triggers contract): findings annotate, they never size, press,
cut, or veto. Pure stdlib; every input is plain data so the whole layer unit-tests without an
engine. ``calibration.infer_side`` is the single source of truth for directive side — no second
keyword list to drift.
"""
from __future__ import annotations

from typing import Any, Optional

from calibration import infer_side

__all__ = ["SEVERE_GATE_CAP", "MRI_MATERIAL_RISE", "DIVERSIFIER_MARGIN", "snapshot",
           "check_state", "check_delta", "memory_inputs"]

#: the severe-forensic bar — MUST match council.reconcile's Bull-cap threshold (cap ≤ 5.0).
SEVERE_GATE_CAP = 5.0
#: an MRI rise this large in one cycle is a material deterioration (MRI is 0–100, pivot 50).
MRI_MATERIAL_RISE = 2.0
#: a name's ρ to the spear must sit at least this far BELOW the book's average pairwise ρ before it
#: counts as a genuine diversifier — being the "lowest pair" inside a tightly-clustered book means
#: nothing, and a margin keeps the check off ties and correlation noise.
DIVERSIFIER_MARGIN = 0.05

_PRESS_STANCES = ("PRESS", "RE-AFFIRM")


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _baskets(state: Optional[dict]) -> list:
    conv = (state or {}).get("conviction_mode") or {}
    return [b for b in (conv.get("baskets") or []) if isinstance(b, dict) and b.get("ticker")]


def snapshot(state: Optional[dict]) -> dict:
    """The small comparable shape ``check_delta`` diffs across cycles (the cockpit_events pattern)."""
    posture = (state or {}).get("posture") or {}
    return {"mri": _num((state or {}).get("mri")), "cap": _num(posture.get("cap"))}


def check_state(state: Optional[dict], *, verdicts: Optional[list] = None,
                pinned_entries: Optional[list] = None,
                superseded_ids: Optional[set] = None) -> dict:
    """One pass over the live state (+ optionally the latest per-name council verdicts and the
    memory pin board) → the contradiction findings. Pure and total: missing blocks check nothing
    (never guess, never raise)."""
    findings: list = []
    posture = (state or {}).get("posture") or {}
    cap = _num(posture.get("cap"))
    posture_code = str(posture.get("code") or "")

    # ---- per-name: directive vs the name's own floor / forensic gate -------------------------
    for b in _baskets(state):
        tk = b.get("ticker")
        directive = str(b.get("directive") or "")
        side = infer_side(directive) if directive else None
        ladder = b.get("ladder") or {}
        price = _num(ladder.get("price"))
        floor = _num(ladder.get("floor"))
        if side == "avoid" and price is not None and floor is not None and price < floor:
            findings.append({
                "id": "rich_below_floor", "ticker": tk, "level": "warn",
                "signals": {"directive": directive, "price": price, "floor": floor},
                "why": (f"{tk}: directive reads avoid-side ({directive}) while price "
                        f"{price:g} sits BELOW its own stressed floor {floor:g} — the engine calls "
                        f"it rich under its own liquidation value; one of the two is wrong")})
        gate = b.get("gate") or {}
        gcap = _num(gate.get("cap"))
        if bool(gate.get("applied")) and gcap is not None and gcap <= SEVERE_GATE_CAP \
                and side == "long" and any(k in directive.upper() for k in ("ACCUMULATE", "PRESS", "ADD")):
            findings.append({
                "id": "severe_gate_bullish", "ticker": tk, "level": "risk",
                "signals": {"directive": directive, "gate_cap": gcap,
                            "gate_reason": gate.get("reason")},
                "why": (f"{tk}: severe forensic gate (cap {gcap:g} ≤ {SEVERE_GATE_CAP:g}) beside an "
                        f"accumulate-side directive ({directive}) — the same bar that caps the "
                        f"Bull in council should be capping this surface too")})

    # ---- the measured diversifier vs an avoid-side directive on it ---------------------------
    # book_factor alarms when a ballast drifts to ρ→1 (it stopped diversifying). This is the
    # MISSING INVERSE, and the desk shipped the gap live: the GMX lesson (2026-09-04) — a holding
    # the desk had itself measured at the LOWEST ρ to the spear was cut on the argument that it
    # "duplicates diversification intra-factor", i.e. a taxonomy claim silently outranked the
    # desk's own number with the contradicting datum already on file. When the measurement and the
    # narrative disagree, the NARRATIVE carries the burden of proof — this finding makes that loud.
    conc = ((state or {}).get("book_factor") or {}).get("concentration") or {}
    spear_corr = conc.get("spear_corr") if isinstance(conc.get("spear_corr"), dict) else {}
    avg = _num(conc.get("avg_pairwise"))
    ranked = sorted(((t, _num(c)) for t, c in (spear_corr or {}).items() if _num(c) is not None),
                    key=lambda kv: kv[1])
    if avg is not None and len(ranked) >= 2:
        directives = {b.get("ticker"): str(b.get("directive") or "") for b in _baskets(state)}
        for rank, (tk, rho) in enumerate(ranked, start=1):
            directive = directives.get(tk) or ""
            if not directive or infer_side(directive) != "avoid" or rho > avg - DIVERSIFIER_MARGIN:
                continue
            findings.append({
                "id": "diversifier_cut_on_narrative", "ticker": tk, "level": "warn",
                "signals": {"directive": directive, "spear_corr": rho, "avg_pairwise": avg,
                            "rank": rank, "of": len(ranked), "spear": conc.get("spear")},
                "why": (f"{tk}: avoid-side directive ({directive}) on the book's #{rank}-of-"
                        f"{len(ranked)} LEAST correlated holding — ρ{rho:.2f} to "
                        f"{conc.get('spear') or 'the spear'} vs book avg ρ{avg:.2f}. This name IS "
                        f"the diversification, measured; an argument that it is redundant must "
                        f"outrank the desk's own number, not sidestep it")})

    # ---- recorded verdicts vs the frame they were recorded in --------------------------------
    for v in (verdicts or []):
        if not isinstance(v, dict):
            continue
        tk = v.get("ticker")
        stance = str(v.get("stance") or "").upper()
        if stance in _PRESS_STANCES and cap is not None and cap < 1.0 \
                and not v.get("posture_note") and posture_code:
            findings.append({
                "id": "press_missing_cap_note", "ticker": tk, "level": "warn",
                "signals": {"stance": stance, "posture_cap": cap, "posture": posture_code},
                "why": (f"{tk}: {stance} verdict recorded under a {cap:g}x posture with no cap "
                        f"composition — reconcile always stamps the posture note; it was dropped "
                        f"in the hand-off")})
        directive = str(v.get("engine_directive") or "")
        if directive and stance:
            v_side = "avoid" if any(k in stance for k in ("EXIT", "DE-RISK", "TRIM")) else "long"
            if v_side != infer_side(directive) and not v.get("tension") and not v.get("caveats"):
                findings.append({
                    "id": "verdict_flip_unnamed", "ticker": tk, "level": "warn",
                    "signals": {"stance": stance, "engine_directive": directive},
                    "why": (f"{tk}: verdict {stance} opposes the engine directive ({directive}) "
                            f"with no tension and no caveats — reconcile names dissent; a bare "
                            f"flip is a broken record, not a judgment")})

    # ---- the pin board vs the audit trail ----------------------------------------------------
    sup = superseded_ids or set()
    for e in (pinned_entries or []):
        if isinstance(e, dict) and e.get("id") in sup:
            findings.append({
                "id": "stale_pinned_memory", "ticker": e.get("ticker"), "level": "warn",
                "signals": {"entry_id": e.get("id"), "type": e.get("type")},
                "why": (f"pinned memory {e.get('id')} ({e.get('ticker') or 'book'}) has been "
                        f"superseded — the desk is displaying a conclusion the record already "
                        f"corrected; re-pin the successor or unpin")})

    read = ("coherent — no surface argues with another"
            if not findings else
            f"{len(findings)} contradiction(s): " + ", ".join(sorted({f['id'] for f in findings})))
    return {"findings": findings, "n": len(findings), "read": read}


def check_delta(prev_snap: Optional[dict], curr_snap: Optional[dict]) -> list:
    """Cycle-delta patterns over ``snapshot`` pairs. Cold start (no prev) checks nothing."""
    if not prev_snap or not curr_snap:
        return []
    findings = []
    p_mri, c_mri = _num(prev_snap.get("mri")), _num(curr_snap.get("mri"))
    p_cap, c_cap = _num(prev_snap.get("cap")), _num(curr_snap.get("cap"))
    if None not in (p_mri, c_mri, p_cap, c_cap) \
            and (c_mri - p_mri) >= MRI_MATERIAL_RISE and c_cap > p_cap:
        findings.append({
            "id": "cap_loosened_as_mri_rose", "ticker": None, "level": "warn",
            "signals": {"mri": [p_mri, c_mri], "cap": [p_cap, c_cap]},
            "why": (f"posture cap loosened {p_cap:g}x → {c_cap:g}x while MRI deteriorated "
                    f"{p_mri:g} → {c_mri:g} in the same cycle — the dial moved against its own "
                    f"driver; check which input overrode it")})
    return findings


def memory_inputs(mem) -> tuple:
    """Adapter: ``(pinned_entries, superseded_ids)`` from a LivingMemory instance, defensively —
    the checker itself stays plain-data. Any problem → empty inputs (check nothing, never raise)."""
    try:
        pinned = set(mem.pinned_ids())
        entries = [e for e in mem.all() if e.get("id") in pinned]
        sup = set(mem._superseded_ids())
        return entries, sup
    except Exception:
        return [], set()
