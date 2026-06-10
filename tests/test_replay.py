"""Replay harness (Phase 2) — price-history ground truth, Mode A grades against synthetic paths
with known answers, small-n honesty, base-rate feedback, Mode B reconciliation + counterfactual."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta

import price_history as ph
import replay
import valuation_ledger as vl


def _ledger_with(snapshots, path):
    led = vl.ValuationLedger(path=path)
    for snap, ts in snapshots:
        led.record(snap, trigger="manual", ts=ts)
    return led


def _snap(ticker="AGA.V", *, price=1.00, intrinsic=2.00, floor=0.80, bull=3.00,
          archetype="option_convexity", ribbon=None, legs=None):
    s = {"ticker": ticker, "archetype": archetype, "price": price, "intrinsic": intrinsic,
         "ladder": {"floor": floor, "bear": 0.9, "base": intrinsic, "bull": bull},
         "asymmetry": {"rho": 3.0, "phi": floor / price}, "rating": 7.5,
         "band": "STRONG ASYMMETRY", "directive": "WATCH", "gate": {"cap": 10.0},
         "ribbon": ribbon or {}, "inputs": {}}
    if legs:
        s["legs"] = legs
    return s


class PriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_and_conflict(self):
        self.assertTrue(self.h.record("AGA.V", "2026-01-05", 1.10)["ok"])
        self.assertTrue(self.h.record("AGA.V", "2026-01-05", 1.10)["duplicate"])
        bad = self.h.record("AGA.V", "2026-01-05", 1.50)
        self.assertTrue(bad.get("conflict"))           # a restated print is NEVER overwritten
        self.assertEqual(self.h.close_on("AGA.V", "2026-01-05")["close"], 1.10)

    def test_close_on_walks_back_over_weekend(self):
        self.h.record("AGA.V", "2026-01-02", 1.00)     # Friday
        mark = self.h.close_on("AGA.V", "2026-01-04")  # Sunday
        self.assertEqual(mark["close"], 1.00)
        self.assertEqual(mark["lag_days"], 2)
        self.assertIsNone(self.h.close_on("AGA.V", "2026-01-20"))   # beyond max lag

    def test_window_and_min(self):
        for i, c in enumerate([1.0, 0.7, 1.2]):
            self.h.record("AGA.V", f"2026-01-0{i+1}", c)
        lo = self.h.min_close("AGA.V", "2026-01-01", "2026-01-03")
        self.assertEqual(lo["close"], 0.7)
        self.assertEqual(lo["n_days"], 3)


class GradeTests(unittest.TestCase):
    """Synthetic paths with hand-computed answers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))
        self.path = os.path.join(self.tmp.name, "ledger.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_path(self, ticker, t0, closes):
        for i, c in enumerate(closes):
            self.h.record(ticker, t0 + timedelta(days=i), c, save=False)
        self.h._save()

    def test_converging_name_grades_positively(self):
        t0 = date(2026, 1, 1)
        # price 1.00, intrinsic 2.00 (gap +100%); price converges to 1.50 by day 30
        closes = [1.0 + 0.5 * i / 30 for i in range(31)]
        self._seed_path("AGA.V", t0, closes)
        snap = dict(_snap(), ts="2026-01-01T00:00:00Z", id="s1")
        g = replay.grade_snapshot(snap, self.h, 30)
        self.assertTrue(g["convergence"]["sign_agree"])
        # gap0 = 1.0; gapN = (2-1.5)/1.5 = 0.3333; closure = (1 - .3333)/1 = .6667
        self.assertAlmostEqual(g["convergence"]["gap_closure"], 0.6667, places=3)
        self.assertTrue(g["band"]["in_band"])          # 1.5 in [0.8, 3.0]
        self.assertTrue(g["floor"]["held"])

    def test_diverging_and_floor_break(self):
        t0 = date(2026, 1, 1)
        closes = [1.0 - 0.4 * i / 30 for i in range(31)]   # falls to 0.60 < floor 0.80
        self._seed_path("AGA.V", t0, closes)
        snap = dict(_snap(), ts="2026-01-01T00:00:00Z", id="s1")
        g = replay.grade_snapshot(snap, self.h, 30)
        self.assertFalse(g["convergence"]["sign_agree"])
        self.assertLess(g["convergence"]["gap_closure"], 0)
        self.assertFalse(g["floor"]["held"])
        self.assertTrue(g["floor"]["tested"])
        self.assertAlmostEqual(g["floor"]["breach_pct"], (0.6 / 0.8 - 1) * 100, places=0)
        self.assertFalse(g["band"]["in_band"])         # 0.60 < floor leg

    def test_horizon_not_reached_is_skipped_not_fabricated(self):
        self._seed_path("AGA.V", date(2026, 1, 1), [1.0, 1.01])
        snap = dict(_snap(), ts="2026-01-01T00:00:00Z", id="s1")
        self.assertIsNone(replay.grade_snapshot(snap, self.h, 90))

    def test_pit_band_used_when_distributional(self):
        t0 = date(2026, 1, 1)
        self._seed_path("AGA.V", t0, [1.0] * 31)
        snap = dict(_snap(ribbon={"p10": 1.4, "p50": 2.0, "p90": 2.8}),
                    ts="2026-01-01T00:00:00Z", id="s1")
        g = replay.grade_snapshot(snap, self.h, 30)
        self.assertEqual(g["band"]["kind"], "p10_p90")
        self.assertFalse(g["band"]["in_band"])         # 1.0 below P10 — the claim is graded

    def test_report_small_n_honesty_counts_always_expectancy_suppressed(self):
        t0 = date(2026, 1, 1)
        self._seed_path("AGA.V", t0, [1.0 + 0.5 * i / 30 for i in range(31)])
        led = _ledger_with([(_snap(), "2026-01-01T00:00:00Z")], self.path)
        grades = replay.grade_ledger(led, self.h, horizon_days=30)
        rep = replay.report(grades)
        self.assertEqual(rep["n"], 1)
        self.assertTrue(rep["reliability"]["data_limited"])
        self.assertIsNone(rep["convergence"]["mean_gap_closure"])   # suppressed when thin
        self.assertEqual(rep["events"]["floor_held"], 1)            # counts always shown
        self.assertIn("by_archetype", rep)

    def test_ledger_priors_feed_base_rates(self):
        t0 = date(2026, 1, 1)
        self._seed_path("AGA.V", t0, [1.0 - 0.4 * i / 30 for i in range(31)])  # tested + broke
        led = _ledger_with([(_snap(), "2026-01-01T00:00:00Z")], self.path)
        grades = replay.grade_ledger(led, self.h, horizon_days=30)
        priors = replay.ledger_priors(grades)
        post = priors["option_convexity"]["floor_reliability"]
        # engineering prior Beta(8,2) + 1 tested failure -> posterior below the 0.80 prior
        self.assertLess(post["posterior_mean"], post["prior_mean"])
        self.assertAlmostEqual(post["prior_mean"], 0.80, places=3)     # Beta(8,2) mean
        self.assertIn("ci90", post)


class ModeBTests(unittest.TestCase):
    def test_recompute_blend_reconciles(self):
        snap = _snap(legs={"values": {"cost": 1.0, "market": 2.5},
                           "weights": {"cost": 0.3, "market": 0.7}})
        snap["intrinsic"] = 0.95 * (1.0 * 0.3 + 2.5 * 0.7)   # forensic penalty 0.95
        res = replay.recompute_blend(snap)
        self.assertEqual(res["status"], "reconciled")
        self.assertAlmostEqual(res["implied_forensic_penalty"], 0.95, places=4)

    def test_recompute_blend_names_drift(self):
        snap = _snap(legs={"values": {"cost": 1.0, "market": 2.5},
                           "weights": {"cost": 0.3, "market": 0.7}})
        snap["intrinsic"] = 9.99                        # impossible vs its own frozen legs
        self.assertEqual(replay.recompute_blend(snap)["status"], "DRIFT")

    def test_counterfactual_diffs_floor_scaling(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            h = ph.PriceHistory(path=os.path.join(tmp.name, "ph.json"))
            t0 = date(2026, 1, 1)
            for i in range(31):                          # dips to 0.75: breaks floor 0.80, not 0.70
                h.record("AGA.V", t0 + timedelta(days=i), 1.0 - 0.25 * i / 30, save=False)
            h._save()
            led = _ledger_with([(_snap(floor=0.80), "2026-01-01T00:00:00Z")],
                               os.path.join(tmp.name, "ledger.jsonl"))

            def easier_floor(snap):
                snap = dict(snap)
                lad = dict(snap.get("ladder") or {})
                lad["floor"] = (lad.get("floor") or 0) * 0.875   # 0.80 -> 0.70
                snap["ladder"] = lad
                return snap

            res = replay.counterfactual(led, h, easier_floor, horizon_days=30,
                                        label="conservatism −1 step")
            self.assertEqual(res["event_diff"]["floor_held"]["baseline"], 0)
            self.assertEqual(res["event_diff"]["floor_held"]["candidate"], 1)
            self.assertIn("/confirm", res["note"])
        finally:
            tmp.cleanup()


class ConvergenceTypeTests(unittest.TestCase):
    """Audit F4: gap_closure reads backward on an overshoot — the convergence_type label keeps the
    number in context (a bull call that overshot is a gain, not a failed convergence)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self, ticker, t0, closes):
        for i, c in enumerate(closes):
            self.h.record(ticker, t0 + timedelta(days=i), c, save=False)
        self.h._save()

    def _grade(self, ticker, t0, closes, intrinsic):
        self._seed(ticker, t0, closes)
        snap = {"ticker": ticker, "archetype": "option_convexity", "price": closes[0],
                "intrinsic": intrinsic,
                "ladder": {"floor": closes[0] * 0.7, "bear": closes[0] * 0.9,
                           "base": intrinsic, "bull": intrinsic * 1.6},
                "ribbon": {}, "id": "s", "ts": t0.isoformat() + "T00:00:00Z"}
        return replay.grade_snapshot(snap, self.h, 30)["convergence"]

    def test_overshoot_labelled_with_note(self):
        t0 = date(2026, 1, 1)
        # price 100 -> 200, intrinsic 150: started cheap, rallied THROUGH fair value
        c = self._grade("OV.V", t0, [100 + 100 * i / 30 for i in range(31)], 150)
        self.assertEqual(c["convergence_type"], "overshooting")  # crossed THROUGH fair value
        self.assertIsNotNone(c["note"])
        self.assertIs(c["sign_agree"], True)           # direction was right (the label explains it)

    def test_converged_toward_intrinsic(self):
        t0 = date(2026, 1, 1)
        c = self._grade("TW.V", t0, [100 + 40 * i / 30 for i in range(31)], 150)
        self.assertEqual(c["convergence_type"], "toward_intrinsic")
        self.assertGreater(c["gap_closure"], 0)

    def test_reversing_wrong_direction(self):
        t0 = date(2026, 1, 1)
        # price above intrinsic (overvalued) and rises further -> moved away
        c = self._grade("RV.V", t0, [150 + 50 * i / 30 for i in range(31)], 100)
        self.assertEqual(c["convergence_type"], "reversing")
        self.assertIsNotNone(c["note"])


if __name__ == "__main__":
    unittest.main()
