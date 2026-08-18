"""Seesaw-day classifier — the joint bond–metal day types, attribution tags, and the snapshot store."""
import os
import tempfile
import time
import unittest

import seesaw_day as ssd


class TestClassify(unittest.TestCase):
    def test_seesaw_b_distrust_bid(self):
        # yields up + metals up = the debasement tape (last week's bear steepener)
        r = ssd.classify(metal_ret_pct=1.4, d_y10=0.07)
        self.assertTrue(r["available"])
        self.assertEqual(r["day_type"], "SEESAW-B")
        self.assertEqual(r["bias"], "risk_off")
        self.assertIn("B", r["scenario_hint"])

    def test_seesaw_e_normalization(self):
        # Tuesday 2026-08-18: yields down, gold -1.9% — the TLT-call direction
        r = ssd.classify(metal_ret_pct=-1.88, d_y10=-0.018)
        # dy below y_min noise floor -> metals moved alone
        self.assertEqual(r["day_type"], "METAL-LED")
        r2 = ssd.classify(metal_ret_pct=-1.88, d_y10=-0.05)
        self.assertEqual(r2["day_type"], "SEESAW-E")
        self.assertEqual(r2["bias"], "risk_on")
        self.assertIn("E", r2["scenario_hint"])

    def test_common_enemy_real_led(self):
        r = ssd.classify(metal_ret_pct=-2.0, d_y10=0.05, d_real=0.06, d_breakeven=-0.01)
        self.assertEqual(r["day_type"], "COMMON-ENEMY")
        self.assertIn("real-led", r["read"])

    def test_both_bid_a(self):
        r = ssd.classify(metal_ret_pct=1.2, d_y10=-0.06)
        self.assertEqual(r["day_type"], "BOTH-BID-A")
        self.assertEqual(r["bias"], "risk_on")

    def test_liquidation_trumps_common_enemy(self):
        # both sold HARD -> margin flow, not a real-rate verdict
        r = ssd.classify(metal_ret_pct=-4.5, d_y10=0.12)
        self.assertEqual(r["day_type"], "LIQUIDATION")
        self.assertIn("path-risk", r["scenario_hint"])

    def test_quiet_and_breakeven_led_tag(self):
        self.assertEqual(ssd.classify(metal_ret_pct=0.2, d_y10=0.01)["day_type"], "QUIET")
        r = ssd.classify(metal_ret_pct=1.0, d_y10=0.05, d_real=0.01, d_breakeven=0.05)
        self.assertIn("breakeven-led", r["read"])

    def test_basis_discontinuity_refuses_to_classify(self):
        # mixed price bases (the live 2026-08-19 bug): a -47% "gold day" is not a day
        r = ssd.classify(metal_ret_pct=-47.4, d_y10=-0.374)
        self.assertFalse(r["available"])
        self.assertIn("basis discontinuity", r["read"])

    def test_missing_inputs_dormant(self):
        r = ssd.classify(metal_ret_pct=None, d_y10=0.05)
        self.assertFalse(r["available"])
        self.assertIsNone(r["day_type"])

    def test_config_override(self):
        # widen the metal noise floor so a 1% move reads as flat -> bond-led drift
        r = ssd.classify(metal_ret_pct=1.0, d_y10=0.05,
                         config={"seesaw_day": {"metal_min": 1.5}})
        self.assertEqual(r["day_type"], "BOND-DRIFT")


class TestSnapshotStore(unittest.TestCase):
    def test_record_prior_roundtrip_and_upsert(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ss.jsonl")
            yday = time.time() - 86400
            self.assertIsNotNone(ssd.record_snapshot({"gold": 2350.0, "y10": 4.35},
                                                     path=path, now=yday))
            # upsert: a later (live) write the same day REPLACES the boot-default row
            self.assertIsNotNone(ssd.record_snapshot({"gold": 4470.7, "y10": 4.724},
                                                     path=path, now=yday))
            self.assertIsNotNone(ssd.record_snapshot({"gold": 4389.5, "y10": 4.706}, path=path))
            prior = ssd.prior_snapshot(path=path)
            self.assertIsNotNone(prior)
            self.assertAlmostEqual(prior["gold"], 4470.7)
            self.assertEqual(len(ssd._snapshots(path)), 2)

    def test_prior_none_when_thin_or_stale(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ss.jsonl")
            self.assertIsNone(ssd.prior_snapshot(path=path))
            old = time.time() - 86400 * 30
            ssd.record_snapshot({"gold": 4000.0}, path=path, now=old)
            self.assertIsNone(ssd.prior_snapshot(path=path, max_age_days=5.0))

    def test_nothing_usable_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ss.jsonl")
            self.assertIsNone(ssd.record_snapshot({"gold": "n/a"}, path=path))


if __name__ == "__main__":
    unittest.main()
