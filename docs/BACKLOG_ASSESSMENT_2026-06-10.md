# Backlog assessment — June 10, 2026

Disposition of the remaining brainstorm backlog after the handoff fixes + V1 shipped. Each item
judged against the core mission (watch the few baskets closely · engine is truth · grounded-or-
silent · asymmetry over accuracy). **Done** items landed this session; **flagged** items carry a
design objection that should be resolved before anyone builds them.

## Done this session (beyond the handoff)

| Item | What shipped |
|---|---|
| B3 (audit CRITICAL) | Retry/backoff on 429/5xx in `fmp_client._get` and `ingestion_pipeline._http_get*`; uniform staleness envelope (`stale` + `age_s`) on every cache-served FMP response; `market_data.yahoo_quote` now serves an *explicitly flagged* last-good quote on fetch failure instead of nothing, and `snapshot()` provenance says `"fmp (STALE cache)"` when the data came from a budget-exhausted or error fallback. |
| B15 | `cockpit_scheduler.update_jobs()` — flock-guarded read-modify-write for the job store (a lost "ran" mark re-fired jobs). Callers should migrate from bare `load_jobs`+`save_jobs`. |
| V2 | `valuation_actions.ladder_expectation()` — probability-weighted scenario NAV done honestly: supplied `p={bear,base,bull}` → E[V] + edge (labelled as resting on the supplied judgment); **no p → breakeven inversion** ("the price is fair only if P(bull) ≥ x%") — a bar to clear, never an invented forecast. Surfaced on the Story Card (`scenario_ev` + a "must believe" render line). |
| D2 | The slot gate now starts at scout-time: `scout.md` carries the full four-slot taxonomy and requires a `slot:` tag (or `slot-mismatch` / `slot:NONE`) on every candidate; replacement hunts make the incumbent's slot the primary filter. The programmatic gate stays at `/rotate` (`council.slot_gate`). |
| D5 | `@anti-scout` (`.claude/agents/anti-scout.md`) — the disconfirmation hunter: KILL / DEGRADE / CHALLENGER / NOISE per finding, slot-fit challengers feed `/rotate`, CLEAN sweeps are recorded to Memory (an honest empty result is signal). Routed in CLAUDE.md. |

## Flagged — do not build as specced

**V4 — regime-conditioned peer multiples.** The brainstorm asks to drive `peer_ev_oz` off the
regime vector. As specced this **double-counts the regime**: the archetype layer already applies
`regime_multiplier` to each name's `DNA.regime_tilt_leg` — for the explorer that IS the market leg
the peer multiple feeds (`archetypes.py`, `valuation_summary`: `legs[tilt] *= regime_mult`).
Conditioning the input multiple on the same regime vector would tilt the same leg twice, inflating
intrinsic in tailwinds and crushing it in headwinds — systematically overstating asymmetry exactly
when the operator is most tempted to press. If regime-aware comps are still wanted, the clean
seam is to make the regime tilt *operate through* the multiple (replace the leg-level multiplier
for the market leg, not stack on it) — an engine change with a reconciliation test proving the
total regime effect is applied once. Until then, the `peer=±%` what-if knob already lets the
operator price any comp-compression scenario by hand.

## Deferred (right idea, wrong session)

- **D3 pre-screened bench** — auto-forensics + live catalysts at `_add_to_watchlist`: lives inside
  the 6.8k-line TUI monolith; do it together with the TUI split (audit B11/tech-debt item 4) so
  the bench logic lands in a testable module, not deeper into the monolith.
- **H1 live token streaming** — TUI event-loop work; needs a running cockpit to verify. Do with
  the blocking-I/O fix (audit A1.4) since both touch the same `_get`/`_post` plumbing.
- **H2 conditional workflow choreography** — gates/branches in `_run_workflow_bg`; same monolith
  caveat as D3.
- **H5 Conviction Book + Brier** — blocked on a semantic memory-recall substrate by its own spec.
  The calibration loop's `implied_breakeven_p` + `win_probability` already cover the thin edge of
  this (and V2's breakeven inversion now gives the per-name "claimed odds" to grade later).
- **V3 real-options π_opt** — a Black-Scholes-on-rock model is a large engine change to a number
  that already exists as a reasoned premium; needs the operator's sign-off on the model form
  (vol input, expiry = funding horizon?) before code. Propose via `/confirm`-style review first.

## Still open from the audit (next highest-leverage)

1. **A1.4** TUI blocking I/O → workers (pairs with H1).
2. **A2.1** dashboard.py re-derived math deletion.
3. **A1.9** engine state-lock / snapshot-swap + supervised background workers.
4. **B13** kill the hardcoded book (weights dict `engine.py` PortfolioSizer; tickers across TUI/
   ingestion) — single source: `portfolio_metadata`.
5. **B14** tooltip coverage from one glossary.
6. **B16** `FORGE_BUILD_SPEC.md` is still not in the repo — the north star should be in-tree.
