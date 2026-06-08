"""
FORGE keystone test (roadmap Idea 1 ①): the agent-facing conviction projection must surface the
asymmetry the Dialectic Council debates — ρ, φ, the payoff/upside legs — plus the JSF gate reason,
confidence ribbon, and price ladder, and it must fix the latent empty-T/Q/V bug. Pure: feeds a
realistic engine basket straight into the projection (no engine/network).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))
import core  # noqa: E402


def _basket():
    """A basket shaped like asymmetry_rating.build_conviction_state output (the spear)."""
    return {
        "ticker": "AGA.V", "archetype": "option_convexity", "archetype_code": "I",
        "subarchetype": "pre_pea", "subarchetype_label": "Pre-PEA developer",
        "sector_tags": ["Ag", "polymetallic", "T1_USA"],
        "rating": 9.12, "rating_raw": 8.80, "conviction_lift": 0.32,
        "band": "PRIME CONVICTION", "directive": "BELOW FLOOR — ACCUMULATE",
        "pillars": {
            "T": {"score": 6.48, "commodity": "silver", "commodity_regime": 0.41,
                  "commodity_contribution": 2.1, "alpha_contribution": 2.4},
            "Q": {"score": 7.01, "forensic_score": 3.6},
            "V": {"score": 8.22, "mode": "asymmetry", "rho": 3.14, "floor_coverage": 1.28,
                  "payoff": 0.61, "support": 0.8, "upside_pct": 141.0,
                  "downside_to_floor_pct": -21.9},
        },
        "gate": {"applied": False, "cap": 4.5, "reason": "JSF 3.6 >= min 3.5 — clear"},
        "confidence_ribbon": {"plus_minus": 1.4, "quality": "full"},
        "ladder": {"floor": 0.58, "bear": 0.61, "base": 1.05, "bull": 1.47, "price": 0.61},
        "catalysts": [{"title": "summer drill stack"}], "catalyst_signal": 0.3, "catalyst_count": 1,
    }


class ConvictionProjectionTests(unittest.TestCase):
    def setUp(self):
        self.p = core._project_conviction_basket(_basket())

    def test_pillar_scores_no_longer_empty(self):
        # the latent bug: T/Q/V were selected as flat keys that don't exist -> None
        self.assertEqual(self.p["T"], 6.48)
        self.assertEqual(self.p["Q"], 7.01)
        self.assertEqual(self.p["V"], 8.22)

    def test_asymmetry_reaches_the_agents(self):
        a = self.p["asymmetry"]
        self.assertEqual(a["rho"], 3.14)            # the payoff ratio the Bear attacks
        self.assertEqual(a["floor_coverage"], 1.28)  # φ — margin-of-safety leg
        self.assertEqual(a["upside_pct"], 141.0)
        self.assertEqual(a["downside_to_floor_pct"], -21.9)
        self.assertEqual(a["mode"], "asymmetry")

    def test_gate_ribbon_ladder_present(self):
        self.assertEqual(self.p["gate"]["cap"], 4.5)
        self.assertIn("reason", self.p["gate"])
        self.assertEqual(self.p["confidence_ribbon"]["quality"], "full")
        self.assertEqual(self.p["ladder"]["floor"], 0.58)
        self.assertEqual(self.p["ladder"]["bull"], 1.47)

    def test_tailwind_decomposition_surfaced(self):
        t = self.p["tailwind"]
        self.assertEqual(t["commodity"], "silver")
        self.assertEqual(t["commodity_regime"], 0.41)

    def test_taxonomy_and_verdict_carried(self):
        self.assertEqual(self.p["subarchetype"], "pre_pea")
        self.assertEqual(self.p["sector_tags"], ["Ag", "polymetallic", "T1_USA"])
        self.assertEqual(self.p["directive"], "BELOW FLOOR — ACCUMULATE")
        self.assertEqual(self.p["catalyst_count"], 1)

    def test_graceful_on_sparse_basket(self):
        p = core._project_conviction_basket({"ticker": "X"})
        self.assertEqual(p["ticker"], "X")
        self.assertIsNone(p["T"])
        self.assertIsNone(p["asymmetry"]["rho"])     # absent, not faked
        self.assertIsNone(p["gate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
