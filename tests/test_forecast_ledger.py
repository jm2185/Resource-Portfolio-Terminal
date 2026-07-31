"""
Tests for the forecast ledger (forecast_ledger.py) + the MCP tools (forecast_write /
forecast_resolve / forecast_book) + the offline world-state frame.

The disciplines pinned:
  * certainty is not a forecast (p ∈ {0,1} refuses), and no horizon = no forecast;
  * Brier math is exact and resolution is IMMUTABLE (a second resolve refuses — corrections
    supersede the resolution, visibly);
  * the book stays COLD below MIN_N — counts, never a false calibration verdict;
  * verbal→numeric confidence mappings are labeled, never silent;
  * the offline world-state frame serves the stores instead of refusing.
"""
import os
import tempfile
import unittest
from pathlib import Path

import forecast_ledger as fl
from living_memory import LivingMemory

import core


class ShapeTests(unittest.TestCase):
    def test_valid_forecast_builds(self):
        m = fl.new_forecast("CEG reaffirms FY26 guide", 0.75, "2026-08-06", subject="CEG")
        self.assertEqual(("open", 0.75), (m["status"], m["confidence"]))

    def test_certainty_refuses(self):
        for p in (0, 1, 1.0, -0.2, "high"):
            with self.assertRaises(ValueError, msg=p):
                fl.new_forecast("x", p, "2026-08-06")

    def test_no_horizon_refuses(self):
        for d in ("", "sometime 2027", None):
            with self.assertRaises(ValueError, msg=d):
                fl.new_forecast("x", 0.6, d)

    def test_empty_claim_refuses(self):
        with self.assertRaises(ValueError):
            fl.new_forecast("  ", 0.6, "2026-08-06")

    def test_brier_math(self):
        self.assertEqual(0.0625, fl.brier(0.75, True))       # (0.75-1)^2
        self.assertEqual(0.5625, fl.brier(0.75, False))
        self.assertEqual(0.25, fl.brier(0.5, True))          # ignorance line

    def test_resolution_is_immutable(self):
        m = fl.new_forecast("x", 0.6, "2026-08-06")
        r = fl.resolve_meta(m, True, resolved_at="2026-08-06")
        self.assertEqual((True, 0.16), (r["outcome"], r["brier"]))
        with self.assertRaises(ValueError):
            fl.resolve_meta(r, False)                        # no quiet re-score


class BookTests(unittest.TestCase):
    def _entry(self, meta, ts="2026-07-31T00:00:00Z", eid="e1"):
        return {"id": eid, "ts": ts, "type": "forecast", "meta": meta}

    def test_cold_below_min_n_no_verdict(self):
        rows = [self._entry(fl.resolve_meta(fl.new_forecast("x", 0.9, "2026-08-01"), True),
                            eid=f"e{i}") for i in range(fl.MIN_N - 1)]
        agg = fl.book(rows)["aggregate"]
        self.assertTrue(agg["cold"])
        self.assertIn("COLD", agg["read"])                   # never "calibrated" on 4 points

    def test_warm_book_reads_overconfidence(self):
        # five resolved at 0.9 confidence, only 2 hits -> gap +0.5 -> overconfident
        rows = [self._entry(fl.resolve_meta(fl.new_forecast("x", 0.9, "2026-08-01"), i < 2),
                            eid=f"e{i}") for i in range(5)]
        agg = fl.book(rows)["aggregate"]
        self.assertFalse(agg["cold"])
        self.assertEqual("overconfident", agg["read"])
        self.assertFalse(agg["beats_ignorance"])             # mean Brier 0.486 > 0.25

    def test_open_sorted_soonest_and_overdue_flagged(self):
        rows = [self._entry(fl.new_forecast("far", 0.6, "2027-07-31"), eid="far"),
                self._entry(fl.new_forecast("past", 0.6, "2026-07-01"), eid="past")]
        bk = fl.book(rows, now="2026-07-31")
        self.assertEqual(["past", "far"], [r["id"] for r in bk["open"]])
        self.assertEqual(["past"], [r["id"] for r in bk["overdue"]])
        self.assertIn("1 overdue", bk["line"])


class McpToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._saved = core.MEMORY_PATH
        core.MEMORY_PATH = Path(self.tmp)

    def tearDown(self):
        core.MEMORY_PATH = self._saved
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_write_resolve_book_roundtrip(self):
        w = core.forecast_write("CEG reaffirms FY26 guide on the Aug 6 call", 0.75,
                                "2026-08-06", ticker="CEG", basis="R-8: guide is the signal")
        self.assertTrue(w["ok"], w)
        r = core.forecast_resolve(w["id"], True, note="guide reaffirmed, raised low end")
        self.assertTrue(r["ok"], r)
        self.assertEqual(0.0625, r["brier"])
        bk = core.forecast_book()
        self.assertEqual(0, len(bk["open"]))                 # superseded open entry hidden
        self.assertEqual(1, len(bk["resolved"]))
        # the open record SURVIVES in the file (append-only)
        self.assertIsNotNone(LivingMemory(self.tmp).get(w["id"]))

    def test_bad_confidence_refuses_at_write(self):
        w = core.forecast_write("x", 1.0, "2026-08-06")
        self.assertFalse(w["ok"])
        self.assertIn("strictly between", w["error"])

    def test_double_resolve_refuses(self):
        w = core.forecast_write("x", 0.6, "2026-08-06")
        r1 = core.forecast_resolve(w["id"], True)
        r2 = core.forecast_resolve(r1["id"], False)
        self.assertFalse(r2["ok"])
        self.assertIn("already resolved", r2["error"])

    def test_subject_filter(self):
        core.forecast_write("a", 0.6, "2026-08-06", ticker="CEG")
        core.forecast_write("b", 0.6, "2026-09-11", subject="memory-complex")
        self.assertEqual(1, len(core.forecast_book(subject="CEG")["open"]))
        self.assertEqual(1, len(core.forecast_book(subject="memory-complex")["open"]))


class OfflineWorldStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._saved = core.MEMORY_PATH
        core.MEMORY_PATH = Path(self.tmp)

    def tearDown(self):
        core.MEMORY_PATH = self._saved
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_engine_down_serves_the_stores_not_a_refusal(self):
        import thesis_ledger as tl
        mem = LivingMemory(self.tmp)
        body = tl.build_thesis("CEG", stance="CONDITIONAL",
                               claims=[tl.new_claim("g", cid="c1", check="manual",
                                                    status="unknown")])
        mem.write("thesis", text="t", ticker="CEG", tags=["thesis"], meta=body, source="test")
        core.forecast_write("x", 0.6, "2026-08-06", ticker="CEG")
        r = core.get_world_state()
        self.assertTrue(r["ok"])                             # ok, not a refusal
        self.assertFalse(r["engine_running"])
        self.assertEqual("store-only", r["world"]["mode"])
        self.assertEqual("CEG", r["world"]["theses"][0]["ticker"])
        self.assertIn("1 open", r["world"]["forecasts"]["line"])
        self.assertIn("no live regime", r["brief"])          # never fabricates engine numbers


if __name__ == "__main__":
    unittest.main()
