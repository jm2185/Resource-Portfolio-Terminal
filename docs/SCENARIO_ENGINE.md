# Scenario-robustness engine — P3 (`scenario_engine.py`)

The convergence point the whole signal layer feeds. Encodes five macro scenarios, drives their
probability **weights from the live signals**, and scores every holding on **dispersion-penalized
robustness** across the set. Pure, one-directional (a consumer of the P1/P2 monitors — never a
re-computer), fully unit-tested. The scenario set is data-driven (`SCENARIO_KEYS`) so it can grow.

## The five scenarios
| | Scenario | Debasement tilt | Driver signal |
|---|---|---|---|
| **A** | Managed debasement / financial repression | **wins** | macro regime — low/neg real yield + soft DXY |
| **B** | Disorderly fiscal dominance / bear-steepener | crisis-hedge convexity | rates dashboard (P2.1) |
| **C** | AI-productivity muddle-through-WIN | **invalidated** | productivity monitor (P2.2) — breadth × trajectory |
| **D** | Reflation / growth without debasement | premium compresses | copper Cu/Au |
| **E** | **Benign normalization / goldilocks** | premium just **fades** | inverse-stress — positive/normal real yield, no steepener |

**E** is the future the four monetary scenarios structurally omit: real yields normalize positive,
growth steady, no debasement, no crisis — productive equities and cash-yield compound while a
hard-asset book drifts. It was added so the book's coverage hole in the benign world becomes visible
rather than implicit (it also closes the panel's MECE / missing-residual-mass critique).

## Weights — driven FROM the signals
A house base prior `{A .30, B .20, C .18, D .15, E .17}` (debasement-tilted; E the benign residual) is
**tilted by each scenario's live driver** (`raw_s = base_s·(1 + gain·signal_s)`) and normalized to 1. A
firing bear-steepener raises **B**; rising productivity breadth raises **C**; low real yields raise
**A**; a hot Cu/Au raises **D**; a positive/normal real yield raises **E** (the inverse of A, muted by
a crisis steepener). No signal ⇒ that scenario falls back to its prior (graceful when offline).

## Robustness — `E[payoff] − λ·downside_dev`
Each name carries a per-scenario payoff (−1…+1), **slot-derived by default** (overridable via
`portfolio_metadata[t].scenario_payoffs`; a legacy 4-key A–D override still works, missing E → 0):

| Slot | A | B | C | D | E |
|---|---|---|---|---|---|
| silver-spear (AGA.V) | +0.80 | **+1.00** | −0.70 | +0.20 | −0.30 |
| gold-royalty-ballast (GROY) | +0.70 | +0.70 | −0.20 | +0.10 | −0.10 |
| project-generator-holdco (GMX.TO) | +0.40 | +0.10 | −0.10 | +0.50 | +0.05 |
| electrification-royalty (URC.TO) | +0.10 | 0.00 | **+0.60** | **+0.70** | +0.30 |

Robustness is the probability-weighted expected payoff **minus** `λ·(downside semideviation)` (λ = 0.5,
`dispersion_mode="downside"`). **Downside-only** by design: it penalizes a name for its sub-mean (bad)
scenarios but NEVER for its upside leg — squaring the spear's +1.00 B into the penalty was the
Markowitz error in a Druckenmiller book (legacy symmetric stdev is still available via
`dispersion_mode="full"`). It still rewards the all-weather ballast over the convex bet — **robustness
ranks GROY #1** while the spear AGA.V leads on raw single-scenario **upside** — but the gap now reflects
the spear's real DOWNSIDE, not its upside. Set `λ = 0` and the ranking collapses to pure expected value.

> Live debasement+steepener regime: GROY robust 0.250 (#1) · AGA.V E[payoff] 0.492 (#1 upside,
> dispersion 0.585, best B / worst C). Robustness ≠ upside, by design.

## The scenario-C / uranium hole
A standing alarm: when the **C weight is non-trivial** (≥ 0.18) but the **C/D-winning book weight is
thin** (< 0.30 — the electrification-royalty slot is the only real C/D hedge), it fires
`scenario_c_hole`. On the live book (URC 0.15 + GMX 0.10 = 0.25) it **fires** — the book is
structurally under-hedged to the AI-productivity win. This is the gap the plan wanted made explicit;
it feeds the scout/rotation work (P5).

## Book-factor coverage + the ballast SENTINEL (`book_factor.py`)
A read-only lens that turns "is this a portfolio or one bet wearing different tickers?" into measured
fact, from data already cached — never an allocation call:
- **scenario_coverage** aggregates the per-name payoffs × book weights into the book's payoff in EACH
  scenario and the **uncovered weight** (scenarios where the book's payoff is < ~0). On the live book
  in a benign tape it reads ~41% uncovered (**C + E**) — the AI-productivity and benign-normalization
  columns the all-resource book has no answer to.
- **factor_concentration** is the realized single-factor read: the average pairwise correlation across
  the book (from the cached corr matrix; high ⇒ diversified by NAME, concentrated in one factor) plus
  each ballast's ρ to the spear. The **ballast SENTINEL** flags any ballast whose ρ→spear has drifted
  to ~1 — it has quietly stopped being ballast. Surfaced on the regime BOOK line.

## Engine wiring
`engine.py` builds the holdings list from `barbell_weights` + `portfolio_metadata[t].thesis_slot`,
passes the rates / productivity / oil / macro-tape monitor outputs, and attaches
`terminal_state["scenario_engine"]` (weights, rankings, leaders, the hole flag, glossary). Graceful
when the engine is offline (no signals ⇒ prior weights, book still scored).

## Acceptance — status
- ✅ Five-scenario set (A–E) encoded with theses, wins/loses, and drivers; E = the benign/goldilocks future the monetary scenarios omit.
- ✅ Weights driven from the signals (bear-steepener→B, productivity breadth→C, macro→A, copper→D, positive real yield→E); sum to 1; graceful fallback.
- ✅ Every name scored by probability-weighted, **downside-only** robustness; reproduces GROY #1 (spear leads on upside); convexity no longer penalized.
- ✅ Scenario-C / uranium hole flagged; book-factor coverage gauge surfaces the full uncovered weight (C + E); the ballast-correlation SENTINEL flags ρ→spear drift.
- ✅ Payoffs slot-derived + per-name overridable (legacy A–D override migrates, E→0); tunables proposal-gated (`scenario_engine.*` / `book_factor.*`); no `eval()`.

## Deferred (flagged)
- **TUI panel**: the data surface (`terminal_state["scenario_engine"]`) is complete; a dedicated
  scenario panel / probability-bar render is the remaining UI step (TUI can't be exercised without
  `textual` here).
- **Payoff calibration**: the slot payoffs are a reasoned first calibration; the calibration flywheel
  (P-series) can learn them from realized scenario outcomes over time.

## Tests
`tests/test_scenario_engine.py` — weights/drivers, downside-dispersion robustness (GROY #1 /
spear-upside no longer penalized), payoff resolution + 4-key migration, the C-hole, the benign-E
scenario (rises on positive real yield, muted by crisis, book is a headwind there).
`tests/test_book_factor.py` — concentration (single-factor read, ballast-vs-spear flag, symmetric
lookup) + scenario coverage (uncovered weight, book-weighted, eval-excluded). Full suite green.
