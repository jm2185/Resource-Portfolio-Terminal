# The CommodityEx Cockpit (Tier 0)

One persistent **tmux** session that holds your whole workflow — the engine, a live
terminal dashboard, Claude, and Antigravity — so nothing dies when you close the
window, and **one command** brings it all back. The agents live natively as panes;
everything is visible at once on a single "trading desk":

```
┌──────────────────────────┬──────────────────────┐
│                          │  🤖 CLAUDE  (claude) │
│   📟 DASHBOARD           ├──────────────────────┤
│   commodityex_tui.py     │  🪐 ANTIGRAVITY (agy)│
│   (the screen you        ├───────────┬──────────┤
│    live in)              │ 🛰 ENGINE │ 🛠 OPERATOR│
└──────────────────────────┴───────────┴──────────┘
```

Prefer it calmer? `./cockpit.sh --two-window` keeps the dashboard + agents on one
window and tucks the engine/operator onto a second (`Ctrl-b 2`).

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
./cockpit.sh          # build it (first run) or re-attach (every run after) — fast
./cockpit.sh install  # one-time: adds a short `cex` command to your PATH
cex                   # …then just type this from anywhere to boot/re-attach
```
…or double-click **`start-cockpit.command`** in Finder. The engine auto-starts if it
isn't already up, and the dashboard pane **waits for `/state`** before painting, so the
first frame is live (no "engine offline" flash). Re-running while it's up re-attaches
instantly — it never rebuilds a running desk.

| Want to… | Command |
|---|---|
| Boot / re-attach | `./cockpit.sh` (or `cex`) |
| Rebuild fresh | `./cockpit.sh rebuild` |
| Stop everything | `./cockpit.sh kill` |
| Calmer 2-window layout | `./cockpit.sh --two-window` |
| Skip the agents | `./cockpit.sh --no-agents` |
| Point at a different agent CLI | `CEX_CLAUDE_CMD=… CEX_AGY_CMD=… ./cockpit.sh` |

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

**Claude is the one interactive agent; Antigravity (Gemini) runs headless.** Two chat copilots
side by side was redundant, so Antigravity left the layout — it's now a research/red-team backend
called on demand via its web-auth'd `agy` CLI (no API key). Want it back as a live pane? boot
`./cockpit.sh --agy`.

**The agent bus (it feels alive):** the dashboard and the agents talk both ways.
- **Agent → cockpit:** Claude Code hooks (`.claude/hooks/`) stream every prompt / MCP-tool /
  response into the **SIGNALS · AGENT STREAM** rail automatically — you *see* the agents working.
- **Cockpit → agent:** on a focused name, **`a`** sends "why is it rated this?" and **`x`** sends
  `/dossier` straight into the Claude pane; **`b`** runs Antigravity headless for a bear case and
  saves the result to `research/` (streamed onto the bus). The cockpit also POSTs your focused
  ticker to `/ui/state`, so when you type in the Claude pane the agent already knows the name.
- **Headless flag:** `agy -p {prompt}` is the default; override with `CEX_AGY_HEADLESS` if your
  CLI's one-shot flag differs (check `agy --help`).

**Feel-alive layer:** a ~2 Hz heartbeat + a live macro **ticker** along the bottom (every
cross-asset signal, bias-coloured), sparklines on MRI/Ag in the status band, and the agent-stream
glow — the desk always looks awake. Bottom command bar is hidden until you press **`/`** (Esc to
close); the macro ticker lives there the rest of the time.

## What's next (not built yet)
- **Tier 1:** a `SessionStart` hook that greets you with a daily brief; a richer TUI.
- **Tier 2:** hook-chained auto-verification (ingestion → catalyst-verifier) + `/morning`, `/review`, `/audit` skills.
- The statusline/brief get much richer once the Phase 12 MCP tools (`daily_brief`,
  `run_valuation_whatif`) exist — cockpit and tools reinforce each other.
