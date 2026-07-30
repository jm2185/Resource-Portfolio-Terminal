"""predict_arb_monitor — the pure PREDICT-arb brain, tested off the engine.

Covers the three L1 axioms (parity / partition / ladder dominance) with hand-computed nets, the
fee + FX stack (the friction model is first-class — a marginal gross arb must DIE net of fees),
the L2 band-gated value edge + capped Kelly, book-walking, the settlement window, dedup
semantics, and graceful thin-input behavior. No network, no engine."""
from __future__ import annotations

import unittest

import predict_arb_monitor as pam

NO_FEES = {"predict_arb_monitor": {
    "fees": {"ws_commission_per_contract": 0.0, "clearing_fee_per_contract": 0.0,
             "kalshi_fee_applies": False, "fx_applies": False, "fx_spread_oneway": 0.0},
}}

import datetime as _dt
NOW = _dt.datetime(2026, 7, 21, 12, 0, tzinfo=_dt.timezone.utc).timestamp()  # deterministic window math
NEAR = "2026-08-15T12:00:00Z"  # ~25d after NOW — inside the default window
FAR = "2027-09-01T12:00:00Z"   # ~400d — outside the default 180d window


def mkt(ticker, *, yes_ask=None, no_ask=None, yes_bid=None, no_bid=None, strike=None,
        close=NEAR, sizes=(500.0, 500.0), event="EV-1", status="active"):
    return {"ticker": ticker, "event_ticker": event, "title": ticker, "yes_sub_title": ticker,
            "strike_type": "greater" if strike is not None else "", "floor_strike": strike,
            "cap_strike": None, "status": status, "close_time": close,
            "yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask,
            "yes_bid_size": sizes[0], "yes_ask_size": sizes[1],
            "last_price": None, "liquidity": None, "volume_24h": None, "open_interest": None}


def event(markets, *, ticker="EV-1", mut_ex=False, series="KXTEST"):
    return {"event_ticker": ticker, "series_ticker": series, "title": ticker,
            "category": "Economics", "mutually_exclusive": mut_ex, "markets": markets}


def snap(events, orderbooks=None):
    return {"ts": NOW, "series": ["KXTEST"], "events": events,
            "orderbooks": orderbooks or {}, "errors": []}


class TestFees(unittest.TestCase):
    def test_kalshi_fee_ceils_to_cent(self):
        # 0.07 * 0.5 * 0.5 = 0.0175 -> ceil to 0.02
        self.assertEqual(pam.kalshi_fee(0.5), 0.02)
        # 0.07 * 0.3 * 0.7 = 0.0147 -> 0.02 (ceil), and extremes are free
        self.assertEqual(pam.kalshi_fee(0.3), 0.02)
        self.assertEqual(pam.kalshi_fee(0.0), 0.0)
        self.assertEqual(pam.kalshi_fee(None), 0.0)

    def test_friction_stacks_commission_and_fee(self):
        f = pam.friction_per_contract(0.5)      # default: 0.02 WS + 0.02 kalshi
        self.assertAlmostEqual(f, 0.04, places=6)
        f0 = pam.friction_per_contract(0.5, NO_FEES)
        self.assertEqual(f0, 0.0)

    def test_kelly_capped(self):
        # raw Kelly (0.8-0.6)/(1-0.6) = 0.5 -> hard-capped
        self.assertEqual(pam.kelly_fraction(0.8, 0.6, cap=0.10), 0.10)
        self.assertEqual(pam.kelly_fraction(0.5, 0.6, cap=0.10), 0.0)   # negative edge floors at 0
        self.assertIsNone(pam.kelly_fraction(0.8, 1.2))


class TestWalkBook(unittest.TestCase):
    def test_walks_complementary_bids(self):
        # buying YES consumes NO bids at cost 1-p: 5 @ (1-0.55) + 5 @ (1-0.50) = 4.75 / 10
        w = pam.walk_book([(0.55, 5), (0.50, 10)], 10)
        self.assertAlmostEqual(w["avg_cost"], 0.475, places=4)
        self.assertFalse(w["exhausted"])

    def test_exhausted_book_flagged(self):
        w = pam.walk_book([(0.55, 3)], 10)
        self.assertTrue(w["exhausted"])
        self.assertIsNone(pam.walk_book([], 10))


class TestConstraintGraph(unittest.TestCase):
    def test_ladder_and_partition_classified(self):
        lad = event([mkt("L-3.0", yes_ask=0.6, no_ask=0.5, strike=3.0),
                     mkt("L-3.5", yes_ask=0.4, no_ask=0.7, strike=3.5)], ticker="LAD")
        part = event([mkt("P-A", yes_ask=0.5, no_ask=0.6, event="PAR"),
                      mkt("P-B", yes_ask=0.5, no_ask=0.6, event="PAR")], ticker="PAR", mut_ex=True)
        g = pam.build_constraint_graph([lad, part], now_ts=NOW)
        self.assertEqual(len(g["ladders"]), 1)
        self.assertEqual(len(g["partitions"]), 1)
        self.assertEqual([m["floor_strike"] for m in g["ladders"][0]["markets"]], [3.0, 3.5])

    def test_partition_needs_every_leg_quoted(self):
        part = event([mkt("P-A", yes_ask=0.5, no_ask=0.6),
                      mkt("P-B", yes_ask=None, no_ask=None)], ticker="PAR", mut_ex=True)
        g = pam.build_constraint_graph([part], now_ts=NOW)
        self.assertEqual(g["partitions"], [])

    def test_settlement_window_filters(self):
        far = event([mkt("F-1", yes_ask=0.5, no_ask=0.3, strike=1.0, close=FAR),
                     mkt("F-2", yes_ask=0.4, no_ask=0.4, strike=2.0, close=FAR)])
        g = pam.build_constraint_graph([far], now_ts=NOW)
        self.assertEqual(g["ladders"], [])
        self.assertEqual(g["counts"]["in_window"], 0)


class TestL1Structural(unittest.TestCase):
    def test_ladder_dominance_violation_priced(self):
        # bid(>3.5)=0.45 > ask(>3.0)=0.30 -> buy YES(>3.0)@0.30 + NO(>3.5)@0.55: gross 0.15
        lad = event([mkt("L-3.0", yes_ask=0.30, no_ask=0.75, strike=3.0),
                     mkt("L-3.5", yes_ask=0.60, no_ask=0.55, strike=3.5)], ticker="LAD")
        opps = pam.structural_opportunities(pam.build_constraint_graph([lad], now_ts=NOW),
                                            config=NO_FEES)
        ladder = [o for o in opps if o["kind"] == "ladder"]
        self.assertEqual(len(ladder), 1)
        self.assertAlmostEqual(ladder[0]["gross"], 0.15, places=4)
        self.assertAlmostEqual(ladder[0]["net"], 0.15, places=4)     # zero-fee config
        self.assertEqual(ladder[0]["strikes"], [3.0, 3.5])

    def test_fee_stack_nets_the_same_ladder(self):
        # default fees: 2 legs x (0.02 WS + 0.02 kalshi) = 0.08; FX 1.5%/way on cost 0.85 & payout 1
        lad = event([mkt("L-3.0", yes_ask=0.30, no_ask=0.75, strike=3.0),
                     mkt("L-3.5", yes_ask=0.60, no_ask=0.55, strike=3.5)], ticker="LAD")
        opps = pam.structural_opportunities(pam.build_constraint_graph([lad], now_ts=NOW))
        ladder = [o for o in opps if o["kind"] == "ladder"]
        self.assertEqual(len(ladder), 1)
        # net = 1*(0.985) - 0.85*(1.015) - 0.08 = 0.04225
        self.assertAlmostEqual(ladder[0]["net"], 0.0423, places=3)

    def test_marginal_gross_arb_dies_net_of_fees(self):
        # gross +3c: survives with zero fees, DIES under the default friction stack
        lad = event([mkt("L-3.0", yes_ask=0.42, no_ask=0.63, strike=3.0),
                     mkt("L-3.5", yes_ask=0.60, no_ask=0.55, strike=3.5)], ticker="LAD")
        g = pam.build_constraint_graph([lad], now_ts=NOW)
        self.assertTrue(any(o["kind"] == "ladder"
                            for o in pam.structural_opportunities(g, config=NO_FEES)))
        self.assertFalse(any(o["kind"] == "ladder"
                             for o in pam.structural_opportunities(g)))

    def test_partition_dutch_book_buy_all_yes(self):
        part = event([mkt("P-A", yes_ask=0.30, no_ask=0.75, event="PAR"),
                      mkt("P-B", yes_ask=0.30, no_ask=0.75, event="PAR"),
                      mkt("P-C", yes_ask=0.30, no_ask=0.75, event="PAR")],
                     ticker="PAR", mut_ex=True)
        opps = pam.structural_opportunities(pam.build_constraint_graph([part], now_ts=NOW),
                                            config=NO_FEES)
        py = [o for o in opps if o["kind"] == "partition_yes"]
        self.assertEqual(len(py), 1)
        self.assertAlmostEqual(py[0]["net"], 0.10, places=4)         # 1 - 0.90
        # buy-all-NO costs 2.25 for a payout of 2 -> not an opportunity
        self.assertFalse(any(o["kind"] == "partition_no" for o in opps))

    def test_parity_violation_on_a_rung(self):
        lad = event([mkt("L-3.0", yes_ask=0.40, no_ask=0.50, strike=3.0),
                     mkt("L-3.5", yes_ask=0.30, no_ask=0.72, strike=3.5)], ticker="LAD")
        opps = pam.structural_opportunities(pam.build_constraint_graph([lad], now_ts=NOW),
                                            config=NO_FEES)
        par = [o for o in opps if o["kind"] == "parity"]
        self.assertEqual(len(par), 1)                                 # 0.40+0.50 = 0.90 -> +0.10
        self.assertEqual(par[0]["legs"][0]["ticker"], "L-3.0")

    def test_consistent_book_is_clean(self):
        lad = event([mkt("L-3.0", yes_ask=0.62, no_ask=0.40, strike=3.0),
                     mkt("L-3.5", yes_ask=0.42, no_ask=0.60, strike=3.5)], ticker="LAD")
        opps = pam.structural_opportunities(pam.build_constraint_graph([lad], now_ts=NOW),
                                            config=NO_FEES)
        self.assertEqual(opps, [])


class TestL2Value(unittest.TestCase):
    def test_edge_flags_and_kelly_caps(self):
        ev = event([mkt("V-1", yes_ask=0.60, no_ask=0.42)])
        fv = {"V-1": {"p_hat": 0.80, "band": [0.75, 0.85], "source": "ois"}}
        out = pam.value_edges([ev], fv, now_ts=NOW, config=NO_FEES)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["side"], "yes")
        self.assertAlmostEqual(out[0]["net"], 0.20, places=4)
        self.assertEqual(out[0]["kelly"], 0.10)                       # 0.5 raw, capped

    def test_price_inside_band_stays_silent(self):
        ev = event([mkt("V-1", yes_ask=0.60, no_ask=0.42)])
        fv = {"V-1": {"p_hat": 0.80, "band": [0.55, 0.85], "source": "ois"}}
        self.assertEqual(pam.value_edges([ev], fv, now_ts=NOW, config=NO_FEES), [])

    def test_no_side_when_model_below_market(self):
        ev = event([mkt("V-1", yes_ask=0.60, no_bid=0.38, no_ask=0.42)])
        fv = {"V-1": {"p_hat": 0.20, "band": [0.1, 0.3], "source": "options"}}
        out = pam.value_edges([ev], fv, now_ts=NOW, config=NO_FEES)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["side"], "no")                        # win prob 0.8 vs cost 0.42
        self.assertAlmostEqual(out[0]["net"], 0.38, places=4)

    def test_no_fair_values_no_signals(self):
        ev = event([mkt("V-1", yes_ask=0.60, no_ask=0.42)])
        self.assertEqual(pam.value_edges([ev], {}, now_ts=NOW, config=NO_FEES), [])


class TestAssessBook(unittest.TestCase):
    def test_thin_input_graceful(self):
        for empty in (None, {}, {"events": []}):
            dash = pam.assess_book(empty)
            self.assertFalse(dash["available"])
            self.assertEqual(dash["opportunities"], [])

    def test_full_sweep_ranks_and_flags(self):
        lad = event([mkt("L-3.0", yes_ask=0.30, no_ask=0.75, strike=3.0),
                     mkt("L-3.5", yes_ask=0.60, no_ask=0.55, strike=3.5)], ticker="LAD")
        ev = event([mkt("V-1", yes_ask=0.60, no_ask=0.42)], ticker="VAL")
        fv = {"V-1": {"p_hat": 0.80, "band": [0.75, 0.85], "source": "ois"}}
        dash = pam.assess_book(snap([lad, ev]), fair_values=fv, config=NO_FEES)
        self.assertTrue(dash["available"])
        lanes = [o["lane"] for o in dash["opportunities"]]
        self.assertIn("L1", lanes)
        self.assertIn("L2", lanes)
        self.assertEqual(dash["opportunities"][0]["net"],
                         max(o["net"] for o in dash["opportunities"]))
        levels = {f["lane"]: f["level"] for f in dash["flags"]}
        self.assertEqual(levels["L1"], "good")
        self.assertEqual(levels["L2"], "info")

    def test_depth_validation_kills_thin_books(self):
        lad = event([mkt("L-3.0", yes_ask=0.30, no_ask=0.75, strike=3.0),
                     mkt("L-3.5", yes_ask=0.60, no_ask=0.55, strike=3.5)], ticker="LAD")
        # real books too thin for min_size on one leg -> the basket is dropped
        books = {"L-3.0": {"yes": [(0.28, 500)], "no": [(0.68, 2)]},
                 "L-3.5": {"yes": [(0.44, 500)], "no": [(0.44, 500)]}}
        dash = pam.assess_book(snap([lad], books), config=NO_FEES)
        self.assertFalse(any(o["kind"] == "ladder" for o in dash["opportunities"]))

    def test_candidate_tickers_stage_one(self):
        lad = event([mkt("L-3.0", yes_ask=0.30, no_ask=0.75, strike=3.0),
                     mkt("L-3.5", yes_ask=0.60, no_ask=0.55, strike=3.5)], ticker="LAD")
        tks = pam.candidate_orderbook_tickers(snap([lad]), config=NO_FEES)
        self.assertEqual(set(tks), {"L-3.0", "L-3.5"})
        clean = event([mkt("C-1", yes_ask=0.62, no_ask=0.40, strike=3.0),
                       mkt("C-2", yes_ask=0.42, no_ask=0.60, strike=3.5)], ticker="CLN")
        self.assertEqual(pam.candidate_orderbook_tickers(snap([clean]), config=NO_FEES), [])


class TestSelectFresh(unittest.TestCase):
    def test_once_per_day_refire_on_widening(self):
        flag = {"id": "ladder:LAD:a|b", "net": 0.04, "level": "good", "text": "x"}
        fresh, fired = pam.select_fresh([flag], {}, today="2026-07-29")
        self.assertEqual(len(fresh), 1)
        # unchanged net, same day -> deduped
        fresh2, fired2 = pam.select_fresh([flag], fired, today="2026-07-29")
        self.assertEqual(fresh2, [])
        # net widens by >= 1c -> a NEW event, re-fires
        wider = dict(flag, net=0.06)
        fresh3, _ = pam.select_fresh([wider], fired2, today="2026-07-29")
        self.assertEqual(len(fresh3), 1)
        # next day re-fires by design
        fresh4, _ = pam.select_fresh([flag], fired2, today="2026-07-30")
        self.assertEqual(len(fresh4), 1)


class TestGlossary(unittest.TestCase):
    def test_tooltip_renders(self):
        self.assertIn("PREDICT arb SENTINEL", pam.predict_arb_tooltip("predict_arb"))
        self.assertEqual(pam.predict_arb_tooltip("nope"), "")


if __name__ == "__main__":
    unittest.main()
