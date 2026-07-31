"""
Run: ``python -m unittest tests.test_jobnav -v``  (imports commodityex_tui → needs textual + rich).

Checks the hub's three-JOB nav (the reframe): Watch / Screen / Change render up front with the old
mechanisms demoted to log / fleet / concierge drawers. Renders the nav Group via a Rich capture so
this validates the markup actually composes (no broken tags), not just that the function returns.
"""
import unittest

try:
    import commodityex_tui as tui
    from rich.console import Console
    _HAS = True
except Exception:
    _HAS = False


@unittest.skipUnless(_HAS, "textual/rich not installed")
class JobNavTest(unittest.TestCase):
    def _render(self) -> str:
        c = Console(width=160)
        with c.capture() as cap:
            c.print(tui._jobnav_markup())
        return cap.get()

    def test_three_jobs_and_drawers_render(self):
        out = self._render()
        for tok in ("WATCH", "SCREEN", "CHANGE", "log", "fleet", "predict", "concierge"):
            self.assertIn(tok, out)

    def test_jobs_in_rising_consequence_order(self):
        self.assertEqual([j[0] for j in tui.JOBNAV_JOBS], ["watch", "screen", "change"])
        # stale expectation fixed 2026-07-31: the predict drawer shipped with the PREDICT DESK
        # (test_predict_desk.test_predict_reachable_from_hub_jobnav pins its presence) but this
        # list was never updated — invisible until textual was installed in the test env.
        self.assertEqual([d[0] for d in tui.JOBNAV_DRAWERS],
                         ["log", "fleet", "predict", "concierge"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
