# Handoff: Agent Hub — Mission Control (Forge-layer aligned)

> Instruction document for a Claude Code agent. Implement this in the **CommodityEx cockpit** (the Textual TUI `commodityex_tui.py`), wired to the existing **Forge layer** Python modules. The HTML in this folder is a **design reference** — a clickable prototype showing intended layout and behavior. Do **not** ship the HTML; recreate it in the TUI using the cockpit's existing widgets, color constants, and patterns. The data shown in the prototype is illustrative — bind to the real `/state`, MCP tools, scheduler, and Forge modules instead.

---

## 1. Overview

The **Agent Hub** is a full-screen "mission control" overlay where the operator delegates work to a roster of agents and approves the actions agents propose. It replaces the old single-column agent panel (which crammed roster + commands + in-flight runs into one narrow rail that wrapped mid-word) with three clear columns:

```
┌─ TEAM ───────────┬─ WORK ──────────────────────────┬─ FOCUS ─────────────┐
│  Roster          │  Delegate composer (hero)       │  Inspector          │
│  (agents by      │  ──────────────────────────────  │  (selected agent    │
│   function)      │  Board: Proposals · Working ·   │   or task detail)   │
│                  │  Queued · Scheduled · Done      │                     │
└──────────────────┴──────────────────────────────────┴─────────────────────┘
```

Three ideas drive the redesign:

1. **Delegation is the central act.** You pick *an agent · a verb · a subject · when*, and send. A natural-language line routes itself; structured pickers below let you build it explicitly.
2. **The fleet is uniform Opus 4.8.** Every agent runs the same model, so the per-agent differentiator is its **runtime lane** (`pane` / `headless` / `sweep` / `rules`), not its model.
3. **The autonomy boundary is concrete.** Per the Forge spec, *alerts fire autonomously; trims / exits / swaps surface as **proposals*** the operator approves. Proposals are the top lane of the board — the heart of the "delegate → agents act → you approve" flow.

**Fidelity: high.** Colors, type, spacing, copy, and interactions in the prototype are intended as final. Match them using the cockpit's existing token constants (below).

---

## 2. How this maps to the existing Forge layer

This UI is a **view** over modules that already exist in the codebase. Bind to them — do not reinvent:

| UI element | Backing module / surface |
|---|---|
| **Sentinel** agent + "Watching" panel + 6h sweep | `sentinel.py` (liquidity-runway, financing-window/death-spiral, thesis-integrity, fired rules); scheduler `sentinel` job (6h) |
| **Proposals** lane (trim / exit / swap / recalibrate) | Sentinel alerts + Council swap + calibration bias-proposals. These are *proposed, never auto-applied* (autonomy contract) |
| **swap** verb / SWAP proposal | `council.py` swap (friction-adjusted hurdle + catalyst lock) |
| **calibrate** / **bias-scan** / RECALIBRATE proposal | `calibration.py` cold-start priored scorecard + `base_rates.py`; reports a **credible interval, never a bare %** |
| **claim** / **rule** composer verbs | `thesis_ledger.py` + `trigger_grammar.py` (Ulysses rules validated/parsed **at save**, fail-closed) |
| **catalyst** verb + chrome calendar strip | `catalyst_calendar.py` (window-based, grounded-or-silent) |
| Delegate / Schedule / Cancel actions | MCP Forge tools + scheduler jobs; NL entry points `catalyst:` / `claim:` / `rule:` from M4 |
| Autonomy dial | global autonomy setting; default = **alerts** (autonomous alerts only) |

**Non-negotiable from the spec:** the 60% position ceiling is never touched here; liquidity-runway only ever *tightens*. The runner never exits a position unattended — exits are always proposals.

---

## 3. Layout

Full-screen overlay. Prototype canvas is **1560 × 940** (scales to fit). Grid rows: `54px header / 1fr body / 30px footer`. Body columns: **`304px  /  1fr  /  396px`** with a 1px `--line` divider between columns.

### 3.1 Header (top chrome) — 54px, bg `--ink-850`, bottom border `--line`
Left → right:
- **Brand**: `◆` (amber) · `AGENT HUB` (uppercase, white, `--fs-md` bold, letter-spacing `.14em`) · `mission control` (faint, `--fs-2xs`, uppercase).
- **Fleet badge**: pill reading `FLEET  opus 4.8` — border/bg are amber-tinted (`color-mix(--amber 38%/8%)`), `opus 4.8` in `--amber-bright` bold. States the uniform model **once**.
- 1px separator (`--line`, 22px tall).
- **Catalyst strip**: label `CATALYSTS` then 2–3 windows from `catalyst_calendar`: `<TICKER> <event> <in-Nd>`. Ticker in `--gold` bold, the "in N days" in `--amber`; macro events dimmed.
- Spacer (flex 1).
- **Status pips**: `<n> awaiting you` (amber pip), `<n> working` (green pip + glow), `<n> scheduled` (amber pip). Counts in `--gold` bold.
- Separator.
- **Autonomy dial**: label `Autonomy` + a 3-segment control `manual · propose · alerts` (active segment uses the cockpit's existing dial "on" style) + a one-line note that changes per setting:
  - manual → "you **drive** every run"
  - propose → "agents **propose**, you approve"
  - alerts (default) → "alerts **fire** · trims & exits proposed"
- Separator · `esc close` hint.

### 3.2 Left column — ROSTER (304px, bg `--ink-900`)
- Column header: `Roster` (amber rail-title) · meta `11 agents · opus 4.8`.
- Agents grouped by **function**, each group with a header (`title — note  ·  count`):
  - **The Sentinel** — "the book that watches itself"
  - **Dialectic Council** — "verdict & swaps"
  - **Research Pipeline** — "scout → synthesize → gate"
  - **Calibration & Audit** — "keep the book honest"
- **Agent row** (grid `12px / 1fr / auto`, padding `8px 16px`, left-border 2px transparent → `--amber` when selected, bg `--ink-700` on hover/selected):
  - **status dot** (7px): `watching` = green + glow + slow pulse; `working` = green + glow; `scheduled` = `--warn`; `idle` = hollow ring (`--line-strong`).
  - **name** (`--text-hi` bold `--fs-md`) over **role** (one line `--fs-2xs` `--faint`, clamps to 1 line; 2 lines when selected).
  - **right**: a **runtime-lane chip** (see §5) and a `› delegate` hint that fades in on hover/select.
- Footer: dashed `+ New agent — name it, give it a brief & a runtime lane…` affordance.

### 3.3 Center column — DELEGATE + BOARD (1fr, bg `--ink-1000`)

**Composer (the hero)** — fixed block, padding `14px 18px`, bottom border `--line`, bg `--ink-900`:
- Label row: `Delegate a task` (amber rail-title) · hint `describe it, or build it below · ⏎ to send`.
- **Composer box** (border `1.5px --line-strong`, radius `--r-lg`, bg `--ink-800`; turns amber + amber glow when the NL field has text):
  - **NL line**: `›` (amber) + a full-width input. Placeholder: `e.g. "rule AGA.V if runway<5d then alert"  ·  "swap URC.TO→MAG"  ·  "sentinel sweep"`. `⏎` kbd hint at the right. Enter submits.
  - **Fields row** (separated by `·`): four labeled pickers —
    - **agent** — dropdown grouped by function; each option shows name + runtime chip.
    - **do what** — the verb; options come from the selected agent's `can[]` (falls back to the global verb list).
    - **subject** — free text input (ticker / theme).
    - **when** — `now` (one-shot) / `schedule` (recurring). *Hidden when the verb is `claim` or `rule`* (those file to the Ledger, not the scheduler).
  - **Go cluster** (right): a tiny note (`runs on opus 4.8` / `respects <autonomy>` / `files to Thesis Ledger`) + the primary button, whose label changes with context: **Delegate ⏎** / **Schedule ⏲** / **Arm rule ⏎** / **File claim ⏎**. Disabled until agent + subject are set.
- **Saved commands** row: label `saved commands` + clickable pills that pre-fill the composer:
  `› sentinel sweep` · `› swap {a}→{b}` · `› catalyst {ticker}` · `› rule {ticker} if …` · `› claim {ticker} …` · `› calibrate book`.

**Board** — scrolls below the composer, padding `6px 18px 24px`. Lanes top → bottom; each lane has a glyph + uppercase title + count chip + right-aligned note:

| Lane | Glyph | Accent | Notes |
|---|---|---|---|
| **Proposals** | `⚑` | `--amber` | Only shown when non-empty. "awaiting your approval". |
| **Working** | `⟳` | `--good` | "live now". Empty-state copy if none. |
| **Queued** | `◷` | `--dim` | "next up". |
| **Scheduled** | `⏲` | `--amber` | "recurring". |
| **Done today** | `✓` | `--faint` | flagged items get `--warn` accent. |

**Task card** (grid `3px accent / 1fr body`, border `--line` → `--line-strong` hover → `--amber` selected, radius `--r-md`, bg `--ink-800`):
- Row 1: **agent name** (white bold) · runtime chip · `→` · **subject** (`--gold` bold) · **kind** chip (uppercase micro, bordered) · right meta. Meta is cadence (`⏲ every 6h`) for scheduled, `✓ ok` / `⚑ flagged` for done, else elapsed; a `✕` cancel appears on working cards.
- Row 2: **what** (`--fs-2xs` `--silver`).
- Working cards add a 3px progress bar (`--good` fill) + `stage+1/total · pct%`. Scheduled cards show `next run <when>` in amber.

**Proposal card** (the autonomy boundary — distinct from task cards; amber-tinted border + bg, accent `--amber`, or `--teal` for swap / `--gold` for recalibrate):
- Row 1: **ACTION chip** (uppercase bold — `TRIM`/`SWAP`/`EXIT`/`RECALIBRATE`; trim/exit tinted `--warn`, swap `--teal`) · **subject** (`--gold` bold) · **agent name** · runtime chip · right-aligned `from` (e.g. `6m ago · sweep`).
- Row 2: **what** — the rationale (e.g. `liquidity-runway 4.2d < 5d floor — trim 0.6% of book to fit ADV`).
- Row 3: **Approve ↵** (green) + **Dismiss** (neutral, red on hover). Clicking the card body focuses the proposing agent in the inspector; the buttons stop propagation.

### 3.4 Right column — INSPECTOR (396px, bg `--ink-900`)
Shows the **selected task** if one is selected, else the **selected agent**, else an empty state. Scrolls; a sticky footer holds the primary actions.

**Agent inspector**:
- Head: agent **name** (`--fs-xl` white bold) · mode line: runtime chip + `opus 4.8 · <lane sub>` · **role** paragraph (`--fs-base` `--silver`).
- **Watching** section — *only for the Sentinel*: header `Watching · every 6h sweep`, then one row per check with a status dot (`ok` green / `warn` orange), the check name (`liquidity-runway`, `financing-window`, `thesis-integrity`, `Ulysses rules`), a note (`AGA.V 4.2d — below floor`), and a right value (`5d ADV cap`, `dilution ≤2% QoQ`, …). Source: `sentinel.py` sweep result.
- **Can do**: header `Can do · click to load the composer`, then the agent's verbs as clickable chips (loads that verb into the composer).
- **Recurring**: the agent's scheduled jobs (subject + what + cadence + next), or an empty hint.
- **Recent alerts** (Sentinel) / **Recent outputs** (others): rows of `dot + text + meta`, dot colored by level (`good`/`warn`/`info`).
- Footer: **Delegate to `<agent>`** (amber) + **Schedule…** (neutral).

**Task inspector**:
- Head: `<agent>` + runtime chip + `→` + `<subject>` (gold) · mode line: kind chip + `<state> · <elapsed>` · **what**.
- **Stages** (working only): a checklist — done `✓` / current `▸…` / todo `·`.
- **Live log**: a small terminal tail (mono 9px, `--ink-1000` bg) with colored spans (`ok` green, `am` amber, `tl` teal, dim gray).
- Footer: working → **Open in pane ↗** + **Cancel run**; otherwise **Close detail**.

### 3.5 Footer — 30px, bg `--ink-850`, top border `--line`
Keyboard legend (`↵ delegate · ⚑ approve proposals · ⏲ schedule · click an agent…`) and a right-aligned status: `● sentinel is watching the book · autonomy: <label>`.

---

## 4. Interactions & behavior

- **Select agent** → focuses it in the inspector **and** loads it into the composer's agent field; the verb resets to the agent's first capability if the current verb isn't in its `can[]`.
- **Select task / proposal card body** → focuses detail (task → task inspector; proposal → its agent).
- **Saved command pill** → pre-fills agent + verb + subject + NL text.
- **Delegate (now)** → creates a `working` task (grounding → working → writing), selects it, toasts `Delegated <verb> to <agent> on <subject> — <lane sub> on opus 4.8, you'll be notified`. Back the run with the real agent invocation / MCP tool.
- **Schedule** → creates a `scheduled` task with a cadence (`sweep` defaults to `every 6h`), toasts that runs respect the current autonomy. Back with a scheduler job.
- **Arm rule / File claim** (verb = `rule` / `claim`) → writes to the **Thesis Ledger** (`thesis_ledger.py`); rule triggers must **parse at save** via `trigger_grammar.py` (reject invalid, fail-closed). Creates a `done` "filed to ledger" entry; toast confirms `validated at save`.
- **Approve proposal** → removes it from the lane and spawns a `working` task representing the execution (trim/swap/exit → staging→routing→confirming; recalibrate → recompute priors→regrade→scorecard). Toast `Approved <ACTION> on <subject> — routed to the runner`.
- **Dismiss proposal** → removes it; toast `Dismissed <action> on <subject> · logged to the Ledger`.
- **Cancel run** (`✕` or footer) → removes the working task; toast `Cancelled run`.
- **Live tick**: working tasks advance their progress/stage on a ~1.5s interval. In production, drive from real run progress instead of a timer.
- **Toast**: bottom-center, auto-dismiss ~4.6s, `--ink-700` surface + `--line-strong` border + pop shadow; values inside in `--gold` bold.

---

## 5. The runtime-lane chip (and why there's no model chip)

Because the whole fleet runs **Opus 4.8**, a per-agent model badge would be noise. State the model once (the header **Fleet** badge) and let each agent's chip carry its **runtime lane**:

| Lane | Meaning | Chip color |
|---|---|---|
| `pane` | interactive (a live Claude pane) | `--teal` |
| `headless` | background red-team / scout | `--silver` (neutral, `--ink-700` bg) |
| `sweep` | scheduled watcher (the Sentinel) | `--good` (+ green glow on the dot) |
| `rules` | deterministic local audit | `--gold` |

Chip = small pill: 5px dot + lowercase label, `--fs-2xs`/9px, `width: max-content`, no shrink. Inspector mode line spells it out: `opus 4.8 · interactive pane`.

> If your real deployment later runs heterogeneous models, reintroduce a model badge *alongside* the lane chip rather than replacing it.

---

## 6. The roster (default seed — bind to real config)

| Agent | Group | Lane | Status | Verbs (`can`) |
|---|---|---|---|---|
| `sentinel` | The Sentinel | sweep | watching | sweep, liquidity, death-spiral, thesis-integrity |
| `arbiter` | Council | pane | idle | council, swap, explain, ask |
| `bull` | Council | pane | idle | thesis, ask |
| `bear` | Council | headless | working | red-team, liquidity, ask |
| `scout` | Research | headless | scheduled | scout, screen, compare |
| `synthesis` | Research | pane | working | synthesize, compare, ask |
| `verifier` | Research | headless | idle | verify, red-team, gate |
| `calibration` | Audit | rules | idle | calibrate, grade, bias-scan |
| `catalyst-verifier` | Audit | headless | idle | catalyst, verify, audit |
| `data-integrity-auditor` | Audit | rules | idle | audit, grade |
| `conviction-analyst` | Audit | pane | working | explain, ask |

The Sentinel carries a `watches[]` array (the four checks with `status`/`note`/value) rendered in its inspector.

---

## 7. Design tokens (exact values — use the cockpit's existing constants)

**Surfaces:** `--ink-1000 #050507` (deepest bg) · `--ink-900 #08080A` (column canvas) · `--ink-850 #0B0B0D` (chrome) · `--ink-800 #0D0D10` (cards) · `--ink-750 #0E0E10` · `--ink-700 #121214` (chips/menus) · `--ink-550 #1C1C22` (hover).
**Lines:** `--line #26262C` · `--line-soft #1B1B21` · `--line-strong #33333B`.
**Metals/accent:** `--amber #D6A24A` (single accent) · `--amber-bright #E6B968` · `--gold #D9C27E` (headline values) · `--silver #B6B6BE` (body).
**Text ramp:** `--text-hi #FFFFFF` · `--text #CBCBD2` · `--dim #74747C` · `--faint #5C5C66`.
**Signals:** `--good #7FC8A0` (mint) · `--bad #D87A7A` (red) · `--warn #CF9A5C` (orange) · `--teal #6FA8A6`.
**Glows:** green `0 0 6px rgba(127,200,160,.5)`, amber `0 0 0 1px rgba(214,162,74,.25)` (match existing cockpit glow tokens).

**Type:** mono-first — `IBM Plex Mono` (fallback JetBrains Mono / ui-monospace). Scale: `9px` micro labels · `10px` uppercase titles · `12px` body · `13px` emphasized · `15px` section value · `20px` inspector name. Weights 400/600/700. Uppercase labels carry letter-spacing `.08em` (`--ls-label`) / rail titles `.14em` (`--ls-wide`). Tabular numerals always on.

**Spacing:** 2 / 4 / 6 / 8 / 10 / 12 / 16 / 20 / 24px. **Radii:** `--r-sm 3px` · `--r-md 4px` · `--r-lg 6px` · `--r-pill 999px`. **Borders:** hairline 1px; cards 1.5px; focus 2px.

> In the Textual TUI these map to the existing `Color`/style constants in `commodityex_tui.py` (the prototype tokens were lifted verbatim from there). Reuse those constants — don't introduce new hexes.

---

## 8. State

```
autonomy        : "manual" | "propose" | "alerts"   (default "alerts")
selectedAgent   : agent id | null                   (default the Sentinel)
selectedTask    : task id | null                    (task focus wins over agent)
proposals[]     : { id, agent, subject, kind, action, what, from }
tasks[]         : { id, agent, subject, kind, what, state, ...stateFields }
                  state ∈ working|queued|scheduled|done
                  working → { stage, stages[], pct, elapsed }
                  scheduled → { cadence, next }
                  done → { result: "ok"|"flagged", elapsed }
composer        : { agent, kind, subject, when:"now"|"schedule", nl }
```

Derive lane counts by filtering `tasks` on `state`. Proposals live in their own array (they are not tasks until approved).

---

## 9. Files in this bundle (design reference)

- `Agent Hub.html` — entry point; sets up the 1560×940 scaling stage and loads the scripts below.
- `hub.css` — all Agent-Hub styles (chips, composer, lanes, cards, proposals, inspector, chrome).
- `cockpit.css` + `ds/styles.css` (+ `ds/tokens/*`) — the shared "desk at night" tokens & helpers the hub builds on.
- `hub-data.js` — the illustrative seed state (roster, runtimes, proposals, tasks, commands, calendar, outputs). **Replace with live data.**
- `hub-parts.jsx` — presentational components: `LaneChip`, `ActionChip`, `AgentRow`, `ProposalCard`, `TaskCard`, `Lane`.
- `hub-app.jsx` — the `HubApp` container: layout, composer logic, delegate/approve/schedule/file handlers, the two inspectors.

Open `Agent Hub.html` to interact with the reference. Implement the behavior in §4 against the real Forge modules in §2 — the prototype's timers and fake state are stand-ins for live runs.
