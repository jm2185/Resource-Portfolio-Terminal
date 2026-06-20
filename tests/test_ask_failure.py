"""A background ask that fails (timeout / CLI-missing / exception) must NOT leave the chat hung on
'thinking…'. `_deliver_error` clears `_pending_user`, drops the Working-lane entry + live preview, and
surfaces the reason as a reply node in the thread. Imports commodityex_tui (needs textual) → skips when
the TUI stack isn't installed; runs in CI.
"""
import unittest

try:
    import commodityex_tui as tui
    _HAS = True
except Exception:
    _HAS = False


@unittest.skipUnless(_HAS, "textual/rich not installed")
class DeliverErrorTest(unittest.TestCase):
    def setUp(self):
        self.app = tui.Cockpit()
        # a question node 'u1' is mid-flight: pending + in the Working lane + a live stream preview
        self.app._conv["u1"] = {"id": "u1", "parent": None, "role": "you",
                                "text": "scout electrification", "ticker": ""}
        self.app._pending_user = "u1"
        self.app._active = "u1"
        self.app._inflight = {7: {"label": "scout", "agent": "scout"}}
        self.app._stream_buf = {"u1": "partial work…"}

    def test_clears_pending_lane_preview_and_surfaces_reason(self):
        self.app._deliver_error("u1", 7, "⚠ ask timed out after 300s", agent="scout")
        self.assertIsNone(self.app._pending_user)            # the chat no longer hangs on 'thinking…'
        self.assertNotIn(7, self.app._inflight)              # Working-lane entry dropped (it already ended)
        self.assertNotIn("u1", self.app._stream_buf)         # live preview cleared
        agent_nodes = [n for n in self.app._conv.values()
                       if n.get("role") == "agent" and n.get("parent") == "u1"]
        self.assertEqual(len(agent_nodes), 1)                # the reason is now a reply in the thread
        self.assertIn("timed out", agent_nodes[0]["text"])

    def test_only_clears_the_matching_pending(self):
        self.app._pending_user = "u2"                        # a NEWER ask is now the pending one
        self.app._deliver_error("u1", 7, "⚠ ask failed", agent="scout")
        self.assertEqual(self.app._pending_user, "u2")       # don't clear a different ask's wait
        self.assertNotIn(7, self.app._inflight)              # but still tidy up the finished run


if __name__ == "__main__":
    unittest.main()
