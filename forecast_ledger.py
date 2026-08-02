"""
Forecast ledger — standalone, resolvable predictions, Brier-scored without engine legs.

The calibration flywheel's existing trail (``conviction`` entries) scores confidence against a
FROZEN engine decision — ρ/φ/price legs the engine only computes for held/eval names. That leaves a
hole exactly where the desk forecasts most: calls on names it does NOT own ("the Aug 6 print
reaffirms the guide", "the Jul 29 low holds on retest", "SNDK is the weakest structural long over
12 months"). Those were landing as untyped notes with a scoring_note apologizing that they can't be
scored — every resolution a permanent loss of calibration signal.

A ``forecast`` is the minimal scoreable unit, deliberately engine-free:

    claim (falsifiable text) + confidence (0 < p < 1) + resolve_by (a date) → outcome (bool) → Brier

Disciplines, from the house rules:
  * **p is exclusive of 0 and 1** — certainty is not a forecast, and a 0/1 can never be
    distinguished from a fact by the scorer.
  * **resolve_by is mandatory and parseable** — a prediction with no horizon is a narrative.
    The book surfaces overdue-unresolved forecasts; leaving one open past its date is itself
    a calibration datum going stale.
  * **resolution supersedes** (append-only): the open forecast survives in the record; the
    resolution carries the outcome, the Brier score, and who called it.
  * **verbal→numeric mappings are labeled.** A "moderate-high" priced at 0.75 is a modeling
    choice; the entry says so (``confidence_source``) so the trail never pretends the operator
    typed a number they didn't.

The book-level read mirrors ``calibration.brier_aggregate``: mean Brier vs the ignorance baseline
(0.25), plus the over/under-confidence gap (mean p vs realized hit rate). Same honesty rule as the
scorecard: below MIN_N resolved, report the sample as COLD — no false percentages.

Pure stdlib. This module never writes — Living Memory I/O belongs to the caller (the MCP layer).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

#: The documented verbal→numeric mapping for handoff-style confidences. Using it stamps
#: ``confidence_source: verbal-mapped`` on the entry — never silently.
VERBAL_CONFIDENCE: dict = {"low": 0.35, "moderate": 0.60, "moderate-high": 0.75, "high": 0.85}

#: Below this many resolved forecasts the book is COLD — report counts, not percentages.
MIN_N = 5

#: Brier of always-saying-0.5 — the ignorance baseline a calibrated forecaster must beat.
IGNORANCE_BRIER = 0.25


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _parse_date(x: Any) -> Optional[datetime]:
    s = str(x or "").strip().replace("Z", "+00:00")
    if not s:
        return None
    for fmt in (None, "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- shape + validation
def new_forecast(claim: str, confidence: Any, resolve_by: str, *, subject: str = "",
                 basis: str = "", confidence_source: str = "operator",
                 fid: str = "") -> dict:
    """Build + validate a forecast meta body. Raises ``ValueError`` on anything unscoreable —
    a malformed forecast must be rejected at write, not discovered at resolution."""
    text = str(claim or "").strip()
    if not text:
        raise ValueError("forecast.claim is required (a falsifiable statement)")
    p = _num(confidence)
    if p is None or not (0.0 < p < 1.0):
        raise ValueError(f"confidence {confidence!r} must be a probability strictly between 0 and 1 "
                         f"(certainty is not a forecast); verbal levels map via VERBAL_CONFIDENCE "
                         f"{VERBAL_CONFIDENCE}")
    if _parse_date(resolve_by) is None:
        raise ValueError(f"resolve_by {resolve_by!r} must be a parseable date (YYYY-MM-DD) — "
                         f"a prediction with no horizon is a narrative")
    return {"kind": "forecast", "forecast_id": str(fid or "").strip(),
            "claim": text, "confidence": round(p, 4),
            "confidence_source": str(confidence_source or "operator"),
            "resolve_by": str(resolve_by).strip()[:10],
            "subject": str(subject or "").strip(), "basis": str(basis or "").strip(),
            "status": "open"}


def brier(confidence: Any, outcome: Any) -> Optional[float]:
    """The Brier score of one resolved forecast: (p − o)², o ∈ {0, 1}. Lower is better;
    0.25 is the ignorance line. None if the confidence is unusable."""
    p = _num(confidence)
    if p is None:
        return None
    return round((p - (1.0 if outcome else 0.0)) ** 2, 4)


def resolve_meta(meta: dict, outcome: Any, *, note: str = "", resolved_at: str = "") -> dict:
    """The resolution body: the original forecast + outcome + Brier, status ``resolved``. The
    caller supersedes the open entry with this. Refuses to resolve twice (the score is immutable —
    a corrected outcome is a NEW supersession chain, visibly, not a quiet re-score)."""
    if not isinstance(meta, dict) or meta.get("kind") != "forecast":
        raise ValueError("not a forecast entry")
    if meta.get("status") == "resolved":
        raise ValueError("forecast already resolved — supersede the resolution explicitly "
                         "if the outcome was recorded wrongly")
    out = dict(meta)
    o = bool(outcome)
    out.update({"status": "resolved", "outcome": o,
                "brier": brier(meta.get("confidence"), o),
                "resolution_note": str(note or ""),
                "resolved_at": str(resolved_at or "")[:10]})
    return out


# --------------------------------------------------------------------------- the book
def book(entries: list, *, now: Any = None) -> dict:
    """The forecast book over live memory entries (type ``forecast``, superseded already hidden by
    the store). Open forecasts sorted soonest-resolving first, overdue flagged; resolved ones
    aggregated into mean Brier vs ignorance + the over/under-confidence gap. COLD below MIN_N."""
    ref = _parse_date(now) or datetime.now(timezone.utc)
    open_rows, resolved_rows = [], []
    for e in entries or []:
        m = e.get("meta") or {}
        if m.get("kind") != "forecast":
            continue
        row = {"id": e.get("id"), "forecast_id": m.get("forecast_id") or None,
               "claim": m.get("claim"), "confidence": m.get("confidence"),
               "confidence_source": m.get("confidence_source"),
               "subject": m.get("subject") or e.get("ticker"),
               "resolve_by": m.get("resolve_by"), "made": str(e.get("ts") or "")[:10]}
        if m.get("status") == "resolved":
            row.update({"outcome": m.get("outcome"), "brier": m.get("brier"),
                        "resolved_at": m.get("resolved_at"),
                        "note": m.get("resolution_note")})
            resolved_rows.append(row)
        else:
            due = _parse_date(m.get("resolve_by"))
            row["days_to_resolve"] = (due - ref).days if due else None
            row["overdue"] = bool(due and due < ref)
            open_rows.append(row)
    open_rows.sort(key=lambda r: r.get("resolve_by") or "9999")
    resolved_rows.sort(key=lambda r: r.get("resolved_at") or "", reverse=True)

    scored = [r for r in resolved_rows if r.get("brier") is not None]
    agg: dict = {"resolved": len(scored), "cold": len(scored) < MIN_N,
                 "min_n": MIN_N, "ignorance_brier": IGNORANCE_BRIER}
    if scored:
        mean_b = sum(r["brier"] for r in scored) / len(scored)
        mean_p = sum(r["confidence"] for r in scored) / len(scored)
        hit = sum(1 for r in scored if r["outcome"]) / len(scored)
        gap = mean_p - hit
        agg.update({
            "mean_brier": round(mean_b, 4),
            "beats_ignorance": mean_b < IGNORANCE_BRIER,
            "mean_confidence": round(mean_p, 4), "hit_rate": round(hit, 4),
            "confidence_gap": round(gap, 4),
            # the gap only earns a LABEL at a warm sample — a 2-forecast "overconfident" is noise
            "read": ("COLD sample — counts only, no verdict" if agg["cold"] else
                     ("overconfident" if gap > 0.10 else
                      "underconfident" if gap < -0.10 else "calibrated")),
        })
    overdue = [r for r in open_rows if r.get("overdue")]
    return {"open": open_rows, "resolved": resolved_rows, "aggregate": agg,
            "overdue": overdue,
            "line": (f"{len(open_rows)} open ({len(overdue)} overdue) · {len(scored)} resolved"
                     + (f" · Brier {agg['mean_brier']:.3f} vs 0.25 ({agg['read']})"
                        if scored and not agg["cold"] else ""))}
