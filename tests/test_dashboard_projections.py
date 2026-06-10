"""Tests for the streamlit-free dashboard projection/presentation helpers (audit A2.1 / B8).

These pin INVARIANT 1 (the dashboard projects the engine's verdicts, it never re-derives them) and
GROUNDED-OR-SILENT (a missing datum renders "—", never a fabricated default / stale literal). Pure —
no streamlit import in the path, so the legacy dashboard's logic is testable in this container.
"""
import unittest

import dashboard_projections as proj


class DirectiveColorTests(unittest.TestCase):
    """Colour is a PRESENTATION map keyed off the engine's directive *text* — the dashboard decides
    no directive of its own. Strings here are the actual vocabulary of asymmetry_rating._directive."""

    def test_accumulate_is_green(self):
        for d in ("BELOW FAIR VALUE — ACCUMULATE", "BELOW FLOOR — ACCUMULATE · watch closely"):
            self.assertEqual(proj.directive_color(d), "#00E676", d)

    def test_trim_is_orange(self):
        self.assertEqual(proj.directive_color("RICH — TRIM"), "#FF9800")

    def test_trim_beats_hold_in_mixed_directive(self):
        # "UPSIDE SPENT — HOLD / TRIM" must read cautionary (orange), not neutral (grey)
        self.assertEqual(proj.directive_color("UPSIDE SPENT — HOLD / TRIM"), "#FF9800")

    def test_avoid_is_red(self):
        self.assertEqual(proj.directive_color("FORENSIC DECAY — AVOID / DE-RISK"), "#FF5252")
        self.assertEqual(proj.directive_color("WEAK SETUP — STAND ASIDE"), "#FF5252")

    def test_hold_monitor_core_are_neutral(self):
        for d in ("QUALITY — CORE HOLD", "FAIR VALUE — HOLD", "THESIS INTACT — MONITOR",
                  "STRONG ASYMMETRY — WATCH CLOSELY"):
            self.assertEqual(proj.directive_color(d), "#888888", d)

    def test_missing_directive_is_neutral_not_a_guess(self):
        self.assertEqual(proj.directive_color(None), "#888888")
        self.assertEqual(proj.directive_color(""), "#888888")

    def test_bg_matches_colour_and_neutral_is_transparent(self):
        self.assertEqual(proj.directive_bg("RICH — TRIM"), "rgba(255,152,0,0.06)")
        self.assertEqual(proj.directive_bg(None), "transparent")


class ProjectionTests(unittest.TestCase):
    def test_directive_by_ticker_projects_engine_block(self):
        cm = {"baskets": [{"ticker": "AGA.V", "directive": "BELOW FLOOR — ACCUMULATE"},
                          {"ticker": "GROY", "directive": "QUALITY — CORE HOLD"},
                          {"ticker": None, "directive": "ignored"}]}
        out = proj.directive_by_ticker(cm)
        self.assertEqual(out, {"AGA.V": "BELOW FLOOR — ACCUMULATE", "GROY": "QUALITY — CORE HOLD"})

    def test_directive_by_ticker_absent_block_is_empty(self):
        self.assertEqual(proj.directive_by_ticker(None), {})       # grounded-or-silent, no fabrication
        self.assertEqual(proj.directive_by_ticker({}), {})

    def test_spear_ticker_from_config_thesis_slot(self):
        cfg = {"portfolio_metadata": {"AGA.V": {"thesis_slot": "silver-spear"},
                                      "GROY": {"thesis_slot": "gold-royalty-ballast"}}}
        self.assertEqual(proj.spear_ticker(cfg), "AGA.V")

    def test_spear_ticker_absent_is_none(self):
        self.assertIsNone(proj.spear_ticker({"portfolio_metadata": {"GROY": {"thesis_slot": "x"}}}))
        self.assertIsNone(proj.spear_ticker(None))


class GroundedOrSilentTests(unittest.TestCase):
    def test_node_price_reads_engine_or_none(self):
        state = {"nodes": {"AGA.V": {"price": 0.83}, "GROY": {"price": None}}}
        self.assertEqual(proj.node_price(state, "AGA.V"), 0.83)
        self.assertIsNone(proj.node_price(state, "GROY"))          # present-but-None -> unknown
        self.assertIsNone(proj.node_price(state, "URC.TO"))        # absent -> unknown
        self.assertIsNone(proj.node_price(None, "AGA.V"))          # no feed -> unknown (not a literal)

    def test_node_shares_reads_engine_or_none(self):
        state = {"nodes": {"AGA.V": {"shares": 5000}}}
        self.assertEqual(proj.node_shares(state, "AGA.V"), 5000.0)
        self.assertIsNone(proj.node_shares(state, "GROY"))

    def test_fmt_or_dash(self):
        self.assertEqual(proj.fmt_or_dash(1234.5, ",.0f"), "1,234")
        self.assertEqual(proj.fmt_or_dash(0.123, ".1f"), "0.1")
        self.assertEqual(proj.fmt_or_dash(None, ".1f"), "—")       # never coerced to 0
        self.assertEqual(proj.fmt_or_dash("n/a", ".1f"), "—")
        self.assertEqual(proj.fmt_or_dash(True, ",.0f"), "—")      # a bool is not a quantity


if __name__ == "__main__":
    unittest.main()
