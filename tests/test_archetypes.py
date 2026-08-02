"""
Phase 5 — Polymorphic Archetype Factory test suite.

Pure-stdlib (unittest only) so it runs anywhere, including environments where the
heavy `engine.py` dependencies (numpy / yfinance / fastapi) are absent. Covers the
abstract contract, the metadata DNA registry, all five concrete archetypes, FX
normalization, graceful degradation, the Regime Impact Vector, the conviction
overlay, the forensic sieve, the router (fail-fast + tag/score routing + lifecycle
versioning + correlation groups), and the anchor 60/15/15/10 test bench.
"""

import json
import unittest
from datetime import date

from archetypes import (
    AssetArchetype, ArchetypeDNA, ARCHETYPE_DNA, ARCHETYPE_REGISTRY,
    OptionConvexityArchetype, CapitalMarginArchetype, CommodityCyclicalArchetype,
    AssetLightYieldArchetype, PureMacroDeltaArchetype,
    PolymorphicRouter, TickerNotRegisteredError, ArchetypeConfigError,
    build_default_router, technical_quality, option_premium,
    capital_discount_factor, spot_linked_fair_value, NEUTRAL_REGIME,
)
from archetypes import (
    _commodity_spot, SubArchetypeDNA, SUBARCHETYPE_DNA, subarchetype_dna,
    subarchetypes_for, compose_leg_weights, SparseDataError,
)

CONFIG_PATH = "v5_config.json"
MACRO = {"spot_ag": 75.6, "gold": 2650.0, "real_yield": 2.1, "silver_vol": 0.30,
         "y30": 4.99, "capital_discount": 0.88}


def _cfg():
    with open(CONFIG_PATH, "r") as fh:
        return json.load(fh)


def _aga_payload(cfg, **over):
    data = {
        "shares_out": cfg["aga_shares_out"], "currency": "CAD", "macro": dict(MACRO),
        "aisc": 25.6, "comps": {"peer_ev_oz": 2.078},
        "financials": {"cash": 53.07e6, "monthly_burn": 0.75e6, "shares_t0": 208.6e6,
                       "shares_t1": 208.6e6, "curr_burn": 2.25e6, "prev_burn": 2.0e6,
                       "enterprise_value": 120e6, "sga_expense": 0.4e6},
    }
    data.update(over)
    return data


def _groy_payload(cfg, currency="USD", **over):
    data = {
        "currency": currency, "shares_out": 150e6, "macro": dict(MACRO),
        "ref_price": 3.22, "spot_ref": 74.8, "base_mult": 1.15,
        "annual_cashflow_per_share": 0.18,
        "financials": {"sloan_cfo": 0.01, "sloan_bs": 0.01, "net_debt": 0.0, "ebitda": 40e6,
                       "shares_t0": 150e6, "shares_t1": 150e6},
    }
    data.update(over)
    return data


def _royalty_data(currency="CAD", **over):
    """Asset-light FLOOR inputs — Orogen-shaped: net liquid backing (≈$30M working capital, debt-free,
    52.6M sh) + a producing-royalty cash stream (≈$13.6M/yr). The floor's two legs."""
    d = {"currency": currency, "shares_out": 52.6e6, "macro": dict(MACRO),
         "working_capital": 30e6, "total_debt": 0.0, "annual_cashflow": 13.6e6,
         "ref_price": 3.75, "spot_ref": 2860.0, "commodity": "gold"}
    d.update(over)
    return d


class TestAssetLightRoyaltyFloor(unittest.TestCase):
    """The royalty FLOOR is the REP analogue — net liquid backing + a stressed producing-royalty NAV,
    additive and recoverable — NOT accounting book value (book understates a royalty's economic floor,
    the OGN.V $0.50-on-$3.75 bug). Book/cash/ref survive only as a clearly-labelled degraded proxy."""

    def setUp(self):
        self.cfg = _cfg()
        self.arch = AssetLightYieldArchetype("OGN.V", self.cfg)

    @staticmethod
    def _stressed_nav(cf_ps, stress=0.65, disc=0.12):
        return cf_ps * stress / disc

    def test_floor_is_net_liquid_plus_stressed_nav(self):
        cost = self.arch.calculate_cost_basis(_royalty_data())
        cf_ps = 13.6e6 / 52.6e6
        expect = (30e6 / 52.6e6) + self._stressed_nav(cf_ps)        # additive, the REP analogue
        self.assertAlmostEqual(cost, expect, places=3)
        bd = self.arch._breakdown["cost"]
        self.assertIn("REP-equivalent", bd["method"])
        self.assertNotIn("book", bd["method"].lower())

    def test_book_value_ignored_when_principled_inputs_present(self):
        # book ($0.50) present, but the principled floor must win AND be far higher — the OGN fix
        cost = self.arch.calculate_cost_basis(_royalty_data(book_value_per_share=0.50))
        self.assertGreater(cost, 0.50)
        self.assertNotIn("book", self.arch._breakdown["cost"]["method"].lower())

    def test_stressed_nav_only_without_liquid_backing(self):
        d = _royalty_data()
        d.pop("working_capital")
        cost = self.arch.calculate_cost_basis(d)
        self.assertAlmostEqual(cost, self._stressed_nav(13.6e6 / 52.6e6), places=3)

    def test_falls_back_to_book_labelled_degraded(self):
        cost = self.arch.calculate_cost_basis(
            {"currency": "CAD", "shares_out": 52.6e6, "book_value_per_share": 0.50})
        self.assertAlmostEqual(cost, 0.50, places=4)
        self.assertTrue(self.arch._breakdown["cost"]["degraded_proxy"])
        self.assertIn("DEGRADED", self.arch._breakdown["cost"]["method"])

    def test_floor_stays_below_full_income_nav(self):
        # the floor (stressed, no growth) must sit BELOW the going-concern income NAV — recoverable downside
        d = _royalty_data()
        self.assertLess(self.arch.calculate_cost_basis(d),
                        self.arch.calculate_income_basis(d, NEUTRAL_REGIME))

    def test_stress_params_are_config(self):
        cfg = _cfg()
        cfg["royalty_floor"] = {"cashflow_stress": 1.0, "discount": 0.09}    # un-stressed, lower cap rate
        d = _royalty_data(); d.pop("working_capital")                        # isolate the NAV leg
        cost = AssetLightYieldArchetype("OGN.V", cfg).calculate_cost_basis(d)
        self.assertAlmostEqual(cost, self._stressed_nav(13.6e6 / 52.6e6, 1.0, 0.09), places=3)

    def test_sparse_errors_with_no_floor_inputs(self):
        with self.assertRaises(SparseDataError):
            self.arch.calculate_cost_basis({"currency": "CAD", "shares_out": 52.6e6})


# --------------------------------------------------------------------------- #
#  Abstract contract + metadata DNA
# --------------------------------------------------------------------------- #
class TestAbstractContract(unittest.TestCase):
    def test_cannot_instantiate_base(self):
        with self.assertRaises(TypeError):
            AssetArchetype("X")

    def test_every_archetype_binds_dna_and_implements_contract(self):
        cfg = _cfg()
        for name, cls in ARCHETYPE_REGISTRY.items():
            inst = cls("T", cfg)
            self.assertIsInstance(inst.DNA, ArchetypeDNA)
            self.assertEqual(inst.DNA.name, name)
            self.assertEqual(inst.name, name)
            for meth in ("calculate_cost_basis", "calculate_market_basis",
                         "calculate_income_basis", "calculate_forensic_score",
                         "valuation_summary", "normalize_fx", "calculate_conviction"):
                self.assertTrue(callable(getattr(inst, meth)), f"{name}.{meth}")
            self.assertIn(inst.DNA.regime_index, range(5))
            self.assertIn(inst.DNA.regime_tilt_leg, ("cost", "market", "income"))

    def test_dna_registry_codes_and_indices(self):
        self.assertEqual(len(ARCHETYPE_DNA), 5)
        self.assertEqual([d.code for d in ARCHETYPE_DNA.values()], ["I", "II", "III", "IV", "V"])
        self.assertEqual(sorted(d.regime_index for d in ARCHETYPE_DNA.values()), [0, 1, 2, 3, 4])

    def test_base_weights_sum_to_one_per_archetype(self):
        for d in ARCHETYPE_DNA.values():
            self.assertAlmostEqual(sum(d.base_weights.values()), 1.0, places=6, msg=d.name)


# --------------------------------------------------------------------------- #
#  Option Convexity (AGA.V)
# --------------------------------------------------------------------------- #
class TestOptionConvexity(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()
        self.arch = OptionConvexityArchetype("AGA.V", self.cfg)

    def test_cost_is_rep_floor(self):
        cost = self.arch.calculate_cost_basis(_aga_payload(self.cfg))
        self.assertAlmostEqual(cost, 0.744, delta=0.01)        # REP floor after the 2026-06-12 treasury refresh
        # (cash C$53.07M -> C$48M per the Red Mountain commencement PR; was 0.764 post-Belmont-fix, 0.824 before)

    def test_triangulation_blend_between_legs(self):
        s = self.arch.valuation_summary(_aga_payload(self.cfg), regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["archetype_code"], "I")
        self.assertAlmostEqual(sum(s["weights"].values()), 1.0, places=6)
        lo, hi = sorted([s["legs"]["cost"], s["legs"]["market"]])
        self.assertLessEqual(lo, s["blended_intrinsic"])
        self.assertLessEqual(s["blended_intrinsic"], hi)
        self.assertEqual(s["legs"]["income"], 0.0)             # explorer income zero by design
        self.assertEqual(s["data_quality"], "full")            # income weight 0 -> not "degraded"

    def test_market_leg_dominates_and_exceeds_cost(self):
        s = self.arch.valuation_summary(_aga_payload(self.cfg), regime_vector=NEUTRAL_REGIME)
        self.assertGreater(s["legs"]["market"], s["legs"]["cost"])
        self.assertGreater(s["weights"]["market"], s["weights"]["cost"])

    def test_exploration_leg_carries_capital_discount(self):
        """Audit F1: the exploration-upside leg must apply the SAME capital-discount haircut as
        the defined-ounce market leg (the engine's authoritative path does). Pre-fix the replica
        omitted it, so v_exploration was invariant to capital_discount — a ~14% over-statement.
        Probe it directly: halving capital_discount must scale v_exploration by the same factor."""
        full = _aga_payload(self.cfg)
        full["macro"]["capital_discount"] = 0.88
        half = _aga_payload(self.cfg)
        half["macro"]["capital_discount"] = 0.44                # exactly half
        s_full = self.arch.valuation_summary(full, regime_vector=NEUTRAL_REGIME)
        s_half = self.arch.valuation_summary(half, regime_vector=NEUTRAL_REGIME)
        ve_full = s_full["component_breakdown"]["market"]["v_exploration"]
        ve_half = s_half["component_breakdown"]["market"]["v_exploration"]
        self.assertGreater(ve_full, 0.0)
        # v_exploration now scales linearly with capital_discount (it didn't before the fix)
        self.assertAlmostEqual(ve_half, ve_full * 0.5, delta=ve_full * 0.02)


# --------------------------------------------------------------------------- #
#  FX normalization (base = CAD)
# --------------------------------------------------------------------------- #
class TestFXNormalization(unittest.TestCase):
    def test_usd_name_scales_by_fx_vs_cad_twin(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg, fx_rates={"USD": 1.38})
        usd = arch.valuation_summary(_groy_payload(cfg, "USD"), regime_vector=NEUTRAL_REGIME)
        cad = arch.valuation_summary(_groy_payload(cfg, "CAD"), regime_vector=NEUTRAL_REGIME)
        # every leg passes through the same FX hook; the blend is linear in the legs
        self.assertAlmostEqual(usd["blended_intrinsic"], cad["blended_intrinsic"] * 1.38, delta=1e-3)
        self.assertEqual(usd["native_currency"], "USD")
        self.assertEqual(usd["base_currency"], "CAD")

    def test_normalize_fx_hook_basics(self):
        arch = PureMacroDeltaArchetype("PSLV", _cfg(), fx_rates={"USD": 1.40})
        self.assertAlmostEqual(arch.normalize_fx(10.0, "CAD"), 10.0)
        self.assertAlmostEqual(arch.normalize_fx(10.0, "USD"), 14.0)
        self.assertEqual(arch.normalize_fx(10.0, "ZZZ"), 10.0)      # unknown ccy -> graceful 1.0
        self.assertEqual(arch.normalize_fx(float("nan"), "USD"), 0.0)


# --------------------------------------------------------------------------- #
#  Graceful degradation
# --------------------------------------------------------------------------- #
class TestGracefulDegradation(unittest.TestCase):
    def test_missing_comps_drops_market_leg(self):
        cfg = _cfg()
        arch = OptionConvexityArchetype("AGA.V", cfg)
        s = arch.valuation_summary(_aga_payload(cfg, comps={}), comps={}, regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["confidence"]["market"], 0.0)
        self.assertEqual(s["weights"]["cost"], 1.0)            # blend falls back to the cost floor
        self.assertAlmostEqual(s["blended_intrinsic"], s["legs"]["cost"], places=6)
        self.assertEqual(s["data_quality"], "degraded")
        self.assertTrue(any("market" in w for w in s["warnings"]))

    def test_total_sparsity_yields_zero_not_crash(self):
        arch = OptionConvexityArchetype("AGA.V", {})
        s = arch.valuation_summary({}, comps={}, regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["blended_intrinsic"], 0.0)
        self.assertEqual(s["data_quality"], "sparse")
        self.assertEqual(sum(s["weights"].values()), 0.0)

    def test_income_archetype_degrades_when_cashflow_missing(self):
        cfg = _cfg()
        data = _groy_payload(cfg, "USD")
        data.pop("annual_cashflow_per_share")
        s = AssetLightYieldArchetype("GROY", cfg).valuation_summary(data, regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["confidence"]["income"], 0.0)
        self.assertGreater(s["blended_intrinsic"], 0.0)        # cost+market still carry it
        self.assertEqual(s["data_quality"], "degraded")


# --------------------------------------------------------------------------- #
#  Regime Impact Vector
# --------------------------------------------------------------------------- #
class TestRegimeVector(unittest.TestCase):
    def test_alpha_extracted_at_correct_index_and_clamped(self):
        cfg = _cfg()
        vec = (0.1, 0.2, 0.3, 0.4, 0.5)
        self.assertAlmostEqual(OptionConvexityArchetype("A", cfg).regime_alpha(vec), 0.1)
        self.assertAlmostEqual(CapitalMarginArchetype("A", cfg).regime_alpha(vec), 0.2)
        self.assertAlmostEqual(CommodityCyclicalArchetype("A", cfg).regime_alpha(vec), 0.3)
        self.assertAlmostEqual(AssetLightYieldArchetype("A", cfg).regime_alpha(vec), 0.4)
        self.assertAlmostEqual(PureMacroDeltaArchetype("A", cfg).regime_alpha(vec), 0.5)
        self.assertEqual(PureMacroDeltaArchetype("A", cfg).regime_alpha((0, 0, 0, 0, 9.0)), 1.0)  # clamp
        self.assertEqual(OptionConvexityArchetype("A", cfg).regime_alpha(None), 0.0)
        self.assertEqual(CapitalMarginArchetype("A", cfg).regime_alpha((0.5,)), 0.0)              # short vector

    def test_positive_alpha_amplifies_negative_fades(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg)
        base = _groy_payload(cfg, "USD")
        up = arch.valuation_summary(base, regime_vector=(0, 0, 0, 1.0, 0))["blended_intrinsic"]
        flat = arch.valuation_summary(base, regime_vector=NEUTRAL_REGIME)["blended_intrinsic"]
        down = arch.valuation_summary(base, regime_vector=(0, 0, 0, -1.0, 0))["blended_intrinsic"]
        self.assertGreater(up, flat)
        self.assertGreater(flat, down)

    def test_income_tilt_moves_only_income_leg(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg)
        a = arch.valuation_summary(_groy_payload(cfg, "USD"), regime_vector=NEUTRAL_REGIME)
        b = arch.valuation_summary(_groy_payload(cfg, "USD"), regime_vector=(0, 0, 0, 0.8, 0))
        self.assertAlmostEqual(a["legs"]["cost"], b["legs"]["cost"], places=6)
        self.assertAlmostEqual(a["legs"]["market"], b["legs"]["market"], places=6)
        self.assertGreater(b["legs"]["income"], a["legs"]["income"])
        self.assertEqual(b["regime_tilt_leg"], "income")

    def test_market_tilt_archetype_moves_market_leg(self):
        cfg = _cfg()
        arch = PureMacroDeltaArchetype("PSLV", cfg, fx_rates={"USD": 1.38})
        payload = {"currency": "USD", "nav_per_unit": 12.0, "spot_ref": 74.8, "macro": dict(MACRO)}
        a = arch.valuation_summary(payload, regime_vector=NEUTRAL_REGIME)
        b = arch.valuation_summary(payload, regime_vector=(0, 0, 0, 0, 0.6))
        self.assertAlmostEqual(a["legs"]["cost"], b["legs"]["cost"], places=6)
        self.assertGreater(b["legs"]["market"], a["legs"]["market"])
        self.assertEqual(b["regime_tilt_leg"], "market")
        self.assertAlmostEqual(b["regime_multiplier"], 1.3, places=6)   # 1 + 0.5*0.6


# --------------------------------------------------------------------------- #
#  Conviction overlay (CrowdEx heritage)
# --------------------------------------------------------------------------- #
class TestConvictionOverlay(unittest.TestCase):
    def test_conviction_bounds_and_direction(self):
        arch = CommodityCyclicalArchetype("GMX.TO", _cfg())
        self.assertEqual(arch.calculate_conviction({}), 0.5)            # neutral with no signals
        bull = arch.calculate_conviction({"insider_net_buying": 1.0, "catalyst_momentum": 1.0,
                                          "institutional_flow": 1.0})
        bear = arch.calculate_conviction({"insider_net_buying": -1.0, "short_interest_pressure": 1.0})
        self.assertGreater(bull, 0.5)
        self.assertLess(bear, 0.5)
        self.assertTrue(0.0 <= bull <= 1.0 and 0.0 <= bear <= 1.0)

    def test_conviction_is_surfaced_but_not_in_intrinsic(self):
        cfg = _cfg()
        arch = OptionConvexityArchetype("AGA.V", cfg)
        plain = arch.valuation_summary(_aga_payload(cfg), regime_vector=NEUTRAL_REGIME)
        convd = arch.valuation_summary(_aga_payload(cfg, conviction_signals={"insider_net_buying": 1.0,
                                       "catalyst_momentum": 1.0}), regime_vector=NEUTRAL_REGIME)
        self.assertIn("conviction", plain)
        self.assertGreater(convd["conviction"], plain["conviction"])
        # conviction is a SIZING overlay — it must NOT move the intrinsic
        self.assertAlmostEqual(plain["blended_intrinsic"], convd["blended_intrinsic"], places=6)


# --------------------------------------------------------------------------- #
#  Forensic sieve
# --------------------------------------------------------------------------- #
class TestForensicSieve(unittest.TestCase):
    def test_score_bounds_and_penalty_mapping(self):
        arch = OptionConvexityArchetype("AGA.V", _cfg())
        clean = {"cash": 20e6, "monthly_burn": 0.5e6, "shares_t0": 100e6, "shares_t1": 100e6,
                 "curr_burn": 1.4e6, "prev_burn": 1.5e6, "enterprise_value": 80e6, "sga_expense": 0.2e6}
        # shares_t0 (current) > t1 (prior) => dilution velocity fails (engine convention)
        dirty = {"cash": 2e6, "monthly_burn": 1.0e6, "shares_t0": 110e6, "shares_t1": 100e6,
                 "curr_burn": 4.0e6, "prev_burn": 1.0e6, "enterprise_value": 80e6, "sga_expense": 1.5e6}
        self.assertAlmostEqual(arch.calculate_forensic_score(clean), 4.0, places=6)
        self.assertAlmostEqual(arch.calculate_forensic_score(dirty), 0.0, places=6)
        self.assertAlmostEqual(arch.forensic_penalty(4.0), 1.0, places=6)
        self.assertAlmostEqual(arch.forensic_penalty(0.0), 0.70, places=6)
        self.assertAlmostEqual(arch.forensic_penalty(2.0), 0.85, places=6)

    def test_missing_financials_neutral_default(self):
        self.assertAlmostEqual(OptionConvexityArchetype("AGA.V", _cfg()).calculate_forensic_score({}), 2.5, places=6)

    def test_passive_vehicle_sieve(self):
        arch = PureMacroDeltaArchetype("PSLV", _cfg())
        clean = {"premium_to_nav": 0.01, "expense_ratio": 0.005, "adv_usd": 50e6, "physically_backed": True}
        self.assertAlmostEqual(arch.calculate_forensic_score(clean), 4.0, places=6)

    def test_forensic_penalty_applies_to_blended(self):
        cfg = _cfg()
        arch = OptionConvexityArchetype("AGA.V", cfg)
        dirty = {"cash": 2e6, "monthly_burn": 1.0e6, "shares_t0": 110e6, "shares_t1": 100e6,
                 "curr_burn": 4.0e6, "prev_burn": 1.0e6, "enterprise_value": 80e6, "sga_expense": 1.5e6}
        s = arch.valuation_summary(_aga_payload(cfg, financials=dirty), regime_vector=NEUTRAL_REGIME)
        self.assertLess(s["forensic_penalty"], 1.0)
        self.assertAlmostEqual(s["intrinsic_after_forensic"],
                               s["blended_intrinsic"] * s["forensic_penalty"], delta=1e-3)


# --------------------------------------------------------------------------- #
#  Shared math helpers (parity with the engine primitives)
# --------------------------------------------------------------------------- #
class TestMathHelpers(unittest.TestCase):
    def test_technical_quality_monotonic_and_clamped(self):
        cfg = _cfg()
        self.assertGreater(technical_quality(cfg, "red_mountain")["tq"], technical_quality(cfg, "mogollon")["tq"])
        for proj in cfg["technical_quality"]["projects"]:
            tq = technical_quality(cfg, proj)["tq"]
            self.assertGreaterEqual(tq, cfg["technical_quality"]["tq_min"])
            self.assertLessEqual(tq, cfg["technical_quality"]["tq_max"])

    def test_option_premium_coherent_and_vol_sensitive(self):
        cfg = _cfg()
        lo = option_premium(cfg, 75.6, 25.6, 0.20, 2.1, stage="explorer")["pi_opt"]
        hi = option_premium(cfg, 75.6, 25.6, 0.45, 2.1, stage="explorer")["pi_opt"]
        self.assertGreaterEqual(hi, lo)
        self.assertGreaterEqual(lo, 0.0)
        ex = option_premium(cfg, 75.6, 25.6, 0.45, -0.5, stage="explorer")["pi_opt"]
        pr = option_premium(cfg, 75.6, 25.6, 0.45, -0.5, stage="producer")["pi_opt"]
        self.assertGreaterEqual(ex, pr)                          # stage decay

    def test_capital_discount_live_operating_point(self):
        self.assertAlmostEqual(capital_discount_factor(_cfg(), 4.99), 0.8808, delta=0.01)

    def test_spot_linked_decoupled_from_share_price(self):
        self.assertGreater(spot_linked_fair_value(4.82, 1.15, 90.0, 74.8, 1.0),
                           spot_linked_fair_value(4.82, 1.15, 60.0, 74.8, 1.0))
        self.assertEqual(spot_linked_fair_value(0.0, 1.15, 90.0, 74.8, 1.0), 0.0)

    def test_pre_revenue_scoring_primitives(self):
        self.assertEqual(AssetArchetype.runway_months(20e6, 1e6), 20.0)
        self.assertEqual(AssetArchetype.runway_months(20e6, 0.0), float("inf"))
        self.assertAlmostEqual(AssetArchetype.cash_burn_acceleration(3e6, 1e6, 100e6), 0.02)
        self.assertAlmostEqual(AssetArchetype.dilution_velocity(110e6, 100e6), 0.40)   # 10% QoQ -> 40%/yr


# --------------------------------------------------------------------------- #
#  Polymorphic router — registration, fail-fast, tag/score routing, versioning
# --------------------------------------------------------------------------- #
class TestPolymorphicRouter(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()

    def test_register_and_value(self):
        router = PolymorphicRouter(self.cfg)
        router.register_asset("AGA.V", OptionConvexityArchetype("AGA.V", self.cfg))
        s = router.get_valuation("AGA.V", _aga_payload(self.cfg), NEUTRAL_REGIME)
        self.assertEqual(s["archetype"], "option_convexity")
        self.assertGreater(s["blended_intrinsic"], 0.0)

    def test_unregistered_ticker_fails_fast(self):
        router = PolymorphicRouter(self.cfg)
        with self.assertRaises(TickerNotRegisteredError):
            router.get_valuation("NOPE.X", {}, NEUTRAL_REGIME)
        with self.assertRaises(TickerNotRegisteredError):
            router.lifecycle_history("NOPE.X")

    def test_register_rejects_non_archetype(self):
        router = PolymorphicRouter(self.cfg)
        with self.assertRaises(ArchetypeConfigError):
            router.register_asset("BAD", object())
        with self.assertRaises(ArchetypeConfigError):
            router.register_archetype_class("bad", object)

    def test_tag_based_routing(self):
        router = PolymorphicRouter(self.cfg)
        router.register_archetype_class("asset_light_yield", AssetLightYieldArchetype)
        router.register_tag_rule("royalty", "asset_light_yield")
        # unregistered ticker, but its payload carries the routing tag
        arch = router.resolve("NEWROY.TO", {"tags": ["royalty"]})
        self.assertIsInstance(arch, AssetLightYieldArchetype)

    def test_score_threshold_routing(self):
        router = PolymorphicRouter(self.cfg)
        router.register_archetype_class("option_convexity", OptionConvexityArchetype)
        # pre-revenue names (very low revenue) route to Option Convexity
        router.register_score_rule("annual_revenue_musd", 0.0, 1.0, "option_convexity")
        self.assertIsInstance(router.resolve("PREREV.V", {"annual_revenue_musd": 0.0}), OptionConvexityArchetype)
        with self.assertRaises(TickerNotRegisteredError):
            router.resolve("BIGREV", {"annual_revenue_musd": 500.0})   # outside band -> no route

    def test_ticker_mapping_wins_over_rules(self):
        router = PolymorphicRouter(self.cfg)
        router.register_archetype_class("asset_light_yield", AssetLightYieldArchetype)
        router.register_tag_rule("explorer", "asset_light_yield")
        router.register_asset("AGA.V", OptionConvexityArchetype("AGA.V", self.cfg))
        self.assertIsInstance(router.resolve("AGA.V", {"tags": ["explorer"]}), OptionConvexityArchetype)

    def test_historical_lifecycle_versioning(self):
        router = PolymorphicRouter(self.cfg)
        router.register_asset("AGA.V", OptionConvexityArchetype("AGA.V", self.cfg), label="explorer")
        router.migrate_asset("AGA.V", CommodityCyclicalArchetype("AGA.V", self.cfg),
                             effective=date(2028, 1, 1), label="producer")
        self.assertEqual(len(router.lifecycle_history("AGA.V")), 2)
        self.assertIsInstance(router.resolve("AGA.V", as_of=date(2026, 6, 1)), OptionConvexityArchetype)
        self.assertIsInstance(router.resolve("AGA.V", as_of=date(2029, 1, 1)), CommodityCyclicalArchetype)
        self.assertIsInstance(router.resolve("AGA.V"), CommodityCyclicalArchetype)   # latest
        early = router.get_valuation("AGA.V", _aga_payload(self.cfg), NEUTRAL_REGIME, as_of=date(2026, 6, 1))
        self.assertEqual(early["archetype"], "option_convexity")
        self.assertEqual(early["lifecycle_versions"], 2)

    def test_migrate_requires_existing_ticker(self):
        router = PolymorphicRouter(self.cfg)
        with self.assertRaises(TickerNotRegisteredError):
            router.migrate_asset("GHOST", OptionConvexityArchetype("GHOST", self.cfg), effective=date(2030, 1, 1))


# --------------------------------------------------------------------------- #
#  build_default_router + anchor 60/15/15/10 bench + correlation foundation
# --------------------------------------------------------------------------- #
class TestDefaultRouterAndAnchorBench(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()
        self.router = build_default_router(self.cfg)

    def test_routes_every_portfolio_name(self):
        # every RESOURCE-lane name routes; conventional-lane entries (lane guard, 2026-08-02:
        # CEG/CEGS) are deliberately NOT in the resource router — dual_sided prices them instead.
        import dual_sided
        pm = self.cfg["portfolio_metadata"]
        names = {k for k in pm if not str(k).startswith("_")
                 and not dual_sided.is_conventional(k, pm)}
        self.assertEqual(set(self.router.registered_tickers()), names)
        self.assertEqual(self.router.resolve("AGA.V").name, "option_convexity")
        # GMX.TO (Globex Mining) is the diversified royalty/holdco ballast — it shares the
        # asset-light royalty tailwind with GROY; its metal differentiation rides
        # commodity_regime in the T-pillar, not the archetype.
        # (URC.TO removed 2026-07-31: config-only, never actually held — see remove_holding.)
        self.assertEqual(self.router.resolve("GMX.TO").name, "asset_light_yield")
        self.assertEqual(self.router.resolve("GROY").name, "asset_light_yield")

    def test_type_fallback_when_no_explicit_archetype(self):
        cfg = _cfg()
        cfg["portfolio_metadata"]["ZZZ.V"] = {"type": "explorer", "stage": "PEA"}
        self.assertEqual(build_default_router(cfg).resolve("ZZZ.V").name, "option_convexity")

    def test_unknown_type_is_skipped_not_guessed(self):
        cfg = _cfg()
        cfg["portfolio_metadata"]["WUT.V"] = {"type": "totally_unknown_type"}
        self.assertNotIn("WUT.V", build_default_router(cfg).registered_tickers())

    def test_anchor_barbell_all_names_value_sanely(self):
        payloads = {
            "AGA.V": _aga_payload(self.cfg),
            "GROY": _groy_payload(self.cfg, "USD"),
            "GMX.TO": {"currency": "CAD", "shares_out": 120e6, "macro": dict(MACRO),
                       "annual_production_oz": 4_000_000, "aisc": 18.0,
                       "financials": {"sloan_cfo": 0.02, "sloan_bs": 0.03, "net_debt": 50e6, "ebitda": 80e6,
                                      "shares_t0": 120e6, "shares_t1": 121e6}},
        }
        regime = (0.4, 0.0, 0.2, 0.3, 0.0)
        weights = {"AGA.V": 0.60, "GROY": 0.24, "GMX.TO": 0.16}
        book = 0.0
        for ticker, data in payloads.items():
            s = self.router.get_valuation(ticker, data, regime)
            self.assertGreater(s["blended_intrinsic"], 0.0, ticker)
            self.assertAlmostEqual(sum(s["weights"].values()), 1.0, places=6, msg=ticker)
            self.assertIn(s["data_quality"], ("full", "degraded"), ticker)
            self.assertEqual(s["base_currency"], "CAD", ticker)
            book += weights[ticker] * s["intrinsic_after_forensic"]
        self.assertGreater(book, 0.0)

    def test_correlation_groups_seed_cross_archetype_sizing(self):
        groups = self.router.correlation_groups()
        # every RESOURCE anchor name loads on silver_beta -> one shared risk-factor group.
        # Conventional-lane names (CEG) are excluded by design — their independence from the
        # spear is the point, and correlation_monitor tracks it separately (lane-aware drift).
        self.assertIn("silver_beta", groups)
        import dual_sided
        pm = self.cfg["portfolio_metadata"]
        names = {k for k in pm if not str(k).startswith("_")
                 and not dual_sided.is_conventional(k, pm)}
        self.assertEqual(set(groups["silver_beta"]), names)

    def test_risk_factor_exposure_normalized(self):
        s = self.router.get_valuation("GROY", _groy_payload(self.cfg, "USD"), NEUTRAL_REGIME)
        self.assertAlmostEqual(sum(s["risk_factor_exposure"].values()), 1.0, places=2)
        self.assertTrue(set(s["tags"]))                          # tags surfaced for routing/UX

    def test_summary_is_fully_serializable(self):
        json.dumps(self.router.get_valuation("AGA.V", _aga_payload(self.cfg), NEUTRAL_REGIME))


# --------------------------------------------------------------------------- #
#  Commodity spot framing — regression guard for the 5000%-upside bug
# --------------------------------------------------------------------------- #
class TestCommoditySpotFraming(unittest.TestCase):
    """The ballast market leg scales fair value by (spot_now / spot_ref). The config spot_ref is
    SILVER-framed (~75), so feeding a non-silver live spot (gold ~4500) into that ratio manufactures
    a ~60x phantom fair value — the cause of GROY's spurious 5000% upside. _commodity_spot must
    return a value in the SAME frame as spot_ref: live for silver, NEUTRAL (== spot_ref) otherwise."""

    DATA = {"spot_ref": 74.8, "macro": {"spot_ag": 30.5, "gold": 4472.0}}

    def test_gold_does_not_bleed_the_gold_price_into_a_silver_frame(self):
        # the bug: gold returned ~4472 over a 74.8 spot_ref -> 60x. Fixed: returns spot_ref (neutral).
        self.assertEqual(_commodity_spot(self.DATA, "gold"), 74.8)

    def test_uranium_and_diversified_are_neutral_too(self):
        for c in ("uranium", "diversified", "holdco"):
            self.assertEqual(_commodity_spot(self.DATA, c), 74.8, c)

    def test_none_commodity_defaults_to_silver(self):
        self.assertEqual(_commodity_spot(self.DATA, None), 30.5)   # default frame is silver (live)

    def test_silver_is_live_linked_in_frame(self):
        self.assertEqual(_commodity_spot(self.DATA, "silver"), 30.5)

    def test_neutral_spot_yields_a_factor_of_one(self):
        # the whole point: a non-silver name's market leg is ref*mult, not a blown-up multiple
        spot_now = _commodity_spot(self.DATA, "gold")
        fv = spot_linked_fair_value(ref_price=3.13, base_mult=1.15, spot_now=spot_now,
                                    spot_ref=74.8, spot_beta=1.0)
        self.assertAlmostEqual(fv, 3.13 * 1.15, places=6)       # factor == 1.0, no phantom upside

    def test_sourced_nav_drives_a_sane_ballast_intrinsic(self):
        # NO-HARDCODE path: a sourced book/NAV per share anchors BOTH legs; the intrinsic tracks
        # filings, and a USD royalty trading ~1.5 is nowhere near a 50x intrinsic.
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg, fx_rates={"USD": 1.38})
        data = _groy_payload(cfg, "USD", book_value_per_share=3.13, ref_price=3.13,
                             commodity="gold", spot_ref=74.8)
        s = arch.valuation_summary(data, regime_vector=NEUTRAL_REGIME)
        # native-USD intrinsic should sit within a sane band of the sourced book value, not 50x it
        usd_intrinsic = s["blended_intrinsic"] / 1.38
        self.assertLess(usd_intrinsic, 3.13 * 3.0, "ballast intrinsic must not balloon off-frame")
        self.assertGreater(usd_intrinsic, 0.0)


# --------------------------------------------------------------------------- #
#  Sub-archetype taxonomy — the 3rd axis (finer sort WITHIN an archetype)
# --------------------------------------------------------------------------- #
class TestSubArchetypeTaxonomy(unittest.TestCase):
    def test_every_sub_points_at_a_real_core_archetype(self):
        for name, sub in SUBARCHETYPE_DNA.items():
            self.assertEqual(sub.name, name)
            self.assertIn(sub.parent, ARCHETYPE_DNA, f"{name} -> {sub.parent}")

    def test_overlay_ships_inert_identity(self):
        # the safe default: NO sub carries weight/confidence deltas yet (display + correlation only)
        for sub in SUBARCHETYPE_DNA.values():
            self.assertEqual(dict(sub.weight_delta), {}, sub.name)
            self.assertEqual(dict(sub.confidence_delta), {}, sub.name)

    def test_compose_weights_is_identity_with_inert_or_missing_overlay(self):
        core = {"cost": 0.05, "market": 0.25, "income": 0.70}
        self.assertEqual(compose_leg_weights(core, None), core)
        self.assertEqual(compose_leg_weights(core, subarchetype_dna("nsr_royalty")), core)

    def test_compose_weights_renormalizes_when_a_delta_is_earned(self):
        # forward-looking: once a delta exists, weights shift but still sum to 1
        sub = SubArchetypeDNA("x", "asset_light_yield", "x", weight_delta={"market": 0.10, "income": -0.10})
        w = compose_leg_weights({"cost": 0.05, "market": 0.25, "income": 0.70}, sub)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=6)
        self.assertGreater(w["market"], 0.25)

    def test_subarchetypes_for_groups_by_parent(self):
        royalties = {d.name for d in subarchetypes_for("asset_light_yield")}
        self.assertIn("nsr_royalty", royalties)
        self.assertIn("royalty_generator_holdco", royalties)        # the Globex-style holdco
        self.assertNotIn("grassroots", royalties)                   # that's an explorer sub

    def test_summary_surfaces_sub_and_sector_tags_without_moving_intrinsic(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg, fx_rates={"USD": 1.38})
        plain = arch.valuation_summary(_groy_payload(cfg, "USD"), regime_vector=NEUTRAL_REGIME)
        tagged = arch.valuation_summary(
            _groy_payload(cfg, "USD", subarchetype="nsr_royalty", sector_tags=["Au", "royalty"]),
            regime_vector=NEUTRAL_REGIME)
        self.assertEqual(tagged["subarchetype"], "nsr_royalty")
        self.assertEqual(tagged["subarchetype_parent"], "asset_light_yield")
        self.assertIn("Au", tagged["sector_tags"])
        # identity overlay: tagging changes NOTHING about the valuation
        self.assertEqual(tagged["blended_intrinsic"], plain["blended_intrinsic"])
        self.assertIsNone(plain["subarchetype"])

    def test_parent_mismatch_is_flagged_not_crashed(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg)
        # a "grassroots" (explorer) sub on a royalty is a config smell -> warning, no crash
        s = arch.valuation_summary(_groy_payload(cfg, "USD", subarchetype="grassroots"),
                                   regime_vector=NEUTRAL_REGIME)
        self.assertTrue(any("grassroots" in w and "parent" in w for w in s["warnings"]))

    def test_book_names_carry_distinct_royalty_subtypes(self):
        # the user's complaint resolved at the sub-axis: GMX (generator holdco) != GROY (NSR)
        cfg = _cfg()
        pm = cfg["portfolio_metadata"]
        self.assertEqual(pm["GROY"]["subarchetype"], "nsr_royalty")
        self.assertEqual(pm["GMX.TO"]["subarchetype"], "royalty_generator_holdco")
        self.assertNotEqual(pm["GROY"]["subarchetype"], pm["GMX.TO"]["subarchetype"])

    def test_config_subarchetypes_are_registered_and_parented_right(self):
        cfg = _cfg()
        for tkr, pm in cfg["portfolio_metadata"].items():
            if str(tkr).startswith("_"):
                continue
            sub = pm.get("subarchetype")
            if not sub:
                continue
            dna = subarchetype_dna(sub)
            self.assertIsNotNone(dna, f"{tkr}: unknown subarchetype {sub}")
            self.assertEqual(dna.parent, pm.get("archetype"),
                             f"{tkr}: sub {sub} parent {dna.parent} != archetype {pm.get('archetype')}")

    def test_taxonomy_in_sync_with_asymmetry_mirror(self):
        import asymmetry_rating
        for parent, names in asymmetry_rating.NICHE_TAGS.items():
            canonical = {d.name for d in subarchetypes_for(parent)}
            self.assertEqual(set(names), canonical, f"mirror drift for {parent}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
