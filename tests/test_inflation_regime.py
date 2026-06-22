"""Inflation-regime monitor — unbundle the real yield. Breakeven derivation, the move decomposition
(nominal-led headwind vs breakeven-led deflation vs debasement tailwind), trend, and the quadrant."""
import unittest

import inflation_regime as ir


class BreakevenTests(unittest.TestCase):
    def test_breakeven_is_nominal_minus_real(self):
        self.assertEqual(ir.breakeven(4.50, 2.10), 2.40)

    def test_breakeven_none_on_missing_leg(self):
        self.assertIsNone(ir.breakeven(4.50, None))


class LevelReadTests(unittest.TestCase):
    def test_elevated_is_debasement_tailwind(self):
        r = ir.assess(nominal_10y=4.80, real_10y=2.20)            # be 2.60 ≥ be_hot 2.50
        self.assertEqual(r["bias"], "risk_on")
        self.assertIn("debasement", r["level_read"].lower())

    def test_disinflation_is_headwind(self):
        r = ir.assess(nominal_10y=4.00, real_10y=2.10)            # be 1.90 ≤ be_cold 2.00
        self.assertEqual(r["bias"], "risk_off")
        self.assertIn("disinflation", r["level_read"].lower())

    def test_anchored_is_neutral(self):
        r = ir.assess(nominal_10y=4.30, real_10y=2.10)            # be 2.20 in the band
        self.assertEqual(r["bias"], "neutral")
        self.assertIn("anchored", r["level_read"].lower())


class DecompositionTests(unittest.TestCase):
    def test_nominal_led_is_classic_gold_headwind(self):
        # real yield rose, driven by rising nominals; breakeven unchanged
        r = ir.assess(nominal_10y=4.50, real_10y=2.30,
                      prev_nominal_10y=4.30, prev_real_10y=2.10)
        self.assertEqual(r["driver"], "NOMINAL-LED")
        self.assertGreater(r["decomposition"]["d_real_yield"], 0)
        self.assertIn("headwind", r["decomp_read"].lower())
        self.assertFalse(r["flags"])

    def test_breakeven_led_collapse_is_deflationary_and_flags(self):
        # real yield rose because breakevens collapsed — the worse, distinct regime
        r = ir.assess(nominal_10y=4.00, real_10y=2.30,
                      prev_nominal_10y=4.10, prev_real_10y=2.00)
        self.assertEqual(r["driver"], "BREAKEVEN-LED")
        self.assertGreater(r["decomposition"]["d_real_yield"], 0)
        self.assertIn("deflationary", r["decomp_read"].lower())
        self.assertEqual(r["flags"][0]["id"], "deflation_watch")

    def test_breakeven_led_rise_is_debasement_tailwind(self):
        # real yield FELL because breakevens rose — best case for gold, no flag
        r = ir.assess(nominal_10y=4.20, real_10y=1.80,
                      prev_nominal_10y=4.10, prev_real_10y=2.00)
        self.assertEqual(r["driver"], "BREAKEVEN-LED")
        self.assertLess(r["decomposition"]["d_real_yield"], 0)
        self.assertIn("debasement", r["decomp_read"].lower())
        self.assertFalse(r["flags"])


class TrendAndQuadrantTests(unittest.TestCase):
    def test_trend_accelerating(self):
        r = ir.assess(nominal_10y=4.50, real_10y=1.90, prev_nominal_10y=4.30, prev_real_10y=2.10)
        self.assertTrue(r["be_rising"])
        self.assertIn("accelerating", r["trend"].lower())

    def test_quadrant_stagflation(self):
        # rising inflation expectations + slowing growth
        r = ir.assess(nominal_10y=4.50, real_10y=1.90, prev_nominal_10y=4.30, prev_real_10y=2.10,
                      growth_trend=-1.0)
        self.assertIn("STAGFLATION", r["quadrant"])

    def test_quadrant_heating(self):
        r = ir.assess(nominal_10y=4.50, real_10y=1.90, prev_nominal_10y=4.30, prev_real_10y=2.10,
                      growth_trend=1.0)
        self.assertIn("HEATING", r["quadrant"])

    def test_quadrant_absent_without_growth(self):
        r = ir.assess(nominal_10y=4.50, real_10y=1.90, prev_nominal_10y=4.30, prev_real_10y=2.10)
        self.assertIsNone(r["quadrant"])


class DormancyTests(unittest.TestCase):
    def test_dormant_without_inputs(self):
        r = ir.assess()
        self.assertFalse(r["available"])
        self.assertIsNone(r["breakeven"])

    def test_precomputed_breakeven_accepted(self):
        r = ir.assess(be=2.35)
        self.assertTrue(r["available"])
        self.assertEqual(r["breakeven"], 2.35)
        self.assertIsNone(r["driver"])                  # no priors → no decomposition, still graceful


if __name__ == "__main__":
    unittest.main()
