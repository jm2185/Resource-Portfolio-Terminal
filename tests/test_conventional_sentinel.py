"""conventional_sentinel — the archetype-aware SENTINEL zones (Phase 4 of the dual-sided TIV spec):
the asymmetry-zone cross (price crossing a lens's ladder) + the rebalance-band drift. Pure detectors,
hand-verifiable."""
import unittest

import conventional_sentinel as cs

LADDER = {"floor": 40.0, "bear": 44.0, "base": 52.0, "bull": 71.0}


class ZoneOfTests(unittest.TestCase):
    def test_zone_classification(self):
        self.assertEqual(cs.zone_of(35, LADDER)["zone"], "below_floor")
        self.assertEqual(cs.zone_of(47, LADDER)["zone"], "accumulate")
        self.assertEqual(cs.zone_of(60, LADDER)["zone"], "fair_to_rich")
        self.assertEqual(cs.zone_of(80, LADDER)["zone"], "extended")

    def test_thin_ladder_is_graceful(self):
        self.assertIsNone(cs.zone_of(50, {"floor": 40})["zone"])     # no base → can't classify
        self.assertIsNone(cs.zone_of(None, LADDER)["zone"])


class ZoneCrossTests(unittest.TestCase):
    def test_fires_only_on_transition(self):
        # first observation (no prev) records the zone, does NOT fire
        r0 = cs.asymmetry_zone_cross("X.TO", 35, LADDER, lens="deep_value", prev_zone=None)
        self.assertFalse(r0["crossed"])
        self.assertEqual(r0["flags"], [])
        # same zone again → no fire
        r1 = cs.asymmetry_zone_cross("X.TO", 47, LADDER, lens="compounder", prev_zone="accumulate")
        self.assertFalse(r1["crossed"])

    def test_falling_below_floor_is_opportunity(self):
        r = cs.asymmetry_zone_cross("EEFT", 35, LADDER, lens="deep_value", prev_zone="accumulate")
        self.assertTrue(r["crossed"])
        self.assertEqual(r["flags"][0]["id"], "asymmetry_zone_cross")
        self.assertEqual(r["flags"][0]["level"], "good")
        self.assertIn("floor", r["flags"][0]["text"].lower())

    def test_rising_above_ceiling_is_extended_warn(self):
        r = cs.asymmetry_zone_cross("X.TO", 80, LADDER, lens="compounder", prev_zone="fair_to_rich")
        self.assertTrue(r["crossed"])
        self.assertEqual(r["flags"][0]["level"], "warn")
        self.assertIn("torpedo", r["flags"][0]["text"].lower())

    def test_reclaiming_floor_is_info(self):
        r = cs.asymmetry_zone_cross("EEFT", 47, LADDER, lens="deep_value", prev_zone="below_floor")
        self.assertTrue(r["crossed"])
        self.assertEqual(r["flags"][0]["level"], "info")
        self.assertIn("reclaim", r["flags"][0]["text"].lower())


class RebalanceBandTests(unittest.TestCase):
    def test_drift_outside_band_flags(self):
        r = cs.rebalance_band("X.TO", 0.12, 0.08)               # 4pp drift > 3pp band
        self.assertTrue(r["drifted"])
        self.assertEqual(r["flags"][0]["id"], "rebalance_drift")
        self.assertEqual(r["flags"][0]["level"], "warn")

    def test_within_band_is_quiet(self):
        self.assertFalse(cs.rebalance_band("X.TO", 0.09, 0.08)["drifted"])

    def test_missing_inputs_dormant(self):
        self.assertFalse(cs.rebalance_band("X.TO", None, 0.08)["drifted"])


class AssessBookTests(unittest.TestCase):
    def test_combines_zone_and_rebalance_and_carries_zones(self):
        reads = [{"ticker": "X.TO", "lens": "compounder", "price": 80, "ladder": LADDER,
                  "weight": 0.12, "target": 0.08}]
        r = cs.assess_book(reads, prev_zones={"X.TO": "fair_to_rich"})
        self.assertTrue(r["available"])
        ids = {f["id"] for f in r["flags"]}
        self.assertIn("asymmetry_zone_cross", ids)              # rose into extended
        self.assertIn("rebalance_drift", ids)                   # 4pp off target
        self.assertEqual(r["zones_next"]["X.TO"], "extended")   # carried forward for next cycle

    def test_empty_is_clean_noop(self):
        r = cs.assess_book([])
        self.assertFalse(r["available"])
        self.assertEqual(r["flags"], [])


class SelectFreshTests(unittest.TestCase):
    def test_dedup_and_refire_on_new_zone(self):
        flags = [{"id": "asymmetry_zone_cross", "ticker": "X.TO", "zone": "extended", "level": "warn"}]
        fresh, fired = cs.select_fresh(flags, {}, today="2026-06-24")
        self.assertEqual(len(fresh), 1)
        fresh2, _ = cs.select_fresh(flags, fired, today="2026-06-24")
        self.assertEqual(fresh2, [])                            # same zone, same day → no re-pin
        moved = [{"id": "asymmetry_zone_cross", "ticker": "X.TO", "zone": "below_floor", "level": "good"}]
        fresh3, _ = cs.select_fresh(moved, fired, today="2026-06-24")
        self.assertEqual(len(fresh3), 1)                        # a new zone is a new event


if __name__ == "__main__":
    unittest.main()
