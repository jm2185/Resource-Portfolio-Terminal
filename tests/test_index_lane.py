"""
Tests for the index-diversifier lane (index_lane.py) — the fourth lane, built 2026-09-05.

Guarantees pinned:
  * membership = portfolio_metadata + lane:'index' (never barbell_weights); a lane entry with no read
    block is a VISIBLE gap, not a skip;
  * the decorrelation gate is MEASURED: it fails on missing ρ, fails inside the margin, passes only
    at/under avg_pairwise − margin — and the margin IS the coherence checker's (they cannot drift);
  * the vehicle gates fail by name on currency / breadth / liquidity / fee (the EMBX lesson);
  * a diversifier must NAME the hole it covers;
  * the read is street-stamped, carries no rating, and produces the ladder shape the conventional
    sentinel consumes — proven by feeding it straight through;
  * weight band: floor AND ceiling; ceiling governs adds (add_frozen), no forced sale;
  * the lane guard refuses scout/council/discovery/pipeline for index names;
  * the shipped config block loads; the XEC.TO candidate carries a MEASURED receipt and reproduces its
    2026-09-05 REFUSAL from the stored numbers (the gate caught a stale receipt on its first real run).
"""
import json
import unittest

import coherence_check
import conventional_sentinel as cs
import dual_sided
import index_lane as il

XEC_BLOCK = {
    "price": 44.96, "fwd_pe": 11.7, "pe_hist": {"p10": 10.5, "p50": 12.4, "p90": 15.0},
    "max_drawdown": 0.153, "y10": 0.0478, "constituents": 1200, "median_notional": 3_008_493,
    "expense_ratio": 0.0026, "currency": "CAD",
    "decorrelation_receipt": {"rho_to_spear": 0.243, "avg_pairwise": 0.80, "window_days": 490,
                              "as_of": "2026-09-04", "source": "desk measurement 20260904-154625"},
}


def _pmeta(**over):
    base = {
        "AGA.V": {"type": "explorer", "thesis_slot": "silver-spear"},
        "CEG": {"name": "Constellation Energy", "lane": "conventional", "units": 54, "pricing_ref": "CEG"},
        "XEC.TO": {"name": "iShares Core MSCI EM (CAD)", "lane": "index", "units": 10, "pricing_ref": "XEC.TO",
                   "currency": "CAD", "index_lane": dict(XEC_BLOCK),
                   "scenario_payoffs": {"A": 0.02, "B": -0.05, "C": 0.03, "D": 0.0, "E": 0.08}},
    }
    base.update(over)
    return base


class MembershipTests(unittest.TestCase):
    def test_only_index_lane_names_enter(self):
        pos = il.positions(_pmeta())
        self.assertEqual([p["ticker"] for p in pos], ["XEC.TO"])
        self.assertTrue(il.is_index("XEC.TO", _pmeta()))
        self.assertFalse(il.is_index("CEG", _pmeta()))
        self.assertFalse(il.is_index("AGA.V", _pmeta()))

    def test_monitoring_lane_covers_both_conventional_and_index(self):
        pm = _pmeta()
        self.assertTrue(il.is_monitoring_lane("CEG", pm))
        self.assertTrue(il.is_monitoring_lane("XEC.TO", pm))
        self.assertFalse(il.is_monitoring_lane("AGA.V", pm))

    def test_lane_without_read_block_is_a_visible_gap(self):
        pm = _pmeta(**{"VFV.TO": {"lane": "index", "units": 3}})
        pos = {p["ticker"]: p for p in il.positions(pm)}
        self.assertTrue(pos["VFV.TO"]["unpriceable"])
        reads = il.build_reads(list(pos.values()), None)
        self.assertEqual(reads["VFV.TO"]["error"], "unpriceable")
        rows = {r["ticker"]: r for r in il.sleeve_rows(reads)}
        self.assertIn("error", rows["VFV.TO"])


class DecorrelationGateTests(unittest.TestCase):
    def test_margin_is_bound_to_the_coherence_checker(self):
        self.assertEqual(il.DEFAULT_INDEX_LANE_CONFIG["rho_margin"], coherence_check.DIVERSIFIER_MARGIN)

    def test_missing_rho_fails(self):
        g = il.decorrelation_gate(None, 0.8)
        self.assertFalse(g["passed"]); self.assertIn("narrative", g["read"])

    def test_inside_the_margin_fails_and_at_the_bar_passes(self):
        # avg 0.80, margin 0.05 → bar 0.75: 0.78 is inside the cluster, 0.75 is at the bar
        self.assertFalse(il.decorrelation_gate(0.78, 0.80)["passed"])
        self.assertTrue(il.decorrelation_gate(0.75, 0.80)["passed"])
        self.assertTrue(il.decorrelation_gate(0.24, 0.80)["passed"])

    def test_short_window_and_stale_receipt_fail(self):
        self.assertFalse(il.decorrelation_gate(0.24, 0.80, window_days=60)["passed"])
        g = il.decorrelation_gate(0.24, 0.80, as_of="2026-06-01", today="2026-09-05")
        self.assertFalse(g["passed"]); self.assertIn("re-measure", g["read"])
        self.assertTrue(il.decorrelation_gate(0.24, 0.80, as_of="2026-09-04", today="2026-09-05")["passed"])


class VehicleGateTests(unittest.TestCase):
    def test_xec_passes(self):
        self.assertTrue(il.vehicle_gate(_pmeta()["XEC.TO"])["passed"])

    def test_each_gate_fails_by_name(self):
        base = _pmeta()["XEC.TO"]
        usd = {**base, "currency": "USD", "index_lane": {**XEC_BLOCK, "currency": "USD"}}
        self.assertIn("currency", il.vehicle_gate(usd)["failures"][0])
        thin = {**base, "index_lane": {**XEC_BLOCK, "median_notional": 841_995}}   # EMBX's number
        self.assertIn("notional", il.vehicle_gate(thin)["failures"][0])
        narrow = {**base, "index_lane": {**XEC_BLOCK, "constituents": 40}}
        self.assertIn("constituents", il.vehicle_gate(narrow)["failures"][0])
        pricey = {**base, "index_lane": {**XEC_BLOCK, "expense_ratio": 0.0076}}     # EMBX's ER
        self.assertIn("expense ratio", il.vehicle_gate(pricey)["failures"][0])

    def test_missing_input_fails_never_passes_silently(self):
        m = {**_pmeta()["XEC.TO"], "index_lane": {k: v for k, v in XEC_BLOCK.items() if k != "constituents"}}
        g = il.vehicle_gate(m)
        self.assertFalse(g["passed"]); self.assertFalse(g["checks"]["constituents"]["passed"])


class CoverageAndAdmissionTests(unittest.TestCase):
    def test_must_name_a_hole(self):
        self.assertTrue(il.coverage_declaration(_pmeta()["XEC.TO"])["declared"])
        self.assertEqual(il.coverage_declaration(_pmeta()["XEC.TO"])["covers"], ["E"])
        self.assertFalse(il.coverage_declaration({"scenario_payoffs": {"A": 0.0, "E": 0.01}})["declared"])
        self.assertFalse(il.coverage_declaration({})["declared"])

    def test_admission_is_the_conjunction(self):
        m = _pmeta()["XEC.TO"]
        a = il.admission(m, today="2026-09-05")
        self.assertTrue(a["admitted"], a["read"])
        # any one gate failing refuses, and the read names which
        r = il.admission({**m, "scenario_payoffs": {}}, today="2026-09-05")
        self.assertFalse(r["admitted"]); self.assertIn("beta", r["read"])
        r = il.admission({**m, "index_lane": {**XEC_BLOCK, "decorrelation_receipt": {}}}, today="2026-09-05")
        self.assertFalse(r["admitted"]); self.assertIn("narrative", r["read"])

    def test_engine_supplied_rho_overrides_the_receipt(self):
        m = _pmeta()["XEC.TO"]
        # a live corr matrix says it has drifted INTO the cluster → refused despite the stored receipt
        r = il.admission(m, spear_rho=0.79, avg_pairwise=0.80, today="2026-09-05")
        self.assertFalse(r["admitted"])


class ReadTests(unittest.TestCase):
    def test_ladder_is_street_stamped_and_has_no_rating(self):
        v = il.value({**XEC_BLOCK, "ticker": "XEC.TO"})
        self.assertTrue(v["available"]); self.assertEqual(v["basis"], "street")
        self.assertNotIn("rating", v); self.assertNotIn("pillars", v)
        L = v["ladder"]
        self.assertAlmostEqual(L["floor"], 44.96 * (1 - 0.153), places=3)
        self.assertAlmostEqual(L["base"], 44.96 * 12.4 / 11.7, places=3)
        self.assertAlmostEqual(L["bull"], 44.96 * 15.0 / 11.7, places=3)
        self.assertEqual(L["basis"]["floor"], "empirical")
        self.assertEqual(v["zone"], "accumulate")          # below its own median multiple
        self.assertAlmostEqual(v["erp"], 1 / 11.7 - 0.0478, places=4)
        self.assertIn("STREET", v["read"])

    def test_extended_and_thin_erp_flag(self):
        v = il.value({**XEC_BLOCK, "fwd_pe": 16.0, "y10": 0.05})
        self.assertEqual(v["zone"], "extended")
        ids = {f["id"] for f in v["flags"]}
        self.assertIn("multiple_extended", ids); self.assertIn("erp_thin", ids)

    def test_missing_inputs_named_not_invented(self):
        v = il.value({"ticker": "X", "price": 10.0})
        self.assertFalse(v["available"]); self.assertIn("fwd_pe", v["data_completeness"]["missing"])
        v2 = il.value({**XEC_BLOCK, "max_drawdown": None})
        self.assertTrue(v2["available"]); self.assertIsNone(v2["ladder"]["floor"])

    def test_read_feeds_the_conventional_sentinel_directly(self):
        reads = il.build_reads(il.positions(_pmeta()), lambda ref: 44.96, nav=7670.0)
        r = reads["XEC.TO"]
        out = cs.assess_book([r], prev_zones={}, config=None)
        self.assertIn("zones_next", out)
        self.assertEqual(out["zones_next"].get("XEC.TO"), r["zone"])

    def test_dead_feed_falls_back_to_stored_price_stamped_stale(self):
        reads = il.build_reads(il.positions(_pmeta()), lambda ref: None, nav=7670.0)
        r = reads["XEC.TO"]
        self.assertTrue(r["stale"]); self.assertEqual(r["price"], 44.96); self.assertIn("STALE", r["read"])
        self.assertTrue(il.sleeve_rows(reads)[0]["stale"])

    def test_weight_and_band_flow_from_nav(self):
        reads = il.build_reads(il.positions(_pmeta()), lambda ref: 44.96, nav=7670.0)
        r = reads["XEC.TO"]
        self.assertAlmostEqual(r["market_value"], 449.6, places=2)
        self.assertAlmostEqual(r["weight"], 449.6 / 7670.0, places=4)
        self.assertEqual(r["band"]["zone"], "in_band")
        row = il.sleeve_rows(reads)[0]
        self.assertEqual(row["covers"], ["E"]); self.assertEqual(row["basis"], "street")


class WeightBandTests(unittest.TestCase):
    def test_floor_ceiling_and_add_freeze(self):
        self.assertEqual(il.weight_band(0.03)["zone"], "below_floor")
        self.assertEqual(il.weight_band(0.08)["zone"], "in_band")
        b = il.weight_band(0.15)
        self.assertEqual(b["zone"], "above_ceiling"); self.assertTrue(b["add_frozen"])
        self.assertIn("no forced sale", b["read"])
        self.assertFalse(il.weight_band(0.149)["add_frozen"])

    def test_config_override(self):
        b = il.weight_band(0.12, config={"index_lane": {"ceiling": 0.10}})
        self.assertTrue(b["add_frozen"])


class GuardTests(unittest.TestCase):
    def test_lane_guard_refuses_edge_seeking_flows_for_index_names(self):
        pm = _pmeta()
        for act in ("scout", "council", "discovery", "pipeline"):
            g = dual_sided.guard_conventional("XEC.TO", act, pm)
            self.assertFalse(g["allowed"], act); self.assertEqual(g["lane"], "index")
        self.assertTrue(dual_sided.guard_conventional("XEC.TO", "whatif", pm)["allowed"])
        self.assertTrue(dual_sided.guard_conventional("AGA.V", "council", pm)["allowed"])


class ShippedConfigTests(unittest.TestCase):
    def test_config_block_loads_and_binds_the_margin(self):
        with open("v5_config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        blk = cfg.get("index_lane")
        self.assertIsInstance(blk, dict)
        self.assertEqual(blk["rho_margin"], coherence_check.DIVERSIFIER_MARGIN)
        self.assertLess(blk["floor"], blk["ceiling"])
        self.assertEqual(blk["book_currency"], "CAD")
        # nothing is HELD in the lane yet — the operator has not bought; membership must be empty
        self.assertEqual(il.positions(cfg.get("portfolio_metadata")), [])

    def test_xec_candidate_carries_a_measured_receipt_and_its_refusal(self):
        """The first candidate was REFUSED by the lane's own gate on 2026-09-05 (ρ 0.29 vs a measured
        book average of 0.31 — inside the cluster by the margin). The universe entry must say so, the
        receipt must be a MEASUREMENT (not the test-fixture 0.80 the first freeze carried), and the
        gate must reproduce the refusal from the stored numbers — a kill-log entry that grades."""
        with open("data/candidate_universe.json", encoding="utf-8") as f:
            uni = json.load(f)
        cand = next(c for c in uni["candidates"] if c["ticker"] == "XEC.TO")
        self.assertEqual(cand["lane"], "index"); self.assertIn("index-diversifier", cand["slots"])
        self.assertTrue(cand.get("source"))
        rc = cand["index_lane"]["decorrelation_receipt"]
        self.assertLess(rc["avg_pairwise"], 0.5, "the receipt's book average must be a measurement of THIS book")
        self.assertIn("MEASURED", rc["source"])
        meta = {"currency": cand["currency"], "index_lane": cand["index_lane"],
                "scenario_payoffs": cand["scenario_payoffs"]}
        a = il.admission(meta, today=rc["as_of"])
        self.assertFalse(a["admitted"], a["read"])
        self.assertIn("inside the cluster", a["read"])
        self.assertFalse(cand["admission"]["admitted"])
        # the vehicle and coverage gates still pass — ONLY the decorrelation margin refuses it
        self.assertTrue(a["vehicle"]["passed"]); self.assertTrue(a["coverage"]["declared"])

    def test_universe_still_loads_through_the_discovery_screen(self):
        import discovery_screen
        fn = getattr(discovery_screen, "load_universe", None)
        if fn is None:
            self.skipTest("discovery_screen has no load_universe entry point")
        out = fn()
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main()
