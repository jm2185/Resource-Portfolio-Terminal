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
    """V5 — narrative→number decomposition + the breakpoint kill-switch (Damodaran discipline).

    Re-specced after the V5 audit: (a) the build-up must RECONCILE (Σ post-weight post-penalty
    contributions == intrinsic — parts never exceed the whole); (b) the spot solve inverts the
    engine's actual LINEAR linkage (value ∝ 1+β·(spot/ref−1)), labelled engine-exact only when
    spot_ref is in the payload; (c) the spear routes through peer EV/oz — its market leg has no
    spot linkage by design, so a spot breakpoint must NOT silently no-op."""

    # internally consistent: blended = 0.45·1.5 + 0.55·4.0 = 2.875; ×0.92 forensic ⇒ iv = 2.645
    SPOT_LINKED = {
        "intrinsic_after_forensic": 2.645,
        "forensic_penalty": 0.92,
        "legs": {"cost": 1.5, "market": 4.0, "income": 0.0},
        "weights": {"cost": 0.45, "market": 0.55, "income": 0.0},
        "component_breakdown": {
            "cost": {"method": "0.45x spot-linked NAV floor (proxy)", "value_cad": 1.5},
            "market": {"method": "spot-linked fair value", "spot_beta": 1.35, "spot_now": 86.0,
                       "spot_ref": 80.0, "value_cad": 4.0, "commodity": "uranium"},
            "income": {"method": "none", "value_cad": 0.0},
            "forensic": {"score": 0.92}},
    }

    def test_decomposition_and_upside(self):
        card = story_card(self.SPOT_LINKED, price=2.00, ticker="URC.TO")
        self.assertEqual(card["intrinsic"], 2.645)
        self.assertEqual(card["upside_pct"], 32.2)         # 2.645/2.00 - 1 (round-half-even)
        legs = {c["leg"] for c in card["build_up"]}
        self.assertEqual(legs, {"cost", "market", "income"})
        self.assertEqual(card["forensic_score"], 0.92)

    def test_build_up_reconciles_to_intrinsic(self):
        # the V5 audit bug: raw pre-weight legs summed PAST the intrinsic (market 3.48 vs total 1.90
        # on live AGA.V). The card's contributions must sum to the card's number.
        card = story_card(self.SPOT_LINKED, price=2.00, ticker="URC.TO")
        contribs = [c["contribution_cad"] for c in card["build_up"] if c["contribution_cad"] is not None]
        self.assertAlmostEqual(sum(contribs), card["intrinsic"], places=2)
        self.assertAlmostEqual(card["build_up_total"], card["intrinsic"], places=2)
        for c in card["build_up"]:                          # no single part exceeds the whole
            if c["contribution_cad"] is not None:
                self.assertLessEqual(c["contribution_cad"], card["intrinsic"] + 1e-9)

    def test_breakpoint_is_a_downward_commodity_move_engine_exact(self):
        card = story_card(self.SPOT_LINKED, price=2.00, ticker="URC.TO")
        bp = card["breakpoint"]
        self.assertEqual(bp["intrinsic_drop_pct"], 24.4)   # (1 - 2.00/2.645)
        self.assertEqual(bp["commodity"], "uranium")
        self.assertLess(bp["spot_break"], 86.0)            # the thesis breaks on a DROP in spot
        self.assertIn("engine-exact", bp["method"])        # inverts the LINEAR engine model
        self.assertIn("gap", bp["gap_note"].lower())       # the discrete-gap risk is named
        # hand-solve: ratio=(2.00−0.621)/2.024; F0=1+1.35·(86/80−1); s*=80·((ratio·F0−1)/1.35+1)
        ratio = (2.00 - 0.621) / 2.024
        f0 = 1.0 + 1.35 * (86.0 / 80.0 - 1.0)
        s_star = 80.0 * ((ratio * f0 - 1.0) / 1.35 + 1.0)
        self.assertAlmostEqual(bp["spot_break"], s_star, places=2)

    def test_breakpoint_without_spot_ref_is_labelled_first_order(self):
        s = copy.deepcopy(self.SPOT_LINKED)
        del s["component_breakdown"]["market"]["spot_ref"]
        bp = story_card(s, price=2.00, ticker="URC.TO")["breakpoint"]
        self.assertIsNotNone(bp["spot_break"])
        self.assertIn("first-order", bp["method"])         # honest about its own precision

    def test_breakpoint_flags_dilution_only_when_floor_above_price(self):
        # small spot-linked contribution → the non-spot floor sits above price → spot can't break it
        high_floor = {"intrinsic_after_forensic": 2.4,
                      "legs": {"cost": 3.0, "market": 1.0, "income": 0.0},
                      "weights": {"cost": 0.7, "market": 0.3, "income": 0.0},
                      "component_breakdown": {
                          "market": {"method": "spot-linked", "spot_beta": 1.35, "spot_now": 86.0,
                                     "spot_ref": 80.0, "value_cad": 1.0, "commodity": "uranium"}}}
        bp = story_card(high_floor, price=2.00, ticker="URC.TO")["breakpoint"]
        self.assertIsNone(bp["spot_break"])
        self.assertIn("dilution", bp["method"].lower())

    def test_spear_breakpoint_routes_through_peer_ev(self):
        # the explorer market leg has NO spot linkage (decoupled by design) — the old guard made the
        # breakpoint silently dead for the one name where convexity IS the thesis. It must route
        # through the peer multiple instead.
        spear = {"intrinsic_after_forensic": 0.945,
                 "forensic_penalty": 0.9,
                 "legs": {"cost": 0.45, "market": 1.2, "income": 0.0},
                 "weights": {"cost": 0.2, "market": 0.8, "income": 0.0},
                 "component_breakdown": {
                     "cost": {"method": "REP floor", "value_cad": 0.45},
                     "market": {"method": "quality-graded comps + exploration x (1+pi_opt)",
                                "peer_ev_oz": 2.08, "v_mkt_defined": 1.0, "v_exploration": 0.2},
                     "income": {"method": "none (pre-revenue explorer)", "value_cad": 0.0}}}
        bp = story_card(spear, price=0.71, ticker="AGA.V")["breakpoint"]
        self.assertIsNotNone(bp)
        self.assertNotIn("spot_break", bp)                 # no fake spot solve
        self.assertIsNotNone(bp["peer_ev_break"])
        self.assertLess(bp["peer_ev_break"], 2.08)         # breaks on a peer DE-RATE
        self.assertLess(bp["peer_ev_move_pct"], 0)
        self.assertIn("peer EV/oz", bp["method"])

    def test_negative_spot_beta_is_flagged(self):
        s = copy.deepcopy(self.SPOT_LINKED)
        s["component_breakdown"]["market"]["spot_beta"] = -1.35
        bp = story_card(s, price=2.00, ticker="URC.TO")["breakpoint"]
        self.assertIn("beta_warning", bp)

    def test_breakpoint_omitted_without_price(self):
        self.assertIsNone(story_card(self.SPOT_LINKED)["breakpoint"])

    def test_render_is_legible(self):
        render = render_story_card(story_card(self.SPOT_LINKED, price=2.00, ticker="URC.TO"))
        for token in ("STORY", "URC.TO", "intrinsic", "breaks", "uranium"):
            self.assertIn(token, render)


if __name__ == "__main__":
    unittest.main(verbosity=2)
