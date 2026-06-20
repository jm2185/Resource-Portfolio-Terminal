"""Tests for the Agent-Hub Quest-Log feed helpers (hub_gist) — the collapse-when-done behaviour and
the result-gist extraction. Pure, so they run without textual/rich."""
import unittest

from hub_gist import ask_failure_message, is_run_expanded, reply_gist


# A verbose scout reply like the one that prompted this: a long "I will…" preamble, then the signal.
_VERBOSE = """project-generator-holdco slot.
I will read the output of the relaxed discovery screen to see which candidates pass.
I will search the web for Eagle Plains Resources (EPL.V) to gather its market cap.
I will register Eagle Plains Resources (EPL.V) and Strategic Metals (SMD.V) in the universe.
I have completed the scouting run for the project-generator-holdco slot.

### Summary of Actions Taken:
1. **Scouted and Registered Candidates:** Added **EPL.V** (Eagle Plains) and **SMD.V** to the bench.
2. **Executed Screen:** Ran the discovery screen under strict and relaxed gates.

### Key Decisions Needed from the Desk:
* **Augment or Hold GMX.TO?** EPL.V is a clean micro-cap challenger — allocate to augment the slot?
"""


class ReplyGistTest(unittest.TestCase):
    def test_skips_i_will_narration(self):
        g = reply_gist(_VERBOSE, width=140)
        self.assertFalse(g.lower().startswith("i will"))      # not the preamble
        self.assertNotIn("relaxed discovery screen", g.lower())

    def test_surfaces_a_labelled_conclusion(self):
        # prefers a labelled tail section over the narration; here "Summary…" leads to its content
        g = reply_gist(_VERBOSE, width=140)
        self.assertIn("Scouted", g)                           # the actual finding, not the plan

    def test_header_label_pulls_next_line(self):
        txt = "Verdict:\nSWAP — the challenger clears the slot and the ρ-edge holds."
        g = reply_gist(txt, width=120)
        self.assertIn("Verdict", g)
        self.assertIn("SWAP", g)                              # content from the line after the header

    def test_inline_label_returned_whole(self):
        txt = "I will check the tape.\nThe call: WAIT — extended into the catalyst."
        g = reply_gist(txt)
        self.assertTrue(g.startswith("The call"))
        self.assertIn("WAIT", g)

    def test_plain_short_reply_passthrough(self):
        self.assertEqual(reply_gist("GROY looks cheap vs peers on EV/oz."),
                         "GROY looks cheap vs peers on EV/oz.")

    def test_strips_markdown_chrome(self):
        self.assertEqual(reply_gist("### Top pick\n**AGA.V** — the convex spear."),
                         "Top pick — AGA.V — the convex spear.")

    def test_clips_to_width(self):
        g = reply_gist("Net: " + "x" * 300, width=40)
        self.assertLessEqual(len(g), 41)                      # width + the … ellipsis
        self.assertTrue(g.endswith("…"))

    def test_empty_is_empty(self):
        self.assertEqual(reply_gist(""), "")
        self.assertEqual(reply_gist(None), "")

    def test_all_narration_falls_back_not_crash(self):
        g = reply_gist("I will do X.\nI will do Y.")
        self.assertTrue(g)                                    # returns something rather than blank


class AskFailureMessageTest(unittest.TestCase):
    def test_timeout_with_partial_preserves_work(self):
        m = ask_failure_message("timeout", timeout_s=300, partial="Found EPL.V and SMD.V…")
        self.assertIn("Found EPL.V and SMD.V", m)            # 5 minutes of work isn't discarded
        self.assertIn("300s", m)
        self.assertIn("partial output above", m)

    def test_timeout_without_partial_states_no_output(self):
        m = ask_failure_message("timeout", timeout_s=300)
        self.assertIn("300s", m)
        self.assertIn("No output", m)

    def test_timeout_unknown_duration(self):
        self.assertIn("timed out", ask_failure_message("timeout"))

    def test_cli_missing_points_at_env(self):
        self.assertIn("CEX_ASK_CMD", ask_failure_message("cli_missing"))

    def test_error_includes_exception(self):
        self.assertIn("boom", ask_failure_message("error", exc="boom"))

    def test_every_kind_is_nonempty(self):
        for k in ("timeout", "cli_missing", "error"):
            self.assertTrue(ask_failure_message(k))


class IsRunExpandedTest(unittest.TestCase):
    def test_running_is_expanded_by_default(self):
        self.assertTrue(is_run_expanded({"status": "running", "uid": "run:1"}, set()))

    def test_done_is_collapsed_by_default(self):
        self.assertFalse(is_run_expanded({"status": "done", "uid": "thread:1"}, set()))

    def test_user_toggle_expands_a_done_row(self):
        self.assertTrue(is_run_expanded({"status": "done", "uid": "thread:1"}, {"thread:1"}))

    def test_running_honoured_even_if_not_in_set(self):
        self.assertTrue(is_run_expanded({"status": "running", "uid": "run:9"}, {"other"}))

    def test_none_expanded_set_is_safe(self):
        self.assertFalse(is_run_expanded({"status": "done", "uid": "x"}, None))


if __name__ == "__main__":
    unittest.main()
