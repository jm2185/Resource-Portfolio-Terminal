"""The PREDICT scanner's thin engine legs, bound to a no-boot stub (no network, no uvicorn):
the assessment marshals the cached snapshot + fair values into the pure sweep, and the _fire twin
emits exactly the three artifacts — a Signals-rail activity note, a regime-stamped Living-Memory
sentinel entry, and an append-only predict_ledger line — deduped so an unchanged basket never
fires twice in a day. So a regression that silently disarms the alert path (the whole point of
the scanner) can't return."""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
import unittest

from tests.helpers import TempMemoryMixin, make_engine_stub

import engine as engine_mod
import living_memory


def _snapshot(now_ts):
    near = (_dt.datetime.fromtimestamp(now_ts, _dt.timezone.utc)
            + _dt.timedelta(days=25)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def mkt(tk, yes_ask, no_ask, strike):
        return {"ticker": tk, "event_ticker": "KXFED-26SEP", "title": tk, "yes_sub_title": tk,
                "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
                "status": "active", "close_time": near, "yes_bid": None, "yes_ask": yes_ask,
                "no_bid": None, "no_ask": no_ask, "yes_bid_size": 500.0, "yes_ask_size": 500.0,
                "last_price": None, "liquidity": None, "volume_24h": None, "open_interest": None}

    # bid(>4.00) implied 0.45 > ask(>3.75) 0.30 -> a ladder-dominance Dutch book
    return {"ts": now_ts, "series": ["KXFED"], "errors": [],
            "events": [{"event_ticker": "KXFED-26SEP", "series_ticker": "KXFED",
                        "title": "Fed Sept", "category": "Economics", "mutually_exclusive": False,
                        "available_on_brokers": True,
                        "markets": [mkt("KXFED-26SEP-T3.75", 0.30, 0.75, 3.75),
                                    mkt("KXFED-26SEP-T4.00", 0.60, 0.55, 4.00)]}],
            "orderbooks": {}}


NO_FEES_CFG = {"predict_arb_monitor": {
    "fees": {"ws_commission_per_contract": 0.0, "clearing_fee_per_contract": 0.0,
             "kalshi_fee_applies": False, "fx_applies": False}}}


class TestPredictArbEngineWiring(TempMemoryMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._led = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._led.close()
        os.unlink(self._led.name)                  # the engine leg must create it on first fire
        self._prev_led = engine_mod.PREDICT_LEDGER_PATH
        self._prev_fv = engine_mod.PREDICT_FV_PATH
        engine_mod.PREDICT_LEDGER_PATH = self._led.name
        engine_mod.PREDICT_FV_PATH = self._led.name + ".fv.json"

    def tearDown(self):
        engine_mod.PREDICT_LEDGER_PATH = self._prev_led
        engine_mod.PREDICT_FV_PATH = self._prev_fv
        for p in (self._led.name, self._led.name + ".fv.json"):
            try:
                os.unlink(p)
            except OSError:
                pass
        super().tearDown()

    def _stub(self):
        now_ts = _dt.datetime(2026, 7, 21, 12, 0, tzinfo=_dt.timezone.utc).timestamp()
        s = make_engine_stub("_predict_cfg", "_predict_arb_assessment", "_fire_predict_arb",
                             "_predict_fair_values", "set_predict_fair_value",
                             config=NO_FEES_CFG,
                             state_cache={"predict_snapshot": _snapshot(now_ts),
                                          "predict_status": "LIVE", "predict_ts": now_ts})
        s.activity = []
        s.record_agent_activity = lambda ev: s.activity.append(ev)
        return s

    def test_assessment_finds_the_dutch_book(self):
        s = self._stub()
        dash = s._predict_arb_assessment()
        self.assertTrue(dash["available"])
        self.assertEqual(dash["status"], "LIVE")
        kinds = {o["kind"] for o in dash["opportunities"]}
        self.assertIn("ladder", kinds)
        self.assertTrue(any(f["level"] == "good" for f in dash["flags"]))

    def test_fire_emits_activity_memory_and_ledger_once(self):
        s = self._stub()
        dash = s._predict_arb_assessment()
        s._fire_predict_arb(dash)
        # 1) Signals-rail note
        self.assertTrue(any("PREDICT" in a.get("summary", "") for a in s.activity))
        # 2) Living-Memory sentinel entry, tagged for regime-aware recall
        lm = living_memory.LivingMemory()
        entries = [e for e in lm.query(type="sentinel", limit=0)
                   if "predict_arb" in (e.get("tags") or [])]
        self.assertEqual(len(entries), len(dash["flags"]))
        self.assertEqual(entries[0]["ticker"], "KXFED-26SEP")
        # 3) the append-only fired ledger with full pricing context
        with open(engine_mod.PREDICT_LEDGER_PATH) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(lines), len(dash["flags"]))
        self.assertEqual(lines[0]["lane"], "L1")
        self.assertIn("legs", lines[0]["opportunity"])
        # same day, unchanged nets -> fully deduped, nothing new anywhere
        n_act = len(s.activity)
        s._fire_predict_arb(dash)
        self.assertEqual(len(s.activity), n_act)
        with open(engine_mod.PREDICT_LEDGER_PATH) as f:
            self.assertEqual(len([l for l in f if l.strip()]), len(lines))

    def test_missing_snapshot_is_honest_not_fatal(self):
        s = self._stub()
        s.state_cache = {}
        dash = s._predict_arb_assessment()
        self.assertFalse(dash["available"])
        self.assertIn("warming up", dash["summary"])
        s._fire_predict_arb(dash)                  # no flags -> no artifacts, no raise
        self.assertEqual(s.activity, [])

    def test_fair_value_roundtrip_feeds_l2(self):
        s = self._stub()
        res = s.set_predict_fair_value({"ticker": "KXFED-26SEP-T3.75", "p_hat": 55,
                                        "band": [0.5, 0.6], "source": "OIS strip 2026-07"})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res["p_hat"], 0.55)       # percent form normalized
        fv = s._predict_fair_values()
        self.assertIn("KXFED-26SEP-T3.75", fv)
        # grounded-or-silent: no source -> refused
        bad = s.set_predict_fair_value({"ticker": "X", "p_hat": 0.5})
        self.assertIn("error", bad)
        # the L2 lane actually consumes it: p̂=0.55 vs yes_ask=0.30 -> a value signal appears
        dash = s._predict_arb_assessment()
        self.assertTrue(any(o["lane"] == "L2" and o["ticker"] == "KXFED-26SEP-T3.75"
                            for o in dash["opportunities"]))


if __name__ == "__main__":
    unittest.main()
