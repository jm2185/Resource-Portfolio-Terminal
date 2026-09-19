"""
Phase 5 — Polymorphic Archetype Factory test suite.

Pure-stdlib (unittest only) so it runs anywhere, including environments where the
heavy `engine.py` dependencies (numpy / yfinance / fastapi) are absent. Covers the
abstract contract, the metadata DNA registry, all six concrete archetypes, FX
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
    AssetLightYieldArchetype, PureMacroDeltaArchetype, ContractedCyclicalArchetype,
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
            self.assertIn(inst.DNA.regime_index, range(6))
            self.assertIn(inst.DNA.regime_tilt_leg, ("cost", "market", "income"))

    def test_dna_registry_codes_and_indices(self):
        self.assertEqual(len(ARCHETYPE_DNA), 6)
        self.assertEqual([d.code for d in ARCHETYPE_DNA.values()], ["I", "II", "III", "IV", "V", "VI"])
        self.assertEqual(sorted(d.regime_index for d in ARCHETYPE_DNA.values()), [0, 1, 2, 3, 4, 5])

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
        # every RESOURCE-lane name routes; non-resource lanes (lane guard, 2026-08-02:
        # CEG/CEGS conventional; exited 2026-09-19) are deliberately NOT in the resource
        # router — dual_sided priced the conventional sleeve while it was held.
        import dual_sided
        pm = self.cfg["portfolio_metadata"]
        names = {k for k in pm if not str(k).startswith("_")
                 and dual_sided.lane_of(k, pm) == "resource"}
        self.assertEqual(set(self.router.registered_tickers()), names)
        self.assertEqual(self.router.resolve("AGA.V").name, "option_convexity")
        # GMX.TO removed 2026-09-19: exited for capital efficiency in favour of
        # satellite plays (confirmed by operator; see SPEAR_STATUS.md). The URC.TO
        # removal precedent (2026-07-31) applies: exited names leave the suite.
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
        # GMX.TO removed 2026-09-19 (exited): the anchor pair is AGA.V/GROY,
        # weights renormalized to the survivors.
        payloads = {
            "AGA.V": _aga_payload(self.cfg),
            "GROY": _groy_payload(self.cfg, "USD"),
        }
        regime = (0.4, 0.0, 0.2, 0.3, 0.0)
        weights = {"AGA.V": 0.60 / 0.84, "GROY": 0.24 / 0.84}
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
        # names whose archetype DNA loads on silver_beta share one risk-factor group.
        # Conventional-lane names (CEG) are excluded by design — their independence from the
        # spear is the point, and correlation_monitor tracks it separately (lane-aware drift).
        # Contracted cyclicals (TDW/DHT) load on energy risk factors, not silver_beta.
        self.assertIn("silver_beta", groups)
        silver_names = {t for t in self.router.registered_tickers()
                        if "silver_beta" in self.router.resolve(t).DNA.risk_factor_tags}
        self.assertEqual(set(groups["silver_beta"]), silver_names)
        self.assertEqual(set(groups["dayrate_cycle"]), {"DHT", "TDW"})

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
        # the user's complaint resolved at the sub-axis: GMX (generator holdco) != GROY (NSR).
        # GMX.TO exited 2026-09-19 -- the GROY half of the distinction remains pinned.
        cfg = _cfg()
        pm = cfg["portfolio_metadata"]
        self.assertEqual(pm["GROY"]["subarchetype"], "nsr_royalty")
        self.assertNotIn("GMX.TO", pm)

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


# --------------------------------------------------------------------------- #
#  PEA-NAV income leg (BRC.V 2026-09-19)
# --------------------------------------------------------------------------- #
class TestPeaNavLeg(unittest.TestCase):
    def setUp(self):
        from archetypes import pea_nav_ps as _pnp
        self.pea_nav_ps = _pnp
        self.cfg = _cfg()
        self.block = self.cfg["pea_nav_by_ticker"]["BRC.V"]
        self.shares = 375280000.0

    def test_reported_grid_cells_reproduce(self):
        # Exact company-published cells: (31 Ag, 2700 Au) -> US$437M; (66.90, 4554.04) -> US$1,555M
        _, m1 = self.pea_nav_ps(self.block, 31.0, 2700.0, "base", self.shares, 1.39)
        self.assertAlmostEqual(m1["npv_usd_m"], 437.0, places=6)
        self.assertFalse(m1["extrapolated_beyond_company_grid"])
        _, m2 = self.pea_nav_ps(self.block, 66.90, 4554.04, "base", self.shares, 1.39)
        self.assertAlmostEqual(m2["npv_usd_m"], 1555.0, places=6)

    def test_monotone_in_both_metals(self):
        lo, _ = self.pea_nav_ps(self.block, 40.0, 3000.0, "base", self.shares, 1.39)
        hi_ag, _ = self.pea_nav_ps(self.block, 60.0, 3000.0, "base", self.shares, 1.39)
        hi_au, _ = self.pea_nav_ps(self.block, 40.0, 4200.0, "base", self.shares, 1.39)
        self.assertGreater(hi_ag, lo)
        self.assertGreater(hi_au, lo)

    def test_scenario_ordering_and_assumptions(self):
        # bear < base < bull per share; bull extrapolates beyond the company grid and says so
        bear, mb = self.pea_nav_ps(self.block, 46.59, 3097.0, "bear", self.shares, 1.39)
        base, _ = self.pea_nav_ps(self.block, 66.56, 4425.0, "base", self.shares, 1.39)
        bull, mg = self.pea_nav_ps(self.block, 86.53, 5752.0, "bull", self.shares, 1.39)
        self.assertLess(bear, base)
        self.assertLess(base, bull)
        self.assertTrue(mg["extrapolated_beyond_company_grid"])
        self.assertFalse(mb["extrapolated_beyond_company_grid"])
        self.assertGreater(mg["p_nav"], 0.0)
        # spot base-case anchor: ~C$1.02/share at ~US$66.5 Ag (hand-verified 2026-09-19)
        self.assertAlmostEqual(base, 1.0196, delta=0.01)

    def test_malformed_block_degrades_to_zero(self):
        ps, meta = self.pea_nav_ps({}, 60.0, 4000.0, "base", self.shares, 1.39)
        self.assertEqual(ps, 0.0)
        self.assertIn("error", meta)
        ps2, _ = self.pea_nav_ps(self.block, 60.0, 4000.0, "base", 0.0, 1.39)
        self.assertEqual(ps2, 0.0)

    def test_brc_weights_override_and_income_confidence(self):
        arch = OptionConvexityArchetype("BRC.V", self.cfg)
        w = arch.weights()
        self.assertAlmostEqual(w["cost"], 0.25)
        self.assertAlmostEqual(w["market"], 0.35)
        self.assertAlmostEqual(w["income"], 0.40)
        # AGA.V (no PEA block) keeps DNA weights and a zero income leg
        aga = OptionConvexityArchetype("AGA.V", self.cfg)
        self.assertEqual(aga.weights()["income"], 0.00)
        self.assertEqual(aga.calculate_income_basis({"macro": {}}, NEUTRAL_REGIME), 0.0)

    def test_brc_income_leg_positive_with_live_macro(self):
        arch = OptionConvexityArchetype("BRC.V", self.cfg)
        data = {"shares_out": self.shares, "currency": "CAD",
                "macro": {"spot_ag": 66.56, "gsr": 66.48, "real_yield": 2.0,
                          "silver_vol": 0.30, "capital_discount": 0.88},
                "aisc": 17.44}
        inc = arch.calculate_income_basis(data, NEUTRAL_REGIME)
        self.assertGreater(inc, 0.5)   # ~C$1.02 at ~US$66.5 Ag
        self.assertLess(inc, 2.0)
        conf = arch.assess_confidence("income", inc, data, {})
        self.assertGreater(conf, 0.0)

    def test_market_leg_excludes_mine_plan_ounces(self):
        arch = OptionConvexityArchetype("BRC.V", self.cfg)
        data = {"shares_out": self.shares, "currency": "CAD",
                "macro": {"spot_ag": 66.56, "gsr": 66.48, "real_yield": 2.0,
                          "silver_vol": 0.30, "capital_discount": 0.88},
                "aisc": 17.44}
        comps = {"peer_ev_oz": 1.37}
        arch.calculate_market_basis(data, comps)
        scale = arch._breakdown["market"]["pea_mine_plan_excluded_scale"]
        # (123.1M - 89.6M) / 123.1M — the PEA mine plan is DCF'd in the income leg
        self.assertAlmostEqual(scale, (123.1 - 89.6) / 123.1, places=4)


# --------------------------------------------------------------------------- #
#  Self-funded growth torque (commodity_cyclical income leg)
# --------------------------------------------------------------------------- #
class TestSelfFundedGrowthTorque(unittest.TestCase):
    def _ag_data(self, spot=66.56):
        return {"shares_out": 492.66e6, "currency": "USD",
                "annual_production_oz": 15.05e6, "aisc": 28.23,
                "macro": {"spot_ag": spot, "real_yield": 2.0, "silver_vol": 0.30}}

    def _ag_cfg(self):
        cfg = _cfg()
        cfg.setdefault("self_funded_growth", {})["AG"] = {
            "reinvestment_rate": 0.075, "discovery_cost_per_oz": 8.0, "p_discovery": 0.50}
        cfg["project_catalysts"] = {}  # isolate the growth engine; catalysts covered separately
        return cfg

    def test_inert_without_config(self):
        # No self_funded_growth block -> static margin capitalization, but the
        # torque metric is still surfaced (pure function of sourced inputs).
        arch = CommodityCyclicalArchetype("GMX.TO", _cfg())
        data = self._ag_data()
        v = arch.calculate_income_basis(data, NEUTRAL_REGIME)
        m = 66.56 - 28.23
        self.assertAlmostEqual(v, 15.05e6 * m * 6.0 / 492.66e6 * arch.fx_rates["USD"], places=2)
        bd = arch._breakdown["income"]
        self.assertNotIn("growth_uplift_years", bd)
        # torque = prod * years / shares, FX-normalized to CAD
        self.assertAlmostEqual(bd["torque_ps_per_dollar_ag"], 15.05e6 * 6.0 / 492.66e6 * arch.fx_rates["USD"], places=3)
        self.assertGreater(bd["torque_elasticity"], 1.0)   # operating leverage > 1

    def test_growth_uplift_math(self):
        arch = CommodityCyclicalArchetype("AG", self._ag_cfg())
        data = self._ag_data()
        v = arch.calculate_income_basis(data, NEUTRAL_REGIME)
        m = 66.56 - 28.23
        k = 0.075 * 0.50 / 8.0
        uplift = k * m
        base = 15.05e6 * m * 10.0 / 492.66e6   # AG per-ticker override: 10y minimum
        self.assertAlmostEqual(v, (base + 15.05e6 * m * uplift / 492.66e6) * arch.fx_rates["USD"], places=2)
        bd = arch._breakdown["income"]
        self.assertAlmostEqual(bd["growth_uplift_years"], uplift, places=4)
        # torque is convex in the margin: prod * (Y + 2*k*m) / shares
        self.assertAlmostEqual(bd["torque_ps_per_dollar_ag"],
                               15.05e6 * (10.0 + 2.0 * uplift) / 492.66e6 * arch.fx_rates["USD"], places=3)
        plain = CommodityCyclicalArchetype("GMX.TO", _cfg()).calculate_income_basis(
            self._ag_data(), NEUTRAL_REGIME)
        self.assertGreater(v, plain)   # self-funded growth strictly accretes

    def test_torque_convex_in_silver(self):
        # At higher silver the growth engine adds more ounces AND each ounce is
        # worth more margin: torque rises with the margin (the 2*k*m term).
        arch = CommodityCyclicalArchetype("AG", self._ag_cfg())
        lo = arch.calculate_income_basis(self._ag_data(spot=50.0), NEUTRAL_REGIME)
        t_lo = arch._breakdown["income"]["torque_ps_per_dollar_ag"]
        hi = arch.calculate_income_basis(self._ag_data(spot=90.0), NEUTRAL_REGIME)
        t_hi = arch._breakdown["income"]["torque_ps_per_dollar_ag"]
        self.assertGreater(t_hi, t_lo)
        self.assertGreater(hi, lo)

    def test_malformed_config_degrades_inert(self):
        for bad in ({"reinvestment_rate": 1.5, "discovery_cost_per_oz": 8.0, "p_discovery": 0.5},
                    {"reinvestment_rate": 0.075, "discovery_cost_per_oz": -1.0, "p_discovery": 0.5},
                    {"reinvestment_rate": 0.075},
                    "not-a-dict"):
            cfg = _cfg()
            cfg.setdefault("self_funded_growth", {})["AG"] = bad
            cfg["project_catalysts"] = {}  # isolate the growth engine
            arch = CommodityCyclicalArchetype("AG", cfg)
            v = arch.calculate_income_basis(self._ag_data(), NEUTRAL_REGIME)
            m = 66.56 - 28.23
            # malformed growth config -> inert, but the 10y per-ticker override still applies
            self.assertAlmostEqual(v, 15.05e6 * m * 10.0 / 492.66e6 * arch.fx_rates["USD"], places=2)
            self.assertNotIn("growth_uplift_years", arch._breakdown["income"])


# --------------------------------------------------------------------------- #
#  Scenario band (commodity_cyclical)
# --------------------------------------------------------------------------- #
class TestCyclicalScenarioBand(unittest.TestCase):
    def _ag_summary(self, cfg=None, **over):
        cfg = cfg if cfg is not None else _cfg()
        arch = CommodityCyclicalArchetype("AG", cfg)
        data = {"shares_out": 492.66e6, "currency": "USD",
                "annual_production_oz": 15.05e6, "aisc": 28.23,
                "ref_price": 19.84, "spot_ref": 66.3, "base_mult": 1.20, "spot_beta": 1.35,
                "book_value_per_share": 8.5,
                "macro": {"spot_ag": 66.56, "real_yield": 2.0, "silver_vol": 0.30},
                "financials": {}}
        data.update(over)
        return arch.valuation_summary(data, regime_vector=NEUTRAL_REGIME)

    def test_band_anchors_and_orders(self):
        s = self._ag_summary()
        sc = s["scenarios"]
        self.assertIsNotNone(sc)
        # base re-runs the same legs: anchors exactly to the published intrinsic
        self.assertAlmostEqual(sc["base"], s["intrinsic_after_forensic"], places=4)
        self.assertGreater(sc["bull"], sc["base"])
        self.assertLess(sc["bear"], sc["base"])
        self.assertGreater(sc["bear"], 0.0)
        # upside is fatter than downside: margin^2 growth + spot_beta convexity
        self.assertGreater(sc["bull"] - sc["base"], sc["base"] - sc["bear"])

    def test_tornado_isolates_growth_slice(self):
        s = self._ag_summary()
        t = s["scenarios"]["tornado"]
        self.assertGreater(t["silver"], 0.0)
        # growth slice in final units = leg slice x income weight x penalty
        w = s["weights"]["income"]
        pen = s["forensic_penalty"]
        arch = CommodityCyclicalArchetype("AG", _cfg())
        data = {"shares_out": 492.66e6, "currency": "USD",
                "annual_production_oz": 15.05e6, "aisc": 28.23,
                "macro": {"spot_ag": 66.56, "real_yield": 2.0, "silver_vol": 0.30}}
        arch.calculate_income_basis(data, NEUTRAL_REGIME)
        g = arch._breakdown["income"]["growth_value_cad"]
        self.assertAlmostEqual(t["self_funded_growth"], g * w * pen, places=3)

    def test_band_without_growth_config(self):
        cfg = _cfg()
        cfg.pop("self_funded_growth", None)
        s = self._ag_summary(cfg)
        sc = s["scenarios"]
        self.assertIsNotNone(sc)
        self.assertGreater(sc["bull"], sc["base"])
        self.assertNotIn("self_funded_growth", sc["tornado"])

    def test_band_none_when_carrier_legs_dead(self):
        arch = CommodityCyclicalArchetype("AG", _cfg())
        sc = arch.scenario_band({"macro": {}}, {}, {"cost": 1.0, "market": 0.0, "income": 0.0},
                                {"cost": 0.5, "market": 0.0, "income": 0.0}, 1.0, 1.0)
        self.assertIsNone(sc)

    def test_shifts_are_labeled(self):
        s = self._ag_summary()
        sh = s["scenarios"]["shifts"]
        self.assertAlmostEqual(sh["spot_up"], 66.56 * 1.30, places=2)
        self.assertAlmostEqual(sh["spot_dn"], 66.56 * 0.70, places=2)
        self.assertAlmostEqual(sh["bull_margin"], 66.56 * 1.30 - 28.23, places=2)
        self.assertIn("margin^2", s["scenarios"]["method"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# Per-ticker margin capitalization years override (AG = 10.0 minimum)
# ---------------------------------------------------------------------------

def _ag_cyc_payload(cfg):
    from archetypes import CommodityCyclicalArchetype
    cfg = dict(cfg); cfg["project_catalysts"] = {}  # isolate capitalization; catalysts covered separately
    arch = CommodityCyclicalArchetype("AG", cfg, fx_rates={"USD": 1.39})
    data = {"shares_out": 492660000, "currency": "USD",
            "annual_production_oz": 15050000, "aisc": 28.23,
            "book_value_per_share": 6.02,
            "macro": {"spot_ag": 66.56, "real_yield": 2.0, "silver_vol": 0.30},
            "financials": {}}
    return arch, data


def test_ag_uses_ten_year_capitalization():
    from archetypes import NEUTRAL_REGIME
    cfg = _cfg()
    arch, data = _ag_cyc_payload(cfg)
    arch.calculate_income_basis(data, NEUTRAL_REGIME)
    bd = arch._breakdown["income"]
    assert bd["years"] == 10.0, bd


def test_ag_ten_year_income_matches_hand_calc():
    from archetypes import NEUTRAL_REGIME
    cfg = _cfg()
    arch, data = _ag_cyc_payload(cfg)
    got = arch.calculate_income_basis(data, NEUTRAL_REGIME)
    # hand calc: prod*margin*(10+growth)/shares * 1.39 ; growth=(0.075*0.5/8)*38.33=0.1797
    margin = 66.56 - 28.23
    expect = 15050000 * margin * (10.0 + 0.1797) / 492660000 * 1.39
    assert abs(got - expect) / expect < 1e-9, (got, expect)


def test_other_tickers_keep_default_six_years():
    from archetypes import NEUTRAL_REGIME, CommodityCyclicalArchetype
    cfg = _cfg()
    arch = CommodityCyclicalArchetype("SNAG", cfg, fx_rates={"USD": 1.39})
    data = {"shares_out": 1e8, "currency": "USD",
            "annual_production_oz": 5e6, "aisc": 20.0,
            "book_value_per_share": 4.0,
            "macro": {"spot_ag": 66.56, "real_yield": 2.0, "silver_vol": 0.30},
            "financials": {}}
    arch.calculate_income_basis(data, NEUTRAL_REGIME)
    assert arch._breakdown["income"]["years"] == 6.0


# ---------------------------------------------------------------------------
# Project-catalyst bucket (restarts / expansions) -- transferable across names
# ---------------------------------------------------------------------------

def _cat_synth_cfg(catalysts):
    cfg = _cfg()
    cfg["project_catalysts"] = catalysts
    cfg["self_funded_growth"] = {}  # isolate the catalyst engine
    return cfg


def _cat_payload(**over):
    data = {"shares_out": 492.66e6, "currency": "USD",
            "annual_production_oz": 15.05e6, "aisc": 28.23,
            "ref_price": 19.84, "spot_ref": 66.3, "base_mult": 1.20, "spot_beta": 1.35,
            "book_value_per_share": 6.02,
            "macro": {"spot_ag": 66.56, "real_yield": 2.0, "silver_vol": 0.30},
            "financials": {}}
    data.update(over)
    return data


class TestProjectCatalysts(unittest.TestCase):
    def test_jerritt_math_matches_hand_calc(self):
        # Real config, AG: Jerritt restart composes exactly with the margin leg.
        cfg = _cfg()
        arch = CommodityCyclicalArchetype("AG", cfg, fx_rates={"USD": 1.39})
        v = arch.calculate_income_basis(_cat_payload(), NEUTRAL_REGIME)
        m = 66.56 - 28.23
        k = 0.079 * 0.50 / 8.0
        cat_net = (6.8e6 * (66.56 - 26.0) * (10.0 - 1.25) - 75e6) * 0.65
        expect = (15.05e6 * m * (10.0 + k * m) + cat_net) / 492.66e6 * 1.39
        self.assertAlmostEqual(v, expect, places=2)
        self.assertAlmostEqual(arch._breakdown["income"]["catalyst_value_cad"],
                               cat_net / 492.66e6 * 1.39, places=2)

    def test_malformed_entries_degrade_inert(self):
        bad = {"TST": [
            {"name": "neg oz", "incremental_oz_per_yr": -5e6, "catalyst_aisc_per_oz": 20.0,
             "capex_remaining": 1e6, "delay_years": 1.0, "p_execution": 0.5},
            {"name": "p>1", "incremental_oz_per_yr": 5e6, "catalyst_aisc_per_oz": 20.0,
             "capex_remaining": 1e6, "delay_years": 1.0, "p_execution": 1.5},
            {"name": "missing aisc", "incremental_oz_per_yr": 5e6,
             "capex_remaining": 1e6, "delay_years": 1.0, "p_execution": 0.5},
            "not-a-dict",
            {"name": "zero p", "incremental_oz_per_yr": 5e6, "catalyst_aisc_per_oz": 20.0,
             "capex_remaining": 1e6, "delay_years": 1.0, "p_execution": 0.0},
        ]}
        arch = CommodityCyclicalArchetype("TST", _cat_synth_cfg(bad), fx_rates={"USD": 1.39})
        self.assertEqual(arch._project_catalysts(), [])
        v = arch.calculate_income_basis(_cat_payload(), NEUTRAL_REGIME)
        m = 66.56 - 28.23                      # TST keeps the default 6-year cap
        self.assertAlmostEqual(v, 15.05e6 * m * 6.0 / 492.66e6 * 1.39, places=2)
        self.assertNotIn("catalyst_value_cad", arch._breakdown["income"])

    def test_missing_block_is_inert(self):
        cfg = _cfg()
        cfg.pop("project_catalysts", None)
        arch = CommodityCyclicalArchetype("AG", cfg, fx_rates={"USD": 1.39})
        self.assertEqual(arch._project_catalysts(), [])
        arch.calculate_income_basis(_cat_payload(), NEUTRAL_REGIME)
        self.assertNotIn("catalyst_value_cad", arch._breakdown["income"])

    def test_catalysts_do_not_leak_across_tickers(self):
        # Transferability: per-ticker lists, archetype-level frame-agnostic code.
        mk = lambda oz: {"name": "x", "incremental_oz_per_yr": oz, "catalyst_aisc_per_oz": 20.0,
                         "capex_remaining": 0.0, "delay_years": 0.0, "p_execution": 1.0}
        cfg = _cat_synth_cfg({"AAA": [mk(1e6)], "BBB": [mk(2e6), mk(3e6)]})
        self.assertEqual(len(CommodityCyclicalArchetype("AAA", cfg)._project_catalysts()), 1)
        self.assertEqual(len(CommodityCyclicalArchetype("BBB", cfg)._project_catalysts()), 2)
        self.assertEqual(CommodityCyclicalArchetype("CCC", cfg)._project_catalysts(), [])
        # AAA's value reflects only its own 1M oz/yr catalyst (default 6-year cap).
        arch = CommodityCyclicalArchetype("AAA", cfg, fx_rates={"USD": 1.39})
        arch.calculate_income_basis(_cat_payload(), NEUTRAL_REGIME)
        self.assertAlmostEqual(arch._breakdown["income"]["catalyst_value_cad"],
                               1e6 * (66.56 - 20.0) * 6.0 / 492.66e6 * 1.39, places=2)

    def test_floored_catalyst_has_no_value_and_no_torque(self):
        cfg = _cat_synth_cfg({"TST": [
            {"name": "underwater", "incremental_oz_per_yr": 5e6, "catalyst_aisc_per_oz": 100.0,
             "capex_remaining": 10e6, "delay_years": 1.0, "p_execution": 0.8}]})
        arch = CommodityCyclicalArchetype("TST", cfg, fx_rates={"USD": 1.39})
        data = _cat_payload()
        v = arch.calculate_income_basis(data, NEUTRAL_REGIME)
        m = 66.56 - 28.23
        self.assertAlmostEqual(v, 15.05e6 * m * 6.0 / 492.66e6 * 1.39, places=2)
        t1 = arch._breakdown["income"]["torque_ps_per_dollar_ag"]
        arch2 = CommodityCyclicalArchetype("TST", _cat_synth_cfg({"TST": []}),
                                           fx_rates={"USD": 1.39})
        arch2.calculate_income_basis(data, NEUTRAL_REGIME)
        self.assertAlmostEqual(t1, arch2._breakdown["income"]["torque_ps_per_dollar_ag"], places=6)

    def test_tornado_carries_catalyst_slice(self):
        cfg = _cfg()
        arch = CommodityCyclicalArchetype("AG", cfg)
        s = arch.valuation_summary(_cat_payload(), regime_vector=NEUTRAL_REGIME)
        t = s["scenarios"]["tornado"]
        self.assertIn("project_catalysts", t)
        self.assertGreater(t["project_catalysts"], 0.0)
        arch2 = CommodityCyclicalArchetype("AG", cfg)
        arch2.calculate_income_basis(_cat_payload(), NEUTRAL_REGIME)
        c = arch2._breakdown["income"]["catalyst_value_cad"]
        # places=2: summary weights are display-rounded (0.49 vs internal 0.49019)
        self.assertAlmostEqual(t["project_catalysts"],
                               c * s["weights"]["income"] * s["forensic_penalty"], places=2)

    def test_catalyst_participates_in_silver_shock(self):
        # AgEq framing: shocked silver carries the catalyst margin (fixed GSR).
        cfg = _cfg()
        s_with = CommodityCyclicalArchetype("AG", cfg).valuation_summary(
            _cat_payload(), regime_vector=NEUTRAL_REGIME)
        cfg2 = _cfg()
        cfg2["project_catalysts"] = {}
        s_without = CommodityCyclicalArchetype("AG", cfg2).valuation_summary(
            _cat_payload(), regime_vector=NEUTRAL_REGIME)
        self.assertGreater(s_with["scenarios"]["bull"], s_without["scenarios"]["bull"])
        self.assertGreater(s_with["scenarios"]["base"], s_without["scenarios"]["base"])
        self.assertGreater(s_with["scenarios"]["tornado"]["silver"],
                           s_without["scenarios"]["tornado"]["silver"])


# --------------------------------------------------------------------------- #
#  Contracted Cyclical (VI) — contracted day-rate asset services (TDW, DHT)
# --------------------------------------------------------------------------- #
def _cc_payload(**over):
    data = {
        "currency": "CAD", "shares_out": 50e6, "net_debt": 0.0,
        "active_units": 200, "utilization": 0.80, "cash_opex_per_day": 10000.0,
        "contracted_rate": 22000.0, "leading_edge_rate": 24000.0,
        "contract_coverage": 0.50, "book_value_per_share": 30.0,
        "financials": {"sloan_cfo": 0.01, "sloan_bs": 0.01, "net_debt": 0.0,
                       "ebitda": 600e6, "shares_t0": 50e6, "shares_t1": 50e6},
    }
    data.update(over)
    return data


def _cc_cfg(**over):
    block = {"cap_years": 5.0, "rate_vol": 0.30, "ev_ebitda": 8.0}
    block.update(over)
    return {"contracted_cyclical": {"TST": block}}


class TestContractedCyclical(unittest.TestCase):
    def setUp(self):
        self.arch = ContractedCyclicalArchetype("TST", _cc_cfg())

    def test_income_leg_matches_hand_calc(self):
        # vessel_days = 200*365*0.8 = 58,400
        # cash = 58400 * (0.5*12000 + 0.5*14000) = 58400 * 13000 = 759.2e6
        # v = 759.2e6 * 5 / 50e6 = 75.92
        v = self.arch.calculate_income_basis(_cc_payload(), NEUTRAL_REGIME)
        self.assertAlmostEqual(v, 75.92, places=2)

    def test_torque_per_1k_day(self):
        self.arch.calculate_income_basis(_cc_payload(), NEUTRAL_REGIME)
        meta = self.arch._breakdown["income"]
        # 200*365*0.8*1000*5/50e6 = 5.84
        self.assertAlmostEqual(meta["torque_ps_per_1k_day"], 5.84, places=2)
        self.assertGreater(meta["torque_elasticity"], 1.0)   # operating leverage

    def test_income_splits_contracted_and_repricing(self):
        self.arch.calculate_income_basis(_cc_payload(), NEUTRAL_REGIME)
        meta = self.arch._breakdown["income"]
        self.assertAlmostEqual(meta["contracted_cash_native"], 58400 * 0.5 * 12000, delta=1.0)
        self.assertAlmostEqual(meta["repricing_cash_native"], 58400 * 0.5 * 14000, delta=1.0)

    def test_cost_floor_uses_fleet_value_when_sourced(self):
        arch = ContractedCyclicalArchetype("TST", _cc_cfg(fleet_value_per_unit=25e6))
        v = arch.calculate_cost_basis(_cc_payload(net_debt=500e6))
        # (200 * 25e6 - 500e6) / 50e6 = 90.0
        self.assertAlmostEqual(v, 90.0, places=2)
        self.assertIn("replacement-cost", arch._breakdown["cost"]["method"])

    def test_cost_falls_back_to_book_with_proxy_flag(self):
        v = self.arch.calculate_cost_basis(_cc_payload())
        self.assertAlmostEqual(v, 30.0, places=2)

    def test_legs_resolve_config_inputs_with_engine_style_payload(self):
        # Regression: the engine's _archetype_payload carries only live fields
        # (price/currency/macro) — per-ticker fundamentals must fall back to the
        # sourced config block via _input, not raise SparseDataError. (2026-09-19:
        # TDW/DHT legs silently degraded live because shares_out/book_value_per_share
        # were read data-only.)
        cfg_block = {"contracted_cyclical": {"TST": {
            "cap_years": 5.0, "rate_vol": 0.30, "ev_ebitda": 8.0,
            "shares_out": 50e6, "net_debt": 0.0, "active_units": 200,
            "utilization": 0.80, "cash_opex_per_day": 10000.0,
            "contracted_rate": 22000.0, "leading_edge_rate": 24000.0,
            "contract_coverage": 0.50, "book_value_per_share": 30.0}}}
        arch = ContractedCyclicalArchetype("TST", cfg_block)
        live_only = {"currency": "CAD", "price": 40.0, "macro": {}, "comps": {},
                     "financials": {}}
        self.assertAlmostEqual(arch.calculate_cost_basis(live_only), 30.0, places=2)
        self.assertAlmostEqual(arch.calculate_income_basis(live_only, NEUTRAL_REGIME),
                               75.92, places=2)
        s = arch.valuation_summary(live_only, regime_vector=NEUTRAL_REGIME)
        self.assertGreater(s["blended_intrinsic"], 0.0)
        self.assertIn("proxy", arch._breakdown["cost"]["method"])

    def test_market_midcycle_ev_ebitda(self):
        v = self.arch.calculate_market_basis(_cc_payload(mid_cycle_ebitda=600e6), {})
        # (600e6 * 8 - 0) / 50e6 = 96.0
        self.assertAlmostEqual(v, 96.0, places=2)

    def test_market_derives_midcycle_from_contracted_book(self):
        # coverage 0.50 >= 50%: contracted rate anchors mid-cycle.
        # mid EBITDA = 200*365*0.80*(22000-10000) = 700.8e6
        # v = 700.8e6 * 8.0 / 50e6 = 112.128
        v = self.arch.calculate_market_basis(_cc_payload(), {})
        self.assertAlmostEqual(v, 112.128, places=2)
        meta = self.arch._breakdown["market"]
        self.assertIn("contracted-book anchor", meta["ebitda_basis"])

    def test_market_explicit_mid_cycle_rate_wins(self):
        arch = ContractedCyclicalArchetype("TST", _cc_cfg(mid_cycle_rate=26000.0))
        v = arch.calculate_market_basis(_cc_payload(), {})
        # 58400 * (26000-10000) = 934.4e6; * 8.0 / 50e6 = 149.504
        self.assertAlmostEqual(v, 149.504, places=2)
        self.assertIn("explicit mid_cycle_rate", arch._breakdown["market"]["ebitda_basis"])

    def test_market_pbook_fallback(self):
        # coverage < 50% with no explicit mid_cycle_rate: derivation degrades,
        # P/Book fallback engages as before.
        v = self.arch.calculate_market_basis(_cc_payload(contract_coverage=0.30),
                                             {"p_book": 1.5})
        self.assertAlmostEqual(v, 45.0, places=2)

    def test_ev_ebitda_mid_preferred_over_forward(self):
        arch = ContractedCyclicalArchetype(
            "TST", _cc_cfg(ev_ebitda_mid=6.0, ev_ebitda=8.0))
        v = arch.calculate_market_basis(_cc_payload(), {})
        # 700.8e6 * 6.0 / 50e6 = 84.096 (mid-cycle multiple, not forward 8.0x)
        self.assertAlmostEqual(v, 84.096, places=2)
        self.assertEqual(arch._breakdown["market"]["multiple_basis"],
                         "mid-cycle multiple input")

    def test_income_deducts_corporate_costs(self):
        # 759.2e6 vessel cash - 100e6 G&A - 50e6 maint = 609.2e6
        # v = 609.2e6 * 5 / 50e6 = 60.92
        v = self.arch.calculate_income_basis(
            _cc_payload(annual_gna=100e6, annual_maint_capex=50e6), NEUTRAL_REGIME)
        self.assertAlmostEqual(v, 60.92, places=2)
        meta = self.arch._breakdown["income"]
        self.assertAlmostEqual(meta["annual_gna_native"], 100e6, delta=1.0)
        self.assertAlmostEqual(meta["annual_maint_capex_native"], 50e6, delta=1.0)
        self.assertIn("G&A", meta["cash_basis"])

    def test_income_zero_deductions_by_default(self):
        # no annual_gna / annual_maint_capex supplied: vessel-gross, as before
        v = self.arch.calculate_income_basis(_cc_payload(), NEUTRAL_REGIME)
        self.assertAlmostEqual(v, 75.92, places=2)
        self.assertIn("vessel-gross", self.arch._breakdown["income"]["cash_basis"])

    def test_scenario_band_dayrate_shock(self):
        data = _cc_payload()
        inc = self.arch.calculate_income_basis(data, NEUTRAL_REGIME)
        legs = {"cost": 30.0, "market": 96.0, "income": inc}
        band = self.arch.scenario_band(data, {}, legs,
                                       {"cost": 0.75, "market": 0.80, "income": 0.75},
                                       1.0, 1.0)
        self.assertGreater(band["bull"], band["base"])
        self.assertGreater(band["base"], band["bear"])
        self.assertAlmostEqual(band["tornado"]["dayrate"], band["bull"] - band["base"], places=3)
        # repricing-only shock: a fully contracted book does not move
        data_full = _cc_payload(contract_coverage=1.0)
        inc_full = self.arch.calculate_income_basis(data_full, NEUTRAL_REGIME)
        band_full = self.arch.scenario_band(
            data_full, {}, {"cost": 30.0, "market": 96.0, "income": inc_full},
            {"cost": 0.75, "market": 0.80, "income": 0.75}, 1.0, 1.0)
        self.assertAlmostEqual(band_full["bull"], band_full["base"], places=6)
        self.assertAlmostEqual(band_full["bear"], band_full["base"], places=6)

    def test_sparse_inputs_raise_per_leg(self):
        with self.assertRaises(SparseDataError):
            self.arch.calculate_income_basis({"shares_out": 50e6}, NEUTRAL_REGIME)
        with self.assertRaises(SparseDataError):
            self.arch.calculate_cost_basis({"shares_out": 50e6})
        with self.assertRaises(SparseDataError):
            self.arch.calculate_market_basis({"shares_out": 50e6}, {})

    def test_malformed_inputs_degrade_inert(self):
        # coverage > 1, negative units: raise, never fabricate
        with self.assertRaises(SparseDataError):
            self.arch.calculate_income_basis(_cc_payload(contract_coverage=1.5), NEUTRAL_REGIME)
        with self.assertRaises(SparseDataError):
            self.arch.calculate_income_basis(_cc_payload(active_units=-5), NEUTRAL_REGIME)

    def test_regime_neutral_until_sixth_coefficient(self):
        arch = ContractedCyclicalArchetype("TST", _cc_cfg())
        self.assertEqual(arch.regime_alpha(NEUTRAL_REGIME), 0.0)
        self.assertAlmostEqual(arch.regime_multiplier(NEUTRAL_REGIME), 1.0, places=6)

    def test_forensic_uses_producer_sieve(self):
        score = self.arch.calculate_forensic_score(
            _cc_payload()["financials"])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 4.0)
        self.assertAlmostEqual(score, 4.0, places=6)   # clean books: all four pass
        self.assertEqual(self.arch._breakdown["forensic"]["sieve"], "contracted_cyclical")

    def test_router_routes_tdw_and_dht(self):
        cfg = _cfg()
        router = build_default_router(cfg)
        self.assertEqual(router.resolve("TDW").name, "contracted_cyclical")
        self.assertEqual(router.resolve("DHT").name, "contracted_cyclical")

    def test_tdw_config_inputs_are_sourced(self):
        cfg = _cfg()
        tdw = cfg["contracted_cyclical"]["TDW"]
        for key in ("active_units", "utilization", "cash_opex_per_day",
                    "contracted_rate", "leading_edge_rate", "contract_coverage"):
            self.assertGreater(tdw[key], 0, f"TDW.{key}")
        self.assertIn("dive", tdw["_source"])

    def test_income_leg_records_dayrate_provenance(self):
        # 2026-09-19: the engine's rate-hunt overlay tags payload["_dayrate_meta"];
        # the income breakdown must carry which print priced the leg (and flag staleness).
        p = _cc_payload(_dayrate_meta={"asof": "2026-09-19", "source": "test:hunt",
                                       "stale_days": 3, "stale": False})
        self.arch.calculate_income_basis(p, NEUTRAL_REGIME)
        b = self.arch._breakdown["income"]
        self.assertEqual(b["rate_asof"], "2026-09-19")
        self.assertEqual(b["rate_source"], "test:hunt")
        self.assertNotIn("rate_note", b)

    def test_income_leg_flags_stale_rate_print(self):
        p = _cc_payload(_dayrate_meta={"asof": "2026-01-01", "source": "test:old",
                                       "stale_days": 90, "stale": True})
        self.arch.calculate_income_basis(p, NEUTRAL_REGIME)
        b = self.arch._breakdown["income"]
        self.assertIn("STALE", b["rate_note"])
