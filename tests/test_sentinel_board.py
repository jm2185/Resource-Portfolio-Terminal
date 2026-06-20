"""Tests for sentinel_board (action-plan P2.3) — the consolidated SENTINEL monitor surface."""
import unittest

import sentinel_board as sb
import rates_monitor
import productivity_monitor
import oil_supply_monitor


CUR = {"dgs2": 3.90, "dgs5": 4.10, "dgs10": 4.55, "dgs30": 4.95, "fedfunds": 4.33}
MACRO_TAPE = {
    "net_tilt": "RISK-ON",
    "signals": [
        {"key": "gsr", "label": "Gold/Silver", "value": 72.0, "read": "Silver leadership", "bias": "risk_on"},
        {"key": "real_yield", "label": "Real Yield", "value": 0.3, "read": "Tailwind for metals", "bias": "risk_on"},
        {"key": "dxy", "label": "DXY", "value": 99.0, "read": "Weak dollar", "bias": "risk_on"},
        {"key": "cu_au", "label": "Copper/Gold ×1k", "value": 1.6, "read": "Growth/reflation bid", "bias": "risk_on"},
        {"key": "cftc", "label": "CFTC Net %ile", "value": 30.0, "read": "Mid-range", "bias": "neutral"},
    ],
}


class ConsolidationTests(unittest.TestCase):
    def test_all_monitors_become_cards(self):
        board = sb.build(
            rates=rates_monitor.assess(CUR),
            productivity=productivity_monitor.assess([1.5, 1.6], breadth=0.4),
            oil=oil_supply_monitor.assess(wti=70.0, front=66.0, deferred=69.0),
            macro_tape=MACRO_TAPE,
            usdcad=sb.usdcad_carry(4.33, 2.75),
        )
        ids = {c["id"] for c in board["monitors"]}
        for expected in ("rates", "productivity", "oil_supply", "silver_positioning",
                         "copper", "macro_regime", "usdcad_carry"):
            self.assertIn(expected, ids, expected)
        # every card carries the uniform shape
        for c in board["monitors"]:
            for k in ("id", "label", "read", "value", "flag", "feeds_scenario"):
                self.assertIn(k, c)

    def test_active_flags_bubble_up_with_monitor_id(self):
        rates = rates_monitor.assess(CUR, prior={**CUR, "dgs30": CUR["dgs30"] - 0.35})  # bear-steepener
        oil = oil_supply_monitor.assess(wti=92.0, ovx=55.0, front=85.0, deferred=83.0)   # elevated
        board = sb.build(rates=rates, oil=oil)
        flag_monitors = {f["monitor"] for f in board["flags"]}
        self.assertIn("rates", flag_monitors)
        self.assertIn("oil_supply", flag_monitors)
        self.assertGreaterEqual(board["net_read"]["active_flags"], 2)

    def test_clean_board_has_no_flags(self):
        board = sb.build(rates=rates_monitor.assess(CUR), macro_tape=MACRO_TAPE)
        self.assertEqual(board["flags"], [])
        self.assertIn("clean", board["net_read"]["summary"])

    def test_each_card_names_the_scenario_it_feeds(self):
        board = sb.build(productivity=productivity_monitor.assess([2.4, 2.8], breadth=0.8, breadth_prior=0.6))
        prod = next(c for c in board["monitors"] if c["id"] == "productivity")
        self.assertIn("C", prod["feeds_scenario"])

    def test_coverage_reports_missing_monitors_honestly(self):
        board = sb.build(rates=rates_monitor.assess(CUR))    # only one monitor wired
        self.assertIn("rates", board["coverage"]["present"])
        self.assertIn("uranium_term", board["coverage"]["missing"])
        self.assertIn("productivity", board["coverage"]["missing"])
        self.assertLess(board["net_read"]["coverage_pct"], 100)

    def test_uranium_term_card_with_invalidation_flag(self):
        ut = {"read": "term rolled over", "value": -0.2,
              "flag": {"id": "uranium_term_invalidation", "active": True, "level": "risk",
                       "text": "uranium term market rolling over"}}
        board = sb.build(uranium_term=ut)
        self.assertIn("uranium_term", board["coverage"]["present"])
        self.assertTrue(any(f["monitor"] == "uranium_term" for f in board["flags"]))


class UsdCadCarryTests(unittest.TestCase):
    def test_positive_carry_favours_usd(self):
        r = sb.usdcad_carry(4.33, 2.75)
        self.assertGreater(r["carry_pp"], 0)
        self.assertEqual(r["tilt"], "USD")

    def test_negative_carry_favours_cad(self):
        self.assertEqual(sb.usdcad_carry(2.5, 3.5)["tilt"], "CAD")

    def test_flat_carry_neutral(self):
        self.assertEqual(sb.usdcad_carry(4.0, 4.0)["tilt"], "NEUTRAL")

    def test_missing_rate_graceful(self):
        self.assertIsNone(sb.usdcad_carry(None, 2.75)["carry_pp"])


if __name__ == "__main__":
    unittest.main()
