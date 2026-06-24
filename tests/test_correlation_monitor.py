"""correlation_monitor — the "second thesis vs redundant bet" gauge (Phase 1 of the dual-sided TIV
spec). Tests use two EXACTLY-orthogonal basis series so every Pearson ρ is hand-verifiable:

    A = [1,1,-1,-1] repeated   (the spear / junior-mining-beta factor)
    B = [1,-1,-1,1] repeated   (an independent factor)   →   over each period  ρ(A,B) = 0

For a mix c = α·A + β·B,  ρ(c, A) = α / sqrt(α²+β²)  — so the candidate correlations are exact.
"""
import unittest

import correlation_monitor as cm

_PERIOD_A = [1.0, 1.0, -1.0, -1.0]
_PERIOD_B = [1.0, -1.0, -1.0, 1.0]
A = _PERIOD_A * 10          # 40 points (≥ min_n=30), zero-mean
B = _PERIOD_B * 10          # 40 points, zero-mean, exactly uncorrelated with A


def mix(alpha, beta):
    return [alpha * A[i] + beta * B[i] for i in range(len(A))]


# The four conversation candidates, by construction:
SPEAR = A                   # AGA.V — the dominant factor
BANKS = mix(1.0, 0.0)       # ρ→spear = 1.00  → REDUNDANT (a leveraged duplicate of the steepener bet)
URNJ = mix(1.0, 1.0)        # ρ→spear ≈ 0.71  → REDUNDANT (different metal, same risk-appetite beta)
TMX = mix(1.0, 2.0)         # ρ→spear ≈ 0.45  → PARTIAL   (one real overlap: Capital Formation fees)
EEFT = mix(0.0, 1.0)        # ρ→spear = 0.00  → INDEPENDENT (the cleanest decorrelation)
HEDGE = mix(-1.0, 2.0)      # ρ→spear ≈ -0.45 → INDEPENDENT (a hedge, the best "different reason")


class InputPrepTests(unittest.TestCase):
    def test_returns_from_closes(self):
        r = cm.returns_from_closes([("2026-06-01", 100.0), ("2026-06-02", 110.0), ("2026-06-03", 99.0)])
        self.assertEqual([d for d, _ in r], ["2026-06-02", "2026-06-03"])  # dated on the later day
        self.assertAlmostEqual(r[0][1], 0.10, places=6)
        self.assertAlmostEqual(r[1][1], -0.10, places=6)

    def test_returns_skips_bad_prints(self):
        r = cm.returns_from_closes({"2026-06-01": 100.0, "2026-06-02": 0.0, "2026-06-03": 120.0})
        self.assertTrue(all(isinstance(x, float) for _, x in r))         # no div-by-zero / None leaks

    def test_align_returns_intersects_dates(self):
        aligned, dates = cm.align_returns({
            "A": [("d1", 0.1), ("d2", 0.2), ("d3", 0.3)],
            "B": [("d2", 0.5), ("d3", 0.6), ("d4", 0.7)]})
        self.assertEqual(dates, ["d2", "d3"])                            # only the shared sessions
        self.assertEqual(aligned["A"], [0.2, 0.3])
        self.assertEqual(aligned["B"], [0.5, 0.6])

    def test_align_empty_is_graceful(self):
        self.assertEqual(cm.align_returns({}), ({}, []))


class PearsonTests(unittest.TestCase):
    def test_exact_correlations(self):
        self.assertAlmostEqual(cm.pearson(BANKS, SPEAR), 1.0, places=6)
        self.assertAlmostEqual(cm.pearson(URNJ, SPEAR), 0.7071, places=3)
        self.assertAlmostEqual(cm.pearson(TMX, SPEAR), 0.4472, places=3)
        self.assertAlmostEqual(cm.pearson(EEFT, SPEAR), 0.0, places=6)
        self.assertAlmostEqual(cm.pearson(HEDGE, SPEAR), -0.4472, places=3)

    def test_clamped_and_symmetric(self):
        self.assertEqual(cm.pearson(SPEAR, SPEAR), 1.0)              # clamp holds at the edge
        self.assertAlmostEqual(cm.pearson(SPEAR, URNJ), cm.pearson(URNJ, SPEAR), places=9)

    def test_min_n_and_zero_variance(self):
        self.assertIsNone(cm.pearson([0.1, 0.2, 0.3], A, min_n=30))  # too few aligned points → None
        self.assertIsNone(cm.pearson([1.0] * 40, A))                 # zero-variance leg → None, not a crash
        self.assertIsNone(cm.pearson([], A))

    def test_tail_alignment(self):
        # a longer series is tail-aligned to the shorter; correlation is unchanged on the overlap
        self.assertAlmostEqual(cm.pearson(URNJ + URNJ, SPEAR), 0.7071, places=3)


class VerdictTests(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(cm.independence_verdict(0.05)["verdict"], "INDEPENDENT")
        self.assertEqual(cm.independence_verdict(0.45)["verdict"], "PARTIAL")
        self.assertEqual(cm.independence_verdict(0.80)["verdict"], "REDUNDANT")
        self.assertEqual(cm.independence_verdict(None)["verdict"], "INSUFFICIENT")

    def test_negative_is_independent_hedge(self):
        v = cm.independence_verdict(-0.6)
        self.assertEqual(v["verdict"], "INDEPENDENT")               # a hedge is NOT redundancy
        self.assertIn("hedge", v["label"].lower())

    def test_thresholds_are_config(self):
        v = cm.independence_verdict(0.5, config={"correlation_monitor": {"independent_max": 0.6}})
        self.assertEqual(v["verdict"], "INDEPENDENT")               # raise the bar → 0.5 now independent


class AssessCandidateTests(unittest.TestCase):
    def _book(self):
        # the resource book — all A-dominated (they ride the same factor as the spear)
        return {"AGA.V": SPEAR, "GROY": mix(0.8, 0.2), "GMX.TO": mix(0.7, 0.3), "URC.TO": mix(0.75, 0.25)}

    def test_banks_screened_redundant(self):
        r = cm.assess_candidate(BANKS, self._book(), spear="AGA.V", name="AX")
        self.assertEqual(r["verdict"], "REDUNDANT")
        self.assertTrue(any(f["id"] == "redundant_thesis" for f in r["flags"]))
        self.assertTrue(any(e["type"] == "correlation" for e in r["events"]))

    def test_urnj_not_independent_despite_different_metal(self):
        r = cm.assess_candidate(URNJ, self._book(), spear="AGA.V", name="URNJ")
        self.assertNotEqual(r["verdict"], "INDEPENDENT")           # the whole point: different sector, same beta

    def test_tmx_partial(self):
        r = cm.assess_candidate(TMX, self._book(), spear="AGA.V", name="X.TO")
        self.assertEqual(r["verdict"], "PARTIAL")
        self.assertTrue(any(f["id"] == "partial_thesis" for f in r["flags"]))

    def test_eeft_independent(self):
        r = cm.assess_candidate(EEFT, self._book(), spear="AGA.V", name="EEFT")
        self.assertEqual(r["verdict"], "INDEPENDENT")
        self.assertEqual(r["flags"], [])                           # a real second thesis: no flag
        self.assertIsNotNone(r["rho_to_book"])

    def test_insufficient_history_is_graceful(self):
        r = cm.assess_candidate([0.1, 0.2, 0.3], {"AGA.V": [0.1, -0.1, 0.2]}, name="THIN")
        self.assertFalse(r["available"])
        self.assertEqual(r["verdict"], "INSUFFICIENT")


class DriftTests(unittest.TestCase):
    def test_rising_into_correlation_fires(self):
        d = cm.drift(0.70, 0.40, ticker="GROY")
        self.assertTrue(d["drifting"])
        self.assertEqual(d["flags"][0]["id"], "correlation_drift")
        self.assertEqual(d["flags"][0]["level"], "warn")

    def test_flat_is_quiet(self):
        self.assertFalse(cm.drift(0.50, 0.48, ticker="GROY")["drifting"])

    def test_hedge_tightening_does_not_fire(self):
        # ρ −0.4 → −0.2 is a big delta, but it is getting MORE useful, not drifting to the spear
        self.assertFalse(cm.drift(-0.20, -0.40, ticker="HEDGE")["drifting"])

    def test_conventional_escalates_to_risk(self):
        d = cm.drift(0.70, 0.40, ticker="X.TO", lane="conventional")
        self.assertTrue(d["drifting"])
        self.assertEqual(d["flags"][0]["level"], "risk")

    def test_missing_window_is_graceful(self):
        self.assertFalse(cm.drift(0.7, None, ticker="X.TO")["available"])


class BookIndependenceTests(unittest.TestCase):
    def _holdings(self):
        return [{"ticker": "AGA.V", "slot": "silver-spear"},
                {"ticker": "X.TO", "lane": "conventional"},
                {"ticker": "GROY", "lane": "resource"},
                {"ticker": "MISSING.TO", "lane": "resource"}]

    def _short(self):
        return {"AGA.V": {"X.TO": 0.70, "GROY": 0.70}}              # both at 0.70 today

    def _long(self):
        return {"AGA.V": {"X.TO": 0.40, "GROY": 0.40}}              # both rose from 0.40 — both drifting

    def test_lane_aware_levels(self):
        r = cm.assess_book_independence(self._short(), self._holdings(), spear="AGA.V",
                                        corr_matrix_long=self._long())
        self.assertTrue(r["available"])
        # same drift, different lane → conventional is risk, resource ballast is warn
        levels = {f["ticker"]: f["level"] for f in r["flags"] if f["id"] == "correlation_drift"}
        self.assertEqual(levels.get("X.TO"), "risk")
        self.assertEqual(levels.get("GROY"), "warn")

    def test_conventional_redundant_standing_alarm(self):
        r = cm.assess_book_independence(self._short(), self._holdings(), spear="AGA.V")
        # no long matrix → no drift, but a conventional sleeve at ρ0.70 ≥ 0.60 is a standing risk alarm
        self.assertTrue(any(f["id"] == "conventional_redundant" and f["ticker"] == "X.TO"
                            for f in r["flags"]))

    def test_missing_coverage_is_honest(self):
        r = cm.assess_book_independence(self._short(), self._holdings(), spear="AGA.V")
        self.assertIn("MISSING.TO", [m["ticker"] for m in r["coverage"]["missing"]])
        self.assertEqual(r["n_conventional"], 1)

    def test_empty_is_graceful(self):
        r = cm.assess_book_independence({}, [], spear="AGA.V")
        self.assertFalse(r["available"])


class SelectFreshTests(unittest.TestCase):
    def test_dedup_same_day_same_bucket(self):
        flags = [{"id": "correlation_drift", "ticker": "X.TO", "corr": 0.71, "level": "warn"}]
        fresh, fired = cm.select_fresh(flags, {}, today="2026-06-24")
        self.assertEqual(len(fresh), 1)
        fresh2, _ = cm.select_fresh(flags, fired, today="2026-06-24")
        self.assertEqual(fresh2, [])                               # already pinned today, same decile

    def test_refire_on_worsened_bucket(self):
        _, fired = cm.select_fresh([{"id": "correlation_drift", "ticker": "X.TO", "corr": 0.61}],
                                   {}, today="2026-06-24")
        fresh, _ = cm.select_fresh([{"id": "correlation_drift", "ticker": "X.TO", "corr": 0.78}],
                                   fired, today="2026-06-24")
        self.assertEqual(len(fresh), 1)                            # 0.6 → 0.8 decile is a new event

    def test_refire_next_day(self):
        _, fired = cm.select_fresh([{"id": "correlation_drift", "ticker": "X.TO", "corr": 0.71}],
                                   {}, today="2026-06-24")
        fresh, _ = cm.select_fresh([{"id": "correlation_drift", "ticker": "X.TO", "corr": 0.71}],
                                   fired, today="2026-06-25")
        self.assertEqual(len(fresh), 1)


class DiversifierScreenTests(unittest.TestCase):
    """The SCREEN-window diversifier search: the book's macro-correlation summary + a universe ranked by
    independence (measured ρ where prices exist, factor-proxy otherwise)."""

    def test_book_macro_summary_folds_concentration_and_drift(self):
        bf = {"available": True, "avg_pairwise": 0.7, "single_factor": True, "single_factor_threshold": 0.6,
              "spear": "AGA.V", "spear_corr": {"GROY": 0.74},
              "flags": [{"id": "ballast_correlated", "ticker": "GROY"}], "read": "avg pairwise ρ 0.70 …"}
        ind = {"by_ticker": {"X.TO": {"drift": {"drifting": True, "delta": 0.3, "rho_short": 0.7, "rho_long": 0.4}}},
               "flags": [{"id": "correlation_drift", "ticker": "X.TO"}]}
        m = cm.book_macro_summary(bf, ind)
        self.assertTrue(m["single_factor"])
        self.assertEqual(m["avg_pairwise"], 0.7)
        self.assertEqual(m["spear_corr"]["GROY"], 0.74)
        self.assertEqual(m["drift"][0]["ticker"], "X.TO")
        self.assertEqual(len(m["flags"]), 2)                       # book flag + independence flag
        self.assertFalse(cm.book_macro_summary({}, None)["available"])   # graceful

    def test_measured_ranks_independent_over_redundant(self):
        book = {"AGA.V": SPEAR, "GROY": mix(0.8, 0.2)}
        cand_rets = {"EEFT": EEFT, "BANK": BANKS}                  # EEFT=B (independent), BANK=A (redundant)
        cands = [{"ticker": "BANK", "commodity": "financials"}, {"ticker": "EEFT", "commodity": ""}]
        r = cm.screen_uncorrelated(cands, candidate_returns=cand_rets, book_returns_by_ticker=book)
        order = [c["ticker"] for c in r["candidates"]]
        self.assertEqual(order[0], "EEFT")                         # most independent floats to the top
        self.assertEqual(order[-1], "BANK")
        self.assertEqual(r["candidates"][0]["basis"], "measured")
        self.assertEqual(r["candidates"][0]["verdict"], "INDEPENDENT")
        self.assertGreaterEqual(r["n_diversifiers"], 1)

    def test_proxy_distinguishes_resource_from_conventional(self):
        cands = [{"ticker": "SILV", "commodity": "silver"},                      # book's factor → same
                 {"ticker": "EEFT", "commodity": "", "vehicle": "operator"}]     # conventional → distinct
        r = cm.screen_uncorrelated(cands)                          # no returns supplied → factor proxy
        by = {c["ticker"]: c for c in r["candidates"]}
        self.assertEqual(by["SILV"]["verdict"], "SAME-FACTOR")
        self.assertEqual(by["SILV"]["basis"], "proxy")
        self.assertEqual(by["EEFT"]["verdict"], "DISTINCT-FACTOR")

    def test_all_resource_universe_reports_no_diversifier(self):
        cands = [{"ticker": "SILV", "commodity": "silver"}, {"ticker": "GLD", "commodity": "gold"}]
        r = cm.screen_uncorrelated(cands)
        self.assertEqual(r["n_diversifiers"], 0)
        self.assertIn("conventional core", r["read"])              # the honest "no diversifier here" finding


if __name__ == "__main__":
    unittest.main()
