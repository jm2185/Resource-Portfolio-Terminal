"""
Tests for the engine /state -> MatrixState adapter (matrix/adapter.py) — Forge-Matrix M0.

Pins the contract mapping against a realistic published-state fixture (the real key shapes from
engine.py): regime band from macro_tape + mri + posture, the stress complex with the engine bias ->
colour-state mapping, the watchlist in engine (conviction) order, change_pct as an explicit GAP (None,
never invented), the barbell split derived from live node market value, the injected-catalyst path, and
graceful degradation when the feed is empty/stale.
"""
import unittest

from matrix import build_matrix_state
from matrix.contract import CatalystRef, MatrixState

# A realistic slice of engine.published_state (the keys the adapter reads).
STATE = {
    "mri": 58.0,
    "macro_tape": {
        "net_tilt": "RISK-OFF",
        "signals": [
            {"key": "vix", "label": "VIX", "value": 25.4, "bias": "risk_off", "read": "Elevated fear"},
            {"key": "gsr", "label": "Gold/Silver", "value": 82.0, "bias": "neutral", "read": "Balanced"},
            {"key": "cu_au", "label": "Copper/Gold ×1k", "value": 1.7, "bias": "risk_on",
             "read": "Growth/reflation bid"},
        ],
    },
    "posture": {"code": "defensive", "label": "DEFENSIVE", "cap": 0.8},
    "nodes": {
        "AGA.V": {"price": 1.00, "role": "The Spear", "shares": 100000.0},
        "GROY": {"price": 2.00, "role": "Ballast", "shares": 30000.0},
    },
    "conviction_mode": {"baskets": [
        {"ticker": "AGA.V", "rating": 8, "directive": "ACCUMULATE", "ladder": {"price": 1.00},
         "pillars": {"V": {"rho": 3.2, "floor_coverage": 1.85}}},
        {"ticker": "GROY", "rating": 6, "directive": "HOLD", "ladder": {"price": 2.00},
         "pillars": {"V": {"rho": 1.4, "floor_coverage": 1.2}}},
    ]},
    "freshness": {"prices": {"stale": False}, "macro": {"stale": True}},
}


class RegimeBandTests(unittest.TestCase):
    def setUp(self):
        self.ms = build_matrix_state(STATE, now=1000.0)

    def test_raw_net_tilt_and_mri_carried(self):
        self.assertEqual(self.ms.net_tilt, "RISK-OFF")
        self.assertEqual(self.ms.mri, 58.0)                 # raw MRI carried, not bucketed away

    def test_regime_label_and_cap_from_posture(self):
        self.assertEqual(self.ms.regime_label, "DEFENSIVE")
        self.assertEqual(self.ms.posture_cap, 0.8)

    def test_generated_at_passthrough(self):
        self.assertEqual(self.ms.generated_at, 1000.0)


class StressComplexTests(unittest.TestCase):
    def setUp(self):
        self.ms = build_matrix_state(STATE)

    def test_bias_maps_to_colour_state(self):
        by_label = {s.label: s for s in self.ms.stress}
        self.assertEqual(by_label["VIX"].state, "stress")          # risk_off -> stress (red)
        self.assertEqual(by_label["Gold/Silver"].state, "elevated")  # neutral -> elevated (amber)
        self.assertEqual(by_label["Copper/Gold ×1k"].state, "calm")  # risk_on -> calm (green)

    def test_value_and_read_preserved(self):
        vix = self.ms.stress[0]
        self.assertEqual(vix.value, 25.4)
        self.assertEqual(vix.read, "Elevated fear")

    def test_order_preserved(self):
        self.assertEqual([s.label for s in self.ms.stress],
                         ["VIX", "Gold/Silver", "Copper/Gold ×1k"])


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.ms = build_matrix_state(STATE)

    def test_symbols_abbreviated_in_conviction_order(self):
        self.assertEqual([w.symbol for w in self.ms.watchlist], ["AGA", "GROY"])

    def test_last_price_from_nodes(self):
        self.assertEqual(self.ms.watchlist[0].last, 1.00)
        self.assertEqual(self.ms.watchlist[1].last, 2.00)

    def test_change_pct_none_when_not_provided(self):
        for w in self.ms.watchlist:
            self.assertIsNone(w.change_pct)                  # neither node field nor injection -> None

    def test_per_name_conviction_fields(self):
        aga, groy = self.ms.watchlist
        self.assertEqual((aga.rating, aga.directive), (8.0, "ACCUMULATE"))
        self.assertEqual((aga.rho, aga.floor_coverage), (3.2, 1.85))
        self.assertEqual((groy.rating, groy.directive), (6.0, "HOLD"))

    def test_last_falls_back_to_ladder_price(self):
        state = {"conviction_mode": {"baskets": [{"ticker": "XYZ.V", "ladder": {"price": 3.3}}]},
                 "nodes": {}}
        ms = build_matrix_state(state)
        self.assertEqual(ms.watchlist[0].symbol, "XYZ")
        self.assertEqual(ms.watchlist[0].last, 3.3)


class BarbellTests(unittest.TestCase):
    def test_split_from_live_market_value(self):
        ms = build_matrix_state(STATE)
        # spear MV = 1.00*100000 = 100000; ballast MV = 2.00*30000 = 60000; total 160000
        self.assertEqual(ms.spear_pct, 62.5)
        self.assertEqual(ms.ballast_pct, 37.5)

    def test_none_when_no_market_value(self):
        ms = build_matrix_state({"nodes": {"AGA.V": {"role": "The Spear"}}})
        self.assertIsNone(ms.spear_pct)
        self.assertIsNone(ms.ballast_pct)


class CatalystTests(unittest.TestCase):
    def test_none_when_not_injected(self):
        self.assertIsNone(build_matrix_state(STATE).next_catalyst)

    def test_maps_soonest_injected_catalyst(self):
        cats = [{"label": "AGA drill", "_days_to_start": 12}, {"label": "Later", "_days_to_start": 40}]
        ms = build_matrix_state(STATE, catalysts=cats)
        self.assertEqual(ms.next_catalyst, CatalystRef(label="AGA DRILL", days=12))

    def test_label_truncated_and_uppercased(self):
        cats = [{"title": "a very long catalyst label here", "days": 3}]
        ms = build_matrix_state(STATE, catalysts=cats)
        self.assertEqual(ms.next_catalyst.days, 3)
        self.assertEqual(ms.next_catalyst.label, "A VERY LONG CATA")   # 16 chars, upper


class ChangeTests(unittest.TestCase):
    def test_injected_changes_map(self):
        ms = build_matrix_state(STATE, changes={"AGA.V": 2.4, "GROY": -1.1})
        self.assertEqual(ms.watchlist[0].change_pct, 2.4)
        self.assertEqual(ms.watchlist[1].change_pct, -1.1)

    def test_node_change_field_wins_over_injection(self):
        state = dict(STATE)
        state["nodes"] = {"AGA.V": {"price": 1.0, "role": "The Spear", "shares": 1.0, "change_pct": 5.5}}
        ms = build_matrix_state(state, changes={"AGA.V": 1.1})
        self.assertEqual(ms.watchlist[0].change_pct, 5.5)


class MonitoredTests(unittest.TestCase):
    def test_injected_bench_names_are_eval_only(self):
        ms = build_matrix_state(STATE, monitored=[{"symbol": "ABRA.TO", "last": 2.1, "change_pct": 4.0},
                                                  {"symbol": "BRC.V", "price": 0.5}])
        mon = [w for w in ms.watchlist if w.eval_only]
        self.assertEqual([w.symbol for w in mon], ["ABRA", "BRC"])
        self.assertEqual((mon[0].last, mon[0].change_pct), (2.1, 4.0))
        self.assertEqual(mon[1].last, 0.5)                     # 'price' alias accepted
        self.assertTrue(all(not w.eval_only for w in ms.watchlist if w.symbol in ("AGA", "GROY")))


class DegradationTests(unittest.TestCase):
    def test_stale_flag_from_freshness(self):
        self.assertTrue(build_matrix_state(STATE).stale)             # macro feed stale

    def test_not_stale_when_all_fresh(self):
        state = dict(STATE, freshness={"prices": {"stale": False}, "macro": {"stale": False}})
        self.assertFalse(build_matrix_state(state).stale)

    def test_empty_state_is_safe_balanced_stale_frame(self):
        ms = build_matrix_state(None, now=5.0)
        self.assertIsInstance(ms, MatrixState)
        self.assertEqual(ms.net_tilt, "BALANCED")
        self.assertTrue(ms.stale)
        self.assertEqual(ms.watchlist, ())
        self.assertEqual(ms.generated_at, 5.0)


if __name__ == "__main__":
    unittest.main()
