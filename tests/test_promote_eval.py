"""The promote-to-engine-rated link: a GRADUATED candidate enters the engine's EVAL set through
the human-gated promote_to_eval MCP tool — rated alongside the book (priced, archetype-valued,
T-Q-V scored, hot-loaded next cycle) but holding NO barbell weight and entering NO sizing.
Covers the engine-side eval-set helper, the MCP gates (graduation receipts → archetype →
book-protection → confirm), demotion, and the eval_only echo through the rating."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_server"))

import core  # noqa: E402  (mcp_server/core.py)
import engine  # noqa: E402
import living_memory  # noqa: E402
import research_cache  # noqa: E402
from asymmetry_rating import build_conviction_state  # noqa: E402


class EvalOnlyTickersTests(unittest.TestCase):
    """engine.eval_only_tickers — the single definition of the EVAL set."""

    def test_selects_only_flagged_dict_entries(self):
        cfg = {"portfolio_metadata": {
            "AGA.V": {"archetype": "option_convexity"},                 # book name: no flag
            "KTN.V": {"archetype": "option_convexity", "eval_only": True},
            "ZZZ.V": {"archetype": "prospect_generator", "eval_only": False},
            "_comment": "not a name",
            "_eval_note": {"eval_only": True},                          # underscore -> skipped
        }}
        self.assertEqual(engine.eval_only_tickers(cfg), ["KTN.V"])

    def test_empty_and_malformed_configs(self):
        self.assertEqual(engine.eval_only_tickers({}), [])
        self.assertEqual(engine.eval_only_tickers({"portfolio_metadata": "oops"}), [])
        self.assertEqual(engine.eval_only_tickers(None), [])

    def test_cap_bounds_the_download(self):
        cfg = {"portfolio_metadata": {f"T{i}.V": {"eval_only": True} for i in range(10)}}
        self.assertEqual(len(engine.eval_only_tickers(cfg)), 6)         # default cap
        self.assertEqual(len(engine.eval_only_tickers(cfg, cap=2)), 2)
        self.assertEqual(engine.eval_only_tickers(cfg, cap=0), [])


class _PromoteBase(unittest.TestCase):
    """Sandbox core's module bindings (config / backups / memory / research cache) per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.cfg_path = os.path.join(root, "v5_config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump({"portfolio_metadata": {
                "AGA.V": {"archetype": "option_convexity", "thesis_slot": "silver-spear"}},
                "ballast_valuation": {}}, f)
        self.mem = living_memory.LivingMemory(path=os.path.join(root, "mem.jsonl"))
        self.rc = research_cache.ResearchCache(path=os.path.join(root, "research.json"))
        self._saved = {k: getattr(core, k) for k in
                       ("CONFIG_PATH", "BACKUP_DIR", "_living_memory", "_research_cache", "READONLY")}
        from pathlib import Path
        core.CONFIG_PATH = Path(self.cfg_path)
        core.BACKUP_DIR = Path(root) / ".backups"
        core._living_memory = lambda: self.mem
        core._research_cache = lambda: self.rc
        core.READONLY = False

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(core, k, v)
        self.tmp.cleanup()

    def _graduate(self, tkr="KTN.V"):
        return self.mem.write("graduation", ticker=tkr, text=f"GRADUATED {tkr}",
                              tags=["graduation"], source="graduation-gate")

    def _config(self):
        with open(self.cfg_path, encoding="utf-8") as f:
            return json.load(f)


class PromoteGateTests(_PromoteBase):
    def test_refuses_without_graduation_receipts(self):
        out = core.promote_to_eval("KTN.V", "option_convexity", confirm=True)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("refused"))
        self.assertIn("graduation", out["error"])
        self.assertNotIn("KTN.V", self._config()["portfolio_metadata"])

    def test_refuses_unknown_archetype_never_guesses(self):
        self._graduate()
        out = core.promote_to_eval("KTN.V", "moonshot_vibes", confirm=True)
        self.assertTrue(out.get("refused"))
        self.assertIn("unknown archetype", out["error"])

    def test_refuses_to_overwrite_a_book_holding(self):
        self._graduate("AGA.V")
        out = core.promote_to_eval("AGA.V", "option_convexity", confirm=True)
        self.assertTrue(out.get("refused"))
        self.assertIn("BOOK holding", out["error"])

    def test_refuses_graduation_ref_for_another_name(self):
        other = self._graduate("XYZ.V")
        out = core.promote_to_eval("KTN.V", "option_convexity",
                                   graduation_ref=other["id"], confirm=True)
        self.assertTrue(out.get("refused"))

    def test_dry_call_returns_plan_and_writes_nothing(self):
        self._graduate()
        out = core.promote_to_eval("KTN.V", "option_convexity",
                                   inputs_json=json.dumps({"stage": "PEA"}))
        self.assertEqual(out["status"], "needs_confirmation")
        self.assertIn("KTN.V", out["plan"]["portfolio_metadata"])
        self.assertNotIn("KTN.V", self._config()["portfolio_metadata"])

    def test_research_without_provenance_is_refused(self):
        self._graduate()
        out = core.promote_to_eval("KTN.V", "option_convexity", confirm=True,
                                   inputs_json=json.dumps(
                                       {"research": {"shares_out": {"value": 120e6}}}))
        self.assertTrue(out.get("refused"))
        self.assertIn("provenance", out["error"])

    def test_readonly_blocks_promotion(self):
        core.READONLY = True
        out = core.promote_to_eval("KTN.V", "option_convexity", confirm=True)
        self.assertFalse(out["ok"])
        self.assertIn("read-only", out["error"])


class PromoteWriteTests(_PromoteBase):
    INPUTS = {"type": "explorer", "stage": "PEA", "currency": "CAD",
              "thesis_slot": "silver-spear-challenger", "sector_tags": ["silver"],
              "ballast": {"commodity": "silver", "ref_price": 1.4, "spot_ref": 75.0,
                          "evil_extra": "dropped"},
              "research": {"shares_out": {"value": 120e6, "source": "https://sedar.example/ktn",
                                          "as_of": "2026-06-01", "confidence": "high"}}}

    def test_confirmed_promotion_writes_scoped_sections(self):
        grad = self._graduate()
        out = core.promote_to_eval("KTN.V", "option_convexity", confirm=True,
                                   inputs_json=json.dumps(self.INPUTS),
                                   graduation_ref=grad["id"])
        self.assertTrue(out["ok"], out)
        cfg = self._config()
        meta = cfg["portfolio_metadata"]["KTN.V"]
        self.assertTrue(meta["eval_only"])
        self.assertEqual(meta["archetype"], "option_convexity")
        self.assertEqual(meta["thesis_slot"], "silver-spear-challenger")
        self.assertEqual(meta["graduation_ref"], grad["id"])
        # ballast block is field-scoped (the unknown key never lands in config)
        self.assertEqual(cfg["ballast_valuation"]["KTN.V"],
                         {"commodity": "silver", "ref_price": 1.4, "spot_ref": 75.0})
        # the book holding is untouched
        self.assertNotIn("eval_only", cfg["portfolio_metadata"]["AGA.V"])
        # research lands in the cache WITH provenance
        self.assertEqual(self.rc.value("KTN.V", "shares_out"), 120e6)
        self.assertIn("sedar", self.rc.get("KTN.V", "shares_out")["source"])
        # the promotion is on the record, ref'd to the graduation
        entries = self.mem.query(ticker="KTN.V", type="promotion", limit=1)
        self.assertEqual(len(entries), 1)
        self.assertIn(grad["id"], entries[0]["refs"])
        # a restorable backup exists
        self.assertTrue(any(core.BACKUP_DIR.iterdir()))
        # and the engine-side helper now sees the name
        self.assertEqual(engine.eval_only_tickers(cfg), ["KTN.V"])

    def test_repromote_updates_the_eval_entry(self):
        self._graduate()
        core.promote_to_eval("KTN.V", "option_convexity", confirm=True,
                             inputs_json=json.dumps({"stage": "PEA"}))
        out = core.promote_to_eval("KTN.V", "asset_light_yield", confirm=True,
                                   inputs_json=json.dumps({"stage": "resource"}))
        self.assertTrue(out["ok"], out)
        meta = self._config()["portfolio_metadata"]["KTN.V"]
        self.assertEqual(meta["archetype"], "asset_light_yield")
        self.assertEqual(meta["stage"], "resource")


class DemoteTests(_PromoteBase):
    def test_demotion_refuses_a_book_holding(self):
        out = core.demote_from_eval("AGA.V", confirm=True)
        self.assertTrue(out.get("refused"))
        self.assertIn("AGA.V", self._config()["portfolio_metadata"])

    def test_demotion_removes_only_the_eval_entry(self):
        self._graduate()
        core.promote_to_eval("KTN.V", "option_convexity", confirm=True,
                             inputs_json=json.dumps({"ballast": {"commodity": "silver"}}))
        dry = core.demote_from_eval("KTN.V")
        self.assertEqual(dry["status"], "needs_confirmation")
        self.assertIn("KTN.V", self._config()["portfolio_metadata"])
        out = core.demote_from_eval("KTN.V", reason="failed the spear bar", confirm=True)
        self.assertTrue(out["ok"], out)
        cfg = self._config()
        self.assertNotIn("KTN.V", cfg["portfolio_metadata"])
        self.assertNotIn("KTN.V", cfg["ballast_valuation"])
        self.assertIn("AGA.V", cfg["portfolio_metadata"])
        self.assertEqual(len(self.mem.query(ticker="KTN.V", type="demotion", limit=5)), 1)


class EvalEchoTests(unittest.TestCase):
    """The eval_only marker must survive engine → rating → basket so no consumer can mistake a
    rated eval name for a holding."""

    def test_rating_echoes_eval_flag(self):
        assets = [
            {"ticker": "KTN.V", "archetype": "option_convexity", "eval_only": True,
             "price": 1.0, "floor": 0.8, "base": 1.5, "mri": 47.0},
            {"ticker": "AGA.V", "archetype": "option_convexity",
             "price": 0.7, "floor": 0.6, "base": 1.2, "mri": 47.0},
        ]
        baskets = {b["ticker"]: b for b in build_conviction_state(assets)["baskets"]}
        self.assertTrue(baskets["KTN.V"]["eval_only"])
        self.assertFalse(baskets["AGA.V"]["eval_only"])

    def test_memory_types_registered(self):
        self.assertIn("promotion", living_memory.ENTRY_TYPES)
        self.assertIn("demotion", living_memory.ENTRY_TYPES)


if __name__ == "__main__":
    unittest.main()
