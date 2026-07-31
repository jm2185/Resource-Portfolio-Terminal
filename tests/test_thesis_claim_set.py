"""
Tests for the claim-resolution flow — thesis_ledger.set_claim_status / claim_status_summary and the
MCP tool core.thesis_claim_set.

This is R-7's last mile: criteria pre-registered as claims are only enforceable if the operator can
resolve them after the event without hand-editing the store. The guarantees pinned here:

  * only MANUAL claims flip — an engine claim refuses (the Sentinel owns those against live
    metrics; a hand flip would be overwritten or would lie);
  * a typo (unknown claim id, unknown status) refuses loudly — it must not look like a verdict;
  * the flip SUPERSEDES the thesis (append-only: the pre-event record survives) and lands in the
    claim's ``history`` with who/when/why;
  * the Sentinel's integrity math picks the flip up — the whole point of storing criteria as
    claims.
"""
import os
import tempfile
import unittest
from pathlib import Path

import sentinel as sen
import thesis_ledger as tl
from living_memory import LivingMemory

import core


def _body():
    return tl.build_thesis(
        "CEG", stance="CONDITIONAL",
        claims=[
            tl.new_claim("guide reaffirmed", cid="c1", check="manual", status="unknown"),
            tl.new_claim("PPA pipeline intact", cid="c2", check="manual", status="unknown"),
            tl.new_claim("phi holds", cid="c3", metric="phi", op=">=", threshold=1.0),
        ],
        rules=[tl.new_rule("event:earnings", "review", rid="r1")])


class SetClaimStatusTests(unittest.TestCase):
    def test_flips_a_manual_claim_and_records_history(self):
        out = tl.set_claim_status(_body(), "c1", "holds", note="guide $11-12 reaffirmed on call",
                                  actor="operator", ts="2026-08-06T15:00:00Z")
        c1 = [c for c in out["claims"] if c["id"] == "c1"][0]
        self.assertEqual("holds", c1["status"])
        self.assertEqual(1, len(c1["history"]))
        h = c1["history"][0]
        self.assertEqual(("unknown", "holds", "operator"), (h["from"], h["to"], h["actor"]))
        self.assertIn("reaffirmed", h["note"])

    def test_original_body_is_not_mutated(self):
        body = _body()
        tl.set_claim_status(body, "c1", "broken")
        self.assertEqual("unknown", body["claims"][0]["status"])   # caller's copy untouched

    def test_engine_claim_refuses(self):
        with self.assertRaises(ValueError) as cm:
            tl.set_claim_status(_body(), "c3", "holds")
        self.assertIn("ENGINE claim", str(cm.exception))

    def test_unknown_claim_and_status_refuse_loudly(self):
        with self.assertRaises(ValueError):
            tl.set_claim_status(_body(), "c9", "holds")
        with self.assertRaises(ValueError):
            tl.set_claim_status(_body(), "c1", "confirmed")        # not a CLAIM_STATUS

    def test_second_flip_appends_history_not_replaces(self):
        out = tl.set_claim_status(_body(), "c1", "broken", ts="t1")
        out = tl.set_claim_status(out, "c1", "holds", note="corrected after transcript", ts="t2")
        c1 = [c for c in out["claims"] if c["id"] == "c1"][0]
        self.assertEqual(["t1", "t2"], [h["ts"] for h in c1["history"]])
        self.assertEqual("broken", c1["history"][1]["from"])

    def test_flipped_claim_moves_the_sentinel_integrity_math(self):
        """The mechanism R-7 rides on: a manual flip must change what the sweep computes."""
        before = sen.thesis_integrity(_body()["claims"], {"phi": 1.2})
        self.assertEqual(1, before["holds"])                       # only the engine claim holds
        flipped = tl.set_claim_status(_body(), "c1", "holds")
        after = sen.thesis_integrity(flipped["claims"], {"phi": 1.2})
        self.assertEqual(2, after["holds"])

    def test_summary_reads_the_board(self):
        # engine claim c3 carries its STORED 'holds' (the sweep owns the live value)
        s = tl.claim_status_summary(tl.set_claim_status(_body(), "c1", "holds"))
        self.assertEqual((3, 2, 0, 1), (s["total"], s["holds"], s["broken"], s["unknown"]))
        self.assertIn("2 hold", s["line"])
        self.assertIn("1 unknown", s["line"])


class McpToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self._saved = core.MEMORY_PATH
        core.MEMORY_PATH = Path(self.tmp)
        mem = LivingMemory(self.tmp)
        body = _body()
        tl.validate_thesis_or_raise(body)
        self.orig = mem.write("thesis", text=tl.thesis_summary_line(body), ticker="CEG",
                              tags=["thesis"], meta=body, source="test")

    def tearDown(self):
        core.MEMORY_PATH = self._saved
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_flip_supersedes_and_reads_back_the_board(self):
        r = core.thesis_claim_set("CEG", "c1", "holds", note="guide reaffirmed")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.orig["id"], r["superseded"])
        self.assertIn("2 hold", r["board"])                         # c1 flipped + engine c3 stored
        mem = LivingMemory(self.tmp)
        latest = mem.latest_thesis("CEG")
        self.assertNotEqual(self.orig["id"], latest["id"])          # superseded, not edited
        c1 = [c for c in latest["meta"]["claims"] if c["id"] == "c1"][0]
        self.assertEqual("holds", c1["status"])
        self.assertEqual("guide reaffirmed", c1["history"][0]["note"])
        # the pre-event record survives in the file (append-only)
        self.assertIsNotNone(mem.get(self.orig["id"]))

    def test_engine_claim_and_missing_thesis_refuse(self):
        r = core.thesis_claim_set("CEG", "c3", "holds")
        self.assertFalse(r["ok"])
        self.assertIn("ENGINE", r["error"])
        r = core.thesis_claim_set("GROY", "c1", "holds")
        self.assertFalse(r["ok"])
        self.assertIn("no thesis", r["error"])

    def test_sequential_flips_accumulate_on_the_latest_body(self):
        core.thesis_claim_set("CEG", "c1", "holds")
        core.thesis_claim_set("CEG", "c2", "broken", note="pipeline hedged")
        latest = LivingMemory(self.tmp).latest_thesis("CEG")["meta"]
        got = {c["id"]: c["status"] for c in latest["claims"]}
        self.assertEqual({"c1": "holds", "c2": "broken", "c3": "holds"}, got)


class FundamentalsFallbackTests(unittest.TestCase):
    """get_fundamentals must not go dark with the engine: engine-first, direct FMP fallback."""

    def test_engine_down_falls_back_to_direct_profile(self):
        import fmp_client
        saved = fmp_client.FMPClient.profile
        fmp_client.FMPClient.profile = lambda self, s: {"data": {"symbol": s.upper(),
                                                                 "price": 263.56},
                                                        "cached": True, "stale": False}
        try:
            r = core.get_fundamentals("ceg")
        finally:
            fmp_client.FMPClient.profile = saved
        self.assertEqual("direct", r.get("via"))                    # engine is down in tests
        self.assertFalse(r["engine_running"])
        self.assertEqual(263.56, r["data"]["price"])

    def test_direct_fallback_failure_still_reports_engine_down(self):
        import fmp_client
        saved = fmp_client.FMPClient.__init__

        def boom(self, *a, **kw):
            raise RuntimeError("no client")
        fmp_client.FMPClient.__init__ = boom
        try:
            r = core.get_fundamentals("CEG")
        finally:
            fmp_client.FMPClient.__init__ = saved
        self.assertFalse(r["engine_running"])
        self.assertIn("direct_fallback_error", r)

    def test_empty_ticker_still_refuses(self):
        self.assertEqual({"error": "ticker required"}, core.get_fundamentals(""))


if __name__ == "__main__":
    unittest.main()
