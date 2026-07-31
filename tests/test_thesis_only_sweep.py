"""
Tests for the thesis-only Sentinel sweep — sentinel.sweep_thesis_only and the core.sentinel_sweep
wiring that extends the discipline layer past the held book.

The guarantees pinned:
  * manual claims drive integrity (the operator's flips COUNT); engine claims fall to unknown —
    fail closed, never claimed to hold on data we don't have;
  * calendar-armed ``event:<kind>`` rules FIRE from the calendar alone (no engine required) and are
    deduped/acked exactly like the held path;
  * the engine-dependent checks are stamped ``not_applicable`` — present with a reason, never
    silently omitted; ``mode: thesis-only`` marks the whole status;
  * the core wiring sweeps every underwritten name with the ENGINE DOWN (the whole point) and
    writes the per-name status to Memory.
"""
import os
import tempfile
import unittest
from pathlib import Path

import sentinel as sen
import thesis_ledger as tl
from catalyst_calendar import CatalystCalendar
from living_memory import LivingMemory

import core


def _body(claims=None, rules=None):
    return tl.build_thesis(
        "CEG", stance="CONDITIONAL",
        claims=claims if claims is not None else [
            tl.new_claim("guide reaffirmed", cid="c1", check="manual", status="unknown"),
            tl.new_claim("PPA intact", cid="c2", check="manual", status="holds"),
            tl.new_claim("phi holds", cid="c3", metric="phi", op=">=", threshold=1.0),
        ],
        rules=rules if rules is not None else [
            tl.new_rule("event:earnings", "review", rid="r1")])


class PureSweepTests(unittest.TestCase):
    def test_manual_claims_score_engine_claims_fall_to_unknown(self):
        st = sen.sweep_thesis_only(ticker="CEG", thesis=_body())
        by_id = {s["id"]: s["status"] for s in st["integrity"]["statuses"]}
        self.assertEqual({"c1": "unknown", "c2": "holds", "c3": "unknown"}, by_id)
        self.assertEqual("thesis-only", st["mode"])

    def test_operator_flip_moves_the_swept_integrity(self):
        flipped = tl.set_claim_status(_body(), "c1", "holds")
        st = sen.sweep_thesis_only(ticker="CEG", thesis=flipped)
        self.assertEqual(2, st["integrity"]["holds"])

    def test_event_rule_fires_from_the_calendar_alone(self):
        st = sen.sweep_thesis_only(ticker="CEG", thesis=_body(),
                                   events={"earnings": "2026-08-06"})
        self.assertEqual(1, len(st["fired_rules"]))
        self.assertEqual("r1", st["fired_rules"][0]["rule_id"])
        # a review rule proposes, never auto-acts (Open-Decision #5 carries over)
        self.assertFalse(st["fired_rules"][0]["auto_actable"])
        # no event -> no fire
        st2 = sen.sweep_thesis_only(ticker="CEG", thesis=_body(), events={})
        self.assertEqual([], st2["fired_rules"])

    def test_engine_metric_rules_fail_closed_not_fire(self):
        body = _body(rules=[tl.new_rule("phi < 1.0", "alert", rid="r1")])
        st = sen.sweep_thesis_only(ticker="CEG", thesis=body)
        self.assertEqual([], st["fired_rules"])              # phi unknown -> leg False

    def test_integrity_below_floor_alert_and_ack_dedupe(self):
        body = _body(claims=[
            tl.new_claim("a", cid="c1", check="manual", status="broken"),
            tl.new_claim("b", cid="c2", check="manual", status="broken"),
            tl.new_claim("c", cid="c3", check="manual", status="holds")])
        st = sen.sweep_thesis_only(ticker="CEG", thesis=body)
        self.assertTrue(st["integrity"]["below_floor"])
        self.assertEqual(["CEG:integrity"], [a["key"] for a in st["new_alerts"]])
        acked = sen.sweep_thesis_only(ticker="CEG", thesis=body,
                                      acknowledged_keys={"CEG:integrity"})
        self.assertEqual([], acked["new_alerts"])            # acked -> not new again

    def test_engine_dependent_checks_are_stamped_not_silent(self):
        st = sen.sweep_thesis_only(ticker="CEG", thesis=_body())
        self.assertIn("not_applicable", st["liquidity"])
        self.assertIn("not_applicable", st["window"])
        self.assertEqual("n/a (not held)", st["size_gate"])
        self.assertIsNone(st["size_band_exception_allowed"])
        self.assertIn("[thesis-only]", sen.status_to_memory_text(st))


class CoreWiringTests(unittest.TestCase):
    """core.sentinel_sweep with the engine down (as it is under test) sweeps the theses."""

    def setUp(self):
        self.mem_tmp = tempfile.mktemp(suffix=".jsonl")
        self.cal_tmp = tempfile.mktemp(suffix=".jsonl")
        self._saved = (core.MEMORY_PATH, core.CALENDAR_PATH)
        core.MEMORY_PATH = Path(self.mem_tmp)
        core.CALENDAR_PATH = Path(self.cal_tmp)
        mem = LivingMemory(self.mem_tmp)
        mem.write("thesis", text="t", ticker="CEG", tags=["thesis"], meta=_body(), source="test")
        mu = tl.build_thesis("MU", stance="REJECT",
                             claims=[tl.new_claim("no long held", cid="c1", check="manual",
                                                  status="holds")],
                             rules=[tl.new_rule("event:supply_data", "alert", rid="r1")])
        mem.write("thesis", text="t", ticker="MU", tags=["thesis"], meta=mu, source="test")

    def tearDown(self):
        core.MEMORY_PATH, core.CALENDAR_PATH = self._saved
        for p in (self.mem_tmp, self.cal_tmp):
            if os.path.exists(p):
                os.remove(p)

    def test_sweeps_all_theses_engine_down_and_persists(self):
        r = core.sentinel_sweep()
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["engine_running"])
        self.assertEqual({"CEG", "MU"}, {n["ticker"] for n in r["names"]})
        self.assertTrue(all(n.get("mode") == "thesis-only" for n in r["names"]))
        self.assertIn("thesis-only", r.get("note", ""))
        mem = LivingMemory(self.mem_tmp)
        self.assertEqual(2, len(mem.query(type="sentinel", limit=0)))

    def test_ticker_filter_narrows(self):
        r = core.sentinel_sweep(ticker="mu")
        self.assertEqual(["MU"], [n["ticker"] for n in r["names"]])

    def test_a_hit_calendar_window_arms_the_rule_through_the_sweep(self):
        """End-to-end: window marked hit -> event -> rule fires -> alert lands in the status."""
        cal = CatalystCalendar(self.cal_tmp)
        e = cal.write(kind="supply_data", title="DRAM contract rollover", ticker="MU",
                      window_start="2026-07-01", window_end="2026-07-31", confidence="guided")
        cal.set_status(e["id"], "hit")
        r = core.sentinel_sweep(ticker="MU")
        mu = r["names"][0]
        self.assertEqual(1, mu["new_alerts"])
        # superseded theses are not double-swept: still exactly one status per name per sweep
        self.assertEqual(1, len([n for n in r["names"] if n["ticker"] == "MU"]))


if __name__ == "__main__":
    unittest.main()
