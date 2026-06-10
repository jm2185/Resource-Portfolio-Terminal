"""
Replay & grading harness — Phase 2 of docs/VALIDATION_FLYWHEEL_PLAN.md.

"Given only what was stamped at T, what did the model say, and what happened over the next N
days?" Grades valuation-ledger snapshots (``valuation_ledger.py``) against the cached daily-close
store (``price_history.py``) — never a live quote, so a replay is reproducible.

Mode A — as-stamped grading (no engine re-run), four grades per snapshot/horizon:
  * **Convergence** — did price move toward intrinsic? Sign-agreement of the stamped gap vs the
    realized move, plus gap-closure (how much of the gap closed).
  * **Band coverage** — did the realized price land inside the claimed band? P10–P90 when the
    snapshot carries a distributional ribbon (the honest PIT test), else the ladder [floor, bull].
  * **Floor reliability** — the lowest close over the window vs the stamped REP floor.
  * Directive expectancy stays with ``calibration.score_outcome`` via the decision↔snapshot join —
    no duplicate machinery here.

Mode B — counterfactual replay on frozen state:
  * ``recompute_blend`` — reconcile a snapshot's stamped intrinsic against its own frozen legs ×
    weights (the golden-ledger regression seam: code drift that silently rewrites what the model
    "would have said" fails this).
  * ``counterfactual`` — re-grade the whole ledger under a caller-supplied snapshot transform
    (e.g. a scaled REP floor) and diff the reports — the receipts engine for a ``/confirm``
    parameter proposal.

Feedback path: ``ledger_priors`` folds the grade counts into ``base_rates.update_beta`` per
archetype (floor reliability / band coverage posteriors).

Small-n honesty (house style): event COUNTS are always shown (counts don't lie at small n);
convergence expectancy is suppressed below MIN_N with an explicit ``data_limited`` flag.

Pure stdlib.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable, Optional

try:
    import base_rates as br
except Exception:                                      # priors are an enhancement, never a hard dep
    br = None

HORIZONS = (30, 90, 180)
MIN_N = 5                                              # mirrors calibration.MIN_PERSONAL_N

#: claimed containment of the distributional ribbon (P10–P90). The PIT test compares measured
#: coverage against this; persistent divergence is the evidence for a /confirm sigma-map proposal.
CLAIMED_COVERAGE = 0.80
#: a floor counts as TESTED (not just held-from-afar) when the window low came within this of it.
FLOOR_TEST_PROXIMITY = 0.10


def _num(x) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _snap_date(snap: dict):
    try:
        return datetime.strptime(str(snap.get("ts") or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
#  Mode A — as-stamped grading
# --------------------------------------------------------------------------- #
def grade_snapshot(snap: dict, history, horizon_days: int) -> Optional[dict]:
    """Grade ONE snapshot at one horizon against the price store. Returns None when the horizon
    hasn't elapsed or the store has no usable mark (an honest skip, never a fabricated grade)."""
    t0 = _snap_date(snap)
    ticker = snap.get("ticker")
    p0 = _num(snap.get("price"))
    iv = _num(snap.get("intrinsic"))
    if t0 is None or not ticker or p0 is None or p0 <= 0:
        return None
    horizon_date = t0 + timedelta(days=int(horizon_days))
    mark = history.close_on(ticker, horizon_date)
    if mark is None or str(mark.get("date") or "") <= t0.isoformat():
        return None                                    # horizon not reached / no data — skip
    pN = float(mark["close"])

    out: dict = {"ticker": ticker, "archetype": snap.get("archetype"),
                 "snapshot_id": snap.get("id"), "stamped": t0.isoformat(),
                 "horizon_days": int(horizon_days), "mark_date": mark["date"],
                 "price_t0": p0, "price_tN": pN,
                 "realized_return": round(pN / p0 - 1.0, 4)}

    # --- convergence: did price move toward intrinsic? ---
    if iv is not None and iv > 0:
        gap0 = (iv - p0) / p0
        gapN = (iv - pN) / pN
        realized = pN / p0 - 1.0
        sign_agree = (gap0 > 0 and realized > 0) or (gap0 < 0 and realized < 0) \
            if abs(gap0) > 1e-9 else None
        gap_closure = round((abs(gap0) - abs(gapN)) / abs(gap0), 4) if abs(gap0) > 1e-9 else None
        # Audit F4: gap_closure is mathematically correct but reads BACKWARD on an overshoot — a
        # name that rockets PAST intrinsic widens the (now-negative) gap and scores negative
        # closure, which an operator misreads as "the call failed". Label the regime so the number
        # is never read out of context: a successful bull call that overshot is a GAIN, just one
        # that closed its valuation window. The grade asks "did price move toward the estimate",
        # not "did the trade make money" — convergence_type + note keep that distinction explicit.
        convergence_type, note = None, None
        if abs(gap0) > 1e-9:
            crossed = (gap0 > 0) != (gapN > 0)         # price moved across intrinsic
            if crossed:
                convergence_type = "overshooting"
                note = ("price crossed THROUGH intrinsic — directionally right, but it kept going "
                        "past fair value (a gain that closed the valuation window, not a failure)")
            elif abs(gapN) < abs(gap0):
                convergence_type = "toward_intrinsic"
            elif sign_agree is False:
                convergence_type = "reversing"
                note = "price moved AWAY from intrinsic in the wrong direction"
            else:
                convergence_type = "widening"          # same side, gap grew (e.g. intrinsic ran ahead)
        out["convergence"] = {"gap_t0": round(gap0, 4), "gap_tN": round(gapN, 4),
                              "sign_agree": sign_agree, "gap_closure": gap_closure,
                              "convergence_type": convergence_type, "note": note}

    # --- band coverage: the PIT test (P10–P90 when stamped; ladder [floor, bull] otherwise) ---
    ribbon = snap.get("ribbon") or {}
    p10, p90 = _num(ribbon.get("p10")), _num(ribbon.get("p90"))
    ladder = snap.get("ladder") or {}
    floor, bull = _num(ladder.get("floor")), _num(ladder.get("bull"))
    if p10 is not None and p90 is not None:
        out["band"] = {"kind": "p10_p90", "lo": p10, "hi": p90,
                       "in_band": bool(p10 <= pN <= p90), "claimed": CLAIMED_COVERAGE}
    elif floor is not None and bull is not None:
        out["band"] = {"kind": "ladder_floor_bull", "lo": floor, "hi": bull,
                       "in_band": bool(floor <= pN <= bull), "claimed": None}

    # --- floor reliability: the lowest close over the window vs the stamped REP floor ---
    if floor is not None and floor > 0:
        lo = history.min_close(ticker, t0, horizon_date)
        if lo:
            held = lo["close"] >= floor
            tested = lo["close"] <= floor * (1.0 + FLOOR_TEST_PROXIMITY)
            out["floor"] = {"floor": floor, "window_low": lo["close"], "low_date": lo["date"],
                            "held": bool(held), "tested": bool(tested),
                            "breach_pct": (round((lo["close"] / floor - 1.0) * 100.0, 1)
                                           if not held else None)}
    return out


def grade_ledger(ledger, history, *, horizon_days: int = 90,
                 tickers: Optional[list] = None) -> list:
    """Mode A over the whole ledger (oldest-first). Snapshots whose horizon hasn't elapsed, or
    with no price data, are skipped — honest gaps, not fabricated grades."""
    grades = []
    for snap in ledger.query(limit=0, newest_first=False):
        if tickers and str(snap.get("ticker") or "").upper() not in {t.upper() for t in tickers}:
            continue
        g = grade_snapshot(snap, history, horizon_days)
        if g is not None:
            grades.append(g)
    return grades


def _expectancy_ci(vals: list, mass: float = 0.90) -> Optional[tuple]:
    n = len(vals)
    if n < 2:
        return None
    m = sum(vals) / n
    var = sum((x - m) ** 2 for x in vals) / (n - 1)
    se = (var / n) ** 0.5
    z = 1.645 if mass == 0.90 else 1.96
    return (round(m - z * se, 4), round(m + z * se, 4))


def _summary(grades: list) -> dict:
    """One grade-list → the report block: event COUNTS always; convergence expectancy only when
    warm (the reliability pattern)."""
    conv = [g["convergence"] for g in grades if g.get("convergence")]
    closures = [c["gap_closure"] for c in conv if c.get("gap_closure") is not None]
    signs = [c["sign_agree"] for c in conv if c.get("sign_agree") is not None]
    bands = [g["band"] for g in grades if g.get("band")]
    pit = [b for b in bands if b["kind"] == "p10_p90"]
    floors = [g["floor"] for g in grades if g.get("floor")]
    tested = [f for f in floors if f.get("tested")]
    n = len(grades)
    data_limited = n < MIN_N
    out = {
        "n": n,
        # --- event counts (always shown; counts don't lie at small n) ---
        "events": {
            "band_in": sum(1 for b in bands if b["in_band"]), "band_n": len(bands),
            "pit_in": sum(1 for b in pit if b["in_band"]), "pit_n": len(pit),
            "pit_claimed": CLAIMED_COVERAGE if pit else None,
            "floor_held": sum(1 for f in floors if f["held"]), "floor_n": len(floors),
            "floor_tested": len(tested),
            "floor_held_when_tested": sum(1 for f in tested if f["held"]),
            "sign_agree": sum(1 for s in signs if s), "sign_n": len(signs),
        },
        # --- convergence expectancy (suppressed when thin — the reliability pattern) ---
        "convergence": {
            "mean_gap_closure": (round(sum(closures) / len(closures), 4)
                                 if closures and not data_limited else None),
            "gap_closure_ci90": (_expectancy_ci(closures) if not data_limited else None),
            "n": len(closures),
        },
        "reliability": {
            "n": n, "data_limited": data_limited,
            "note": (None if not data_limited else
                     f"DATA-LIMITED (n={n}<{MIN_N}): read the event counts, not a point "
                     f"expectancy — the apparatus is warming, by design."),
        },
    }
    if pit:
        cov = out["events"]["pit_in"] / out["events"]["pit_n"]
        out["pit_coverage"] = {"measured": round(cov, 3), "claimed": CLAIMED_COVERAGE,
                               "gap": round(cov - CLAIMED_COVERAGE, 3),
                               "read": ("bands too NARROW — claimed containment not met; widen the "
                                        "sigma map (propose via /confirm)" if cov < CLAIMED_COVERAGE
                                        else "claimed containment met")}
    return out


def report(grades: list, *, by_archetype: bool = True) -> dict:
    """The valuation track record — the answer to "show me the alpha", with small-n honesty."""
    if not grades:
        return {"n": 0, "note": "no gradeable snapshots yet — the ledger is accruing; every day "
                                "of operation adds history (this is the apparatus, warming)."}
    out = _summary(grades)
    if by_archetype:
        groups: dict = {}
        for g in grades:
            groups.setdefault(g.get("archetype") or "_unknown", []).append(g)
        out["by_archetype"] = {a: _summary(rows) for a, rows in groups.items()}
    return out


# --------------------------------------------------------------------------- #
#  Feedback into priors (Phase 2.4)
# --------------------------------------------------------------------------- #
def ledger_priors(grades: list) -> dict:
    """Fold the grade counts into the base-rate registry's Bayesian update (per archetype):
    ``rep_floor_reliability`` (held / tested) and ``band_coverage`` posteriors. Returns {} when
    base_rates is unavailable — an enhancement, never a hard dependency."""
    if br is None or not grades:
        return {}
    groups: dict = {}
    for g in grades:
        groups.setdefault(g.get("archetype") or "_unknown", []).append(g)
    out: dict = {}
    for arch, rows in groups.items():
        floors = [g["floor"] for g in rows if g.get("floor")]
        tested = [f for f in floors if f.get("tested")]
        bands = [g["band"] for g in rows if g.get("band")]
        entry: dict = {}
        if tested:
            held = sum(1 for f in tested if f["held"])
            entry["floor_reliability"] = br.update_beta("rep_floor_reliability",
                                                        held, len(tested) - held)
        if bands:
            inb = sum(1 for b in bands if b["in_band"])
            entry["band_coverage"] = br.update_beta("band_coverage", inb, len(bands) - inb)
        if entry:
            out[arch] = entry
    return out


# --------------------------------------------------------------------------- #
#  Mode B — counterfactual replay on frozen state
# --------------------------------------------------------------------------- #
def recompute_blend(snap: dict, *, tolerance: float = 0.05) -> dict:
    """Golden-ledger reconciliation: recompute the confidence/weight blend from the snapshot's own
    FROZEN legs and compare to the stamped intrinsic. The stamped intrinsic may sit at or below the
    raw blend (forensic penalty ≤ 1 applies post-blend); a stamped value ABOVE the blend, or an
    implied penalty below the floor of plausibility, is drift — code rewriting history."""
    legs = (snap.get("legs") or {})
    values, weights = legs.get("values") or {}, legs.get("weights") or {}
    iv = _num(snap.get("intrinsic"))
    pairs = [(k, _num(values.get(k)), _num(weights.get(k))) for k in values]
    pairs = [(k, v, w) for k, v, w in pairs if v is not None and w is not None and w > 0]
    if iv is None or not pairs:
        return {"status": "unreconcilable", "reason": "snapshot lacks intrinsic or frozen legs"}
    blend = sum(v * w for _, v, w in pairs)
    wsum = sum(w for _, _, w in pairs)
    if wsum > 0 and abs(wsum - 1.0) > 1e-6:
        blend = blend / wsum                            # weights stored unnormalized — normalize
    if blend <= 0:
        return {"status": "unreconcilable", "reason": "non-positive blend"}
    # The 0.25 lower bound is the engine's MOST SEVERE forensic penalty (a DESIGN FLOOR, not a
    # buffer) — a legitimate snapshot at that state lands implied_penalty≈0.25, so it's reconciled,
    # not drift. A value BELOW 0.25 means the stamp came from a different blend formula than the
    # frozen legs imply (code drift) — that is the case the floor is here to catch (audit F5).
    implied_penalty = iv / blend
    ok = implied_penalty <= 1.0 + tolerance and implied_penalty >= 0.25
    return {"status": "reconciled" if ok else "DRIFT",
            "intrinsic_stamped": iv, "blend_recomputed": round(blend, 4),
            "implied_forensic_penalty": round(implied_penalty, 4),
            "note": (None if ok else
                     "stamped intrinsic is inconsistent with its own frozen legs×weights — "
                     "either the stamp or the blend math drifted; investigate before trusting "
                     "grades built on it.")}


def counterfactual(ledger, history, transform: Callable[[dict], dict], *,
                   horizon_days: int = 90, label: str = "counterfactual") -> dict:
    """Re-grade the whole ledger under a snapshot TRANSFORM (e.g. scale every REP floor by a
    candidate conservatism step) and diff the resulting report against the as-stamped baseline —
    the receipts table a /confirm parameter proposal attaches. The transform receives a COPY of
    each snapshot; the ledger itself is never touched (append-only, and this is read-side)."""
    baseline = grade_ledger(ledger, history, horizon_days=horizon_days)
    transformed = []
    for snap in ledger.query(limit=0, newest_first=False):
        try:
            alt = transform(dict(snap))
        except Exception:
            continue
        g = grade_snapshot(alt, history, horizon_days)
        if g is not None:
            transformed.append(g)
    base_rep, alt_rep = report(baseline, by_archetype=False), report(transformed, by_archetype=False)

    def _ev(rep):
        return (rep.get("events") or {})
    diff = {}
    for k in ("floor_held", "floor_tested", "floor_held_when_tested", "band_in", "band_n",
              "sign_agree"):
        b, a = _ev(base_rep).get(k), _ev(alt_rep).get(k)
        if b is not None or a is not None:
            diff[k] = {"baseline": b, "candidate": a}
    return {"label": label, "horizon_days": horizon_days,
            "baseline": base_rep, "candidate": alt_rep, "event_diff": diff,
            "note": ("evidence for a /confirm proposal — the flywheel PROPOSES, the operator "
                     "turns it; nothing here writes config.")}
