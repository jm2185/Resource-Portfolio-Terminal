"""Divergence / decoupling SENTINEL — leverage (factor explains the move) vs decoupling (residual on
size), the volume gate, direction, and graceful dormancy."""
import unittest

import divergence_monitor as dm


class LeverageVsDecouplingTests(unittest.TestCase):
    def test_move_with_the_factor_is_leverage_no_flag(self):
        # +12% while silver +6% at β1.9 → β explains +11.4%, residual ~+0.6% → boring leverage
        r = dm.assess(name_return=0.12, factor_return=0.06, beta=1.9, volume=4e5, adv=1e5, name="AGA.V")
        self.assertTrue(r["available"])
        self.assertFalse(r["flag"])
        self.assertLess(abs(r["residual"]), 0.06)
        self.assertFalse(r["sign_divergence"])

    def test_decoupled_up_on_size_flags(self):
        # +12% AGAINST silver −2% on 4× volume → +15.8% unexplained → DECOUPLED
        r = dm.assess(name_return=0.12, factor_return=-0.02, beta=1.9, volume=4e5, adv=1e5, name="AGA.V")
        self.assertTrue(r["flag"])
        self.assertEqual(r["direction"], "STRENGTH")
        self.assertTrue(r["sign_divergence"])
        self.assertAlmostEqual(r["residual"], 0.12 - (1.9 * -0.02), places=4)
        self.assertEqual(r["rvol"], 4.0)
        self.assertEqual(r["events"][0]["type"], "divergence")
        self.assertIn("DECOUPLED", r["read"])

    def test_decoupled_but_thin_volume_does_not_flag(self):
        # big residual but only 1.5× volume → a thin-tape wick, not real flow → no flag
        r = dm.assess(name_return=0.12, factor_return=-0.02, beta=1.9, volume=1.5e5, adv=1e5, name="AGA.V")
        self.assertFalse(r["flag"])
        self.assertFalse(r["on_size"])

    def test_decoupled_down_is_weakness(self):
        r = dm.assess(name_return=-0.10, factor_return=0.03, beta=1.5, volume=5e5, adv=1e5, name="AGA.V")
        self.assertTrue(r["flag"])
        self.assertEqual(r["direction"], "WEAKNESS")
        self.assertTrue(r["sign_divergence"])


class RobustnessTests(unittest.TestCase):
    def test_missing_beta_defaults_to_one(self):
        r = dm.assess(name_return=0.12, factor_return=-0.02, volume=4e5, adv=1e5)
        self.assertEqual(r["beta"], 1.0)
        self.assertAlmostEqual(r["residual"], 0.14, places=4)        # 0.12 − (1.0×−0.02)
        self.assertTrue(r["flag"])

    def test_no_adv_means_no_size_gate_no_flag(self):
        r = dm.assess(name_return=0.12, factor_return=-0.02, beta=1.9, volume=4e5, adv=0)
        self.assertIsNone(r["rvol"])
        self.assertFalse(r["flag"])                                  # can't confirm flow → no flag

    def test_dormant_without_returns(self):
        r = dm.assess(volume=4e5, adv=1e5, name="AGA.V")
        self.assertFalse(r["available"])
        self.assertFalse(r["flag"])

    def test_thresholds_are_config(self):
        # tighten residual_min so the same move no longer flags; loosen rvol so 2× passes
        r = dm.assess(name_return=0.12, factor_return=-0.02, beta=1.9, volume=2e5, adv=1e5,
                      config={"divergence_monitor": {"residual_min": 0.20, "rvol_min": 2.0}})
        self.assertEqual(r["rvol"], 2.0)
        self.assertTrue(r["on_size"])                                # 2× clears the loosened gate
        self.assertFalse(r["flag"])                                  # but residual 15.8% < 20% min


class SigmaNormalizationTests(unittest.TestCase):
    """Context-aware threshold: 'decoupled' means beyond normal FOR THIS NAME — a +6% residual flags a
    low-vol royalty but NOT the high-vol spear (the same number, opposite verdicts)."""

    def _r(self, sigma):                                  # +6% residual on a flat factor, 4× volume
        return dm.assess(name_return=0.06, factor_return=0.0, beta=1.0, volume=4e5, adv=1e5,
                         residual_sigma=sigma, name="X")

    def test_same_residual_flags_low_vol_not_high_vol(self):
        low = self._r(0.015)                             # low-vol royalty: 6% = 4σ → decoupled
        high = self._r(0.05)                             # high-vol spear: 6% = 1.2σ → normal, NOT decoupled
        self.assertTrue(low["flag"])
        self.assertEqual(low["decoupled_basis"], "sigma")
        self.assertAlmostEqual(low["z"], 4.0, places=1)
        self.assertFalse(high["flag"])
        self.assertAlmostEqual(high["z"], 1.2, places=1)

    def test_absolute_fallback_without_sigma(self):
        r = dm.assess(name_return=0.06, factor_return=0.0, beta=1.0, volume=4e5, adv=1e5, name="X")
        self.assertEqual(r["decoupled_basis"], "absolute")
        self.assertIsNone(r["z"])
        self.assertTrue(r["flag"])                       # 6% ≥ absolute 6% fallback

    def test_z_min_is_config(self):
        r = dm.assess(name_return=0.06, factor_return=0.0, beta=1.0, volume=4e5, adv=1e5,
                      residual_sigma=0.03, config={"divergence_monitor": {"z_min": 3.0}})
        self.assertAlmostEqual(r["z"], 2.0, places=1)
        self.assertFalse(r["flag"])                      # 2σ < 3σ threshold


class ExplainContextTests(unittest.TestCase):
    """The triage adapts to the NAME's type — factor, ETF basket, drill-relevance, insider system,
    corporate-event flavour — instead of a silver-explorer template."""

    def test_silver_spear_explorer(self):
        c = dm.explain_context(ticker="AGA.V", archetype="option_convexity", commodity="silver")
        self.assertEqual(c["factor"], "silver")
        self.assertIn("SILJ", c["etfs"])
        self.assertTrue(c["drill_relevant"])
        self.assertIn("SEDI", c["insider"])
        self.assertEqual(c["kind"], "explorer / developer")

    def test_gold_royalty_us_listed(self):
        c = dm.explain_context(ticker="GROY", archetype="asset_light_yield", commodity="gold")
        self.assertEqual(c["factor"], "gold")
        self.assertIn("GDXJ", c["etfs"])
        self.assertFalse(c["drill_relevant"])              # a royalty has no drill leak
        self.assertIn("SEC Form 4", c["insider"])          # US listing → not SEDI
        self.assertIn("royalty", c["kind"])

    def test_holdco_is_not_a_driller_even_when_option_convexity(self):
        # project-generator-holdco maps to option_convexity, but a holdco doesn't drill
        c = dm.explain_context(ticker="GMX.TO", archetype="option_convexity",
                               subarchetype="royalty_generator_holdco", commodity="")
        self.assertFalse(c["drill_relevant"])
        self.assertIn("holdco", c["kind"])
        self.assertIn("SEDI", c["insider"])

    def test_electrification_uranium(self):
        c = dm.explain_context(ticker="URC.TO", archetype="asset_light_yield", commodity="uranium")
        self.assertEqual(c["factor"], "uranium")
        self.assertIn("URA", c["etfs"])
        self.assertFalse(c["drill_relevant"])

    def test_unknown_commodity_falls_back_to_broad(self):
        c = dm.explain_context(ticker="ZZZ.V", archetype="option_convexity", commodity="")
        self.assertIn("broad", c["factor"])
        self.assertIn("XME", c["etfs"])

    def test_commodity_inferred_from_slot_when_untagged(self):
        c = dm.explain_context(ticker="X.V", archetype="asset_light_yield", slot="gold-royalty-ballast")
        self.assertEqual(c["factor"], "gold")


if __name__ == "__main__":
    unittest.main()
