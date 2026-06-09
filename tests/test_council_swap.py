"""
Tests for the Council swap system (council.py swap_verdict, Forge M6).

Pins the friction-adjusted hurdle arithmetic and the catalyst lock as executable guarantees — the
over-trading brake (Darwinian high-grading WITHOUT churn): a swap needs a big NET edge, and never sells
an incumbent sitting on a near catalyst.
"""
import unittest

import council
from council import estimate_friction, swap_verdict


class HurdleTests(unittest.TestCase):
    def test_spec_acceptance_reject(self):
        # challenger ρ=4.0 vs incumbent ρ=3.0, friction=0.08 -> edge 0.3333, net 0.2533 < 0.35 -> REJECT
        v = swap_verdict({"ticker": "GROY", "rho": 3.0}, {"ticker": "NEW.V", "rho": 4.0},
                         friction=0.08)
        self.assertEqual(v["decision"], "REJECT")
        self.assertAlmostEqual(v["edge"], 0.3333, places=3)
        self.assertAlmostEqual(v["net_edge"], 0.2533, places=3)

    def test_strong_challenger_swaps(self):
        v = swap_verdict({"ticker": "GROY", "rho": 3.0}, {"ticker": "NEW.V", "rho": 5.0},
                         friction=0.08)
        self.assertEqual(v["decision"], "SWAP")           # edge 0.667 - 0.08 = 0.587 >= 0.35
        self.assertGreaterEqual(v["net_edge"], v["hurdle"])

    def test_just_below_hurdle_rejects(self):
        # tune challenger so net_edge sits a hair under 0.35
        v = swap_verdict({"ticker": "I", "rho": 3.0}, {"ticker": "C", "rho": 4.27}, friction=0.08)
        self.assertAlmostEqual(v["edge"], 0.4233, places=3)
        self.assertLess(v["net_edge"], 0.35)
        self.assertEqual(v["decision"], "REJECT")


class CatalystLockTests(unittest.TestCase):
    def test_catalyst_within_lock_defers_regardless_of_edge(self):
        # huge edge, but the incumbent has a catalyst 12d out with a 21d lock -> DEFER
        v = swap_verdict({"ticker": "AGA.V", "rho": 3.0}, {"ticker": "C", "rho": 9.0},
                         friction=0.05, catalyst_days=12, lock_window=21)
        self.assertEqual(v["decision"], "DEFER")
        self.assertEqual(v["days_to_catalyst"], 12)
        self.assertIn("12", v["rationale"])

    def test_catalyst_outside_lock_does_not_defer(self):
        v = swap_verdict({"ticker": "AGA.V", "rho": 3.0}, {"ticker": "C", "rho": 9.0},
                         friction=0.05, catalyst_days=40, lock_window=21)
        self.assertNotEqual(v["decision"], "DEFER")       # 40 > 21 -> no lock

    def test_regime_inflection_defers(self):
        v = swap_verdict({"ticker": "AGA.V", "rho": 3.0}, {"ticker": "C", "rho": 9.0},
                         friction=0.05, regime_inflection=True)
        self.assertEqual(v["decision"], "DEFER")
        self.assertIn("regime", v["rationale"].lower())


class FrictionTests(unittest.TestCase):
    def test_friction_grows_with_illiquidity(self):
        liquid = estimate_friction(0.5)                   # half a day to exit
        illiquid = estimate_friction(15)                  # 15 days to exit
        self.assertLess(liquid, illiquid)
        self.assertGreaterEqual(illiquid, liquid)

    def test_friction_default_used_when_not_passed(self):
        # incumbent with a 10-day runway -> friction computed from the liquidity model, not 0
        v = swap_verdict({"ticker": "I", "rho": 3.0, "days_90": 10.0}, {"ticker": "C", "rho": 4.5})
        self.assertGreater(v["friction"], 0.0)

    def test_friction_capped(self):
        self.assertLessEqual(estimate_friction(10_000), council.SLIP_MAX + council.REENTRY_COST + 1e-9)


class GuardTests(unittest.TestCase):
    def test_missing_rho_rejects_safely(self):
        v = swap_verdict({"ticker": "I"}, {"ticker": "C", "rho": 4.0})
        self.assertEqual(v["decision"], "REJECT")
        self.assertIn("ρ", v["reason"])

    def test_memory_entry_shape(self):
        v = swap_verdict({"ticker": "GROY", "rho": 3.0}, {"ticker": "NEW.V", "rho": 5.0},
                         friction=0.08)
        e = council.swap_to_memory_entry(v)
        self.assertEqual(e["type"], "decision")
        self.assertIn("up_tier", e["tags"])
        self.assertEqual(e["ticker"], "NEW.V")


class SlotGateTests(unittest.TestCase):
    """The non-negotiable slot-fit precheck (D1) — slot first, ρ-edge second."""

    def test_mismatch_blocks_before_edge(self):
        ok, reason = council.slot_gate("electrification-royalty", "gold-royalty-ballast")
        self.assertFalse(ok)
        self.assertEqual(reason, "slot-mismatch")

    def test_same_slot_fits(self):
        ok, reason = council.slot_gate("silver-spear", "silver-spear")
        self.assertTrue(ok)
        self.assertEqual(reason, "slot-fit")

    def test_unknown_challenger_slot_passes_flagged(self):
        ok, reason = council.slot_gate("silver-spear", None)
        self.assertTrue(ok)
        self.assertEqual(reason, "slot-unverified")

    def test_unknown_incumbent_slot_does_not_hard_block(self):
        ok, _ = council.slot_gate(None, "gold-royalty-ballast")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
