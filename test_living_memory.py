"""
Tests for Living Memory (living_memory.py) — the Forge substrate everything hangs off.

Pure + offline. Pins the non-negotiables: append-only immutability (corrections SUPERSEDE, the prior
survives), typed validation (bad data can't enter the track record), provenance on every entry, and
regime-conditioned recall ("under a similar regime").
"""
import os
import tempfile
import unittest

import living_memory as lm


class WriteAndReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.m = lm.LivingMemory(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_write_stamps_provenance_and_id(self):
        e = self.m.write("note", text="permitting looks optimistic", ticker="aga.v",
                         tags=["permitting", "jurisdiction:CAN"], source="user")
        self.assertTrue(e["id"])
        self.assertTrue(e["ts"].endswith("Z"))
        self.assertEqual(e["type"], "note")
        self.assertEqual(e["ticker"], "aga.v")          # preserved as given (query is case-insensitive)
        self.assertEqual(e["source"], "user")
        self.assertIn("permitting", e["tags"])

    def test_unknown_type_fails_fast(self):
        with self.assertRaises(ValueError):
            self.m.write("vibes", text="nope")

    def test_persists_across_instances(self):
        self.m.write("thesis", text="floor + drill optionality", ticker="AGA.V")
        m2 = lm.LivingMemory(path=self.tmp)            # fresh instance reads the file
        self.assertEqual(len(m2.all()), 1)
        self.assertEqual(m2.latest(ticker="AGA.V")["type"], "thesis")

    def test_cache_is_mtime_invalidated(self):
        self.m.write("note", text="one", ticker="GROY")
        self.assertEqual(len(self.m.all()), 1)
        m2 = lm.LivingMemory(path=self.tmp)
        m2.write("note", text="two", ticker="GROY")    # external append
        self.assertEqual(len(self.m.all()), 2)         # first instance picks it up via mtime

    def test_torn_line_is_tolerated(self):
        self.m.write("note", text="ok", ticker="URC.TO")
        with open(self.tmp, "a", encoding="utf-8") as fh:
            fh.write("{ this is not valid json\n")
        self.assertEqual(len(self.m.all()), 1)         # bad line skipped, no crash


class ImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.m = lm.LivingMemory(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_supersede_keeps_history_and_hides_old_by_default(self):
        old = self.m.write("council_verdict", text="RE-AFFIRM", ticker="AGA.V")
        new = self.m.write  # noqa
        upd = self.m.supersede(old["id"], "council_verdict", text="TRIM", ticker="AGA.V")
        self.assertEqual(upd["meta"]["supersedes"], old["id"])
        self.assertIn(old["id"], upd["refs"])
        # default query hides the superseded original...
        live = self.m.query(ticker="AGA.V", type="council_verdict")
        self.assertEqual([e["id"] for e in live], [upd["id"]])
        # ...but the full record still contains BOTH (append-only audit trail)
        self.assertEqual(len(self.m.all()), 2)
        self.assertEqual(len(self.m.query(ticker="AGA.V", include_superseded=True)), 2)


class ManagementTests(unittest.TestCase):
    """pin / unpin / retract / reaffirm / get — the operator's control over memory."""
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.m = lm.LivingMemory(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_get_by_id(self):
        a = self.m.write("note", text="silver leadership", ticker="AGA.V")
        self.assertEqual(self.m.get(a["id"])["text"], "silver leadership")
        self.assertIsNone(self.m.get("nope"))

    def test_pin_and_unpin(self):
        a = self.m.write("note", text="keep me", ticker="AGA.V")
        self.m.pin(a["id"])
        self.assertEqual(self.m.pinned_ids(), {a["id"]})
        # pins are metadata, not content — they don't pollute the note stream
        self.assertEqual([e["text"] for e in self.m.query(type="note")], ["keep me"])
        self.m.unpin(a["id"])
        self.assertEqual(self.m.pinned_ids(), set())

    def test_retract_hides_via_tombstone(self):
        a = self.m.write("note", text="dilution risk", ticker="AGA.V")
        self.m.retract(a["id"])
        live = [e for e in self.m.query(ticker="AGA.V", type="note")
                if not (e.get("meta") or {}).get("retracted")]
        self.assertEqual(live, [])                       # gone from the live stream
        self.assertEqual(len(self.m.query(ticker="AGA.V", type="note", include_superseded=True)), 2)  # trail kept

    def test_reaffirm_freshens(self):
        a = self.m.write("note", text="thesis intact", ticker="AGA.V",
                         ts="2000-01-01T00:00:00Z")       # ancient → stale
        r = self.m.reaffirm(a["id"])
        self.assertTrue(r["meta"]["reaffirmed"])
        self.assertEqual(r["text"], "thesis intact")      # content carried forward
        self.assertGreater(r["ts"], a["ts"])              # fresh-dated (resets decay)
        self.assertEqual([e["id"] for e in self.m.query(ticker="AGA.V", type="note")], [r["id"]])


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.m = lm.LivingMemory(path=self.tmp)
        self.m.write("note", text="silver leadership strong", ticker="AGA.V",
                     tags=["macro"], regime={"mri": 39.0, "posture": "spear_exploit"})
        self.m.write("decision", text="ACCUMULATE", ticker="AGA.V",
                     regime={"mri": 41.0, "posture": "spear_exploit"})
        self.m.write("outcome", text="held floor", ticker="GROY",
                     regime={"mri": 72.0, "posture": "defensive"})

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_filters_and_together(self):
        self.assertEqual(len(self.m.query(ticker="AGA.V")), 2)
        self.assertEqual(len(self.m.query(type="outcome")), 1)
        self.assertEqual(len(self.m.query(tag="macro")), 1)
        self.assertEqual(len(self.m.query(contains="LEADERSHIP")), 1)   # case-insensitive

    def test_thread_is_oldest_first(self):
        th = self.m.thread("AGA.V")
        self.assertEqual([e["type"] for e in th], ["note", "decision"])

    def test_regime_like_recall(self):
        # a risk-on, low-MRI regime should recall the two AGA spear-exploit entries, not the
        # defensive GROY outcome captured at MRI 72
        hits = self.m.query(regime_like={"mri": 40.0, "posture": "spear_exploit"})
        tickers = {h["ticker"] for h in hits}
        self.assertEqual(tickers, {"AGA.V"})
        self.assertTrue(all("_regime_match" in h for h in hits))

    def test_regime_similarity_monotonic(self):
        near = lm.regime_similarity({"mri": 40, "posture": "x"}, {"mri": 42, "posture": "x"})
        far = lm.regime_similarity({"mri": 40, "posture": "x"}, {"mri": 80, "posture": "y"})
        self.assertGreater(near, far)
        self.assertEqual(lm.regime_similarity({"mri": None}, {"mri": 40}), 0.0)  # never faked

    def test_stats_counts_by_type_and_ticker(self):
        s = self.m.stats()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_type"]["note"], 1)
        self.assertEqual(s["by_ticker"]["AGA.V"], 2)


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.m = lm.LivingMemory(path=self.tmp)
        self.dir = tempfile.mkdtemp()
        self._write("AGA_V_thread_20260604-181828.md", "# AGA.V — drill catalysts\n\nbody")
        self._write("pipeline_silver_20260601-090000.md", "# Pipeline: silver\n\nverdicts")
        self._write("LOST_CHAT_ef233d67.md", "====\n\n[USER]\nrecovered")

    def _write(self, name, body):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp):
            os.remove(self.tmp)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_imports_with_parsed_ticker_ts_and_kind(self):
        import seed_living_memory as seed
        res = seed.import_decisions(self.m, self.dir)
        self.assertEqual(res["imported"], 3)
        aga = self.m.latest(ticker="AGA.V", type="thread")
        self.assertIsNotNone(aga)
        self.assertEqual(aga["ts"], "2026-06-04T18:18:28Z")
        self.assertIn("imported", aga["tags"])
        self.assertEqual(aga["meta"]["kind"], "research_thread")
        # pipeline file -> book-level (no single ticker), tagged pipeline
        pipe = [e for e in self.m.all() if "pipeline" in e.get("tags", [])]
        self.assertEqual(len(pipe), 1)
        self.assertIsNone(pipe[0]["ticker"])

    def test_idempotent_rerun_skips(self):
        import seed_living_memory as seed
        seed.import_decisions(self.m, self.dir)
        res2 = seed.import_decisions(self.m, self.dir)
        self.assertEqual(res2["imported"], 0)
        self.assertEqual(res2["skipped"], 3)

    def test_ticker_and_ts_parsers(self):
        import seed_living_memory as seed
        self.assertEqual(seed._parse_ticker("AGA_V_thread_x.md"), "AGA.V")
        self.assertEqual(seed._parse_ticker("GROY_thread_x.md"), "GROY")
        self.assertIsNone(seed._parse_ticker("pipeline_silver_x.md"))
        self.assertEqual(seed._parse_ts("x_20260604-181828.md"), "2026-06-04T18:18:28Z")
        self.assertIsNone(seed._parse_ts("no_timestamp.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
