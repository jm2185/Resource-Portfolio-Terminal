"""
Tests for the layered holdco/royalty-company NAV (holdco_nav.py) and its quarterly feed bridge
(holdco_nav_feed.py). The first proves the pure math (annuity → hard floor → per-share range → entry
zone); the second proves the NAV inputs are READ FROM the provenance store on a reporting cadence
(never hardcoded), degrade loudly when a layer isn't sourced, and flag staleness.
"""
import unittest
from datetime import date

import holdco_nav
import holdco_nav_feed


# A minimal stand-in for research_cache.ResearchCache — same get() contract (entry dict or None),
# so the feed bridge is tested in isolation without touching data/research_cache.json.
class FakeCache:
    def __init__(self, data=None):
        self._d = data or {}

    def set(self, ticker, field, value, source="src", as_of="2026-03-31", confidence="med", note=""):
        e = {"value": value, "source": source, "as_of": as_of, "confidence": confidence}
        if note:
            e["note"] = note
        self._d.setdefault(ticker.upper(), {})[field] = e
        return e

    def get(self, ticker, field):
        return (self._d.get(ticker.upper(), {}) or {}).get(field)


class TestAnnuityPV(unittest.TestCase):
    def test_flat_finite_annuity(self):
        # 100/yr, 15yr @10%, no growth = 100 × annuity-factor(7.60608)
        self.assertEqual(holdco_nav.annuity_pv(100, discount_rate=0.10, life_years=15), 760.61)

    def test_growing_annuity(self):
        # t1: 100/1.1 = 90.9091 ; t2: 105/1.21 = 86.7769 ; sum = 177.69
        self.assertEqual(holdco_nav.annuity_pv(100, discount_rate=0.10, life_years=2, growth=0.05), 177.69)

    def test_negative_cashflow_gives_negative_pv(self):
        self.assertLess(holdco_nav.annuity_pv(-50, discount_rate=0.10, life_years=10), 0)

    def test_bad_inputs_return_none(self):
        self.assertIsNone(holdco_nav.annuity_pv("nope"))
        self.assertIsNone(holdco_nav.annuity_pv(100, life_years=0))
        self.assertIsNone(holdco_nav.annuity_pv(100, discount_rate=-1.0))
        self.assertIsNone(holdco_nav.annuity_pv(float("inf")))


class TestHardFloor(unittest.TestCase):
    def test_net_of_g_and_a_plus_liquid(self):
        hf = holdco_nav.hard_floor_total(producing_royalty_cf=10, corporate_g_and_a=4, net_liquid_assets=50)
        self.assertEqual(hf["producing_net_cf"], 6.0)
        self.assertEqual(hf["producing_pv"], 45.64)         # 6 × 7.60608
        self.assertEqual(hf["hard_floor"], 95.64)           # 45.64 + 50
        self.assertTrue(hf["self_funding"])
        self.assertFalse(hf["floored_at_zero"])

    def test_liquid_only_when_no_producing(self):
        hf = holdco_nav.hard_floor_total(net_liquid_assets=37_500_000)
        self.assertEqual(hf["producing_pv"], 0.0)
        self.assertEqual(hf["hard_floor"], 37_500_000)

    def test_burn_below_liquid_floors_at_zero(self):
        # producing far under G&A, capitalized burn exceeds the cash → equity floor can't go negative
        hf = holdco_nav.hard_floor_total(producing_royalty_cf=1, corporate_g_and_a=10, net_liquid_assets=5)
        self.assertFalse(hf["self_funding"])
        self.assertTrue(hf["floored_at_zero"])
        self.assertEqual(hf["hard_floor"], 0.0)


class TestAssess(unittest.TestCase):
    def test_unavailable_without_shares(self):
        out = holdco_nav.assess(name="X", net_liquid_assets=100)
        self.assertFalse(out["available"])

    def test_layers_are_monotonic(self):
        out = holdco_nav.assess(name="X", shares=100, producing_royalty_cf=10, corporate_g_and_a=4,
                                net_liquid_assets=50, risked_pipeline_value=20, optionality_value=10)
        self.assertLessEqual(out["hard_floor_ps"], out["risked_nav_ps"])
        self.assertLessEqual(out["risked_nav_ps"], out["blue_sky_ps"])

    def test_entry_zone_below_floor_is_free(self):
        out = holdco_nav.assess(name="X", price=0.5, shares=100, net_liquid_assets=95.64,
                                risked_pipeline_value=20)
        self.assertEqual(out["entry_zone"], "below_hard_floor")
        self.assertGreaterEqual(out["floor_coverage"], 1.0)
        self.assertIn("FREE", out["read"])

    def test_entry_zone_pipeline_band(self):
        out = holdco_nav.assess(name="X", price=1.0, shares=100, producing_royalty_cf=10,
                                corporate_g_and_a=4, net_liquid_assets=50, risked_pipeline_value=20)
        self.assertEqual(out["entry_zone"], "in_pipeline_band")   # hf_ps≈0.956 < 1.0 < risked_ps≈1.156

    def test_entry_zone_above_risked(self):
        out = holdco_nav.assess(name="X", price=2.0, shares=100, producing_royalty_cf=10,
                                corporate_g_and_a=4, net_liquid_assets=50, risked_pipeline_value=20)
        self.assertEqual(out["entry_zone"], "above_risked_nav")

    def test_no_price_still_reports_range(self):
        out = holdco_nav.assess(name="X", shares=100, net_liquid_assets=50)
        self.assertNotIn("floor_coverage", out)
        self.assertIn("hard floor", out["read"])

    def test_sourced_flags_pass_through_to_coverage(self):
        out = holdco_nav.assess(name="X", shares=100, net_liquid_assets=50,
                                sourced={"net_liquid_assets": True, "producing_royalty_cf": False})
        self.assertTrue(out["coverage"]["net_liquid_assets"])
        self.assertFalse(out["coverage"]["producing_royalty_cf"])


class TestRiskedPipelineLadder(unittest.TestCase):
    """The UPSIDE the floor omits: risked NAV = hard floor + Σ(pipeline NPV × stage-probability).
    This is what gives a holdco/PG a real fair value instead of a degraded book anchor."""

    def test_stage_probability_matches_and_defaults(self):
        self.assertEqual(holdco_nav.stage_probability("construction"), 0.90)
        self.assertEqual(holdco_nav.stage_probability("Feasibility Study"), 0.50)   # substring
        self.assertEqual(holdco_nav.stage_probability("producing"), 1.00)
        self.assertEqual(holdco_nav.stage_probability("who knows"),
                         holdco_nav.DEFAULT_STAGE_PROBABILITY["_default"])          # never silent 0 or 1

    def test_risked_pipeline_sums_npv_times_probability(self):
        rp = holdco_nav.risked_pipeline_from_assets([
            {"name": "A", "npv": 100, "stage": "construction"},     # 100 × 0.90 = 90
            {"name": "B", "npv": 200, "stage": "pfs"},              # 200 × 0.30 = 60
        ])
        self.assertEqual(rp["risked_pipeline_value"], 150.0)
        self.assertEqual(len(rp["assets"]), 2)

    def test_explicit_probability_overrides_stage(self):
        rp = holdco_nav.risked_pipeline_from_assets([{"name": "A", "npv": 100, "stage": "pea",
                                                      "probability": 0.5}])
        self.assertEqual(rp["risked_pipeline_value"], 50.0)        # 0.5, not the pea 0.15

    def test_bad_npv_contributes_zero_but_is_listed(self):
        rp = holdco_nav.risked_pipeline_from_assets([{"name": "X", "npv": None, "stage": "fs"}])
        self.assertEqual(rp["risked_pipeline_value"], 0.0)
        self.assertEqual(len(rp["assets"]), 1)                     # transparency: still shown

    def test_assess_pipeline_lifts_base_above_floor(self):
        out = holdco_nav.assess(name="PG", price=1.0, shares=100, net_liquid_assets=50,
                                pipeline_assets=[{"name": "A", "npv": 100, "stage": "construction"},
                                                 {"name": "B", "npv": 200, "stage": "pfs"}])
        self.assertEqual(out["hard_floor_ps"], 0.5)               # floor unchanged (liquid only)
        self.assertEqual(out["risked_nav_ps"], 2.0)              # (50 + 150)/100 — the upside layer
        self.assertEqual(out["ladder"], {"bear": 0.5, "base": 2.0, "bull": 2.0})
        self.assertLess(out["hard_floor_ps"], out["risked_nav_ps"])
        self.assertEqual(len(out["pipeline_assets"]), 2)


class TestFeedReadInputs(unittest.TestCase):
    def test_maps_cache_fields_to_assess_kwargs(self):
        c = FakeCache()
        c.set("GMX.TO", "holdco_net_liquid_assets", 37_500_000, as_of="2025-12-31", confidence="high")
        c.set("GMX.TO", "holdco_shares_outstanding", 57_000_000, as_of="2026-06-24", confidence="high")
        rd = holdco_nav_feed.read_inputs(c, "GMX.TO")
        self.assertEqual(rd["inputs"]["net_liquid_assets"], 37_500_000)
        self.assertEqual(rd["inputs"]["shares"], 57_000_000)
        self.assertTrue(rd["sourced"]["net_liquid_assets"])
        # producing + g&a never sourced → flagged in missing_for_floor, not invented
        self.assertIn("producing_royalty_cf", rd["missing_for_floor"])
        self.assertNotIn("producing_royalty_cf", rd["inputs"])

    def test_shares_override_used_only_when_unsourced_and_flagged(self):
        c = FakeCache()
        rd = holdco_nav_feed.read_inputs(c, "ZZZ", shares_override=12_345)
        self.assertEqual(rd["inputs"]["shares"], 12_345)
        self.assertFalse(rd["sourced"]["shares"])           # market data, not a filing
        # a sourced share count wins over the override
        c.set("ZZZ", "holdco_shares_outstanding", 999, as_of="2026-03-31")
        rd2 = holdco_nav_feed.read_inputs(c, "ZZZ", shares_override=12_345)
        self.assertEqual(rd2["inputs"]["shares"], 999)
        self.assertTrue(rd2["sourced"]["shares"])


class TestFeedStaleness(unittest.TestCase):
    def test_oldest_layer_binds_and_flags_refresh(self):
        as_of = {"producing_royalty_cf": "2026-03-31", "corporate_g_and_a": "2026-03-31",
                 "net_liquid_assets": "2025-12-31", "shares": "2026-03-31"}
        s = holdco_nav_feed.feed_staleness(as_of, today=date(2026, 6, 24))
        self.assertEqual(s["oldest_as_of"], "2025-12-31")   # the stalest hard-floor layer binds
        self.assertTrue(s["refresh_due"])                   # 175d > 136d cycle

    def test_fresh_quarter_not_due(self):
        as_of = {k: "2026-03-31" for k in holdco_nav_feed.HARD_FLOOR_ARGS}
        s = holdco_nav_feed.feed_staleness(as_of, today=date(2026, 5, 1))
        self.assertFalse(s["refresh_due"])

    def test_empty_is_graceful(self):
        s = holdco_nav_feed.feed_staleness({}, today=date(2026, 6, 24))
        self.assertIsNone(s["oldest_as_of"])
        self.assertFalse(s["refresh_due"])


class TestAssessFromCache(unittest.TestCase):
    def _gmx_cache(self):
        c = FakeCache()
        # GMX: liquid book is the floor, operations credited zero (sourced deliberate zero)
        c.set("GMX.TO", "holdco_net_liquid_assets", 37_500_000, as_of="2025-12-31", confidence="high")
        c.set("GMX.TO", "holdco_shares_outstanding", 57_000_000, as_of="2026-06-24", confidence="high")
        c.set("GMX.TO", "holdco_producing_royalty_cf", 0, as_of="2025-12-31", confidence="high",
              note="operations net-negative ex asset sales; floor credits ops zero")
        c.set("GMX.TO", "holdco_corporate_g_and_a", 0, as_of="2025-12-31", confidence="high",
              note="netted into producing=0")
        return c

    def test_fully_sourced_floor_reads_clean(self):
        c = self._gmx_cache()
        out = holdco_nav_feed.assess_from_cache(c, "GMX.TO", price=1.75, name="Globex",
                                                today=date(2026, 6, 24))
        self.assertTrue(out["available"])
        self.assertAlmostEqual(out["hard_floor_ps"], 37_500_000 / 57_000_000, places=2)  # ≈0.66
        self.assertTrue(out["feed"]["floor_sourced"])
        self.assertEqual(out["feed"]["missing_for_floor"], [])
        # Dec-31 data is >1 quarter old at Jun-24 → the feed nudges a refresh, honestly
        self.assertTrue(out["feed"]["refresh_due"])
        self.assertIn("refresh due", out["feed"]["data_quality"])

    def test_pending_floor_degrades_loudly(self):
        c = FakeCache()
        c.set("GMX.TO", "holdco_shares_outstanding", 57_000_000, as_of="2026-06-24")
        out = holdco_nav_feed.assess_from_cache(c, "GMX.TO", price=1.75, today=date(2026, 6, 24))
        self.assertFalse(out["feed"]["floor_sourced"])
        self.assertIn("PENDING", out["feed"]["data_quality"])
        self.assertIn("producing_royalty_cf", out["feed"]["missing_for_floor"])
        self.assertIn("net_liquid_assets", out["feed"]["missing_for_floor"])

    def test_provenance_round_trips(self):
        c = self._gmx_cache()
        out = holdco_nav_feed.assess_from_cache(c, "GMX.TO", price=1.75, today=date(2026, 6, 24))
        prov = out["feed"]["provenance"]["net_liquid_assets"]
        self.assertEqual(prov["value"], 37_500_000)
        self.assertEqual(prov["confidence"], "high")
        self.assertEqual(prov["as_of"], "2025-12-31")


class TestFieldFor(unittest.TestCase):
    def test_known_and_unknown(self):
        self.assertEqual(holdco_nav_feed.field_for("net_liquid_assets"), "holdco_net_liquid_assets")
        self.assertIsNone(holdco_nav_feed.field_for("not_a_field"))


class TestReadQualityInputs(unittest.TestCase):
    def test_reads_facts_and_derives_balance_sheet_lens(self):
        c = FakeCache()
        c.set("GMX.TO", "quality_asset_count", 270, as_of="2026-06-24")
        c.set("GMX.TO", "quality_share_growth_rate", 0.007, as_of="2026-06-24")
        c.set("GMX.TO", "quality_cashflow_coverage", 0.29, as_of="2025-12-31")
        c.set("GMX.TO", "holdco_net_liquid_assets", 37_500_000, as_of="2025-12-31")
        c.set("GMX.TO", "holdco_shares_outstanding", 57_010_000, as_of="2026-06-24")
        out = holdco_nav_feed.read_quality_inputs(c, "GMX.TO", price=1.75)
        self.assertEqual(out["inputs"]["asset_count"], 270)
        # derived: 37.5M / (1.75 × 57.01M) ≈ 0.376  (the balance-sheet lens)
        self.assertAlmostEqual(out["inputs"]["net_liquid_to_mktcap"], 0.3759, places=3)

    def test_unfed_facts_are_absent_not_invented(self):
        c = FakeCache()
        c.set("GROY", "quality_tier1_operator_fraction", 0.75, as_of="2026-03-31")
        out = holdco_nav_feed.read_quality_inputs(c, "GROY", price=3.0)
        self.assertEqual(out["inputs"]["tier1_operator_fraction"], 0.75)
        self.assertNotIn("asset_count", out["inputs"])           # not fed → simply absent
        self.assertNotIn("net_liquid_to_mktcap", out["inputs"])  # no net-liquid fed → not derivable


if __name__ == "__main__":
    unittest.main()
