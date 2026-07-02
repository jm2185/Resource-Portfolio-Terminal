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
    story_card, render_story_card, ladder_expectation, scenario_probabilities, scenario_nav,
)


class ScenarioNavTests(unittest.TestCase):
    """V2 — probability-weighted scenario NAV: leg probabilities DERIVED from live signals (a catalyst
    p_discovery_delta · regime tilt · calibration base rate), with an honest breakeven fallback."""

    LADDER = {"floor": 0.80, "bear": 0.95, "base": 1.50, "bull": 2.50, "price": 1.00}

    def test_probabilities_sum_to_one_and_default_base_heavy(self):
        out = scenario_probabilities()
        self.assertFalse(out["grounded"])                  # no signal → not grounded
        p = out["p"]
        self.assertAlmostEqual(p["bear"] + p["base"] + p["bull"], 1.0, places=3)
        self.assertGreater(p["base"], p["bull"])           # base-heavy neutral prior

    def test_catalyst_grounds_and_shifts_to_bull(self):
        out = scenario_probabilities(p_discovery_delta=0.10)
        self.assertTrue(out["grounded"])
        self.assertGreater(out["p"]["bull"], out["p"]["bear"])
        self.assertTrue(any("catalyst" in d for d in out["drivers"]))

    def test_base_rate_grounds_and_recentres(self):
        hot = scenario_probabilities(base_rate=0.70)
        self.assertTrue(hot["grounded"])
        self.assertGreater(hot["p"]["bull"], hot["p"]["bear"])
        cold = scenario_probabilities(base_rate=0.20)
        self.assertGreater(cold["p"]["bear"], cold["p"]["bull"])

    def test_regime_tilt_alone_does_not_ground(self):
        out = scenario_probabilities(regime_tilt="RISK-ON")
        self.assertFalse(out["grounded"])                  # a tilt refines but never fabricates E[NAV]

    def test_scenario_nav_grounded_gives_expected_value(self):
        out = scenario_nav(self.LADDER, p_discovery_delta=0.10, regime_tilt="RISK-ON", price=1.00)
        self.assertTrue(out["grounded"])
        self.assertEqual(out["mode"], "derived_p")
        ev = out["expected_value"]
        self.assertTrue(0.95 <= ev <= 2.50)                # bounded by the ladder legs
        self.assertIsNotNone(out.get("edge_pct"))
        self.assertTrue(out.get("drivers"))

    def test_scenario_nav_ungrounded_falls_back_to_breakeven(self):
        out = scenario_nav(self.LADDER, regime_tilt="RISK-ON", price=1.00)
        self.assertFalse(out["grounded"])
        self.assertEqual(out["mode"], "breakeven_inversion")
        self.assertNotIn("expected_value", out)            # never an invented E[NAV]
        self.assertIn("p_bull_breakeven", out)


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

    def test_upside_uses_price_in_the_intrinsic_currency(self):
        """The currency-consistency bug: a USD name's intrinsic is CAD-normalized, so the upside
        ratio MUST use the CAD price, not the native one — otherwise GROY reads ~60% upside instead
        of the ~14% the conviction view shows. summarize_delta divides intrinsic ÷ price, so the
        caller must hand it a price in the intrinsic's (CAD) currency."""
        base = {"intrinsic_after_forensic": 4.60}             # CAD intrinsic
        native_price, fx = 2.88, 1.40
        cad_price = native_price * fx                          # 4.03
        wrong = summarize_delta(base, base, native_price, {})  # mixing currencies (the bug)
        right = summarize_delta(base, base, cad_price, {})     # the fix
        self.assertAlmostEqual(wrong["base"]["upside_pct"], 59.7, places=0)   # nonsense
        self.assertAlmostEqual(right["base"]["upside_pct"], 14.1, places=0)   # matches conviction view

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


class LadderExpectationTests(unittest.TestCase):
    """V2 — probability-weighted scenario NAV, done honestly: supplied p → E[V]; no p → INVERT to
    the breakeven belief (never an invented probability)."""

    LADDER = {"floor": 0.55, "bear": 0.60, "base": 1.20, "bull": 2.40, "price": 0.72}

    def test_supplied_p_gives_expected_value_and_edge(self):
        ev = ladder_expectation(self.LADDER, p={"bear": 0.3, "base": 0.5, "bull": 0.2})
        self.assertEqual(ev["mode"], "supplied_p")
        # E[V] = .3·0.60 + .5·1.20 + .2·2.40 = 1.26
        self.assertAlmostEqual(ev["expected_value"], 1.26, places=4)
        self.assertAlmostEqual(ev["edge_pct"], 75.0, places=1)   # 1.26/0.72 - 1
        self.assertIn("supplied probabilities", ev["note"])      # provenance, not authority

    def test_bad_probabilities_are_rejected_not_normalized_away(self):
        self.assertIn("error", ladder_expectation(self.LADDER, p={"bear": 0.6, "base": 0.5,
                                                                  "bull": 0.4}))   # sums to 1.5
        self.assertIn("error", ladder_expectation(self.LADDER, p={"bear": "x", "base": 0.5,
                                                                  "bull": 0.5}))

    def test_no_p_inverts_to_the_breakeven_belief(self):
        ev = ladder_expectation(self.LADDER)
        self.assertEqual(ev["mode"], "breakeven_inversion")
        # p*·2.40 + (1−p*)·0.60 = 0.72 ⇒ p* = 0.12/1.80
        self.assertAlmostEqual(ev["p_bull_breakeven"], 0.12 / 1.80, places=4)
        self.assertIn("bar to clear", ev["note"])                # a bar, not a forecast
        self.assertNotIn("expected_value", ev)                   # nothing invented

    def test_price_below_bear_is_named_as_paid_to_be_wrong(self):
        ev = ladder_expectation({**self.LADDER, "price": 0.50})
        self.assertEqual(ev["p_bull_breakeven"], 0.0)
        self.assertIn("paid to be wrong", ev["read"])

    def test_price_above_bull_is_named_as_unjustifiable(self):
        ev = ladder_expectation({**self.LADDER, "price": 3.00})
        self.assertEqual(ev["p_bull_breakeven"], 1.0)
        self.assertIn("no belief", ev["read"])

    def test_degenerate_ladder_yields_no_breakeven(self):
        ev = ladder_expectation({"bull": 1.0, "bear": 1.0, "price": 0.9})   # bull == bear
        self.assertNotIn("p_bull_breakeven", ev)


class StoryCardSpreadTests(unittest.TestCase):
    """Phase-7 flywheel: the story-card method spread (n_methods + spread_pct on card and render)."""

    SUMMARY = {"intrinsic_after_forensic": 1.71,
               "legs": {"cost": 1.0, "market": 2.0},
               "weights": {"cost": 0.3, "market": 0.7},
               "component_breakdown": {"cost": {"method": "REP"}, "market": {"method": "EV/oz"}}}

    def test_method_spread_on_card_and_render(self):
        card = story_card(self.SUMMARY, price=0.61, ticker="AGA.V")
        ms = card["method_spread"]
        self.assertEqual(ms["n_methods"], 2)
        self.assertIsNotNone(ms["spread_pct"])
        self.assertIn("methods spread", render_story_card(card))


if __name__ == "__main__":
    unittest.main(verbosity=2)
