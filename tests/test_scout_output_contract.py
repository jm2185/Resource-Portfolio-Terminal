"""The gemini scout must produce a GROUNDED, slot-gated SHORTLIST, not a conclusions-only hand-wave
(2026-07-03: gemini-flash returned 3 unsourced 'Key Decisions' referencing a report it never wrote,
including a mega-cap that slot-mismatches a junior slot). Two guards:

1. _gemini_prompt injects a per-agent OUTPUT CONTRACT for the scout — a sourced ## Shortlist table
   FIRST, slot-fit as a hard gate, no 'review the report' deferral.
2. That '## Shortlist' label is a condense_reply result-anchor, so the table SURVIVES the Quest-Log's
   narration-strip instead of being cut down to the trailing conclusion.
"""
import unittest

from hub_gist import condense_reply


class GeminiScoutContract(unittest.TestCase):
    def _prompt(self, agent, brief="find gold royalty replacements", subject="GROY"):
        import commodityex_tui as t
        # call the pure prompt builder off the class without a running app
        return t.Cockpit._gemini_prompt.__get__(_Stub())(agent, brief, subject)

    def test_scout_prompt_carries_the_shortlist_contract(self):
        p = self._prompt("scout")
        self.assertIn("## Shortlist", p)
        self.assertIn("Price (source)", p)
        self.assertIn("Slot-fit", p)
        self.assertIn("SLOT-MISMATCH", p)
        self.assertIn("the table IS the report", p)

    def test_non_contract_agent_is_unchanged(self):
        # catalyst-verifier has a different output shape — no shortlist contract forced on it
        p = self._prompt("catalyst-verifier")
        self.assertNotIn("## Shortlist", p)
        self.assertIn("cite sources", p)                   # the grounding nudge still applies


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


class _Stub:
    """Minimal stand-in so _gemini_prompt (which only touches these helpers) runs without a TUI app."""
    _RESEARCH_AGENTS = frozenset({"scout", "synthesis", "verifier"})
    _GEMINI_OUTPUT_CONTRACT = None                          # set from the real class below

    def _agent_role(self, agent):
        return f"the {agent}"

    def _thesis_slot_hint(self, subject):
        return ""


def setUpModule():
    import commodityex_tui as t
    _Stub._GEMINI_OUTPUT_CONTRACT = t.Cockpit._GEMINI_OUTPUT_CONTRACT


if __name__ == "__main__":
    unittest.main()
