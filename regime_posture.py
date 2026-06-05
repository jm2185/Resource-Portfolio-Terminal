"""
Regime posture — the master temperature dial (Forge Phase 3).

Druckenmiller's discipline: the macro regime sets the master risk dial — *how hard you press and how
much dry powder you hold* — and bottom-up name work is downstream of it. This module turns the
engine's live regime read into one book-level **posture**: a stance (SPEAR EXPLOIT / BALANCED /
DEFENSIVE) and a size **cap** in [0.5, 1.25] that *composes* onto every name's verdict
("ACCUMULATE" under a tightened posture reads "ACCUMULATE, smaller / slower, 0.75x cap").

Critically, per the signal-coherence rules, posture is a **book-level dial, never a name-level rival
signal** — it modulates size and the visual temperature, it does not score a name buy/sell.

Grounded in the engine's own conventions (verified in engine.py):
  * **MRI** is the composite regime index — *low = risk-on* (pivot 50; <40 strongly risk-on, >60
    stress). It already integrates DXY / curve / liquidity, so it is the primary cap driver.
  * **real_yield** pivot is **2.0%** — above it is a headwind for the metals (the book's core
    exposure), below it a tailwind. This is the one overlay we add on top of MRI because the spear +
    ballast are real-yield sensitive in a way worth surfacing explicitly.
  * **dxy_mom** is signed (a bid dollar is a headwind); a minor tilt only, to avoid double-counting
    what MRI already contains.

Pure stdlib, fully testable. Every coefficient is a REASONED FIRST CALIBRATION (not backtested) —
the shape (risk-on lifts the cap, real-yield/DXY headwinds cut it) is the point; the magnitudes are
tunable.
"""
from __future__ import annotations

from typing import Optional

MRI_PIVOT = 50.0
MRI_RISK_ON = 40.0          # below -> risk-on stance
MRI_RISK_OFF = 60.0         # above -> defensive stance
REAL_YIELD_PIVOT = 2.0      # % — above is a headwind for the metals
CAP_FLOOR, CAP_CEIL = 0.5, 1.25


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def compute(*, mri: Optional[float] = None, net_tilt: Optional[str] = None,
            real_yield: Optional[float] = None, dxy_mom: Optional[float] = None) -> dict:
    """Book-level posture from the live regime. Returns {code, label, cap, headwind, drivers,
    rationale}. Degrades gracefully: with no signals it returns a neutral BALANCED / 1.0x posture."""
    mri = _num(mri)
    ry = _num(real_yield)
    dxy = _num(dxy_mom)
    tilt = str(net_tilt or "").strip().lower().replace("-", "_").replace(" ", "_")

    # ---- stance: regime tilt first (explicit), MRI as the fallback / tie-breaker ----------------
    if tilt in ("risk_on", "riskon"):
        risk_on, risk_off = True, False
    elif tilt in ("risk_off", "riskoff"):
        risk_on, risk_off = False, True
    else:
        risk_on = mri is not None and mri < MRI_RISK_ON
        risk_off = mri is not None and mri > MRI_RISK_OFF
    if risk_off:
        code, label = "defensive", "DEFENSIVE"
    elif risk_on:
        code, label = "spear_exploit", "SPEAR EXPLOIT"
    else:
        code, label = "balanced", "BALANCED"

    # ---- cap: start neutral, lift on tailwinds, cut on headwinds (bounded) ----------------------
    cap = 1.0
    drivers = []
    if mri is not None:
        adj = _clamp((MRI_PIVOT - mri) / 40.0 * 0.25, -0.25, 0.25)   # low MRI lifts, high MRI cuts
        cap += adj
        drivers.append({"name": "MRI", "value": round(mri, 1), "cap_adj": round(adj, 3)})
    if ry is not None:
        adj = _clamp(-(ry - REAL_YIELD_PIVOT) * 0.10, -0.20, 0.15)   # real-yield headwind on the metals
        cap += adj
        drivers.append({"name": "real_yield", "value": round(ry, 2), "cap_adj": round(adj, 3)})
    if dxy is not None and dxy != 0.0:
        adj = _clamp(-_clamp(dxy, -2.0, 2.0) * 0.05, -0.10, 0.10)    # bid dollar = minor headwind
        cap += adj
        drivers.append({"name": "dxy_mom", "value": round(dxy, 3), "cap_adj": round(adj, 3)})
    cap = round(_clamp(cap, CAP_FLOOR, CAP_CEIL), 2)

    headwind = cap < 1.0
    # the dominant cap mover (for the one-line rationale)
    top = max(drivers, key=lambda d: abs(d["cap_adj"]), default=None)
    if top is None:
        rationale = "no live regime signals — neutral posture"
    else:
        direction = "headwind" if top["cap_adj"] < 0 else "tailwind"
        rationale = f"{label.lower()} · {top['name']} {direction} (cap {cap:g}x)"

    return {
        "code": code,
        "label": label,
        "cap": cap,
        "headwind": headwind,
        "drivers": drivers,
        "rationale": rationale,
    }
