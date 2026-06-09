"""
Tests for calibration (calibration.py).

Pins the Druckenmiller objective: the scorecard leads with expectancy / slugging / upside-capture /
downside-containment, hit-rate is demoted to secondary, a correct AVOID that falls is a process win,
and upside-capture catches under-betting a good call.
"""
import os
import sys
import tempfile
import unittest

import calibration as cal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))


def _dec(price=1.00, floor=0.80, base=1.50, bull=2.50, verdict="BELOW FLOOR — ACCUMULATE",
         archetype="option_convexity", ticker="AGA.V"):
    return {"ticker": ticker, "verdict": verdict, "side": cal.infer_side(verdict),
            "price": price, "legs": {"floor": floor, "base": base, "bull": bull, "bear": 0.95},
            "archetype": archetype}


class ScoreOutcomeTests(unittest.TestCase):
    def test_bull_leg_hit_is_a_win_with_capture(self):
        s = cal.score_outcome(_dec(), 2.50, horizon_days=90)     # reached the bull leg exactly
        self.assertEqual(s["result"], "win")
        self.assertEqual(s["leg_hit"], "bull")
        self.assertTrue(s["floor_held"])
        self.assertAlmostEqual(s["upside_capture"], 1.0, places=2)   # full capture of the projected bull

    def test_under_betting_a_good_call_shows_low_capture(self):
        s = cal.score_outcome(_dec(), 1.30)                      # up, but well short of the 2.50 bull
        self.assertEqual(s["result"], "win")
        self.assertLess(s["upside_capture"], 0.30)               # you under-rode the winner

    def test_broke_floor_is_a_loss(self):
        s = cal.score_outcome(_dec(), 0.60)
        self.assertEqual(s["result"], "loss")
        self.assertEqual(s["leg_hit"], "broke_floor")
        self.assertFalse(s["floor_held"])

    def test_correct_avoid_that_falls_is_a_process_win(self):
        s = cal.score_outcome(_dec(verdict="RICH — TRIM"), 0.70)  # we passed; it fell -> good call
        self.assertEqual(s["side"], "avoid")
        self.assertEqual(s["result"], "win")

    def test_scratch_near_flat(self):
        self.assertEqual(cal.score_outcome(_dec(), 1.01)["result"], "scratch")

    def test_unscored_when_missing_price(self):
        self.assertEqual(cal.score_outcome({"legs": {}}, 1.0)["status"], "unscored")


class ScorecardTests(unittest.TestCase):
    def _mix(self):
        return [
            cal.score_outcome(_dec(), 2.50),                     # big win (+150%)
            cal.score_outcome(_dec(), 1.30),                     # small win (+30%)
            cal.score_outcome(_dec(), 0.70),                     # loss (-30%)
            cal.score_outcome(_dec(archetype="asset_light_yield",
                                   verdict="QUALITY — CORE HOLD"), 1.10),  # royalty small win
        ]

    def test_headline_is_expectancy_and_slugging_not_hitrate(self):
        sc = cal.scorecard(self._mix())
        # the objective metrics are top-level; hit-rate is buried under 'secondary'
        self.assertIn("expectancy_per_decision", sc)
        self.assertIn("slugging_ratio", sc)
        self.assertIn("upside_capture", sc)
        self.assertIn("downside_containment", sc)
        self.assertNotIn("hit_rate", sc)                         # demoted
        self.assertIn("hit_rate", sc["secondary"])

    def test_slugging_rewards_big_winners(self):
        sc = cal.scorecard(self._mix())
        # avg win (≈ (1.50+0.30+0.10)/3) clearly exceeds avg loss (0.30) -> slugging > 1
        self.assertGreater(sc["slugging_ratio"], 1.0)
        self.assertGreater(sc["expectancy_per_decision"], 0.0)

    def test_per_archetype_split(self):
        sc = cal.scorecard(self._mix(), by_archetype=True)
        self.assertIn("option_convexity", sc["by_archetype"])
        self.assertIn("asset_light_yield", sc["by_archetype"])

    def test_empty_is_graceful(self):
        self.assertEqual(cal.scorecard([])["n"], 0)


class FreezeTests(unittest.TestCase):
    def test_decision_from_rating_captures_legs_and_asymmetry(self):
        basket = {
            "ticker": "AGA.V", "archetype": "option_convexity",
            "directive": "BELOW FLOOR — ACCUMULATE",
            "asymmetry": {"rho": 3.1, "floor_coverage": 1.28},
            "gate": {"cap": 4.5},
            "ladder": {"floor": 0.58, "bear": 0.61, "base": 1.05, "bull": 1.47, "price": 0.61},
        }
        d = cal.decision_from_rating(basket)
        self.assertEqual(d["side"], "long")
        self.assertEqual(d["price"], 0.61)
        self.assertEqual(d["legs"]["bull"], 1.47)
        self.assertEqual(d["rho"], 3.1)
        self.assertEqual(d["phi"], 1.28)
        self.assertEqual(d["archetype"], "option_convexity")


class MCPGlueTests(unittest.TestCase):
    """The decision -> outcome -> scorecard loop through Living Memory, via the MCP core functions.
    Points core.MEMORY_PATH at a temp store so the versioned track record is never touched."""

    def setUp(self):
        import core
        self.core = core
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._orig = core.MEMORY_PATH
        core.MEMORY_PATH = self.tmp

    def tearDown(self):
        self.core.MEMORY_PATH = self._orig
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_outcome_and_scorecard_round_trip(self):
        mem = self.core._living_memory()
        dec = {"ticker": "AGA.V", "verdict": "BELOW FLOOR — ACCUMULATE", "side": "long",
               "price": 1.0, "legs": {"floor": 0.8, "base": 1.5, "bull": 2.5, "bear": 0.95},
               "archetype": "option_convexity"}
        mem.write("decision", text="frozen", ticker="AGA.V", meta=dec)
        out = self.core.record_outcome("AGA.V", 2.5, horizon_days=90)
        self.assertTrue(out["ok"])
        self.assertEqual(out["scored"]["result"], "win")
        self.assertEqual(out["scored"]["leg_hit"], "bull")
        sc = self.core.calibration_scorecard()
        self.assertTrue(sc["ok"])
        self.assertEqual(sc["closed"], 1)
        self.assertGreater(sc["scorecard"]["expectancy_per_decision"], 0.0)

    def test_outcome_without_decision_is_graceful(self):
        out = self.core.record_outcome("GROY", 5.0)
        self.assertFalse(out["ok"])
        self.assertIn("no frozen decision", out["error"])


class BriefPriorTests(unittest.TestCase):
    """The flywheel's read side — the compact per-archetype prior injected into agent briefs (H3)."""

    def test_cold_start_surfaces_base_rate_with_no_outcomes(self):
        # zero closed decisions, but the spear's archetype still gets its published base rate (value
        # from day one) — honest cold start, never a bare %.
        bp = cal.brief_prior(cal.priored_scorecard([], archetypes=["option_convexity"]),
                             ["option_convexity"])
        row = bp["archetypes"]["option_convexity"]
        self.assertTrue(row["cold"])
        self.assertEqual(row["n"], 0)
        self.assertIsNone(row["expectancy"])
        self.assertEqual(row["base_rate"]["name"], "discovery_to_mine")
        self.assertAlmostEqual(row["base_rate"]["value"], 0.5, places=1)

    def test_warm_sample_surfaces_expectancy(self):
        scored = [cal.score_outcome(_dec(archetype="option_convexity"), 2.50),
                  cal.score_outcome(_dec(archetype="option_convexity"), 1.30)]
        bp = cal.brief_prior(cal.priored_scorecard(scored, archetypes=["option_convexity"]),
                             ["option_convexity"])
        row = bp["archetypes"]["option_convexity"]
        self.assertEqual(row["n"], 2)
        self.assertIsNotNone(row["expectancy"])
        self.assertIn("base_rate", row)               # base rate still attached while sample is thin

    def test_empty_when_nothing_useful(self):
        self.assertEqual(cal.brief_prior({}), {})
        # an archetype with no outcomes AND no mapped base rate yields no row
        self.assertEqual(cal.brief_prior({"by_archetype": {}, "base_rates": {}},
                                         ["totally_unmapped_archetype"]), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
