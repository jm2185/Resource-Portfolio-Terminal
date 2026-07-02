"""Engine-side wiring for the conventional-core SENTINEL zones (Phase 4 of the dual-sided TIV spec):
the auto-fire the pure ``conventional_sentinel`` tests don't cover — the clickable pin + regime-stamped
Living-Memory event for a fresh zone cross / rebalance drift, deduped. Binds ``_fire_conventional_zones``
to a stub (no live engine, no network), exactly as the divergence/correlation wiring tests do."""
import unittest

import living_memory
from tests.helpers import TempMemoryMixin, make_engine_stub


class ConventionalZonesWiringTests(TempMemoryMixin, unittest.TestCase):
    def _stub(self):
        return make_engine_stub("_fire_conventional_zones", "_fire_narrative_break",
                                "record_annotation",
                                config={"conventional_sentinel": {}}, mri=45.0)

    def _cz(self):
        return {"flags": [{"id": "asymmetry_zone_cross", "ticker": "X.TO", "level": "warn",
                           "zone": "extended",
                           "text": "X.TO (compounder) crossed ABOVE the priced-in-growth ceiling — torpedo-exposed"}]}

    def test_zone_cross_pins_and_logs_once(self):
        s = self._stub()
        s._fire_conventional_zones(self._cz())
        pin = s.terminal_state["agent_annotations"]["X.TO"][-1]
        self.assertEqual(pin["level"], "warn")
        self.assertEqual(pin["agent"], "sentinel")
        self.assertIsNotNone(pin.get("seq"))
        self.assertEqual(s.state_cache["conventional_zones_fired"]["X.TO"]["key"], "extended")

        n = len(s.terminal_state["agent_annotations"]["X.TO"])
        s._fire_conventional_zones(self._cz())                              # same zone, same day
        self.assertEqual(len(s.terminal_state["agent_annotations"]["X.TO"]), n)   # no re-pin

        rows = living_memory.LivingMemory().query(type="sentinel")
        self.assertTrue(any("X.TO" in r.get("text", "") for r in rows))

    def test_new_zone_refires(self):
        s = self._stub()
        s._fire_conventional_zones(self._cz())
        moved = {"flags": [{"id": "asymmetry_zone_cross", "ticker": "X.TO", "level": "good",
                            "zone": "below_floor", "text": "X.TO fell below the floor"}]}
        s._fire_conventional_zones(moved)
        self.assertEqual(len(s.terminal_state["agent_annotations"]["X.TO"]), 2)

    def test_no_flags_is_dormant(self):
        s = self._stub()
        s._fire_conventional_zones({"flags": []})
        self.assertEqual(s.terminal_state["agent_annotations"], {})
        s._fire_conventional_zones(None)                                    # never raises
        self.assertEqual(s.terminal_state["agent_annotations"], {})

    def test_narrative_break_pins_and_logs_once(self):
        s = self._stub()
        flags = [{"id": "narrative_break", "ticker": "EEFT", "level": "warn", "claim": "Ria",
                  "text": "EEFT: 'Ria resilient' receipt REVERSED — narrative break"}]
        s._fire_narrative_break(flags)
        pin = s.terminal_state["agent_annotations"]["EEFT"][-1]
        self.assertEqual(pin["badge"], "📰")
        self.assertEqual(pin["level"], "warn")
        n = len(s.terminal_state["agent_annotations"]["EEFT"])
        s._fire_narrative_break(flags)                                      # same claim, same day → no re-pin
        self.assertEqual(len(s.terminal_state["agent_annotations"]["EEFT"]), n)
        rows = living_memory.LivingMemory().query(type="sentinel")
        self.assertTrue(any("narrative break" in r.get("text", "").lower() for r in rows))
        s._fire_narrative_break([])                                         # dormant on empty; never raises


if __name__ == "__main__":
    unittest.main()
