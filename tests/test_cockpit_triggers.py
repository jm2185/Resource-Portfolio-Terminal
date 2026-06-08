"""
Tests for reactive triggers (cockpit_triggers.py). Pins the three guardrails: decision-support only
(pin/highlight, never a book action), rate-limited (cooldown suppresses re-fires / flapping), and
that only the intended events trigger.
"""
import unittest

import cockpit_triggers as ct


class EvaluateTests(unittest.TestCase):
    def test_defensive_posture_pins_a_caution(self):
        evs = [{"kind": "posture", "summary": "posture → DEFENSIVE", "level": "warn", "persist": True}]
        out = ct.evaluate(evs, fired={}, now=1000.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["action"], "pin")
        self.assertEqual(out[0]["level"], "warn")
        self.assertIn("DEFENSIVE", out[0]["text"].upper())

    def test_easing_posture_does_not_trigger(self):
        evs = [{"kind": "posture", "summary": "posture → SPEAR EXPLOIT", "level": "good"}]
        self.assertEqual(ct.evaluate(evs, fired={}, now=1000.0), [])

    def test_jsf_trip_highlights_risk(self):
        evs = [{"kind": "alert", "summary": "JSF gate tripped on AGA.V", "ticker": "AGA.V", "level": "risk"}]
        out = ct.evaluate(evs, fired={}, now=1000.0)
        self.assertEqual(out[0]["action"], "highlight")
        self.assertEqual(out[0]["ticker"], "AGA.V")
        self.assertEqual(out[0]["level"], "risk")

    def test_outputs_are_only_pin_or_highlight_never_book_actions(self):
        evs = [{"kind": "posture", "summary": "posture → DEFENSIVE"},
               {"kind": "alert", "summary": "JSF gate tripped on AGA.V", "ticker": "AGA.V"}]
        for a in ct.evaluate(evs, fired={}, now=1000.0):
            self.assertIn(a["action"], ("pin", "highlight"))   # decision-support only

    def test_cooldown_rate_limits_retrigger(self):
        evs = [{"kind": "alert", "summary": "JSF gate tripped on AGA.V", "ticker": "AGA.V"}]
        fired = {"jsf:AGA.V": 1000.0}
        # within the cooldown window -> suppressed
        self.assertEqual(ct.evaluate(evs, fired=fired, now=1000.0 + 60), [])
        # after the cooldown -> fires again
        self.assertEqual(len(ct.evaluate(evs, fired=fired, now=1000.0 + ct.COOLDOWN_SECONDS + 1)), 1)

    def test_unrelated_events_are_ignored(self):
        evs = [{"kind": "note", "summary": "AGA.V: ACCUMULATE → TRIM", "ticker": "AGA.V"},
               {"kind": "note", "summary": "JSF gate cleared on AGA.V", "ticker": "AGA.V"}]
        self.assertEqual(ct.evaluate(evs, fired={}, now=1000.0), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
