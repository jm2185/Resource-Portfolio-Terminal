"""Tests for the Phase 7 T-Q-V Asymmetry Rating (Conviction Mode).

Run: ``python -m pytest test_asymmetry_rating.py -q``  (or ``python test_asymmetry_rating.py``).
Pure-Python, no numpy/pandas — mirrors the dependency-free design of the rating module.
"""

import unittest

from asymmetry_rating import (
    DEFAULT_CONVICTION_CONFIG,
    compute_asymmetry_rating,
    build_conviction_state,
    merge_conviction_config,
)


def _spear(**over):
    """A healthy Option-Convexity basket trading just below its REP floor (the AGA.V archetype
    at the documented May-2026 operating point)."""
    base = dict(
        ticker="AGA.V", archetype="option_convexity", archetype_code="I",
        price=0.71, floor=0.824, base=1.69, bull=1.95, bear=1.05,
        mri=40.2, regime_alpha=0.4, forensic_score=3.5, avg_tq=1.12,
        conviction=0.6, runway_months=22.0, dilution_velocity=0.0, data_quality="full",
    )
    base.update(over)
    return base


class TestPillars(unittest.TestCase):
    def test_all_pillars_and_rating_bounded(self):
        r = compute_asymmetry_rating(_spear())
        for p in ("T", "Q", "V"):
            self.assertGreaterEqual(r["pillars"][p]["score"], 0.0)
            self.assertLessEqual(r["pillars"][p]["score"], 10.0)
        self.assertGreaterEqual(r["rating"], 0.0)
        self.assertLessEqual(r["rating"], 10.0)

    def test_macro_tailwind_monotonic_in_mri(self):
        # Lower MRI (more risk-on) -> higher macro tailwind T.
        hi = compute_asymmetry_rating(_spear(mri=20.0))["pillars"]["T"]["score"]
        lo = compute_asymmetry_rating(_spear(mri=80.0))["pillars"]["T"]["score"]
        self.assertGreater(hi, lo)

    def test_macro_tailwind_responds_to_alpha(self):
        pos = compute_asymmetry_rating(_spear(regime_alpha=0.9))["pillars"]["T"]["score"]
        neg = compute_asymmetry_rating(_spear(regime_alpha=-0.9))["pillars"]["T"]["score"]
        self.assertGreater(pos, neg)

    def test_alpha_has_significant_influence_on_rating(self):
        # alpha_option must meaningfully move the FINAL rating for an Option Convexity asset.
        pos = compute_asymmetry_rating(_spear(regime_alpha=1.0))
        neg = compute_asymmetry_rating(_spear(regime_alpha=-1.0))
        self.assertGreater(pos["rating"] - neg["rating"], 1.5)   # >1.5 pts of swing from alpha alone
        self.assertGreater(pos["pillars"]["T"]["alpha_contribution"],
                           neg["pillars"]["T"]["alpha_contribution"])

    def test_option_convexity_leans_more_on_macro(self):
        # kappa is higher for option_convexity, so alpha moves T more than for a default archetype.
        oc = (compute_asymmetry_rating(_spear(archetype="option_convexity", regime_alpha=1.0))["pillars"]["T"]["score"]
              - compute_asymmetry_rating(_spear(archetype="option_convexity", regime_alpha=-1.0))["pillars"]["T"]["score"])
        yld = (compute_asymmetry_rating(_spear(archetype="asset_light_yield", regime_alpha=1.0))["pillars"]["T"]["score"]
               - compute_asymmetry_rating(_spear(archetype="asset_light_yield", regime_alpha=-1.0))["pillars"]["T"]["score"])
        self.assertGreater(oc, yld)

    def test_company_quality_rewards_forensics(self):
        clean = compute_asymmetry_rating(_spear(forensic_score=4.0))["pillars"]["Q"]["score"]
        dirty = compute_asymmetry_rating(_spear(forensic_score=2.0))["pillars"]["Q"]["score"]
        self.assertGreater(clean, dirty)

    def test_resource_quality_sources(self):
        # avg_tq and explicit resource_quality should map into [0,1] sensibly (fallbacks).
        q_tq = compute_asymmetry_rating(_spear(avg_tq=1.70))["pillars"]["Q"]["resource_quality"]
        q_lo = compute_asymmetry_rating(_spear(avg_tq=0.55))["pillars"]["Q"]["resource_quality"]
        self.assertAlmostEqual(q_tq, 1.0, places=3)
        self.assertAlmostEqual(q_lo, 0.0, places=3)
        # Fraser alone is now the 'jurisdiction' lens, normalized over the [50,95] band.
        a = _spear(); a.pop("avg_tq"); a["fraser_index"] = 84.0
        self.assertAlmostEqual(
            compute_asymmetry_rating(a)["pillars"]["Q"]["resource_quality"],
            (84.0 - 50) / (95 - 50), places=3)

    def test_mining_quality_checklist(self):
        # The Q pillar should read like a mining checklist when raw lenses are supplied.
        a = _spear(); a.pop("avg_tq")
        a.update(grade_gpt=290, resource_oz=270_000_000, fraser_index=84.2,
                 recovery=0.877, stage="PEA")
        r = compute_asymmetry_rating(a)
        lenses = r["pillars"]["Q"]["lenses"]
        for k in ("grade", "scale", "jurisdiction", "metallurgy", "permitting"):
            self.assertIn(k, lenses)
            self.assertGreaterEqual(lenses[k], 0.0)
            self.assertLessEqual(lenses[k], 1.0)
        self.assertAlmostEqual(lenses["scale"], 1.0, places=2)   # huge resource saturates scale
        self.assertLess(lenses["permitting"], 0.5)               # PEA is early-stage

    def test_management_blends_with_conviction(self):
        hi = compute_asymmetry_rating(_spear(management_score=1.0))["pillars"]["Q"]["management"]
        lo = compute_asymmetry_rating(_spear(management_score=0.0))["pillars"]["Q"]["management"]
        self.assertGreater(hi, lo)
        # Absent management_score falls back to the conviction read.
        none = compute_asymmetry_rating(_spear())["pillars"]["Q"]
        self.assertAlmostEqual(none["management"], none["conviction"], places=3)


class TestValuationAsymmetry(unittest.TestCase):
    def test_below_floor_saturates_support_and_payoff(self):
        # Price below the floor => downside-to-floor is zero, payoff saturates, support high.
        r = compute_asymmetry_rating(_spear(price=0.60, floor=0.824, bull=1.95))["pillars"]["V"]
        self.assertEqual(r["downside_to_floor_pct"], 0.0)
        self.assertGreaterEqual(r["floor_coverage"], 1.0)
        self.assertGreater(r["score"], 8.0)

    def test_symmetric_setup_scores_mid(self):
        # ~2:1 up/down to floor should land V_payoff near the half-saturation midpoint.
        r = compute_asymmetry_rating(_spear(price=1.0, floor=0.8, bull=1.4))["pillars"]["V"]
        # U=0.4, Df=0.2 -> rho=2 -> payoff=0.5
        self.assertAlmostEqual(r["payoff"], 0.5, places=2)

    def test_expensive_no_upside_scores_low(self):
        # Trading above the bull target with a distant floor => weak asymmetry.
        r = compute_asymmetry_rating(_spear(price=2.5, floor=0.824, base=1.69, bull=1.95))
        self.assertLess(r["pillars"]["V"]["score"], 3.5)
        self.assertEqual(r["pillars"]["V"]["upside_pct"], 0.0)

    def test_no_price_is_graceful(self):
        r = compute_asymmetry_rating(_spear(price=0.0))
        self.assertEqual(r["pillars"]["V"]["score"], 0.0)
        self.assertIsNotNone(r["rating"])


class TestGateAndRibbon(unittest.TestCase):
    def test_forensic_gate_caps_rating(self):
        r = compute_asymmetry_rating(_spear(forensic_score=1.0))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.0)

    def test_aggressive_dilution_caps_rating(self):
        r = compute_asymmetry_rating(_spear(dilution_velocity=0.20))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.5)
        self.assertIn("AVOID", r["directive"])

    def test_short_runway_caps_rating(self):
        r = compute_asymmetry_rating(_spear(runway_months=3.0))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.5)

    def test_dispersion_is_ribbon_not_penalty(self):
        # Sparse data must WIDEN the ribbon, not lower the point estimate vs the full-data case.
        full = compute_asymmetry_rating(_spear(data_quality="full"))
        sparse = compute_asymmetry_rating(_spear(data_quality="sparse"))
        self.assertEqual(full["rating"], sparse["rating"])             # identical point estimate
        self.assertGreater(sparse["confidence_ribbon"]["plus_minus"],
                           full["confidence_ribbon"]["plus_minus"])    # only the band widens

    def test_wide_scenario_band_widens_ribbon(self):
        tight = compute_asymmetry_rating(_spear(bull=1.8, bear=1.5))
        wide = compute_asymmetry_rating(_spear(bull=3.0, bear=0.3))
        self.assertGreater(wide["confidence_ribbon"]["plus_minus"],
                           tight["confidence_ribbon"]["plus_minus"])


class TestComposite(unittest.TestCase):
    def test_spear_operating_point_is_strong(self):
        # The documented AGA.V operating point should land in "Strong asymmetry" territory.
        r = compute_asymmetry_rating(_spear())
        self.assertGreaterEqual(r["rating"], 7.0)
        self.assertIn(r["band"], ("STRONG ASYMMETRY", "PRIME CONVICTION"))
        self.assertIn("WATCH", r["directive"].upper() + " " + ("ACCUMULATE" if "ACCUM" in r["directive"] else ""))

    def test_valuation_is_heaviest_pillar(self):
        pw = compute_asymmetry_rating(_spear())["pillar_weights"]
        self.assertGreater(pw["V"], pw["T"])
        self.assertGreater(pw["V"], pw["Q"])

    def test_band_labels_cover_range(self):
        self.assertEqual(compute_asymmetry_rating(_spear(price=0.60))["band"] in
                         {"PRIME CONVICTION", "STRONG ASYMMETRY"}, True)
        broken = compute_asymmetry_rating(_spear(forensic_score=0.5, price=2.5, bull=1.95))
        self.assertEqual(broken["band"], "BROKEN / AVOID")


class TestBuildConvictionState(unittest.TestCase):
    def test_builds_and_ranks(self):
        assets = [
            _spear(),
            _spear(ticker="GROY", archetype="asset_light_yield", price=3.2, floor=2.0,
                   base=3.4, bull=3.8, bear=2.9, regime_alpha=0.1, avg_tq=None,
                   fraser_index=72.0, forensic_score=3.0),
            _spear(ticker="BAD", forensic_score=0.5, dilution_velocity=0.3, price=2.0, bull=2.1),
        ]
        state = build_conviction_state(assets, config=None,
                                       meta={"mri": 40.2, "regime": "RISK-ON"})
        self.assertEqual(state["view"], "conviction")
        self.assertTrue(state["primary"])
        self.assertEqual(len(state["baskets"]), 3)
        # Sorted highest-rating first; the gated "BAD" name must rank last.
        ratings = [b["rating"] for b in state["baskets"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertEqual(state["baskets"][-1]["ticker"], "BAD")
        self.assertEqual(state["context"]["regime"], "RISK-ON")

    def test_one_bad_basket_never_breaks_the_view(self):
        state = build_conviction_state([{"ticker": "X", "price": "not-a-number"}])
        self.assertEqual(state["status"], "live")
        self.assertEqual(len(state["baskets"]), 1)


class TestConfig(unittest.TestCase):
    def test_partial_config_merge(self):
        cfg = merge_conviction_config({"conviction_mode": {"rho_half": 3.0}})
        self.assertEqual(cfg["rho_half"], 3.0)
        self.assertIn("q_weights", cfg)                       # untouched default preserved
        self.assertEqual(cfg["q_weights"]["forensic"], 0.45)

    def test_defaults_self_consistent(self):
        for arche, w in DEFAULT_CONVICTION_CONFIG["pillar_weights_by_archetype"].items():
            self.assertAlmostEqual(w["T"] + w["Q"] + w["V"], 1.0, places=6, msg=arche)


if __name__ == "__main__":
    unittest.main(verbosity=2)
