"""Tests for rates_history (action-plan P2.1 support) — the daily rate-snapshot store that gives the
bear-steepener its prior-window value."""
import os
import tempfile
import time
import unittest

import rates_history as rh

DAY = 86400.0
NOW = time.mktime(time.strptime("2026-06-20", "%Y-%m-%d")) + 12 * 3600   # noon, deterministic


class RatesHistoryTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(self.path)                                   # start empty

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def _seed(self):
        rh.record({"dgs2": 3.5, "dgs10": 4.2, "dgs30": 4.5, "fedfunds": 4.3}, path=self.path, now=NOW - 30 * DAY)
        rh.record({"dgs2": 3.7, "dgs10": 4.4, "dgs30": 4.7, "fedfunds": 4.3}, path=self.path, now=NOW - 20 * DAY)
        rh.record({"dgs2": 3.9, "dgs10": 4.55, "dgs30": 4.95, "fedfunds": 4.33}, path=self.path, now=NOW)

    def test_record_and_readback_oldest_first(self):
        self._seed()
        snaps = rh.snapshots(self.path)
        self.assertEqual([s["day"] for s in snaps],
                         sorted(s["day"] for s in snaps))
        self.assertEqual(len(snaps), 3)
        self.assertAlmostEqual(snaps[0]["dgs30"], 4.5)

    def test_idempotent_per_day(self):
        rh.record({"dgs10": 4.5}, path=self.path, now=NOW)
        again = rh.record({"dgs10": 9.9}, path=self.path, now=NOW)   # same day -> no-op
        self.assertIsNone(again)
        self.assertEqual(len(rh.snapshots(self.path)), 1)
        self.assertAlmostEqual(rh.snapshots(self.path)[0]["dgs10"], 4.5)   # first write wins

    def test_no_usable_rate_returns_none(self):
        self.assertIsNone(rh.record({"junk": "x", "dgs10": "n/a"}, path=self.path, now=NOW))
        self.assertEqual(rh.snapshots(self.path), [])

    def test_prior_within_picks_closest_to_window(self):
        self._seed()
        prior = rh.prior_within(20.0, path=self.path, now=NOW)
        self.assertIsNotNone(prior)
        self.assertEqual(prior["day"], "2026-05-31")           # the ~20-day-old snapshot
        self.assertAlmostEqual(prior["dgs30"], 4.7)

    def test_prior_respects_min_days(self):
        # today's snapshot (age 0) must be excluded by min_days, so a 1-snapshot store has no prior.
        rh.record({"dgs10": 4.5, "dgs30": 4.9}, path=self.path, now=NOW)
        self.assertIsNone(rh.prior_within(20.0, path=self.path, min_days=5.0, now=NOW))

    def test_prior_within_none_on_empty(self):
        self.assertIsNone(rh.prior_within(20.0, path=self.path, now=NOW))

    def test_tolerates_torn_line(self):
        self._seed()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"day": "2026-06-19", "dgs10": 4.5\n')   # torn JSON, no closing brace
        self.assertEqual(len(rh.snapshots(self.path)), 3)      # torn line skipped, never crashes


if __name__ == "__main__":
    unittest.main()
