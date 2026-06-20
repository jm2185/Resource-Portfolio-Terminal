"""The Hub chat is FREE-FORM: a composer message scopes to a ticker only when the user explicitly
types one — the focused name is never auto-applied. The composer hands `_delegate` a subject of
`_detect_ticker(text)` (or the routed ticker), both of which ignore `self._focus`; the old
`_blend_subject()` focus-fallback is gone.

Imports commodityex_tui (needs textual/rich) → skips when the TUI stack isn't installed; runs in CI.
"""
import unittest

try:
    import commodityex_tui as tui
    _HAS = True
except Exception:
    _HAS = False


@unittest.skipUnless(_HAS, "textual/rich not installed")
class HubChatScopeTest(unittest.TestCase):
    def setUp(self):
        self.app = tui.Cockpit()
        self.app._focus = "AGA.V"               # a name IS in focus — it must not leak into chat scope

    def test_general_question_names_no_ticker(self):
        # deictic / general questions name no ticker -> subject is None (free-form), not the focus
        self.assertIsNone(self.app._detect_ticker("why is this rated low?"))
        self.assertIsNone(self.app._detect_ticker("what's the silver macro outlook this week?"))
        self.assertIsNone(self.app._route_intent("give me the bull case")[2])

    def test_explicit_ticker_scopes(self):
        # an explicitly typed exchange-suffixed ticker DOES scope the chat
        self.assertEqual(self.app._detect_ticker("is URC.TO cheap vs peers?"), "URC.TO")
        self.assertEqual(self.app._route_intent("bull case on AGA.V")[2], "AGA.V")

    def test_focus_is_never_the_fallback_subject(self):
        # the contract the fix encodes: ticker detection ignores self._focus entirely
        self.app._focus = "GROY"
        self.assertIsNone(self.app._detect_ticker("how do real yields look right now?"))


if __name__ == "__main__":
    unittest.main()
