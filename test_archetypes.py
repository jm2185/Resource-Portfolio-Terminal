"""
Phase 5 — Polymorphic Archetype Factory test suite.

Pure-stdlib (unittest only) so it runs anywhere, including environments where the
heavy `engine.py` dependencies (numpy / yfinance / fastapi) are absent. Covers
the abstract contract, all five archetypes, FX normalization, graceful
degradation, the Regime Impact Vector wiring, the confidence-tilted blend, the
forensic sieve, the router (fail-fast + historical lifecycle versioning), and the
anchor 60/15/15/10 test bench wired from the live config.
"""

import json
import unittest
from datetime import date

from archetypes import (
    AssetArchetype, OptionConvexityArchetype, CapitalMarginArchetype,
    CommodityCyclicalArchetype, AssetLightYieldArchetype, PureMacroDeltaArchetype,
    PolymorphicRouter, TickerNotRegisteredError, ArchetypeConfigError,
    build_default_router, technical_quality, option_premium,
    capital_discount_factor, spot_linked_fair_value, ARCHETYPE_REGISTRY,
    NEUTRAL_REGIME,
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


# --------------------------------------------------------------------------- #
#  Abstract contract
# --------------------------------------------------------------------------- #

class TestAbstractContract(unittest.TestCase):
    def test_cannot_instantiate_base(self):
        with self.assertRaises(TypeError):
            AssetArchetype("X")  # ABC with abstract methods

    def test_every_archetype_implements_contract(self):
        cfg = _cfg()
        for name, cls in ARCHETYPE_REGISTRY.items():
            inst = cls("T", cfg)
            for meth in ("calculate_cost_basis", "calculate_market_basis",
                         "calculate_income_basis", "calculate_forensic_score",
                         "valuation_summary", "normalize_fx"):
                self.assertTrue(callable(getattr(inst, meth)), f"{name}.{meth}")
            self.assertIn(inst.REGIME_INDEX, range(5))
            self.assertIn(inst.REGIME_TILT_LEG, ("cost", "market", "income"))

    def test_regime_indices_are_unique_and_complete(self):
        idx = sorted(cls.REGIME_INDEX for cls in ARCHETYPE_REGISTRY.values())
        self.assertEqual(idx, [0, 1, 2, 3, 4])


# --------------------------------------------------------------------------- #
#  Option Convexity (AGA.V)
# --------------------------------------------------------------------------- #

class TestOptionConvexity(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()
        self.arch = OptionConvexityArchetype("AGA.V", self.cfg)

    def test_cost_is_rep_floor(self):
        # REP floor reconstructed by hand from config ~ $0.824/share (cf. PHASE4 doc "cost": 0.82)
        cost = self.arch.calculate_cost_basis(_aga_payload(self.cfg))
        self.assertAlmostEqual(cost, 0.824, delta=0.01)

    def test_triangulation_blend_between_legs(self):
        s = self.arch.valuation_summary(_aga_payload(self.cfg), regime_vector=NEUTRAL_REGIME)
        self.assertAlmostEqual(sum(s["weights"].values()), 1.0, places=6)
        lo, hi = sorted([s["legs"]["cost"], s["legs"]["market"]])
        self.assertLessEqual(lo, s["blended_intrinsic"])
        self.assertLessEqual(s["blended_intrinsic"], hi)
        self.assertEqual(s["legs"]["income"], 0.0)          # explorer income is zero by design
        self.assertEqual(s["data_quality"], "full")         # income weight is 0, so not "degraded"

    def test_market_leg_dominates_and_exceeds_cost(self):
        s = self.arch.valuation_summary(_aga_payload(self.cfg), regime_vector=NEUTRAL_REGIME)
        self.assertGreater(s["legs"]["market"], s["legs"]["cost"])
        self.assertGreater(s["weights"]["market"], s["weights"]["cost"])


# --------------------------------------------------------------------------- #
#  FX normalization (base = CAD)
# --------------------------------------------------------------------------- #

class TestFXNormalization(unittest.TestCase):
    def test_usd_name_scales_by_fx_vs_cad_twin(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg, fx_rates={"USD": 1.38})
        usd = arch.valuation_summary(_groy_payload(cfg, "USD"), regime_vector=(0, 0, 0, 0.0, 0))
        cad = arch.valuation_summary(_groy_payload(cfg, "CAD"), regime_vector=(0, 0, 0, 0.0, 0))
        # Every leg passes through the same FX hook, and the blend is linear in the
        # legs, so the USD valuation must equal the CAD-twin valuation x 1.38
        # (delta accommodates 4dp display rounding of each blended figure).
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
        data = _aga_payload(cfg, comps={})                          # no peer_ev_oz
        s = arch.valuation_summary(data, comps={}, regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["confidence"]["market"], 0.0)
        self.assertEqual(s["weights"]["cost"], 1.0)                 # blend falls back to the cost floor
        self.assertAlmostEqual(s["blended_intrinsic"], s["legs"]["cost"], places=6)
        self.assertEqual(s["data_quality"], "degraded")
        self.assertTrue(any("market" in w for w in s["warnings"]))

    def test_total_sparsity_yields_zero_not_crash(self):
        arch = OptionConvexityArchetype("AGA.V", {})               # empty config, empty data
        s = arch.valuation_summary({}, comps={}, regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["blended_intrinsic"], 0.0)
        self.assertEqual(s["data_quality"], "sparse")
        self.assertEqual(sum(s["weights"].values()), 0.0)

    def test_income_archetype_degrades_when_cashflow_missing(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg)
        data = _groy_payload(cfg, "USD")
        data.pop("annual_cashflow_per_share")
        s = arch.valuation_summary(data, regime_vector=NEUTRAL_REGIME)
        self.assertEqual(s["confidence"]["income"], 0.0)
        self.assertGreater(s["blended_intrinsic"], 0.0)            # cost+market still carry it
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
        # clamp to [-1, 1] and graceful handling of malformed vectors
        self.assertEqual(PureMacroDeltaArchetype("A", cfg).regime_alpha((0, 0, 0, 0, 9.0)), 1.0)
        self.assertEqual(OptionConvexityArchetype("A", cfg).regime_alpha(None), 0.0)
        self.assertEqual(OptionConvexityArchetype("A", cfg).regime_alpha((0.5,)), 0.5)
        self.assertEqual(CapitalMarginArchetype("A", cfg).regime_alpha((0.5,)), 0.0)  # short vector

    def test_positive_alpha_amplifies_negative_fades(self):
        cfg = _cfg()
        arch = AssetLightYieldArchetype("GROY", cfg)
        base = _groy_payload(cfg, "USD")
        up = arch.valuation_summary(base, regime_vector=(0, 0, 0, 1.0, 0))["blended_intrinsic"]
        flat = arch.valuation_summary(base, regime_vector=NEUTRAL_REGIME)["blended_intrinsic"]
        down = arch.valuation_summary(base, regime_vector=(0, 0, 0, -1.0, 0))["blended_intrinsic"]
        self.assertGreater(up, flat)
        self.assertGreater(flat, down)

    def test_overlay_applied_once_to_tilt_leg_only(self):
        cfg = _cfg()
        # income-tilted archetype: only the income leg moves with alpha
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
#  Forensic sieve
# --------------------------------------------------------------------------- #

class TestForensicSieve(unittest.TestCase):
    def test_score_bounds_and_penalty_mapping(self):
        cfg = _cfg()
        arch = OptionConvexityArchetype("AGA.V", cfg)
        clean = {"cash": 20e6, "monthly_burn": 0.5e6, "shares_t0": 100e6, "shares_t1": 100e6,
                 "curr_burn": 1.4e6, "prev_burn": 1.5e6, "enterprise_value": 80e6, "sga_expense": 0.2e6}
        # shares_t0 is the CURRENT (post-raise) count; t0 > t1 => dilution fails (engine convention)
        dirty = {"cash": 2e6, "monthly_burn": 1.0e6, "shares_t0": 110e6, "shares_t1": 100e6,
                 "curr_burn": 4.0e6, "prev_burn": 1.0e6, "enterprise_value": 80e6, "sga_expense": 1.5e6}
        self.assertAlmostEqual(arch.calculate_forensic_score(clean), 4.0, places=6)
        self.assertAlmostEqual(arch.calculate_forensic_score(dirty), 0.0, places=6)
        self.assertAlmostEqual(arch.forensic_penalty(4.0), 1.0, places=6)
        self.assertAlmostEqual(arch.forensic_penalty(0.0), 0.70, places=6)
        self.assertAlmostEqual(arch.forensic_penalty(2.0), 0.85, places=6)

    def test_missing_financials_neutral_default(self):
        cfg = _cfg()
        arch = OptionConvexityArchetype("AGA.V", cfg)
        self.assertAlmostEqual(arch.calculate_forensic_score({}), 2.5, places=6)   # neutral, non-punitive

    def test_passive_vehicle_sieve(self):
        arch = PureMacroDeltaArchetype("PSLV", _cfg())
        clean = {"premium_to_nav": 0.01, "expense_ratio": 0.005, "adv_usd": 50e6, "physically_backed": True}
        self.assertAlmostEqual(arch.calculate_forensic_score(clean), 4.0, places=6)

    def test_forensic_penalty_applies_to_blended(self):
        cfg = _cfg()
        arch = OptionConvexityArchetype("AGA.V", cfg)
        # shares_t0 is the CURRENT (post-raise) count; t0 > t1 => dilution fails (engine convention)
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
        tq_lo = technical_quality(cfg, "mogollon")["tq"]
        tq_hi = technical_quality(cfg, "red_mountain")["tq"]
        self.assertGreater(tq_hi, tq_lo)                            # higher grade/jurisdiction -> higher TQ
        for proj in cfg["technical_quality"]["projects"]:
            tq = technical_quality(cfg, proj)["tq"]
            self.assertGreaterEqual(tq, cfg["technical_quality"]["tq_min"])
            self.assertLessEqual(tq, cfg["technical_quality"]["tq_max"])

    def test_option_premium_coherent_and_vol_sensitive(self):
        cfg = _cfg()
        lo = option_premium(cfg, 75.6, 25.6, 0.20, 2.1, stage="explorer")["pi_opt"]
        hi = option_premium(cfg, 75.6, 25.6, 0.45, 2.1, stage="explorer")["pi_opt"]
        self.assertGreaterEqual(hi, lo)                             # more realized vol -> more convexity
        self.assertGreaterEqual(lo, 0.0)
        # stage decay: explorer >= producer
        ex = option_premium(cfg, 75.6, 25.6, 0.45, -0.5, stage="explorer")["pi_opt"]
        pr = option_premium(cfg, 75.6, 25.6, 0.45, -0.5, stage="producer")["pi_opt"]
        self.assertGreaterEqual(ex, pr)

    def test_capital_discount_live_operating_point(self):
        cd = capital_discount_factor(_cfg(), 4.99)
        self.assertAlmostEqual(cd, 0.8808, delta=0.01)              # cf. ENGINE_DESIGN §6.2

    def test_spot_linked_decoupled_from_share_price(self):
        # fair value depends on commodity spot, never the name's own price
        fv_lo = spot_linked_fair_value(4.82, 1.15, 60.0, 74.8, 1.0)
        fv_hi = spot_linked_fair_value(4.82, 1.15, 90.0, 74.8, 1.0)
        self.assertGreater(fv_hi, fv_lo)
        self.assertEqual(spot_linked_fair_value(0.0, 1.15, 90.0, 74.8, 1.0), 0.0)


# --------------------------------------------------------------------------- #
#  Polymorphic router
# --------------------------------------------------------------------------- #

class TestPolymorphicRouter(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()

    def test_register_and_value(self):
        router = PolymorphicRouter(self.cfg)
        router.register_asset("AGA.V", OptionConvexityArchetype("AGA.V", self.cfg))
        s = router.get_valuation("AGA.V", _aga_payload(self.cfg), regime_vector=NEUTRAL_REGIME)
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

    def test_historical_lifecycle_versioning(self):
        router = PolymorphicRouter(self.cfg)
        # AGA.V begins life as a pre-revenue explorer (Option Convexity) ...
        router.register_asset("AGA.V", OptionConvexityArchetype("AGA.V", self.cfg),
                              label="explorer")
        # ... then graduates to a producing Commodity Cyclical in 2028.
        router.migrate_asset("AGA.V", CommodityCyclicalArchetype("AGA.V", self.cfg),
                             effective=date(2028, 1, 1), label="producer")
        self.assertEqual(len(router.lifecycle_history("AGA.V")), 2)
        # resolution honours as_of
        self.assertIsInstance(router.resolve("AGA.V", as_of=date(2026, 6, 1)), OptionConvexityArchetype)
        self.assertIsInstance(router.resolve("AGA.V", as_of=date(2029, 1, 1)), CommodityCyclicalArchetype)
        self.assertIsInstance(router.resolve("AGA.V"), CommodityCyclicalArchetype)  # latest
        # valuation routes through the as_of-resolved archetype
        early = router.get_valuation("AGA.V", _aga_payload(self.cfg), NEUTRAL_REGIME, as_of=date(2026, 6, 1))
        self.assertEqual(early["archetype"], "option_convexity")
        self.assertEqual(early["lifecycle_versions"], 2)

    def test_migrate_requires_existing_ticker(self):
        router = PolymorphicRouter(self.cfg)
        with self.assertRaises(TickerNotRegisteredError):
            router.migrate_asset("GHOST", OptionConvexityArchetype("GHOST", self.cfg), effective=date(2030, 1, 1))


# --------------------------------------------------------------------------- #
#  build_default_router + the anchor 60/15/15/10 test bench
# --------------------------------------------------------------------------- #

class TestDefaultRouterAndAnchorBench(unittest.TestCase):
    def setUp(self):
        self.cfg = _cfg()
        self.router = build_default_router(self.cfg)

    def test_routes_every_portfolio_name(self):
        self.assertEqual(set(self.router.registered_tickers()),
                         set(self.cfg["portfolio_metadata"]))
        # routing honours the explicit archetype keys in config
        self.assertEqual(self.router.resolve("AGA.V").NAME, "option_convexity")
        self.assertEqual(self.router.resolve("GMX.TO").NAME, "commodity_cyclical")
        self.assertEqual(self.router.resolve("URC.TO").NAME, "asset_light_yield")
        self.assertEqual(self.router.resolve("GROY").NAME, "asset_light_yield")

    def test_type_fallback_when_no_explicit_archetype(self):
        cfg = _cfg()
        cfg["portfolio_metadata"]["ZZZ.V"] = {"type": "explorer", "stage": "PEA"}  # no archetype key
        router = build_default_router(cfg)
        self.assertEqual(router.resolve("ZZZ.V").NAME, "option_convexity")

    def test_unknown_type_is_skipped_not_guessed(self):
        cfg = _cfg()
        cfg["portfolio_metadata"]["WUT.V"] = {"type": "totally_unknown_type"}
        router = build_default_router(cfg)
        self.assertNotIn("WUT.V", router.registered_tickers())     # explicit skip, never a silent guess

    def test_anchor_barbell_all_names_value_sanely(self):
        # The 60/15/15/10 barbell: AGA.V spear + royalty/cyclical ballast. Each
        # name must route, value positive, blend to weights summing to 1, and not
        # collapse to "sparse" given a reasonable payload.
        payloads = {
            "AGA.V": _aga_payload(self.cfg),
            "GROY": _groy_payload(self.cfg, "USD"),
            "URC.TO": {"currency": "CAD", "shares_out": 80e6, "macro": dict(MACRO),
                       "ref_price": 4.82, "spot_ref": 74.8, "base_mult": 1.15,
                       "annual_cashflow_per_share": 0.22,
                       "financials": {"sloan_cfo": 0.01, "sloan_bs": 0.02, "net_debt": 0.0,
                                      "ebitda": 30e6, "shares_t0": 80e6, "shares_t1": 80e6}},
            "GMX.TO": {"currency": "CAD", "shares_out": 120e6, "macro": dict(MACRO),
                       "annual_production_oz": 4_000_000, "aisc": 18.0,
                       "financials": {"sloan_cfo": 0.02, "sloan_bs": 0.03, "net_debt": 50e6,
                                      "ebitda": 80e6, "shares_t0": 120e6, "shares_t1": 121e6}},
        }
        regime = (0.4, 0.0, 0.2, 0.3, 0.0)
        weights_bps = {"AGA.V": 0.60, "URC.TO": 0.15, "GROY": 0.15, "GMX.TO": 0.10}
        book = 0.0
        for ticker, data in payloads.items():
            s = self.router.get_valuation(ticker, data, regime)
            self.assertGreater(s["blended_intrinsic"], 0.0, ticker)
            self.assertAlmostEqual(sum(s["weights"].values()), 1.0, places=6, msg=ticker)
            self.assertIn(s["data_quality"], ("full", "degraded"), ticker)
            self.assertEqual(s["base_currency"], "CAD", ticker)
            book += weights_bps[ticker] * s["intrinsic_after_forensic"]
        # the barbell blends to a single CAD intrinsic per dollar of book
        self.assertGreater(book, 0.0)

    def test_summary_is_fully_serializable(self):
        s = self.router.get_valuation("AGA.V", _aga_payload(self.cfg), NEUTRAL_REGIME)
        json.dumps(s)   # must round-trip (no numpy/Decimal/date leakage in the payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
