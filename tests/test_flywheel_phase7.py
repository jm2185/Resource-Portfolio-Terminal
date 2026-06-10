"""Phase 7 — the scout scorecard (hit-rate-as-funnel-objective, regret, graduation edge), the
new memory entry types, the peer-comp audit extensions (Phase 5), and the story-card spread."""
from __future__ import annotations

import unittest

import calibration
import living_memory
import peer_normalization as pn
import valuation_actions as va


class EntryTypeTests(unittest.TestCase):
    def test_new_types_registered(self):
        self.assertIn("scout_candidate", living_memory.ENTRY_TYPES)
        self.assertIn("graduation", living_memory.ENTRY_TYPES)


class ScoutScorecardTests(unittest.TestCase):
    ROWS = [
        {"ticker": "A.V", "archetype": "option_convexity", "slot": "silver-spear",
         "graduated": True, "realized_return": 0.80},
        {"ticker": "B.V", "archetype": "option_convexity", "slot": "silver-spear",
         "graduated": True, "realized_return": -0.20},
        {"ticker": "C.V", "archetype": "option_convexity", "slot": "silver-spear",
         "graduated": False, "realized_return": 0.50},   # the regret case
        {"ticker": "D.V", "archetype": "asset_light_yield", "slot": "gold-royalty-ballast",
         "graduated": False, "realized_return": -0.10},
    ]

    def test_buckets_and_hit_rate_headline(self):
        sc = calibration.scout_scorecard(self.ROWS)
        self.assertEqual(sc["n"], 4)
        self.assertEqual(sc["all"]["hit_rate"], 0.5)       # 0.80 and 0.50 clear the 0.30 bar
        self.assertIn("hit-rate", sc["headline"])
        self.assertIn("by_archetype", sc)
        self.assertIn("by_slot", sc)

    def test_regret_names_the_killed_winner(self):
        sc = calibration.scout_scorecard(self.ROWS)
        self.assertEqual(sc["regret"]["n"], 1)
        self.assertEqual(sc["regret"]["tickers"], ["C.V"])

    def test_graduation_edge_and_inversion_warning(self):
        sc = calibration.scout_scorecard(self.ROWS)
        # graduates avg 0.30, kills avg 0.20 -> positive edge, no warning
        self.assertAlmostEqual(sc["graduation_edge"], 0.10, places=4)
        self.assertNotIn("warning", sc)
        inverted = [dict(r, graduated=not r["graduated"]) for r in self.ROWS]
        sc2 = calibration.scout_scorecard(inverted)
        self.assertIn("warning", sc2)                      # kills outperform -> the gate is wrong

    def test_objective_inversion_is_named_not_silent(self):
        sc = calibration.scout_scorecard(self.ROWS)
        self.assertIn("BY DESIGN", sc["note"])             # funnel hit-rate ≠ book objective
        self.assertIn("expectancy", sc["note"])

    def test_empty_watch(self):
        self.assertEqual(calibration.scout_scorecard([])["n"], 0)


class PeerAuditTests(unittest.TestCase):
    PEERS = [
        {"ticker": "P1", "ev_oz": 1.0, "stage": "pea"},
        {"ticker": "P2", "ev_oz": 1.1, "stage": "pea"},
        {"ticker": "P3", "ev_oz": 0.9, "stage": "pea"},
        {"ticker": "P4", "ev_oz": 1.05, "stage": "pea"},
    ]

    def test_outlier_flagged_and_downweighted_never_dropped(self):
        peers = self.PEERS + [{"ticker": "WILD", "ev_oz": 30.0, "stage": "pea"}]
        res = pn.blended_peer_ev_oz(peers, "pea")
        self.assertTrue(res["outliers"])
        self.assertEqual(res["outliers"][0]["ticker"], "WILD")
        self.assertIn("WILD", res["peers"])                # visible, not silently dropped
        self.assertTrue(res["peers"]["WILD"]["outlier"])
        self.assertAlmostEqual(res["peers"]["WILD"]["weight"], pn.OUTLIER_DOWNWEIGHT, places=4)
        clean = pn.blended_peer_ev_oz(self.PEERS, "pea")["blended_ev_oz"]
        self.assertLess(abs(res["blended_ev_oz"] - clean), 30.0 / 5 - clean)  # influence capped

    def test_no_outlier_logic_below_min_n(self):
        peers = self.PEERS[:2] + [{"ticker": "WILD", "ev_oz": 30.0, "stage": "pea"}]
        res = pn.blended_peer_ev_oz(peers, "pea")
        self.assertNotIn("outliers", res)                  # 3 peers: no robust center to deviate from

    def test_dispersion_and_leave_one_out(self):
        res = pn.blended_peer_ev_oz(self.PEERS, "pea")
        self.assertIn("dispersion", res)
        self.assertGreater(res["dispersion"]["rel_dispersion"], 0)
        self.assertIn("sensitivity", res)
        self.assertIn(res["max_swing_peer"], res["sensitivity"])

    def test_comp_audit_over_engine_details(self):
        details = {"P1": {"adjusted_ev_oz": 1.0, "weight_used": 0.5},
                   "P2": {"adjusted_ev_oz": 2.0, "weight_used": 0.5}}
        audit = pn.comp_audit(details)
        self.assertEqual(audit["n_peers"], 2)
        self.assertGreater(audit["rel_dispersion"], 0)
        self.assertIn(audit["max_swing_peer"], ("P1", "P2"))
        self.assertIsNone(pn.comp_audit({"P1": {"adjusted_ev_oz": 1.0, "weight_used": 1.0}}))


class StoryCardSpreadTests(unittest.TestCase):
    SUMMARY = {"intrinsic_after_forensic": 1.71,
               "legs": {"cost": 1.0, "market": 2.0},
               "weights": {"cost": 0.3, "market": 0.7},
               "component_breakdown": {"cost": {"method": "REP"}, "market": {"method": "EV/oz"}}}

    def test_method_spread_on_card_and_render(self):
        card = va.story_card(self.SUMMARY, price=0.61, ticker="AGA.V")
        ms = card["method_spread"]
        self.assertEqual(ms["n_methods"], 2)
        self.assertIsNotNone(ms["spread_pct"])
        self.assertIn("methods spread", va.render_story_card(card))


if __name__ == "__main__":
    unittest.main()
