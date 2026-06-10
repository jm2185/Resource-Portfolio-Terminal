"""Pre-flight hardening pass — the fixes that close the live-operation blind spots:
P1 numeric-confidence vocabulary in uncertainty (the engine's triangulation tilts are numbers,
not high/med/low), P2 the daily price mark (same-day convergent, past immutable), P4 the
cross-check wiring through ingestion + the Sentinel data-conflict alert, P5 the backtest job
prompt driving the flywheel sweeps."""
from __future__ import annotations

import os
import tempfile
import unittest

import uncertainty as unc


class NumericConfidenceTests(unittest.TestCase):
    """P1 — the engine speaks numeric tilts (v5_config triangulation.confidence: cost 0.9,
    market 0.85, income 0.2); the sigma map must accept BOTH vocabularies, fail-closing only on
    a value that fits neither."""

    def test_numeric_maps_to_ordinal_grades(self):
        for numeric, ordinal in ((0.9, "high"), (0.85, "high"), (0.6, "med"),
                                 (0.5, "med"), (0.2, "low"), (0.0, "low")):
            s_num, fc = unc.sigma_for(numeric)
            s_ord, _ = unc.sigma_for(ordinal)
            self.assertEqual(s_num, s_ord, f"{numeric} should grade as {ordinal}")
            self.assertFalse(fc, f"{numeric} is a VALID grade — must not fail-close")

    def test_malformed_still_fails_closed(self):
        for bad in (None, "", "very-high", 1.5, -0.1):
            sigma, fc = unc.sigma_for(bad)
            self.assertTrue(fc, f"{bad!r} fits neither vocabulary — must fail closed")
            self.assertEqual(sigma, unc.DEFAULTS["confidence_sigma_rel"]["low"])

    def test_engine_shaped_leg_confidence_no_false_fail_closed(self):
        """The LIVE engine shape: numeric confidences must propagate without flooding
        fail_closed (the pre-fix behavior treated every leg as ungraded → max sigma)."""
        d = unc.intrinsic_distribution(
            {"cost": 1.0, "market": 2.0, "income": 0.5},
            {"cost": 0.3, "market": 0.5, "income": 0.2},
            leg_confidence={"cost": 0.9, "market": 0.85, "income": 0.2})
        self.assertEqual(d["fail_closed"], [])
        all_low = unc.intrinsic_distribution(
            {"cost": 1.0, "market": 2.0, "income": 0.5},
            {"cost": 0.3, "market": 0.5, "income": 0.2},
            leg_confidence={"cost": 0.2, "market": 0.2, "income": 0.2})
        self.assertLess(d["rel_width"], all_low["rel_width"])   # graded ≠ worst-case treatment


class RecordMarkTests(unittest.TestCase):
    """P2 — the engine's intraday mark converges to the close; history stays immutable."""

    def setUp(self):
        import price_history as ph
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_day_mark_updates(self):
        a = self.h.record_mark("AGA.V", "2026-06-10", 0.61, today="2026-06-10")
        self.assertTrue(a["ok"] and not a.get("updated"))
        b = self.h.record_mark("AGA.V", "2026-06-10", 0.63, today="2026-06-10")
        self.assertTrue(b["ok"] and b["updated"])               # converges to the close
        self.assertEqual(self.h.close_on("AGA.V", "2026-06-10")["close"], 0.63)

    def test_past_immutable_future_refused(self):
        self.h.record("AGA.V", "2026-06-09", 0.58)
        past = self.h.record_mark("AGA.V", "2026-06-09", 0.99, today="2026-06-10")
        self.assertTrue(past.get("conflict"))                   # yesterday can't be rewritten
        self.assertEqual(self.h.close_on("AGA.V", "2026-06-09")["close"], 0.58)
        fut = self.h.record_mark("AGA.V", "2026-06-11", 0.70, today="2026-06-10")
        self.assertFalse(fut["ok"])

    def test_duplicate_mark_no_dirty_write(self):
        self.h.record_mark("AGA.V", "2026-06-10", 0.61, today="2026-06-10")
        r = self.h.record_mark("AGA.V", "2026-06-10", 0.61, today="2026-06-10")
        self.assertTrue(r.get("duplicate"))


class IngestionCrossCheckTests(unittest.TestCase):
    """P4 — the pipeline runs the two-source check after the merge; conflicts ride the payload
    and demote the (temp) cache, never the values themselves."""

    def _pipeline(self, rc):
        import ingestion_pipeline as ip
        p = ip.IngestionPipeline.__new__(ip.IngestionPipeline)   # no adapters/network needed
        p._research_cache = lambda: rc
        return p

    def test_conflict_flagged_on_payload_and_cache(self):
        from research_cache import ResearchCache
        tmp = tempfile.TemporaryDirectory()
        try:
            rc = ResearchCache(path=os.path.join(tmp.name, "rc.json"))
            rc.set("AGA.V", "shares_out", 208_600_000, "https://sedar/filing", "2026-01-01",
                   confidence="high")
            data = {"tickers": {"AGA.V": {"financials": {"shares_t0": 300_000_000,
                                                         "cash": None}}}}
            conflicts = self._pipeline(rc)._cross_check_filings(data)
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0]["field"], "shares_out")
            self.assertIn("data_conflicts", data["tickers"]["AGA.V"])
            entry = rc.get("AGA.V", "shares_out")
            self.assertEqual(entry["confidence"], "low")         # demoted, fail-closed
            self.assertEqual(entry["value"], 208_600_000)        # NEVER averaged/replaced
        finally:
            tmp.cleanup()

    def test_agreement_and_absence_are_quiet(self):
        from research_cache import ResearchCache
        tmp = tempfile.TemporaryDirectory()
        try:
            rc = ResearchCache(path=os.path.join(tmp.name, "rc.json"))
            rc.set("AGA.V", "shares_out", 208_600_000, "src", "2026-01-01", confidence="high")
            data = {"tickers": {"AGA.V": {"financials": {"shares_t0": 210_000_000}},
                                "GROY": {"financials": {}}}}
            self.assertEqual(self._pipeline(rc)._cross_check_filings(data), [])
            self.assertEqual(rc.get("AGA.V", "shares_out")["confidence"], "high")
        finally:
            tmp.cleanup()


class SentinelConflictAlertTests(unittest.TestCase):
    """P4 — a flagged conflict surfaces as a warn alert on the Sentinel sweep."""

    BASKET = {"asymmetry": {"floor_coverage": 1.1, "rho": 3.0, "upside_pct": 80.0},
              "ladder": {"price": 1.0, "floor": 0.8}, "gate": {"cap": 7.0}}

    def test_conflict_becomes_warn_alert(self):
        import sentinel as sen
        st = sen.sweep_name(ticker="AGA.V", basket=dict(self.BASKET),
                            data_conflicts=[{"field": "shares_out",
                                             "filings_value": 208_600_000,
                                             "market_value": 300_000_000,
                                             "disagreement": 0.3047}])
        hits = [a for a in st["alerts"] if "data_conflict" in str(a.get("key"))]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["level"], "warn")
        self.assertIn("30% apart", hits[0]["text"])

    def test_note_only_conflict_formats_without_percentage(self):
        import sentinel as sen
        st = sen.sweep_name(ticker="AGA.V", basket=dict(self.BASKET),
                            data_conflicts=[{"field": "cash", "disagreement": None,
                                             "note": "DATA CONFLICT: ..."}])
        txt = [a for a in st["alerts"] if "data_conflict" in str(a.get("key"))][0]["text"]
        self.assertNotIn("% apart", txt)
        self.assertIn("flagged on the cached field", txt)

    def test_no_conflicts_no_alert(self):
        import sentinel as sen
        st = sen.sweep_name(ticker="AGA.V", basket=dict(self.BASKET))
        self.assertFalse([a for a in st["alerts"] if "data_conflict" in str(a.get("key"))])


class SchedulerSweepCadenceTests(unittest.TestCase):
    """P5 — the scheduled backtest job now drives the flywheel sweeps."""

    def test_backtest_prompt_names_the_sweeps(self):
        import cockpit_scheduler as cs
        prompt = cs.prompt_for(cs.new_job("backtest", topic="the book"))
        for tool in ("sweep_outcomes", "sweep_scout_outcomes", "replay_grade", "/confirm"):
            self.assertIn(tool, prompt)


if __name__ == "__main__":
    unittest.main()
