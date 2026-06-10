"""
Tests for regime posture (regime_posture.py) — the master temperature dial.

Pins the Druckenmiller shape: risk-on lifts the cap (press the spear), risk-off cuts it (dry
powder), real-yield/DXY headwinds trim it even inside a risk-on stance, and the whole thing degrades
gracefully to a neutral BALANCED/1.0x when signals are missing.
"""
import unittest

import regime_posture as rp


class StanceTests(unittest.TestCase):
    def test_low_mri_is_spear_exploit(self):
        p = rp.compute(mri=38.0)
        self.assertEqual(p["code"], "spear_exploit")
        self.assertGreater(p["cap"], 1.0)               # tailwind lifts the cap

    def test_high_mri_is_defensive(self):
        p = rp.compute(mri=72.0)
        self.assertEqual(p["code"], "defensive")
        self.assertLess(p["cap"], 1.0)                  # dry powder

    def test_mid_mri_is_balanced(self):
        self.assertEqual(rp.compute(mri=50.0)["code"], "balanced")

    def test_explicit_net_tilt_overrides_mri_band(self):
        # an explicit risk_off tilt wins even at a middling MRI
        self.assertEqual(rp.compute(mri=50.0, net_tilt="risk_off")["code"], "defensive")
        self.assertEqual(rp.compute(mri=55.0, net_tilt="risk-on")["code"], "spear_exploit")


class CapTests(unittest.TestCase):
    def test_real_yield_headwind_trims_cap_even_in_risk_on(self):
        easy = rp.compute(mri=38.0, real_yield=1.0)     # low yields -> tailwind
        tight = rp.compute(mri=38.0, real_yield=3.5)    # high yields -> headwind
        self.assertGreater(easy["cap"], tight["cap"])
        self.assertEqual(tight["code"], "spear_exploit")   # still exploit stance...
        self.assertTrue(tight["headwind"])                 # ...but flagged a headwind cap

    def test_real_yield_pivot_is_neutral(self):
        # at exactly the 2.0% pivot the real-yield term adds nothing
        p = rp.compute(mri=50.0, real_yield=2.0)
        ry = next(d for d in p["drivers"] if d["name"] == "real_yield")
        self.assertEqual(ry["cap_adj"], 0.0)

    def test_dxy_bid_is_a_minor_headwind(self):
        calm = rp.compute(mri=45.0, dxy_mom=0.0)
        bid = rp.compute(mri=45.0, dxy_mom=1.5)
        self.assertLessEqual(bid["cap"], calm["cap"])

    def test_cap_is_bounded(self):
        floor = rp.compute(mri=95.0, real_yield=6.0, dxy_mom=2.0)
        ceil = rp.compute(mri=5.0, real_yield=-2.0, dxy_mom=-2.0)
        self.assertGreaterEqual(floor["cap"], rp.CAP_FLOOR)
        self.assertLessEqual(ceil["cap"], rp.CAP_CEIL)


class GracefulTests(unittest.TestCase):
    def test_no_signals_is_neutral(self):
        p = rp.compute()
        self.assertEqual(p["code"], "balanced")
        self.assertEqual(p["cap"], 1.0)
        self.assertIn("no live regime", p["rationale"])

    def test_garbage_inputs_dont_crash(self):
        p = rp.compute(mri="n/a", real_yield=None, dxy_mom="x", net_tilt=42)
        self.assertEqual(p["cap"], 1.0)
        self.assertIn(p["code"], ("balanced", "spear_exploit", "defensive"))

    def test_rationale_names_the_dominant_mover(self):
        p = rp.compute(mri=30.0, real_yield=2.0)       # MRI is the only mover
        self.assertIn("MRI", p["rationale"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
