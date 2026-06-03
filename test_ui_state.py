"""
Run: ``python -m unittest test_ui_state -v``  (stdlib only).

Locks the engine-owned UIStateManager: versioned read side, partial-patch merge with the
`ticker` alias, and the monotonic command stream agents use to steer the frontend.
"""

import unittest

from ui_state import UIStateManager, SCHEMA_VERSION


class TestUIStateRead(unittest.TestCase):
    def setUp(self):
        self.ui = UIStateManager()

    def test_initial_is_versioned_and_empty(self):
        s = self.ui.get()
        self.assertEqual(s["schema_version"], SCHEMA_VERSION)
        self.assertIsNone(s["focused_ticker"])
        self.assertEqual(s["visible_tickers"], [])
        self.assertIsNone(s["last_updated"])

    def test_partial_patch_merges_and_stamps(self):
        self.ui.update({"focused_ticker": "GMX.TO", "active_view": "detailed",
                        "visible_tickers": ["AGA.V", "GMX.TO"]})
        self.ui.update({"selected_whatif": "silver=+5"})        # partial: must not wipe earlier fields
        s = self.ui.get()
        self.assertEqual(s["focused_ticker"], "GMX.TO")
        self.assertEqual(s["active_view"], "detailed")
        self.assertEqual(s["visible_tickers"], ["AGA.V", "GMX.TO"])
        self.assertEqual(s["selected_whatif"], "silver=+5")
        self.assertIsNotNone(s["last_updated"])

    def test_ticker_alias_and_focused_property(self):
        self.ui.update({"ticker": "URC.TO"})                    # alias for focused_ticker
        self.assertEqual(self.ui.focused_ticker, "URC.TO")
        self.assertEqual(self.ui.get()["focused_ticker"], "URC.TO")

    def test_get_returns_a_copy(self):
        self.ui.get()["focused_ticker"] = "HACKED"
        self.assertIsNone(self.ui.focused_ticker)


class TestUICommands(unittest.TestCase):
    def setUp(self):
        self.ui = UIStateManager()

    def test_monotonic_seq_and_payload(self):
        c1 = self.ui.command("focus", {"ticker": "AGA.V"})
        c2 = self.ui.command("view", {"view": "conviction"})
        self.assertEqual(c1["seq"], 1)
        self.assertEqual(c2["seq"], 2)
        self.assertEqual(c1["action"], "focus")
        self.assertEqual(c1["args"], {"ticker": "AGA.V"})
        self.assertEqual(self.ui.last_command["seq"], 2)

    def test_empty_action_raises(self):
        with self.assertRaises(ValueError):
            self.ui.command("", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
