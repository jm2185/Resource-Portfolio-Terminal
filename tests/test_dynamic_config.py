"""
Run: ``python -m unittest test_dynamic_config -v``  (stdlib only; uses a temp SQLite DB).

Locks the dynamic-config overlay: defaults+overrides merge, allowlist + range validation,
set/reset, the propose->confirm->audit flow, and named scenarios.
"""

import os
import tempfile
import unittest

import engine
from dynamic_config import DynamicConfigManager, ConfigError, _get_path

DEFAULTS = {
    "conservatism_scalar": 0.88,
    "directive_thresholds": {"spear_upside_high_conviction": 0.8, "spear_arbitrage_pct": 50.0},
    "conviction_mode": {"rho_half": 2.0, "delta_floor": 0.1, "support_curve": "linear"},
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

    def test_enum_tunable_support_curve(self):
        # string-enum allowlist entry (conviction_mode.support_curve): valid choices apply,
        # invalid choices reject, and a proposal does NOT change the effective value until confirmed.
        self.assertEqual(_get_path(self.m.effective(), "conviction_mode.support_curve"), "linear")
        with self.assertRaises(ConfigError):
            self.m.set_param("conviction_mode.support_curve", "deep")    # not in choices
        p = self.m.propose("conviction_mode.support_curve", "depth", reason="V6 #1 (lean on)")
        self.assertEqual(p["status"], "pending")
        self.assertEqual(_get_path(self.m.effective(), "conviction_mode.support_curve"), "linear")  # unapplied
        self.m.confirm(p["id"])
        self.assertEqual(_get_path(self.m.effective(), "conviction_mode.support_curve"), "depth")

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

    def test_propose_cut_holding_is_gated(self):
        # the MCP/agent path: cut_holding files a PROPOSAL (not a direct apply) -> operator confirms.
        p = self.m.propose_cut_holding("URC.TO", reason="rotated out of URC")
        self.assertEqual(p["key"], "barbell_weights")
        self.assertNotIn("URC.TO", p["value"])             # the proposed vector already drops URC
        # not applied until confirmed
        self.assertIn("URC.TO", self.m.effective()["barbell_weights"])
        self.m.confirm(p["id"])
        bw = {k: v for k, v in self.m.effective()["barbell_weights"].items() if k != "_comment"}
        self.assertNotIn("URC.TO", bw)
        self.assertAlmostEqual(sum(bw.values()), 1.0)


class TestConfigOverlayReachesEngines(unittest.TestCase):
    """v5.1 engine-audit action #1: the dynamic-config overlay reaches the core engines (was:
    /confirm'd overrides silently bypassed live valuation / JSF / directives because each engine
    re-read the raw file)."""

    def test_get_config_provider_routing(self):
        # No provider wired (standalone engine, e.g. unit tests) -> raw file read, unchanged.
        v = engine.ValuationEngine("v5_config.json")
        self.assertEqual(v.get_config()["conservatism_scalar"], 0.88)
        # A wired provider is served instead of the file (this is what carries the overlay).
        v._config_provider = lambda: {"conservatism_scalar": 0.99, "_sentinel": True}
        self.assertEqual(v.get_config()["conservatism_scalar"], 0.99)
        self.assertTrue(v.get_config()["_sentinel"])
        v._config_provider = None
        self.assertEqual(v.get_config()["conservatism_scalar"], 0.88)

    def test_set_defaults_merges_file_then_overrides(self):
        tmp = os.path.join(tempfile.mkdtemp(), "dc.sqlite")
        dc = DynamicConfigManager({"conservatism_scalar": 0.88}, db_path=tmp)
        self.assertEqual(dc.effective()["conservatism_scalar"], 0.88)
        # file-edit hot-reload: most config is NOT in the allowlist and can only change via the file
        dc.set_defaults({"conservatism_scalar": 0.80, "project_buckets_oz_AgEq": {"x": 1}})
        self.assertEqual(dc.effective()["conservatism_scalar"], 0.80)
        self.assertEqual(dc.effective()["project_buckets_oz_AgEq"], {"x": 1})
        # a confirmed override wins over the file default...
        dc.set_param("conservatism_scalar", 1.10, source="test")
        self.assertEqual(dc.effective()["conservatism_scalar"], 1.10)
        # ...and persists across subsequent file refreshes
        dc.set_defaults({"conservatism_scalar": 0.70})
        self.assertEqual(dc.effective()["conservatism_scalar"], 1.10)

    def test_refresh_effective_config_wires_engines(self):
        m = engine.CommodityExMonitor()
        # swap to a temp-DB overlay so we never touch the real data/dynamic_config.sqlite
        tmp = os.path.join(tempfile.mkdtemp(), "dc.sqlite")
        m.dconfig = DynamicConfigManager(m.config, db_path=tmp)
        m.dconfig.set_param("conservatism_scalar", 1.07, source="test")
        m._refresh_effective_config()
        # the override now reaches the live valuation engine through its provider
        self.assertEqual(m.valuation_engine.get_config()["conservatism_scalar"], 1.07)
        self.assertEqual(m.forensic_engine.get_config()["conservatism_scalar"], 1.07)


if __name__ == "__main__":
    unittest.main(verbosity=2)
