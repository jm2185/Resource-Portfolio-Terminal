"""
Run: ``python -m unittest tests.test_screen_funnel -v``  (imports commodityex_tui → needs textual).

Pure-content check for the SCREEN disconfirmation-funnel markup (the reframe's job-3 surface): the
kill-rate header, the survived-clean / survived-with-gaps / killed lanes, cause-of-death on the
archive, the slot incumbent each survivor must beat, the disproof pips, and the clickable
open/disconfirm affordances. The surface itself renders through the proven InspectScreen modal.
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
                    {"ticker": "APGO.V", "gate": "slot_fit", "reason": "vehicle 'producer' mismatch"}]}

    def test_renders_killrate_lanes_cause_and_links(self):
        body = tui._screen_funnel_markup(
            "silver-spear", self._result(), "◆ AGA.V",
            {"SILV": {"verifier", "forensic"}, "SSV.V": set()})
        self.assertIn("38 screened", body)
        self.assertIn("2 survived", body)
        self.assertIn("SLOT-FIT", body)                             # clean-survivor lane
        self.assertIn("DISCONFIRM", body)                           # gappy-survivor lane
        self.assertIn("ARCHIVE", body)                              # killed lane
        self.assertIn("† survival", body)                           # cause of death
        self.assertIn("vs ◆ AGA.V", body)                           # slot incumbent
        self.assertIn("gaps: runway_months", body)                  # data gaps surfaced
        self.assertIn("app.funnel('disconfirm','SILV')", body)      # clickable disconfirm
        self.assertIn("app.funnel('open','SILV')", body)            # clickable open

    def test_empty_universe(self):
        body = tui._screen_funnel_markup(
            "gold-royalty-ballast", {"n_in": 0, "n_survivors": 0, "survivors": [], "killed": []},
            None, {})
        self.assertIn("universe empty", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
