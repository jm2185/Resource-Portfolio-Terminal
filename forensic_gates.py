"""
Forensic gate helpers — pure, stdlib, unit-testable in isolation (the engine wires them in).

``runway_aware_dilution_pass`` fixes a misleading forensic: the JSF dilution test is raw QoQ share
expansion vs a 2% bar, weighted 35% of the explorer penalty. But a pre-revenue explorer funds itself
BY issuing equity, so a one-time strategic raise reads identically to death-spiral dilution — even
though it just *lowered* forward dilution risk by buying runway. The real danger signal is dilution
that FAILS to leave an adequate runway (raising into weakness at bad terms), not dilution per se.

This nets dilution against the runway it bought:
  * raw pass            — dilution below the QoQ threshold (unchanged behaviour);
  * runway-insulated    — over the threshold, BUT the treasury clears ``runway_min_months`` (× an
                          optional comfort multiple) and the step-up is below the catastrophic
                          ceiling → it's FUNDING, pass;
  * fail                — over the threshold with inadequate runway (death-spiral shape), OR a
                          catastrophic single-period expansion (a distress signal even if it bought
                          runway).

Fully backward-compatible: ``enabled=False`` restores the raw ``< threshold`` test.
"""
from __future__ import annotations

from typing import Tuple


def _f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if v == v else default          # NaN guard
    except (TypeError, ValueError):
        return default


def runway_aware_dilution_pass(*, dilution, runway_months,
                               max_qoq_dilution_pct: float = 2.0,
                               runway_min_months: float = 18.0,
                               enabled: bool = True,
                               runway_comfort_mult: float = 1.0,
                               catastrophic_pct: float = 50.0) -> Tuple[bool, str, bool]:
    """Return ``(passed, reason, runway_insulated)``.

    ``dilution`` is the fractional QoQ share expansion (e.g. 0.30 = +30%); ``runway_months`` is
    cash / monthly burn. ``runway_insulated`` is True only when the pass is *earned by runway*
    (not a raw sub-threshold pass), so callers can label it honestly and never silently.
    """
    d = max(0.0, _f(dilution))
    raw_pass = d < (_f(max_qoq_dilution_pct, 2.0) / 100.0)
    if raw_pass:
        return True, f"below QoQ dilution threshold ({d * 100:.1f}%)", False
    if not enabled:
        return False, f"share count expanded ({d * 100:.1f}%)", False

    r = _f(runway_months)
    catastrophic = d >= (_f(catastrophic_pct, 50.0) / 100.0)
    comfortable = r >= _f(runway_min_months, 18.0) * _f(runway_comfort_mult, 1.0)
    if catastrophic:
        return False, f"catastrophic single-period dilution ({d * 100:.0f}%)", False
    if comfortable:
        return True, f"dilution funded runway ({r:.1f} mo) — insulated", True
    return False, f"share count expanded ({d * 100:.1f}%) without adequate runway ({r:.1f} mo)", False
