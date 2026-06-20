"""Tests for regime_lens (Regime Engine v2, G1+G2) — two-lens split + shared curve tell."""
import unittest

import regime_lens as rl


# A live-shaped tape (today's fixture): broad calm, metals headwind from real yield.
LIVE_TAPE = {"signals": [
    {"key": "gsr", "label": "Gold/Silver", "value": 64.29, "bias": "risk_on", "read": "Silver leadership"},
    {"key": "cu_au", "label": "Copper/Gold", "value": 1.52, "bias": "risk_on", "read": "Growth/reflation bid"},
    {"key": "dxy_gold", "label": "DXY/Gold", "value": 24.17, "bias": "risk_on", "read": "Gold dominant"},
    {"key": "dxy", "label": "DXY", "value": 100.8, "bias": "neutral", "read": "Neutral"},
    {"key": "real_yield", "label": "Real Yield", "value": 2.45, "bias": "risk_off", "read": "Headwind"},
    {"key": "sofr_spread", "label": "SOFR", "value": 0.05, "bias": "risk_on", "read": "Funding calm"},
    {"key": "hy_spread", "label": "HY", "value": 2.72, "bias": "risk_on", "read": "Credit benign"},
    {"key": "curve_2s30s", "label": "30Y-10Y", "value": 0.49, "bias": "neutral", "read": "Positive slope"},
    {"key": "vix", "label": "VIX", "value": 16.4, "bias": "neutral", "read": "Normal"},
    {"key": "cftc", "label": "CFTC", "value": 50.0, "bias": "neutral", "read": "Mid-range"},
    {"key": "vix_term", "label": "VIX Term", "value": 1.13, "bias": "risk_on", "read": "Contango"},
]}


class LensPartitionTests(unittest.TestCase):
    def test_every_signal_in_exactly_one_lens(self):
        r = rl.assess(LIVE_TAPE)
        broad = {s["key"] for s in r["broad"]["signals"]}
        metals = {s["key"] for s in r["metals"]["signals"]}
        self.assertFalse(broad & metals, "no signal may feed both lenses")
        self.assertEqual(broad, {"vix", "vix_term", "hy_spread", "sofr_spread", "cftc"})
        self.assertEqual(metals, {"real_yield", "dxy_gold", "gsr", "cu_au", "curve_2s30s", "dxy"})

    def test_metals_drives_conviction(self):
        r = rl.assess(LIVE_TAPE)
        self.assertTrue(r["metals"]["drives_conviction"])
        self.assertEqual(r["broad"]["role"], "context")
        self.assertEqual(r["drives_conviction"], "metals")


class DivergenceTests(unittest.TestCase):
    def test_live_broad_riskon_metals_not(self):
        # the core G1 acceptance: broad reads risk-on, metals reads mixed-to-headwind, divergence flagged.
        r = rl.assess(LIVE_TAPE)
        self.assertEqual(r["broad"]["label"], "RISK-ON")
        self.assertIn(r["metals"]["label"], ("MIXED", "HEADWIND"))
        self.assertTrue(r["divergence"])

    def test_real_yield_headwind_foregrounded(self):
        r = rl.assess(LIVE_TAPE)
        ry = next(s for s in r["metals"]["signals"] if s["key"] == "real_yield")
        self.assertEqual(ry["score"], -1.0)
        self.assertIn("Headwind", ry["read"])

    def test_agreement_when_metals_also_supportive(self):
        tape = {"signals": [
            {"key": "real_yield", "value": 0.2, "bias": "risk_on"},   # low RY -> supportive
            {"key": "dxy_gold", "value": 24.0, "bias": "risk_on"},     # gold strong -> supportive
            {"key": "dxy", "value": 98.0, "bias": "risk_on"},          # soft dollar -> supportive
            {"key": "vix", "value": 13.0, "bias": "risk_on"},
            {"key": "hy_spread", "value": 2.5, "bias": "risk_on"},
        ]}
        r = rl.assess(tape)
        self.assertEqual(r["metals"]["label"], "SUPPORTIVE")
        self.assertFalse(r["divergence"])


class CurveTellG2Tests(unittest.TestCase):
    def test_bear_steepener_active_scores_metals_caution(self):
        r = rl.assess(LIVE_TAPE, bear_steepener=True)
        curve = next(s for s in r["metals"]["signals"] if s["key"] == "curve_2s30s")
        self.assertEqual(curve["score"], -1.0)
        self.assertIn("fiscal-dominance", curve["read"])
        self.assertTrue(r["curve_tell"]["bear_steepener"])

    def test_curve_dormant_when_no_steepener(self):
        r = rl.assess(LIVE_TAPE, bear_steepener=False)
        curve = next(s for s in r["metals"]["signals"] if s["key"] == "curve_2s30s")
        self.assertEqual(curve["score"], 0.0)
        self.assertIn("dormant", curve["read"])

    def test_reads_flag_from_rates_dashboard(self):
        # G2: same flag the P2.1 dashboard / P3 engine consume — no divergent curve interpretation.
        r = rl.assess(LIVE_TAPE, rates={"bear_steepener": {"active": True}})
        self.assertTrue(r["curve_tell"]["bear_steepener"])
        self.assertEqual(r["curve_tell"]["shared_with"], "rates_dashboard.bear_steepener + scenario.weights.B")


class G3ReadTests(unittest.TestCase):
    def test_gsr_never_claims_leadership(self):
        r = rl.assess(LIVE_TAPE)
        gsr = next(s for s in r["metals"]["signals"] if s["key"] == "gsr")
        self.assertNotIn("leadership", gsr["read"].lower())
        self.assertIn("cheap", gsr["read"].lower())

    def test_dxy_gold_label_and_bias_agree(self):
        r = rl.assess(LIVE_TAPE)
        dg = next(s for s in r["metals"]["signals"] if s["key"] == "dxy_gold")
        self.assertEqual(dg["score"], 1.0)                 # gold strong -> metals-supportive (consistent)
        self.assertIn("Gold strong", dg["read"])

    def test_copper_gold_supply_caveat(self):
        r = rl.assess(LIVE_TAPE)
        cu = next(s for s in r["metals"]["signals"] if s["key"] == "cu_au")
        self.assertEqual(cu["score"], 0.0)                 # not scored as a clean reflation read
        self.assertIn("supply", cu["read"].lower())


class StructureTests(unittest.TestCase):
    def test_weights_are_config(self):
        # emphasising real_yield (config, proposal-gated) tips the live metals lens to HEADWIND.
        r = rl.assess(LIVE_TAPE, config={"regime_lens": {"weights": {"real_yield": 4.0}}})
        self.assertEqual(r["metals"]["label"], "HEADWIND")

    def test_glossary_and_empty(self):
        r = rl.assess([])
        self.assertIn("metals", r["glossary"])
        self.assertEqual(r["metals"]["signals"], [])


if __name__ == "__main__":
    unittest.main()
