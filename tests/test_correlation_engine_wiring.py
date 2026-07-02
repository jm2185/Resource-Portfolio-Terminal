"""Engine-side wiring for the conventional-core correlation SENTINEL (Phase 1 of the dual-sided TIV
spec) — the auto-fire the pure ``correlation_monitor`` tests don't cover: the clickable pin (🔗) +
regime-stamped Living-Memory event for a fresh drift / conventional-redundant alarm, with once-per-event
dedup. Binds ``_fire_correlation_drift`` to a lightweight stub (no live engine, no network), exactly as
``test_divergence_engine_wiring`` does for ``_fire_divergence`` — the trend companion it mirrors."""
import unittest

import living_memory
from tests.helpers import TempMemoryMixin, make_engine_stub


class CorrelationEngineWiringTests(TempMemoryMixin, unittest.TestCase):
    def _stub(self):
        return make_engine_stub("_fire_correlation_drift", "record_annotation",
                                config={"correlation_monitor": {}})

    def _ci(self):
        # a conventional sleeve drifting INTO the spear — the alarm the conventional core leans on
        return {"flags": [{"id": "correlation_drift", "ticker": "X.TO", "level": "risk", "active": True,
                           "corr": 0.71, "delta": 0.31,
                           "text": "X.TO ρ to AGA.V rising +0.40→+0.71 (+0.31) — a CONVENTIONAL sleeve "
                                   "correlating to the spear"}]}

    def test_drift_pins_and_logs_once(self):
        s = self._stub()
        s._fire_correlation_drift(self._ci())
        pin = s.terminal_state["agent_annotations"]["X.TO"][-1]
        self.assertEqual(pin["badge"], "🔗")
        self.assertEqual(pin["level"], "risk")
        self.assertEqual(pin["agent"], "sentinel")
        self.assertIsNotNone(pin.get("seq"))                                  # clickable in the dossier
        self.assertEqual(s.state_cache["correlation_fired"]["X.TO"]["bucket"], 0.7)

        n_before = len(s.terminal_state["agent_annotations"]["X.TO"])
        s._fire_correlation_drift(self._ci())                                 # same event, same day, same decile
        self.assertEqual(len(s.terminal_state["agent_annotations"]["X.TO"]), n_before)  # no re-pin

        rows = living_memory.LivingMemory().query(type="sentinel")
        self.assertTrue(any("X.TO" in r.get("text", "") and "spear" in r.get("text", "") for r in rows))

    def test_worsened_correlation_refires(self):
        s = self._stub()
        s._fire_correlation_drift(self._ci())
        worse = self._ci()
        worse["flags"][0]["corr"] = 0.84                                      # 0.7 → 0.8 decile = a new event
        s._fire_correlation_drift(worse)
        self.assertEqual(len(s.terminal_state["agent_annotations"]["X.TO"]), 2)

    def test_no_flags_is_dormant(self):
        s = self._stub()
        s._fire_correlation_drift({"flags": []})
        self.assertEqual(s.terminal_state["agent_annotations"], {})
        s._fire_correlation_drift(None)                                       # never raises
        self.assertEqual(s.terminal_state["agent_annotations"], {})


if __name__ == "__main__":
    unittest.main()
