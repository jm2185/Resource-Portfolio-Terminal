> **Provenance.** UX assessment + enhancement backlog exported from Claude Design
> (`commodityex-cockpit-design-system`, `guidelines/cockpit-ux-assessment.md`),
> produced after reviewing the live `commodityex_tui.py`.
>
> **Implementation status (this repo).** Tracked here so the backlog is durable.
>
> - ✅ **Kill the flashing around the focused company card.** The 2 Hz `.live`
>   pulse on the conviction card was removed; the focused card now carries a
>   calm, *static* amber left-rule. (`_pulse` only animates the macro ticker.)
> - ✅ **Merge the Council into the Book page (no separate tab) with a shared
>   chat.** The Council tab is gone; the Dialectic reconciliation renders inline
>   atop the Book conversation — collapsed to a compact verdict strip, expanding
>   (`full debate ⌄`) to the full Bull / Bear / Arbiter debate. Its action
>   buttons (Re-run with memory · Save as prior · Pull outcomes) and "convene the
>   council" all post into the ONE shared conversation. Tabs are now
>   Book · What-If · Regime · Profile · Dossier (keys 1–5). *(Later collapsed into
>   a single reasoning spine + inline lenses — see the two-up reorg below.)*
> - ✅ **Tier 1 — Flow & muscle memory (discoverability).**
>   - **Command palette** — a `PaletteScreen` modal: fuzzy-search names · council ·
>     what-if · dossiers · scenarios · tabs · help; ↑/↓ select, ↵ run, recap line.
>     Reachable via **Ctrl-K from anywhere** (a `priority` binding — works even
>     while the chat input is focused) or `:` from a tab/grid. Plain text with no
>     match falls through to the desk agents.
>   - **Ask-history recall** — `↑/↓` in the chat bar cycles your prior asks
>     (`ChatInput` + `_ask_history`), Bloomberg-History style.
>   - **`?` help / keymap overlay** — a pop-over cheat-sheet of every binding +
>     the click grammar (`action_help`).
> - ✅ **Tier 2 (part) — agent oversight: AGENTS control strip + action receipts/undo.**
>   - **AGENTS control strip** — an always-visible readout atop the signals rail
>     (`#agents_strip`): in-flight agent runs (the interactive ask + the running
>     pipeline) with the bound name, **live elapsed**, and a **✗ cancel** that
>     truly terminates the child process (the ask now runs via `Popen`, and a
>     cancelled run's reply is dropped). "idle" when nothing is running.
>   - **Action receipts + undo** — state-changing actions emit a receipt of *what
>     changed* (`_receipt`): note saved · scenario saved · proposal applied /
>     rejected · dossier written. Reversible ones carry **↶ undo** — a note is
>     undone by an immutable Living-Memory `supersede` (hidden from the live
>     thread, audit trail kept); a written dossier is undone by deleting the file.
>     Engine-applied changes (confirm/scenario) show a receipt without a false
>     undo.
> - ✅ **Tier 2 (part) — memory management with provenance.** Living Memory is now
>   *manageable*, within the append-only model: each entry shows **provenance**
>   (`by <source> · <age>` + confidence) and carries **pin · edit · ✕** affordances.
>   Pinned entries float to the top (📌) and are exempt from decay; **edit**
>   supersedes in place (immutable); **✕ retract** tombstones an entry out of the
>   live stream (trail kept); and stale entries (> 14d) **decay** to
>   `stale · <age> — ↻ re-confirm`, which freshens them. (`living_memory`:
>   `get/pinned_ids/pin/unpin/retract/reaffirm`.) This closes the assessment's
>   three "if you do only three things" (palette · oversight · memory).
> - ✅ **Two-up reorg (five tabs → a reasoning spine + inline lenses).** The
>   `TabbedContent` is gone: the center is a spine (conviction card + inline
>   council + shared conversation) with `Collapsible` lenses (What-If · Regime
>   detail · Name detail · Book grid); `action_tab()` is kept as a compat shim that
>   summons the matching lens, so every caller still works. Macro is always-on
>   (`#regime_panel`); the left rail splits into **Holdings** + an open, agent-fed
>   **Watchlist** (search → scout); the INTEL rail becomes a unified **AGENT
>   COLUMN**. Spec + phase status: `docs/tui-two-up-reorg.md`.
> - ✅ **Autonomy dial.** `manual · propose · auto (≤ posture cap)` in the agent
>   column — the visible agent-trust boundary; proposals gained one-click
>   **✓ approve / ✗ reject / ? why**.
> - ✅ **Agent Hub (Phase 6).** A summonable mission-control modal (Ctrl-K →
>   "agent hub", or **manage ›**): Roster · Commands · Tasks · Notes — a lens over
>   existing data (`.claude/agents`, desk tape, Living Memory) + a small persisted
>   command store (`data/cockpit_commands.json`).
> - ✅ **Watch-rail catalyst countdowns + floor-breach flag**, plus the
>   `cockpit.sh` **focus layout** (full-screen dashboard; agents on window 2) and
>   the opt-in **operator desk-tape hook** (`CEX_OPERATOR_TAPE=1`).
> - ✅ **Scenario A/B pinning (What-If lens).** Pin a scenario as baseline A
>   (`⊹ pin as A/B baseline`); later runs show **Δ vs A**, not just vs base.
> - ✅ **Recurring agent work (the scheduler).** `cockpit_scheduler.py` + a
>   dashboard tick fire dial-gated jobs (scout · backtest · verify · brainstorm ·
>   build a new agent). `manual` pauses · `propose` files a one-click ✓ job-run ·
>   `auto` runs headless. Jobs emit a **review draft** (`data/agent_drafts/`) +
>   memory note + tape entry; the runner never commits/pushes. Managed from the
>   Hub's RECURRING panel (`job <kind> <topic> [@min]`).
> - ✅ **Unified Hub (mission control) + side column removed.** The Review room and the Agent Hub
>   merged into one full-screen, multi-card `HubScreen` (press `h`/`v`); the desk's right agent
>   column is gone (cleaner desk, freed space). LEFT cards: AGENTS WORKING (concise, no noise) ·
>   autonomy dial · proposals (✓/✗) · ROSTER (Claude subagents **+ Antigravity**) with a live PANES
>   read · RECURRING · COMMANDS · **ENGINE AUDIT**. RIGHT: the master-detail board over Results ·
>   Memory · Research · Threads · **Tape**, with **⧉ copy** (the dashboard owns the mouse, so copy is
>   an in-app action) + focus/pin/retract/discard/ask. **Engine Audit** (fetch · verify · review) is a
>   new job kind + Hub card that audits the engine's *inputs · thresholds · valuation formulas*.
>   **Book Health** on the desk expanded (rating · forensics · risk · posture · integrity · priorities).
>   `cockpit.sh`: `⌥O` ops-shell popup + `⌥V`/`Ctrl-b v` clipboard paste.
> - ✅ **Agent notes & memory open in full.** Agent-column AGENT NOTES and LIVING
>   MEMORY rows (and the Hub's NOTES) are now click-to-open: a pop-over shows the
>   whole entry + provenance (source · age · regime captured-under) with act-in-place
>   (focus · pin · re-confirm · retract); acting from a pop-over closes it. The DESK
>   TAPE folds routine read-only agent calls (`get_/list_…`) into a tally so the feed
>   shows signal, not every poll. Truncation now ellipsises instead of cutting words.
> - ✅ **The Review room (`v`).** A full-screen master-detail reader unifying the
>   four things you need to see/verify — **Living Memory · job Results · Research /
>   dossiers · Threads** — list on the left, full content + provenance on the right,
>   with act-in-place (focus · pin/re-confirm/retract for memory; discard / "send to
>   chat to act on" for results & research; open / save for threads). ↑↓ / j k move,
>   ←→ or 1-5 switch category, ↵ open, Esc. Reached by `v`, the palette ("review"),
>   or **review ›** on the memory rail. Gives reading + verifying a real home so the
>   chat stops doing triple duty (the chat itself is unchanged for now, by choice).
> - ⏳ **Still deferred.** Compare/split view (PANEL), calm/reduced-motion toggle,
>   CVD-safe palette, first-run coach, the "injected into N asks" memory-usage
>   counter, and a *daemonized* scheduler (runs only while the dashboard is up).

---

# Cockpit UX — Assessment & Enhancement Backlog

A review of the live `commodityex_tui.py` (Textual TUI, ~2,900 lines) against
the design system, Bloomberg Terminal UX philosophy, and current agentic-AI
interface research. **Goal: enhance flow, usability, and UX without uprooting a
single feature.** Everything here is additive or a refinement of what already
ships.

---

## 1 · Verdict — what your agent built is genuinely strong

The implementation is mature and already **on-brand 1:1** — the palette
(`#08080A` screen, `#D6A24A` amber, `#26262C` hairlines), the 3-column desk
(`#watch 30` · `#tabs 1fr` · `#signals 36`), the 2 Hz heartbeat, and the docked
ticker are exactly the design system. More importantly, several patterns are
*ahead* of typical TUIs and squarely match best practice:

| Pattern in your TUI | Why it's good (grounded) |
|---|---|
| **Universal click-to-inspect modal** (`action_explain`, click any metric/tape/value → grounded pop-over) | Bloomberg's core doctrine: *conceal complexity, surface it on demand*. Detail is one click away from everywhere, not crammed on-screen. |
| **Branching conversation tree** bound to a focused ticker, lineage-scoped context, follow-up forks | Treats agent work as *threads of inquiry*, not a flat chat scroll — exactly the "chat-first fails for agents" fix. |
| **Desk Tape "nervous system"** (your ran/edited/git + agent work in one feed) | The agentic-UX "activity log / action timeline" pattern — observable agent behavior builds trust. |
| **Human-gated AGENT PROPOSALS** (`#id key=value … confirm/reject`) | Textbook human-in-the-loop: agents *propose*, you *approve*. Approval as a first-class surface. |
| **Living Memory** with type glyphs + focus-first ordering | The agentic "memory as self-awareness" pattern — the desk remembers and shows its reasoning. |
| **Plain-text-first routing** (no commands needed; `note:` / `/` are opt-in) | Low-barrier intervention: natural language is the primary control surface. |
| **What-If knobs** with debounced live revalue + decompose | Mixed-initiative scenario forging with immediate feedback. |

So this is **not** a rebuild. The opportunities below are about *discoverability,
agent oversight controls, and closing small loops* — making a powerful desk feel
effortless.

---

## 2 · Inspiration distilled

**Bloomberg Terminal (40 yrs of dense-data UX):**
- *Conceal complexity; surface what you need, when you need it.* ✅ you do this.
- **Predictability & a consistent click/affordance grammar** — users must be able
  to *tell what's interactive*. The amber-on-black "this is a key" convention is
  iconic for a reason.
- **The command line + autocomplete menu + History recall + HELP-on-anything** —
  one launch point that is *discoverable*, with a "recap" of the last function.
- **PANEL** — compare multiple views/names at once.

**Agentic-AI interface research (2025–26):**
- **Transparency · Control · Consistency**, plus *"nudge, don't nag."*
- **Long-running controls with clear semantics** — start / stop / pause / resume,
  and *"if you stop now, here's what happens."*
- **Action receipts** — every state-changing action shows *what changed* + a
  **rollback** hook (not just a log entry).
- **Progressive autonomy** — an explicit, adjustable boundary for what agents may
  do unattended; forced pauses in financial contexts are *features, not failures.*
- **Memory management UI** — review / edit / pin / delete + **provenance**
  ("using prior: …") + decay.
- **In-flight intent** — show the current step/why, not just a spinner.

---

## 3 · Enhancement backlog (prioritized)

Impact × effort, ordered for sequencing. **T-shirt effort** in brackets.

### Tier 1 — Flow & muscle memory  *(cheap, high daily payoff)*

1. **Command palette / launcher (`:` or Ctrl-K).** [M]
   A discoverable fuzzy launcher over *names · commands · dossiers · scenarios ·
   tabs* — "council on GMX", "open dossier 3", "what-if AGA". Plain text still
   flows to agents; this is the Bloomberg command-line for *navigation & actions*,
   so the user never wonders "what can I type?". Show a **recap line** of the last
   action and an autocomplete menu as they type.
2. **Command/ask history recall (↑/↓ in the chat bar).** [S]
   Up-arrow re-populates prior asks (Bloomberg History key). Huge for iterating on
   a prompt.
3. **`?` Help / keymap overlay.** [S]
   A modal cheat-sheet of every binding + the click grammar. Discoverability for a
   dense keyboard model. (Bloomberg `HELP`.)
4. **A consistent "clickable" affordance.** [S]
   You have *many* click targets (metrics, tape, tickers, φ/ρ). Give them ONE
   subtle shared style — a dotted amber underline or a leading `›` — so users
   *learn the grammar by sight*. Predictability is the whole game.

### Tier 2 — Agent oversight  *(the agent-centric core)*

5. **Live "AGENTS" control strip.** [M]
   A compact always-visible readout of in-flight work (asks, pipeline stage) with
   **cancel / pause** affordances and elapsed time. Replaces fire-and-forget
   ("reply lands in Book") with *visible, interruptible* runs. Show the current
   **step**, not just `⟳ thinking…`.
6. **Action receipts + Undo.** [M]
   When a proposal is applied, a scenario saved, config edited, or a dossier
   written, emit a receipt: *what changed* + **`↶ undo`**. The Desk Tape is a log;
   receipts add reversibility. Even a single-level "undo last change" is
   transformative for trust.
7. **Autonomy dial (wire to POSTURE).** [M]
   Make the agent gate a *visible, adjustable* level:
   `MANUAL · PROPOSE-ONLY · AUTO-WITHIN-CAP`. It already exists implicitly
   (proposals are human-gated; posture caps size) — surfacing it as one dial gives
   the operator an explicit trust slider. Forced pauses here are a feature.
8. **Memory management.** [M]
   Living Memory is append + read today. Add **pin / edit / delete** and
   **provenance** ("captured by arbiter · 2d" / "using prior: silver leadership"
   when an ask injects it). Let stale entries **decay** or prompt re-confirm. This
   is the one place the agentic literature is most emphatic.

### Tier 3 — Workflow depth

9. **Compare / split view (PANEL).** [L]
   Two conviction cards side-by-side, or a **what-if scenario diffed against base**
   (Δ per pillar). Today everything is single-focus.
10. **Catalyst countdown + floor-breach alerting in the watch rail.** [M]
    You already track catalysts & triggers — surface "next catalyst 7d" and
    **flash a name amber/red when price crosses its floor or invalidation.**
    *Surface what matters when it matters.*
11. **Scenario A/B pinning.** [S]
    "Pin this scenario", step knobs, see Δ vs the pinned set — turns What-If into a
    comparison tool, not just a one-shot.

### Tier 4 — Polish & inclusivity

12. **Global transient toast region** (bottom-right, above ticker). [S]
    `_status()` only speaks in What-If today; make `✓ saved · ⟳ asking · ↻ restored
    frame` consistent across every tab.
13. **Calm / reduced-motion toggle.** [S]
    Pause the heartbeat + ticker crawl for screen-recording or deep focus.
14. **CVD-safe semantics.** [S]
    Bloomberg explicitly flags red/green for color-vision deficiency. Your muted
    mint/red sit close in luminance — you already pair `▲/▼` glyphs; formalize a
    glyph-redundant, CVD-safe alt palette and document it.
15. **First-run coach overlay.** [S]
    A one-time dismissible card teaching the plain-text-first model + click grammar.
    Flattens the TUI learning curve.

---

## 4 · If you do only three things

1. **Command palette + history + `?` help** (Tier 1, 1–3). The single biggest
   *flow* unlock — makes the dense keyboard model discoverable and fast, the way
   Bloomberg's command line does.
2. **AGENTS control strip + action receipts/undo** (Tier 2, 5–6). The single
   biggest *agent-trust* unlock — in-flight visibility, interruptibility, and
   reversibility are what the agentic-UX research says separate "demo" from "daily
   driver."
3. **Memory management with provenance** (Tier 2, 8). The single biggest
   *agentic-depth* unlock, and the area most under-served today.

All three are **additive** — they layer controls and discoverability onto the
existing surfaces. Nothing here removes or restructures a feature; the desk you
have stays intact and gets easier to fly.

> See `enhancements-board.html` for these rendered as on-brand mock components.
