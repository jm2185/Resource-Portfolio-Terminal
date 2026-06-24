"""
Tests for quality_lenses.py — archetype-native Q. The point isn't just that it runs; it's that a
royalty and a holdco get scored on their OWN lenses (operator quality, balance sheet, accretion) so the
reads the market-confidence proxy erased come back: GROY's ~30%/yr dilution drags a genuinely good
royalty book to MIDDLING quality, and GMX's recurring-coverage weakness shows through its strong vault.
"""
import unittest

import quality_lenses as q


class TestLensSetSelection(unittest.TestCase):
    def test_holdco_detected_on_subarchetype(self):
        self.assertTrue(q.is_holdco({"subarchetype": "royalty_generator_holdco"}))
        self.assertTrue(q.is_holdco({"subarchetype": "project_generator_holdco"}))
        self.assertEqual(q.lens_set_for({"archetype": "asset_light_yield",
                                         "subarchetype": "royalty_generator_holdco"}), "holdco")

    def test_royalty_is_asset_light_yield_but_not_a_holdco(self):
        self.assertTrue(q.is_royalty({"archetype": "asset_light_yield"}))
        self.assertEqual(q.lens_set_for({"archetype": "asset_light_yield"}), "royalty")

    def test_explorer_has_no_native_set(self):
        self.assertIsNone(q.lens_set_for({"archetype": "option_convexity"}))
        out = q.quality_lenses_for({"archetype": "option_convexity"}, {"producing_royalty_count": 5})
        self.assertFalse(out["available"])               # explorer keeps the resource checklist


class TestRoyaltyLenses(unittest.TestCase):
    GROY = {"producing_royalty_count": 6, "tier1_operator_fraction": 0.75, "top_line_fraction": 0.85,
            "cashflow_coverage": 1.5, "share_growth_rate": 0.30}

    def test_groy_dilution_drags_a_good_book_to_middling(self):
        out = q.quality_lenses_for({"archetype": "asset_light_yield"}, self.GROY)
        self.assertTrue(out["available"])
        self.assertEqual(out["basis"], "royalty_lenses")
        self.assertEqual(out["lenses"]["operator_quality"], 0.75)     # the book itself is good
        self.assertEqual(out["lenses"]["accretion"], 0.0)             # but 30%/yr dilution = zero accretion
        self.assertTrue(0.48 <= out["q_a"] <= 0.54)                   # net: MIDDLING, not "high quality royalty"

    def test_killing_the_dilution_lifts_quality(self):
        clean = dict(self.GROY, share_growth_rate=0.0)
        hi = q.quality_lenses_for({"archetype": "asset_light_yield"}, clean)["q_a"]
        lo = q.quality_lenses_for({"archetype": "asset_light_yield"}, self.GROY)["q_a"]
        self.assertGreater(hi, lo + 0.15)                            # accretion discipline matters a lot

    def test_weights_renormalize_over_present_lenses(self):
        out = q.quality_lenses_for({"archetype": "asset_light_yield"},
                                   {"tier1_operator_fraction": 0.8, "top_line_fraction": 0.6})
        self.assertTrue(out["available"])
        self.assertAlmostEqual(sum(out["weights"].values()), 1.0, places=3)
        self.assertIn("accretion", out["missing"])                  # not fed → dropped, not invented


class TestHoldcoLenses(unittest.TestCase):
    GMX = {"asset_count": 270, "net_liquid_to_mktcap": 0.376, "share_growth_rate": 0.007,
           "cashflow_coverage": 0.29}

    def test_gmx_strong_vault_with_visible_coverage_weakness(self):
        out = q.quality_lenses_for({"archetype": "asset_light_yield",
                                    "subarchetype": "project_generator_holdco"}, self.GMX)
        self.assertEqual(out["basis"], "holdco_lenses")
        self.assertGreater(out["lenses"]["capital_allocation"], 0.95)  # flat share count = disciplined
        self.assertEqual(out["lenses"]["cashflow_coverage"], 0.0)       # PG doesn't self-fund — shown, not hidden
        self.assertTrue(0.64 <= out["q_a"] <= 0.72)                     # strong overall, weakness visible

    def test_balance_sheet_is_the_dominant_lens(self):
        rich = q.quality_lenses_for({"subarchetype": "holdco"}, dict(self.GMX, net_liquid_to_mktcap=0.5))
        thin = q.quality_lenses_for({"subarchetype": "holdco"}, dict(self.GMX, net_liquid_to_mktcap=0.0))
        self.assertGreater(rich["q_a"] - thin["q_a"], 0.15)            # 0.35 weight => biggest mover


class TestDegradesLoudly(unittest.TestCase):
    def test_no_inputs_is_unavailable_and_lists_missing(self):
        out = q.quality_lenses_for({"archetype": "asset_light_yield"}, {})
        self.assertFalse(out["available"])
        self.assertEqual(out["lens_set"], "royalty")
        self.assertTrue(set(out["missing"]) >= {"diversification", "operator_quality", "accretion"})


if __name__ == "__main__":
    unittest.main()
