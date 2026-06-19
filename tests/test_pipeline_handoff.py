"""
Run: ``python -m unittest tests.test_pipeline_handoff -v``  (pure + offline — only living_memory.py).

The durable pipeline hand-off (scout → synthesis → verifier) at the SUBSTRATE level. Subagents run
in isolated contexts, so a chain that relies on the conductor copy-pasting each stage's text into the
next prompt breaks the moment a downstream prompt is thin — the reported "first agents aren't passing
results to the next agents" failure. The fix routes the hand-off through Living Memory under a per-run
TAG: each stage persists its output; the next stage recovers it by tag even when its prompt carries
nothing. These tests pin that contract:
  * a stage recovers the prior stage's work from the store with ZERO prompt-threading (the core
    guarantee — no stage starts blind),
  * the run tag isolates concurrent runs (one run's shortlist never leaks into another's),
  * the type filter separates the lanes (scout_candidate vs the synthesis note) under one tag,
  * the MCP comma-split contract makes a single ``tags`` string queryable by each token.
"""
import os
import tempfile
import unittest

import living_memory as lm

RUN = "pl:silver-0619"            # the conductor's run tag for this pipeline run
OTHER = "pl:gold-0620"            # a concurrent, unrelated run


def _mcp_split(tags: str):
    """Mirror mcp_server.core.memory_write: a comma-separated ``tags`` string → token list, so a
    single string the agent passes (``"pl:silver-0619,scout"``) is queryable by each token."""
    return [t.strip() for t in str(tags).split(",") if t.strip()]


@unittest.skipUnless(hasattr(lm, "LivingMemory"), "living_memory present")
class PipelineHandoffSubstrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.m = lm.LivingMemory(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def _scout_writes_shortlist(self):
        """@scout freezes each survivor — the persistence IS the hand-off (no text is threaded)."""
        for tk, slot, stage in [("SSV.V", "silver-spear", "pea"),
                                ("AGS.V", "silver-spear", "pre_pea"),
                                ("DSV.V", "silver-spear", "grassroots")]:
            self.m.write("scout_candidate", ticker=tk, text=f"{tk} convex Ag junior",
                         tags=_mcp_split(f"{RUN},scout"), source="scout",
                         meta={"slot": slot, "stage": stage, "source": "https://sedarplus.ca/x"})
        # a SECOND, concurrent run writes its own candidate under a different tag
        self.m.write("scout_candidate", ticker="GROY", text="gold royalty",
                     tags=_mcp_split(f"{OTHER},scout"), source="scout", meta={"slot": "gold-royalty-ballast"})

    def test_synthesis_recovers_shortlist_with_no_prompt_threading(self):
        # THE core guarantee: scout only PERSISTED (nothing was pasted into synthesis's prompt).
        self._scout_writes_shortlist()
        recovered = self.m.query(type="scout_candidate", tag=RUN)
        tickers = {e["ticker"] for e in recovered}
        self.assertEqual(tickers, {"SSV.V", "AGS.V", "DSV.V"})      # the full shortlist came back
        self.assertNotIn("GROY", tickers)                          # the other run did NOT leak in
        # the meta the next stage needs (slot/stage/source) survived the hand-off
        ssv = next(e for e in recovered if e["ticker"] == "SSV.V")
        self.assertEqual(ssv["meta"]["slot"], "silver-spear")
        self.assertEqual(ssv["meta"]["stage"], "pea")
        self.assertTrue(ssv["meta"]["source"].startswith("http"))

    def test_run_tag_isolates_concurrent_runs(self):
        self._scout_writes_shortlist()
        self.assertEqual({e["ticker"] for e in self.m.query(type="scout_candidate", tag=OTHER)}, {"GROY"})

    def test_verifier_recovers_the_synthesis_ranking_by_tag_and_type(self):
        # @synthesis persists its ranking as a note under the run tag; @verifier recovers it blind.
        self._scout_writes_shortlist()
        self.m.write("note", text="SYNTHESIS RANKING — advancing: SSV.V (8/10, grade), AGS.V (6/10)",
                     tags=_mcp_split(f"{RUN},synthesis"), source="synthesis")
        notes = self.m.query(tag=RUN, type="note")
        self.assertEqual(len(notes), 1)
        self.assertIn("advancing: SSV.V", notes[0]["text"])
        # the type filter keeps the lanes clean: the synthesis note query does NOT return scout entries
        self.assertNotIn("scout_candidate", {n["type"] for n in notes})
        # and the scout lane is still independently recoverable under the same tag
        self.assertEqual(len(self.m.query(type="scout_candidate", tag=RUN)), 3)

    def test_a_thin_prompt_alone_would_start_blind_tag_is_what_saves_it(self):
        # Belt-and-suspenders documentation: with neither threaded text NOR a tag, recovery is empty
        # (a blind stage). The run tag is the difference between a working chain and a broken one.
        self._scout_writes_shortlist()
        self.assertEqual(self.m.query(type="scout_candidate", tag="pl:nonexistent"), [])
        self.assertTrue(self.m.query(type="scout_candidate", tag=RUN))     # with the tag → recovered

    def test_mcp_comma_split_makes_each_token_queryable(self):
        # the contract mcp_server.core.memory_write relies on: one tags string → many queryable tokens
        self.assertEqual(_mcp_split("pl:silver-0619,scout"), ["pl:silver-0619", "scout"])
        self.m.write("scout_candidate", ticker="SSV.V", tags=_mcp_split("pl:silver-0619,scout"))
        self.assertTrue(self.m.query(tag="pl:silver-0619"))    # the run tag matches
        self.assertTrue(self.m.query(tag="scout"))             # the lane tag matches too


if __name__ == "__main__":
    unittest.main(verbosity=2)
