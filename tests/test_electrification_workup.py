"""Tests for electrification_workup (action-plan P5.3) — the slot-fit-first uranium-vehicle work-up."""
import unittest

import electrification_workup as ew


class SlotFitTests(unittest.TestCase):
    def test_uranium_royalty_fits(self):
        f = ew.slot_fit({"ticker": "X", "vehicle": "royalty", "commodities": ["uranium"]})
        self.assertTrue(f["fit"])
        self.assertEqual(f["verdict"], "slot-FIT")

    def test_physical_holding_fits(self):
        # a physical uranium holding trust IS ballast (the manual: physical/holding vehicle fits).
        f = ew.slot_fit({"ticker": "SPUT", "vehicle": "physical_holding", "commodities": ["uranium"]})
        self.assertTrue(f["fit"])

    def test_direct_operator_is_mismatch(self):
        f = ew.slot_fit({"ticker": "MINER", "vehicle": "operator", "commodities": ["uranium"]})
        self.assertFalse(f["fit"])
        self.assertFalse(next(g["pass"] for g in f["gates"] if g["gate"] == "ballast_stability"))

    def test_no_electrification_exposure_is_mismatch(self):
        f = ew.slot_fit({"ticker": "GOLDR", "vehicle": "royalty", "commodities": ["gold"]})
        self.assertFalse(f["fit"])
        self.assertFalse(next(g["pass"] for g in f["gates"] if g["gate"] == "electrification_exposure"))

    def test_volatile_pure_spot_beta_is_mismatch(self):
        f = ew.slot_fit({"ticker": "LEVU", "vehicle": "etf", "commodities": ["uranium"],
                         "volatility": "high"})
        self.assertFalse(f["fit"])

    def test_copper_streamer_fits(self):
        f = ew.slot_fit({"ticker": "CUSTREAM", "vehicle": "streamer", "commodities": ["copper", "cobalt"]})
        self.assertTrue(f["fit"])
        self.assertIn("copper", f["exposure"])


class WorkupTests(unittest.TestCase):
    def setUp(self):
        self.cands = [
            {"ticker": "URANROY", "vehicle": "royalty", "commodities": ["uranium", "copper", "lithium"],
             "discount_to_nav": 0.30},                                   # broad + cheap fitter
            {"ticker": "BIGMINER", "vehicle": "operator", "commodities": ["uranium"],
             "discount_to_nav": 0.50},                                   # cheapest but a MISMATCH (operator)
            {"ticker": "GOLDONLY", "vehicle": "royalty", "commodities": ["gold"]},   # no electrification
        ]

    def test_mismatches_flagged_even_when_cheap(self):
        r = ew.workup(self.cands)
        self.assertIn("BIGMINER", r["mismatches"])      # cheapest, but operator -> mismatch
        self.assertIn("GOLDONLY", r["mismatches"])
        self.assertNotIn("BIGMINER", [f["ticker"] for f in r["fitters"]])

    def test_best_fit_is_the_slot_fitter(self):
        r = ew.workup(self.cands)
        self.assertEqual(r["best_fit"], "URANROY")

    def test_swap_candidate_when_challenger_outscores_incumbent(self):
        # a broad, cheap, royalty challenger vs a narrow uranium-only incumbent royalty.
        r = ew.workup([{"ticker": "BROADROY", "vehicle": "royalty",
                        "commodities": ["uranium", "copper", "nickel"], "discount_to_nav": 0.35}],
                      incumbent={"ticker": "URC.TO", "vehicle": "royalty",
                                 "commodities": ["uranium"], "volatility": "low"})
        self.assertEqual(r["recommendation"], "SWAP-CANDIDATE")
        self.assertEqual(r["feeds"], "/rotate")

    def test_augment_when_complementary_exposure(self):
        # a fitter that adds metals the incumbent lacks but doesn't clear the swap margin -> AUGMENT.
        r = ew.workup([{"ticker": "COPONLY", "vehicle": "royalty", "commodities": ["uranium", "copper"]}],
                      incumbent={"ticker": "URC.TO", "vehicle": "royalty",
                                 "commodities": ["uranium"], "discount_to_nav": 0.30},
                      config={"electrification_workup": {"swap_margin": 0.5}})  # huge margin -> not SWAP
        self.assertEqual(r["recommendation"], "AUGMENT")

    def test_hold_when_no_fitter(self):
        r = ew.workup([{"ticker": "GOLDONLY", "vehicle": "royalty", "commodities": ["gold"]}])
        self.assertEqual(r["recommendation"], "HOLD")
        self.assertIsNone(r["best_fit"])

    def test_default_incumbent_is_urc(self):
        r = ew.workup([])
        self.assertEqual(r["incumbent"]["ticker"], "URC.TO")


class StructureTests(unittest.TestCase):
    def test_glossary_and_note(self):
        r = ew.workup([{"ticker": "X", "vehicle": "royalty", "commodities": ["uranium"]}])
        self.assertIn("electrification_workup", r["glossary"])
        self.assertIn("slot-fit", r["note"].lower())

    def test_empty_graceful(self):
        r = ew.workup(None)
        self.assertEqual(r["fitters"], [])
        self.assertEqual(r["recommendation"], "HOLD")


if __name__ == "__main__":
    unittest.main()
