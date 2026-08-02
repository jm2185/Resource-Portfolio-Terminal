# The CommodityEx Cockpit (Tier 0)

One persistent **tmux** session that holds your whole workflow — so nothing dies when you
close the window, and **one command** brings it all back. The default **focus** layout gives the
dashboard a **full-screen window** (its in-dashboard **AGENT COLUMN** mirrors the agents, so the
panes no longer need permanent real estate) and puts Claude / Operator on a second
window you flip to with **⌥2** (or `Ctrl-b 2`):

```
window 1 · desk                     window 2 · agents
┌──────────────────────────────┐    ┌──────────────────────┐
│                              │    │  🤖 CLAUDE  (claude) │
│  📟 DASHBOARD (full screen)  │ ⌥2 ├──────────────────────┤
│  commodityex_tui.py          │───►│  🛠 OPERATOR (.venv) │
│  ← the AGENT COLUMN is inside│    │                      │
└──────────────────────────────┘    └──────────────────────┘
```

The **engine runs off-pane as a hidden background daemon** (logs to `data/engine.log`);
it persists across detach/close, and `./cockpit.sh kill` stops it. Prefer the agents always
on-screen? **`./cockpit.sh --desk`** keeps the legacy single-window layout (dashboard ≈76% + a
Claude / Operator stack down the right edge); `--two-window` is the calmer split.

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
| Point at a different agent CLI | `CEX_CLAUDE_CMD=… ./cockpit.sh` |

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

**The Claude pane is on by default** — the interactive copilot. The whole fleet runs on Claude
(the Gemini/agy lane is retired — subscription cancelled): red-teaming is @bear's seat, and the
dashboard's `b` key fires it on the focused name. Want just the dashboard + operator?
boot `./cockpit.sh --no-agents`.

**The agent bus (it feels alive):** the dashboard and the agents talk both ways.
- **Agent → cockpit:** Claude Code hooks (`.claude/hooks/`) stream every prompt / MCP-tool /
  response into the **SIGNALS · AGENT STREAM** rail automatically — you *see* the agents working.
- **Cockpit → agent:** on a focused name, **`a`** sends "why is it rated this?", **`x`** sends
  `/dossier`, and **`b`** fires the @bear red-team — all straight into the Claude pane. The
  cockpit also POSTs your focused ticker to `/ui/state`, so when you type in the Claude pane the
  agent already knows the name.

**Token-cost governance (models & effort).** Every headless `claude -p` spawn now carries
`--model`/`--effort`, so a seat's registry model governs the *whole* session, not just the
subagent: opus seats (council · value · balance-sheet · synthesis · verifier · conviction) run
**Opus 4.8 pinned** (`claude-opus-4-8` — the desk does not ride the alias up to Opus 5); sonnet
seats (scout · calibration · catalyst-verifier · data-integrity · anti-scout · entry-sentinel ·
sentinel) run the `sonnet` alias (currently Sonnet 5) end-to-end. Defaults: asks/stages at
`--effort high` (the CLI's xhigh default is for deep interactive work), **scheduled jobs at
sonnet · medium**, the **Concierge at haiku** (no effort flag — haiku doesn't take one). Knobs:
`CEX_ASK_EFFORT` · `CEX_PIPELINE_EFFORT` · `CEX_JOB_MODEL`/`CEX_JOB_EFFORT` ·
`CEX_CONCIERGE_MODEL`/`CEX_CONCIERGE_EFFORT`. An explicit `--model` in your own
`CEX_*_CMD` template always wins; non-claude commands are never touched.

**Feel-alive layer:** a ~2 Hz heartbeat + a live macro **ticker** along the bottom (every
cross-asset signal, bias-coloured), sparklines on MRI/Ag in the status band, and the agent-stream
glow — the desk always looks awake. Bottom command bar is hidden until you press **`/`** (Esc to
close); the macro ticker lives there the rest of the time.

## The Agent Hub — THE BLEND (press `h`)
Everything *agentic* lives one key away in the full-screen **Agent Hub** (`h`, `v`, or
`Ctrl-K → "hub"`). The hub is **"The Blend"** — one surface, five strengths, no clutter, fully
drivable by mouse (every hotkey mirrors a visible, clickable affordance):

- **Quest Log (center — HOME):** a live feed of past & current research events — working runs,
  proposals (inline ✓/✗), threads, finished dossiers/matchups, and Living-Memory events as one
  stream. Each event type wears a distinct **filled badge** so the feed scans at a glance —
  ❖ DOSSIER · ⇄ MATCHUP · ⚑ FLAG · ✎ NOTE · ⑂ ASK · ⚙ WORKING (a kind-colored left rule ties each
  entry's lines together). Every row is **collapsible depth**: the **▸/▾ caret (or `space`)
  unfolds the full, untruncated event in place** — the whole reply/note wrapped (never clipped) +
  a meta line (agent · model · regime-at-write · tags · elapsed). **Click the row (or `⏎`) and its
  surface opens out of it**: a chain → the Pipeline, a matchup → the bench, an ask → the Thread.
  Filter chips **All · Working · Flagged · Matchups** (`f` cycles).
- **Command-bar completion:** the `/` bar is chat-aware — type **`@s`** and every agent starting
  with *s* pops up with its purpose (`@scout · @sentinel · @synthesis`); a bare first token
  completes the prefixes (`note:` `claim:` `rule:` `scenario:`…) and book tickers. **Tab** takes
  the first; every suggestion is clickable.
- **Subject-at-fire (no sticky target):** there is **one** notion of "the current name" — the desk
  **focus**. The hub has no separate target to set and forget; every launch **confirms the subject
  in its setup, defaulted to focus and editable**, before it runs. A bare ticker in the `/` bar just
  sets focus ("look at this name"). So the hub and the desk can never disagree on what you're working on.
- **Top navigation bar (`1–5`):** QUEST LOG · PIPELINE · MATCHUP · THREAD · ROSTER — explore any
  surface from the top; **tabs set up, they never fire**. The PIPELINE tab opens in **setup** mode
  when nothing is running: pick the chain recipe, **confirm/edit the SUBJECT** (book chips or type
  one — defaults to focus), edit stages (✕ remove · + add from the Roster), then **▶ LAUNCH** is the
  one explicit execution moment.
- **Launch (left rail):** each verb **opens its setup** — the rail shows the focused-name default
  (*on the focused name X*) and every chain (⛓ deep dossier · quick red-team · convene council, plus
  your saved workflows) opens the Pipeline setup to confirm the subject + stages before ▶ LAUNCH.
  The **⇄ matchup bench** (`m`) picks the holding (defaults to focus, changeable) vs 1–4 outsiders;
  **browse the fleet** with `r`.
- **Working lane (right rail):** every in-flight run — AUTO/MANUAL tagged, model on each, live bars,
  click to watch, ✗ to cancel.
- **Focus surfaces:** **Pipeline** (nodes + hand-painted fan-out/fan-in connectors, ◂ ▸ inspect a
  stage, ⏸ pause / + add stage / ⏹ stop — honest stage-boundary controls), **Matchup bench** (one
  holding vs up to 4 outsiders, a column per contender, best-in-row highlighted; the engine only
  rates *book* names, so the run has the agents score every outsider and those numbers fill the
  grid marked **~ (estimate)** while the holding keeps its grounded engine numbers — the verdict
  surfaces right there), **Thread** (one linear
  narrative; a branch is a continuation you *switch to* at the track-switch, `⊞ compare` weighs the
  endpoints side-by-side), and the **Roster** drawer (model + purpose on every card; ▶ run · ⛓ chain).
  Every surface closes by **✕, esc, or a click on the backdrop** — never esc-only.
- **Concierge (docked bottom, every hub screen, `c`):** a plain **read-only** LLM in its own quiet
  lane — explains, recaps, finds. It is *not* an agent: it cannot trade, fire pipelines, or write
  Living Memory, and its Q&A is ephemeral.
- **`/` command bar:** the power path, hidden until summoned — plain-English routing (`@agent …`,
  a bare ticker sets the target, `note:`/`claim:`/`rule:`/`scenario:` keep their prefixes).

The previous-generation hub stays one click away (**⌘ mission control (classic)** in the footer, or
`Ctrl-K → "Mission control (classic)"`) — the reader board, composer and audit cards are unchanged:

- **AGENTS column:** the **roster** as a real menu — each Claude subagent with *what it does*,
  plus **▶ run** it on the focused name now or **⏱ assign** it a recurring task. A live **PANES**
  read shows which CLIs are actually up.
- **WORK column:** **AGENTS WORKING** (concise, no-noise summaries of in-flight runs + the pipeline +
  flags), the **autonomy dial**, **proposals** (✓/✗), **recurring** jobs (each shows *its* agent),
  saved **commands**, **ENGINE AUDIT**, and the add-input.

**Assign an agent to a task:** `⏱` on the roster, or type `job <agent> <topic>` /
`job <kind> <topic> by <agent>` (e.g. `job bear AGA.V dilution`, `job audit thresholds by
data-integrity-auditor`). Every subagent runs via `@name` on the Claude CLI. The autonomy dial
still governs run vs propose vs pause.
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

## The daily brief
Every Claude session opens with a **live daily brief** in context via the `SessionStart` hook
(`.claude/hooks/daily_brief.py`): the shared situational frame (regime + posture, rated book,
running pipeline, recent Living Memory) **plus a TODAY layer** — per-name flags worth your eyes
(BELOW REP floor · binding forensic cap · live catalyst · stale feed). The agent-callable
sibling is the **`daily_brief` MCP tool** (same flag logic, one source of truth), and the
**statusline** surfaces the headline flag — `⚑<n> below-floor`. Grounded-or-silent (engine
offline → one honest line, never invented numbers); the hook always exits 0 so it can never
block a session.

## What's next (not built yet)
The full backlog lives in **Living Memory** (notes tagged `backlog` — ask "what's on the
backlog?" or query from mission control). Headlines:
- **Tier 2:** hook-chained auto-verification (ingestion → catalyst-verifier) + `/morning`, `/review`, `/audit` skills.
- Blend hub: N-way matchup bench · saved Quest-Log views · N-depth pipeline painter · motion polish.
