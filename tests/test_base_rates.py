"""
Tests for base_rates.py + the calibration cold-start layer (Forge M7).

Pins: the pure-stdlib Beta/LogNormal interval math is correct; priors report an estimate WITH a
credible interval (never a bare %); Bayesian update moves the posterior toward the data; the cold-start
scorecard leans on priors with wide intervals at low n; and a systematic bias emits a PROPOSAL only.
"""
import unittest

import base_rates as br
import calibration as cal


class NumericsTests(unittest.TestCase):
    def test_betainc_symmetry(self):
        self.assertAlmostEqual(br.betainc(12, 12, 0.5), 0.5, places=4)
        self.assertAlmostEqual(br.beta_ppf(0.5, 12, 12), 0.5, places=4)

    def test_beta_ci_brackets_mean(self):
        lo, hi = br.beta_ci(12, 12, 0.90)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        self.assertAlmostEqual((lo + hi) / 2, 0.5, places=2)     # symmetric prior

    def test_norm_ppf(self):
        self.assertAlmostEqual(br.norm_ppf(0.5), 0.0, places=6)
        self.assertAlmostEqual(br.norm_ppf(0.95), 1.6449, places=3)

    def test_lognormal_ci_brackets_median(self):
        lo, hi = br.lognormal_ci(br.math.log(15.5), 0.30, 0.90)
        self.assertLess(lo, 15.5)
        self.assertGreater(hi, 15.5)


class PriorReportingTests(unittest.TestCase):
    def test_discovery_prior_matches_minex(self):
        e = br.estimate("discovery_to_mine")
        self.assertAlmostEqual(e["mean"], 0.50, places=2)        # MinEx 45% nominal / 50% corrected
        self.assertEqual(e["confidence"], "high")
        self.assertIn("minexconsulting", e["url"])

    def test_grassroots_is_wide_and_low_confidence(self):
        e = br.estimate("grassroots_to_mine")
        self.assertLess(e["mean"], 0.01)                         # ~1 in 1000
        self.assertEqual(e["confidence"], "low")
        lo, hi = e["ci90"]
        self.assertGreater(hi / max(lo, 1e-9), 10)               # spans an order of magnitude

    def test_ma_premium_median_35pct(self):
        e = br.estimate("ma_premium_20d")
        self.assertAlmostEqual(e["median"], 0.35, places=2)      # offset -1 applied

    def test_every_prior_has_a_source_and_interval(self):
        for name in br.PRIORS:
            e = br.estimate(name)
            self.assertTrue(e.get("source"))
            self.assertTrue(e.get("url"))
            self.assertEqual(len(e["ci90"]), 2)                  # never a bare point

    def test_report_is_never_a_bare_percent(self):
        r = br.report("discovery_to_mine")
        self.assertIn("CI", r)                                   # always carries the interval

    def test_stage_cap_decays(self):
        self.assertGreater(br.stage_cap("discovery")["mean"], br.stage_cap("production")["mean"])


class UpdateTests(unittest.TestCase):
    def test_update_moves_toward_data(self):
        up = br.update_beta("discovery_to_mine", 8, 2)           # 80% observed vs 50% prior
        self.assertGreater(up["posterior_mean"], up["prior_mean"])
        self.assertLess(up["posterior_mean"], 0.80)             # but shrunk toward the prior
        self.assertEqual(up["n_data"], 10)

    def test_normal_update_shifts_mean(self):
        up = br.update_normal(0.0, 0.5, [1.0, 1.2, 0.8], 0.4)
        self.assertGreater(up["posterior_mu"], 0.0)
        self.assertEqual(up["n"], 3)


class ColdStartTests(unittest.TestCase):
    def _dec(self, **o):
        d = {"ticker": "AGA.V", "verdict": "BELOW FLOOR — ACCUMULATE", "price": 1.0,
             "legs": {"floor": 0.8, "base": 1.5, "bull": 2.5, "bear": 0.95},
             "archetype": "option_convexity"}
        d.update(o)
        return d

    def test_win_probability_is_interval_not_bare_pct(self):
        wp = cal.win_probability([])                            # zero decisions
        self.assertEqual(len(wp["ci90"]), 2)
        self.assertTrue(wp["cold_start"])
        self.assertEqual(wp["ci90"][0] < wp["mean"] < wp["ci90"][1], True)

    def test_cold_scorecard_surfaces_base_rates(self):
        scored = [cal.score_outcome(self._dec(), 2.5)]          # 1 decision -> COLD
        sc = cal.priored_scorecard(scored)
        self.assertTrue(sc["cold_start"])
        self.assertIn("option_convexity", sc["base_rates"])     # mapped to discovery_to_mine
        self.assertIn("discovery_to_mine", sc["reference_priors"])
        self.assertIn("cold_start_note", sc)

    def test_ledger_rejects_widen_n(self):
        scored = [cal.score_outcome(self._dec(), 2.5)]
        rejects = [{"ticker": "X", "wins": 2, "losses": 1}]     # a passed name that mostly fell
        wp = cal.win_probability(scored, ledger_rejects=rejects)
        self.assertEqual(wp["wins"], 1 + 2)
        self.assertEqual(wp["losses"], 0 + 1)

    def test_archetype_base_rate_only_for_researched(self):
        self.assertIsNotNone(cal.archetype_base_rate("option_convexity"))
        self.assertIsNone(cal.archetype_base_rate("asset_light_yield"))   # no invented authority


class BiasProposalTests(unittest.TestCase):
    def _win(self, ret):
        return {"status": "scored", "result": "win" if ret > 0.05 else "scratch",
                "signed_return": ret, "realized_return": ret, "floor_held": True,
                "upside_capture": 0.2, "archetype": "option_convexity"}

    def test_no_proposal_on_cold_sample(self):
        sc = cal.scorecard([self._win(1.0)])                    # n=1, too thin
        sc["n"] = 1
        self.assertEqual(cal.bias_proposals(sc), [])

    def test_conservative_floor_emits_proposal_not_apply(self):
        # 6 winners, floors always held, zero losses -> propose easing conservatism (never apply)
        scored = [self._win(1.0) for _ in range(6)]
        sc = cal.scorecard(scored)
        props = cal.bias_proposals(sc)
        self.assertTrue(any(p.get("key") == "conservatism_scalar" for p in props))
        self.assertTrue(all("PROPOSAL" in p["reason"] or p.get("kind") == "review" for p in props))

    def test_under_betting_emits_review_item(self):
        scored = [self._win(0.10) for _ in range(5)]            # wins but tiny capture (0.2)
        sc = cal.scorecard(scored)
        props = cal.bias_proposals(sc)
        self.assertTrue(any(p.get("kind") == "review" for p in props))


if __name__ == "__main__":
    unittest.main(verbosity=2)
