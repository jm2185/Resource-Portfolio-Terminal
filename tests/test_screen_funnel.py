"""
Run: ``python -m unittest tests.test_screen_funnel -v``  (imports commodityex_tui → needs textual).

Pure-content check for the SCREEN disconfirmation-funnel markup (the reframe's job-3 surface):
slot-MISMATCH kills (wrong slot) are counted quietly and never archived as "cause of death"; the
archive holds only SUBSTANTIVE kills; survivors carry their slot incumbent + disproof pips; and a
slot with no candidates shows a clean scout CTA, not a wall of mismatches.
"""
import unittest

try:
    import commodityex_tui as tui
    _HAS = True
except Exception:
    _HAS = False


@unittest.skipUnless(_HAS, "textual not installed")
class ScreenFunnelMarkupTest(unittest.TestCase):
    def _result(self):
        return {"slot": "silver-spear", "n_in": 38, "n_survivors": 2,
                "survivors": [
                    {"ticker": "SILV", "vehicle": "producer", "stage": "pea"},
                    {"ticker": "SSV.V", "vehicle": "explorer", "stage": "pre_pea",
                     "data_gaps": ["runway_months"]}],
                "killed": [
                    {"ticker": "LUN.TO", "gate": "survival", "reason": "dilution_annual 0.4 > 0.25"},
                    {"ticker": "APGO.V", "gate": "slot_fit", "reason": "tagged for ['gold'], not silver-spear"}]}

    def test_candidates_lanes_substantive_cause_and_links(self):
        body = tui._screen_funnel_markup(
            "silver-spear", self._result(), "◆ AGA.V",
            {"SILV": {"verifier", "forensic"}, "SSV.V": set()})
        self.assertIn("3 candidate", body)                  # 2 survivors + 1 substantive kill
        self.assertIn("2 survived", body)
        self.assertIn("1 killed", body)
        self.assertIn("other-slot name", body)              # the 1 slot_fit mismatch, counted quietly
        self.assertIn("SLOT-FIT", body)
        self.assertIn("DISCONFIRM", body)
        self.assertIn("ARCHIVE", body)
        self.assertIn("† survival", body)                   # the substantive kill (LUN.TO)
        self.assertNotIn("APGO.V", body)                    # the slot mismatch is NOT archived/listed here
        self.assertIn("vs ◆ AGA.V", body)
        self.assertIn("gaps: runway_months", body)
        self.assertIn("app.funnel('disconfirm','SILV')", body)
        self.assertIn("app.funnel('open','SILV')", body)

    def test_all_slot_mismatch_shows_scout_cta_not_a_kill_dump(self):
        # the user's exact case: screen a slot whose universe names are all tagged for OTHER slots →
        # 0 candidates, a clean scout CTA, and NO "cause of death" wall.
        res = {"slot": "project-generator-holdco", "n_in": 7, "n_survivors": 0, "survivors": [],
               "killed": [{"ticker": "BRC.V", "gate": "slot_fit", "reason": "tagged for ['silver_spear']"},
                          {"ticker": "U-UN.TO", "gate": "slot_fit", "reason": "tagged for ['electrification_royalty']"}]}
        body = tui._screen_funnel_markup("project-generator-holdco", res, "● GMX.TO", {})
        self.assertIn("0 candidate", body)
        self.assertIn("No candidates tagged", body)
        self.assertIn("/scout project-generator-holdco", body)
        self.assertNotIn("ARCHIVE", body)                   # no cause-of-death wall
        self.assertNotIn("cause of death", body)
        self.assertIn("BRC.V", body)                        # mismatches noted quietly, not archived

    def test_empty_universe_scout_cta(self):
        body = tui._screen_funnel_markup(
            "gold-royalty-ballast", {"n_in": 0, "n_survivors": 0, "survivors": [], "killed": []}, None, {})
        self.assertIn("No candidates tagged", body)
        self.assertIn("/scout gold-royalty-ballast", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
