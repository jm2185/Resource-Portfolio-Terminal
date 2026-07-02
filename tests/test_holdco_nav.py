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


class TestOptionalityLens(unittest.TestCase):
    """The blue-sky read: 'price > risked NAV' is not naively 'no upside' — measure what the market
    pays for the optionality (implied) and grade it per-asset against a peer comp."""

    def test_implied_optionality_is_what_the_market_pays(self):
        o = holdco_nav.optionality_read(price_ps=1.75, risked_nav_ps=1.40, shares=57_000_000,
                                        asset_count=257)
        self.assertAlmostEqual(o["implied_optionality_total"], 19_950_000, delta=1)
        self.assertEqual(o["implied_pct_of_price"], 20.0)
        self.assertAlmostEqual(o["implied_per_asset"], 77_626, delta=2)     # tiny premium per asset

    def test_negative_when_price_below_risked(self):
        o = holdco_nav.optionality_read(price_ps=1.0, risked_nav_ps=1.40, shares=100, asset_count=10)
        self.assertLess(o["implied_optionality_total"], 0)                 # not paying for blue sky at all

    def test_peer_comp_grades_cheap(self):
        # market pays 77.6k/asset, a peer comp says 200k/asset → the blue sky is CHEAP
        o = holdco_nav.optionality_read(price_ps=1.75, risked_nav_ps=1.40, shares=57_000_000,
                                        asset_count=257, ev_per_asset=200_000)
        self.assertEqual(o["verdict_vs_peer"], "cheap")
        self.assertGreater(o["blue_sky_ps"], 1.40)                        # bull = risked + peer comp

    def test_unavailable_without_inputs(self):
        self.assertFalse(holdco_nav.optionality_read(price_ps=None, risked_nav_ps=1.4,
                                                     shares=100)["available"])

    def test_assess_surfaces_optionality_and_peer_comp_sets_bull(self):
        out = holdco_nav.assess(name="PG", price=1.75, shares=57_000_000, net_liquid_assets=37_500_000,
                                pipeline_assets=[{"name": "A", "npv": 90_000_000, "stage": "construction"}],
                                asset_count=257, ev_per_asset=200_000)
        self.assertTrue(out["optionality"]["available"])
        self.assertEqual(out["optionality"]["verdict_vs_peer"], "cheap")
        self.assertGreater(out["blue_sky_ps"], out["risked_nav_ps"])      # peer comp lifts the bull


class TestCentralFairValue(unittest.TestCase):
    """The archetype-aware fair-value anchor (the rating's `base`): a royalty's worth is its TANGIBLE
    carried book; a PG holdco's is net-liquid + portfolio optionality. The PURE wire gate is the
    anti-crush guarantee — a below-price NAV is asserted only on HIGH confidence."""

    # ---- royalty: tangible carried book ----
    def test_royalty_sourced_goodwill_is_tangible_book(self):
        r = holdco_nav.central_fair_value(mode="royalty", total_equity=722_000_000,
                                          goodwill=170_000_000, shares=230_809_201, price=1.60)
        self.assertEqual(r["basis"], "tangible_book_ex_goodwill")
        self.assertEqual(r["confidence"], "high")
        self.assertAlmostEqual(r["fair_value_ps"], (722_000_000 - 170_000_000) / 230_809_201, places=3)
        self.assertTrue(r["wire"])                                  # cheap vs price, high conf → wires

    def test_royalty_default_haircut_caps_confidence_at_med(self):
        r = holdco_nav.central_fair_value(mode="royalty", total_equity=722_000_000,
                                          shares=230_809_201, price=None)
        self.assertIn("default_haircut", r["basis"])
        self.assertEqual(r["confidence"], "med")                    # unsourced goodwill ⇒ never HIGH
        self.assertAlmostEqual(r["fair_value_ps"], 722_000_000 * 0.75 / 230_809_201, places=3)

    def test_royalty_missing_equity_unavailable(self):
        r = holdco_nav.central_fair_value(mode="royalty", shares=100, price=1.0)
        self.assertFalse(r["available"])
        self.assertIn("total_equity", r["missing"])

    # ---- holdco / PG: net-liquid + pipeline (+ peer) ----
    def test_holdco_pipeline_only_is_low_conf_and_never_wires(self):
        # the GMX case: a below-price NAV from a MODELLED pipeline must NOT crush the rating
        g = holdco_nav.central_fair_value(mode="holdco", hard_floor_ps=0.658, shares=57_010_000,
                                          risked_pipeline_value=42_525_000, price=1.75)
        self.assertEqual(g["confidence"], "low")
        self.assertLess(g["fair_value_ps"], 1.75)
        self.assertFalse(g["wire"])                                 # ANTI-CRUSH: low conf below price

    def test_holdco_peer_mark_lifts_and_wires(self):
        g = holdco_nav.central_fair_value(mode="holdco", hard_floor_ps=0.658, shares=57_010_000,
                                          risked_pipeline_value=42_525_000,
                                          peer_portfolio_value=40_000_000, price=1.75)
        self.assertEqual(g["basis"], "net_liquid_plus_pipeline_plus_peer")
        self.assertEqual(g["confidence"], "med")
        self.assertGreater(g["fair_value_ps"], 1.75)               # now cheap → wires positive upside
        self.assertTrue(g["wire"])

    def test_holdco_peer_mark_below_price_still_wires_at_med(self):
        # The live GMX case (2026-07): a SOURCED peer-portfolio mark makes the sum-of-parts complete, so
        # even when it lands just BELOW price it must WIRE at med — not fall back to the degraded archetype
        # blend, which reads far lower and manufactures a false RICH/TRIM. This is the peer-sourced
        # carve-out to the anti-crush "HIGH only below price" rule (net-liquid + pipeline + peer ≠ thin).
        g = holdco_nav.central_fair_value(mode="holdco", hard_floor_ps=0.658, shares=57_010_000,
                                          risked_pipeline_value=42_525_000,
                                          peer_portfolio_value=30_000_000, price=2.01)
        self.assertEqual(g["basis"], "net_liquid_plus_pipeline_plus_peer")
        self.assertEqual(g["confidence"], "med")
        self.assertAlmostEqual(g["fair_value_ps"], 1.93, places=2)  # < price 2.01, but complete + sourced
        self.assertTrue(g["wire"])                                  # peer-sourced ⇒ asserts below price at med

    def test_holdco_pipeline_only_below_price_still_held(self):
        # The guard the carve-out must NOT loosen: a pipeline-ONLY (no peer mark) below-price NAV is the
        # genuinely thin LOW-confidence case and stays HELD — anti-crush intact.
        g = holdco_nav.central_fair_value(mode="holdco", hard_floor_ps=0.658, shares=57_010_000,
                                          risked_pipeline_value=42_525_000, price=2.01)
        self.assertEqual(g["confidence"], "low")
        self.assertLess(g["fair_value_ps"], 2.01)
        self.assertFalse(g["wire"])

    # ---- the anti-crush wire gate, in isolation ----
    def test_below_price_nav_needs_high_confidence(self):
        # A below-price NAV would force NEGATIVE value-mode upside — the exact crush. On MED confidence
        # it must be HELD (informational), never wired...
        med = holdco_nav.central_fair_value(mode="royalty", total_equity=100, shares=100, price=1.50)
        self.assertEqual(med["confidence"], "med")                     # default haircut
        self.assertAlmostEqual(med["fair_value_ps"], 0.75, places=3)   # < price 1.50
        self.assertFalse(med["wire"])
        self.assertIn("anti-crush", med["wire_reason"])
        # ...but a HIGH-confidence (goodwill sourced) below-price NAV DOES wire — we trust the call.
        high = holdco_nav.central_fair_value(mode="royalty", total_equity=120, goodwill=0,
                                             shares=100, price=1.50)
        self.assertEqual(high["confidence"], "high")
        self.assertAlmostEqual(high["fair_value_ps"], 1.20, places=3)  # < price, but sourced
        self.assertTrue(high["wire"])

    def test_subfloor_nav_is_incoherent_not_wired(self):
        r = holdco_nav.central_fair_value(mode="royalty", total_equity=100, goodwill=0, shares=100,
                                          price=0.50, hard_floor_ps=2.0)
        self.assertFalse(r["wire"])
        self.assertIn("below hard floor", r["wire_reason"])

    def test_unknown_mode_is_graceful(self):
        r = holdco_nav.central_fair_value(mode="explorer", total_equity=100, shares=100)
        self.assertFalse(r["available"])


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

    def test_pipeline_field_lifts_risked_nav_and_flags_sourced(self):
        c = self._gmx_cache()
        c.set("GMX.TO", "holdco_pipeline_assets",
              [{"name": "P1", "npv": 100_000_000, "stage": "construction"}],   # 100M × 0.90 = 90M risked
              as_of="2026-06-24", confidence="low")
        out = holdco_nav_feed.assess_from_cache(c, "GMX.TO", price=1.75, today=date(2026, 6, 24))
        self.assertTrue(out["feed"]["pipeline_sourced"])
        self.assertGreater(out["risked_nav_ps"], out["hard_floor_ps"])         # the upside layer lifts base
        self.assertEqual(out["ladder"]["base"], out["risked_nav_ps"])

    def test_no_pipeline_means_risked_equals_floor_and_not_sourced(self):
        c = self._gmx_cache()
        out = holdco_nav_feed.assess_from_cache(c, "GMX.TO", price=1.75, today=date(2026, 6, 24))
        self.assertFalse(out["feed"]["pipeline_sourced"])
        self.assertEqual(out["risked_nav_ps"], out["hard_floor_ps"])           # no upside underwritten

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


# ---- General royalty metal-RE-RATE in central_fair_value, with the verify-before-wire gate ------
#
# A royalty book carried at acquisition COST understates as the metal re-rates ("book understates a
# royalty"). These pin the cockpit-wide fix and its trust gate:
#
#   * DETECTOR (always on, no rating change): every royalty-mode fair value returns
#     cost_basis_anchor=True and, until re-rated, rerate_candidate=True — so the under-mark is visible
#     for EVERY royalty name. holdco/PG mode is NOT a cost anchor.
#   * CORRECTION (flag-gated, fail-safe): a SOURCED rerated_book_value lifts the anchor only when the
#     royalty_rerate flag is on — only ever UP (never crush below cost), capped at MED confidence.
#   * VERIFY-BEFORE-WIRE: an agent-sourced re-rate may NOT move the rating until an INDEPENDENT
#     verifier has cleared it (rerated_verified). Unverified ⇒ held back (rerate_pending_verification),
#     cost book stands. Default is unverified — a sourced value is inert until checked. The feed reads
#     a CONFIRMED verdict off the research_cache `verified` block.

hn = holdco_nav
hnf = holdco_nav_feed


def _groy(**over):
    a = dict(mode="royalty", price=2.76, shares=230.8e6, total_equity=722e6, goodwill=0.0)
    a.update(over)
    return a


ON = {"royalty_rerate": {"enabled": True}}
OFF = {"royalty_rerate": {"enabled": False}}


class _FakeCache:
    """Mimics ResearchCache.get(ticker, field) over a plain nested dict."""
    def __init__(self, d):
        self._d = d
    def get(self, ticker, field):
        return self._d.get(ticker, {}).get(field)


class DetectorTests(unittest.TestCase):
    def test_every_royalty_is_flagged_cost_basis_and_rerate_candidate(self):
        r = hn.central_fair_value(**_groy())
        self.assertTrue(r["cost_basis_anchor"])
        self.assertTrue(r["rerate_candidate"])
        self.assertFalse(r["rerate_applied"])
        self.assertEqual(r["basis"], "tangible_book_ex_goodwill")
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_holdco_mode_is_not_a_cost_basis_anchor(self):
        h = hn.central_fair_value(mode="holdco", price=1.97, shares=57e6, hard_floor_ps=0.658,
                                  risked_pipeline_value=100e6, peer_portfolio_value=30e6)
        self.assertFalse(h["cost_basis_anchor"])
        self.assertFalse(h["rerate_candidate"])
        self.assertFalse(h["rerate_applied"])

    def test_flags_present_on_every_return(self):
        for r in (hn.central_fair_value(mode="royalty", price=1.0, shares=None),
                  hn.central_fair_value(mode="bogus")):
            for k in ("cost_basis_anchor", "rerate_applied", "rerate_candidate",
                      "rerate_pending_verification"):
                self.assertIn(k, r)


class CorrectionGateTests(unittest.TestCase):
    def test_flag_off_keeps_cost_book_even_with_a_verified_rerate(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True, config=OFF)
        self.assertFalse(r["rerate_applied"])
        self.assertFalse(r["rerate_pending_verification"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_flag_on_and_verified_lifts_the_anchor(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True, config=ON)
        self.assertTrue(r["rerate_applied"])
        self.assertFalse(r["rerate_candidate"])
        self.assertFalse(r["rerate_pending_verification"])
        self.assertEqual(r["basis"], "royalty_book_rerated_to_metal")
        self.assertAlmostEqual(r["fair_value_ps"], 4.333, places=2)        # 1.0e9 / 230.8e6
        self.assertAlmostEqual(r["components"]["rerate_uplift_pct"], 38.5, places=0)
        self.assertTrue(r["wire"])

    def test_rerate_never_crushes_below_cost(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=500e6, rerated_verified=True, config=ON)
        self.assertFalse(r["rerate_applied"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_rerate_confidence_is_capped_at_med(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_confidence="high",
                                  rerated_verified=True, config=ON)
        self.assertEqual(r["confidence"], "med")
        r_low = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_confidence="low",
                                      rerated_verified=True, config=ON)
        self.assertEqual(r_low["confidence"], "low")

    def test_default_config_absence_is_off(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True)
        self.assertFalse(r["rerate_applied"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)


class VerifyBeforeWireTests(unittest.TestCase):
    def test_unverified_rerate_is_held_back_not_applied(self):
        # flag ON, value above cost, but NOT verified ⇒ held back; the rating stays on cost book
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=False, config=ON)
        self.assertFalse(r["rerate_applied"])
        self.assertTrue(r["rerate_pending_verification"])
        self.assertTrue(r["rerate_candidate"])
        self.assertEqual(r["basis"], "tangible_book_ex_goodwill")
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)        # NOT 4.33 — unverified can't move it

    def test_unverified_is_the_safe_default(self):
        # rerated_verified defaults False ⇒ a sourced value is inert until an independent pass clears it
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, config=ON)
        self.assertFalse(r["rerate_applied"])
        self.assertTrue(r["rerate_pending_verification"])

    def test_verification_flips_it_on(self):
        held = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=False, config=ON)
        live = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True, config=ON)
        self.assertAlmostEqual(held["fair_value_ps"], 3.128, places=2)
        self.assertAlmostEqual(live["fair_value_ps"], 4.333, places=2)


class FeedVerificationTests(unittest.TestCase):
    """The feed maps the research_cache `verified` block to the rerated_verified flag the gate reads."""
    def _raw(self, verified):
        entry = {"value": 1.0e9, "confidence": "med"}
        if verified is not None:
            entry["verified"] = verified
        cache = _FakeCache({"GROY": {
            "total_equity": {"value": 722e6, "confidence": "high"},
            "shares_out": {"value": 230.8e6},
            "royalty_book_rerated_value": entry,
        }})
        return hnf.fair_value_inputs_from_cache(cache, "GROY")

    def test_absent_verified_is_false(self):
        self.assertFalse(self._raw(None)["rerated_verified"])

    def test_confirmed_verdict_is_verified(self):
        self.assertTrue(self._raw({"verdict": "confirmed", "by": "verifier"})["rerated_verified"])

    def test_rejected_verdict_is_not_verified(self):
        self.assertFalse(self._raw({"verdict": "rejected"})["rerated_verified"])

    def test_bool_true_is_verified(self):
        self.assertTrue(self._raw(True)["rerated_verified"])

    def test_value_and_confidence_flow_through(self):
        raw = self._raw({"verdict": "confirmed"})
        self.assertEqual(raw["rerated_book_value"], 1.0e9)
        self.assertEqual(raw["rerated_confidence"], "med")


class BlueSkyBullLegTests(unittest.TestCase):
    """The display bull leg = fair value + a VERIFIED dev-pipeline increment (never the gross-on-book
    double-count). Gated on verification; display-only (value-mode rating reads base, not bull)."""
    def test_verified_blue_sky_adds_increment_to_fair_value(self):
        r = hn.central_fair_value(**_groy(), blue_sky_value=60e6, blue_sky_verified=True)
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)            # base = cost book
        self.assertAlmostEqual(r["blue_sky_ps"], 3.128 + 60e6 / 230.8e6, places=2)  # bull = base + increment

    def test_unverified_blue_sky_is_none(self):
        r = hn.central_fair_value(**_groy(), blue_sky_value=60e6, blue_sky_verified=False)
        self.assertIsNone(r["blue_sky_ps"])

    def test_absent_blue_sky_is_none(self):
        self.assertIsNone(hn.central_fair_value(**_groy())["blue_sky_ps"])

    def test_blue_sky_key_present_on_every_return(self):
        for r in (hn.central_fair_value(mode="royalty", price=1.0, shares=None),
                  hn.central_fair_value(mode="bogus")):
            self.assertIn("blue_sky_ps", r)

    def test_feed_reads_confirmed_blue_sky(self):
        cache = _FakeCache({"GROY": {
            "total_equity": {"value": 722e6, "confidence": "high"},
            "shares_out": {"value": 230.8e6},
            "holdco_blue_sky_value": {"value": 60e6, "verified": {"verdict": "confirmed"}},
        }})
        raw = hnf.fair_value_inputs_from_cache(cache, "GROY")
        self.assertEqual(raw["blue_sky_value"], 60e6)
        self.assertTrue(raw["blue_sky_verified"])

    def test_feed_unverified_blue_sky_absent_receipt(self):
        cache = _FakeCache({"GROY": {"total_equity": {"value": 722e6}, "shares_out": {"value": 230.8e6},
                                     "holdco_blue_sky_value": {"value": 60e6}}})   # no verified block
        self.assertFalse(hnf.fair_value_inputs_from_cache(cache, "GROY")["blue_sky_verified"])


if __name__ == "__main__":
    unittest.main()
