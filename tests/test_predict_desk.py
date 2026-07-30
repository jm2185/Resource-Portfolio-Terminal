"""The PREDICT DESK's pure section builders (cockpit_widgets) — plain data → rich.Text, so the
full-screen surface renders identically in tests and in the cockpit. Also pins the nav contract:
the desk is a first-class Blend tab (key 7 / F) on every surface."""
from __future__ import annotations

import unittest

import cockpit_widgets as cw


DASH = {
    "available": True, "status": "LIVE", "as_of": 1_785_000_000.0,
    "universe": {"events": 46, "markets": 535, "quoted": 409, "ladders": 24, "partitions": 7},
    "fees_model": {"ws_commission_per_contract": 0.02, "kalshi_fee_rate": 0.07,
                   "fx_spread_oneway": 0.015, "fx_applies": True},
    "errors": [],
    "opportunities": [
        {"lane": "L1", "kind": "ladder", "event_ticker": "KXFED-26SEP", "net": 0.042,
         "size_cap": 130.0, "depth_validated": True, "net_at_size": 0.038,
         "legs": [{"side": "yes", "ticker": "KXFED-26SEP-T3.75", "ask": 0.30},
                  {"side": "no", "ticker": "KXFED-26SEP-T4.00", "ask": 0.55}]},
        {"lane": "L2", "kind": "value", "ticker": "KXCPIYOY-26AUG-T2.7", "side": "yes",
         "ask": 0.60, "p_hat": 0.72, "source": "nowcast", "net": 0.091, "kelly": 0.1},
    ],
}


class TestDeskBuilders(unittest.TestCase):
    def test_status_strip(self):
        t = cw.predict_desk_status(DASH).plain
        self.assertIn("LIVE", t)
        self.assertIn("46 events", t)
        self.assertIn("24 ladders", t)
        self.assertIn("placeholders until launch", t)      # the fee caveat is said out loud

    def test_l1_lane_spells_legs_and_depth(self):
        t = cw.predict_desk_lane(DASH, "L1").plain
        self.assertIn("riskless if filled", t)
        self.assertIn("+4.2¢", t)
        self.assertIn("YES", t)
        self.assertIn("depth✓", t)
        self.assertNotIn("KXCPIYOY", t)                    # lanes never mix

    def test_l2_lane_labeled_a_bet(self):
        t = cw.predict_desk_lane(DASH, "L2").plain
        self.assertIn("a BET, never arb", t)
        self.assertIn("p̂=0.72", t)
        self.assertIn("Kelly", t)
        self.assertNotIn("KXFED-26SEP ", t)

    def test_empty_lanes_render_meaning(self):
        empty = {"available": True, "opportunities": []}
        self.assertIn("clean", cw.predict_desk_lane(empty, "L1").plain)
        self.assertIn("no live edge", cw.predict_desk_lane(empty, "L2").plain)

    def test_fv_book_and_ledger(self):
        fv = {"KXFED-26SEP-T4.00": {"p_hat": 0.55, "band": [0.5, 0.6],
                                    "source": "OIS strip", "as_of": "2026-07-30"}}
        t = cw.predict_desk_fv(fv).plain
        self.assertIn("KXFED-26SEP-T4.00", t)
        self.assertIn("OIS strip", t)
        self.assertIn("REQUIRES a source", cw.predict_desk_fv({}).plain)
        rows = [{"date": "2026-07-30", "lane": "L1", "kind": "partition_no",
                 "event_ticker": "KXHIGHNY-26JUL30", "net": 0.01}]
        t = cw.predict_desk_ledger(rows).plain
        self.assertIn("KXHIGHNY-26JUL30", t)
        self.assertIn("+1.0¢", t)
        self.assertIn("empty", cw.predict_desk_ledger([]).plain)

    def test_thin_input_never_raises(self):
        for fn in (cw.predict_desk_status, cw.predict_desk_fv, cw.predict_desk_ledger):
            fn(None)
        cw.predict_desk_lane(None, "L1")
        cw.predict_desk_lane({}, "L2")


class TestNavContract(unittest.TestCase):
    def test_predict_is_a_first_class_tab(self):
        keys = [k for k, _, _, _ in cw.BLEND_NAV]
        self.assertIn("predict", keys)
        import cockpit_surfaces as cs
        self.assertTrue(hasattr(cs, "PredictSurface"))
        self.assertEqual(cs.PredictSurface.NAV_ID, "predict")
        binds = {getattr(b, "key", None) for b in cs.BlendSurface.BINDINGS}
        self.assertIn("7", binds)
        hub_binds = {getattr(b, "key", None) for b in cs.BlendHubScreen.BINDINGS}
        self.assertIn("7", hub_binds)


if __name__ == "__main__":
    unittest.main()
