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


class CandidateAnchorTests(unittest.TestCase):
    """D4 — the reference-class / outside-view prior a discovery candidate is scored against."""

    def test_spear_sleeve_resolves_to_discovery_base_rate(self):
        a = cal.candidate_anchor(sleeve="spear")
        self.assertEqual(a["archetype"], "option_convexity")
        self.assertEqual(a["base_rate"]["name"], "discovery_to_mine")
        self.assertAlmostEqual(a["base_rate"]["value"], 0.5, places=1)
        self.assertIn("reference class", a["line"].lower())

    def test_archetype_resolves_directly(self):
        self.assertEqual(cal.candidate_anchor("option_convexity")["archetype"], "option_convexity")

    def test_unmapped_returns_empty_not_invented(self):
        # honesty: no researched prior maps -> {} rather than a fabricated authority
        self.assertEqual(cal.candidate_anchor("mystery_archetype"), {})
        self.assertEqual(cal.candidate_anchor(sleeve="nonsense"), {})


def _qdec(price=1.0, floor=0.8, base=1.5, bull=2.5, rho=3.0, phi=1.2,
          archetype="option_convexity", verdict="BELOW FLOOR — ACCUMULATE"):
    """A frozen decision carrying the asymmetry shape (rho/phi) — the raw material the
    decision-quality axis grades, and the path layer compounds."""
    return {"ticker": "AGA.V", "verdict": verdict, "side": cal.infer_side(verdict), "price": price,
            "legs": {"floor": floor, "base": base, "bull": bull, "bear": 0.95},
            "rho": rho, "phi": phi, "archetype": archetype}


class PathRiskTests(unittest.TestCase):
    """Tier-1 #1 (Taleb / ergodicity): the scorecard must see the WEALTH PATH, not only the ensemble
    mean — a +ve arithmetic expectancy can sit on a book compounding toward ruin."""

    def test_positive_expectancy_can_hide_negative_geometric(self):
        seq = [cal.score_outcome(_qdec(), 2.5), cal.score_outcome(_qdec(), 2.5),
               cal.score_outcome(_qdec(), 0.10)]            # +150%, +150%, then -90%
        sc = cal.scorecard(seq)
        self.assertGreater(sc["expectancy_per_decision"], 0.0)          # arithmetic says 'great'
        self.assertLess(sc["path"]["geometric_return_per_decision"], 0.0)  # the path says 'down'
        self.assertLess(sc["path"]["ending_wealth_mult"], 1.0)         # you actually lost money
        self.assertIsNotNone(sc["path_warning"])
        self.assertIn("ergodicity", sc["path_warning"])

    def test_max_drawdown_tracks_the_sequence(self):
        seq = [cal.score_outcome(_qdec(), 2.0), cal.score_outcome(_qdec(), 0.5)]  # +100% then -50%
        sc = cal.scorecard(seq)
        self.assertAlmostEqual(sc["path"]["max_drawdown"], 0.5, places=3)   # 2.0 → 1.0 peak-to-trough

    def test_ruin_event_counted_on_halving_floor_break(self):
        sc = cal.scorecard([cal.score_outcome(_qdec(floor=0.8), 0.3)])      # -70%, below floor
        self.assertEqual(sc["path"]["ruin_events"], 1)

    def test_avoids_excluded_from_wealth_path(self):
        # a correct AVOID that fell is a process win, but you weren't holding — not on the wealth path
        sc = cal.scorecard([cal.score_outcome(_qdec(verdict="RICH — TRIM"), 0.5)])
        self.assertEqual(sc["path"], {})
        self.assertIsNone(sc["path_warning"])

    def test_no_warning_when_geometric_is_positive(self):
        sc = cal.scorecard([cal.score_outcome(_qdec(), 2.5), cal.score_outcome(_qdec(), 1.5)])
        self.assertIsNone(sc["path_warning"])


class DecisionQualityTests(unittest.TestCase):
    """Tier-1 #2 (Duke / anti-resulting): grade the FROZEN bet shape independently of the print, and
    separate process from luck."""

    def test_well_shaped_from_rho_and_phi(self):
        self.assertEqual(cal.score_outcome(_qdec(rho=3.0, phi=1.2), 1.0)["decision_quality"],
                         "well_shaped")

    def test_thin_when_rho_below_bar(self):
        self.assertEqual(cal.score_outcome(_qdec(rho=1.1, phi=1.2), 1.0)["decision_quality"], "thin")

    def test_unknown_without_frozen_shape(self):
        d = _qdec(); d.pop("rho"); d.pop("phi")
        self.assertEqual(cal.score_outcome(d, 1.0)["decision_quality"], "unknown")

    def test_implied_breakeven_from_payoff(self):
        self.assertAlmostEqual(cal.score_outcome(_qdec(rho=3.0), 1.0)["implied_breakeven_p"],
                               0.25, places=3)            # 1/(1+3)

    def test_grade_is_outcome_independent(self):
        win = cal.score_outcome(_qdec(rho=3.0), 2.5)
        loss = cal.score_outcome(_qdec(rho=3.0), 0.7)
        self.assertNotEqual(win["result"], loss["result"])             # the PRINT differs
        self.assertEqual(win["decision_quality"], loss["decision_quality"])  # the BET is the same

    def test_process_edge_separates_shape_from_luck(self):
        rows = [cal.score_outcome(_qdec(rho=3.0), 2.5),    # well-shaped win
                cal.score_outcome(_qdec(rho=3.0), 1.3),    # well-shaped win
                cal.score_outcome(_qdec(rho=1.1), 0.7)]    # thin loss
        sc = cal.scorecard(rows)
        self.assertEqual(sc["process"]["well_shaped_n"], 2)
        self.assertEqual(sc["process"]["thin_n"], 1)
        self.assertGreater(sc["process"]["process_edge"], 0.0)
        self.assertEqual(sc["process"]["calibration"]["n"], 3)


class ReliabilityTests(unittest.TestCase):
    """Tier-2 #5 (Tetlock): the headline must be honest about a thin sample — no frequentist interval
    off 2 points, and slugging flagged unreliable until the win/loss averages mean something."""

    def test_thin_sample_is_data_limited_with_no_frequentist_ci(self):
        sc = cal.scorecard([cal.score_outcome(_qdec(), 2.5), cal.score_outcome(_qdec(), 0.7)])
        rel = sc["reliability"]
        self.assertTrue(rel["data_limited"])
        self.assertIsNone(rel["expectancy_ci90"])         # refuse the false-precision interval
        self.assertIn("DATA-LIMITED", rel["note"])

    def test_warm_sample_gets_expectancy_interval(self):
        rows = [cal.score_outcome(_qdec(), p) for p in (2.5, 2.5, 1.3, 1.4, 0.7, 0.6)]  # 4 wins, 2 losses
        rel = cal.scorecard(rows)["reliability"]
        self.assertFalse(rel["data_limited"])
        self.assertIsNotNone(rel["expectancy_ci90"])
        self.assertTrue(rel["slugging_reliable"])

    def test_slugging_unreliable_with_too_few_losses(self):
        rows = [cal.score_outcome(_qdec(), p) for p in (2.5, 2.5, 1.3, 1.4, 0.7)]  # 4 wins, 1 loss, n=5
        rel = cal.scorecard(rows)["reliability"]
        self.assertFalse(rel["data_limited"])             # n≥5 overall
        self.assertFalse(rel["slugging_reliable"])        # but only 1 loss → ratio not yet trustworthy


if __name__ == "__main__":
    unittest.main(verbosity=2)
