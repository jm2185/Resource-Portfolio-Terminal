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


class MetalsLensViewTests(unittest.TestCase):
    """The destination 'read the metals lens' points at — built straight from assess()."""

    def test_view_explains_drivers_and_divergence(self):
        lens = rl.assess(LIVE_TAPE)
        title, body = rl.metals_lens_view(lens)
        self.assertIn("METALS LENS", title)
        self.assertIn("drives conviction", body.lower())
        self.assertIn("Real Yield", body)                  # each metals driver's read is surfaced…
        self.assertIn("Headwind", body)                    # …in plain language
        self.assertNotIn("[", body)                        # no stray brackets -> Rich markup is safe
        self.assertTrue(lens.get("divergence"))
        self.assertIn("DIVERGENCE", body)

    def test_view_degrades_on_empty(self):
        for empty in ({}, None):
            title, body = rl.metals_lens_view(empty)
            self.assertIn("METALS LENS", title)
            self.assertIn("hasn't been computed", body)    # honest 'not ready', never a blank popup

    def test_view_lists_every_metals_signal(self):
        lens = rl.assess(LIVE_TAPE)
        n_metals = len(lens["metals"]["signals"])
        body = rl.metals_lens_view(lens)[1]
        self.assertEqual(body.count("  • "), n_metals)     # one bullet per metals driver


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


class NewSignalLensTests(unittest.TestCase):
    """The two VP+ tells: net liquidity (broad/flows lens, scored off its bias) and 10Y breakeven
    (metals lens, level-scored — high = debasement tailwind, low = disinflation headwind)."""

    TAPE = {"signals": [
        {"key": "net_liq", "label": "Fed Net Liquidity", "value": 5.40, "bias": "risk_off", "read": "draining"},
        {"key": "breakeven", "label": "10Y Breakeven", "value": 2.60, "bias": "risk_on", "read": "elevated"},
        {"key": "vix", "label": "VIX", "value": 16.0, "bias": "neutral", "read": "Normal"},
    ]}

    def test_net_liq_is_broad_scored_off_bias(self):
        r = rl.assess(self.TAPE)
        nl = next(s for s in r["broad"]["signals"] if s["key"] == "net_liq")
        self.assertEqual(nl["score"], -1.0)               # risk_off bias → −1 in the broad lens
        self.assertNotIn("net_liq", {s["key"] for s in r["metals"]["signals"]})

    def test_breakeven_is_metals_and_level_scored(self):
        r = rl.assess(self.TAPE)
        be = next(s for s in r["metals"]["signals"] if s["key"] == "breakeven")
        self.assertEqual(be["score"], 1.0)                # 2.60 ≥ be_hot 2.50 → debasement tailwind
        self.assertIn("debasement", be["read"].lower())

    def test_breakeven_cold_is_headwind(self):
        tape = {"signals": [{"key": "breakeven", "value": 1.90, "bias": "risk_off"}]}
        be = next(s for s in rl.assess(tape)["metals"]["signals"] if s["key"] == "breakeven")
        self.assertEqual(be["score"], -1.0)               # ≤ be_cold 2.00 → disinflation headwind
        self.assertIn("headwind", be["read"].lower())

    def test_partition_holds_for_new_keys(self):
        r = rl.assess(self.TAPE)
        broad = {s["key"] for s in r["broad"]["signals"]}
        metals = {s["key"] for s in r["metals"]["signals"]}
        self.assertIn("net_liq", broad)
        self.assertIn("breakeven", metals)
        self.assertFalse(broad & metals)


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
