# The CommodityEx Cockpit (Tier 0)

One persistent **tmux** session that holds your whole workflow — so nothing dies when you
close the window, and **one command** brings it all back. The default **focus** layout gives the
dashboard a **full-screen window** (its in-dashboard **AGENT COLUMN** mirrors the agents, so the
panes no longer need permanent real estate) and puts Claude / Antigravity / Operator on a second
window you flip to with **⌥2** (or `Ctrl-b 2`):

```
window 1 · desk                     window 2 · agents
┌──────────────────────────────┐    ┌──────────────────────┐
│                              │    │  🤖 CLAUDE  (claude) │
│  📟 DASHBOARD (full screen)  │ ⌥2 ├──────────────────────┤
│  commodityex_tui.py          │───►│  🪐 ANTIGRAVITY (agy)│
│  ← the AGENT COLUMN is inside│    ├──────────────────────┤
│                              │    │  🛠 OPERATOR (.venv) │
└──────────────────────────────┘    └──────────────────────┘
```

The **engine runs off-pane as a hidden background daemon** (logs to `data/engine.log`);
it persists across detach/close, and `./cockpit.sh kill` stops it. Prefer the agents always
on-screen? **`./cockpit.sh --desk`** keeps the legacy single-window layout (dashboard ≈76% + a
Claude / Antigravity / Operator stack down the right edge); `--two-window` is the calmer split.

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
| Full-screen dashboard (default) | `./cockpit.sh` (or `--focus`) |
| Legacy right-stack layout | `./cockpit.sh --desk` |
| Calmer 2-window layout | `./cockpit.sh --two-window` |
| Skip the agents | `./cockpit.sh --no-agents` |
| Operator commands → desk tape | `CEX_OPERATOR_TAPE=1 ./cockpit.sh` |
| Point at a different agent CLI | `CEX_CLAUDE_CMD=… CEX_AGY_CMD=… ./cockpit.sh` |

## Living in it (tmux basics — mouse is on, so you can also just click)
| Do this | Keys |
|---|---|
| Flip desk ⇄ agents window | `⌥1` / `⌥2` (or `Ctrl-b` then `1` / `2`) |
| **Ops shell** (git pull · `./cockpit.sh kill` · restart · tests) | `⌥O` — a popup shell over the dashboard, in the repo |
| Copy (shells) | drag-select → macOS clipboard · double/triple-click word/line · iTerm2 = native `⌘C` |
| Paste | `⌘V` (native) · `⌥V` or `Ctrl-b v` (from the macOS clipboard) |
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

**Both agents are panes by default** — Claude as the interactive copilot, Antigravity (Gemini) as
an independent analyst / red-team via its web-auth'd `agy` CLI (no API key). The dashboard's `b`
key also red-teams the focused name headlessly through `agy`. Want just the dashboard + operator?
boot `./cockpit.sh --no-agents`.

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

## The Hub — mission control (press `h`)
The main desk is now just the **book**: holdings + a detailed BOOK HEALTH rail, the conviction card,
inline Council, and the chat. Everything *agentic* lives one key away in the full-screen **Hub**
(`h`, or `v`, or `Ctrl-K → "hub"`) — a multi-card mission control:

- **LEFT — live + controls:** **AGENTS WORKING** (concise, no-noise summaries of in-flight runs +
  the pipeline + flags), the **autonomy dial**, **proposals** (✓/✗), the **roster** (Claude
  subagents **and** Antigravity) with a live **PANES** read (so you can see whether the
  Antigravity/Gemini pane actually launched), **recurring** jobs, saved **commands**, and **ENGINE
  AUDIT**.
- **RIGHT — the review board:** a master-detail reader over **Results · Memory · Research · Threads ·
  Tape**. Live work shows as summaries; the **full in-depth synthesis** is one click away. Read it,
  **⧉ copy** it (the desk owns the mouse, so copy is a one-click action), focus the name, pin/retract
  a memory, discard a draft, or send a result to the chat to act on. `↑↓`/`jk` move · `←→`/`1-5`
  category · `c` copy · `Esc`.

**Recurring agent work** keeps the desk **improving itself**: `job <kind> <topic> [@min]` (e.g.
`job scout silver juniors @1440`) schedules **scout · backtest · verify · brainstorm · build · audit**.
The **autonomy dial** is the boundary: **manual** pauses, **propose** (default) files a one-click
**✓ run / ✕ skip**, **auto** runs headless + posts a receipt.

**ENGINE AUDIT** (fetch · verify · review) turns the agents on the engine *itself* — the numbers that
feed each valuation, the thresholds, and the valuation formulas — and writes a methodology report
(any tunable change is a *proposal*, never auto-applied). Run it from the Hub or schedule `job audit …`.

**Hard safety line:** the runner **never commits, pushes, or edits tracked files**. Every job —
including *build a new agent* — emits a **review draft** under `data/agent_drafts/` plus a
Living-Memory note and a Tape entry. You review and apply. `CEX_JOB_CMD` (→ `CEX_PIPELINE_CMD` →
`claude -p {prompt}`) governs how far the agent reaches. Jobs run while the dashboard is up.

## What's next (not built yet)
- **Tier 1:** a `SessionStart` hook that greets you with a daily brief; a richer TUI.
- **Tier 2:** hook-chained auto-verification (ingestion → catalyst-verifier) + `/morning`, `/review`, `/audit` skills.
- The statusline/brief get much richer once the Phase 12 MCP tools (`daily_brief`,
  `run_valuation_whatif`) exist — cockpit and tools reinforce each other.
