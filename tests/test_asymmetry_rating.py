"""Tests for the Phase 7 T-Q-V Asymmetry Rating (Conviction Mode).

Run: ``python -m pytest test_asymmetry_rating.py -q``  (or ``python test_asymmetry_rating.py``).
Pure-Python, no numpy/pandas — mirrors the dependency-free design of the rating module.
"""

import unittest

from asymmetry_rating import (
    DEFAULT_CONVICTION_CONFIG,
    compute_asymmetry_rating,
    build_conviction_state,
    merge_conviction_config,
    ASYMMETRY_GLOSSARY,
    tooltip_text,
    NICHE_TAGS,
    niche_tags_for,
)


def _spear(**over):
    """A healthy Option-Convexity basket trading just below its REP floor (the AGA.V archetype
    at the documented May-2026 operating point)."""
    base = dict(
        ticker="AGA.V", archetype="option_convexity", archetype_code="I",
        price=0.71, floor=0.824, base=1.69, bull=1.95, bear=1.05,
        mri=40.2, regime_alpha=0.4, forensic_score=3.5, avg_tq=1.12,
        conviction=0.6, runway_months=22.0, dilution_velocity=0.0, data_quality="full",
    )
    base.update(over)
    return base


class TestPillars(unittest.TestCase):
    def test_all_pillars_and_rating_bounded(self):
        r = compute_asymmetry_rating(_spear())
        for p in ("T", "Q", "V"):
            self.assertGreaterEqual(r["pillars"][p]["score"], 0.0)
            self.assertLessEqual(r["pillars"][p]["score"], 10.0)
        self.assertGreaterEqual(r["rating"], 0.0)
        self.assertLessEqual(r["rating"], 10.0)

    def test_macro_tailwind_monotonic_in_mri(self):
        # Lower MRI (more risk-on) -> higher macro tailwind T.
        hi = compute_asymmetry_rating(_spear(mri=20.0))["pillars"]["T"]["score"]
        lo = compute_asymmetry_rating(_spear(mri=80.0))["pillars"]["T"]["score"]
        self.assertGreater(hi, lo)

    def test_macro_tailwind_responds_to_alpha(self):
        pos = compute_asymmetry_rating(_spear(regime_alpha=0.9))["pillars"]["T"]["score"]
        neg = compute_asymmetry_rating(_spear(regime_alpha=-0.9))["pillars"]["T"]["score"]
        self.assertGreater(pos, neg)

    def test_alpha_has_significant_influence_on_rating(self):
        # alpha_option must meaningfully move the score. (The conviction lift intentionally
        # compresses macro's marginal effect on an extreme-V, below-floor name — the asymmetry is
        # the story there — so the full-rating swing is moderate while the T channel stays strong.)
        pos = compute_asymmetry_rating(_spear(regime_alpha=1.0))
        neg = compute_asymmetry_rating(_spear(regime_alpha=-1.0))
        self.assertGreater(pos["rating"] - neg["rating"], 0.8)
        self.assertGreater(pos["pillars"]["T"]["alpha_contribution"]
                           - neg["pillars"]["T"]["alpha_contribution"], 4.0)  # macro channel intact

    def test_option_convexity_leans_more_on_macro(self):
        # kappa is higher for option_convexity, so alpha moves T more than for a default archetype.
        oc = (compute_asymmetry_rating(_spear(archetype="option_convexity", regime_alpha=1.0))["pillars"]["T"]["score"]
              - compute_asymmetry_rating(_spear(archetype="option_convexity", regime_alpha=-1.0))["pillars"]["T"]["score"])
        yld = (compute_asymmetry_rating(_spear(archetype="asset_light_yield", regime_alpha=1.0))["pillars"]["T"]["score"]
               - compute_asymmetry_rating(_spear(archetype="asset_light_yield", regime_alpha=-1.0))["pillars"]["T"]["score"])
        self.assertGreater(oc, yld)

    def test_company_quality_rewards_forensics(self):
        clean = compute_asymmetry_rating(_spear(forensic_score=4.0))["pillars"]["Q"]["score"]
        dirty = compute_asymmetry_rating(_spear(forensic_score=2.0))["pillars"]["Q"]["score"]
        self.assertGreater(clean, dirty)

    def test_resource_quality_sources(self):
        # avg_tq and explicit resource_quality should map into [0,1] sensibly (fallbacks).
        q_tq = compute_asymmetry_rating(_spear(avg_tq=1.70))["pillars"]["Q"]["resource_quality"]
        q_lo = compute_asymmetry_rating(_spear(avg_tq=0.55))["pillars"]["Q"]["resource_quality"]
        self.assertAlmostEqual(q_tq, 1.0, places=3)
        self.assertAlmostEqual(q_lo, 0.0, places=3)
        # Fraser alone is now the 'jurisdiction' lens, normalized over the [50,95] band.
        a = _spear(); a.pop("avg_tq"); a["fraser_index"] = 84.0
        self.assertAlmostEqual(
            compute_asymmetry_rating(a)["pillars"]["Q"]["resource_quality"],
            (84.0 - 50) / (95 - 50), places=3)

    def test_mining_quality_checklist(self):
        # The Q pillar should read like a mining checklist when raw lenses are supplied.
        a = _spear(); a.pop("avg_tq")
        a.update(grade_gpt=290, resource_oz=270_000_000, fraser_index=84.2,
                 recovery=0.877, stage="PEA")
        r = compute_asymmetry_rating(a)
        lenses = r["pillars"]["Q"]["lenses"]
        for k in ("grade", "scale", "jurisdiction", "metallurgy", "permitting"):
            self.assertIn(k, lenses)
            self.assertGreaterEqual(lenses[k], 0.0)
            self.assertLessEqual(lenses[k], 1.0)
        self.assertAlmostEqual(lenses["scale"], 1.0, places=2)   # huge resource saturates scale
        self.assertLess(lenses["permitting"], 0.5)               # PEA is early-stage

    def test_management_blends_with_conviction(self):
        hi = compute_asymmetry_rating(_spear(management_score=1.0))["pillars"]["Q"]["management"]
        lo = compute_asymmetry_rating(_spear(management_score=0.0))["pillars"]["Q"]["management"]
        self.assertGreater(hi, lo)
        # Absent management_score falls back to the conviction read.
        none = compute_asymmetry_rating(_spear())["pillars"]["Q"]
        self.assertAlmostEqual(none["management"], none["conviction"], places=3)


class TestValuationAsymmetry(unittest.TestCase):
    def test_below_floor_saturates_support_and_payoff(self):
        # Price below the floor => downside-to-floor is zero, payoff saturates, support high.
        r = compute_asymmetry_rating(_spear(price=0.60, floor=0.824, bull=1.95))["pillars"]["V"]
        self.assertEqual(r["downside_to_floor_pct"], 0.0)
        self.assertGreaterEqual(r["floor_coverage"], 1.0)
        self.assertGreater(r["score"], 8.0)

    def test_symmetric_setup_scores_mid(self):
        # ~2:1 up/down to floor should land V_payoff near the half-saturation midpoint.
        r = compute_asymmetry_rating(_spear(price=1.0, floor=0.8, bull=1.4))["pillars"]["V"]
        # U=0.4, Df=0.2 -> rho=2 -> payoff=0.5
        self.assertAlmostEqual(r["payoff"], 0.5, places=2)

    def test_expensive_no_upside_scores_low(self):
        # Trading above the bull target with a distant floor => weak asymmetry.
        r = compute_asymmetry_rating(_spear(price=2.5, floor=0.824, base=1.69, bull=1.95))
        self.assertLess(r["pillars"]["V"]["score"], 3.5)
        self.assertEqual(r["pillars"]["V"]["upside_pct"], 0.0)

    def test_no_price_is_graceful(self):
        r = compute_asymmetry_rating(_spear(price=0.0))
        self.assertEqual(r["pillars"]["V"]["score"], 0.0)
        self.assertIsNotNone(r["rating"])


def _premium(**over):
    """A spear trading WELL ABOVE its floor (no structural support) — so the forensic gate
    bites fully (floor_support = 0)."""
    a = _spear(price=2.5, floor=0.50, base=1.69, bull=1.95, bear=1.05)
    a.update(over)
    return a


class TestGateAndRibbon(unittest.TestCase):
    def test_forensic_gate_caps_rating_when_not_floor_supported(self):
        r = compute_asymmetry_rating(_premium(forensic_score=1.0))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 6.0)            # broken JSF, no floor support -> capped

    def test_aggressive_dilution_caps_rating_at_premium(self):
        r = compute_asymmetry_rating(_premium(dilution_velocity=0.20))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.5)
        self.assertIn("AVOID", r["directive"])

    def test_short_runway_caps_rating_at_premium(self):
        r = compute_asymmetry_rating(_premium(runway_months=3.0))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.5)

    def test_solid_floor_relaxes_dilution_gate(self):
        # THE FIX: a junior below its REP floor with huge upside + routine financing dilution must
        # NOT be slammed to 'avoid' — the gate is relaxed because the downside is structurally held.
        r = compute_asymmetry_rating(_spear(price=0.71, floor=0.71 * 1.18,
                                            base=0.71 * 4.0, bull=0.71 * 5.76,
                                            dilution_velocity=0.12))
        self.assertGreaterEqual(r["rating"], 7.5)
        self.assertIn(r["band"], ("STRONG ASYMMETRY", "PRIME CONVICTION"))
        self.assertIn("ACCUMULATE", r["directive"])

    def test_broken_balance_sheet_still_penalized_below_floor(self):
        # Even below floor, a genuinely broken balance sheet (very low JSF) stays a heavy penalty.
        r = compute_asymmetry_rating(_spear(price=0.71, floor=0.71 * 1.18,
                                            base=2.0, bull=3.0, forensic_score=0.5))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 6.0)

    def test_dispersion_is_ribbon_not_penalty(self):
        # Sparse data must WIDEN the ribbon, not lower the point estimate vs the full-data case.
        full = compute_asymmetry_rating(_spear(data_quality="full"))
        sparse = compute_asymmetry_rating(_spear(data_quality="sparse"))
        self.assertEqual(full["rating"], sparse["rating"])             # identical point estimate
        self.assertGreater(sparse["confidence_ribbon"]["plus_minus"],
                           full["confidence_ribbon"]["plus_minus"])    # only the band widens

    def test_wide_scenario_band_widens_ribbon(self):
        tight = compute_asymmetry_rating(_spear(bull=1.8, bear=1.5))
        wide = compute_asymmetry_rating(_spear(bull=3.0, bear=0.3))
        self.assertGreater(wide["confidence_ribbon"]["plus_minus"],
                           tight["confidence_ribbon"]["plus_minus"])


class TestComposite(unittest.TestCase):
    def test_spear_operating_point_is_strong(self):
        # The documented AGA.V operating point should land in "Strong asymmetry" territory.
        r = compute_asymmetry_rating(_spear())
        self.assertGreaterEqual(r["rating"], 7.0)
        self.assertIn(r["band"], ("STRONG ASYMMETRY", "PRIME CONVICTION"))
        self.assertIn("WATCH", r["directive"].upper() + " " + ("ACCUMULATE" if "ACCUM" in r["directive"] else ""))

    def test_valuation_is_heaviest_pillar(self):
        pw = compute_asymmetry_rating(_spear())["pillar_weights"]
        self.assertGreater(pw["V"], pw["T"])
        self.assertGreater(pw["V"], pw["Q"])

    def test_band_labels_cover_range(self):
        self.assertIn(compute_asymmetry_rating(_spear(price=0.60))["band"],
                      {"PRIME CONVICTION", "STRONG ASYMMETRY"})
        # Genuinely broken + expensive + soft macro -> BROKEN / AVOID.
        broken = compute_asymmetry_rating(_spear(forensic_score=0.0, conviction=0.0, price=3.0,
                                                 avg_tq=0.55, bull=1.95, mri=90))
        self.assertEqual(broken["band"], "BROKEN / AVOID")


class TestBuildConvictionState(unittest.TestCase):
    def test_builds_and_ranks(self):
        assets = [
            _spear(),
            _spear(ticker="GROY", archetype="asset_light_yield", price=3.2, floor=2.0,
                   base=3.4, bull=3.8, bear=2.9, regime_alpha=0.1, avg_tq=None,
                   fraser_index=72.0, forensic_score=3.0),
            _spear(ticker="BAD", forensic_score=0.5, dilution_velocity=0.3, price=2.0, bull=2.1),
        ]
        state = build_conviction_state(assets, config=None,
                                       meta={"mri": 40.2, "regime": "RISK-ON"})
        self.assertEqual(state["view"], "conviction")
        self.assertTrue(state["primary"])
        self.assertEqual(len(state["baskets"]), 3)
        # Sorted highest-rating first; the gated "BAD" name must rank last.
        ratings = [b["rating"] for b in state["baskets"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertEqual(state["baskets"][-1]["ticker"], "BAD")
        self.assertEqual(state["context"]["regime"], "RISK-ON")

    def test_one_bad_basket_never_breaks_the_view(self):
        state = build_conviction_state([{"ticker": "X", "price": "not-a-number"}])
        self.assertEqual(state["status"], "live")
        self.assertEqual(len(state["baskets"]), 1)


class TestConfig(unittest.TestCase):
    def test_partial_config_merge(self):
        cfg = merge_conviction_config({"conviction_mode": {"rho_half": 3.0}})
        self.assertEqual(cfg["rho_half"], 3.0)
        self.assertIn("q_weights", cfg)                       # untouched default preserved
        self.assertEqual(cfg["q_weights"]["forensic"], 0.35)

    def test_defaults_self_consistent(self):
        for arche, w in DEFAULT_CONVICTION_CONFIG["pillar_weights_by_archetype"].items():
            self.assertAlmostEqual(w["T"] + w["Q"] + w["V"], 1.0, places=6, msg=arche)


class TestArchetypeDifferentiation(unittest.TestCase):
    def _royalty(self, **o):
        a = dict(ticker="GROY", archetype="asset_light_yield", price=4.44, floor=2.0, base=4.30,
                 mri=50, regime_alpha=0.12, forensic_score=3.0, conviction=0.5, data_quality="full",
                 fraser_index=72.0, stage="PRODUCING", management_score=0.60)
        a.update(o); return a

    def test_royalty_uses_value_mode(self):
        r = compute_asymmetry_rating(self._royalty())
        self.assertEqual(r["pillars"]["V"]["mode"], "value")

    def test_royalty_at_fair_value_is_not_weak(self):
        # The reported bug: a quality royalty near fair value must NOT be rated "WEAK/EXPENSIVE".
        r = compute_asymmetry_rating(self._royalty())
        self.assertGreaterEqual(r["rating"], 5.0)
        self.assertIn(r["band"], ("SOLID / FAIR", "HIGH QUALITY", "PRIME QUALITY"))
        self.assertNotIn("TRIM", r["directive"])

    def test_royalty_weights_q_heaviest(self):
        pw = compute_asymmetry_rating(self._royalty())["pillar_weights"]
        self.assertGreater(pw["Q"], pw["V"])
        self.assertGreater(pw["Q"], pw["T"])

    def test_explorer_still_asymmetry_mode_and_v_heaviest(self):
        r = compute_asymmetry_rating(_spear())
        self.assertEqual(r["pillars"]["V"]["mode"], "asymmetry")
        self.assertGreater(r["pillar_weights"]["V"], r["pillar_weights"]["Q"])

    def test_value_mode_centres_on_fair_value(self):
        # Trading right at fair value -> value_term sits at the configured center (quality premium).
        r = compute_asymmetry_rating(self._royalty(price=4.30, base=4.30))
        self.assertAlmostEqual(r["pillars"]["V"]["value_term"], 0.60, places=2)

    def test_value_mode_below_fair_value_scores_higher(self):
        cheap = compute_asymmetry_rating(self._royalty(price=3.4, base=4.30))["pillars"]["V"]["score"]
        rich = compute_asymmetry_rating(self._royalty(price=5.5, base=4.30))["pillars"]["V"]["score"]
        self.assertGreater(cheap, rich)


def _royalty73(**o):
    """A producing royalty (asset_light_yield) at ~fair value — the URC.TO / GROY shape."""
    a = dict(ticker="GROY", archetype="asset_light_yield", price=4.44, floor=2.0, base=4.30,
             mri=50, regime_alpha=0.12, forensic_score=3.0, conviction=0.5, fraser_index=72.0,
             stage="PRODUCING", management_score=0.6, data_quality="full")
    a.update(o)
    return a


class TestPhase73RoyaltyGate(unittest.TestCase):
    """Phase 7.3: the cash-burn survival gate (dilution / runway) must NOT slam a recurring-cash-flow
    royalty whose share issuance funds accretive acquisitions — it scores on cash-flow quality. The
    JSF (genuinely broken balance sheet) trigger stays universal, and explorers are still gated."""

    def test_royalty_high_dilution_not_gated(self):
        # Real GROY dilution (0.319) AND the engine's ×4-annualized figure (~1.28) both pass clean.
        for dv in (0.319, 1.28):
            r = compute_asymmetry_rating(_royalty73(dilution_velocity=dv))
            self.assertFalse(r["gate"]["applied"], f"dv={dv} should not gate a royalty")
            self.assertGreaterEqual(r["rating"], 5.0)
            self.assertNotIn("AVOID", r["directive"])
            self.assertEqual(r["pillars"]["V"]["mode"], "value")

    def test_royalty_runway_exempt_but_explorer_gated(self):
        roy = compute_asymmetry_rating(_royalty73(runway_months=3.0))
        self.assertFalse(roy["gate"]["applied"])                      # runway is not a royalty survival metric
        exp = compute_asymmetry_rating(dict(ticker="X", archetype="option_convexity", price=2.5,
              floor=0.5, base=1.69, bull=1.95, bear=1.05, mri=50, regime_alpha=0.0,
              forensic_score=3.0, runway_months=3.0))
        self.assertTrue(exp["gate"]["applied"])                       # same input gates a pre-revenue name

    def test_royalty_broken_balance_sheet_still_gated(self):
        # JSF is universal — a royalty with a genuinely broken balance sheet is still capped.
        r = compute_asymmetry_rating(_royalty73(forensic_score=0.5))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.5)

    def test_explorer_dilution_still_gated_at_premium(self):
        # Archetype differentiation: the burn gate still bites an explorer diluting at a premium.
        r = compute_asymmetry_rating(_spear(price=2.5, floor=0.5, dilution_velocity=0.20))
        self.assertTrue(r["gate"]["applied"])
        self.assertLessEqual(r["rating"], 4.5)
        self.assertIn("AVOID", r["directive"])

    def test_uranium_royalty_scores_on_quality(self):
        # URC.TO shape: asset-light yield trading a touch below fair value, routine dilution -> fair+.
        r = compute_asymmetry_rating(_royalty73(ticker="URC.TO", price=3.4, base=3.6,
                                                forensic_score=3.2, dilution_velocity=0.25))
        self.assertFalse(r["gate"]["applied"])
        self.assertGreaterEqual(r["rating"], 5.0)
        self.assertIn(r["band"], ("SOLID / FAIR", "HIGH QUALITY", "PRIME QUALITY"))

    def test_exempt_list_is_config_driven(self):
        # Emptying survival_exempt_archetypes re-enables the burn gate (config plumbing works).
        gate = dict(DEFAULT_CONVICTION_CONFIG["forensic_gate"], survival_exempt_archetypes=[])
        r = compute_asymmetry_rating(_royalty73(dilution_velocity=0.319),
                                     {"conviction_mode": {"forensic_gate": gate}})
        self.assertTrue(r["gate"]["applied"])


class TestPhase73Ceiling(unittest.TestCase):
    """Phase 7.3: a strong asymmetry setup reaches 8.5-9.5+ when JUSTIFIED by floor support and a
    macro tailwind — and only then; a moderate-macro op-point stays in STRONG, not PRIME."""

    def test_prime_setup_reaches_prime_band(self):
        # Deep below floor + big bull + risk-on macro + clean fundamentals -> PRIME CONVICTION.
        r = compute_asymmetry_rating(_spear(price=0.60, floor=0.85, base=2.8, bull=4.0,
                                            mri=20.0, regime_alpha=0.9, forensic_score=4.0,
                                            avg_tq=1.6, conviction=0.85, runway_months=30.0))
        self.assertGreaterEqual(r["rating"], 8.5)
        self.assertEqual(r["band"], "PRIME CONVICTION")

    def test_below_floor_plus_strong_macro_reaches_prime(self):
        # The documented spear, below floor, lifted into PRIME by a strong macro tailwind.
        r = compute_asymmetry_rating(_spear(mri=20.0, regime_alpha=0.9))
        self.assertGreaterEqual(r["rating"], 8.5)
        self.assertEqual(r["band"], "PRIME CONVICTION")

    def test_op_point_is_strong_not_prime_on_moderate_macro(self):
        # Moderate macro (mri 40, alpha 0.4): genuinely STRONG but not yet PRIME — the ceiling is earned.
        r = compute_asymmetry_rating(_spear())
        self.assertGreaterEqual(r["rating"], 7.0)
        self.assertLess(r["rating"], 8.5)


class TestPhase74Glossary(unittest.TestCase):
    """Phase 7.4: the educational tooltip glossary that powers the '?' icons in both frontends."""

    def test_glossary_covers_every_rendered_metric(self):
        required = ["rating", "T", "Q", "V", "band", "directive", "mri", "alpha",
                   "forensic_score", "resource_quality", "management", "dilution", "runway",
                   "floor_coverage", "upside", "payoff", "stability", "ribbon", "gate", "archetype"]
        for k in required:
            self.assertIn(k, ASYMMETRY_GLOSSARY, k)
            self.assertIn("what", ASYMMETRY_GLOSSARY[k], k)
            self.assertTrue(tooltip_text(k), k)              # flattens to non-empty multi-line text

    def test_dilution_tooltip_explains_the_archetype_edge(self):
        t = tooltip_text("dilution").lower()
        self.assertIn("royalt", t)                           # mentions royalties
        self.assertIn("exempt", t)                           # explains the 7.3 gate exemption
        self.assertIn("explorer", t)                         # contrasts with explorers

    def test_tooltip_unknown_key_is_empty(self):
        self.assertEqual(tooltip_text("does_not_exist"), "")

    def test_conviction_state_embeds_glossary_for_frontends(self):
        st = build_conviction_state([_spear()])
        self.assertIn("glossary", st)
        self.assertIn("rating", st["glossary"])
        self.assertIsInstance(st["glossary"]["rating"], str)

    def test_niche_tags_are_a_nonbreaking_hook(self):
        # now sourced from the canonical archetypes.SUBARCHETYPE_DNA (3rd taxonomy axis)
        self.assertIn("nsr_royalty", niche_tags_for("asset_light_yield"))
        self.assertIn("royalty_generator_holdco", niche_tags_for("asset_light_yield"))
        self.assertIn("near_term_dev", niche_tags_for("commodity_cyclical"))
        self.assertEqual(niche_tags_for("unknown_archetype"), [])   # safe default
        self.assertEqual(niche_tags_for(None), [])


class CommodityTailwindTests(unittest.TestCase):
    """Commodity-aware tailwind: two royalties on different metals must score different T,
    while sharing the archetype lean (CrowdEx-style layered tags). Backward-compatible."""

    def setUp(self):
        from asymmetry_rating import _pillar_macro_tailwind, merge_conviction_config
        self.T = _pillar_macro_tailwind
        self.cfg = merge_conviction_config(None)

    def _royalty(self, commodity, creg):
        return {"archetype": "asset_light_yield", "mri": 47.0, "regime_alpha": 0.2,
                "commodity": commodity, "commodity_regime": creg}

    def test_different_commodity_different_tailwind(self):
        gold = self.T(self._royalty("gold", 0.6), self.cfg)
        uranium = self.T(self._royalty("uranium", -0.4), self.cfg)
        self.assertNotAlmostEqual(gold["score"], uranium["score"])             # gold ≠ uranium
        self.assertAlmostEqual(gold["alpha_contribution"], uranium["alpha_contribution"])  # shared royalty lean
        self.assertGreater(gold["commodity_contribution"], uranium["commodity_contribution"])
        self.assertEqual(gold["commodity"], "gold")

    def test_same_commodity_same_tailwind(self):
        self.assertEqual(self.T(self._royalty("gold", 0.6), self.cfg)["score"],
                         self.T(self._royalty("gold", 0.6), self.cfg)["score"])

    def test_backward_compatible_without_commodity(self):
        asset = {"archetype": "option_convexity", "mri": 47.0, "regime_alpha": 0.3}
        t = self.T(asset, self.cfg)
        self.assertNotIn("commodity_contribution", t)                          # no commodity signal → legacy
        kappa = self.cfg["kappa_by_archetype"]["option_convexity"]
        a, m = (1 + 0.3) / 2, 1 - 47 / 100
        self.assertAlmostEqual(t["score"], round(10 * (kappa * a + (1 - kappa) * m), 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
