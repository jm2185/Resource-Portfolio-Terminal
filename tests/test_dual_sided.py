"""dual_sided — the conventional-core valuation engine (Phase 2 of the dual-sided TIV spec). Tests the
two solvers (compounder reverse-DCF, deep-value SOTP) on hand-verifiable math + TMX/EEFT-flavored
fixtures, the fail-closed SOTP fallback, the shared schema, and the lane guard."""
import unittest

import dual_sided as ds


class MathTests(unittest.TestCase):
    def test_triangulate_blend_and_renormalize(self):
        base, w = ds._triangulate({"cost": 10, "market": 20, "income": 30},
                                  {"cost": 0.1, "market": 0.4, "income": 0.5},
                                  {"cost": 1.0, "market": 1.0, "income": 1.0})
        self.assertAlmostEqual(base, 24.0, places=6)                 # 0.1·10 + 0.4·20 + 0.5·30
        self.assertAlmostEqual(w["income"], 0.5, places=6)
        # a missing leg renormalizes out (no fake default)
        base2, w2 = ds._triangulate({"cost": 10, "market": 20},
                                    {"cost": 0.1, "market": 0.4, "income": 0.5}, {"cost": 1.0, "market": 1.0})
        self.assertAlmostEqual(base2, 18.0, places=6)                # weights → {0.2, 0.8}

    def test_reverse_dcf_roundtrips(self):
        # price the DCF at g=0.06, then the reverse solve must recover ~0.06
        fcf, wacc, cap, gt, nd, sh = 250.0, 0.09, 10, 0.025, -100.0, 280.0
        price = ds._per_share(ds._forward_dcf(fcf, 0.06, wacc, cap, gt), nd, sh)
        impl = ds._implied_growth(price, fcf, wacc, cap, gt, nd, sh, bounds=[-0.10, 0.40])
        self.assertEqual(impl["bounded"], "in_band")
        self.assertAlmostEqual(impl["implied_growth"], 0.06, places=3)

    def test_reverse_dcf_flags_above_ceiling(self):
        impl = ds._implied_growth(10_000.0, 250.0, 0.09, 10, 0.025, -100.0, 280.0, bounds=[-0.10, 0.40])
        self.assertEqual(impl["bounded"], "above_ceiling")          # priced beyond the model's growth ceiling

    def test_regime_tilt_is_one_leg_and_banded(self):
        cfg = ds._cfg(None)
        self.assertAlmostEqual(ds._regime_mult(0.0, cfg), 1.0, places=6)
        self.assertLessEqual(ds._regime_mult(5.0, cfg), 1.3)        # clamped (ballast band, not the spear's)
        self.assertGreaterEqual(ds._regime_mult(-5.0, cfg), 0.7)


class CompounderTests(unittest.TestCase):
    def _tmx(self, price=None):
        # a TMX-flavored premium compounder: fairly priced at ~6% growth
        fair = ds._per_share(ds._forward_dcf(250.0, 0.06, 0.09, 10, 0.025), -100.0, 280.0)
        return {"ticker": "X.TO", "price": price if price is not None else fair, "shares_out": 280.0,
                "net_debt": -100.0, "fcf": 250.0, "wacc": 0.09, "cap_years": 10,
                "growth": {"p10": 0.03, "p50": 0.06, "p90": 0.10},
                "quality": 0.82, "management_score": 0.75, "conviction": 0.6, "forensic_score": 3.7,
                "mri": 48.0, "regime_alpha": 0.2}

    def test_schema_and_value_mode(self):
        r = ds.solve_compounder(self._tmx())
        self.assertTrue(r["available"])
        self.assertEqual(r["lens"], "compounder")
        self.assertEqual(r["asymmetry"]["mode"], "value")           # compounder runs value mode
        self.assertIsNotNone(r["rating"])
        L = r["ladder"]
        self.assertGreater(L["bull"], L["base"])
        self.assertGreater(L["base"], L["bear"])
        self.assertLess(L["floor"], L["base"])                      # the torpedo floor sits below base

    def test_implied_growth_recovered_when_fairly_priced(self):
        r = ds.solve_compounder(self._tmx())                        # priced at the p50 DCF
        self.assertAlmostEqual(r["swing_variable"]["implied_growth"], 0.06, places=2)
        self.assertEqual(r["swing_variable"]["implied_vs_ceiling"], "within")
        self.assertTrue(r["swing_variable"]["asserted"])            # n=0 realized until Phase 6 seeds + grades

    def test_overpriced_is_torpedo_exposed(self):
        r = ds.solve_compounder(self._tmx(price=300.0))             # priced for growth above the ceiling
        self.assertEqual(r["swing_variable"]["implied_vs_ceiling"], "above")
        self.assertIn("torpedo", r["swing_variable"]["read"].lower())

    def test_unavailable_without_fcf(self):
        r = ds.solve_compounder({"ticker": "X.TO", "price": 50, "shares_out": 280, "growth": {"p50": 0.06}})
        self.assertFalse(r["available"])


class DeepValueTests(unittest.TestCase):
    def _eeft(self):
        # an EEFT-flavored deep-value name: SOTP well above price, a real NAV floor
        return {"ticker": "EEFT", "price": 90.0, "shares_out": 45.0, "net_debt": 200.0, "fcf": 500.0,
                "segments": [{"name": "Payments", "value": 600.0, "multiple": 8.0, "bull_multiple": 11.0},
                             {"name": "Ria", "value": 180.0, "multiple": 6.0, "bull_multiple": 8.0},
                             {"name": "CoreCard", "value": 120.0, "multiple": 10.0, "bull_multiple": 14.0}],
                "swing_segment": "Ria", "nav_per_share": 60.0,
                "quality": 0.6, "management_score": 0.6, "conviction": 0.55, "mri": 45.0}

    def test_sotp_math_and_asymmetry_mode(self):
        r = ds.solve_deep_value(self._eeft())
        self.assertTrue(r["available"])
        self.assertEqual(r["asymmetry"]["mode"], "asymmetry")       # deep_value: the discount is convexity
        # SOTP EV = 600·8 + 180·6 + 120·10 = 7080; equity = 6880; /45 ≈ 152.9 (the market leg)
        self.assertAlmostEqual(r["legs"]["values"]["market"], 152.888, places=2)
        self.assertAlmostEqual(r["asymmetry"]["phi"], 60.0 / 90.0, places=2)   # φ = floor/price
        self.assertFalse(r["data_completeness"]["fallback_used"])

    def test_swing_segment_named(self):
        r = ds.solve_deep_value(self._eeft())
        self.assertEqual(r["swing_variable"]["segment"], "Ria")
        self.assertTrue(r["swing_variable"]["asserted"])

    def test_fallback_when_no_segments(self):
        p = self._eeft()
        p.pop("segments")
        r = ds.solve_deep_value(p)
        self.assertTrue(r["available"])
        self.assertTrue(r["data_completeness"]["fallback_used"])
        self.assertIn(r["confidence_ribbon"]["quality"], ("degraded", "sparse"))  # fail-closed: wider band
        self.assertIn("FALLBACK", r["swing_variable"]["read"])

    def test_unavailable_without_segments_or_fcf(self):
        r = ds.solve_deep_value({"ticker": "EEFT", "price": 90, "shares_out": 45, "net_debt": 200})
        self.assertFalse(r["available"])


class ValueAndLaneTests(unittest.TestCase):
    def test_value_runs_both_lenses(self):
        payload = {"ticker": "X.TO", "price": 50.0, "shares_out": 280.0, "net_debt": -100.0,
                   "fcf": 250.0, "growth": {"p50": 0.06},
                   "segments": [{"name": "Core", "value": 400.0, "multiple": 9.0}], "nav_per_share": 35.0}
        r = ds.value(payload)
        self.assertTrue(r["lens_available"]["compounder"])
        self.assertTrue(r["lens_available"]["deep_value"])
        self.assertEqual(r["compounder"]["lens"], "compounder")
        self.assertEqual(r["deep_value"]["lens"], "deep_value")

    def test_lane_guard_blocks_conventional_discovery(self):
        md = {"X.TO": {"lane": "conventional"}, "AGA.V": {"slot": "silver-spear"}}
        self.assertFalse(ds.guard_conventional("X.TO", "scout", md)["allowed"])
        self.assertFalse(ds.guard_conventional("X.TO", "council", md)["allowed"])
        self.assertIn("conventional lane", ds.guard_conventional("X.TO", "scout", md)["reason"])
        # resource names (the default) pass everything; a non-edge action passes for anyone
        self.assertTrue(ds.guard_conventional("AGA.V", "scout", md)["allowed"])
        self.assertTrue(ds.guard_conventional("X.TO", "valuation", md)["allowed"])

    def test_lane_helpers_default_resource(self):
        md = {"X.TO": {"lane": "conventional"}}
        self.assertTrue(ds.is_conventional("X.TO", md))
        self.assertFalse(ds.is_conventional("AGA.V", md))           # unknown → resource default
        self.assertEqual(ds.lane_of("UNKNOWN", md), "resource")


def _lens(intrinsic, *, phi=0.6, pm=0.8, lens="compounder", available=True):
    return {"available": available, "lens": lens, "intrinsic": intrinsic,
            "asymmetry": {"phi": phi}, "confidence_ribbon": {"plus_minus": pm},
            "swing_variable": {"name": "x", "segment": "Ria"}, "rating": 6.0, "band": "X", "directive": "Y"}


class ReconcileTests(unittest.TestCase):
    def test_premium_franchise(self):
        r = ds.reconcile(_lens(80, phi=0.5, lens="compounder"), _lens(40, phi=0.5, lens="deep_value"), 50)
        self.assertEqual(r["shape"], "premium-franchise")
        self.assertEqual(r["leader"], "compounder")
        self.assertEqual(r["lead_lens"], "compounder")            # durability is the thesis
        self.assertGreater(r["spread_pct"], 12)

    def test_mispricing_flag(self):
        r = ds.reconcile(_lens(40, lens="compounder"), _lens(70, phi=0.6, lens="deep_value"), 50)
        self.assertEqual(r["shape"], "mispricing-flag")
        self.assertEqual(r["lead_lens"], "deep_value")            # the parts are worth more
        self.assertIn("mispricing", r["read"])

    def test_converged_leads_tighter_ribbon(self):
        r = ds.reconcile(_lens(51, pm=0.5, lens="compounder"), _lens(49, pm=0.9, phi=0.6, lens="deep_value"), 50)
        self.assertEqual(r["shape"], "converged")
        self.assertEqual(r["lead_lens"], "compounder")            # tighter ribbon wins the headline

    def test_phi_strong_leads_deep_value(self):
        # price at/below the asset floor → floor protection leads even when the compounder intrinsic is higher
        r = ds.reconcile(_lens(80, lens="compounder"), _lens(55, phi=1.10, lens="deep_value"), 50)
        self.assertEqual(r["shape"], "premium-franchise")
        self.assertEqual(r["lead_lens"], "deep_value")

    def test_single_lens_and_neither(self):
        r1 = ds.reconcile(_lens(60, lens="compounder"), {"available": False}, 50)
        self.assertEqual(r1["shape"], "single-lens")
        self.assertEqual(r1["lead_lens"], "compounder")
        r2 = ds.reconcile({"available": False}, {"available": False}, 50)
        self.assertFalse(r2["available"])

    def test_value_includes_reconciliation(self):
        payload = {"ticker": "X.TO", "price": 50.0, "shares_out": 280.0, "net_debt": -100.0,
                   "fcf": 250.0, "growth": {"p50": 0.06},
                   "segments": [{"name": "Core", "value": 400.0, "multiple": 9.0}], "nav_per_share": 35.0}
        r = ds.value(payload)
        self.assertIn("reconciliation", r)
        self.assertTrue(r["reconciliation"]["available"])
        self.assertIn(r["reconciliation"]["shape"],
                      ("premium-franchise", "mispricing-flag", "converged", "single-lens"))


class LedgerIntegrationTests(unittest.TestCase):
    def _basket(self):
        return {"ticker": "X.TO", "archetype": "compounder", "rating": 6.6, "band": "HIGH QUALITY",
                "directive": "QUALITY — CORE HOLD",
                "ladder": {"floor": 40.0, "bear": 44.0, "base": 52.0, "bull": 71.0, "price": 47.0},
                "pillars": {"T": {"score": 5.0}, "Q": {"score": 7.0},
                            "V": {"score": 5.4, "rho": 1.8, "floor_coverage": 0.85}},
                "gate": {"cap": 10.0, "reason": "clean"},
                "confidence_ribbon": {"plus_minus": 0.9, "quality": "full"}}

    def test_snapshot_carries_dual_sided_keys(self):
        import valuation_ledger as vl
        spread = {"shape": "premium-franchise", "leader": "compounder", "lead_lens": "compounder",
                  "spread_pct": 24.0, "compounder_intrinsic": 52.0, "deep_value_intrinsic": 41.0}
        sv = {"name": "priced-in growth", "value": "9%/yr", "base_rate_name": "compounder_growth_persistence",
              "asserted": True}
        snap = vl.snapshot_from_basket(self._basket(), lens="compounder", divergence_spread=spread, swing_variable=sv)
        self.assertEqual(snap["lens"], "compounder")
        self.assertEqual(snap["divergence_spread"]["shape"], "premium-franchise")
        self.assertTrue(snap["swing_variable"]["asserted"])
        self.assertEqual(snap["intrinsic"], 52.0)

    def test_fingerprint_flips_on_shape_and_stays_stable_for_resource(self):
        import valuation_ledger as vl
        spread = {"shape": "premium-franchise", "lead_lens": "compounder"}
        sv = {"value": "9%/yr"}
        snap = vl.snapshot_from_basket(self._basket(), lens="compounder", divergence_spread=spread, swing_variable=sv)
        snap2 = vl.snapshot_from_basket(self._basket(), lens="compounder",
                                        divergence_spread={"shape": "mispricing-flag", "lead_lens": "deep_value"},
                                        swing_variable=sv)
        self.assertNotEqual(vl.fingerprint(snap), vl.fingerprint(snap2))   # a shape flip is material
        # a resource snapshot (no dual-sided keys) is unaffected — fingerprint stable + no stray keys
        res = vl.snapshot_from_basket(self._basket())
        self.assertNotIn("lens", res)
        self.assertEqual(vl.fingerprint(res), vl.fingerprint(vl.snapshot_from_basket(self._basket())))


if __name__ == "__main__":
    unittest.main()
