"""
Tests for the Dialectic Council reconciler (council.py).

Pins the signal-coherence rules as executable guarantees: the engine directive is the dominant
prior, grounded claims outweigh narrative, the Bear sets invalidation but never vetoes the convex
spear on narrative alone, a severe forensic gate caps the Bull, one verdict with dissent as a caveat,
and regime posture composes onto the action rather than competing with it.
"""
import unittest

import council
from council import Claim, reconcile


def _facts(**over):
    f = {
        "ticker": "AGA.V", "archetype": "option_convexity",
        "directive": "BELOW FLOOR — ACCUMULATE · watch closely",
        "asymmetry": {"rho": 3.1, "floor_coverage": 1.28, "upside_pct": 141.0},
        "gate": {"applied": False, "cap": 4.5, "reason": "clear"},
        "ladder": {"floor": 0.58, "price": 0.61, "bull": 1.47},
    }
    f.update(over)
    return f


class PriorAndBlendTests(unittest.TestCase):
    def test_engine_directive_is_the_dominant_prior(self):
        # no claims -> verdict tracks the engine's own directive
        v = reconcile(_facts(), [], [])
        self.assertGreater(v["convergence"]["bull"], 60)
        self.assertEqual(v["stance"], "RE-AFFIRM")

    def test_grounded_claims_move_more_than_narrative(self):
        narrative_bear = reconcile(_facts(), [], [Claim("bear", "feels toppy", grounded=False)])
        grounded_bear = reconcile(_facts(), [], [Claim("bear", "φ only 1.02 at base", grounded=True,
                                                       field="floor_coverage")])
        self.assertLess(grounded_bear["convergence"]["bull"], narrative_bear["convergence"]["bull"])

    def test_bull_claims_push_bull_share_up(self):
        base = reconcile(_facts(), [], [])
        bull = reconcile(_facts(), [Claim("bull", "ρ 3.1, convex", grounded=True, field="rho"),
                                    Claim("bull", "drill optionality", grounded=False)], [])
        self.assertGreaterEqual(bull["convergence"]["bull"], base["convergence"]["bull"])


class GuardrailTests(unittest.TestCase):
    def test_bear_cannot_narrative_veto_the_spear(self):
        # a pile of NARRATIVE bear claims on the convex spear cannot force EXIT
        bears = [Claim("bear", f"worry {i}", grounded=False, weight=2.0) for i in range(6)]
        v = reconcile(_facts(directive="UPSIDE SPENT — HOLD / TRIM"), [], bears)
        self.assertNotEqual(v["stance"], "EXIT / DE-RISK")
        self.assertIn("bear_no_narrative_veto_on_spear", v["guardrails_applied"])

    def test_engine_break_DOES_let_the_bear_win(self):
        # but a GROUNDED engine break (φ collapsed) is allowed to drive de-risk
        v = reconcile(
            _facts(asymmetry={"rho": 0.3, "floor_coverage": 0.7, "upside_pct": 5.0},
                   directive="UPSIDE SPENT — HOLD / TRIM"),
            [], [Claim("bear", "φ 0.7 — floor broke", grounded=True, field="floor_coverage", weight=3.0)])
        self.assertTrue(v["engine_break"])
        self.assertIn(v["stance"], ("TRIM", "EXIT / DE-RISK"))

    def test_severe_forensic_gate_caps_the_bull(self):
        v = reconcile(
            _facts(gate={"applied": True, "cap": 4.0, "reason": "JSF burn"},
                   directive="FORENSIC DECAY — AVOID / DE-RISK"),
            [Claim("bull", "huge upside", grounded=True, field="upside_pct", weight=5.0)], [])
        self.assertIn("forensic_gate_caps_bull", v["guardrails_applied"])
        self.assertLessEqual(v["convergence"]["bull"], 30)
        self.assertIn(v["stance"], ("TRIM", "EXIT / DE-RISK"))

    def test_zero_cap_is_the_most_severe_gate_not_no_gate(self):
        # falsy-zero regression: cap=0.0 (a FULL forensic block) used to fall through `or 10.0`
        # and read as "no gate" — leaving the Bull uncapped at the engine's loudest warning.
        v = reconcile(
            _facts(gate={"applied": True, "cap": 0.0, "reason": "JSF full block"},
                   directive="FORENSIC DECAY — AVOID / DE-RISK"),
            [Claim("bull", "huge upside", grounded=True, field="upside_pct", weight=5.0)], [])
        self.assertIn("forensic_gate_caps_bull", v["guardrails_applied"])
        self.assertLessEqual(v["convergence"]["bull"], 30)
        self.assertTrue(v["engine_break"])

    def test_royalty_bear_is_not_veto_protected(self):
        # the no-veto shield is spear-only; a royalty can be de-risked by the bear
        bears = [Claim("bear", f"accretion weak {i}", grounded=False, weight=2.0) for i in range(8)]
        v = reconcile(_facts(ticker="GROY", archetype="asset_light_yield",
                             directive="RICH — TRIM"), [], bears)
        self.assertNotIn("bear_no_narrative_veto_on_spear", v["guardrails_applied"])


class VerdictShapeTests(unittest.TestCase):
    def test_one_verdict_with_dissent_as_caveat(self):
        v = reconcile(_facts(),
                      [Claim("bull", "convex", grounded=True, field="rho")],
                      [Claim("bear", "dilution risk into tightening", grounded=True,
                             field="dilution_velocity"),
                       Claim("bear", "hard invalidation $0.58", grounded=True, invalidation=True)])
        self.assertIsInstance(v["verdict_line"], str)
        self.assertTrue(v["caveats"])                       # dissent preserved as caveat
        self.assertTrue(any("0.58" in c for c in v["caveats"]))
        self.assertIsNotNone(v["tension"])                  # strongest dissent named

    def test_contested_flag_in_band(self):
        # tune to ~50/50 by pitting equal grounded weights against a neutral directive
        v = reconcile(_facts(directive="FAIR VALUE — HOLD"),
                      [Claim("bull", "x", grounded=True)], [Claim("bear", "y", grounded=True)])
        self.assertTrue(v["convergence"]["contested"])

    def test_posture_composes_onto_the_action(self):
        v = reconcile(_facts(), [], [], posture={"code": "spear_exploit", "cap": 0.75,
                                                 "label": "SPEAR EXPLOIT"})
        self.assertIn("0.75x", v["verdict_line"])
        self.assertIsNotNone(v["posture_note"])

    def test_improving_asymmetry_reads_press(self):
        strong = [Claim("bull", "ρ rising", grounded=True, field="rho", weight=3.0)]
        v = reconcile(_facts(directive="STRONG ASYMMETRY — WATCH CLOSELY"), strong, [],
                      improving=True)
        self.assertEqual(v["stance"], "PRESS")

    def test_to_memory_entry_is_well_formed(self):
        v = reconcile(_facts(), [Claim("bull", "x", grounded=True)], [])
        e = council.to_memory_entry(v)
        self.assertEqual(e["type"], "council_verdict")
        self.assertEqual(e["ticker"], "AGA.V")
        self.assertIn("council", e["tags"])
        self.assertIn("stance", e["meta"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
