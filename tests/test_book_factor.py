"""book_factor — the read-only concentration + scenario-coverage gauges that turn a 'you're one bet
wearing different tickers / your scenarios have holes' critique into measured fact."""
import unittest

import book_factor as bf


# A book that is diversified by NAME but concentrated in one factor — high pairwise correlations.
SINGLE_FACTOR_CORR = {
    "AGA.V":  {"GROY": 0.74, "GMX.TO": 0.69, "URC.TO": 0.66},
    "GROY":   {"AGA.V": 0.74, "GMX.TO": 0.71, "URC.TO": 0.62},
    "GMX.TO": {"AGA.V": 0.69, "GROY": 0.71, "URC.TO": 0.58},
    "URC.TO": {"AGA.V": 0.66, "GROY": 0.62, "GMX.TO": 0.58},
}
BOOK = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]


class FactorConcentrationTests(unittest.TestCase):
    def test_high_pairwise_reads_single_factor(self):
        r = bf.factor_concentration(SINGLE_FACTOR_CORR, BOOK, spear="AGA.V")
        self.assertTrue(r["available"])
        self.assertTrue(r["single_factor"])                 # avg ρ well above 0.60
        self.assertGreater(r["avg_pairwise"], 0.6)
        self.assertEqual(set(r["spear_corr"]), {"GROY", "GMX.TO", "URC.TO"})
        self.assertIn("one factor", r["read"].lower())

    def test_low_pairwise_reads_multi_factor(self):
        corr = {"AGA.V": {"SPY": 0.05, "TLT": -0.10}, "SPY": {"AGA.V": 0.05, "TLT": -0.2},
                "TLT": {"AGA.V": -0.10, "SPY": -0.2}}
        r = bf.factor_concentration(corr, ["AGA.V", "SPY", "TLT"], spear="AGA.V")
        self.assertFalse(r["single_factor"])
        self.assertLess(r["avg_pairwise"], 0.6)

    def test_ballast_correlated_to_spear_is_flagged(self):
        corr = {"AGA.V": {"GROY": 0.91}, "GROY": {"AGA.V": 0.91}}
        r = bf.factor_concentration(corr, ["AGA.V", "GROY"], spear="AGA.V")
        self.assertEqual(len(r["flags"]), 1)                 # 0.91 ≥ 0.85 → stopped being ballast
        self.assertEqual(r["flags"][0]["ticker"], "GROY")

    def test_symmetric_lookup_and_missing_data(self):
        # only one direction stored — the lookup must find the transpose
        r = bf.factor_concentration({"AGA.V": {"GROY": 0.8}}, ["AGA.V", "GROY"], spear="AGA.V")
        self.assertEqual(r["spear_corr"]["GROY"], 0.8)
        # no correlations at all → graceful n/a, not a crash
        r2 = bf.factor_concentration({}, ["AGA.V", "GROY"], spear="AGA.V")
        self.assertFalse(r2["available"])
        self.assertIsNone(r2["avg_pairwise"])

    def test_threshold_is_config(self):
        r = bf.factor_concentration(SINGLE_FACTOR_CORR, BOOK,
                                    config={"book_factor": {"single_factor_corr": 0.95}})
        self.assertFalse(r["single_factor"])                 # raise the bar → no longer "single factor"


class ScenarioCoverageTests(unittest.TestCase):
    def _scenario_result(self):
        # the resource book: strong in A/B (debasement, fiscal stress), HEADWIND in C (AI-productivity)
        return {
            "weights": {"A": 0.34, "B": 0.22, "C": 0.30, "D": 0.14},
            "scenarios": {"C": {"name": "AI-productivity muddle-through-WIN"}},
            "rankings": [
                {"ticker": "AGA.V", "book_weight": 0.60, "payoffs": {"A": 0.8, "B": 1.0, "C": -0.7, "D": 0.2}},
                {"ticker": "GROY", "book_weight": 0.20, "payoffs": {"A": 0.7, "B": 0.7, "C": -0.2, "D": 0.1}},
                {"ticker": "GMX.TO", "book_weight": 0.20, "payoffs": {"A": 0.4, "B": 0.1, "C": -0.1, "D": 0.5}},
            ],
        }

    def test_uncovered_weight_and_holes(self):
        r = bf.scenario_coverage(self._scenario_result())
        self.assertTrue(r["available"])
        self.assertEqual(r["by_scenario"]["A"]["status"], "covered")
        self.assertEqual(r["by_scenario"]["C"]["status"], "headwind")   # book payoff < 0 in scenario C
        self.assertIn("C", [h["scenario"] for h in r["holes"]])
        self.assertAlmostEqual(r["uncovered_weight"], 0.30, places=2)   # C's 30% weight is the hole
        self.assertIn("30%", r["read"])

    def test_book_weighted_not_equal_weighted(self):
        # the spear is 60% — a deeply negative spear payoff should dominate the book payoff
        r = bf.scenario_coverage(self._scenario_result())
        # C payoff = 0.6*-0.7 + 0.2*-0.2 + 0.2*-0.1 = -0.48
        self.assertAlmostEqual(r["by_scenario"]["C"]["book_payoff"], -0.48, places=2)

    def test_no_held_names_is_graceful(self):
        r = bf.scenario_coverage({"weights": {"A": 1.0}, "rankings": []})
        self.assertFalse(r["available"])
        self.assertEqual(r["uncovered_weight"], 0.0)

    def test_eval_only_names_excluded(self):
        sr = {"weights": {"A": 0.5, "C": 0.5},
              "rankings": [{"ticker": "AGA.V", "book_weight": 1.0, "payoffs": {"A": 0.8, "C": -0.7}},
                           {"ticker": "OGN.V", "book_weight": None, "payoffs": {"A": 0.9, "C": 0.9}}]}
        r = bf.scenario_coverage(sr)
        # OGN.V (eval, no book_weight) must NOT rescue scenario C's coverage
        self.assertEqual(r["by_scenario"]["C"]["status"], "headwind")


if __name__ == "__main__":
    unittest.main()
