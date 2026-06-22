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


if __name__ == "__main__":
    unittest.main()
