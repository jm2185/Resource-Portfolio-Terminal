# Scenario-robustness engine — P3 (`scenario_engine.py`)

The convergence point the whole signal layer feeds. Encodes four macro scenarios, drives their
probability **weights from the live signals**, and scores every holding on **dispersion-penalized
robustness** across the set. Pure, one-directional (a consumer of the P1/P2 monitors — never a
re-computer), fully unit-tested.

## The four scenarios
| | Scenario | Debasement tilt | Driver signal |
|---|---|---|---|
| **A** | Managed debasement / financial repression | **wins** | macro regime — low/neg real yield + soft DXY |
| **B** | Disorderly fiscal dominance / bear-steepener | crisis-hedge convexity | rates dashboard (P2.1) |
| **C** | AI-productivity muddle-through-WIN | **invalidated** | productivity monitor (P2.2) — breadth × trajectory |
| **D** | Reflation / growth without debasement | premium compresses | copper Cu/Au |

## Weights — driven FROM the signals
A house base prior `{A .34, B .22, C .20, D .24}` (debasement-tilted central case) is **tilted by each
scenario's live driver** (`raw_s = base_s·(1 + gain·signal_s)`) and normalized to 1. A firing
bear-steepener raises **B**; rising productivity breadth raises **C**; low real yields raise **A**;
a hot Cu/Au raises **D**. No signal ⇒ that scenario falls back to its prior (graceful when offline).

## Robustness — `E[payoff] − λ·dispersion`
Each name carries a per-scenario payoff (−1…+1), **slot-derived by default** (overridable via
`portfolio_metadata[t].scenario_payoffs`):

| Slot | A | B | C | D |
|---|---|---|---|---|
| silver-spear (AGA.V) | +0.80 | **+1.00** | −0.70 | +0.20 |
| gold-royalty-ballast (GROY) | +0.70 | +0.70 | −0.20 | +0.10 |
| project-generator-holdco (GMX.TO) | +0.40 | +0.10 | −0.10 | +0.50 |
| electrification-royalty (URC.TO) | +0.10 | 0.00 | **+0.60** | **+0.70** |

Robustness is the probability-weighted expected payoff **minus** `λ·(weighted stdev across scenarios)`
(λ = 0.5). The dispersion penalty is the whole point: it rewards the all-weather ballast over the
convex bet. **So robustness ranks GROY #1**, while the spear AGA.V still leads on raw single-scenario
**upside** (highest `E[payoff]`, best in B) — both are reported, so the convexity is never buried.
Set `λ = 0` and the ranking collapses back to pure expected value (the spear wins) — verified in tests.

> Live debasement+steepener regime: GROY robust 0.250 (#1) · AGA.V E[payoff] 0.492 (#1 upside,
> dispersion 0.585, best B / worst C). Robustness ≠ upside, by design.

## The scenario-C / uranium hole
A standing alarm: when the **C weight is non-trivial** (≥ 0.18) but the **C/D-winning book weight is
thin** (< 0.30 — the electrification-royalty slot is the only real C/D hedge), it fires
`scenario_c_hole`. On the live book (URC 0.15 + GMX 0.10 = 0.25) it **fires** — the book is
structurally under-hedged to the AI-productivity win. This is the gap the plan wanted made explicit;
it feeds the scout/rotation work (P5).

## Engine wiring
`engine.py` builds the holdings list from `barbell_weights` + `portfolio_metadata[t].thesis_slot`,
passes the rates / productivity / oil / macro-tape monitor outputs, and attaches
`terminal_state["scenario_engine"]` (weights, rankings, leaders, the hole flag, glossary). Graceful
when the engine is offline (no signals ⇒ prior weights, book still scored).

## Acceptance — status
- ✅ Four-scenario set encoded with theses, wins/loses, and drivers.
- ✅ Weights driven from the signals (bear-steepener→B, productivity breadth→C, macro→A, copper→D); sum to 1; graceful fallback.
- ✅ Every name scored by probability-weighted robustness; **reproduces GROY #1** (spear leads on upside).
- ✅ Scenario-C / uranium hole flagged on the live book.
- ✅ Payoffs slot-derived + per-name overridable; tunables proposal-gated (`scenario_engine.*`); no `eval()`.

## Deferred (flagged)
- **TUI panel**: the data surface (`terminal_state["scenario_engine"]`) is complete; a dedicated
  scenario panel / probability-bar render is the remaining UI step (TUI can't be exercised without
  `textual` here).
- **Payoff calibration**: the slot payoffs are a reasoned first calibration; the calibration flywheel
  (P-series) can learn them from realized scenario outcomes over time.

## Tests
`tests/test_scenario_engine.py` (18) — weights/drivers, robustness ranking (GROY #1 / spear-upside),
payoff resolution, the C-hole, structure. 326 green across the affected dependency-free suites.
