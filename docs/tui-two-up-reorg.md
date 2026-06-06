# CommodityEx TUI — Two-Up Desk reorg (implementation record)

> **Provenance.** Layout-only refactor of `commodityex_tui.py` from the *CommodityEx —
> Textual TUI Reorg (Two-Up Desk) · Agent Spec v2*. The engine, endpoints and business logic are
> untouched; this moved and regrouped Textual widgets and is reconciled against everything already
> shipped (command palette, `ChatInput` history, `#agents_strip`, receipts/undo, memory management,
> inline Council) so nothing regressed.

## The shape, in one breath

Five `TabbedContent` panes (Book · What-If · Regime · Profile · Dossier) collapsed into **one
persistent spine** — the focused conviction card + the inline Council + one shared conversation —
with the old tabs reborn as **inline lenses** (`Collapsible` panels) summoned in context. Macro is
an always-on regime panel; the INTEL rail is a unified **agent column**; the left rail splits into
**Holdings** + an open, agent-fed **Watchlist**.

The load-bearing trick: `action_tab()` is kept as a **compat shim** that opens the matching lens
(or, for `book`/`council`, the spine / inline Council). Every caller — palette results, slash routes,
row clicks, the agent `switch_tab` handler — keeps working untouched.

## Implementation status (this repo)

- ✅ **Phase 0 — Prep.** `self._autonomy = "propose"`, `self._watch_query = ""`; per-surface render
  methods confirmed container-agnostic.
- ✅ **Phase 1 — INTEL rail → Agent Column.** `#signals` → `#agents`: keeps `#agents_strip` +
  `#signalbody` (desk tape), adds `#autonomy` (the dial), `#proposals` (one-click ✓/✗/?) and a
  rehomed `#memory` (Living Memory, affordances intact). The desk tape now frames `agent="operator"`
  op-kind events as **you** (see Phase L's operator hook).
- ✅ **Phase 2 — Always-on regime panel.** `#regime_panel` renders the compact decomposition on every
  `refresh_data`; the heavy detail (UST curve, integrity, full components) stays in the Regime lens.
  Ends the old status-band / regime-tab / signals triplication.
- ✅ **Phase 3 — Tabs → spine + lenses.** `TabbedContent` removed; center is `Vertical #surface`
  (always-on `#regime_panel` + `VerticalScroll #spine` + the docked `ChatInput #cmdbar`). The spine
  holds `#conviction` (the card), `#agent_reply` (inline council + shared conversation) and the four
  `Collapsible` lenses: `#lens_whatif`, `#lens_regime`, `#lens_dossier` (profile + dossier folded),
  `#lens_grid` (the dense `#booktbl`). `action_tab()` shim + `open_lens`/`action_lens`/`_lens_open`/
  `_current_view`; `on_collapsible_toggled` (and `_on_lens_opened`) render a lens body the moment it's
  summoned, by any entry point.
- ✅ **Phase 4 — Holdings / Watchlist split.** `#holdingsbody` = the rated book (click a name to focus
  it on the spine; floor-breach ⚑ + catalyst-countdown ↯ badges); `#watchbody` = an agent-fed bench
  (pipeline finds outside the book) with a `#watchsearch` door that scouts a theme/name headlessly.
- ✅ **Phase 5 — Cleanup.** Retired the `1-5` tab keys; added `w` what-if · `e` council · `d` detail ·
  `g` grid (palette `^K` + `?` help unchanged). Knob-stepping hints moved into the What-If lens.
- ✅ **Phase 6 — Agent Hub.** `AgentHubScreen` (Ctrl-K → "agent hub", or **manage ›** on the agent
  column): **Roster** (`.claude/agents/*.md` → dispatch on the focus) · **Commands** (saved prompt
  templates, `{ticker}` → focus, persisted to `data/cockpit_commands.json`) · **Tasks** (lens over
  in-flight + desk tape) · **Notes** (lens over Living Memory). A lens over existing data, not a
  parallel store.
- ✅ **Phase L — `cockpit.sh` focus layout.** New default `focus`: the dashboard owns a full-screen
  window; Claude / Antigravity / Operator move to a second window (⌥2 / Ctrl-b 2). `--desk` keeps the
  legacy right-stack. Opt-in operator desk-tape hook (`CEX_OPERATOR_TAPE=1` →
  `scripts/cex-operator-hook.sh` + `cex_optape.py`). The `a`/`b`/`x` dispatch keys still reach the
  agent panes across windows.
- ✅ **Scenario A/B pinning (What-If lens).** Pin a scenario result as baseline **A** (`⊹ pin as A/B
  baseline`); subsequent runs show **Δ vs A** (intrinsic + upside), not just vs base — pin a thesis,
  step the knobs to a variant, read the difference. `action_wf_pin` / `action_wf_unpin`,
  `self._wf_pinned`.

## Invariants held

- **Engine untouched** — still a pure consumer of `/state`, `/config/*`, `/decisions`; still POSTs
  `/action/whatif`, `/config/scenario|confirm`, `/ui/state`. No ρ/φ/JSF/MRI math in the UI.
- **No feature dropped** — every tab survives as a lens, the always-on panel, or (Council) the inline
  strip. Palette, ChatInput history, AGENTS strip, receipts/undo, memory management, Inspect, `?` help
  all preserved; only their container changed.
- **Tested headlessly** — `test_commodityex_tui.py` updated to the new structure; new
  `test_reorg_spine_lenses_and_agent_column` and `test_agent_hub` cover the lens shim, always-on
  regime frame, Holdings/Watchlist split, autonomy dial, one-click proposals and the Hub.

## Deferred (not built yet)

Compare/split view (two conviction columns) · a live recurring-action scheduler for the Hub (the
`cockpit_events.py` + `cockpit_triggers.py` substrate exists; the cron firing does not) ·
reduced-motion / CVD-safe polish · first-run coach · the "injected into N asks" memory-usage counter.
