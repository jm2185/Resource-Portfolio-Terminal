"""Phase 4 — second-source cross-check (flag, never average) + research-cache point-in-time
enforcement (restatement history, as_at reconstruction)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest

import cross_check as cc
from research_cache import ResearchCache


class ResearchCacheHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rc = ResearchCache(path=os.path.join(self.tmp.name, "rc.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_restatement_preserves_history_and_flags(self):
        self.rc.set("AGA.V", "shares_out", 208_600_000, "https://sedar/filing-a", "2026-01-01",
                    confidence="high")
        entry = self.rc.set("AGA.V", "shares_out", 215_000_000, "https://sedar/filing-b",
                            "2026-06-01", confidence="high")
        self.assertTrue(entry.get("restated"))
        hist = entry["history"]
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["value"], 208_600_000)   # the superseded entry survives, dated

    def test_same_value_refresh_not_marked_restated(self):
        self.rc.set("AGA.V", "cash", 53.07, "src", "2026-01-01")
        entry = self.rc.set("AGA.V", "cash", 53.07, "src", "2026-02-01")
        self.assertFalse(entry.get("restated"))
        self.assertEqual(len(entry["history"]), 1)        # refresh still archived

    def test_as_at_reconstructs_what_was_known(self):
        e1 = self.rc.set("AGA.V", "aisc_per_oz", 14.5, "src-a", "2026-01-01")
        # force distinct fetched_at days for the reconstruction
        self.rc._d["AGA.V"]["aisc_per_oz"]["history"] = []
        self.rc._d["AGA.V"]["aisc_per_oz"]["fetched_at"] = time.mktime((2026, 1, 1, 12, 0, 0, 0, 0, -1))
        self.rc._save()
        e2 = self.rc.set("AGA.V", "aisc_per_oz", 16.0, "src-b", "2026-03-01")
        self.rc._d["AGA.V"]["aisc_per_oz"]["fetched_at"] = time.mktime((2026, 3, 1, 12, 0, 0, 0, 0, -1))
        self.rc._save()
        then = self.rc.as_at("AGA.V", "aisc_per_oz", "2026-02-01")
        self.assertEqual(then["value"], 14.5)             # February's truth, not today's restatement
        now = self.rc.as_at("AGA.V", "aisc_per_oz", "2026-04-01")
        self.assertEqual(now["value"], 16.0)
        self.assertIsNone(self.rc.as_at("AGA.V", "aisc_per_oz", "2025-12-01"))   # didn't exist yet

    def test_history_bounded(self):
        for i in range(20):
            self.rc.set("AGA.V", "cash", float(i), "src", "2026-01-01")
        self.assertLessEqual(len(self.rc.get("AGA.V", "cash")["history"]), 12)


class CrossCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rc = ResearchCache(path=os.path.join(self.tmp.name, "rc.json"))
        self.rc.set("AGA.V", "shares_out", 208_600_000, "https://sedar/filing", "2026-01-01",
                    confidence="high")

    def tearDown(self):
        self.tmp.cleanup()

    def test_relative_disagreement(self):
        self.assertAlmostEqual(cc.relative_disagreement(100, 110), 10 / 110, places=6)
        self.assertIsNone(cc.relative_disagreement(None, 1))
        self.assertIsNone(cc.relative_disagreement(0, 0))

    def test_agreement_passes_untouched(self):
        res = cc.check_field(self.rc, "AGA.V", "shares_out", 210_000_000, "FMP")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.rc.get("AGA.V", "shares_out")["confidence"], "high")

    def test_conflict_flags_never_averages(self):
        res = cc.check_field(self.rc, "AGA.V", "shares_out", 300_000_000, "FMP")
        self.assertEqual(res["status"], "conflict")
        entry = self.rc.get("AGA.V", "shares_out")
        self.assertEqual(entry["value"], 208_600_000)     # the value is NOT averaged or replaced
        self.assertEqual(entry["confidence"], "low")      # ...but trust is demoted (fail-closed)
        self.assertIn("DATA CONFLICT", entry["note"])
        self.assertTrue(entry["history"])                 # the demotion is itself a visible event

    def test_conflict_widens_the_band_end_to_end(self):
        """The wired pathway: conflict -> confidence low -> distributional band widens."""
        import uncertainty as unc
        legs, weights = {"cost": 1.0, "market": 2.0}, {"cost": 0.3, "market": 0.7}
        before = unc.intrinsic_distribution(
            legs, weights, leg_confidence={"cost": "high",
                                           "market": self.rc.get("AGA.V", "shares_out")["confidence"]})
        cc.check_field(self.rc, "AGA.V", "shares_out", 300_000_000, "FMP")
        after = unc.intrinsic_distribution(
            legs, weights, leg_confidence={"cost": "high",
                                           "market": self.rc.get("AGA.V", "shares_out")["confidence"]})
        self.assertGreater(after["rel_width"], before["rel_width"])

    def test_cross_check_ticker_aliases_and_single_source(self):
        res = cc.cross_check_ticker(self.rc, "AGA.V",
                                    {"sharesOutstanding": 209_000_000, "totalCash": 50_000_000})
        self.assertEqual(res["results"]["shares_out"]["status"], "ok")
        self.assertEqual(res["results"]["cash"]["status"], "single_source")   # nothing cached
        self.assertEqual(res["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
