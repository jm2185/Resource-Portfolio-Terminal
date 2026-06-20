"""Tests for commodity_regime — each metal has its own structural drivers; uranium is decoupled
from PMs. P1.1: the tailwind is FORWARD-STRUCTURAL (levels), and near-term momentum is a SEPARATE,
labeled factor (compute_momentum) that never enters the structural lean."""
import unittest

import commodity_regime as cr


class CommodityRegimeStructuralTests(unittest.TestCase):
    """compute() is the structural (forward) tailwind — built from LEVELS only."""

    def test_gold_vs_uranium_differ_same_macro(self):
        macro = {"real_yield": -0.5, "gsr": 88.0, "uranium_term": -0.6}
        g = cr.compute("gold", **macro)
        u = cr.compute("uranium", **macro)
        self.assertNotEqual(g, u)                     # gold ≠ uranium under the same macro
        self.assertGreater(g, 0)                      # falling real yields → structural gold tailwind
        self.assertLess(u, 0)                          # negative term structure → uranium headwind

    def test_gold_is_real_yield_level_not_dollar_momentum(self):
        # P1.1: gold's structural tailwind tracks the real-yield LEVEL and ignores the dollar TAPE.
        deep = cr.compute("gold", real_yield=-1.0)
        rich = cr.compute("gold", real_yield=3.0)
        self.assertGreater(deep, rich)                # lower real yield → higher structural tailwind
        # dxy momentum must NOT move the structural lean (it lives in compute_momentum).
        self.assertEqual(cr.compute("gold", real_yield=0.0, dxy_mom=-2.0),
                         cr.compute("gold", real_yield=0.0, dxy_mom=+2.0))

    def test_uranium_structural_is_term_not_momentum(self):
        # P1.1: uranium's structural driver is the TERM market (supply/demand structure), NOT spot
        # price momentum. uranium_mom must not move the structural lean.
        self.assertEqual(cr.compute("uranium", uranium_term=0.5), 0.5)
        self.assertEqual(cr.compute("uranium", uranium_term=-0.3), -0.3)
        self.assertEqual(cr.compute("uranium", uranium_mom=0.9, real_yield=-2.0), 0.0)  # momentum ignored
        # neutral (0.0) until the term monitor feeds a read — never a momentum stand-in.
        self.assertEqual(cr.compute("uranium"), 0.0)

    def test_silver_adds_gsr_to_gold_monetary(self):
        # Silver = gold's monetary driver (real-yield level) + its own structural relative-value (GSR).
        base = {"real_yield": 0.0}
        gold = cr.compute("gold", **base)
        silver_cheap = cr.compute("silver", gsr=95.0, **base)    # contrarian-cheap vs gold
        self.assertGreater(silver_cheap, gold * 0.5)             # silver-specific structural lift present

    def test_silver_ignores_riskon_tape_in_structural(self):
        # P1.1: the risk-on positioning/sentiment term moved to compute_momentum — it must NOT move
        # the structural silver lean.
        base = {"real_yield": 0.0, "gsr": 80.0}
        self.assertEqual(cr.compute("silver", risk_on=0.9, **base),
                         cr.compute("silver", risk_on=-0.9, **base))

    def test_low_gsr_is_silver_leadership_tailwind(self):
        # Engine's GSR thesis (engine.py GSR signal + metric def): GSR < 75 = silver LEADERSHIP =
        # bullish; the 75–85 band is balanced. Pins the U-shape (and the old-inversion fix).
        base = {"real_yield": 0.0}
        lead = cr.compute("silver", gsr=62.0, **base)       # silver leading (the live regime)
        neutral = cr.compute("silver", gsr=80.0, **base)    # balanced band
        self.assertGreater(lead, neutral)                   # leadership lifts vs balanced
        self.assertGreater(lead, 0.0)                       # and it's a tailwind, not a headwind

    def test_gsr_is_u_shaped_both_extremes_bullish(self):
        # Both extremes lift silver (leadership at low GSR, contrarian-cheap at high GSR); the
        # 75–85 band is balanced (flat).
        base = {"real_yield": 0.0}
        low, mid_a, mid_b, high = (cr.compute("silver", gsr=g, **base) for g in (62.0, 78.0, 82.0, 95.0))
        self.assertGreater(low, mid_a)                      # leadership > balanced
        self.assertGreater(high, mid_b)                     # contrarian-cheap > balanced
        self.assertAlmostEqual(mid_a, mid_b)                # 75–85 band is flat

    def test_diversified_is_a_blend(self):
        macro = {"real_yield": -0.5, "gsr": 88.0}
        d = cr.compute("diversified", **macro)
        g, s = cr.compute("gold", **macro), cr.compute("silver", **macro)
        self.assertAlmostEqual(d, max(-1.0, min(1.0, 0.5 * g + 0.5 * s)), places=2)

    def test_unknown_commodity_is_none_not_faked(self):
        self.assertIsNone(cr.compute("platinum", real_yield=-1.0))
        self.assertIsNone(cr.compute(None))

    def test_clamped_to_unit_range(self):
        self.assertLessEqual(cr.compute("gold", real_yield=-10.0), 1.0)
        self.assertGreaterEqual(cr.compute("uranium", uranium_term=-9.0), -1.0)


class CommodityMomentumTests(unittest.TestCase):
    """compute_momentum() is the SEPARATE, LABELED near-term factor — never part of the tailwind."""

    def test_momentum_carries_the_dollar_and_price_tape(self):
        # The backward-looking tape that was stripped from the structural lean lives HERE.
        weak_usd = cr.compute_momentum("gold", dxy_mom=-2.0)   # weak dollar → positive near-term
        strong_usd = cr.compute_momentum("gold", dxy_mom=+2.0)
        self.assertGreater(weak_usd, strong_usd)
        self.assertEqual(cr.compute_momentum("uranium", uranium_mom=0.5), 0.5)
        self.assertEqual(cr.compute_momentum("uranium", uranium_mom=-0.3), -0.3)

    def test_silver_momentum_includes_riskon(self):
        hot = cr.compute_momentum("silver", dxy_mom=0.0, risk_on=0.9)
        cold = cr.compute_momentum("silver", dxy_mom=0.0, risk_on=-0.9)
        self.assertGreater(hot, cold)

    def test_momentum_unknown_commodity_is_none(self):
        self.assertIsNone(cr.compute_momentum("platinum", dxy_mom=-1.0))
        self.assertIsNone(cr.compute_momentum(None))

    def test_momentum_clamped_to_unit_range(self):
        self.assertLessEqual(cr.compute_momentum("gold", dxy_mom=-20.0), 1.0)
        self.assertGreaterEqual(cr.compute_momentum("uranium", uranium_mom=-9.0), -1.0)


class StructuralMomentumSeparationTests(unittest.TestCase):
    """The P1.1 invariant: structural and momentum are independent channels. A strong-secular name
    in a weak near-term tape scores a HIGH structural tailwind regardless of momentum (the GROY shape)."""

    def test_strong_secular_weak_tape_keeps_high_structural(self):
        # GROY-shape: deep-negative real yields (structural gold tailwind) but a strong-dollar
        # near-term tape (negative momentum). The structural tailwind must stay HIGH and be
        # untouched by the weak tape.
        structural = cr.compute("gold", real_yield=-1.0, dxy_mom=+2.0)   # strong dollar tape
        self.assertGreaterEqual(structural, 0.9)                         # secular tailwind intact
        momentum = cr.compute_momentum("gold", real_yield=-1.0, dxy_mom=+2.0)
        self.assertLess(momentum, 0.0)                                   # near-term tape is negative
        # The two channels disagree by design — momentum never drags the structural lean down.
        self.assertGreater(structural, momentum)

    def test_compute_ignores_all_momentum_inputs(self):
        # Passing the full live signal bundle, the momentum keys must not perturb the structural lean.
        base = dict(real_yield=-0.5, gsr=70.0, uranium_term=0.2)
        for commodity in ("gold", "silver", "uranium", "diversified"):
            clean = cr.compute(commodity, **base)
            noisy = cr.compute(commodity, **base, dxy_mom=-1.7, uranium_mom=0.8, risk_on=0.6)
            self.assertEqual(clean, noisy, f"{commodity}: momentum leaked into the structural lean")


if __name__ == "__main__":
    unittest.main()
