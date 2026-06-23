"""Phase 6 — the slot-fit-first discovery screen: gate ordering, the kill log, the
missing-data policy, and the base-rate anchor attachment."""
from __future__ import annotations

import os
import tempfile
import unittest

import discovery_screen as ds


def _cand(**kw):
    base = {"ticker": "TEST.V", "name": "Test Co", "slots": ["silver-spear"],
            "vehicle": "explorer", "commodity": "silver", "stage": "pea",
            "fraser_index": 80.0, "mcap_cad_m": 60.0, "runway_months": 18.0,
            "dilution_annual": 0.08, "cash_cad_m": 20.0,
            "stressed_in_ground_cad_m": 40.0, "ev_cad_m": 50.0}
    base.update(kw)
    return base


def _no_anchor(arch, stage, commodity):
    return {"archetype": arch, "stage": stage, "stub": True}


class SlotFitTests(unittest.TestCase):
    def test_slot_fit_is_the_first_gate(self):
        res = ds.screen([_cand(vehicle="royalty")], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertEqual(res["killed"][0]["gate"], "slot_fit")
        self.assertEqual(res["gate_order"][0], "slot_fit")

    def test_identity_gates_fail_closed(self):
        res = ds.screen([_cand(vehicle=None)], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertIn("fail-closed", res["killed"][0]["reason"])
        res = ds.screen([_cand(stage=None)], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertEqual(res["killed"][0]["gate"], "stage_window")

    def test_stage_window_per_slot(self):
        # a PFS developer is PAST the silver-spear window (PEA-or-earlier)...
        res = ds.screen([_cand(stage="pfs")], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertEqual(res["killed"][0]["gate"], "stage_window")
        # ...but a producing royalty has NO stage window in the ballast slot
        roy = _cand(slots=["gold-royalty-ballast"], vehicle="royalty", commodity="gold",
                    stage="producer")
        res = ds.screen([roy], slot="gold-royalty-ballast", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)


class NovelSlotTests(unittest.TestCase):
    """A slot the taxonomy doesn't know is not a dead end: it's screened on QUALITY (slot-identity gates
    skipped, like satellite) and FLAGGED novel, so the operator can formalize it or hold a satellite."""

    def test_unknown_slot_screens_on_quality_and_flags_novel(self):
        res = ds.screen([_cand()], slot="lithium-brine-royalty", anchor_fn=_no_anchor)
        self.assertEqual(res.get("novel_slot"), "lithium-brine-royalty")
        self.assertTrue(res["off_slot"])
        self.assertEqual(res["n_survivors"], 1)            # NOT dead-ended on "unknown slot"
        self.assertIn("not in the taxonomy", res["note"].lower())

    def test_quality_gates_still_apply_under_a_novel_slot(self):
        # only the slot-IDENTITY gates are skipped — a foreign listing must STILL be killed
        res = ds.screen([_cand(ticker="FRES.L")], slot="lithium-brine-royalty", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 0)
        self.assertEqual(res["killed"][0]["gate"], "listing")

    def test_novel_slot_ignores_a_tag_mismatch(self):
        # candidate tagged silver-spear; a novel-slot screen must not kill it on the tag (identity skipped)
        res = ds.screen([_cand(slots=["silver-spear"])], slot="copper-explorer-v2", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)

    def test_known_slot_is_not_flagged_novel(self):
        res = ds.screen([_cand()], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertNotIn("novel_slot", res)
        self.assertFalse(res["off_slot"])

    def test_satellite_is_off_slot_but_not_novel(self):
        res = ds.screen([_cand()], slot="satellite", anchor_fn=_no_anchor)
        self.assertTrue(res["off_slot"])
        self.assertNotIn("novel_slot", res)                # an intentional off-slot screen, not unknown


class ListingGateTests(unittest.TestCase):
    """US + Canada only — foreign primary listings are killed at the listing gate, ahead of
    jurisdiction/valuation; the suffix allowlist is operator-configurable via screen_config."""

    def test_foreign_listings_are_killed(self):
        for tk in ("FRES.L", "HOC.L", "EMR.AX", "0857.HK"):
            res = ds.screen([_cand(ticker=tk)], slot="silver-spear", anchor_fn=_no_anchor)
            self.assertEqual(res["killed"][0]["gate"], "listing", f"{tk} should die at listing")
            self.assertIn("US + Canada", res["killed"][0]["reason"])

    def test_north_american_listings_pass(self):
        for tk in ("AGA.V", "ABRA.TO", "FOO.CN", "BAR.NE", "PAAS.OTC", "GROY"):
            res = ds.screen([_cand(ticker=tk)], slot="silver-spear", anchor_fn=_no_anchor)
            self.assertEqual(res["n_survivors"], 1, f"{tk} should survive the listing gate")

    def test_missing_ticker_fails_closed(self):
        res = ds.screen([_cand(ticker=None)], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertEqual(res["killed"][0]["gate"], "listing")
        self.assertIn("fail-closed", res["killed"][0]["reason"])

    def test_allowlist_is_configurable(self):
        res = ds.screen([_cand(ticker="FRES.L")], slot="silver-spear",
                        gates={"allowed_ticker_suffixes": ["V", "TO", "L"]}, anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)


class NumericGateTests(unittest.TestCase):
    def test_each_kill_names_its_gate(self):
        cases = [
            (_cand(fraser_index=30.0), "jurisdiction"),
            (_cand(mcap_cad_m=2_000.0), "mcap_band"),
            (_cand(runway_months=2.0), "survival"),
            (_cand(dilution_annual=0.50), "survival"),
            (_cand(cash_cad_m=1.0, stressed_in_ground_cad_m=2.0, ev_cad_m=100.0),
             "rep_floor_coverage"),
        ]
        for cand, gate in cases:
            res = ds.screen([cand], slot="silver-spear", anchor_fn=_no_anchor)
            self.assertEqual(res["killed"][0]["gate"], gate, f"expected kill at {gate}")
            self.assertTrue(res["killed"][0]["reason"])

    def test_missing_numeric_data_passes_with_named_gaps(self):
        cand = _cand(fraser_index=None, runway_months=None, ev_cad_m=None)
        res = ds.screen([cand], slot="silver-spear", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)
        gaps = res["survivors"][0]["data_gaps"]
        self.assertIn("fraser_index", gaps)
        self.assertIn("runway_months", gaps)
        self.assertIn("rep_floor_coverage", gaps)

    def test_survivor_carries_anchor_and_coverage(self):
        res = ds.screen([_cand()], slot="silver-spear", anchor_fn=_no_anchor)
        s = res["survivors"][0]
        self.assertEqual(s["anchor"]["archetype"], "option_convexity")
        self.assertAlmostEqual(s["rep_floor_coverage"], (20 + 40) / 50, places=3)

    def test_gate_overrides(self):
        res = ds.screen([_cand(fraser_index=50.0)], slot="silver-spear",
                        gates={"fraser_min": 40.0}, anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)


class UniverseFileTests(unittest.TestCase):
    def test_seeded_universe_loads_and_brc_fails_stage_gate(self):
        uni = ds.load_universe()
        cands = uni.get("candidates") or []
        self.assertTrue(cands, "data/candidate_universe.json must load")
        res = ds.screen(cands, slot="silver-spear", anchor_fn=_no_anchor)
        killed = {k["ticker"]: k for k in res["killed"]}
        # the seeded peers are PFS/DFS — correctly OUTSIDE the spear's PEA-or-earlier window
        self.assertIn("BRC.V", killed)
        self.assertEqual(killed["BRC.V"]["gate"], "stage_window")


class OffSlotTests(unittest.TestCase):
    """The satellite / off-slot screen — asymmetric bets that DON'T fit a thesis slot (new sleeves /
    satellites outside the barbell): skip the two slot-IDENTITY gates, keep the quality discipline."""

    def test_satellite_skips_the_identity_gates(self):
        # a clean copper developer fits NO thesis slot (dies at slot_fit normally) — satellite surfaces it
        cu = _cand(ticker="CUX.V", slots=["copper-developer"], vehicle="developer", commodity="copper")
        self.assertEqual(ds.screen([cu], slot="silver-spear", anchor_fn=_no_anchor)["n_survivors"], 0)
        res = ds.screen([cu], slot="satellite", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)
        self.assertEqual(res["slot"], "satellite")
        self.assertFalse([k for k in res["killed"] if k["gate"] in ("slot_fit", "stage_window")])

    def test_satellite_is_not_off_discipline(self):
        # off-slot keeps every QUALITY gate: no runway still dies on survival
        broke = _cand(ticker="ZZZ.V", slots=["NONE"], runway_months=0.0)
        res = ds.screen([broke], slot="satellite", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 0)
        self.assertTrue(any(k["gate"] == "survival" for k in res["killed"]))

    def test_satellite_anchors_on_the_candidate_archetype(self):
        cand = _cand(slots=["NONE"], archetype="developer")
        res = ds.screen([cand], slot="satellite", anchor_fn=_no_anchor)
        self.assertEqual(res["survivors"][0]["anchor"]["archetype"], "developer")

    def test_is_off_slot_recognises_aliases(self):
        for s in ("satellite", "off-slot", "OFFSLOT", "none", "any", "freeform"):
            self.assertTrue(ds.is_off_slot(s))
        for s in ("silver-spear", "gold-royalty-ballast", ""):
            self.assertFalse(ds.is_off_slot(s))


class SlotCreationTests(unittest.TestCase):
    """Runtime-extensible taxonomy: create a slot from the TUI (data, not code), keep it gradeable."""

    def setUp(self):
        self.tmp = os.path.join(tempfile.mkdtemp(), "slots.json")

    def tearDown(self):
        ds.reload_slots(self.tmp + ".gone")            # reset the module globals to seed-only

    def test_add_makes_a_slot_live_and_gradeable(self):
        saved = ds.add_slot("copper-developer", vehicles=["developer"], commodities=["copper"],
                            archetype="option_convexity", path=self.tmp)
        self.assertEqual(saved["archetype"], "option_convexity")
        self.assertIn("copper-developer", ds.SLOT_RULES)               # add_slot reloaded the live taxonomy
        self.assertEqual(ds.SLOT_RULES["copper-developer"]["vehicles"], {"developer"})   # list -> set
        self.assertEqual(ds.SLOT_ARCHETYPE["copper-developer"], "option_convexity")

    def test_screen_accepts_the_created_slot(self):
        ds.add_slot("copper-developer", vehicles=["developer"], commodities=["copper"], path=self.tmp)
        cand = _cand(ticker="CUX.V", slots=["copper-developer"], vehicle="developer", commodity="copper")
        self.assertEqual(ds.screen([cand], slot="copper-developer", anchor_fn=_no_anchor)["n_survivors"], 1)

    def test_seed_slots_are_immutable(self):
        with self.assertRaises(ValueError):
            ds.add_slot("silver-spear", vehicles=["explorer"], path=self.tmp)

    def test_archetype_constrained_to_a_gradeable_one(self):
        saved = ds.add_slot("odd-thing", vehicles=["royalty"], archetype="made_up", path=self.tmp)
        self.assertIn(saved["archetype"], ds.ARCHETYPES)               # not orphaned
        self.assertEqual(saved["archetype"], "asset_light_yield")      # royalty -> asset-light yield

    def test_add_needs_a_vehicle(self):
        with self.assertRaises(ValueError):
            ds.add_slot("no-vehicle", vehicles=[], path=self.tmp)

    def test_draft_from_candidate_is_ready_for_add(self):
        d = ds.draft_slot_from_candidate({"ticker": "CUX.V", "vehicle": "developer", "commodity": "copper"})
        self.assertEqual(d["name"], "copper-developer")
        self.assertEqual(d["vehicles"], ["developer"])
        self.assertEqual(d["commodities"], ["copper"])
        self.assertIn(d["archetype"], ds.ARCHETYPES)
        saved = ds.add_slot(**d, path=self.tmp)                        # the draft feeds add_slot directly
        self.assertEqual(saved["name"], "copper-developer")


class TaxonomyRouterTests(unittest.TestCase):
    """The funnel routes to ALL FIVE engine archetypes (not the spear+ballast pair), and the
    electrification slot admits the diversified-holdco vehicle its doctrine always allowed."""

    def test_archetypes_covers_all_five_engine_classes(self):
        for a in ("option_convexity", "capital_margin", "commodity_cyclical",
                  "asset_light_yield", "pure_macro_delta"):
            self.assertIn(a, ds.ARCHETYPES)

    def test_vehicle_routing_is_archetype_correct(self):
        self.assertEqual(ds.archetype_for_vehicle("physical"), "pure_macro_delta")    # spot beta, NOT yield
        self.assertEqual(ds.archetype_for_vehicle("operator"), "commodity_cyclical")
        self.assertEqual(ds.archetype_for_vehicle("producer"), "commodity_cyclical")
        self.assertEqual(ds.archetype_for_vehicle("royalty"), "asset_light_yield")
        self.assertEqual(ds.archetype_for_vehicle("streamer"), "asset_light_yield")
        self.assertEqual(ds.archetype_for_vehicle("holdco"), "asset_light_yield")
        self.assertEqual(ds.archetype_for_vehicle("developer"), "option_convexity")
        self.assertEqual(ds.archetype_for_vehicle("explorer"), "option_convexity")

    def test_electrification_slot_admits_a_diversified_holdco(self):
        # a copper royalty-holdco now fits the electrification-ballast slot (doctrine parity); before,
        # the {royalty,streamer,physical}-only rule killed it at slot_fit
        holdco = _cand(ticker="ALS.TO", slots=["electrification-royalty"], vehicle="holdco",
                       commodity="copper", stage="producer")
        res = ds.screen([holdco], slot="electrification-royalty", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)
        self.assertFalse([k for k in res["killed"] if k["gate"] == "slot_fit"])

    def test_mcap_band_is_archetype_aware(self):
        # a spear at 2000M is too big (junior band); the SAME size is a FIT for a ballast royalty/holdco
        spear = _cand(mcap_cad_m=2000.0)
        self.assertEqual(ds.screen([spear], slot="silver-spear", anchor_fn=_no_anchor)["killed"][0]["gate"],
                         "mcap_band")
        roy = _cand(ticker="ALS.TO", slots=["electrification-royalty"], vehicle="holdco",
                    commodity="copper", stage="producer", mcap_cad_m=3000.0)
        res = ds.screen([roy], slot="electrification-royalty", anchor_fn=_no_anchor)
        self.assertEqual(res["n_survivors"], 1)
        self.assertFalse([k for k in res["killed"] if k["gate"] == "mcap_band"])

    def test_operator_mcap_override_still_wins(self):
        roy = _cand(ticker="ALS.TO", slots=["electrification-royalty"], vehicle="holdco",
                    commodity="copper", stage="producer", mcap_cad_m=3000.0)
        res = ds.screen([roy], slot="electrification-royalty",
                        gates={"mcap_band_cad_m": [5.0, 500.0]}, anchor_fn=_no_anchor)
        self.assertEqual(res["killed"][0]["gate"], "mcap_band")    # explicit override caps it back


if __name__ == "__main__":
    unittest.main()
