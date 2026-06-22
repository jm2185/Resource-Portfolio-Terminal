"""Engine-side wiring for the automated decoupling SENTINEL — the marshalling the pure
``divergence_monitor`` tests don't cover: date-aligned β/σ regression off the cached comps frames, the
per-cycle assess, and the auto-fire (clickable pin + regime-stamped Living-Memory event) with dedup.

Binds the three engine methods to a lightweight stub (no live engine, no network) so a regression like
the `Index`-truthiness bug — an empty baseline that silently disarmed the sentinel — can't return."""
import os
import tempfile
import types
import unittest

import numpy as np
import pandas as pd

import engine
import living_memory

E = engine.CommodityExMonitor

HOLDINGS = [
    {"ticker": "AGA.V", "commodity": "silver", "slot": "silver-spear", "archetype": "option_convexity"},
    {"ticker": "GROY", "commodity": "gold", "slot": "gold-royalty-ballast", "archetype": "asset_light_yield"},
    {"ticker": "GMX.TO", "commodity": "diversified", "slot": "project-generator-holdco"},
    {"ticker": "URC.TO", "commodity": "uranium", "slot": "electrification-royalty"},
]


def _aligned_frames():
    """60 sessions of DATE-ALIGNED returns: AGA = 1.9·silver + noise, GROY = 1.0·gold + noise."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2026-03-01", periods=60)
    si = rng.normal(0, 0.02, 60)
    gc = rng.normal(0, 0.008, 60)
    df_rets = pd.DataFrame({
        "AGA.V": 1.9 * si + rng.normal(0, 0.012, 60),
        "GROY": 1.0 * gc + rng.normal(0, 0.006, 60),
        "GMX.TO": rng.normal(0, 0.02, 60),
        "URC.TO": rng.normal(0, 0.02, 60),
    }, index=idx)
    factor_rets = pd.DataFrame({"SI=F": si, "GC=F": gc}, index=idx)
    return df_rets, factor_rets


class DivergenceEngineWiringTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self._prev_mem = os.environ.get("CEX_MEMORY_PATH")
        os.environ["CEX_MEMORY_PATH"] = self._tmp.name
        self.df_rets, self.factor_rets = _aligned_frames()
        self.vols = {"AGA.V": 0.7, "GROY": 0.25, "GMX.TO": 0.5, "URC.TO": 0.6}

    def tearDown(self):
        if self._prev_mem is None:
            os.environ.pop("CEX_MEMORY_PATH", None)
        else:
            os.environ["CEX_MEMORY_PATH"] = self._prev_mem
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _stub(self, snapshot):
        s = types.SimpleNamespace()
        s.state_cache = {"df_rets": self.df_rets, "factor_rets": self.factor_rets,
                         "vols": self.vols, "divergence_inputs": snapshot}
        s.config = {"divergence_monitor": {"z_min": 2.5, "residual_min": 0.06, "rvol_min": 3.0}}
        s.terminal_state = {"mri": 41.0, "posture": {"code": "balanced"}, "agent_annotations": {}}
        s._agent_seq = 0
        s._lm = None
        for nm in ("_divergence_baseline", "_divergence_assessment", "_fire_divergence", "record_annotation"):
            setattr(s, nm, types.MethodType(getattr(E, nm), s))
        return s

    def test_baseline_regresses_beta_from_aligned_frames(self):
        bl = self._stub({})._divergence_baseline(HOLDINGS)
        self.assertEqual(bl["AGA.V"]["basis"], "regression")
        self.assertAlmostEqual(bl["AGA.V"]["beta"], 1.9, delta=0.25)      # the bug returned {} here
        self.assertAlmostEqual(bl["GROY"]["beta"], 1.0, delta=0.3)
        self.assertEqual(bl["AGA.V"]["n"], 60)
        # holdco / uranium have no cached factor column → conservative own-vol fallback σ, not a crash
        self.assertEqual(bl["GMX.TO"]["basis"], "fallback")
        self.assertEqual(bl["URC.TO"]["basis"], "fallback")

    def test_decouple_flags_pins_and_logs_once(self):
        snap = {"by_ticker": {"AGA.V": {"day_return": 0.12, "volume": 4e5, "adv": 1e5},
                              "GROY": {"day_return": 0.012, "volume": 1e5, "adv": 1e5}},
                "factors": {"silver": -0.02, "gold": 0.012, "copper": None}, "ts": 123.0}
        s = self._stub(snap)
        dash = s._divergence_assessment(HOLDINGS)
        self.assertTrue(dash["by_ticker"]["AGA.V"]["flag"])
        self.assertEqual(dash["by_ticker"]["AGA.V"]["decoupled_basis"], "sigma")   # σ-normalized
        self.assertFalse(dash["by_ticker"]["GROY"]["flag"])                        # tracks gold → leverage
        self.assertEqual(dash["as_of"], 123.0)
        missing = {m["ticker"] for m in dash["coverage"]["missing"]}
        self.assertEqual(missing, {"GMX.TO", "URC.TO"})

        s._fire_divergence(dash)
        pin = s.terminal_state["agent_annotations"]["AGA.V"][-1]
        self.assertEqual(pin["badge"], "⚡")
        self.assertEqual(pin["level"], "warn")
        self.assertEqual(pin["agent"], "sentinel")
        self.assertIsNotNone(pin.get("seq"))                                       # clickable in the dossier
        self.assertEqual(s.state_cache["divergence_fired"]["AGA.V"]["sign"], 1)

        n_before = len(s.terminal_state["agent_annotations"]["AGA.V"])
        s._fire_divergence(dash)                                                   # same event, same day
        self.assertEqual(len(s.terminal_state["agent_annotations"]["AGA.V"]), n_before)  # no re-pin

        rows = living_memory.LivingMemory().query(type="sentinel")
        self.assertTrue(any("decoupled from silver" in r.get("text", "") for r in rows))

    def test_leverage_move_does_not_flag_or_pin(self):
        snap = {"by_ticker": {"AGA.V": {"day_return": 0.12, "volume": 4e5, "adv": 1e5}},
                "factors": {"silver": 0.06}, "ts": 124.0}
        s = self._stub(snap)
        dash = s._divergence_assessment(HOLDINGS)
        self.assertFalse(dash["by_ticker"]["AGA.V"]["flag"])                       # +12% WITH +6% silver
        s._fire_divergence(dash)
        self.assertNotIn("AGA.V", s.terminal_state["agent_annotations"])

    def test_stale_or_empty_snapshot_is_dormant(self):
        s = self._stub({})                                                         # no tape this cycle
        dash = s._divergence_assessment(HOLDINGS)
        self.assertFalse(dash["available"])
        s._fire_divergence(dash)                                                   # nothing to fire
        self.assertEqual(s.terminal_state["agent_annotations"], {})


if __name__ == "__main__":
    unittest.main()
