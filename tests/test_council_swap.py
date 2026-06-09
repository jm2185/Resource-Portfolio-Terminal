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

    def test_missing_liquidity_fails_closed_to_the_cap(self):
        # the rotation fail-open: days_90=None used to floor friction at re-entry only (2%) — an
        # UNKNOWN tape priced as perfectly liquid, silently flipping REJECT→SWAP on absent data.
        # Unknown liquidity must carry the conservative cap, and the verdict must say so.
        self.assertAlmostEqual(estimate_friction(None),
                               council.SLIP_MAX + council.REENTRY_COST, places=6)
        self.assertGreater(estimate_friction(None), estimate_friction(0.5))
        v = swap_verdict({"ticker": "I", "rho": 3.0}, {"ticker": "C", "rho": 4.5})  # no days_90
        self.assertTrue(v["friction_degraded"])
        self.assertIn("liquidity unknown", v["rationale"])
        # the same pair WITH a liquid tape is cheaper to swap — absent data can't be the best case
        v_liquid = swap_verdict({"ticker": "I", "rho": 3.0, "days_90": 0.5}, {"ticker": "C", "rho": 4.5})
        self.assertLess(v_liquid["friction"], v["friction"])
        self.assertFalse(v_liquid["friction_degraded"])

    def test_past_catalyst_does_not_lock(self):
        # a NEGATIVE days_to_catalyst is a stale calendar row (the event already happened) — it must
        # not freeze the gate in DEFER forever.
        v = swap_verdict({"ticker": "I", "rho": 3.0, "days_90": 1.0}, {"ticker": "C", "rho": 6.0},
                         catalyst_days=-5)
        self.assertNotEqual(v["decision"], "DEFER")
        self.assertFalse(v["catalyst_lock"])


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

    def test_unknown_incumbent_slot_passes_flagged_never_clean(self):
        # the fail-open: slot_gate(None, <any slot>) used to return a CLEAN 'slot-fit' — a
        # wrong-slot challenger waved through unflagged. Unknown must read 'slot-unverified'.
        ok, reason = council.slot_gate(None, "gold-royalty-ballast")
        self.assertTrue(ok)
        self.assertEqual(reason, "slot-unverified")
        ok, reason = council.slot_gate(None, None)
        self.assertTrue(ok)
        self.assertEqual(reason, "slot-unverified")


class FrictionProvenanceTests(unittest.TestCase):
    """Tier-2 #3 (Druckenmiller): the friction constants must carry base_rates.py-style provenance —
    every one graded as an engineering prior, with the slip_max permissive-direction caveat explicit."""

    def test_every_constant_has_basis_and_confidence(self):
        prov = council.swap_param_provenance()
        for key in ("hurdle", "lock_window", "slip_per_day", "slip_max", "reentry_cost"):
            self.assertIn(key, prov)
            self.assertIn("basis", prov[key])
            self.assertIn("confidence", prov[key])
            self.assertTrue(prov[key]["confidence"].lower().startswith("engineering"))

    def test_slip_max_caveat_flags_understatement_direction(self):
        note = council.swap_param_provenance()["slip_max"]["note"].lower()
        self.assertIn("understate", note)
        self.assertIn("permissive", note)            # the error direction is named

    def test_verdict_carries_friction_basis(self):
        v = swap_verdict({"ticker": "URC.TO", "rho": 2.0, "days_90": 10},
                         {"ticker": "NXE.TO", "rho": 3.2})
        self.assertIn("friction_basis", v)
        self.assertIn("slip_max", v["friction_basis"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
