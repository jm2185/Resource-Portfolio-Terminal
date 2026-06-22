"""Hub chat persistence — the conversation tree survives a restart (it was in-memory only, so past
chats vanished every launch). Imports commodityex_tui (needs textual) → skips otherwise; runs in CI."""
import os
import tempfile
import unittest

try:
    import commodityex_tui as tui
    _HAS = True
except Exception:
    _HAS = False


@unittest.skipUnless(_HAS, "textual/rich not installed")
class ConvPersistTest(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get("CEX_CONV_PATH")
        self.path = os.path.join(tempfile.mkdtemp(), "conv.json")
        os.environ["CEX_CONV_PATH"] = self.path

        class _Stub(tui.Cockpit):                 # the real persistence methods, no heavy __init__
            def __init__(s):
                s._conv = {}
                s._node_seq = 0
        self._Stub = _Stub

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("CEX_CONV_PATH", None)
        else:
            os.environ["CEX_CONV_PATH"] = self._orig

    def test_save_then_load_survives_restart(self):
        a = self._Stub()
        a._new_node("you", "why is AGA cheap?", None)
        a._new_node("agent", "below the REP floor", str(a._node_seq))
        self.assertTrue(os.path.exists(self.path))         # _new_node persisted

        b = self._Stub()                                   # simulate a restart (fresh, empty _conv)
        b._load_conv()
        self.assertEqual(len(b._conv), 2)                  # threads came back
        self.assertIn("why is AGA cheap?", [n["text"] for n in b._conv.values()])
        self.assertEqual(b._node_seq, 2)                   # seq counter restored…
        self.assertEqual(b._new_node("you", "follow up", None), "3")   # …so new nodes don't collide

    def test_missing_file_is_an_empty_desk(self):
        os.environ["CEX_CONV_PATH"] = self.path + ".nope"
        b = self._Stub()
        b._load_conv()
        self.assertEqual(b._conv, {})

    def test_corrupt_file_is_fenced(self):
        with open(self.path, "w") as f:
            f.write("{ not valid json")
        b = self._Stub()
        b._load_conv()
        self.assertEqual(b._conv, {})                      # no crash, just an empty desk


if __name__ == "__main__":
    unittest.main()
