"""
Run: ``python -m unittest test_conviction_health -v``  (stdlib only, no streamlit/numpy).

Locks the Phase 8 metric-health colour ramp so the Conviction-Mode colour coding
(green good · amber mid · red weak) cannot silently drift, and stays aligned with
the Asymmetry-Rating band cutoffs (8.5 / 7.0 / 5.0 / 3.0).
"""

import unittest

from conviction_health import (
    NEUTRAL, health_color, health_label, quality_color,
)

GREEN_STRONG, GREEN, AMBER, ORANGE, RED = (
    "#00E676", "#69F0AE", "#FFB74D", "#FF9800", "#FF5252")
# Rank a colour by health (higher = healthier) to assert monotonicity.
_RANK = {RED: 0, ORANGE: 1, AMBER: 2, GREEN: 3, GREEN_STRONG: 4}


class TestHealthColor(unittest.TestCase):
    def test_band_thresholds_match_rating_bands(self):
        # Cutoffs mirror asymmetry_rating BANDS: 8.5 / 7.0 / 5.0 / 3.0.
        self.assertEqual(health_color(9.2), GREEN_STRONG)
        self.assertEqual(health_color(8.5), GREEN_STRONG)   # inclusive lower edge
        self.assertEqual(health_color(7.4), GREEN)
        self.assertEqual(health_color(7.0), GREEN)
        self.assertEqual(health_color(6.0), AMBER)
        self.assertEqual(health_color(5.0), AMBER)
        self.assertEqual(health_color(4.0), ORANGE)
        self.assertEqual(health_color(3.0), ORANGE)
        self.assertEqual(health_color(1.5), RED)
        self.assertEqual(health_color(0.0), RED)

    def test_monotonic_non_decreasing(self):
        prev = -1
        s = 0.0
        while s <= 10.0:
            rank = _RANK[health_color(s)]
            self.assertGreaterEqual(rank, prev, f"colour got worse as score rose at {s}")
            prev = rank
            s += 0.1

    def test_unknown_is_calm_neutral_not_alarming(self):
        for bad in (None, "n/a", "", float("nan") and "x"):
            self.assertEqual(health_color(None if bad is None else bad), NEUTRAL)
        self.assertEqual(health_color("not-a-number"), NEUTRAL)

    def test_numeric_strings_are_accepted(self):
        self.assertEqual(health_color("8.6"), GREEN_STRONG)
        self.assertEqual(health_color("2"), RED)


class TestHealthLabel(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(health_label(8.0), "good")
        self.assertEqual(health_label(7.0), "good")
        self.assertEqual(health_label(5.5), "mid")
        self.assertEqual(health_label(4.0), "weak")
        self.assertEqual(health_label(1.0), "bad")
        self.assertEqual(health_label(None), "n/a")


class TestQualityColor(unittest.TestCase):
    def test_ribbon_tokens(self):
        # Tokens emitted by asymmetry_rating._confidence_ribbon.
        self.assertEqual(quality_color("full"), GREEN)
        self.assertEqual(quality_color("degraded"), AMBER)
        self.assertEqual(quality_color("sparse"), RED)

    def test_case_insensitive_and_synonyms(self):
        self.assertEqual(quality_color("FULL"), GREEN)
        self.assertEqual(quality_color(" Sparse "), RED)
        self.assertEqual(quality_color("moderate"), AMBER)

    def test_unknown_is_neutral(self):
        self.assertEqual(quality_color("whatever"), NEUTRAL)
        self.assertEqual(quality_color(None), NEUTRAL)
        self.assertEqual(quality_color(""), NEUTRAL)


if __name__ == "__main__":
    unittest.main()
