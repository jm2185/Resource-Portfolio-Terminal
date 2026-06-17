"""
Runway-aware dilution in asymmetry_rating._forensic_gate — the CONVICTION-mode gate that renders
"dilution NN%/yr ... cap X" on the rating (distinct from the JSF gate). A FUNDED raise (high dilution
VELOCITY but a long runway) must NOT cap the asymmetry; a short-runway diluter still must.
"""
import unittest

import asymmetry_rating as ar

GATE_CFG = {"forensic_gate": {
    "score_floor": 1.5, "score_cap": 4.0, "jsf_relax": 0.5,
    "aggressive_dilution": 0.10, "dilution_cap": 4.5, "dilution_relax": 1.0,
    "dilution_runway_comfort_months": 18.0,
    "min_runway_months": 6.0, "runway_cap": 4.5, "runway_relax": 1.0,
    "floor_support_band": [0.85, 1.10],
    "survival_exempt_archetypes": ["asset_light_yield"],
}}


def _asset(**kw):
    a = {"archetype": "option_convexity", "forensic_score": 2.5,
         "dilution_velocity": 0.82, "runway_months": 19.3, "price": 0.63, "floor": 0.605}
    a.update(kw)
    return a


class ForensicGateRunwayTests(unittest.TestCase):
    def test_funded_raise_not_capped(self):
        # AGA-like: 82%/yr dilution but ~19 mo runway -> funding, NOT a survival cap
        g = ar._forensic_gate(_asset(runway_months=19.3), GATE_CFG)
        self.assertFalse(g["applied"])
        self.assertNotIn("dilution", g["reason"])

    def test_short_runway_diluter_still_capped(self):
        g = ar._forensic_gate(_asset(runway_months=5.0), GATE_CFG)
        self.assertTrue(g["applied"])
        self.assertIn("dilution", g["reason"])

    def test_mid_runway_below_comfort_still_dilution_capped(self):
        # 12 mo: survives (>6) but below the 18-mo funded bar -> dilution cap still applies
        g = ar._forensic_gate(_asset(runway_months=12.0), GATE_CFG)
        self.assertTrue(g["applied"])
        self.assertIn("dilution", g["reason"])

    def test_royalty_exempt_from_burn_triggers(self):
        g = ar._forensic_gate(_asset(archetype="asset_light_yield", runway_months=3.0), GATE_CFG)
        self.assertNotIn("dilution", g["reason"])
        self.assertNotIn("runway", g["reason"])

    def test_funded_raise_at_premium_still_capped(self):
        # funded (long runway) BUT trading at a PREMIUM (price >> floor, no support) -> dilution
        # stays gated: a valuation/promotional caution, not a survival one (desk policy preserved).
        g = ar._forensic_gate(_asset(runway_months=24.0, price=2.5, floor=0.50), GATE_CFG)
        self.assertTrue(g["applied"])
        self.assertIn("dilution", g["reason"])

    def test_comfort_knob_is_tunable(self):
        # comfort 999 -> even 19.3 mo isn't "funded" -> dilution caps again (proves the knob works)
        cfg = {"forensic_gate": dict(GATE_CFG["forensic_gate"], dilution_runway_comfort_months=999.0)}
        g = ar._forensic_gate(_asset(runway_months=19.3), cfg)
        self.assertTrue(g["applied"])
        self.assertIn("dilution", g["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
