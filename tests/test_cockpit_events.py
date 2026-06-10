"""
Tests for cockpit event detection (cockpit_events.py) — the semantic state-change layer.

Pins: cold start fires nothing; a posture flip / JSF trip / directive change each become a typed
event; only the signal-worthy ones carry persist=True (so the audit record stays clean); a tightening
posture flags warn while an easing one flags good.
"""
import unittest

import cockpit_events as ce


def _state(posture_code="spear_exploit", posture_label="SPEAR EXPLOIT", gate_aga=False,
           aga_directive="BELOW FLOOR — ACCUMULATE · watch closely"):
    return {
        "posture": {"code": posture_code, "label": posture_label, "cap": 0.75},
        "conviction_mode": {"baskets": [
            {"ticker": "AGA.V", "directive": aga_directive, "gate": {"applied": gate_aga}},
            {"ticker": "GROY", "directive": "QUALITY — CORE HOLD", "gate": {"applied": False}},
        ]},
    }


class SnapshotTests(unittest.TestCase):
    def test_reduces_to_comparable_shape(self):
        s = ce.snapshot(_state())
        self.assertEqual(s["posture"]["code"], "spear_exploit")
        self.assertEqual(s["gates"], {"AGA.V": False, "GROY": False})
        self.assertIn("AGA.V", s["directives"])


class DetectTests(unittest.TestCase):
    def test_cold_start_fires_nothing(self):
        self.assertEqual(ce.detect_events({}, ce.snapshot(_state())), [])

    def test_posture_flip_to_defensive_is_warn_and_persisted(self):
        prev = ce.snapshot(_state(posture_code="spear_exploit"))
        curr = ce.snapshot(_state(posture_code="defensive", posture_label="DEFENSIVE"))
        evs = ce.detect_events(prev, curr)
        p = [e for e in evs if e["kind"] == "posture"]
        self.assertEqual(len(p), 1)
        self.assertIn("DEFENSIVE", p[0]["summary"])
        self.assertEqual(p[0]["level"], "warn")        # tightening
        self.assertTrue(p[0]["persist"])               # book-level regime change -> memory

    def test_posture_easing_is_good(self):
        prev = ce.snapshot(_state(posture_code="defensive"))
        curr = ce.snapshot(_state(posture_code="spear_exploit", posture_label="SPEAR EXPLOIT"))
        p = [e for e in ce.detect_events(prev, curr) if e["kind"] == "posture"][0]
        self.assertEqual(p["level"], "good")

    def test_jsf_trip_is_risk_and_persisted(self):
        prev = ce.snapshot(_state(gate_aga=False))
        curr = ce.snapshot(_state(gate_aga=True))
        a = [e for e in ce.detect_events(prev, curr) if e["kind"] == "alert"]
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["ticker"], "AGA.V")
        self.assertEqual(a[0]["level"], "risk")
        self.assertTrue(a[0]["persist"])

    def test_jsf_clear_is_informational_not_persisted(self):
        prev = ce.snapshot(_state(gate_aga=True))
        curr = ce.snapshot(_state(gate_aga=False))
        n = [e for e in ce.detect_events(prev, curr) if "cleared" in e["summary"]]
        self.assertEqual(len(n), 1)
        self.assertFalse(n[0]["persist"])              # not audit-worthy

    def test_directive_flip_is_informational(self):
        prev = ce.snapshot(_state(aga_directive="BELOW FLOOR — ACCUMULATE"))
        curr = ce.snapshot(_state(aga_directive="UPSIDE SPENT — HOLD / TRIM"))
        n = [e for e in ce.detect_events(prev, curr) if e.get("ticker") == "AGA.V" and e["kind"] == "note"]
        self.assertEqual(len(n), 1)
        self.assertIn("ACCUMULATE", n[0]["summary"])
        self.assertIn("TRIM", n[0]["summary"])
        self.assertFalse(n[0]["persist"])

    def test_no_change_no_events(self):
        s = ce.snapshot(_state())
        self.assertEqual(ce.detect_events(s, s), [])

    def test_only_signal_worthy_persist(self):
        # a busy cycle: posture flip (persist) + jsf trip (persist) + directive flip (no persist)
        prev = ce.snapshot(_state(posture_code="balanced", gate_aga=False,
                                  aga_directive="THESIS INTACT — MONITOR"))
        curr = ce.snapshot(_state(posture_code="defensive", posture_label="DEFENSIVE", gate_aga=True,
                                  aga_directive="UPSIDE SPENT — HOLD / TRIM"))
        evs = ce.detect_events(prev, curr)
        persisted = [e for e in evs if e["persist"]]
        self.assertEqual({e["kind"] for e in persisted}, {"posture", "alert"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
