"""Tests for the Agent-Hub Quest-Log feed helpers (hub_gist) — the collapse-when-done behaviour and
the result-gist extraction. Pure, so they run without textual/rich."""
import unittest

import json

from hub_gist import (ask_failure_message, ask_timeout_seconds, condense_reply, conv_prune,
                      is_run_expanded, pick_mcap, reduce_stream_json, reply_gist,
                      stream_json_event_text)


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


class CondenseReplyTest(unittest.TestCase):
    def test_strips_leading_narration_to_result_section(self):
        out = condense_reply(_VERBOSE)
        self.assertFalse(out.lower().startswith("i will"))    # the 'I will…' wall is gone
        self.assertNotIn("relaxed discovery screen", out.lower())
        self.assertTrue(out.lstrip().lower().startswith(("summary", "### summary")))
        self.assertIn("Scouted", out)                         # the actionable result is kept whole
        self.assertIn("Augment or Hold GMX.TO", out)          # …including the Key Decisions section

    def test_condense_changes_the_text(self):
        self.assertNotEqual(condense_reply(_VERBOSE), _VERBOSE)

    def test_short_normal_reply_untouched(self):
        s = "GROY looks cheap vs peers on EV/oz; I'd scale in below the floor."
        self.assertEqual(condense_reply(s), s)                # one stray 'I'd' is not a process log

    def test_single_narration_line_not_condensed(self):
        s = "I will check the tape.\nThe call: WAIT — extended into the catalyst."
        self.assertEqual(condense_reply(s), s)                # < min_narration -> left alone

    def test_no_anchor_drops_narration_block(self):
        s = ("I will list files.\nI will read config.\nI will search the web.\nI will run tests.\n\n"
             "EMX.V is the cleanest fit: royalty cash flow, T1 jurisdiction, trades under NAV.")
        out = condense_reply(s)
        self.assertTrue(out.startswith("EMX.V"))
        self.assertNotIn("list files", out)

    def test_all_narration_kept_rather_than_emptied(self):
        s = "I will do A.\nI will do B.\nI will do C.\nI will do D."
        self.assertEqual(condense_reply(s), s)                # nothing after the block -> keep it all

    def test_i_have_completed_counts_as_narration(self):
        s = ("I will scout.\nI will screen.\nI will verify.\nI have completed the scouting run.\n\n"
             "## Recommendation\nLoad EMX.V into the electrification slot.")
        out = condense_reply(s)
        self.assertTrue(out.lower().startswith(("recommendation", "## recommendation")))
        self.assertIn("EMX.V", out)
        self.assertNotIn("I have completed", out)


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


class AskTimeoutSecondsTest(unittest.TestCase):
    def test_generous_default_for_main_chat_asks(self):
        # orchestrator AND named seats both clear minutes — no main-chat ask dies at 300s
        self.assertEqual(ask_timeout_seconds(), 900)
        self.assertEqual(ask_timeout_seconds(None), 900)

    def test_explicit_override_wins(self):
        self.assertEqual(ask_timeout_seconds("1800"), 1800)
        self.assertEqual(ask_timeout_seconds("120"), 120)

    def test_bad_or_empty_override_falls_back_to_default(self):
        self.assertEqual(ask_timeout_seconds("notanumber"), 900)
        self.assertEqual(ask_timeout_seconds(""), 900)             # empty env var ignored
        self.assertEqual(ask_timeout_seconds("0") or 900, 900)     # 0 is falsy -> default


class StreamJsonTest(unittest.TestCase):
    def _lines(self, *events):
        return [json.dumps(e) for e in events]

    def test_event_extracts_assistant_text(self):
        ev = {"type": "assistant", "message": {"content": [{"type": "text", "text": "I will search."},
                                                            {"type": "tool_use", "name": "WebSearch"}]}}
        self.assertEqual(stream_json_event_text(ev), ("I will search.", None))

    def test_event_extracts_result(self):
        self.assertEqual(stream_json_event_text({"type": "result", "result": "EMX.V is the pick."}),
                         ("", "EMX.V is the pick."))

    def test_event_ignores_other_types(self):
        self.assertEqual(stream_json_event_text({"type": "system", "subtype": "init"}), ("", None))
        self.assertEqual(stream_json_event_text("not a dict"), ("", None))

    def test_reduce_returns_result_and_streams_turns(self):
        seen = []
        lines = self._lines(
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "I will research."}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Comparing peers."}]}},
            {"type": "result", "result": "Pick: EMX.V — royalty cash flow, trades under NAV."},
        )
        reply = reduce_stream_json(lines, on_update=lambda txt, n: seen.append((txt, n)))
        self.assertEqual(reply, "Pick: EMX.V — royalty cash flow, trades under NAV.")
        self.assertEqual(seen[0], ("I will research.", 1))            # live tape fired per turn…
        self.assertEqual(seen[-1], ("I will research.\nComparing peers.", 2))  # …accumulating

    def test_reduce_falls_back_to_assistant_text_without_result(self):
        # a run killed before the 'result' event still yields the partial work (timeout-safe)
        lines = self._lines(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Partial finding A."}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Partial finding B."}]}},
        )
        self.assertEqual(reduce_stream_json(lines), "Partial finding A.\nPartial finding B.")

    def test_reduce_non_json_fallback(self):
        # if the CLI isn't actually emitting stream-json, don't lose the output
        self.assertEqual(reduce_stream_json(["just plain text", "more text"]),
                         "just plain text\nmore text")

    def test_reduce_blank_lines_and_empty(self):
        self.assertEqual(reduce_stream_json(["", "  ", "\n"]), "")
        self.assertEqual(reduce_stream_json([]), "")


class PickMcapTest(unittest.TestCase):
    def test_prefers_sourced_shares_times_price(self):
        # the AGA.V case: filed 208.6M × C$0.58 = ~121M, NOT FMP's stale-share 97M
        mc, sh = pick_mcap(208_600_000, 0.58, 97_000_000)
        self.assertAlmostEqual(mc, 120_988_000.0, places=0)
        self.assertEqual(sh, 208_600_000)

    def test_falls_back_to_fmp_without_sourced_shares(self):
        self.assertEqual(pick_mcap(None, 0.58, 97_000_000), (97_000_000.0, None))
        self.assertEqual(pick_mcap(0, 0.58, 97_000_000), (97_000_000.0, None))

    def test_falls_back_to_fmp_without_price(self):
        self.assertEqual(pick_mcap(208_600_000, None, 97_000_000), (97_000_000.0, None))
        self.assertEqual(pick_mcap(208_600_000, 0, 97_000_000), (97_000_000.0, None))

    def test_all_none_when_nothing_available(self):
        self.assertEqual(pick_mcap(None, None, None), (None, None))

    def test_numeric_strings_ok_and_bad_types_safe(self):
        mc, sh = pick_mcap("208600000", "0.58", None)
        self.assertAlmostEqual(mc, 120_988_000.0, places=0)
        self.assertEqual(pick_mcap("x", "y", None), (None, None))


class ConvPruneTest(unittest.TestCase):
    def _conv(self, n_threads, replies=1):
        nodes, seq = {}, 0
        for t in range(n_threads):
            seq += 1
            root = str(seq)
            nodes[root] = {"id": root, "parent": None, "role": "you", "text": f"q{t}", "ts": float(t * 10)}
            p = root
            for r in range(replies):
                seq += 1
                rid = str(seq)
                nodes[rid] = {"id": rid, "parent": p, "role": "agent",
                              "text": f"a{t}.{r}", "ts": float(t * 10 + r + 1)}
                p = rid
        return nodes

    def test_keeps_recent_threads_whole(self):
        nodes = self._conv(5, replies=2)                      # 5 threads × 3 nodes = 15
        pruned = conv_prune(nodes, keep_threads=2)
        roots = [n for n in pruned.values() if n["parent"] is None]
        self.assertEqual(len(roots), 2)                       # only the 2 newest threads
        self.assertEqual(len(pruned), 6)                      # each kept whole (root + 2 replies)
        texts = [n["text"] for n in pruned.values()]
        self.assertIn("q4", texts)                            # newest kept
        self.assertNotIn("q0", texts)                         # oldest dropped

    def test_no_orphans_after_prune(self):
        pruned = conv_prune(self._conv(3, replies=2), keep_threads=1)
        for n in pruned.values():
            self.assertTrue(n["parent"] is None or n["parent"] in pruned)   # every parent present

    def test_small_conv_and_empty(self):
        small = self._conv(1, replies=1)
        self.assertEqual(conv_prune(small, keep_threads=50), small)
        self.assertEqual(conv_prune({}), {})
        self.assertEqual(conv_prune(None), {})


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
