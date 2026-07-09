"""memory_write provenance pass-through (2026-07-08 reassessment, TF4 Phase 2.4).

living_memory.write() has accepted + validated ``provenance`` since 07-02; the MCP surface never
passed it, so an agent citing a filing could never be weighted above ``agent`` in the Council's
claim ranking. These tests pin the pass-through and its cap: the agent channel may assert at most
``sourced`` — ``verified`` / ``engine`` / ``user`` clamp down, never through.

Engine-free: memory is temp'd, the regime-context HTTP is stubbed.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import core


class MemoryWriteProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._orig_path, core.MEMORY_PATH = core.MEMORY_PATH, self.tmp
        self._orig_http = core._http_get_json
        core._http_get_json = mock.Mock(side_effect=RuntimeError("no engine in test"))

    def tearDown(self):
        core.MEMORY_PATH = self._orig_path
        core._http_get_json = self._orig_http
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def _last_entry(self):
        with open(self.tmp, encoding="utf-8") as f:
            return json.loads(f.read().splitlines()[-1])

    def test_default_stays_agent(self):
        res = core.memory_write("note", text="ungrounded thought", ticker="AGA.V")
        self.assertTrue(res["ok"])
        self.assertEqual(self._last_entry()["provenance"], "agent")
        self.assertNotIn("note", res)

    def test_sourced_passes_through(self):
        res = core.memory_write("note", text="Q1 MD&A: cash C$41M — https://sedarplus.ca/...",
                                ticker="AGA.V", provenance="sourced")
        self.assertTrue(res["ok"])
        self.assertEqual(res["provenance"], "sourced")
        self.assertEqual(self._last_entry()["provenance"], "sourced")
        self.assertNotIn("note", res)

    def test_above_sourced_clamps(self):
        for tier in ("verified", "engine", "user"):
            res = core.memory_write("note", text="x", ticker="AGA.V", provenance=tier)
            self.assertTrue(res["ok"], tier)
            self.assertEqual(res["provenance"], "sourced", tier)
            self.assertIn("clamped", res.get("note", ""), tier)
            self.assertEqual(self._last_entry()["provenance"], "sourced", tier)

    def test_web_passes_low(self):
        res = core.memory_write("note", text="blog says...", provenance="web")
        self.assertTrue(res["ok"])
        self.assertEqual(self._last_entry()["provenance"], "web")

    def test_unknown_tier_refused(self):
        res = core.memory_write("note", text="x", provenance="gospel")
        self.assertFalse(res["ok"])
        self.assertIn("unknown provenance", res["error"])
        self.assertFalse(os.path.exists(self.tmp))    # refused before any write


if __name__ == "__main__":
    unittest.main()
