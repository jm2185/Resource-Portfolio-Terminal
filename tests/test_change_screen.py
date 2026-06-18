"""
Run: ``python -m unittest tests.test_change_screen -v``  (needs `textual`).

Headless render check for the CHANGE review surface (the reframe's job-2 surface). Mounts
ChangeReviewScreen over a minimal host App via Textual's Pilot and asserts it composes — i.e. the
DEFAULT_CSS parses and the diff / pre-mortem / commit widgets mount without error. The commit path
(which calls Cockpit-only app methods) is not exercised here; book_change's logic is covered by
tests/test_book_change.py.
"""
import unittest

try:
    from textual.app import App, ComposeResult
    _HAS_TEXTUAL = True
except Exception:                       # textual not installed in this env — skip cleanly
    _HAS_TEXTUAL = False

import book_change as bc

if _HAS_TEXTUAL:
    from commodityex_tui import ChangeReviewScreen

    class _Host(App):
        def compose(self) -> ComposeResult:
            return iter(())             # empty host; we just push the modal over it

    BOOK = [{"ticker": "AGA.V", "weight": 0.34, "role": "spear", "conviction": 8.0},
            {"ticker": "GMX.TO", "weight": 0.28, "role": "ballast", "conviction": 6.0},
            {"ticker": "GROY", "weight": 0.24, "role": "ballast", "conviction": 6.5},
            {"ticker": "URC.TO", "weight": 0.14, "role": "ballast", "conviction": 5.0}]


@unittest.skipUnless(_HAS_TEXTUAL, "textual not installed")
class ChangeScreenMountTest(unittest.IsolatedAsyncioTestCase):
    async def _mount(self, spec):
        p = bc.propose_change(spec, BOOK)
        self.assertTrue(p["ok"])
        app = _Host()
        async with app.run_test() as pilot:
            await app.push_screen(ChangeReviewScreen(p, spec))
            await pilot.pause()
            scr = app.screen
            # the surface mounted: box, diff, pre-mortem input, commit button all present
            self.assertTrue(scr.query_one("#change_box"))
            self.assertTrue(scr.query_one("#change_diff"))
            self.assertTrue(scr.query_one("#change_premortem"))
            self.assertTrue(scr.query_one("#change_commit"))

    async def test_cut_review_mounts(self):
        await self._mount({"kind": "cut", "ticker": "URC.TO"})

    async def test_rotate_review_mounts(self):
        await self._mount({"kind": "rotate", "out": "URC.TO", "in": "SILV",
                           "in_facts": {"role": "spear", "conviction": 7.1, "runway": 9}})

    async def test_reweight_review_mounts(self):
        await self._mount({"kind": "reweight",
                           "weights": {"AGA.V": 0.5, "GMX.TO": 0.2, "GROY": 0.2, "URC.TO": 0.1}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
