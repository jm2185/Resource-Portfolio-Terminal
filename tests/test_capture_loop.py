"""
Integration tests for the calibration CAPTURE LOOP + CONSUMPTION WIRE (the spine that makes the
Tier 1–4 surfaces live instead of inert).

These guard links 1→3 end-to-end against silent regression:
  * CAPTURE — a council_verdict write deterministically freezes a gradeable decision (frozen ρ/φ),
    deduped against re-affirmation, with a stance-change closing the old bet; sweep_outcomes() closes
    decisions at the horizon; backfill_decisions() primes the loop from the live book.
  * CONSUMPTION — get_conviction_ratings (what every Council seat reads) now carries the calibration
    prior (path / spear backstop), so the new guards actually reach the deciders.

Engine-free: the live book is injected (CaptureLoopTests) or the /state HTTP is stubbed
(ConsumptionWireTests). Memory is pointed at a temp store so the versioned record is never touched.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import core
import calibration as cal

#: a single convex spear, the shape the decision-quality + spear surfaces key off
_LADDER = {"price": 1.00, "floor": 0.80, "bear": 0.95, "base": 1.50, "bull": 2.50}


def _book(price=1.00, directive="BELOW FLOOR — ACCUMULATE"):
    ladder = dict(_LADDER, price=price)
    return {"engine_running": True, "baskets": [{
        "ticker": "AGA.V", "archetype": "option_convexity", "directive": directive,
        "ladder": ladder, "asymmetry": {"rho": 3.0, "floor_coverage": 1.2}, "gate": {"cap": 7}}]}


def _spear_decision_meta(price=1.0):
    return {"ticker": "AGA.V", "verdict": "BELOW FLOOR — ACCUMULATE", "side": "long", "price": price,
            "legs": {"floor": 0.8, "bear": 0.95, "base": 1.5, "bull": 2.5},
            "rho": 3.0, "phi": 1.2, "archetype": "option_convexity"}


class CaptureLoopTests(unittest.TestCase):
    """The freeze/record half — the torque the loop was missing. Live book injected, memory temp'd."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._orig_path, core.MEMORY_PATH = core.MEMORY_PATH, self.tmp
        # the decision↔snapshot join writes the valuation ledger — temp it like memory, so the
        # versioned track record is never touched by a test
        self.tmp_ledger = tempfile.mktemp(suffix=".jsonl")
        self._orig_ledger, core.LEDGER_PATH = core.LEDGER_PATH, self.tmp_ledger
        self._orig_gcr = core.get_conviction_ratings
        self._orig_http = core._http_get_json
        core.get_conviction_ratings = lambda with_calibration=True: _book()
        core._http_get_json = mock.Mock(side_effect=RuntimeError("no engine in test"))

    def tearDown(self):
        core.MEMORY_PATH = self._orig_path
        core.LEDGER_PATH = self._orig_ledger
        core.get_conviction_ratings = self._orig_gcr
        core._http_get_json = self._orig_http
        for p in (self.tmp, self.tmp_ledger):
            if os.path.exists(p):
                os.remove(p)

    def _decisions(self):
        return core._living_memory().query(type="decision", limit=0)

    def _outcomes(self):
        return core._living_memory().query(type="outcome", limit=0)

    def test_council_verdict_freezes_a_gradeable_decision(self):
        res = core.memory_write("council_verdict", ticker="AGA.V",
                                meta_json=json.dumps({"stance": "PRESS"}))
        self.assertTrue(res["ok"])
        decs = self._decisions()
        self.assertEqual(len(decs), 1)                 # the hook froze a decision off the verdict
        self.assertEqual(decs[0]["meta"]["rho"], 3.0)  # with the asymmetry shape captured, not dropped
        self.assertEqual(decs[0]["meta"]["phi"], 1.2)

    def test_reaffirmation_does_not_duplicate(self):
        core.memory_write("council_verdict", ticker="AGA.V", meta_json=json.dumps({"stance": "PRESS"}))
        core.memory_write("council_verdict", ticker="AGA.V",
                          meta_json=json.dumps({"stance": "ACCUMULATE"}))  # same action family
        self.assertEqual(len(core._open_decisions(core._living_memory(), "AGA.V")), 1)

    def test_stance_change_closes_old_and_opens_new(self):
        core.memory_write("council_verdict", ticker="AGA.V", meta_json=json.dumps({"stance": "PRESS"}))
        core.get_conviction_ratings = lambda with_calibration=True: _book(2.0, "UPSIDE SPENT — TRIM")
        core.memory_write("council_verdict", ticker="AGA.V", meta_json=json.dumps({"stance": "TRIM"}))
        self.assertEqual(len(self._outcomes()), 1)     # the accumulate bet was closed at the mark
        self.assertEqual(len(core._open_decisions(core._living_memory(), "AGA.V")), 1)  # trim now open

    def test_sweep_records_outcome_at_horizon(self):
        mem = core._living_memory()
        mem.write("decision", text="old", ticker="AGA.V", meta=_spear_decision_meta(),
                  ts="2020-01-01T00:00:00Z")                       # well past any horizon
        res = core.sweep_outcomes(horizon_days=90)
        self.assertEqual(res["n_closed"], 1)
        self.assertEqual(len(self._outcomes()), 1)
        # not-due decisions are left open
        mem.write("decision", text="fresh", ticker="AGA.V", meta=_spear_decision_meta())
        self.assertEqual(core.sweep_outcomes(horizon_days=90)["n_closed"], 0)

    def test_decision_joins_to_a_ledger_snapshot(self):
        """Validation flywheel: a frozen decision carries the id of the FULL valuation snapshot
        that produced it (trigger=decision) — input-attributed, not just legs+ρ/φ."""
        core.memory_write("council_verdict", ticker="AGA.V",
                          meta_json=json.dumps({"stance": "PRESS"}))
        dec = self._decisions()[0]
        sid = dec["meta"].get("valuation_snapshot_id")
        self.assertTrue(sid, "decision meta must carry valuation_snapshot_id")
        import valuation_ledger as vl
        snap = vl.ValuationLedger(path=str(core.LEDGER_PATH)).get(sid)
        self.assertIsNotNone(snap)
        self.assertEqual(snap["trigger"], "decision")
        self.assertEqual(snap["ticker"], "AGA.V")
        self.assertEqual(snap["asymmetry"]["rho"], 3.0)

    def test_backfill_primes_then_is_idempotent(self):
        res = core.backfill_decisions()
        self.assertTrue(res["ok"])
        self.assertIn("AGA.V", res["frozen"])
        self.assertEqual(len(self._decisions()), 1)
        core.backfill_decisions()                       # an open decision already exists → no dup
        self.assertEqual(len(core._open_decisions(core._living_memory(), "AGA.V")), 1)


class ConsumptionWireTests(unittest.TestCase):
    """The read half — the new prior must reach the deciders via get_conviction_ratings, not just the
    world brief no Council seat fetches."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._orig_path, core.MEMORY_PATH = core.MEMORY_PATH, self.tmp
        mem = core._living_memory()
        dec = mem.write("decision", text="d", ticker="AGA.V", meta=_spear_decision_meta())
        scored = cal.score_outcome(dec["meta"], 0.7)    # a loss on a well-shaped spear
        mem.write("outcome", text="o", ticker="AGA.V", meta=scored, refs=[dec["id"]])
        self._orig_http = core._http_get_json
        core._http_get_json = lambda url, timeout=2.0: {
            "status": "ok", "mri": 5.0,
            "conviction_mode": {"baskets": [], "context": {}, "top_pick": None}}

    def tearDown(self):
        core.MEMORY_PATH = self._orig_path
        core._http_get_json = self._orig_http
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_calibration_prior_carries_path_and_spear(self):
        cp = core._calibration_prior(["option_convexity"])
        self.assertIsNotNone(cp)
        self.assertIn("path", cp)
        self.assertIn("spear_backstop", cp)
        self.assertEqual(cp["spear_backstop"]["spear_decisions"], 1)
        self.assertEqual(cp["spear_backstop"]["false_positives"], 1)   # the loss is a spear FP

    def test_conviction_ratings_now_includes_calibration(self):
        r = core.get_conviction_ratings()               # real fn; engine /state stubbed
        self.assertTrue(r["engine_running"])
        self.assertIn("calibration", r)                 # the deciders now actually see the prior
        self.assertIn("spear_backstop", r["calibration"])

    def test_capture_callers_opt_out_of_calibration(self):
        self.assertNotIn("calibration", core.get_conviction_ratings(with_calibration=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
