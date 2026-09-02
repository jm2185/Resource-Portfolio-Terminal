"""mark_guard — a mark the feed did not deliver is never written (2026-09-02 reassessment, TF3 #1).

Pins the seed-constant chain the sweep found: seed prices badged LIVE → first-cycle daily stamp →
record_mark → immutable. Every branch here is a way a constant reached the track record."""
import unittest

import mark_guard as mg

NOW = 1_700_000_000.0


class TrustworthyTests(unittest.TestCase):
    def test_seed_status_is_never_trustworthy(self):
        ok, why = mg.trustworthy("GROY", prices_stale={"GROY": False}, prices_status="INITIAL_BASELINE",
                                 prices_ts=NOW, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, "seed")

    def test_no_sync_is_never_trustworthy(self):
        ok, why = mg.trustworthy("GROY", prices_stale={"GROY": False}, prices_status="LIVE",
                                 prices_ts=None, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, "no-sync")

    def test_old_sync_is_dead_feed(self):
        ok, why = mg.trustworthy("GROY", prices_stale={"GROY": False}, prices_status="LIVE",
                                 prices_ts=NOW - 3600, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, "sync-stale")

    def test_stale_mark_is_refused(self):
        for flag in (True, 1, "yes"):
            ok, why = mg.trustworthy("GROY", prices_stale={"GROY": flag}, prices_status="DEGRADED",
                                     prices_ts=NOW, now=NOW)
            self.assertFalse(ok); self.assertEqual(why, "stale")

    def test_unknown_ticker_is_not_fresh_by_absence(self):
        ok, why = mg.trustworthy("BNKR.TO", prices_stale={"GROY": False}, prices_status="LIVE",
                                 prices_ts=NOW, now=NOW)
        self.assertFalse(ok); self.assertEqual(why, "unknown")

    def test_live_fresh_mark_passes(self):
        ok, why = mg.trustworthy("groy", prices_stale={"GROY": False}, prices_status="LIVE",
                                 prices_ts=NOW - 10, now=NOW)
        self.assertTrue(ok); self.assertEqual(why, "ok")

    def test_degraded_book_still_stamps_the_fresh_names(self):
        # one stale holding demotes the feed to DEGRADED; the OTHER names' fresh marks still count
        stale = {"AGA.V": False, "GROY": True}
        plan = mg.plan_stamps(["AGA.V", "GROY"], prices_stale=stale, prices_status="DEGRADED",
                              prices_ts=NOW, now=NOW)
        self.assertEqual(plan["stamp"], ["AGA.V"])
        self.assertEqual(plan["skipped"], {"GROY": "stale"})


class SeesawTests(unittest.TestCase):
    def test_seed_silver_or_default_real_yield_never_recorded(self):
        ok, why = mg.seesaw_trusted(prices_stale={"SI=F": False}, prices_status="INITIAL_BASELINE",
                                    ry_status="LIVE", prices_ts=NOW, now=NOW)
        self.assertFalse(ok); self.assertTrue(why.startswith("silver:"))
        ok, why = mg.seesaw_trusted(prices_stale={"SI=F": False}, prices_status="LIVE",
                                    ry_status="DEGRADED_STALE", prices_ts=NOW, now=NOW)
        self.assertFalse(ok); self.assertTrue(why.startswith("real_yield:"))

    def test_live_both_legs_records(self):
        ok, why = mg.seesaw_trusted(prices_stale={"SI=F": False}, prices_status="LIVE",
                                    ry_status="LIVE", prices_ts=NOW, now=NOW)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()


class RegimeTests(unittest.TestCase):
    def test_posture_on_seed_inputs_is_not_an_event(self):
        self.assertFalse(mg.regime_trusted(macro_status="LIVE", prices_status="INITIAL_BASELINE")[0])
        self.assertFalse(mg.regime_trusted(macro_status="DEGRADED_STALE", prices_status="LIVE")[0])
        self.assertFalse(mg.regime_trusted(macro_status=None, prices_status=None)[0])

    def test_live_inputs_persist(self):
        self.assertTrue(mg.regime_trusted(macro_status="LIVE", prices_status="DEGRADED")[0])
        self.assertTrue(mg.regime_trusted(macro_status="LIVE", prices_status="LIVE")[0])
