"""
Distributional intrinsic — P10/P50/P90 by input-confidence propagation (Phase 3 of
docs/VALIDATION_FLYWHEEL_PLAN.md).

Replaces the heuristic confidence-ribbon ± with REAL uncertainty propagation: every valuation leg
already carries a confidence grade (the research-cache high/med/low discipline and the
triangulation confidence tilts); this module turns those grades into a sampled distribution over
the blended intrinsic, so the model states its own precision — and the replay harness can grade
whether that statement meant anything (the PIT coverage test).

Two bands, kept distinct (do not conflate):
  * THIS is the **estimate band** — "how precisely do we know intrinsic, given input quality".
  * The scenario ladder (bear/base/bull) stays a set of THESIS legs — probability-weighted
    honestly by ``valuation_actions.ladder_expectation``, never by this module.

Mechanics (stdlib only, deterministic):
  * Light Monte Carlo (``random.Random(seed)``) over the legs: each leg gets a mean-preserving
    lognormal factor ``exp(σz − σ²/2)`` with σ from its confidence grade (fail-closed: an absent
    grade is treated as ``low`` and flagged), optionally widened by staleness and overridable by
    an EMPIRICAL σ (e.g. the peer-comp dispersion for the market leg — Phase 5 interlock).
  * Drivers by analytic variance attribution (exact for independent lognormal factors):
    ``Var(w·v·f) = (w·v)²(e^{σ²}−1)`` — so the Story Card can say "the width is 61% peer-comp".

Fail-closed is the contract: stale/low-confidence/absent inputs ⇒ a visibly wider band ⇒ (via the
conviction-lift precision scaling in ``asymmetry_rating``) automatically smaller conviction.
"""
from __future__ import annotations

import math
import random
from typing import Any, Optional

#: config-overridable via v5_config.json → "uncertainty" (route changes through /confirm).
DEFAULTS: dict[str, Any] = {
    "confidence_sigma_rel": {"high": 0.10, "med": 0.25, "low": 0.50},
    # the engine's triangulation confidences are NUMERIC tilts in [0,1] (v5_config →
    # triangulation.confidence: cost 0.9, market 0.85, …) while the research cache speaks
    # ordinal high/med/low — both vocabularies are first-class here. Numeric grades map
    # through these thresholds; only a value in NEITHER vocabulary fails closed.
    "numeric_grade_thresholds": {"high": 0.80, "med": 0.50},
    "staleness_halflife_days": 180.0,   # sigma *= 1 + age/halflife, capped below
    "staleness_max_mult": 3.0,
    "n_draws": 2000,
    "seed": 47,
}


def _cfg(cfg: Optional[dict]) -> dict:
    out = dict(DEFAULTS)
    for k, v in (cfg or {}).items():
        if k == "confidence_sigma_rel" and isinstance(v, dict):
            m = dict(DEFAULTS["confidence_sigma_rel"])
            m.update(v)
            out[k] = m
        else:
            out[k] = v
    return out


def sigma_for(confidence, *, age_days: Optional[float] = None,
              cfg: Optional[dict] = None) -> tuple[float, bool]:
    """Relative σ for a confidence grade, staleness-widened. Accepts BOTH vocabularies: the
    ordinal high/med/low (research cache) and a numeric tilt in [0,1] (the engine's
    triangulation confidences — 0.9 ⇒ high, 0.6 ⇒ med, 0.3 ⇒ low via
    ``numeric_grade_thresholds``). Returns ``(sigma, fail_closed)`` — ``fail_closed=True`` only
    when the grade fits NEITHER vocabulary and the LOW treatment was substituted (the contract:
    never a fake 'med', and the substitution is visible)."""
    c = _cfg(cfg)
    grades = c["confidence_sigma_rel"]
    key = str(confidence if confidence is not None else "").strip().lower()
    if key not in grades:
        try:                                            # numeric vocabulary: a [0,1] tilt
            f = float(confidence)
            if f == f and 0.0 <= f <= 1.0:
                th = c["numeric_grade_thresholds"]
                key = ("high" if f >= float(th.get("high", 0.80))
                       else "med" if f >= float(th.get("med", 0.50)) else "low")
        except (TypeError, ValueError):
            pass
    fail_closed = key not in grades
    sigma = float(grades.get(key, grades["low"]))
    if age_days is not None and age_days > 0:
        half = max(1.0, float(c["staleness_halflife_days"]))
        sigma *= min(float(c["staleness_max_mult"]), 1.0 + float(age_days) / half)
    return sigma, fail_closed


def intrinsic_distribution(leg_values: dict, leg_weights: Optional[dict] = None, *,
                           leg_confidence: Optional[dict] = None,
                           leg_sigma: Optional[dict] = None,
                           leg_age_days: Optional[dict] = None,
                           forensic_penalty: float = 1.0,
                           cfg: Optional[dict] = None) -> Optional[dict]:
    """P10/P50/P90 of the blended intrinsic by propagating per-leg uncertainty.

    ``leg_values``      {leg: value} (the triangulation legs — cost/market/income, or any methods)
    ``leg_weights``     {leg: weight} (missing ⇒ equal; zero-weight legs don't participate)
    ``leg_confidence``  {leg: high|med|low} — absent grade ⇒ LOW, flagged (fail-closed)
    ``leg_sigma``       {leg: σ} EMPIRICAL overrides (e.g. peer-comp dispersion for "market")
    ``leg_age_days``    {leg: days} staleness widening per leg

    Returns ``{p10, p50, p90, rel_width, drivers, fail_closed, n_draws, seed}`` or None when no
    leg participates. Deterministic for a fixed seed (replayable)."""
    c = _cfg(cfg)
    leg_weights = leg_weights or {}
    leg_confidence = leg_confidence or {}
    leg_sigma = leg_sigma or {}
    leg_age_days = leg_age_days or {}

    legs = []
    fail_closed: list = []
    for name, raw in (leg_values or {}).items():
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v != v or v <= 0:
            continue
        w = leg_weights.get(name, 1.0 if not leg_weights else 0.0)
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = 0.0
        if w <= 0:
            continue
        if name in leg_sigma and leg_sigma[name] is not None:
            try:
                sigma = max(0.0, float(leg_sigma[name]))
            except (TypeError, ValueError):
                sigma, fc = sigma_for(None, cfg=c)
                fail_closed.append(name)
        else:
            sigma, fc = sigma_for(leg_confidence.get(name),
                                  age_days=leg_age_days.get(name), cfg=c)
            if fc:
                fail_closed.append(name)
        legs.append((name, v, w, sigma))
    if not legs:
        return None

    wsum = sum(w for _, _, w, _ in legs)
    try:
        pen = float(forensic_penalty)
    except (TypeError, ValueError):
        pen = 1.0
    if pen <= 0 or pen != pen:
        pen = 1.0

    # --- Monte Carlo for the quantiles (mean-preserving lognormal factors) ---
    n = max(100, int(c["n_draws"]))
    rng = random.Random(int(c["seed"]))
    draws = []
    for _ in range(n):
        total = 0.0
        for _, v, w, sigma in legs:
            z = rng.gauss(0.0, 1.0)
            f = math.exp(sigma * z - 0.5 * sigma * sigma) if sigma > 0 else 1.0
            total += v * f * w
        draws.append(pen * total / wsum)
    draws.sort()

    def _q(p: float) -> float:
        # Audit F5: linear interpolation between order statistics (NumPy 'linear' / type-7), not
        # index-rounding — rounding quantized P10/P90 to the nearest draw, biasing the band ~0.5%
        # at n=2000 and worse at small n, which the PIT coverage test then grades against an 80%
        # claim. Interpolation removes that bias for a multiply-add.
        idx = p * (n - 1)
        lo = int(idx)
        if lo >= n - 1:
            return draws[n - 1]
        frac = idx - lo
        return draws[lo] * (1.0 - frac) + draws[lo + 1] * frac
    p10, p50, p90 = _q(0.10), _q(0.50), _q(0.90)
    rel_width = (p90 - p10) / (2.0 * p50) if p50 > 0 else None

    # --- drivers by analytic variance attribution (exact for independent lognormals) ---
    vars_ = {name: (w * v / wsum) ** 2 * (math.exp(sigma * sigma) - 1.0)
             for name, v, w, sigma in legs}
    tot_var = sum(vars_.values())
    drivers = sorted(({"input": k, "share": round(v / tot_var, 3)} for k, v in vars_.items()
                      if tot_var > 0), key=lambda d: -d["share"])

    return {"p10": round(p10, 4), "p50": round(p50, 4), "p90": round(p90, 4),
            "rel_width": round(rel_width, 4) if rel_width is not None else None,
            "drivers": drivers,
            "fail_closed": sorted(set(fail_closed)),
            "n_draws": n, "seed": int(c["seed"])}
