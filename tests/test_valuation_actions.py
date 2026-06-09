"""
Run: ``python -m unittest test_valuation_actions -v``  (stdlib only).

Covers the pure what-if helpers (override grammar + diffing) and an integration check
that the archetype revaluation actually responds to a macro override — i.e. that a
``run_valuation_whatif`` on a silver explorer moves intrinsic the right direction.
"""

import copy
import unittest

from valuation_actions import (
    canonical, parse_override, parse_overrides, summarize_delta, REGIME_KEYS, MACRO_KEYS,
    story_card, render_story_card,
)


class TestOverrideGrammar(unittest.TestCase):
    def test_absolute_delta_percent(self):
        self.assertEqual(parse_override(79.8, None), 79.8)
        self.assertEqual(parse_override("79.8", 30.0), 79.8)
        self.assertEqual(parse_override("+5", 30.0), 35.0)
        self.assertEqual(parse_override("-0.5", 1.8), 1.3)
        self.assertAlmostEqual(parse_override("+20%", 2.0), 2.4)
        self.assertAlmostEqual(parse_override("-10%", 2.0), 1.8)

    def test_percent_needs_base_and_bad_value_raises(self):
        with self.assertRaises(ValueError):
            parse_override("+20%", None)
        with self.assertRaises(ValueError):
            parse_override("abc", 1.0)

    def test_aliases_and_parsing(self):
        self.assertEqual(canonical("silver"), "spot_ag")
        self.assertEqual(canonical("RY"), "real_yield")
        self.assertIsNone(canonical("nonsense"))
        ov = parse_overrides("silver=+5 ry=-0.5 peer=+20% bogus=9")
        self.assertEqual(ov, {"spot_ag": "+5", "real_yield": "-0.5", "peer_ev_oz": "+20%"})
        self.assertEqual(parse_overrides({"silver": "+5"}), {"spot_ag": "+5"})

    def test_key_sets_consistent(self):
        self.assertTrue(REGIME_KEYS.issubset({"real_yield", "silver_vol", "mri", "dxy"}))
        self.assertIn("spot_ag", MACRO_KEYS)


class TestSummarizeDelta(unittest.TestCase):
    def test_diff_intrinsic_and_upside(self):
        base = {"intrinsic_after_forensic": 1.00, "legs": {"market": 1.0}}
        scen = {"intrinsic_after_forensic": 1.50, "legs": {"market": 1.5}}
        out = summarize_delta(base, scen, price=1.00, applied={"spot_ag": {"from": 30, "to": 45}})
        self.assertEqual(out["base"]["intrinsic"], 1.00)
        self.assertEqual(out["scenario"]["intrinsic"], 1.50)
        self.assertEqual(out["delta"]["intrinsic_pct"], 50.0)
        self.assertEqual(out["base"]["upside_pct"], 0.0)     # 1.00 / 1.00 - 1
        self.assertEqual(out["scenario"]["upside_pct"], 50.0)  # 1.50 / 1.00 - 1
        self.assertEqual(out["delta"]["upside_pp"], 50.0)

    def test_handles_missing_gracefully(self):
        out = summarize_delta({}, {}, price=None, applied={})
        self.assertIsNone(out["delta"]["intrinsic_pct"])
        self.assertIsNone(out["base"]["upside_pct"])


class TestArchetypeRevaluationResponds(unittest.TestCase):
    """The integration heart of run_whatif: get_valuation must move when a macro knob moves."""

    def setUp(self):
        try:
            from archetypes import build_default_router, REGIME_ORDER
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"archetypes unavailable: {exc}")
        self.router = build_default_router()        # default reads v5_config.json
        self.neutral = [0.0] * len(REGIME_ORDER)

    def _aga_payload(self, peer_ev=2.08):
        # Per ENGINE_DESIGN, the explorer's re-rating flows through peer EV/oz (the absolute silver
        # level is intentionally decoupled to avoid double-counting), so peer_ev is the mover here.
        return {
            "currency": "CAD", "price": 0.71, "shares_out": 120_000_000, "aisc": 18.0,
            "macro": {"spot_ag": 30.0, "gold": 2400.0, "real_yield": 1.8,
                      "silver_vol": 0.35, "capital_discount": 0.9, "y30": 4.8},
            "comps": {"peer_ev_oz": peer_ev},
            "financials": {"cash": 8_000_000, "monthly_burn": 600_000},
        }

    def test_peer_rerate_raises_explorer_intrinsic(self):
        base = self.router.get_valuation("AGA.V", self._aga_payload(2.08), self.neutral)
        scen = self.router.get_valuation("AGA.V", self._aga_payload(3.12), self.neutral)  # +50% peer EV/oz
        bi = base.get("intrinsic_after_forensic")
        si = scen.get("intrinsic_after_forensic")
        self.assertIsInstance(bi, (int, float))
        self.assertIsInstance(si, (int, float))
        self.assertGreater(si, bi, "a +50% peer EV/oz re-rate must raise the explorer intrinsic")

    def test_whatif_diff_shape_end_to_end(self):
        p = self._aga_payload(2.08)
        base = self.router.get_valuation("AGA.V", p, self.neutral)
        scen = self.router.get_valuation("AGA.V", self._aga_payload(3.12), self.neutral)
        out = summarize_delta(base, scen, p["price"], {"peer_ev_oz": {"from": 2.08, "to": 3.12}})
        self.assertGreater(out["delta"]["intrinsic_pct"], 0.0)

    def test_summarize_delta_passes_through_breakdown_for_story_card(self):
        base = self.router.get_valuation("AGA.V", self._aga_payload(2.08), self.neutral)
        out = summarize_delta(base, base, base and 1.00, {})
        self.assertIn("breakdown", out["base"])           # component breakdown rides along
        self.assertIn("weights", out["base"])
        # and the Story Card can be built straight off the enriched whatif 'base'
        card = story_card(out["base"], price=1.00, ticker="AGA.V")
        self.assertIsNotNone(card["intrinsic"])
        self.assertTrue(card["build_up"])                 # at least one leg decomposed


class StoryCardTests(unittest.TestCase):
    """V5 — narrative→number decomposition + the breakpoint kill-switch (Damodaran discipline)."""

    SPOT_LINKED = {
        "intrinsic_after_forensic": 3.26,
        "legs": {"cost": 1.5, "market": 4.0, "income": 0.0},
        "weights": {"cost": 0.45, "market": 0.55, "income": 0.0},
        "component_breakdown": {
            "cost": {"method": "0.45x spot-linked NAV floor (proxy)", "value_cad": 1.5},
            "market": {"method": "spot-linked fair value", "spot_beta": 1.35, "spot_now": 86.0,
                       "value_cad": 4.0, "commodity": "uranium"},
            "income": {"method": "none", "value_cad": 0.0},
            "forensic": {"score": 0.92}},
    }

    def test_decomposition_and_upside(self):
        card = story_card(self.SPOT_LINKED, price=2.50, ticker="URC.TO")
        self.assertEqual(card["intrinsic"], 3.26)
        self.assertEqual(card["upside_pct"], 30.4)         # 3.26/2.50 - 1
        legs = {c["leg"] for c in card["build_up"]}
        self.assertEqual(legs, {"cost", "market", "income"})
        self.assertEqual(card["forensic_score"], 0.92)

    def test_breakpoint_is_a_downward_commodity_move(self):
        card = story_card(self.SPOT_LINKED, price=2.50, ticker="URC.TO")
        bp = card["breakpoint"]
        self.assertEqual(bp["intrinsic_drop_pct"], 23.3)   # (1 - 2.50/3.26)
        self.assertEqual(bp["commodity"], "uranium")
        self.assertLess(bp["spot_break"], 86.0)            # the thesis breaks on a DROP in spot
        self.assertIn("first-order", bp["method"])

    def test_breakpoint_omitted_without_price(self):
        self.assertIsNone(story_card(self.SPOT_LINKED)["breakpoint"])

    def test_render_is_legible(self):
        render = render_story_card(story_card(self.SPOT_LINKED, price=2.50, ticker="URC.TO"))
        for token in ("STORY", "URC.TO", "intrinsic", "breaks", "uranium"):
            self.assertIn(token, render)


if __name__ == "__main__":
    unittest.main(verbosity=2)
