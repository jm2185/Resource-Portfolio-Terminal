"""Tests for device focus-state reading (matrix/device.py) — injected reader, no network."""
import unittest


class FocusStateTests(unittest.TestCase):
    def test_reads_focus_key_truthy(self):
        from matrix import device
        self.assertTrue(device.get_focus_state("h", "focusActive", reader=lambda h: {"focusActive": True}))
        self.assertTrue(device.get_focus_state("h", "f", reader=lambda h: {"f": "ON"}))

    def test_falsey_and_missing(self):
        from matrix import device
        self.assertFalse(device.get_focus_state("h", "focusActive", reader=lambda h: {"focusActive": 0}))
        self.assertFalse(device.get_focus_state("h", "missing", reader=lambda h: {}))
        self.assertFalse(device.get_focus_state("h", "x", reader=lambda h: (_ for _ in ()).throw(RuntimeError())))


if __name__ == "__main__":
    unittest.main()
