"""
Tests for cockpit_scheduler.py — the recurring-agent-work spine. Pure + offline.

Pins the non-negotiables: the autonomy dial is the ONLY thing that turns "due" into action (manual
skips, propose proposes, auto runs); cadence scheduling is monotonic; and the store round-trips.
"""
import os
import tempfile
import unittest

import cockpit_scheduler as s


class SchedulerTests(unittest.TestCase):
    def test_new_job_schedules_one_cadence_out(self):
        j = s.new_job("scout", "silver juniors", every_min=60, now=1000.0)
        self.assertEqual(j["kind"], "scout")
        self.assertTrue(j["enabled"])
        self.assertEqual(j["next_due"], 1000.0 + 60 * 60)          # not immediately due
        self.assertIn("silver juniors", j["label"])
        self.assertEqual(j["runs"], 0)

    def test_unknown_kind_falls_back(self):
        self.assertEqual(s.new_job("vibes", "x")["kind"], s.DEFAULT_KIND)

    def test_prompt_substitutes_topic_and_build_is_review_only(self):
        self.assertIn("silver", s.prompt_for(s.new_job("scout", "silver")))
        build = s.prompt_for(s.new_job("build", "a new uranium agent"))
        self.assertIn("uranium", build)
        self.assertIn("Do NOT edit tracked files", build)         # the hard safety line, in the prompt

    def test_due_respects_enabled_and_time(self):
        a = s.new_job("research", "a", every_min=10, now=0.0)     # next_due = 600
        b = s.new_job("research", "b", every_min=10, now=0.0); b["enabled"] = False
        self.assertEqual(s.due_jobs([a, b], now=500.0), [])       # not yet due
        self.assertEqual([j["id"] for j in s.due_jobs([a, b], now=700.0)], [a["id"]])  # b disabled

    def test_decide_is_the_autonomy_boundary(self):
        self.assertEqual(s.decide("manual"), "skip")
        self.assertEqual(s.decide("propose"), "propose")
        self.assertEqual(s.decide("auto"), "run")
        self.assertEqual(s.decide("nonsense"), "propose")         # safe default

    def test_mark_ran_advances_and_counts(self):
        j = s.new_job("research", "a", every_min=10, now=0.0)
        s.mark_ran(j, now=700.0)
        self.assertEqual(j["last_run"], 700.0)
        self.assertEqual(j["runs"], 1)
        self.assertEqual(j["next_due"], 700.0 + 600)              # one cadence past the run
        self.assertEqual(s.due_jobs([j], now=701.0), [])         # no longer due

    def test_snooze_pushes_next_due(self):
        j = s.new_job("research", "a", every_min=10, now=0.0)
        s.snooze(j, 30, now=1000.0)
        self.assertEqual(j["next_due"], 1000.0 + 30 * 60)

    def test_store_round_trips(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            jobs = [s.new_job("scout", "silver"), s.new_job("backtest", "AGA.V")]
            s.save_jobs(path, jobs)
            loaded = s.load_jobs(path)
            self.assertEqual([j["id"] for j in loaded], [j["id"] for j in jobs])
            self.assertEqual(s.load_jobs("/no/such/path.json"), [])   # missing → empty, no crash
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
