"""
Tests for the one-call conventional add (core.add_holding) + the data-driven CSV symbol map
(conventional_holdings.ws_symbol_map).

The friction being killed: the CEG add took six hand-edits (config block, loader branch, NAV term,
universe, memory, renderer). The contract now: ONE tool call writes the entry, and the entry IS the
integration — the loader matches ws_symbol from config, so no engine edit ever again. Guarantees:

  * membership still means ACTUALLY HELD — units are mandatory (the URC lesson);
  * resource names refuse with the map to the gauntlet path (that friction is design);
  * dry call = plan + a valuation preview through the REAL pipeline; nothing written;
  * confirm writes config (backed up) + a Memory book-change note; re-call UPDATES units;
  * a no-inputs add lands as a VISIBLE unpriceable gap, never hidden;
  * ws_symbol_map only maps conventional entries that declare a symbol.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import conventional_holdings as ch

import core


class WsSymbolMapTests(unittest.TestCase):
    def test_maps_only_conventional_entries_with_a_symbol(self):
        pm = {"AGA.V": {"type": "explorer", "ws_symbol": "AGA"},          # resource — never mapped
              "CEG": {"lane": "conventional", "ws_symbol": "cegs"},
              "IDX": {"lane": "conventional"}}                            # no symbol — no match
        self.assertEqual({"CEGS": "CEG"}, ch.ws_symbol_map(pm))

    def test_live_config_maps_cegs(self):
        cfg = json.load(open("v5_config.json"))
        self.assertEqual("CEG", ch.ws_symbol_map(cfg["portfolio_metadata"]).get("CEGS"))


class AddHoldingTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cfg_path = Path(self.tmpdir) / "v5_config.json"
        shutil.copy("v5_config.json", self.cfg_path)
        self.mem_path = Path(self.tmpdir) / "mem.jsonl"
        self._saved = (core.CONFIG_PATH, core.MEMORY_PATH, core.BACKUP_DIR)
        core.CONFIG_PATH = self.cfg_path
        core.MEMORY_PATH = self.mem_path
        core.BACKUP_DIR = Path(self.tmpdir) / ".bak"

    def tearDown(self):
        core.CONFIG_PATH, core.MEMORY_PATH, core.BACKUP_DIR = self._saved
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cfg(self):
        return json.loads(self.cfg_path.read_text())

    def test_units_are_mandatory(self):
        r = core.add_holding("VFV", units=0)
        self.assertFalse(r["ok"])
        self.assertIn("ACTUALLY HELD", r["error"])

    def test_resource_names_refuse_to_the_gauntlet_path(self):
        r = core.add_holding("AGA.V", units=100)
        self.assertFalse(r["ok"])
        self.assertIn("gauntlet", r["error"])
        r = core.add_holding("GROY", units=1)
        self.assertFalse(r["ok"])

    def test_dry_call_plans_and_writes_nothing(self):
        inputs = {"lens": "compounder", "price": 100.0, "shares_out": 1e9, "fcf": 5e9,
                  "wacc": 0.08, "cap_years": 10, "growth": {"p10": 0.02, "p50": 0.06, "p90": 0.1}}
        r = core.add_holding("VFV", units=10, ws_symbol="VFV", instrument="VFV (TSX ETF)",
                             inputs_json=json.dumps(inputs))
        self.assertEqual("needs_confirmation", r["status"])
        self.assertEqual("ADD", r["plan"]["action"])
        self.assertIsNotNone(r["plan"]["preview"].get("rating"))   # previewed through the pipeline
        self.assertNotIn("VFV", self._cfg()["portfolio_metadata"])  # nothing written

    def test_confirm_writes_config_backup_memory_and_loader_map(self):
        inputs = {"lens": "compounder", "price": 100.0, "shares_out": 1e9, "fcf": 5e9,
                  "wacc": 0.08, "cap_years": 10, "growth": {"p10": 0.02, "p50": 0.06, "p90": 0.1}}
        r = core.add_holding("VFV", units=10, ws_symbol="VFV", instrument="VFV (TSX ETF)",
                             inputs_json=json.dumps(inputs), confirm=True)
        self.assertTrue(r["ok"], r)
        pm = self._cfg()["portfolio_metadata"]
        self.assertEqual("conventional", pm["VFV"]["lane"])
        self.assertEqual(10, pm["VFV"]["units"])
        self.assertEqual("VFV", ch.ws_symbol_map(pm).get("VFV"))    # the loader map — no engine edit
        self.assertNotIn("VFV", self._cfg()["barbell_weights"])     # priced, never sized
        self.assertTrue(os.path.exists(r["backup"].replace(".mcp_backups", str(core.BACKUP_DIR))))
        from living_memory import LivingMemory
        notes = LivingMemory(str(self.mem_path)).query(tag="book-change", limit=0)
        self.assertEqual(1, len(notes))

    def test_recall_updates_units_the_tranche_flow(self):
        inputs = {"lens": "compounder", "price": 100.0, "shares_out": 1e9, "fcf": 5e9,
                  "wacc": 0.08, "cap_years": 10, "growth": {"p10": 0.02, "p50": 0.06, "p90": 0.1}}
        core.add_holding("VFV", units=10, ws_symbol="VFV", inputs_json=json.dumps(inputs),
                         confirm=True)
        r = core.add_holding("VFV", units=25, confirm=True)         # tranche 2 filled
        self.assertEqual("UPDATE", r["action"])
        pm = self._cfg()["portfolio_metadata"]
        self.assertEqual(25, pm["VFV"]["units"])
        self.assertEqual("VFV", pm["VFV"]["ws_symbol"])             # prior fields preserved
        self.assertIn("dual_sided", pm["VFV"])                      # underwriting survives an update

    def test_no_inputs_lands_as_a_visible_gap(self):
        r = core.add_holding("VFV", units=10, confirm=True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["preview"].get("unpriceable"))
        reads = ch.build_reads(ch.positions(self._cfg()["portfolio_metadata"]))
        self.assertIn("error", reads["VFV"])                        # shown, not hidden

    def test_ceg_update_via_the_same_tool(self):
        """The real Thursday flow: tranche 2 fills → one call bumps CEG's units."""
        r = core.add_holding("CEG", units=54, confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual("UPDATE", r["action"])
        pm = self._cfg()["portfolio_metadata"]
        self.assertEqual(54, pm["CEG"]["units"])
        self.assertEqual("CEGS", pm["CEG"]["ws_symbol"])
        self.assertIn("dual_sided", pm["CEG"])                      # underwriting untouched


if __name__ == "__main__":
    unittest.main()
