"""Deny-list parity: no isolated subagent may hold a direct-mutation MCP tool.

2026-07-08 reassessment (TF1 finding #2, TF4 finding #3): the endpoint confirm-guard never fires
on the MCP path (`confirm_param_change` POSTs no ``source``, which defaults to ``cockpit``), so the
agent-manifest deny-list is the LOAD-BEARING closure — and `set_nav` (a rating-moving write with no
proposal/confirm gate) was in no deny-list at all. This test makes the closure mechanical:

1. every subagent manifest denies every direct-mutation tool (the cage holds per-agent);
2. every denied name really is a registered pass-through (a rename can't silently orphan a deny);
3. any FUTURE mutating-named tool added to the registration loop must be denied here or explicitly
   listed as proposal-gated — the one-line-append-with-no-gate drift the registration loop invites.

The main session (the operator's proxy) and the cockpit keep these tools — the line is the
subagent boundary, per the 2026-07-02 execution's preserved-dissent note.
"""
import glob
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Direct-mutation tools: apply a config/book/NAV write with no human confirm step of their own.
DIRECT_MUTATION = {
    "set_param",
    "confirm_param_change",
    "remove_holding",
    "promote_to_eval",
    "demote_from_eval",
    "set_nav",
    # repo mutation from an isolated seat is equally out of bounds
    "edit_file",
    "git_commit",
}

# Mutating-NAMED tools that are legitimately agent-callable because they only FILE A PROPOSAL
# (the human applies via /confirm). Adding a name here is a deliberate, reviewed decision.
PROPOSAL_GATED = {
    "propose_param_change",   # -> /config/propose
    "set_barbell_weights",    # files a proposal (core.py)
    "cut_holding",            # files a proposal (core.py)
    "set_param",              # MCP-side set_param force-routes to the proposal queue, but it is
                              # ALSO in DIRECT_MUTATION: denied to subagents for defense-in-depth.
}

# Verbs that make a pass-through tool name "mutating-shaped" for the drift guard.
MUTATING_PREFIXES = ("set_", "confirm_", "remove_", "promote_", "demote_", "cut_", "edit_")


def _manifests():
    files = sorted(glob.glob(os.path.join(REPO, ".claude", "agents", "*.md")))
    assert files, "no agent manifests found"
    return files


def _denied(path):
    text = open(path, encoding="utf-8").read()
    m = re.search(r"^disallowedTools:\s*(.+)$", text, re.M)
    assert m, f"{os.path.basename(path)} has no disallowedTools line"
    return {t.strip() for t in m.group(1).split(",")}


def _passthrough_tools():
    src = open(os.path.join(REPO, "mcp_server", "server.py"), encoding="utf-8").read()
    # match to the closing paren at column 0 — the tuple body contains ')' inside comments
    m = re.search(r"_PASSTHROUGH_TOOLS[^=]*=\s*\((.*?)^\)", src, re.S | re.M)
    assert m, "could not locate _PASSTHROUGH_TOOLS in mcp_server/server.py"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


class TestAgentManifestDenylist(unittest.TestCase):
    def test_every_subagent_denies_every_direct_mutation_tool(self):
        for path in _manifests():
            denied = _denied(path)
            for tool in sorted(DIRECT_MUTATION):
                self.assertIn(
                    f"mcp__commodity-ex__{tool}", denied,
                    f"{os.path.basename(path)} does not deny {tool} — an isolated subagent "
                    f"would hold a direct-mutation tool (the manifest deny-list is the "
                    f"load-bearing closure; the endpoint guard defaults source to 'cockpit')")

    def test_denied_names_are_real_registered_tools(self):
        registered = _passthrough_tools()
        for tool in sorted(DIRECT_MUTATION):
            self.assertIn(
                tool, registered,
                f"{tool} is in the deny policy but not in _PASSTHROUGH_TOOLS — a rename has "
                f"orphaned the deny entry; update both together")

    def test_no_undenied_mutating_shaped_passthrough(self):
        """Registration-loop drift guard: a new mutating-named tool must be denied or
        explicitly proposal-gated — never silently agent-callable."""
        registered = _passthrough_tools()
        for tool in sorted(registered):
            if not tool.startswith(MUTATING_PREFIXES):
                continue
            self.assertTrue(
                tool in DIRECT_MUTATION or tool in PROPOSAL_GATED,
                f"pass-through tool {tool!r} is mutating-shaped but neither denied "
                f"(DIRECT_MUTATION) nor documented as proposal-gated (PROPOSAL_GATED) — "
                f"decide which before registering it")


if __name__ == "__main__":
    unittest.main()
