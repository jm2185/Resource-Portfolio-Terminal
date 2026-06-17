"""
Run: ``python -m unittest tests.test_remove_holding -v``

Locks the cockpit-native DECOMMISSION path (``remove_holding``): the AGA-capped redistribution math,
the refusals (spear / unknown / eval-only / last-ballast), the dry-run write plan, and the full
ticker-keyed config cleanup. File I/O is mocked so the real v5_config.json is never touched.
"""

import copy
import unittest
from unittest import mock

from mcp_server import core


def _fixture_cfg():
    return {
        "barbell_weights": {"_comment": "the book", "AGA.V": 0.60, "GROY": 0.15,
                            "URC.TO": 0.15, "GMX.TO": 0.10},
        "portfolio_metadata": {
            "AGA.V": {"archetype": "option_convexity"},
            "GROY": {"archetype": "asset_light_yield"},
            "GMX.TO": {"archetype": "asset_light_yield"},
            "URC.TO": {"archetype": "asset_light_yield", "thesis_slot": "electrification-royalty"},
            "NXE.V": {"archetype": "asset_light_yield", "eval_only": True},  # an eval-only name
        },
        "ballast_multiples": {"URC.TO": 1.15, "GROY": 1.15, "GMX.TO": 1.20},
        "ballast_valuation": {"URC.TO": {"currency": "CAD"}, "GROY": {"currency": "USD"}},
        "archetype_barbell_weights": {"AGA.V": 0.60, "URC.TO": 0.15, "GROY": 0.15, "GMX.TO": 0.10},
        "catalysts": {"providers": {
            "rss_news": {"ticker_aliases": {"URC.TO": ["uranium royalty corp"], "GROY": ["gold royalty"]}},
            "marketaux_news": {"symbol_map": {"URC.TO": "URC.TO", "GROY": "GROY"}},
        }},
    }


class RedistributeMathTest(unittest.TestCase):
    def test_cut_urc_matches_pro_rata_capped_vector(self):
        # Cutting URC (0.15) from the live book: AGA is at the 60% ceiling so its weight flows to the
        # ballast pro-rata -> the exact {AGA 0.60, GROY 0.24, GMX 0.16} the cockpit cut also produces.
        survivors = {"AGA.V": 0.60, "GROY": 0.15, "GMX.TO": 0.10}
        out = core._redistribute_weights(survivors, 0.15)
        self.assertAlmostEqual(out["AGA.V"], 0.60, places=4)
        self.assertAlmostEqual(out["GROY"], 0.24, places=4)
        self.assertAlmostEqual(out["GMX.TO"], 0.16, places=4)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

    def test_aga_ceiling_never_breached(self):
        # Remove a sleeve leaving only AGA + one ballast: AGA must stay capped, ballast absorbs.
        out = core._redistribute_weights({"AGA.V": 0.60, "GMX.TO": 0.16}, 0.24)
        self.assertLessEqual(out["AGA.V"], 0.60 + 1e-9)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)


class RemoveHoldingTest(unittest.TestCase):
    def setUp(self):
        self._ro = mock.patch.object(core, "READONLY", False)
        self._ro.start()
        self.addCleanup(self._ro.stop)
        self.written = {}

        def _capture(cfg):
            self.written["cfg"] = copy.deepcopy(cfg)
            return ".mcp_backups/v5_config.json.bak"

        self.p_load = mock.patch.object(core, "_load_raw_config", side_effect=lambda: copy.deepcopy(_fixture_cfg()))
        self.p_write = mock.patch.object(core, "_write_raw_config", side_effect=_capture)
        self.p_post = mock.patch.object(core, "_http_post_json", return_value={"ok": True})
        mem = mock.MagicMock()
        mem.write.return_value = {"id": "mem_1"}
        self.p_mem = mock.patch.object(core, "_living_memory", return_value=mem)
        for p in (self.p_load, self.p_write, self.p_post, self.p_mem):
            p.start()
            self.addCleanup(p.stop)

    # ---- refusals --------------------------------------------------------
    def test_refuses_spear(self):
        res = core.remove_holding("AGA.V", confirm=True)
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("refused"))
        self.assertNotIn("cfg", self.written)            # nothing written

    def test_refuses_unknown(self):
        res = core.remove_holding("ZZZ.V", confirm=True)
        self.assertFalse(res["ok"])
        self.assertNotIn("cfg", self.written)

    def test_refuses_eval_only_routes_to_demote(self):
        res = core.remove_holding("NXE.V", confirm=True)
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("refused"))
        self.assertIn("demote_from_eval", res["error"])

    def test_refuses_when_no_ballast_would_remain(self):
        two_name = {"barbell_weights": {"AGA.V": 0.60, "GROY": 0.40},
                    "portfolio_metadata": {"AGA.V": {}, "GROY": {}}}
        with mock.patch.object(core, "_load_raw_config", side_effect=lambda: copy.deepcopy(two_name)):
            res = core.remove_holding("GROY", confirm=True)
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("refused"))
        self.assertNotIn("cfg", self.written)

    # ---- dry run ---------------------------------------------------------
    def test_dry_run_returns_plan_and_writes_nothing(self):
        res = core.remove_holding("URC.TO", confirm=False)
        self.assertEqual(res.get("status"), "needs_confirmation")
        self.assertIn("barbell_weights", res["plan"]["removes_from"])
        self.assertIn("portfolio_metadata", res["plan"]["removes_from"])
        self.assertIn("archetype_barbell_weights", res["plan"]["removes_from"])
        self.assertTrue(any("ticker_aliases" in b for b in res["plan"]["removes_from"]))
        self.assertNotIn("URC.TO", res["plan"]["barbell_after"])
        self.assertNotIn("cfg", self.written)            # confirm=False writes nothing

    # ---- apply -----------------------------------------------------------
    def test_confirm_cleans_every_block(self):
        res = core.remove_holding("URC.TO", reason="rotated out", confirm=True)
        self.assertTrue(res["ok"])
        cfg = self.written["cfg"]
        self.assertNotIn("URC.TO", cfg["barbell_weights"])
        self.assertNotIn("URC.TO", cfg["portfolio_metadata"])
        self.assertNotIn("URC.TO", cfg["ballast_multiples"])
        self.assertNotIn("URC.TO", cfg["ballast_valuation"])
        self.assertNotIn("URC.TO", cfg["archetype_barbell_weights"])
        self.assertNotIn("URC.TO", cfg["catalysts"]["providers"]["rss_news"]["ticker_aliases"])
        self.assertNotIn("URC.TO", cfg["catalysts"]["providers"]["marketaux_news"]["symbol_map"])
        # survivors untouched, _comment preserved, sums to 1, AGA capped
        self.assertIn("GROY", cfg["barbell_weights"])
        self.assertEqual(cfg["barbell_weights"].get("_comment"), "the book")
        bw = {k: v for k, v in cfg["barbell_weights"].items() if k != "_comment"}
        self.assertAlmostEqual(sum(bw.values()), 1.0, places=6)
        self.assertLessEqual(bw["AGA.V"], 0.60 + 1e-9)

    def test_confirm_clears_overlay_and_logs_memory(self):
        res = core.remove_holding("URC.TO", confirm=True)
        self.assertEqual(res["overlay"], "cleared")
        core._http_post_json.assert_any_call("/config/param/reset", {"key": "barbell_weights"})
        self.assertEqual(res["memory_id"], "mem_1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
