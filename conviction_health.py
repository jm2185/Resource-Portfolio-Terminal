"""
Conviction-Mode metric health -> colour. Single source of truth, zero dependencies.

The dashboard colours the overall Asymmetry Rating by band already; this module
extends the SAME palette and thresholds to the per-metric numbers (T/Q/V pillar
scores) and the data-quality label, so a glance reads health everywhere:

    green  = good   ·   amber = mid   ·   orange/red = weak / bad

Thresholds mirror the Asymmetry-Rating bands in ``asymmetry_rating`` (8.5 PRIME /
7.0 STRONG / 5.0 BALANCED / 3.0 WEAK) so a number's colour always agrees with the
band label it rolls up into. Keeping this pure (no streamlit/numpy) means it is
unit-testable on its own — the colour logic is locked by ``test_conviction_health.py``.
"""

from __future__ import annotations

# Calm grey for unknown / not-applicable — never alarms on missing data.
NEUTRAL = "#8C8C92"

# Canonical 0-10 health ramp (highest band first). Same hexes the dashboard
# already uses for the rating number, so the card shares one visual language.
_RAMP: tuple[tuple[float, str], ...] = (
    (8.5, "#00E676"),  # strong green — good
    (7.0, "#69F0AE"),  # green        — good
    (5.0, "#FFB74D"),  # amber        — mid
    (3.0, "#FF9800"),  # orange       — weak
    (0.0, "#FF5252"),  # red          — bad
)


def _as_float(score) -> float | None:
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def health_color(score) -> str:
    """Map a 0-10 health/score to a palette hex (green good -> red bad).

    Non-numeric / None returns the calm neutral grey rather than alarming.
    """
    s = _as_float(score)
    if s is None:
        return NEUTRAL
    for threshold, colour in _RAMP:
        if s >= threshold:
            return colour
    return _RAMP[-1][1]


def health_label(score) -> str:
    """Plain-language health bucket for natural hover text: good / mid / weak / bad."""
    s = _as_float(score)
    if s is None:
        return "n/a"
    if s >= 7.0:
        return "good"
    if s >= 5.0:
        return "mid"
    if s >= 3.0:
        return "weak"
    return "bad"


# Data-quality tokens emitted by asymmetry_rating._confidence_ribbon are
# full / degraded / sparse; synonyms are accepted so the mapping is robust to
# wording changes elsewhere.
_QUALITY = {
    "full": "#69F0AE", "high": "#69F0AE", "strong": "#69F0AE", "good": "#69F0AE",
    "degraded": "#FFB74D", "medium": "#FFB74D", "moderate": "#FFB74D",
    "partial": "#FFB74D", "mid": "#FFB74D",
    "sparse": "#FF5252", "low": "#FF5252", "thin": "#FF5252", "weak": "#FF5252",
}


def quality_color(label) -> str:
    """Colour a data-quality label (full/degraded/sparse, …). Unknown -> neutral grey."""
    if not label:
        return NEUTRAL
    return _QUALITY.get(str(label).strip().lower(), NEUTRAL)
