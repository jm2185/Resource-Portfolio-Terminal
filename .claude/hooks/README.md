# Cockpit agent-activity hooks

These wire the **Claude pane → cockpit** half of the agent bus. With them on, everything you do
in the Claude pane streams into the dashboard's **SIGNALS · AGENT STREAM** rail in real time —
no copy-paste, no agent having to call a "log" tool.

## What runs
`.claude/settings.json` registers `cockpit_activity.sh` on three Claude Code events:

| Event | Streams as | Example in the rail |
|---|---|---|
| `UserPromptSubmit` | `prompt` | `› claude  why is AGA.V rated this?` |
| `PostToolUse` | `tool` (MCP only) | `⚙ claude  run_valuation_whatif AGA.V` |
| `Stop` | `response` | `✓ claude  responded` |

`cockpit_activity.sh` reads the event JSON on stdin, `_activity.py` compacts it to a one-line
summary, and it `POST`s to the engine `/agent/activity` (which rides `terminal_state`, so the
dashboard shows it on its normal poll).

## Design choices
- **Signal, not noise:** tool events are filtered to **MCP tools only** (`mcp__…`), so book work
  like `run_valuation_whatif` / `propose_param_change` shows up but `Read`/`Grep`/`Bash` don't.
- **Never blocks the agent:** the POST is backgrounded with a 0.6 s timeout and all errors are
  swallowed — if the engine/cockpit isn't running, the hook is a no-op.
- **The other direction** (cockpit → agent) is the dashboard's `a` / `b` / `x` keys, which
  `tmux send-keys` a grounded prompt into the Claude/Antigravity pane and log the dispatch here.

## Antigravity (Gemini) note
These are *Claude Code* hooks, so Antigravity activity isn't captured ambiently. It still shows in
the stream when you dispatch to it (the `b` bear-case key logs the dispatch), and it can post to
`/agent/activity` itself if you wire an equivalent Gemini hook.

## Disable
Remove the `"hooks"` block from `.claude/settings.json` (or delete this folder). Claude Code also
asks you to approve project hooks the first time you open the repo.
