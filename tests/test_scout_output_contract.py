"""The scout must produce a GROUNDED, slot-gated SHORTLIST, not a conclusions-only hand-wave.

The Gemini (agy) lane is retired (subscription cancelled 2026-07): the discipline that used to
ride in the cockpit's per-seat _GEMINI_OUTPUT_CONTRACT now lives where every Claude seat's
contract lives — the .claude/agents definition. These tests pin:
1. The registry routes EVERY seat to Claude — no agent may silently route to the dead agy CLI
   (scout & catalyst-verifier on sonnet; the antigravity seat is gone, @bear is the foil).
2. Opus stays PINNED to 4.8 at the CLI boundary (Opus 5 shipped; the desk does not float up),
   while sonnet rides the alias (Sonnet 5 — approved).
3. scout.md still carries the grounded-shortlist contract (slot gate · sourced claims ·
   persisted hand-off), so the 2026-07-03 unsourced-hand-wave regression can't return.
4. The '## Shortlist' label stays a condense_reply result-anchor, so the table SURVIVES the
   Quest-Log's narration-strip instead of being cut down to the trailing conclusion.
"""
import os
import unittest

import commodityex_tui as t
from cockpit_widgets import (CLAUDE_MODEL_IDS, HUB_AGENT_META, HUB_AGENT_MODEL,
                             _agent_model, _model_cli_id)
from hub_gist import condense_reply


class AllClaudeRegistry(unittest.TestCase):
    def test_no_seat_routes_to_gemini(self):
        for agent, (prov, model) in HUB_AGENT_MODEL.items():
            self.assertEqual(prov, "claude", f"{agent} still routes to the retired {prov} lane")
            self.assertIn(model, ("opus", "sonnet"), f"{agent} carries a non-tier model {model!r}")

    def test_former_gemini_seats_are_sonnet(self):
        self.assertEqual(_agent_model("scout"), ("claude", "sonnet"))
        self.assertEqual(_agent_model("catalyst-verifier"), ("claude", "sonnet"))

    def test_antigravity_seat_is_gone(self):
        self.assertNotIn("antigravity", HUB_AGENT_MODEL)
        self.assertNotIn("antigravity", HUB_AGENT_META)

    def test_gemini_prompt_machinery_is_gone(self):
        self.assertFalse(hasattr(t.Cockpit, "_gemini_prompt"))
        self.assertFalse(hasattr(t.Cockpit, "_GEMINI_OUTPUT_CONTRACT"))
        self.assertFalse(hasattr(t.Cockpit, "_agy_argv"))

    def test_opus_is_pinned_to_4_8_not_the_floating_alias(self):
        self.assertEqual(CLAUDE_MODEL_IDS["opus"], "claude-opus-4-8")
        self.assertEqual(_model_cli_id("opus"), "claude-opus-4-8")
        self.assertEqual(_model_cli_id("sonnet"), "sonnet")   # rides the alias (Sonnet 5)


class ScoutAgentContract(unittest.TestCase):
    """scout.md is the scout's output contract now that the seat runs as a Claude subagent."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".claude", "agents", "scout.md")
        with open(path, encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_seat_is_sonnet(self):
        self.assertIn("model: sonnet", self.text)

    def test_slot_gate_starts_at_scout_time(self):
        self.assertIn("thesis_slot", self.text)
        self.assertIn("slot-mismatch", self.text)

    def test_grounded_shortlist_is_the_deliverable(self):
        low = self.text.lower()
        self.assertIn("shortlist", low)
        self.assertIn("source", low)                   # every claim carries a source
        self.assertIn("scout_candidate", self.text)    # persisted hand-off, not a hand-wave


class ShortlistSurvivesCondense(unittest.TestCase):
    def test_narration_stripped_but_shortlist_table_kept(self):
        reply = ("I will search for gold royalty companies.\n"
                 "I will screen them for slot fit.\n"
                 "I will check current prices on Google Finance.\n"
                 "I will rank the survivors.\n\n"
                 "## Shortlist\n"
                 "| Ticker | Listing | Price (source) | Mkt cap | Slot-fit | Why |\n"
                 "| SLVR.V | TSX-V | C$1.20 — Google Finance | C$80M | FIT | junior Ag royalty |\n\n"
                 "## Key Decisions\n1. Swap into SLVR.V per row 1.")
        out = condense_reply(reply)
        self.assertIn("## Shortlist", out)                 # anchored here, not on Key Decisions
        self.assertIn("SLVR.V", out)
        self.assertIn("Google Finance", out)               # the sourced row survives
        self.assertNotIn("I will search", out)             # narration stripped

    def test_short_reply_without_narration_is_untouched(self):
        reply = "## Shortlist\n| A.V | TSX-V | n/a | n/a | FIT | test |\n\n## Key Decisions\n1. A.V."
        self.assertEqual(condense_reply(reply), reply)     # nothing to condense


if __name__ == "__main__":
    unittest.main()
