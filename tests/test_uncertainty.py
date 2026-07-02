"""Distributional intrinsic (Phase 3) — determinism, fail-closed monotonicity, drivers, and the
ribbon/conviction wiring in asymmetry_rating."""
from __future__ import annotations

import unittest

import uncertainty as unc
from asymmetry_rating import compute_asymmetry_rating


LEGS = {"cost": 1.0, "market": 2.0}
WEIGHTS = {"cost": 0.3, "market": 0.7}


class SigmaMapTests(unittest.TestCase):
    def test_grades_map_and_fail_closed(self):
        hi, fc = unc.sigma_for("high")
        med, _ = unc.sigma_for("med")
        lo, _ = unc.sigma_for("low")
        self.assertTrue(hi < med < lo)
        self.assertFalse(fc)
        absent, fc = unc.sigma_for(None)
        self.assertEqual(absent, lo)                   # absent grade -> LOW treatment
        self.assertTrue(fc)                            # ...and it is FLAGGED, never silent

    def test_staleness_widens_capped(self):
        fresh, _ = unc.sigma_for("high", age_days=0)
        stale, _ = unc.sigma_for("high", age_days=180)
        self.assertAlmostEqual(stale, fresh * 2.0, places=6)
        very, _ = unc.sigma_for("high", age_days=100000)
        self.assertAlmostEqual(very, fresh * 3.0, places=6)   # staleness_max_mult cap


class DistributionTests(unittest.TestCase):
    def test_deterministic_for_a_seed(self):
        a = unc.intrinsic_distribution(LEGS, WEIGHTS, leg_confidence={"cost": "high", "market": "med"})
        b = unc.intrinsic_distribution(LEGS, WEIGHTS, leg_confidence={"cost": "high", "market": "med"})
        self.assertEqual((a["p10"], a["p50"], a["p90"]), (b["p10"], b["p50"], b["p90"]))

    def test_monotonic_widening_on_downgrade(self):
        """The fail-closed property as an executable test: downgrade an input high->low and the
        band must strictly widen."""
        tight = unc.intrinsic_distribution(LEGS, WEIGHTS,
                                           leg_confidence={"cost": "high", "market": "high"})
        wide = unc.intrinsic_distribution(LEGS, WEIGHTS,
                                          leg_confidence={"cost": "high", "market": "low"})
        self.assertGreater(wide["rel_width"], tight["rel_width"])

    def test_absent_confidence_flagged(self):
        d = unc.intrinsic_distribution(LEGS, WEIGHTS, leg_confidence={"cost": "high"})
        self.assertIn("market", d["fail_closed"])

    def test_drivers_sum_to_one_and_name_the_swing(self):
        d = unc.intrinsic_distribution(LEGS, WEIGHTS,
                                       leg_confidence={"cost": "high", "market": "low"})
        self.assertAlmostEqual(sum(x["share"] for x in d["drivers"]), 1.0, places=2)
        self.assertEqual(d["drivers"][0]["input"], "market")   # the low-confidence heavy leg

    def test_empirical_sigma_override(self):
        assumed = unc.intrinsic_distribution(LEGS, WEIGHTS,
                                             leg_confidence={"cost": "high", "market": "low"})
        measured = unc.intrinsic_distribution(LEGS, WEIGHTS,
                                              leg_confidence={"cost": "high", "market": "low"},
                                              leg_sigma={"market": 0.05})
        self.assertLess(measured["rel_width"], assumed["rel_width"])

    def test_no_participating_legs(self):
        self.assertIsNone(unc.intrinsic_distribution({}, {}))
        self.assertIsNone(unc.intrinsic_distribution({"cost": -1.0}, {"cost": 1.0}))


def _asset(leg_confidence):
    return {
        "ticker": "AGA.V", "archetype": "option_convexity", "price": 0.61,
        "floor": 0.52, "base": 1.05, "bull": 2.10, "bear": 0.48,
        "mri": 45.0, "regime_alpha": 0.5, "forensic_score": 3.6, "conviction": 0.6,
        "data_quality": "full",
        "legs": dict(LEGS), "leg_weights": dict(WEIGHTS), "leg_confidence": leg_confidence,
    }


class RibbonWiringTests(unittest.TestCase):
    def test_ribbon_carries_quantiles_when_legs_present(self):
        r = compute_asymmetry_rating(_asset({"cost": "high", "market": "high"}))
        rb = r["confidence_ribbon"]
        self.assertEqual(rb.get("band_source"), "distribution")
        self.assertTrue(rb["p10"] < rb["p50"] < rb["p90"])
        self.assertIn("plus_minus", rb)                # legacy shape preserved for consumers

    def test_wider_band_earns_less_conviction(self):
        """End-to-end fail-closed: same asset, inputs downgraded -> band widens -> rating
        non-increasing (the lift precision scaling)."""
        tight = compute_asymmetry_rating(_asset({"cost": "high", "market": "high"}))
        wide = compute_asymmetry_rating(_asset({"cost": "low", "market": "low"}))
        self.assertGreater(wide["confidence_ribbon"]["rel_width"],
                           tight["confidence_ribbon"]["rel_width"])
        self.assertLessEqual(wide["rating"], tight["rating"])
        self.assertLessEqual(wide["conviction_lift"], tight["conviction_lift"])

    def test_no_legs_falls_back_to_heuristic(self):
        a = _asset({})
        for k in ("legs", "leg_weights", "leg_confidence"):
            a.pop(k)
        r = compute_asymmetry_rating(a)
        rb = r["confidence_ribbon"]
        self.assertNotIn("band_source", rb)
        self.assertIn("plus_minus", rb)                # the heuristic ± still ships


class QuantileInterpolationTests(unittest.TestCase):
    """Audit F5: linear interpolation between order statistics, not index-rounding — removes the
    ~0.5% quantile bias the PIT coverage test would otherwise grade against an 80% claim."""

    def test_quantiles_match_known_normal_within_tolerance(self):
        # build a near-symmetric distribution: single med-confidence leg, value 1.0, weight 1.0
        d = unc.intrinsic_distribution({"x": 1.0}, {"x": 1.0}, leg_confidence={"x": "med"},
                                       cfg={"n_draws": 20000, "seed": 7})
        # mean-preserving factor f = exp(σz − σ²/2): MEAN is 1.0, but MEDIAN is exp(−σ²/2);
        # quantiles are exp(±1.2816·σ − σ²/2).
        import math
        sig = 0.25
        exp_p10 = math.exp(-1.2816 * sig - 0.5 * sig * sig)
        exp_p50 = math.exp(-0.5 * sig * sig)
        exp_p90 = math.exp(1.2816 * sig - 0.5 * sig * sig)
        self.assertAlmostEqual(d["p10"], exp_p10, delta=0.02)
        self.assertAlmostEqual(d["p90"], exp_p90, delta=0.02)
        self.assertAlmostEqual(d["p50"], exp_p50, delta=0.01)

    def test_interpolation_is_deterministic(self):
        a = unc.intrinsic_distribution(LEGS, WEIGHTS, leg_confidence={"cost": "high", "market": "med"})
        b = unc.intrinsic_distribution(LEGS, WEIGHTS, leg_confidence={"cost": "high", "market": "med"})
        self.assertEqual((a["p10"], a["p50"], a["p90"]), (b["p10"], b["p50"], b["p90"]))


class NumericConfidenceTests(unittest.TestCase):
    """Pre-flight hardening P1 — the engine speaks numeric tilts (v5_config triangulation.confidence:
    cost 0.9, market 0.85, income 0.2); the sigma map must accept BOTH vocabularies, fail-closing only
    on a value that fits neither."""

    def test_numeric_maps_to_ordinal_grades(self):
        for numeric, ordinal in ((0.9, "high"), (0.85, "high"), (0.6, "med"),
                                 (0.5, "med"), (0.2, "low"), (0.0, "low")):
            s_num, fc = unc.sigma_for(numeric)
            s_ord, _ = unc.sigma_for(ordinal)
            self.assertEqual(s_num, s_ord, f"{numeric} should grade as {ordinal}")
            self.assertFalse(fc, f"{numeric} is a VALID grade — must not fail-close")

    def test_malformed_still_fails_closed(self):
        for bad in (None, "", "very-high", 1.5, -0.1):
            sigma, fc = unc.sigma_for(bad)
            self.assertTrue(fc, f"{bad!r} fits neither vocabulary — must fail closed")
            self.assertEqual(sigma, unc.DEFAULTS["confidence_sigma_rel"]["low"])

    def test_engine_shaped_leg_confidence_no_false_fail_closed(self):
        """The LIVE engine shape: numeric confidences must propagate without flooding
        fail_closed (the pre-fix behavior treated every leg as ungraded → max sigma)."""
        d = unc.intrinsic_distribution(
            {"cost": 1.0, "market": 2.0, "income": 0.5},
            {"cost": 0.3, "market": 0.5, "income": 0.2},
            leg_confidence={"cost": 0.9, "market": 0.85, "income": 0.2})
        self.assertEqual(d["fail_closed"], [])
        all_low = unc.intrinsic_distribution(
            {"cost": 1.0, "market": 2.0, "income": 0.5},
            {"cost": 0.3, "market": 0.5, "income": 0.2},
            leg_confidence={"cost": 0.2, "market": 0.2, "income": 0.2})
        self.assertLess(d["rel_width"], all_low["rel_width"])   # graded ≠ worst-case treatment


if __name__ == "__main__":
    unittest.main()
