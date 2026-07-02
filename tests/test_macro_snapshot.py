"""macro_snapshot — the ONE per-cycle resolver of the shared regime inputs (Arch 5).

Locks the invariants the engine call sites rely on: metric cells unwrap with alias precedence,
an unpopulated signal stays None (defaults are the CONSUMER's, not the snapshot's), and the tape
reads (signed risk_on ratio, net_tilt) match the legacy in-engine closures exactly.
"""
import unittest

import macro_snapshot


class MetricValueTests(unittest.TestCase):
    def test_unwraps_value_cells_and_plain_values(self):
        m = {"GSR": {"value": 91.3, "status": "LIVE"}, "Real_Yield": 1.1}
        self.assertEqual(macro_snapshot.metric_value(m, "GSR"), 91.3)
        self.assertEqual(macro_snapshot.metric_value(m, "Real_Yield"), 1.1)

    def test_alias_precedence_first_non_none_wins(self):
        m = {"REAL_YIELD": {"value": None}, "Real_Yield": {"value": 2.4}}
        self.assertEqual(macro_snapshot.metric_value(m, "REAL_YIELD", "Real_Yield"), 2.4)

    def test_default_and_graceful_none_metrics(self):
        self.assertIsNone(macro_snapshot.metric_value({}, "GSR"))
        self.assertEqual(macro_snapshot.metric_value(None, "GSR", default=80.0), 80.0)


class SnapshotTests(unittest.TestCase):
    def test_resolves_all_shared_signals(self):
        ts = {"metrics": {"GSR": {"value": 91.3}, "DXY_MOMENTUM": {"value": -0.4},
                          "Real_Yield": 1.1, "URANIUM_TERM": {"value": 0.3}},
              "macro_tape": {"risk_on_count": 6, "risk_off_count": 2, "net_tilt": "RISK-ON"}}
        s = macro_snapshot.snapshot(ts)
        self.assertEqual(s, {"real_yield": 1.1, "gsr": 91.3, "uranium_term": 0.3,
                             "dxy_mom": -0.4, "risk_on": 0.5, "net_tilt": "RISK-ON"})

    def test_unpopulated_signals_stay_none_defaults_are_the_consumers(self):
        s = macro_snapshot.snapshot({"metrics": {}, "macro_tape": {}})
        for k in ("real_yield", "gsr", "uranium_term", "dxy_mom", "net_tilt"):
            self.assertIsNone(s[k], k)
        self.assertEqual(s["risk_on"], 0.0)     # empty tape → 0.0, same as the legacy closure

    def test_risk_on_ratio_matches_legacy_formula(self):
        ts = {"metrics": {}, "macro_tape": {"risk_on_count": 1, "risk_off_count": 4}}
        self.assertAlmostEqual(macro_snapshot.snapshot(ts)["risk_on"], (1 - 4) / 5)

    def test_graceful_on_absent_state(self):
        s = macro_snapshot.snapshot(None)
        self.assertEqual(s["risk_on"], 0.0)
        self.assertIsNone(s["real_yield"])


if __name__ == "__main__":
    unittest.main()
