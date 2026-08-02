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

    def test_clean_l1_shows_near_miss_reasoning(self):
        clean = {"available": True, "opportunities": [],
                 "thresholds": {"theta_struct": 0.01},
                 "near_misses": [{"kind": "partition_no", "event_ticker": "KXHIGHNY-26JUL31",
                                  "gross": 0.01, "fees": 0.08, "net": -0.099}]}
        t = cw.predict_desk_lane(clean, "L1").plain
        self.assertIn("tightest baskets", t)
        self.assertIn("KXHIGHNY-26JUL31", t)
        self.assertIn("gross  +1.0¢", t)
        self.assertIn("net  -9.9¢", t)
        self.assertIn("≥ +1.0¢", t)
        # the ONE-LINE why: the conclusion pre-computed, not left as an exercise in subtraction
        self.assertIn("why: closest basket nets -9.9¢", t)
        self.assertIn("short 10.9¢", t)                     # theta − net, per row too
        self.assertIn("needs gross ≥ +11.9¢", t)            # theta + the basket's fee+FX stack

    def test_book_overview_renders_active_contracts(self):
        dash = {"available": True,
                "board": [{"ticker": "KXFED-26SEP-T4.00", "yes_bid": 0.30, "yes_ask": 0.33,
                           "days_to_close": 47.3, "volume_24h": 12345.0,
                           "category": "Economics", "event_ticker": "KXFED-26SEP",
                           "event_title": "Fed funds rate after the September meeting?",
                           "sub": "Fed funds at 4.00-4.25% after the Sep meeting?"}]}
        t = cw.predict_desk_board(dash).plain
        self.assertIn("BOOK OVERVIEW", t)
        self.assertIn("KXFED-26SEP-T4.00", t)
        self.assertIn("30/33¢", t)
        self.assertIn("12,345", t)
        # the probability read + the human question lead; the code is the trailing handle
        self.assertIn("YES bid/ask", t)
        self.assertIn("≈32%", t)                            # mid of 30/33 read as probability
        self.assertIn("Fed funds rate after the September meeting?", t)
        self.assertIn("Fed funds at 4.00-4.25%", t)
        self.assertIn("no quoted markets", cw.predict_desk_board({}).plain)

    def test_book_overview_groups_an_event_into_a_distribution(self):
        """Sibling outcomes group under ONE question, sorted by implied probability — the market's
        distribution, which is the research the raw ticker list was hiding."""
        ev = {"event_ticker": "KXFEDDECISION-26SEP", "category": "Economics",
              "event_title": "Fed decision in September?", "days_to_close": 47.1}
        dash = {"available": True, "board": [
            {**ev, "ticker": "KXFEDDECISION-26SEP-H26", "sub": "Hike >25bps",
             "yes_bid": 0.01, "yes_ask": 0.02, "volume_24h": 320823},
            {**ev, "ticker": "KXFEDDECISION-26SEP-H25", "sub": "Hike 25bps",
             "yes_bid": 0.59, "yes_ask": 0.60, "volume_24h": 75584},
            {**ev, "ticker": "KXFEDDECISION-26SEP-H0", "sub": "Fed maintains rate",
             "yes_bid": 0.38, "yes_ask": 0.39, "volume_24h": 59569}]}
        t = cw.predict_desk_board(dash).plain
        self.assertEqual(1, t.count("Fed decision in September?"))   # one header, not three rows
        # outcomes ordered by ≈P descending: 60% hike-25 > 38% hold > 2% hike->25
        self.assertLess(t.index("Hike 25bps"), t.index("Fed maintains rate"))
        self.assertLess(t.index("Fed maintains rate"), t.index("Hike >25bps"))
        self.assertIn("≈60%", t)
        self.assertIn("vol24h 455,976", t)                  # the event's summed volume

    def test_book_overview_collapses_weather_noise_stated_not_hidden(self):
        dash = {"available": True, "board": [
            {"ticker": "KXFED-26SEP-T4.00", "event_ticker": "KXFED-26SEP",
             "event_title": "Fed above 4%?", "sub": "Above 4.00%", "category": "Economics",
             "yes_bid": 0.01, "yes_ask": 0.02, "days_to_close": 47.1, "volume_24h": 15865},
            {"ticker": "KXHIGHNY-26JUL31-B84.5", "event_ticker": "KXHIGHNY-26JUL31",
             "sub": "84° to 85°", "category": "Climate and Weather",
             "yes_bid": 0.99, "yes_ask": 1.00, "days_to_close": 0.3, "volume_24h": 31713}]}
        t = cw.predict_desk_board(dash).plain
        self.assertIn("+1 weather day-markets collapsed", t)
        self.assertNotIn("84° to 85°", t)                   # demoted from the board…
        self.assertIn("31,713", t)                          # …but its volume is stated, not hidden

    def test_verdict_strip_names_the_next_move(self):
        # nothing actionable -> says why AND the concrete unlock, with a real ticker
        clean = {"available": True, "opportunities": [],
                 "thresholds": {"theta_struct": 0.01},
                 "near_misses": [{"kind": "ladder", "event_ticker": "KXFED-26OCT",
                                  "gross": 0.0, "fees": 0.06, "net": -0.09}],
                 "board": [{"ticker": "KXFED-26SEP-T4.00", "category": "Economics"}]}
        t = cw.predict_desk_verdict(clean, {}).plain
        self.assertIn("NEXT MOVE", t)
        self.assertIn("nothing actionable", t)
        self.assertIn("closest short 10¢", t)
        self.assertIn("0 p̂ sourced", t)
        self.assertIn("predict_fair_value('KXFED-26SEP-T4.00'", t)
        # a live L1 flips the strip to ACT
        live = {"available": True, "opportunities": [
            {"lane": "L1", "kind": "ladder", "event_ticker": "KXFED-26OCT", "net": 0.042}]}
        t = cw.predict_desk_verdict(live, {}).plain
        self.assertIn("ACT", t)
        self.assertIn("+4.2¢", t)
        # an L2 edge (no L1) reads BET
        bet = {"available": True, "opportunities": [
            {"lane": "L2", "ticker": "KXCPIYOY-26JUL-T3.4", "net": 0.09}]}
        t = cw.predict_desk_verdict(bet, {"KXCPIYOY-26JUL-T3.4": {}}).plain
        self.assertIn("BET", t)
        cw.predict_desk_verdict(None, None)                 # thin input never raises

    def test_near_misses_capped_at_three_with_summary(self):
        nm = [{"kind": "ladder", "event_ticker": f"KXE-{i}", "gross": 0.0,
               "fees": 0.06, "net": -0.09} for i in range(6)]
        clean = {"available": True, "opportunities": [],
                 "thresholds": {"theta_struct": 0.01}, "near_misses": nm}
        t = cw.predict_desk_lane(clean, "L1").plain
        self.assertIn("KXE-2", t)
        self.assertNotIn("KXE-3", t)                        # rows 4-6 summarized, not rendered
        self.assertIn("…+3 more baskets, all short ≥ 10¢", t)

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

    def test_nav_strip_fits_the_surface_box(self):
        # The 7-tab strip must fit the srf_box's 150-col max-width minus its padding — a wider
        # strip silently clips the rightmost tabs off the edge (the original missing-PREDICT-tab
        # bug). Mirrors _blend_nav_markup's cell arithmetic exactly.
        total = sum(max(len(name) + 4, len(tag) + 4) + 3 for _, _, name, tag in cw.BLEND_NAV)
        self.assertLessEqual(total, 148, f"BLEND_NAV strip is {total} cols — tabs will clip")

    def test_predict_reachable_from_hub_jobnav(self):
        # The hub HOME renders the jobnav (not the surface strip) — the desk needs a drawer there
        self.assertIn("predict", [k for k, _ in cw.JOBNAV_DRAWERS])

    def test_desk_has_its_own_feedback_channel(self):
        # _toast writes to the main screen's what-if slot, which a modal desk fully covers — the
        # desk must own a flash line or a re-sweep looks like nothing happened (the r-key bug)
        import cockpit_surfaces as cs
        self.assertTrue(callable(getattr(cs.PredictSurface, "flash", None)))
        self.assertTrue(callable(getattr(cs.PredictSurface, "action_refresh_sweep", None)))


if __name__ == "__main__":
    unittest.main()
