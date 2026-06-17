"""
Run: ``python -m unittest test_dynamic_config -v``  (stdlib only; uses a temp SQLite DB).

Locks the dynamic-config overlay: defaults+overrides merge, allowlist + range validation,
set/reset, the propose->confirm->audit flow, and named scenarios.
"""

import os
import tempfile
import unittest

from dynamic_config import DynamicConfigManager, ConfigError, _get_path

DEFAULTS = {
    "conservatism_scalar": 0.88,
    "directive_thresholds": {"spear_upside_high_conviction": 0.8, "spear_arbitrage_pct": 50.0},
    "conviction_mode": {"rho_half": 2.0, "delta_floor": 0.1},
    "archetype_routing": {"developer": "commodity_cyclical"},  # NOT allowlisted -> protected
}


class DynamicConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = DynamicConfigManager(DEFAULTS, db_path=os.path.join(self.tmp, "c.sqlite"))

    def test_effective_equals_defaults_initially(self):
        self.assertEqual(self.m.effective()["conservatism_scalar"], 0.88)
        self.assertEqual(_get_path(self.m.effective(), "conviction_mode.rho_half"), 2.0)

    def test_set_overrides_and_hot_value(self):
        self.m.set_param("conservatism_scalar", 1.10)
        self.assertEqual(self.m.effective()["conservatism_scalar"], 1.10)
        self.m.set_param("conviction_mode.rho_half", 3.5)          # nested path
        self.assertEqual(_get_path(self.m.effective(), "conviction_mode.rho_half"), 3.5)
        # defaults object is untouched (overlay, not mutation)
        self.assertEqual(DEFAULTS["conservatism_scalar"], 0.88)

    def test_allowlist_and_range_validation(self):
        with self.assertRaises(ConfigError):
            self.m.set_param("archetype_routing.developer", "asset_light_yield")  # not allowlisted
        with self.assertRaises(ConfigError):
            self.m.set_param("conservatism_scalar", 9.9)            # above max
        with self.assertRaises(ConfigError):
            self.m.set_param("conservatism_scalar", "abc")          # wrong type

    def test_reset_returns_to_default(self):
        self.m.set_param("conservatism_scalar", 1.2)
        self.m.reset_param("conservatism_scalar")
        self.assertEqual(self.m.effective()["conservatism_scalar"], 0.88)

    def test_propose_confirm_flow_with_audit(self):
        p = self.m.propose("discovery_multiple" if False else "conservatism_scalar", 1.05,
                           reason="regime turned risk-on; loosen conservatism")
        self.assertEqual(self.m.effective()["conservatism_scalar"], 0.88)  # not applied yet
        self.assertEqual(len(self.m.pending()), 1)
        self.m.confirm(p["id"])
        self.assertEqual(self.m.effective()["conservatism_scalar"], 1.05)  # applied on confirm
        self.assertEqual(len(self.m.pending()), 0)                          # cleared from queue

    def test_propose_requires_reason_and_validates(self):
        with self.assertRaises(ConfigError):
            self.m.propose("conservatism_scalar", 1.0, reason="")
        with self.assertRaises(ConfigError):
            self.m.propose("conservatism_scalar", 99.0, reason="too high")  # range fails fast

    def test_list_params_marks_overridden(self):
        self.m.set_param("conservatism_scalar", 1.1)
        rows = {r["key"]: r for r in self.m.list_params()}
        self.assertTrue(rows["conservatism_scalar"]["overridden"])
        self.assertFalse(rows["conviction_mode.rho_half"]["overridden"])
        self.assertEqual(rows["conviction_mode.rho_half"]["default"], 2.0)

    def test_scenarios_roundtrip(self):
        self.m.save_scenario("bull_silver", {"spot_ag": "+5", "peer_ev_oz": "+20%"})
        self.assertEqual(self.m.get_scenario("bull_silver"), {"spot_ag": "+5", "peer_ev_oz": "+20%"})
        self.assertIn("bull_silver", [s["name"] for s in self.m.list_scenarios()])
        with self.assertRaises(ConfigError):
            self.m.save_scenario("", {"x": 1})


BOOK_DEFAULTS = {
    "barbell_weights": {"_comment": "test book", "AGA.V": 0.60, "GROY": 0.15,
                        "URC.TO": 0.15, "GMX.TO": 0.10},
}


class BarbellOverlayTest(unittest.TestCase):
    """Cockpit-native book rebalancing over the same overlay (set/propose/confirm + hot effective)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = DynamicConfigManager(BOOK_DEFAULTS, db_path=os.path.join(self.tmp, "b.sqlite"))

    def test_set_barbell_vector_flows_to_effective(self):
        self.m.set_param("barbell_weights", {"AGA.V": 0.60, "GROY": 0.25, "GMX.TO": 0.15})
        bw = self.m.effective()["barbell_weights"]
        self.assertEqual(bw["GROY"], 0.25)
        self.assertAlmostEqual(sum(v for k, v in bw.items() if k != "_comment"), 1.0)
        self.assertEqual(bw["_comment"], "test book")          # provenance preserved

    def test_rejects_bad_sum_ceiling_and_unknown(self):
        with self.assertRaises(ConfigError):
            self.m.set_param("barbell_weights", {"AGA.V": 0.5, "GROY": 0.3})       # sums to 0.8
        with self.assertRaises(ConfigError):
            self.m.set_param("barbell_weights", {"AGA.V": 0.7, "GROY": 0.3})       # AGA over ceiling
        with self.assertRaises(ConfigError):
            self.m.set_param("barbell_weights", {"AGA.V": 0.6, "ZZZ": 0.4})        # not a holding

    def test_cut_holding_redistributes_within_ceiling(self):
        # the live ask: cut URC, push into the survivors — AGA is already at the 60% ceiling, so the
        # weight must flow to GROY + GMX ("mainly GMX and GROY"), not AGA.
        self.m.cut_holding("URC.TO")
        bw = {k: v for k, v in self.m.effective()["barbell_weights"].items() if k != "_comment"}
        self.assertNotIn("URC.TO", bw)
        self.assertAlmostEqual(sum(bw.values()), 1.0)
        self.assertLessEqual(bw["AGA.V"], 0.60 + 1e-9)         # ceiling held
        self.assertGreater(bw["GROY"], 0.15)                   # GROY took share
        self.assertGreater(bw["GMX.TO"], 0.10)                 # GMX took share

    def test_propose_confirm_barbell(self):
        p = self.m.propose("barbell_weights", {"AGA.V": 0.60, "GROY": 0.24, "GMX.TO": 0.16},
                           reason="rotate URC out into GROY/GMX")
        self.m.confirm(p["id"])
        self.assertEqual(self.m.effective()["barbell_weights"]["GMX.TO"], 0.16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
