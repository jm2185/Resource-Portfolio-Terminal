"""
Tests for forensic_gates.runway_aware_dilution_pass — the runway-netted dilution forensic.

Pins the contract that fixes the "misleading dilution" case:
  * a sub-threshold raise still passes raw (unchanged);
  * a FUNDED raise (over threshold but runway clears the bar) is insulated and flagged as such;
  * a death-spiral shape (dilution + short runway) still FAILS;
  * a catastrophic single-period expansion fails even with a long runway;
  * enabled=False restores the legacy raw test; comfort_mult raises the bar.
"""
import unittest

import forensic_gates as fg


class RunwayAwareDilutionTests(unittest.TestCase):
    def test_sub_threshold_raw_pass(self):
        p, reason, ins = fg.runway_aware_dilution_pass(dilution=0.01, runway_months=8)
        self.assertTrue(p)
        self.assertFalse(ins)                      # passed on the raw bar, not runway

    def test_funded_raise_insulated_by_runway(self):
        # AGA-like: large QoQ raise (+30%) but ~19 mo runway (> 18 bar) -> funding, insulated
        p, reason, ins = fg.runway_aware_dilution_pass(
            dilution=0.30, runway_months=19.3, runway_min_months=18.0)
        self.assertTrue(p)
        self.assertTrue(ins)
        self.assertIn("runway", reason.lower())

    def test_death_spiral_short_runway_still_fails(self):
        # diluted but runway still short -> raising into weakness -> FAIL (gate still bites)
        p, reason, ins = fg.runway_aware_dilution_pass(
            dilution=0.10, runway_months=5.0, runway_min_months=18.0)
        self.assertFalse(p)
        self.assertFalse(ins)

    def test_catastrophic_raise_fails_even_with_runway(self):
        # a >=50% single-period expansion is a distress signal even if it bought runway
        p, reason, ins = fg.runway_aware_dilution_pass(
            dilution=0.60, runway_months=40.0, runway_min_months=18.0, catastrophic_pct=50.0)
        self.assertFalse(p)
        self.assertFalse(ins)
        self.assertIn("catastrophic", reason.lower())

    def test_disabled_restores_legacy_raw_test(self):
        # enabled=False -> raw < threshold only; the funded raise FAILS like before
        p, reason, ins = fg.runway_aware_dilution_pass(
            dilution=0.30, runway_months=19.3, enabled=False)
        self.assertFalse(p)
        self.assertFalse(ins)

    def test_comfort_mult_raises_the_bar(self):
        # comfort 1.5 -> need 27 mo; 19.3 mo no longer insulates
        p, reason, ins = fg.runway_aware_dilution_pass(
            dilution=0.30, runway_months=19.3, runway_min_months=18.0, runway_comfort_mult=1.5)
        self.assertFalse(p)

    def test_bad_inputs_are_safe(self):
        p, reason, ins = fg.runway_aware_dilution_pass(dilution=None, runway_months=None)
        self.assertTrue(p)                         # None -> 0.0 -> below threshold, no crash


if __name__ == "__main__":
    unittest.main(verbosity=2)
