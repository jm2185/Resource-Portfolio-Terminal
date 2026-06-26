"""Tests for forecast_share — the Lynch guardrail (forecast vs business, measure-only, context-aware)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import forecast_share as fs


class TestForecastShare(unittest.TestCase):

    def test_ballast_drag_above_threshold_warns(self):
        # a ballast whose rating is held DOWN by the forecast (full 6.0 vs business 8.0 = 25%... push higher)
        r = fs.forecast_share_read(6.0, 8.0, archetype="asset_light_yield")
        self.assertAlmostEqual(r["forecast_share"], 0.333, places=2)
        self.assertEqual(r["direction"], "drag")
        self.assertEqual(r["flag"]["level"], "warn")
        self.assertTrue(r["flag"]["flagged"])
        self.assertIn("suppressing", r["read"])
        self.assertEqual(r["business_rating"], 8.0)

    def test_ballast_small_footprint_is_business_driven(self):
        # THE GROY CASE: T weight is only 0.15, so the forecast barely moves the rating. The meter must
        # say "stands on the business" — i.e. the nerf is the (honest) quality penalty, NOT the forecast.
        r = fs.forecast_share_read(6.9, 7.1, archetype="asset_light_yield")
        self.assertLess(r["forecast_share"], 0.05)
        self.assertEqual(r["flag"]["level"], "ok")
        self.assertFalse(r["flag"]["flagged"])
        self.assertIn("stands on the business", r["read"])

    def test_spear_high_share_is_by_design_not_an_alarm(self):
        # a convex spear riding the regime is the THESIS — high share, but info not warn, never "flagged".
        r = fs.forecast_share_read(8.0, 5.0, archetype="option_convexity")
        self.assertGreater(r["forecast_share"], 0.30)
        self.assertTrue(r["forecast_native"])
        self.assertEqual(r["flag"]["level"], "info")
        self.assertFalse(r["flag"]["flagged"])       # by-design ⇒ not an alarm
        self.assertIn("BY DESIGN", r["read"])

    def test_ballast_tailwind_above_threshold_warns_paid_by_regime(self):
        r = fs.forecast_share_read(8.0, 5.5, archetype="asset_light_yield")
        self.assertEqual(r["direction"], "tailwind")
        self.assertEqual(r["flag"]["level"], "warn")
        self.assertIn("paid by the", r["read"])

    def test_neutral_when_forecast_does_not_move_it(self):
        r = fs.forecast_share_read(7.0, 7.0, archetype="asset_light_yield")
        self.assertEqual(r["direction"], "neutral")
        self.assertEqual(r["forecast_share"], 0.0)
        self.assertEqual(r["flag"]["level"], "ok")

    def test_pure_macro_delta_is_forecast_native(self):
        r = fs.forecast_share_read(7.0, 4.5, archetype="pure_macro_delta")
        self.assertTrue(r["forecast_native"])
        self.assertEqual(r["flag"]["level"], "info")

    def test_posture_surfaced_separately_not_in_share(self):
        r = fs.forecast_share_read(6.9, 7.0, archetype="asset_light_yield", posture_factor=0.94)
        self.assertEqual(r["posture_size_cap"], 0.94)        # surfaced as a SEPARATE sizing dial
        # ...and it does NOT inflate the rating share (that's only the macro-off gap)
        self.assertLess(r["forecast_share"], 0.05)

    def test_config_threshold_override(self):
        # tighten the threshold so a small footprint trips the flag
        r = fs.forecast_share_read(6.0, 6.6, archetype="asset_light_yield",
                                   config={"forecast_share": {"flag_threshold": 0.05}})
        self.assertTrue(r["flag"]["flagged"])

    def test_bad_inputs_unavailable(self):
        self.assertFalse(fs.forecast_share_read(None, 7.0)["available"])
        self.assertFalse(fs.forecast_share_read(7.0, None)["available"])
        self.assertFalse(fs.forecast_share_read(0.0, 5.0)["available"])


if __name__ == "__main__":
    unittest.main()
