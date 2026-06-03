# The CommodityEx Cockpit (Tier 0)

One persistent **tmux** session that holds your whole workflow — the engine, a live
terminal dashboard, Claude, and Antigravity — so nothing dies when you close the
window, and one command brings it all back.

```
┌──────────────────────────────┬───────────────────────────┐
│                              │  🤖 CLAUDE  (claude)      │   window 1: "cockpit"
│  📟 commodityex_tui          │     agents on demand      │
│     live Conviction cards    ├───────────────────────────┤
│     from :8000/state         │  🪐 ANTIGRAVITY  (agy)    │
│                              │     analyst / red-team    │
└──────────────────────────────┴───────────────────────────┘
  🛰  ENGINE  (python engine.py → /state)                       window 2: "ops"
  🛠  OPERATOR  (git pull · pip · manual)
```

## One-time setup
```bash
brew install tmux                 # the cockpit runtime
source .venv/bin/activate
pip install textual               # the TUI dashboard pane
```
Wire the **statusline** (live book state in every Claude prompt) into
`~/.claude/settings.json`:
```json
{ "statusLine": { "command": "/Users/joeymason/Macro/statusline.sh" } }
```
→ every prompt shows `⛏ main · opus-4-8 │ RISK-ON · MRI 47 · top AGA.V`.

## Launch
```bash
./cockpit.sh          # build it (first run) or re-attach (every run after)
```
…or double-click **`start-cockpit.command`** in Finder. The engine auto-starts if
it isn't already up, so the dashboard + statusline have `/state` to read.

## Living in it (tmux basics — mouse is on, so you can also just click)
| Do this | Keys |
|---|---|
| Switch cockpit ⇄ ops window | `Ctrl-b` then `1` / `2` |
| Zoom a pane full-screen (and back) | `Ctrl-b` then `z` |
| Move between panes | `Ctrl-b` then arrow, or click |
| Scroll a pane's history | mouse wheel (or `Ctrl-b [`, `q` to exit) |
| **Detach** (leave everything running) | `Ctrl-b` then `d` |
| **Re-attach** later | `./cockpit.sh` |
| Quit the TUI dashboard | `q` |
| Tear the whole cockpit down | `tmux kill-session -t commodityex` |

**The point:** detach (or close the window, or sleep the laptop) and the engine,
dashboard and agent sessions keep running. `./cockpit.sh` drops you back in exactly
where you were — no cold-starting the engine every time.

**iTerm2 users** get native integration automatically (`tmux -CC`): cockpit panes
render as real iTerm tabs/splits. Terminal.app users get plain tmux.

## On the agents
The cockpit is *infrastructure* — it never auto-fires agents. You invoke them in the
Claude pane only when there's a real, specific job:
- `@agent-conviction-analyst` — "why is GMX.TO rated this?"
- `@agent-catalyst-verifier` — "is this catalyst real / correctly attributed?"
- `@agent-data-integrity-auditor` — after a config change, "sweep the book for misIDs."

## What's next (not built yet)
- **Tier 1:** a `SessionStart` hook that greets you with a daily brief; a richer TUI.
- **Tier 2:** hook-chained auto-verification (ingestion → catalyst-verifier) + `/morning`, `/review`, `/audit` skills.
- The statusline/brief get much richer once the Phase 12 MCP tools (`daily_brief`,
  `run_valuation_whatif`) exist — cockpit and tools reinforce each other.
