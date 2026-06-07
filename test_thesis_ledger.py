"""
Tests for the thesis layer (living_memory thesis helpers + thesis_ledger.py, Forge M2).

Pins the M2 acceptance: a saved thesis round-trips with claims/rules intact; the Ledger lists REJECTs
(graveyard) alongside APPROVEs (hall of fame); every rule.trigger is parsed at save and a malformed
one is rejected with a clear error.
"""
import os
import tempfile
import unittest

import living_memory as lm
import thesis_ledger as tl


def _good_thesis(ticker="AGA.V", stance="APPROVE"):
    return tl.build_thesis(
        ticker, archetype="option_convexity", stance=stance,
        idiosyncratic_catalyst="Q3 Nevada drill",
        claims=[
            tl.new_claim("18-month runway", metric="runway_months", op=">=", threshold=18),
            tl.new_claim("permitting faster than Canadian peers"),   # manual
        ],
        rules=[
            tl.new_rule("phi < 1.0 AND no_catalyst_within_days(30)", "trim_to", arg=0.40),
            tl.new_rule("before(event:bought_deal, event:assays)", "exit"),
        ],
        expected={"rho": 3.2, "bull_upside_pct": 138, "floor": 0.824, "conviction": "spear"},
    )


class BuildTests(unittest.TestCase):
    def test_ids_autoassigned(self):
        t = _good_thesis()
        self.assertEqual([c["id"] for c in t["claims"]], ["c1", "c2"])
        self.assertEqual([r["id"] for r in t["rules"]], ["r1", "r2"])

    def test_claim_check_inferred(self):
        t = _good_thesis()
        self.assertEqual(t["claims"][0]["check"], "engine")    # has a metric
        self.assertEqual(t["claims"][1]["check"], "manual")    # no metric


class ValidateTests(unittest.TestCase):
    def test_good_thesis_validates(self):
        ok, errors = tl.validate_thesis(_good_thesis())
        self.assertTrue(ok, errors)

    def test_malformed_rule_trigger_rejected_with_clear_error(self):
        t = _good_thesis()
        t["rules"][0]["trigger"] = "phi < < 1.0"               # garbage
        ok, errors = tl.validate_thesis(t)
        self.assertFalse(ok)
        self.assertTrue(any("does not parse" in e for e in errors))

    def test_out_of_vocab_trigger_rejected(self):
        t = _good_thesis()
        t["rules"][0]["trigger"] = "sharpe > 2"                # not a known metric -> rejected
        ok, errors = tl.validate_thesis(t)
        self.assertFalse(ok)

    def test_engine_claim_needs_valid_metric_op_threshold(self):
        t = _good_thesis()
        t["claims"][0] = {"id": "c1", "text": "bad", "metric": "not_a_metric",
                          "op": "≥", "threshold": "x", "check": "engine"}
        ok, errors = tl.validate_thesis(t)
        self.assertFalse(ok)
        self.assertTrue(any("metric" in e for e in errors))

    def test_trim_to_requires_weight_arg(self):
        t = _good_thesis()
        t["rules"][0]["arg"] = 1.5                              # out of (0,1]
        ok, errors = tl.validate_thesis(t)
        self.assertFalse(ok)

    def test_bad_stance_rejected(self):
        t = _good_thesis(stance="MAYBE")
        ok, errors = tl.validate_thesis(t)
        self.assertFalse(ok)

    def test_validate_or_raise(self):
        with self.assertRaises(ValueError):
            tl.validate_thesis_or_raise(_good_thesis(stance="MAYBE"))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.mem = lm.LivingMemory(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def _save(self, thesis):
        tl.validate_thesis_or_raise(thesis)
        return self.mem.write("thesis", text=tl.thesis_summary_line(thesis),
                              ticker=thesis["ticker"], meta=thesis)

    def test_thesis_round_trips_with_claims_and_rules(self):
        self._save(_good_thesis())
        got = self.mem.latest_thesis("AGA.V")
        self.assertIsNotNone(got)
        body = got["meta"]
        self.assertEqual(len(body["claims"]), 2)
        self.assertEqual(body["rules"][0]["trigger"], "phi < 1.0 AND no_catalyst_within_days(30)")
        self.assertEqual(body["rules"][0]["action"], "trim_to")
        self.assertEqual(body["expected"]["rho"], 3.2)

    def test_ledger_lists_rejects_alongside_approves(self):
        self._save(_good_thesis("AGA.V", stance="APPROVE"))
        self._save(_good_thesis("XYZ.V", stance="REJECT"))
        led = tl.Ledger(self.mem)
        stances = {e["ticker"]: e["stance"] for e in led.entries()}
        self.assertEqual(stances["AGA.V"], "APPROVE")
        self.assertEqual(stances["XYZ.V"], "REJECT")
        self.assertEqual(len(led.graveyard()), 1)
        self.assertEqual(led.graveyard()[0]["ticker"], "XYZ.V")

    def test_ledger_joins_outcomes_and_hall_of_fame(self):
        self._save(_good_thesis("AGA.V", stance="APPROVE"))
        # a realized winning outcome AFTER the thesis
        self.mem.write("outcome", text="OUTCOME WIN", ticker="AGA.V",
                       meta={"status": "scored", "result": "win", "realized_return": 1.2})
        led = tl.Ledger(self.mem)
        e = next(x for x in led.entries() if x["ticker"] == "AGA.V")
        self.assertEqual(e["wins"], 1)
        self.assertTrue(e["resolved"])
        self.assertEqual(len(led.hall_of_fame()), 1)

    def test_theses_helper_filters_rejects(self):
        self._save(_good_thesis("AGA.V", stance="APPROVE"))
        self._save(_good_thesis("XYZ.V", stance="REJECT"))
        self.assertEqual(len(self.mem.theses()), 2)
        self.assertEqual(len(self.mem.theses(include_rejects=False)), 1)
        self.assertEqual(len(self.mem.theses(stance="REJECT")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
