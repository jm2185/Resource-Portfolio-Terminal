"""H3 — the deterministic calibration FLYWHEEL turn (closing the loop).

The capture loop's parts already existed (freeze on council_verdict, sweep_outcomes, the per-archetype
prior injection), but it only turned if a council ran AND an agent remembered the sweep tool. These
guard the closing fix: a PURE planner (calibration.plan_flywheel_actions) decides freeze/close, and the
engine turns it on its own heartbeat (CommodityExMonitor._turn_calibration_flywheel) — writing the same
decision/outcome Living-Memory schema the MCP tools use, so both paths feed one shared ledger.

Engine-free where possible: the planner is pure; the engine method is exercised on a bare monitor
(__new__, no workers) with a temp Living-Memory store, so the versioned record is never touched.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest

import calibration as cal
import engine
import living_memory


def _basket(ticker="AGA.V", directive="BELOW FLOOR — ACCUMULATE", price=1.00, *,
            eval_only=False, rho=3.0, phi=1.2):
    return {"ticker": ticker, "directive": directive, "archetype": "option_convexity",
            "eval_only": eval_only,
            "ladder": {"price": price, "floor": 0.80, "bear": 0.95, "base": 1.50, "bull": 2.50},
            "pillars": {"V": {"rho": rho, "floor_coverage": phi}}, "gate": {"cap": 7}}


def _open_decision(ticker="AGA.V", verdict="BELOW FLOOR — ACCUMULATE", price=1.00, ts="x"):
    return {"id": f"d-{ticker}", "ticker": ticker, "ts": ts,
            "meta": {"ticker": ticker, "verdict": verdict, "side": "long", "price": price,
                     "legs": {"floor": 0.80, "bear": 0.95, "base": 1.50, "bull": 2.50},
                     "rho": 3.0, "phi": 1.2, "archetype": "option_convexity"}}


class StanceFamilyTests(unittest.TestCase):
    def test_canonical_vocab(self):
        self.assertEqual(cal.stance_family("BELOW FLOOR — ACCUMULATE · watch"), "accumulate")
        self.assertEqual(cal.stance_family("UPSIDE SPENT — TRIM"), "trim")
        self.assertEqual(cal.stance_family("DE-RISK / EXIT"), "exit")
        self.assertEqual(cal.stance_family("QUALITY — CORE HOLD"), "hold")

    def test_core_action_key_delegates(self):
        import core
        self.assertEqual(core._action_key("UPSIDE SPENT — TRIM"), "trim")
        self.assertEqual(core._action_key("ACCUMULATE"), cal.stance_family("ACCUMULATE"))


class PurePlannerTests(unittest.TestCase):
    def test_no_open_decision_freezes(self):
        plan = cal.plan_flywheel_actions([], [_basket()], age_days_fn=lambda ts: 0)
        self.assertEqual(len(plan["freeze"]), 1)
        self.assertEqual(plan["close"], [])

    def test_young_same_stance_is_a_noop(self):
        plan = cal.plan_flywheel_actions([_open_decision()], [_basket()], age_days_fn=lambda ts: 10)
        self.assertEqual(plan["freeze"], [])
        self.assertEqual(plan["close"], [])

    def test_horizon_closes_and_refreezes(self):
        plan = cal.plan_flywheel_actions([_open_decision()], [_basket(price=1.30)],
                                         horizon_days=90, age_days_fn=lambda ts: 120)
        self.assertEqual(len(plan["close"]), 1)
        self.assertEqual(plan["close"][0]["reason"], "horizon")
        self.assertEqual(plan["close"][0]["realized_price"], 1.30)     # graded at the live mark
        self.assertEqual(len(plan["freeze"]), 1)                       # tracking stays continuous

    def test_stance_change_closes_and_refreezes(self):
        plan = cal.plan_flywheel_actions([_open_decision()], [_basket(directive="UPSIDE SPENT — TRIM")],
                                         age_days_fn=lambda ts: 5)
        self.assertEqual(len(plan["close"]), 1)
        self.assertEqual(plan["close"][0]["reason"], "stance-change")
        self.assertEqual(len(plan["freeze"]), 1)

    def test_stance_change_without_a_mark_leaves_the_bet_open(self):
        b = _basket(directive="UPSIDE SPENT — TRIM", price=None)
        plan = cal.plan_flywheel_actions([_open_decision()], [b], age_days_fn=lambda ts: 5)
        self.assertEqual(plan["close"], [])                            # can't fairly close at no price
        self.assertEqual(plan["freeze"], [])

    def test_newest_open_decision_wins(self):
        old = _open_decision(verdict="ACCUMULATE")
        old["id"] = "d-old"
        new = _open_decision(verdict="ACCUMULATE")           # same stance, newest first in the list
        plan = cal.plan_flywheel_actions([new, old], [_basket()], age_days_fn=lambda ts: 1)
        self.assertEqual(plan["freeze"], [])                 # dedups to the newest; no double-freeze


class LearnedBaseRateTests(unittest.TestCase):
    """H3→D4: the desk's OWN per-archetype base rates from closed outcomes, fed into the anchor."""

    @staticmethod
    def _scored(arch, signed, *, cap=0.5, floor=True, result=None):
        res = result or ("win" if signed > 0 else "loss")
        return {"status": "scored", "result": res, "signed_return": signed, "upside_capture": cap,
                "floor_held": floor, "archetype": arch}

    def test_empty_until_outcomes_close(self):
        self.assertEqual(cal.learned_base_rates([]), {})
        self.assertEqual(cal.learned_base_rates([{"status": "unscored"}]), {})

    def test_per_archetype_rollup_flags_small_n(self):
        scored = [self._scored("option_convexity", 0.8), self._scored("option_convexity", -0.2)]
        lr = cal.learned_base_rates(scored)
        self.assertEqual(lr["option_convexity"]["n"], 2)
        self.assertIsNotNone(lr["option_convexity"]["expectancy"])
        self.assertTrue(lr["option_convexity"]["data_limited"])         # n=2 < MIN_PERSONAL_N

    def test_anchor_thin_sample_is_context_not_a_bar(self):
        lr = cal.learned_base_rates([self._scored("option_convexity", 0.4)])
        a = cal.candidate_anchor("option_convexity", learned=lr)
        self.assertIn("desk_track_record", a)
        self.assertIn("not yet a hard bar", a["line"])

    def test_anchor_warm_sample_becomes_a_bar(self):
        # ≥ MIN_PERSONAL_N closed, mixed, so the sample is warm (not data_limited)
        scored = [self._scored("option_convexity", r) for r in (0.9, 0.7, 0.5, -0.2, -0.3, 0.6)]
        lr = cal.learned_base_rates(scored)
        self.assertFalse(lr["option_convexity"]["data_limited"])
        a = cal.candidate_anchor("option_convexity", learned=lr)
        self.assertIn("DESK BAR", a["line"])
        self.assertIn("must clear THAT", a["line"])

    def test_anchor_without_learned_is_unchanged(self):
        base = cal.candidate_anchor("option_convexity")
        self.assertNotIn("desk_track_record", base)        # opt-in: no learned dict → no desk block


class EngineTurnTests(unittest.TestCase):
    """The engine-side I/O turn on a bare monitor + temp Living-Memory store."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.mem = living_memory.LivingMemory(path=self.tmp)
        self.mon = engine.CommodityExMonitor.__new__(engine.CommodityExMonitor)   # no __init__/workers
        self.mon._lm = self.mem
        self.mon.terminal_state = {"mri": 47.0, "posture": {"code": "spear_exploit"},
                                   "macro_tape": {"net_tilt": "RISK-ON"}, "conviction_mode": {}}

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def _set_book(self, baskets):
        self.mon.terminal_state["conviction_mode"] = {"baskets": baskets}

    def test_freezes_only_held_priced_non_eval_names(self):
        self._set_book([
            _basket("AGA.V"),
            _basket("KTN.V", eval_only=True),                # rated, not held → no decision
            _basket("XYZ.V", price=None),                    # unpriced (feed miss) → skipped
        ])
        self.mon._turn_calibration_flywheel(interval_s=0)
        decs = self.mem.query(type="decision", limit=0)
        self.assertEqual([d["ticker"] for d in decs], ["AGA.V"])
        meta = decs[0]["meta"]
        self.assertEqual(meta["rho"], 3.0)                   # ρ/φ captured from pillars.V
        self.assertEqual(meta["phi"], 1.2)
        self.assertEqual(decs[0]["source"], "engine-flywheel")
        self.assertIn("flywheel", decs[0]["tags"])

    def test_idempotent_same_stance_pre_horizon(self):
        self._set_book([_basket("AGA.V")])
        self.mon._turn_calibration_flywheel(interval_s=0)
        self.mon._turn_calibration_flywheel(interval_s=0)    # second turn: same stance, young → noop
        self.assertEqual(len(self.mem.query(type="decision", limit=0)), 1)

    def test_throttle_blocks_within_interval(self):
        self._set_book([_basket("AGA.V")])
        self.mon._flywheel_ts = time.time()
        self.mon._turn_calibration_flywheel(interval_s=3600)
        self.assertEqual(self.mem.query(type="decision", limit=0), [])

    def test_horizon_closes_old_and_reopens(self):
        # seed an OPEN decision dated ~100 days ago, directly in the temp store
        old = self.mem.write("decision", text="DECISION old", ticker="AGA.V",
                             tags=["decision"], meta=_open_decision()["meta"],
                             source="seed", ts="2026-03-01T00:00:00")
        self._set_book([_basket("AGA.V", price=1.30)])
        self.mon._turn_calibration_flywheel(interval_s=0)
        outs = self.mem.query(type="outcome", limit=0)
        self.assertEqual(len(outs), 1)
        self.assertIn(old["id"], outs[0]["refs"])            # the outcome grades the aged decision
        self.assertEqual(outs[0]["meta"]["status"], "scored")
        self.assertIn("horizon", outs[0]["text"])
        # and a fresh decision was re-frozen so the seat keeps a live bet
        self.assertEqual(len(self.mem.query(type="decision", limit=0)), 2)

    def test_empty_book_writes_nothing(self):
        self._set_book([])
        self.mon._turn_calibration_flywheel(interval_s=0)
        self.assertEqual(self.mem.query(type="decision", limit=0), [])

    def test_closing_persists_a_learned_snapshot_deduped_daily(self):
        # an aged open decision that closes this turn → a calibration_snapshot is rolled up
        self.mem.write("decision", text="DECISION old", ticker="AGA.V", tags=["decision"],
                       meta=_open_decision()["meta"], source="seed", ts="2026-03-01T00:00:00")
        self._set_book([_basket("AGA.V", price=1.30)])
        self.mon._turn_calibration_flywheel(interval_s=0)
        snaps = self.mem.query(type="calibration_snapshot", limit=0)
        self.assertEqual(len(snaps), 1)
        self.assertIn("option_convexity", (snaps[0]["meta"] or {}).get("learned", {}))
        # a second turn the same day does not write a duplicate snapshot
        self.mon._turn_calibration_flywheel(interval_s=0)
        self.assertEqual(len(self.mem.query(type="calibration_snapshot", limit=0)), 1)


if __name__ == "__main__":
    unittest.main()
