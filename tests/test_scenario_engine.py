"""Tests for scenario_engine (action-plan P3) — the four-scenario robustness convergence point."""
import unittest

import scenario_engine as se
import rates_monitor
import productivity_monitor


# The live book, as the engine wiring builds it from config (barbell weights + thesis slots).
BOOK = [
    {"ticker": "AGA.V",  "slot": "silver-spear",             "weight": 0.45},
    {"ticker": "GROY",   "slot": "gold-royalty-ballast",     "weight": 0.22},
    {"ticker": "GMX.TO", "slot": "project-generator-holdco", "weight": 0.18},
    {"ticker": "URC.TO", "slot": "electrification-royalty",  "weight": 0.15},
]
# A debasement+rates-stress regime (the book's live tilt): low real yield, soft DXY, bear-steepener.
DEBASEMENT_TAPE = {"signals": [
    {"key": "real_yield", "value": 0.0}, {"key": "dxy", "value": 98.0}, {"key": "cu_au", "value": 1.5},
]}
RATES_STRESS = rates_monitor.assess(
    {"dgs2": 3.9, "dgs5": 4.2, "dgs10": 4.7, "dgs30": 5.2, "fedfunds": 4.33},
    prior={"dgs2": 3.95, "dgs5": 4.15, "dgs10": 4.55, "dgs30": 4.85, "fedfunds": 4.33}, move=135)


class WeightTests(unittest.TestCase):
    def test_weights_sum_to_one(self):
        w = se.scenario_weights(rates=RATES_STRESS, macro_tape=DEBASEMENT_TAPE)["weights"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=3)

    def test_no_signals_falls_back_to_prior(self):
        w = se.scenario_weights()["weights"]
        base = se.DEFAULT_SCENARIO_CONFIG["base_prior"]
        tot = sum(base.values())
        for s in ("A", "B", "C", "D"):
            self.assertAlmostEqual(w[s], base[s] / tot, places=3)

    def test_bear_steepener_raises_B(self):
        calm = se.scenario_weights(macro_tape=DEBASEMENT_TAPE)["weights"]["B"]
        stressed = se.scenario_weights(rates=RATES_STRESS, macro_tape=DEBASEMENT_TAPE)["weights"]["B"]
        self.assertGreater(stressed, calm)

    def test_productivity_breadth_raises_C(self):
        low = productivity_monitor.assess([1.0, 1.1], breadth=0.3, breadth_prior=0.3)
        high = productivity_monitor.assess([0.8, 1.0, 2.4, 2.9], breadth=0.8, breadth_prior=0.5)
        c_low = se.scenario_weights(productivity=low, macro_tape=DEBASEMENT_TAPE)["weights"]["C"]
        c_high = se.scenario_weights(productivity=high, macro_tape=DEBASEMENT_TAPE)["weights"]["C"]
        self.assertGreater(c_high, c_low)


class BenignScenarioTests(unittest.TestCase):
    """Scenario E — benign/goldilocks normalization, the future the all-resource book has no answer to.
    It must rise as real yields normalize POSITIVE, and the book must read as a headwind there."""

    def test_E_is_in_the_set_and_weights_sum_to_one(self):
        w = se.scenario_weights(macro_tape={"signals": [{"key": "real_yield", "value": 1.5}]})["weights"]
        self.assertIn("E", w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=3)

    def test_positive_real_yield_raises_E(self):
        debase = se.scenario_weights(macro_tape={"signals": [{"key": "real_yield", "value": -0.5}]})["weights"]["E"]
        benign = se.scenario_weights(macro_tape={"signals": [{"key": "real_yield", "value": 1.5}]})["weights"]["E"]
        self.assertGreater(benign, debase)                 # E is the inverse of the debasement tilt

    def test_crisis_steepener_mutes_E(self):
        benign_tape = {"signals": [{"key": "real_yield", "value": 1.5}]}
        calm = se.scenario_weights(macro_tape=benign_tape)["weights"]["E"]
        crisis = se.scenario_weights(rates=RATES_STRESS, macro_tape=benign_tape)["weights"]["E"]
        self.assertLess(crisis, calm)                      # a disorderly break is not benign

    def test_resource_book_is_a_headwind_in_E(self):
        book = [{"ticker": "AGA.V", "slot": "silver-spear", "weight": 0.60},
                {"ticker": "GROY", "slot": "gold-royalty-ballast", "weight": 0.20},
                {"ticker": "GMX.TO", "slot": "project-generator-holdco", "weight": 0.20}]
        r = se.assess(book, macro_tape={"signals": [{"key": "real_yield", "value": 1.5}]})
        e_payoffs = {row["ticker"]: row["payoffs"]["E"] for row in r["rankings"]}
        self.assertLess(e_payoffs["AGA.V"], 0)             # the spear has no debasement wind in benign
        self.assertEqual(r["scenarios"]["E"]["name"], "Benign normalization / goldilocks")

    def test_fiscal_dominance_score_is_normalized_not_raw(self):
        # REGRESSION (Phase-V V1): the rates fiscal_dominance score is 0..100; it must be normalized
        # to 0..1 before tilting B. The bug only showed with the bear-steepener OFF (the live case) —
        # a non-trivial score (26) fed raw blew B up to ~0.82. The driver must stay in [0,1] and B sane.
        rates_steepener_off = rates_monitor.assess(
            {"dgs2": 4.20, "dgs5": 4.25, "dgs10": 4.45, "dgs30": 4.98, "fedfunds": 4.33})  # no prior/move
        wp = se.scenario_weights(rates=rates_steepener_off,
                                 macro_tape={"signals": [{"key": "real_yield", "value": 2.4},
                                                         {"key": "cu_au", "value": 1.5}]})
        fd = (rates_steepener_off.get("fiscal_dominance") or {}).get("score")
        if fd:                                            # only meaningful when a score exists
            self.assertLessEqual(wp["drivers"]["B"], 1.0)  # driver normalized to 0..1
            self.assertLess(wp["weights"]["B"], 0.60)      # B no longer swamps the prior
            self.assertAlmostEqual(sum(wp["weights"].values()), 1.0, places=3)

    def test_low_real_yield_raises_A(self):
        easy = se.scenario_weights(macro_tape={"signals": [{"key": "real_yield", "value": -0.5}]})["weights"]["A"]
        tight = se.scenario_weights(macro_tape={"signals": [{"key": "real_yield", "value": 1.5}]})["weights"]["A"]
        self.assertGreater(easy, tight)


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.r = se.assess(BOOK, rates=RATES_STRESS, productivity=None, macro_tape=DEBASEMENT_TAPE)

    def test_groy_is_robustness_leader(self):
        # the all-weather ballast tops the dispersion-penalized robustness ranking.
        self.assertEqual(self.r["robustness_leader"], "GROY")
        groy = next(x for x in self.r["rankings"] if x["ticker"] == "GROY")
        self.assertEqual(groy["robustness_rank"], 1)

    def test_spear_leads_on_upside_not_robustness(self):
        # AGA.V (the convex spear) has the highest expected payoff but NOT the best robustness.
        self.assertEqual(self.r["upside_leader"], "AGA.V")
        aga = next(x for x in self.r["rankings"] if x["ticker"] == "AGA.V")
        self.assertEqual(aga["upside_rank"], 1)
        self.assertGreater(aga["robustness_rank"], 1)

    def test_spear_has_higher_dispersion_than_ballast(self):
        aga = next(x for x in self.r["rankings"] if x["ticker"] == "AGA.V")
        groy = next(x for x in self.r["rankings"] if x["ticker"] == "GROY")
        self.assertGreater(aga["dispersion"], groy["dispersion"])

    def test_best_worst_scenarios_labelled(self):
        aga = next(x for x in self.r["rankings"] if x["ticker"] == "AGA.V")
        self.assertEqual(aga["best_scenario"], "B")   # crisis convexity
        self.assertEqual(aga["worst_scenario"], "C")  # productivity win kills the debasement premium

    def test_lambda_zero_collapses_to_expected_value(self):
        # with no dispersion penalty, robustness ranking == upside ranking (the spear wins).
        r0 = se.assess(BOOK, rates=RATES_STRESS, macro_tape=DEBASEMENT_TAPE,
                       config={"scenario_engine": {"dispersion_lambda": 0.0}})
        self.assertEqual(r0["robustness_leader"], r0["upside_leader"])


class PayoffResolutionTests(unittest.TestCase):
    def test_slot_default_used(self):
        r = se.assess([{"ticker": "X", "slot": "electrification-royalty", "weight": 0.1}],
                      macro_tape=DEBASEMENT_TAPE)
        x = r["rankings"][0]
        self.assertEqual(x["payoffs"], {s: round(v, 3) for s, v in se.DEFAULT_SLOT_PAYOFFS["electrification-royalty"].items()})

    def test_explicit_override_wins(self):
        # a legacy 4-key (A–D) override still wins; the new E key defaults to 0 (graceful migration)
        r = se.assess([{"ticker": "X", "slot": "silver-spear", "weight": 0.1,
                        "scenario_payoffs": {"A": 0.1, "B": 0.1, "C": 0.1, "D": 0.1}}])
        self.assertEqual(r["rankings"][0]["payoffs"], {"A": 0.1, "B": 0.1, "C": 0.1, "D": 0.1, "E": 0.0})

    def test_unknown_slot_is_flat_and_graceful(self):
        r = se.assess([{"ticker": "X", "slot": "mystery", "weight": 0.1}])
        self.assertEqual(r["rankings"][0]["payoffs"], {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0})


class HoleTests(unittest.TestCase):
    def test_c_hole_fires_when_C_rises_and_hedge_thin(self):
        # strip the electrification hedge to a sliver and push C up via broad+accelerating productivity.
        thin = [dict(h, weight=(0.02 if h["ticker"] == "URC.TO" else h["weight"])) for h in BOOK]
        hot_c = productivity_monitor.assess([0.8, 1.0, 2.4, 2.9], breadth=0.85, breadth_prior=0.5)
        r = se.assess(thin, rates=RATES_STRESS, productivity=hot_c, macro_tape=DEBASEMENT_TAPE)
        self.assertTrue(r["scenario_c_hole"]["active"])
        self.assertTrue(any(f["id"] == "scenario_c_hole" for f in r["flags"]))

    def test_no_hole_when_hedge_is_well_sized(self):
        fat = [dict(h, weight=(0.40 if h["ticker"] == "URC.TO" else h["weight"])) for h in BOOK]
        hot_c = productivity_monitor.assess([0.8, 1.0, 2.4, 2.9], breadth=0.85, breadth_prior=0.5)
        r = se.assess(fat, rates=RATES_STRESS, productivity=hot_c, macro_tape=DEBASEMENT_TAPE)
        self.assertFalse(r["scenario_c_hole"]["active"])


class StructureTests(unittest.TestCase):
    def test_scenarios_carry_weight_and_driver(self):
        r = se.assess(BOOK, rates=RATES_STRESS, macro_tape=DEBASEMENT_TAPE)
        for s in ("A", "B", "C", "D"):
            self.assertIn("weight", r["scenarios"][s])
            self.assertIn("thesis", r["scenarios"][s])

    def test_glossary_and_framing(self):
        r = se.assess(BOOK, macro_tape=DEBASEMENT_TAPE)
        for k in ("scenario_engine", "scenario_weights", "robustness", "scenario_c_hole"):
            self.assertIn(k, r["glossary"], k)
            self.assertTrue(r["glossary"][k])
        self.assertIn("robustness", r["note"].lower())

    def test_empty_book_graceful(self):
        r = se.assess([], macro_tape=DEBASEMENT_TAPE)
        self.assertEqual(r["rankings"], [])
        self.assertIsNone(r["robustness_leader"])
        self.assertAlmostEqual(sum(r["weights"].values()), 1.0, places=3)


class DownsideDispersionTests(unittest.TestCase):
    """The convexity fix: the dispersion penalty is DOWNSIDE-only, so a convex name is no longer docked
    for its UPSIDE scenario (the Markowitz error in a Druckenmiller book)."""

    def _rows(self, book, **kw):
        r = se.assess(book, rates=RATES_STRESS, macro_tape=DEBASEMENT_TAPE, **kw)
        return {row["ticker"]: row for row in r["rankings"]}

    def test_default_mode_is_downside(self):
        rows = self._rows(BOOK)
        self.assertEqual(rows["AGA.V"]["dispersion_mode"], "downside")

    def test_downside_does_not_penalize_the_spear_upside(self):
        # the spear's robustness must IMPROVE vs the legacy symmetric penalty — its +1.00 B is no longer
        # squared into the penalty; only its deep-negative C is.
        spear_down = self._rows(BOOK)["AGA.V"]
        spear_full = self._rows(BOOK, config={"scenario_engine": {"dispersion_mode": "full"}})["AGA.V"]
        self.assertEqual(spear_full["dispersion_mode"], "full")
        self.assertLessEqual(spear_down["dispersion"], spear_full["dispersion"])   # upside no longer counted
        self.assertGreater(spear_down["robustness"], spear_full["robustness"])     # so robustness rises

    def test_steady_ballast_barely_moves_between_modes(self):
        # GROY is near-symmetric (no big upside leg), so downside vs full should differ far less than for
        # the convex spear — the fix targets convexity, not the ballast.
        rows_d, rows_f = self._rows(BOOK), self._rows(BOOK, config={"scenario_engine": {"dispersion_mode": "full"}})
        spear_rise = rows_d["AGA.V"]["robustness"] - rows_f["AGA.V"]["robustness"]   # downside relief
        groy_rise = rows_d["GROY"]["robustness"] - rows_f["GROY"]["robustness"]
        self.assertGreater(spear_rise, groy_rise)        # the convex spear gains more from dropping the upside penalty

    def test_ballast_still_leads_robustness_by_design(self):
        # the fix narrows the spear-vs-ballast gap; it must NOT invert the intended ordering (ballast is
        # still the more all-weather name on its shallower downside).
        rows = self._rows(BOOK)
        self.assertGreater(rows["GROY"]["robustness"], rows["AGA.V"]["robustness"])

    def test_flat_payoffs_have_zero_dispersion_in_both_modes(self):
        flat = [{"ticker": "FLAT", "scenario_payoffs": {"A": 0.3, "B": 0.3, "C": 0.3, "D": 0.3, "E": 0.3}, "weight": 1.0}]
        for mode in ("downside", "full"):
            row = self._rows(flat, config={"scenario_engine": {"dispersion_mode": mode}})["FLAT"]
            self.assertAlmostEqual(row["dispersion"], 0.0, places=6)

    def test_pure_downside_name_is_still_penalized(self):
        # a name that is BELOW its mean in the bad scenarios must still carry a downside penalty (the fix
        # removes the upside penalty, it does not remove the downside one).
        risky = [{"ticker": "RISKY", "scenario_payoffs": {"A": 0.5, "B": 0.5, "C": -0.9, "D": 0.5}, "weight": 1.0}]
        row = self._rows(risky)["RISKY"]
        self.assertGreater(row["dispersion"], 0.0)
        self.assertLess(row["robustness"], row["expected_payoff"])


if __name__ == "__main__":
    unittest.main()
