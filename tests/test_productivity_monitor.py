"""Tests for productivity_monitor (action-plan P2.2) — the AI-productivity thesis-breaker watch."""
import unittest

import productivity_monitor as pm


class BreadthTests(unittest.TestCase):
    def test_breadth_from_contributions_narrow_vs_broad(self):
        narrow = pm.assess([1.0, 1.0], industry_contributions={"tech": 9.0, "a": 0.3, "b": 0.3, "c": 0.4})
        broad = pm.assess([1.0, 1.0], industry_contributions={"tech": 1.0, "a": 1.0, "b": 1.0, "c": 1.0})
        self.assertLess(narrow["breadth"]["score"], broad["breadth"]["score"])
        self.assertAlmostEqual(broad["breadth"]["score"], 1.0, places=2)   # evenly spread = fully broad
        self.assertFalse(narrow["breadth"]["broad"])
        self.assertTrue(broad["breadth"]["broad"])

    def test_direct_breadth_scalar(self):
        r = pm.assess([1.5, 1.6], breadth=0.8)
        self.assertEqual(r["breadth"]["score"], 0.8)
        self.assertTrue(r["breadth"]["broad"])

    def test_broadening_needs_prior(self):
        widening = pm.assess([1.5, 1.6], breadth=0.7, breadth_prior=0.5)
        flat = pm.assess([1.5, 1.6], breadth=0.7, breadth_prior=0.69)
        self.assertTrue(widening["breadth"]["broadening"])
        self.assertFalse(flat["breadth"]["broadening"])


class TrajectoryTests(unittest.TestCase):
    def test_accelerating_detected(self):
        r = pm.assess([0.8, 1.0, 2.4, 2.8])           # older ~0.9, recent ~2.6 -> accelerating
        self.assertTrue(r["trajectory"]["accelerating"])
        self.assertTrue(r["trajectory"]["sustained"])  # recent mean >= 2.0

    def test_settling_not_accelerating(self):
        r = pm.assess([2.6, 2.4, 1.2, 1.0])           # decelerating back toward trend
        self.assertFalse(r["trajectory"]["accelerating"])

    def test_thin_series_is_graceful(self):
        r = pm.assess([1.5])
        self.assertIsNone(r["trajectory"]["accelerating"])
        self.assertEqual(r["trajectory"]["n"], 1)


class ThesisBreakerTests(unittest.TestCase):
    def test_broad_and_accelerating_trips_flag(self):
        r = pm.assess([0.8, 1.0, 2.4, 2.9], breadth=0.7, breadth_prior=0.5)
        self.assertTrue(any(f["id"] == "debasement_at_risk" for f in r["flags"]))
        self.assertEqual(r["zone"], "BROAD-ACCELERATING")

    def test_narrow_but_accelerating_does_not_trip(self):
        # real-but-narrow goldilocks: accelerating BUT concentrated -> debasement intact (no flag).
        r = pm.assess([0.8, 1.0, 2.4, 2.9], breadth=0.30, breadth_prior=0.28)
        self.assertEqual(r["flags"], [])

    def test_broad_but_flat_does_not_trip(self):
        # broad but settling (not accelerating) -> no thesis break.
        r = pm.assess([2.6, 2.4, 1.0, 0.9], breadth=0.8, breadth_prior=0.6)
        self.assertEqual(r["flags"], [])

    def test_broadening_raises_scenario_c_pressure(self):
        low = pm.assess([1.0, 1.1], breadth=0.3, breadth_prior=0.3)["scenario_c_pressure"]["score"]
        high = pm.assess([2.2, 2.6], breadth=0.8, breadth_prior=0.6)["scenario_c_pressure"]["score"]
        self.assertGreater(high, low)


class StructureTests(unittest.TestCase):
    def test_glossary_and_framing(self):
        r = pm.assess([1.5, 1.6], breadth=0.5)
        for k in ("productivity_monitor", "prod_breadth", "prod_trajectory", "debasement_at_risk"):
            self.assertIn(k, r["glossary"], k)
            self.assertTrue(r["glossary"][k])
        self.assertIn("pick-and-shovel", r["upstream_note"].lower())

    def test_empty_is_graceful(self):
        r = pm.assess(None)
        self.assertIsNone(r["breadth"]["score"])
        self.assertEqual(r["flags"], [])
        self.assertEqual(r["trajectory"]["n"], 0)

    def test_tooltip_unknown_key_empty(self):
        self.assertEqual(pm.productivity_tooltip("nope"), "")


if __name__ == "__main__":
    unittest.main()
