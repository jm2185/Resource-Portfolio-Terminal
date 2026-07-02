"""
Tests for stage-normalized peer EV/oz (peer_normalization.py).

Pure-stdlib. Pins the core idea the user asked for: a more-advanced peer (BRC.V — sole-focus,
further down the de-risking curve, adjacent to AGA.V/Hughes) must be DISCOUNTED to the target's
stage before its EV/oz anchors a less-advanced name, never applied raw.
"""
import unittest

import peer_normalization as pn


class StageFactorTests(unittest.TestCase):
    def test_curve_is_monotonic_along_the_lassonde_path(self):
        path = ["grassroots", "exploration", "delineation", "pre_pea", "pea", "pfs", "dfs", "producer"]
        vals = [pn.stage_factor(s) for s in path]
        self.assertEqual(vals, sorted(vals))                 # de-risking premium rises with stage
        self.assertLess(vals[-1] / vals[1], 6.0)             # but bounded (sanity, not a 100x curve)

    def test_synonyms_and_spacing_tolerated(self):
        self.assertEqual(pn.stage_factor("PEA"), pn.stage_factor("pea"))
        self.assertEqual(pn.stage_factor("Pre-Feasibility"), pn.stage_factor("pfs"))
        self.assertEqual(pn.stage_factor("Pre PEA"), pn.stage_factor("pre_pea"))

    def test_unknown_stage_is_zero_not_invented(self):
        self.assertEqual(pn.stage_factor("nonsense"), 0.0)
        self.assertEqual(pn.stage_factor(None), 0.0)
        self.assertEqual(pn.stage_factor(""), 0.0)


class NormalizeTests(unittest.TestCase):
    def test_more_advanced_peer_is_discounted_to_target(self):
        # BRC.V richer (PFS) EV/oz normalized down to AGA's pre-PEA stage
        norm, factor = pn.normalize_ev_oz(3.00, peer_stage="pfs", target_stage="pre_pea")
        self.assertLess(factor, 1.0)
        self.assertLess(norm, 3.00)
        self.assertAlmostEqual(factor, pn.stage_factor("pre_pea") / pn.stage_factor("pfs"))

    def test_less_advanced_peer_is_lifted_to_target(self):
        norm, factor = pn.normalize_ev_oz(1.00, peer_stage="exploration", target_stage="pea")
        self.assertGreater(factor, 1.0)
        self.assertGreater(norm, 1.00)

    def test_same_stage_is_identity(self):
        norm, factor = pn.normalize_ev_oz(2.20, peer_stage="pea", target_stage="pea")
        self.assertAlmostEqual(factor, 1.0)
        self.assertAlmostEqual(norm, 2.20)

    def test_unknown_stage_falls_back_to_neutral_not_a_fabricated_gap(self):
        norm, factor = pn.normalize_ev_oz(2.0, peer_stage="???", target_stage="pre_pea")
        self.assertEqual((norm, factor), (2.0, 1.0))


class EffectiveOzTests(unittest.TestCase):
    def test_inferred_is_haircut_vs_indicated(self):
        # AGA.V: 10.3M indicated + 236.3M inferred -> inferred dominates but at half weight
        eff = pn.effective_oz(10.3e6, 236.3e6, mi_weight=1.0, inf_weight=0.5)
        self.assertAlmostEqual(eff, 10.3e6 + 0.5 * 236.3e6)
        self.assertLess(eff, 10.3e6 + 236.3e6)               # not credited as if all M&I

    def test_negative_and_missing_are_safe(self):
        self.assertEqual(pn.effective_oz(0, 0), 0.0)
        self.assertEqual(pn.effective_oz(None, None), 0.0)


class BlendTests(unittest.TestCase):
    def _peers(self):
        # raw EV/oz rising with stage (the market already pays the de-risking premium)
        return [
            {"ticker": "BRC.V", "ev_oz": 3.20, "stage": "pfs", "weight": 1.0},   # adjacent prime comp, full weight
            {"ticker": "ABRA.V", "ev_oz": 4.00, "stage": "dfs", "weight": 0.5},
            {"ticker": "SSV.V", "ev_oz": 2.40, "stage": "pfs", "weight": 0.5},
            {"ticker": "DV.V", "ev_oz": 1.60, "stage": "pea", "weight": 0.5},
        ]

    def test_blend_normalizes_then_weights(self):
        out = pn.blended_peer_ev_oz(self._peers(), target_stage="pre_pea")
        self.assertTrue(out["sourced"])
        self.assertEqual(out["n_peers"], 4)
        # every advanced peer normalized BELOW its raw EV/oz at the earlier target stage
        for tkr, d in out["peers"].items():
            self.assertLess(d["normalized_ev_oz"], d["raw_ev_oz"], tkr)
        # blended sits below the raw average (we de-rated advanced peers to AGA's stage)
        raw_avg = sum(p["ev_oz"] for p in self._peers()) / 4
        self.assertLess(out["blended_ev_oz"], raw_avg)

    def test_brc_full_weight_dominates_vs_downweighted_peers(self):
        peers = self._peers()
        out = pn.blended_peer_ev_oz(peers, target_stage="pre_pea")
        self.assertAlmostEqual(out["peers"]["BRC.V"]["weight"], 1.0)
        # BRC carries 1.0 / (1.0+0.5+0.5+0.5) = 40% of the blend — not liquidity-suppressed
        self.assertAlmostEqual(out["peers"]["BRC.V"]["weight"] / 2.5, 0.40)

    def test_empty_or_bad_peers_fall_back_to_default(self):
        out = pn.blended_peer_ev_oz([], target_stage="pre_pea", default=2.5)
        self.assertFalse(out["sourced"])
        self.assertEqual(out["blended_ev_oz"], 2.5)
        out2 = pn.blended_peer_ev_oz([{"ticker": "X", "ev_oz": 0, "stage": "pea"}], target_stage="pea")
        self.assertFalse(out2["sourced"])

    def test_zero_weight_peer_excluded(self):
        peers = self._peers() + [{"ticker": "Z", "ev_oz": 9.9, "stage": "pea", "weight": 0.0}]
        out = pn.blended_peer_ev_oz(peers, target_stage="pre_pea")
        self.assertNotIn("Z", out["peers"])


class OutlierDegenerateMADTests(unittest.TestCase):
    """Audit F5: at n=4 a wild peer among 3 identical ones degenerates MAD to 0; the old
    `if mad > 0` guard silently skipped detection. The MeanAD fallback must catch it + note it."""

    def test_wild_outlier_caught_when_mad_degenerates(self):
        peers = [{"ticker": "A", "ev_oz": 1.0, "stage": "pea"},
                 {"ticker": "B", "ev_oz": 1.0, "stage": "pea"},
                 {"ticker": "C", "ev_oz": 1.0, "stage": "pea"},
                 {"ticker": "WILD", "ev_oz": 100.0, "stage": "pea"}]
        out = pn.blended_peer_ev_oz(peers, "pea")
        flagged = {o["ticker"] for o in out.get("outliers", [])}
        self.assertIn("WILD", flagged)
        wild = next(o for o in out["outliers"] if o["ticker"] == "WILD")
        self.assertEqual(wild["method"], "meanad_fallback")
        self.assertIn("MAD degenerated", out.get("outlier_note", ""))   # never silent
        self.assertTrue(out["peers"]["WILD"]["outlier"])                # down-weighted, not dropped

    def test_normal_dispersion_uses_mad_not_fallback(self):
        peers = [{"ticker": t, "ev_oz": ev, "stage": "pea"}
                 for t, ev in (("A", 1.0), ("B", 1.1), ("C", 0.9), ("D", 1.05), ("WILD", 50.0))]
        out = pn.blended_peer_ev_oz(peers, "pea")
        wild = next(o for o in out["outliers"] if o["ticker"] == "WILD")
        self.assertEqual(wild["method"], "mad")
        self.assertNotIn("outlier_note", out)          # MAD was healthy


class PeerAuditTests(unittest.TestCase):
    """Phase-5 peer-comp audit extensions: outlier down-weighting (never dropping), dispersion,
    leave-one-out sensitivity, and the comp audit over engine details."""

    PEERS = [
        {"ticker": "P1", "ev_oz": 1.0, "stage": "pea"},
        {"ticker": "P2", "ev_oz": 1.1, "stage": "pea"},
        {"ticker": "P3", "ev_oz": 0.9, "stage": "pea"},
        {"ticker": "P4", "ev_oz": 1.05, "stage": "pea"},
    ]

    def test_outlier_flagged_and_downweighted_never_dropped(self):
        peers = self.PEERS + [{"ticker": "WILD", "ev_oz": 30.0, "stage": "pea"}]
        res = pn.blended_peer_ev_oz(peers, "pea")
        self.assertTrue(res["outliers"])
        self.assertEqual(res["outliers"][0]["ticker"], "WILD")
        self.assertIn("WILD", res["peers"])                # visible, not silently dropped
        self.assertTrue(res["peers"]["WILD"]["outlier"])
        self.assertAlmostEqual(res["peers"]["WILD"]["weight"], pn.OUTLIER_DOWNWEIGHT, places=4)
        clean = pn.blended_peer_ev_oz(self.PEERS, "pea")["blended_ev_oz"]
        self.assertLess(abs(res["blended_ev_oz"] - clean), 30.0 / 5 - clean)  # influence capped

    def test_no_outlier_logic_below_min_n(self):
        peers = self.PEERS[:2] + [{"ticker": "WILD", "ev_oz": 30.0, "stage": "pea"}]
        res = pn.blended_peer_ev_oz(peers, "pea")
        self.assertNotIn("outliers", res)                  # 3 peers: no robust center to deviate from

    def test_dispersion_and_leave_one_out(self):
        res = pn.blended_peer_ev_oz(self.PEERS, "pea")
        self.assertIn("dispersion", res)
        self.assertGreater(res["dispersion"]["rel_dispersion"], 0)
        self.assertIn("sensitivity", res)
        self.assertIn(res["max_swing_peer"], res["sensitivity"])

    def test_comp_audit_over_engine_details(self):
        details = {"P1": {"adjusted_ev_oz": 1.0, "weight_used": 0.5},
                   "P2": {"adjusted_ev_oz": 2.0, "weight_used": 0.5}}
        audit = pn.comp_audit(details)
        self.assertEqual(audit["n_peers"], 2)
        self.assertGreater(audit["rel_dispersion"], 0)
        self.assertIn(audit["max_swing_peer"], ("P1", "P2"))
        self.assertIsNone(pn.comp_audit({"P1": {"adjusted_ev_oz": 1.0, "weight_used": 1.0}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
