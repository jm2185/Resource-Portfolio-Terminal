"""Tests for commodity_regime — each metal has its own drivers; uranium is decoupled from PMs."""
import unittest

import commodity_regime as cr


class CommodityRegimeTests(unittest.TestCase):
    def test_gold_vs_uranium_differ_same_macro(self):
        macro = {"real_yield": -0.5, "dxy_mom": -1.0, "gsr": 88.0, "risk_on": 0.4, "uranium_mom": -0.6}
        g = cr.compute("gold", **macro)
        u = cr.compute("uranium", **macro)
        self.assertNotEqual(g, u)                     # gold ≠ uranium under the same macro
        self.assertGreater(g, 0)                      # falling real yields + weak USD → gold tailwind
        self.assertLess(u, 0)                          # uranium momentum negative → headwind

    def test_uranium_uses_its_own_cycle_only(self):
        # uranium ignores PM drivers; only its momentum matters
        self.assertEqual(cr.compute("uranium", uranium_mom=0.5, real_yield=-2.0, dxy_mom=-2.0), 0.5)
        self.assertEqual(cr.compute("uranium", uranium_mom=-0.3, real_yield=-2.0), -0.3)

    def test_silver_adds_gsr_and_riskon_to_gold(self):
        base = {"real_yield": 0.0, "dxy_mom": 0.0}
        gold = cr.compute("gold", **base)
        silver_cheap = cr.compute("silver", gsr=95.0, risk_on=0.8, **base)   # cheap vs gold + risk-on
        self.assertGreater(silver_cheap, gold * 0.5)   # silver-specific lift present

    def test_diversified_is_a_blend(self):
        macro = {"real_yield": -0.5, "dxy_mom": -1.0, "gsr": 88.0, "risk_on": 0.4}
        d = cr.compute("diversified", **macro)
        g, s = cr.compute("gold", **macro), cr.compute("silver", **macro)
        self.assertAlmostEqual(d, round(max(-1.0, min(1.0, 0.5 * g + 0.5 * s)), 3))

    def test_unknown_commodity_is_none_not_faked(self):
        self.assertIsNone(cr.compute("platinum", real_yield=-1.0))
        self.assertIsNone(cr.compute(None))

    def test_clamped_to_unit_range(self):
        self.assertLessEqual(cr.compute("gold", real_yield=-10.0, dxy_mom=-10.0), 1.0)
        self.assertGreaterEqual(cr.compute("uranium", uranium_mom=-9.0), -1.0)


if __name__ == "__main__":
    unittest.main()
