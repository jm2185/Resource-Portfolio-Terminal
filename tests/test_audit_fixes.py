"""Regression tests for the v5.1 engine-audit fixes (the five top actions):

  #1  the dynamic-config overlay reaches the core engines (was: /confirm'd overrides silently
      bypassed live valuation / JSF / directives because each engine re-read the raw file)
  #2  the REP-floor cost leg reconciles to the SAME sourced resource base as the market leg
  #3  ballast fair value anchors on a SOURCED NAV, never raw accounting book (which understates
      holdco/royalty NAV); names without a NAV keep the documented config anchor
  #4  ES95 is a SIGNED DECIMAL end-to-end (negative = loss); the cold-start seed no longer leaves
      the tail-risk machinery inert
  #5  the option-premium relative-moneyness term is stage-gated (needs a real project-vs-peer AISC
      edge); when inactive its weight is dropped and vol+carry renormalize to 1

These are unit/mechanism tests (no live network); they assert the fix invariants, not magic numbers.
"""

import os
import tempfile
import unittest

import engine
from dynamic_config import DynamicConfigManager


class _FakeCache:
    """Minimal research-cache stand-in: .value(ticker, field, default) over a controlled dict."""

    def __init__(self, data):
        self.data = data

    def value(self, tkr, field, default=None):
        return (self.data.get(tkr.upper(), {}) or {}).get(field, default)


class TestConfigOverlayReachesEngines(unittest.TestCase):
    """Action #1."""

    def test_get_config_provider_routing(self):
        # No provider wired (standalone engine, e.g. unit tests) -> raw file read, unchanged.
        v = engine.ValuationEngine("v5_config.json")
        self.assertEqual(v.get_config()["conservatism_scalar"], 0.88)
        # A wired provider is served instead of the file (this is what carries the overlay).
        v._config_provider = lambda: {"conservatism_scalar": 0.99, "_sentinel": True}
        self.assertEqual(v.get_config()["conservatism_scalar"], 0.99)
        self.assertTrue(v.get_config()["_sentinel"])
        v._config_provider = None
        self.assertEqual(v.get_config()["conservatism_scalar"], 0.88)

    def test_set_defaults_merges_file_then_overrides(self):
        tmp = os.path.join(tempfile.mkdtemp(), "dc.sqlite")
        dc = DynamicConfigManager({"conservatism_scalar": 0.88}, db_path=tmp)
        self.assertEqual(dc.effective()["conservatism_scalar"], 0.88)
        # file-edit hot-reload: most config is NOT in the allowlist and can only change via the file
        dc.set_defaults({"conservatism_scalar": 0.80, "project_buckets_oz_AgEq": {"x": 1}})
        self.assertEqual(dc.effective()["conservatism_scalar"], 0.80)
        self.assertEqual(dc.effective()["project_buckets_oz_AgEq"], {"x": 1})
        # a confirmed override wins over the file default...
        dc.set_param("conservatism_scalar", 1.10, source="test")
        self.assertEqual(dc.effective()["conservatism_scalar"], 1.10)
        # ...and persists across subsequent file refreshes
        dc.set_defaults({"conservatism_scalar": 0.70})
        self.assertEqual(dc.effective()["conservatism_scalar"], 1.10)

    def test_refresh_effective_config_wires_engines(self):
        m = engine.CommodityExMonitor()
        # swap to a temp-DB overlay so we never touch the real data/dynamic_config.sqlite
        tmp = os.path.join(tempfile.mkdtemp(), "dc.sqlite")
        m.dconfig = DynamicConfigManager(m.config, db_path=tmp)
        m.dconfig.set_param("conservatism_scalar", 1.07, source="test")
        m._refresh_effective_config()
        # the override now reaches the live valuation engine through its provider
        self.assertEqual(m.valuation_engine.get_config()["conservatism_scalar"], 1.07)
        self.assertEqual(m.forensic_engine.get_config()["conservatism_scalar"], 1.07)


class TestRepFloorReconciliation(unittest.TestCase):
    """Action #2."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")

    def test_effective_oz_passthrough(self):
        shares = 208_600_000
        legacy = self.v.calculate_rep_floor(shares_outstanding=shares)            # config buckets
        floor_zero = self.v.calculate_rep_floor(shares_outstanding=shares, effective_oz=0.0)
        floor_big = self.v.calculate_rep_floor(shares_outstanding=shares, effective_oz=1e9)
        # zero ounces -> cash + infra only (a hard floor below the legacy resource-laden value)
        self.assertLess(floor_zero, legacy)
        self.assertLess(legacy, floor_big)
        # the floor still scales inversely with the share count under the override
        half = self.v.calculate_rep_floor(shares_outstanding=2 * shares, effective_oz=1e9)
        self.assertAlmostEqual(half, floor_big / 2.0, places=6)

    def test_cost_leg_uses_reconciled_oz_and_records_basis(self):
        self.v._rc = __import__("research_cache").ResearchCache()
        kw = dict(peer_ev_oz=2.078, spot_ag=75.6, capital_discount_factor=0.88, real_yield=2.1,
                  silver_vol=0.30, forensic_penalty=1.0, dynamic_aisc=25.6, shares_outstanding=208_600_000)
        d = self.v.calculate_spear_intrinsic(**kw)
        # the cost leg equals the floor evaluated on the SAME effective ounces the market leg used
        expected_cost = self.v.calculate_rep_floor(208_600_000, effective_oz=d["effective_oz_total"])
        self.assertAlmostEqual(d["legs"]["cost"], round(expected_cost, 4), places=4)
        self.assertIn(d["rep_floor_basis"], ("research_cache (filings, reconciled)", "config buckets"))
        # convex-combination invariant preserved (no income leg for a pure explorer)
        lo, hi = sorted([d["legs"]["cost"], d["legs"]["market"]])
        self.assertLessEqual(lo, d["v_intrinsic"])
        self.assertLessEqual(d["v_intrinsic"], hi)


class TestBallastNavAnchor(unittest.TestCase):
    """Action #3."""

    def setUp(self):
        self.m = engine.CommodityExMonitor()

    def test_allow_book_false_requires_genuine_nav(self):
        self.m._rc = _FakeCache({
            "HASNAV": {"currency": "CAD", "nav_inventory": None, "nav_adj_per_share": 5.0,
                       "book_value_per_share": 2.0},
            "BOOKONLY": {"currency": "USD", "nav_inventory": None, "nav_adj_per_share": None,
                         "book_value_per_share": 2.0},
        })
        # a sourced NAV is used regardless of allow_book
        self.assertEqual(self.m._research_book_native("HASNAV", allow_book=False), (5.0, "CAD"))
        # raw book is NOT a fair-value anchor: allow_book=False returns None (caller keeps config ref)
        self.assertIsNone(self.m._research_book_native("BOOKONLY", allow_book=False))
        # but the legacy/archetype caller (allow_book=True, the default) still sees raw book -> unchanged
        self.assertEqual(self.m._research_book_native("BOOKONLY", allow_book=True), (2.0, "USD"))
        self.assertEqual(self.m._research_book_native("BOOKONLY"), (2.0, "USD"))

    def test_ballast_fair_value_method_decoupled_from_price(self):
        # the underlying fair-value method never takes the name's own share price (severed loop)
        fv = self.m.valuation_engine.calculate_ballast_fair_value(
            ref_price=4.0, base_mult=1.15, spot_now=1.0, spot_ref=1.0, spot_beta=1.0, forensic_pen=1.0)
        self.assertAlmostEqual(fv, 4.0 * 1.15)


class TestES95SignedConvention(unittest.TestCase):
    """Action #4."""

    def test_cold_start_seed_is_signed_decimal(self):
        m = engine.CommodityExMonitor()
        es = m.state_cache["es_95"]
        self.assertLess(es, 0.0, "ES95 cold-start seed must be a signed decimal loss (negative)")
        self.assertGreater(es, -1.0, "ES95 seed should be a per-unit decimal, not a percent")

    def test_machinery_live_at_cold_start(self):
        m = engine.CommodityExMonitor()
        es_pct = m.state_cache["es_95"] * 100.0     # display/plumbing convention
        sizer, radar = m.sizer, m.radar
        base = dict(aga_price=0.71, aga_adv=5_000_000, port_vol=0.80, vix=16.5, jsf_score=4.0)
        vols = {"AGA.V": 0.80, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
        corr = {"AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30}}
        live = sizer.calculate_sizing(10000.0, 0.30, vols, corr, 30.0,
                                      dict(base, expected_shortfall_95_pct=es_pct))
        inert = sizer.calculate_sizing(10000.0, 0.30, vols, corr, 30.0,
                                       dict(base, expected_shortfall_95_pct=520.0))  # the OLD seed*100
        # the OLD positive seed left the throttle inert (no tail brake); the new signed seed engages it
        self.assertEqual(inert["es_throttle"], 1.0)
        self.assertLess(live["es_throttle"], 1.0)
        # Health Rating penalty is likewise live (lower than a 0-ES no-penalty baseline)
        h_live = radar.calculate_health_rating(4.0, 30.0, es_pct, False)["health_rating"]
        h_zero = radar.calculate_health_rating(4.0, 30.0, 0.0, False)["health_rating"]
        self.assertLess(h_live, h_zero)


class TestOptionPremiumMoneynessGate(unittest.TestCase):
    """Action #5."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")

    def test_inactive_renormalizes_vol_carry(self):
        # explorer with only an INDUSTRY aisc (peer_aisc=None) -> moneyness term inactive
        r = self.v.calculate_option_premium(75.0, 25.0, 0.30, 2.0, "explorer")
        self.assertFalse(r["moneyness_active"])
        self.assertEqual(r["moneyness_excess"], 0.0)
        self.assertEqual(r["weights_used"]["moneyness"], 0.0)
        self.assertAlmostEqual(r["weights_used"]["vol"] + r["weights_used"]["carry"], 1.0, places=6)

    def test_active_with_real_aisc_edge(self):
        # a genuine project-vs-peer AISC edge re-activates the term at its configured weights
        r = self.v.calculate_option_premium(75.0, 18.0, 0.30, 2.0, "explorer", peer_aisc=25.0)
        self.assertTrue(r["moneyness_active"])
        self.assertGreater(r["moneyness_excess"], 0.0)
        self.assertEqual(r["weights_used"]["moneyness"], 0.4)

    def test_monotonic_and_stage_decay_preserved(self):
        base = self.v.calculate_option_premium(75.0, 25.0, 0.30, 2.0, "explorer")["pi_opt"]
        hi_vol = self.v.calculate_option_premium(75.0, 25.0, 0.50, 2.0, "explorer")["pi_opt"]
        neg_ry = self.v.calculate_option_premium(75.0, 25.0, 0.30, -2.0, "explorer")["pi_opt"]
        prod = self.v.calculate_option_premium(75.0, 25.0, 0.50, -2.0, "producer")["pi_opt"]
        expl = self.v.calculate_option_premium(75.0, 25.0, 0.50, -2.0, "explorer")["pi_opt"]
        self.assertGreater(hi_vol, base)
        self.assertGreater(neg_ry, base)
        self.assertGreater(expl, prod)


class TestSecondBatchFixes(unittest.TestCase):
    """Second-tier audit findings: forensic configurability/contamination, exploration-leg capital
    discount, mos_ledger completeness, fail-conservative defaults, peer-comp anti-fabrication."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")
        self.v._rc = __import__("research_cache").ResearchCache()

    def test_forensic_runway_threshold_is_configurable(self):
        f = engine.ForensicEngine("v5_config.json")
        # ~19.3mo runway passes the default 18mo gate
        _, _, d = f.calculate_jsf_score("AGA.V", 53e6, 2.75e6, 0.02, 0.02, 100, 100, 100)
        self.assertTrue(d["runway"]["pass"])
        # tighten the gate via config -> the SAME runway now fails (config is actually read)
        f._config_provider = lambda: {
            "portfolio_metadata": {"AGA.V": {"type": "explorer"}},
            "forensic_thresholds": {"runway_min_months": 24.0, "cba_denominator": "cash",
                                    "max_burn_acceleration_pct": 0.15, "max_qoq_dilution_pct": 2.0,
                                    "max_sga_ratio": 0.30},
            "forensic_override_policy": {"max_validity_days": 45}, "forensic_overrides": {}}
        _, _, d2 = f.calculate_jsf_score("AGA.V", 53e6, 2.75e6, 0.02, 0.02, 100, 100, 100)
        self.assertFalse(d2["runway"]["pass"])

    def test_exploration_leg_applies_capital_discount(self):
        kw = dict(peer_ev_oz=2.0, spot_ag=75.0, real_yield=2.0, silver_vol=0.30,
                  forensic_penalty=1.0, dynamic_aisc=25.0, shares_outstanding=208_600_000)
        hi = self.v.calculate_spear_intrinsic(capital_discount_factor=1.0, **kw)["v_exploration"]
        lo = self.v.calculate_spear_intrinsic(capital_discount_factor=0.5, **kw)["v_exploration"]
        self.assertGreater(hi, lo)                       # leg now responds to the capital discount
        self.assertAlmostEqual(lo, hi * 0.5, places=4)   # linear in capital_discount_factor

    def test_mos_ledger_includes_option_premium_last_is_forensic(self):
        kw = dict(peer_ev_oz=2.078, spot_ag=75.6, capital_discount_factor=0.88, real_yield=2.1,
                  silver_vol=0.30, forensic_penalty=0.95, dynamic_aisc=25.6, shares_outstanding=208_600_000)
        d = self.v.calculate_spear_intrinsic(**kw)
        names = [r["name"] for r in d["mos_ledger"]]
        self.assertIn("option_premium", names)
        self.assertEqual(names[-1], "forensic_penalty")          # net-haircut invariant preserved
        opt_row = next(r for r in d["mos_ledger"] if r["name"] == "option_premium")
        self.assertAlmostEqual(opt_row["factor"], round(1.0 + d["option_premium"]["pi_opt"], 3), places=3)
        self.assertGreaterEqual(opt_row["factor"], 1.0)          # it is a LIFT, not a haircut

    def test_health_radar_priorities_fail_conservative(self):
        r = engine.HealthRadarEngine("v5_config.json")
        pr = r.generate_priorities({"Implied_Upside": 100.0},   # NO AGA_Intrinsic key
                                   jsf_score=4.0, mri_score=30.0, expected_shortfall_95=-4.0, p_aga=0.71)
        self.assertNotEqual(pr[0]["title"], "EXPLOIT SPEAR ARBITRAGE")

    def test_technical_quality_surfaces_defaults_used(self):
        unk = self.v.calculate_technical_quality("___unconfigured___")
        self.assertFalse(unk["project_configured"])
        self.assertEqual(set(unk["defaults_used"]),
                         {"grade_gpt_ageq", "ageq_share_ag", "ageq_share_au", "rec_ag", "rec_au",
                          "fraser", "infrastructure", "depth"})
        self.v._config_provider = lambda: {"technical_quality": {"enabled": True, "factors": {}, "projects": {
            "P": {"grade_gpt_ageq": 250, "ageq_share_ag": 0.7, "ageq_share_au": 0.3, "rec_ag": 0.85,
                  "rec_au": 0.92, "fraser": 80, "infrastructure": 0.6, "depth": 0.5}}}}
        p = self.v.calculate_technical_quality("P")
        self.assertTrue(p["project_configured"])
        self.assertEqual(p["defaults_used"], [])

    def test_sourced_resource_treats_zero_indicated_as_valid(self):
        self.v._rc = _FakeCache({"X": {"in_ground_ageq_oz_indicated": 0.0,
                                       "in_ground_ageq_oz_inferred": 5_000_000}})
        # 0.0 indicated is a real (all-inferred) value, not "missing" -> not dropped by or-chaining
        self.assertEqual(self.v._sourced_spear_resource("X"), (0.0, 5_000_000.0))


if __name__ == "__main__":
    unittest.main()
