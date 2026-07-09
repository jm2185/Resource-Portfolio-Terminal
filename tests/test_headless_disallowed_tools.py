"""Headless spawns carry a MECHANICAL write-block (2026-07-08 reassessment, TF1/TF4 Phase 1.4).

The scheduled-job and pipeline runners launch `claude -p …` with no agent manifest — for two
audits their only write-guard was a prose string in the prompt. `_inject_disallowed_tools` now
appends `--disallowedTools <direct-mutation set>` to every claude-CLI headless argv, with the same
respect rule as `_inject_model_flags`: a custom CEX_*_CMD (agy, true, …) is left alone, and a
template that already sets the flag wins.

Imports commodityex_tui (needs textual/rich) → skips when the TUI stack isn't installed.
"""
import os
import unittest
from unittest import mock

try:
    import commodityex_tui as tui
    _HAS = True
except Exception:
    _HAS = False


@unittest.skipUnless(_HAS, "textual/rich not installed")
class HeadlessDisallowedToolsTest(unittest.TestCase):
    def test_claude_argv_gets_the_block(self):
        argv = tui.Cockpit._inject_disallowed_tools(["claude", "-p", "x"], "claude -p {prompt}")
        self.assertIn("--disallowedTools", argv)
        blocked = argv[argv.index("--disallowedTools") + 1]
        for t in ("set_param", "confirm_param_change", "remove_holding", "promote_to_eval",
                  "demote_from_eval", "set_nav", "edit_file", "git_commit"):
            self.assertIn(f"mcp__commodity-ex__{t}", blocked)

    def test_custom_cli_left_alone(self):
        argv = tui.Cockpit._inject_disallowed_tools(["agy", "-p", "x"], "agy -p {prompt}")
        self.assertNotIn("--disallowedTools", argv)

    def test_operator_template_wins(self):
        tmpl = "claude --disallowedTools Bash -p {prompt}"
        argv = tui.Cockpit._inject_disallowed_tools(
            ["claude", "--disallowedTools", "Bash", "-p", "x"], tmpl)
        self.assertEqual(argv.count("--disallowedTools"), 1)   # not doubled

    def test_job_and_pipeline_argv_carry_it(self):
        app = tui.Cockpit()
        with mock.patch.dict(os.environ, {}, clear=False):
            for var in ("CEX_JOB_CMD", "CEX_PIPELINE_CMD"):
                os.environ.pop(var, None)
            for argv in (app._job_argv("do a thing"), app._pipeline_argv("scout silver")):
                self.assertTrue(os.path.basename(argv[0]).startswith("claude"))
                self.assertIn("--disallowedTools", argv)


if __name__ == "__main__":
    unittest.main()
