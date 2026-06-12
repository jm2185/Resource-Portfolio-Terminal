"""Tests for the MCP daily_brief tool's actionable flag layer (mcp_server/core._brief_flags).

The flag derivation is pure over an engine /state dict — no engine, no `mcp` package needed —
so it's unit-testable directly. Grounded-or-silent: a missing field is simply not flagged.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_server"))
import core  # noqa: E402


def _state(baskets, freshness=None):
    st = {"conviction_mode": {"baskets": baskets, "top_pick": "AGA.V"}}
    if freshness is not None:
        st["data_freshness"] = freshness
    return st


class DailyBriefFlagTests(unittest.TestCase):
    def test_below_floor_is_an_accumulate_flag(self):
        flags = core._brief_flags(_state([
            {"ticker": "AGA.V", "pillars": {"V": {"floor_coverage": 1.08}}},
        ]))
        below = [f for f in flags if f["kind"] == "below_floor"]
        self.assertEqual(len(below), 1)
        self.assertEqual(below[0]["ticker"], "AGA.V")
        self.assertEqual(below[0]["level"], "good")
        self.assertIn("BELOW REP floor", below[0]["text"])

    def test_severe_forensic_cap_flags_risk(self):
        flags = core._brief_flags(_state([
            {"ticker": "GROY", "pillars": {"V": {"floor_coverage": 0.6}},
             "gate": {"applied": True, "cap": 4.0, "reason": "JSF 2.9<3.5 severe"}},
        ]))
        cap = [f for f in flags if f["kind"] == "forensic_cap"]
        self.assertEqual(len(cap), 1)
        self.assertEqual(cap[0]["level"], "risk")
        # a benign / floor-relaxed cap (> 5) is NOT flagged — only a severe one
        benign = core._brief_flags(_state([
            {"ticker": "GROY", "pillars": {"V": {"floor_coverage": 0.6}},
             "gate": {"applied": True, "cap": 7.0, "reason": "floor-relaxed"}},
        ]))
        self.assertEqual([f for f in benign if f["kind"] == "forensic_cap"], [])

    def test_catalyst_flag_needs_a_live_signal_and_headline(self):
        live = core._brief_flags(_state([
            {"ticker": "AGA.V", "pillars": {"V": {"floor_coverage": 0.8, "downside_to_floor_pct": 30}},
             "catalyst_signal": 0.3, "catalysts": [{"headline": "Drill assays pending"}]},
        ]))
        self.assertEqual([f["kind"] for f in live if f["kind"] == "catalyst"], ["catalyst"])
        # no signal → no catalyst flag (grounded-or-silent)
        quiet = core._brief_flags(_state([
            {"ticker": "AGA.V", "pillars": {"V": {"floor_coverage": 0.8}},
             "catalyst_signal": 0.0, "catalysts": [{"headline": "Drill assays pending"}]},
        ]))
        self.assertEqual([f for f in quiet if f["kind"] == "catalyst"], [])

    def test_stale_feeds_flag_is_book_level(self):
        flags = core._brief_flags(_state(
            [{"ticker": "AGA.V", "pillars": {"V": {"floor_coverage": 0.9, "downside_to_floor_pct": 30}}}],
            freshness={"feeds": {"mri_history": {"stale": True}, "prices": {"stale": False}}}))
        stale = [f for f in flags if f["kind"] == "stale"]
        self.assertEqual(len(stale), 1)
        self.assertIsNone(stale[0]["ticker"])
        self.assertIn("mri_history", stale[0]["text"])

    def test_quiet_book_yields_no_flags(self):
        self.assertEqual(core._brief_flags(_state([
            {"ticker": "AGA.V", "pillars": {"V": {"floor_coverage": 0.8, "downside_to_floor_pct": 30}},
             "gate": {"applied": False}},
        ])), [])

    def test_missing_fields_are_silently_skipped(self):
        # no V pillar, no gate, no catalysts — must not raise, must not invent flags
        self.assertEqual(core._brief_flags(_state([{"ticker": "X"}, {}])), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
