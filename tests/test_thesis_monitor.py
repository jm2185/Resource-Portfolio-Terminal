"""Tests for thesis_monitor (action-plan P5.1) — per-name thesis-variable monitors."""
import unittest

import thesis_monitor as tm


class FrameworkTests(unittest.TestCase):
    def test_each_slot_has_variables_with_a_hard_breaker(self):
        for slot, vars_ in tm.THESIS_VARIABLES.items():
            self.assertTrue(vars_, slot)
            self.assertTrue(any(v.get("hard") for v in vars_), f"{slot} needs a thesis-breaker")

    def test_assess_lists_the_framework_even_without_reads(self):
        r = tm.assess({"ticker": "AGA.V", "slot": "silver-spear"})
        ids = {v["id"] for v in r["variables"]}
        self.assertIn("catalyst_delivery", ids)
        self.assertIn("floor_coverage", ids)
        self.assertEqual(r["thesis_health"], "WATCH")   # all-unknown is not healthy


class StatusResolutionTests(unittest.TestCase):
    def test_explicit_status_strings(self):
        r = tm.assess({"ticker": "GROY", "slot": "gold-royalty-ballast"},
                      {"gold_price": "on_track", "royalty_cash_flow": "on_track",
                       "counterparty_production": "on_track", "nav_per_share": "on_track"})
        self.assertEqual(r["thesis_health"], "ON-TRACK")

    def test_value_vs_min_threshold(self):
        ok = tm.assess({"ticker": "AGA.V", "slot": "silver-spear"},
                       {"floor_coverage": {"value": 1.4, "min": 1.0}})
        bad = tm.assess({"ticker": "AGA.V", "slot": "silver-spear"},
                        {"floor_coverage": {"value": 0.8, "min": 1.0}})
        fc_ok = next(v for v in ok["variables"] if v["id"] == "floor_coverage")
        fc_bad = next(v for v in bad["variables"] if v["id"] == "floor_coverage")
        self.assertEqual(fc_ok["status"], "on_track")
        self.assertEqual(fc_bad["status"], "off_track")

    def test_value_vs_prior_trend_respects_good_direction(self):
        # gold_price good=up: rising is healthy
        up = tm.assess({"ticker": "GROY", "slot": "gold-royalty-ballast"},
                       {"gold_price": {"value": 2400, "prior": 2300}})
        down = tm.assess({"ticker": "GROY", "slot": "gold-royalty-ballast"},
                         {"gold_price": {"value": 2200, "prior": 2300}})
        gp_up = next(v for v in up["variables"] if v["id"] == "gold_price")
        gp_down = next(v for v in down["variables"] if v["id"] == "gold_price")
        self.assertEqual(gp_up["status"], "on_track")
        self.assertEqual(gp_down["status"], "off_track")

    def test_nav_discount_narrowing_is_good(self):
        # nav_discount good=narrowing -> a falling value is healthy
        r = tm.assess({"ticker": "GMX.TO", "slot": "project-generator-holdco"},
                      {"nav_discount": {"value": 0.25, "prior": 0.35}})
        nd = next(v for v in r["variables"] if v["id"] == "nav_discount")
        self.assertEqual(nd["status"], "on_track")


class RollupTests(unittest.TestCase):
    def test_hard_off_track_makes_thesis_off_track(self):
        r = tm.assess({"ticker": "URC.TO", "slot": "electrification-royalty"},
                      {"uranium_term_price": "off_track", "royalty_cash_flow": "on_track",
                       "electrification_demand": "on_track", "vehicle_structure": "on_track"})
        self.assertEqual(r["thesis_health"], "OFF-TRACK")
        self.assertIn("uranium_term_price", r["off_track"])

    def test_soft_off_track_is_only_watch(self):
        r = tm.assess({"ticker": "GROY", "slot": "gold-royalty-ballast"},
                      {"gold_price": "off_track", "royalty_cash_flow": "on_track",
                       "counterparty_production": "on_track", "nav_per_share": "on_track"})
        self.assertEqual(r["thesis_health"], "WATCH")   # gold_price is soft, not a breaker

    def test_hard_unknown_is_watch_not_on_track(self):
        # vehicle_structure (hard) unknown -> WATCH even if everything else is on-track.
        r = tm.assess({"ticker": "URC.TO", "slot": "electrification-royalty"},
                      {"uranium_term_price": "on_track", "royalty_cash_flow": "on_track",
                       "electrification_demand": "on_track"})
        self.assertEqual(r["thesis_health"], "WATCH")
        self.assertIn("vehicle_structure", r["unknown"])


class StructureTests(unittest.TestCase):
    def test_glossary_and_unknown_slot(self):
        r = tm.assess({"ticker": "ZZZ", "slot": "mystery"})
        self.assertEqual(r["thesis_health"], "UNKNOWN")
        self.assertEqual(r["variables"], [])
        self.assertIn("thesis_monitor", r["glossary"])

    def test_empty_holding_graceful(self):
        r = tm.assess(None)
        self.assertEqual(r["thesis_health"], "UNKNOWN")

    def test_tooltip_unknown_key_empty(self):
        self.assertEqual(tm.thesis_tooltip("nope"), "")


if __name__ == "__main__":
    unittest.main()
