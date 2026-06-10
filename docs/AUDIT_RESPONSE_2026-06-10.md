# Valuation-Math Audit — Response Round (2026-06-10)

Closes the five findings from the omniscent valuation-math audit (three parallel adversarial
passes + my own line-level verification of every HIGH-or-above claim). Each fix is tested.

## F1 — MED-HIGH · `archetypes.py:776` · Exploration leg now carries the capital discount
The archetype replica's exploration-upside leg omitted `capital_discount_factor` that the engine's
authoritative path applies (`engine.py:1585`), running the replica's `v_exploration` ~14% rich.
Because the replica feeds the **valuation ledger's frozen legs / `method_spread`** and the
what-if/uncertainty machinery, the ensemble was comparing a method against a slightly-wrong copy
of itself. Added `* cap_disc`. **Test:** `test_archetypes::test_exploration_leg_carries_capital_discount`
(halving capital_discount now halves `v_exploration` — it was invariant before).

## F2 — MED-HIGH · `calibration.py:win_probability` · Personal vs reject Betas split
Rejected-name outcomes were pooled into the *same* Beta as committed decisions. Two reference
classes (gate precision vs capital-allocation skill); the graveyard will always out-number a
4-name book, so rejects would eventually dominate the personal prior (probe: 8-2 personal dragged
to 0.55 by 50 rejects). The headline (`mean`/`ci90`/`n`) is now **personal-only**; rejects ride a
labelled `rejects` block (the gate's calibration), with a caveated `combined` pooled view that is
explicitly **not** the default. `brief_prior` surfaces the reject block as `gate_calibration`.
**Tests:** `test_calibration::AuditFixTests` (F2 ×2), `test_base_rates::test_ledger_rejects_tracked_separately`.

## F3 — MED · `calibration.py` · Breakeven frames named
`implied_breakeven_p = 1/(1+ρ)` is the bull-vs-**floor** breakeven (correct for how the engine
defines ρ — verified, *not* corrupted), but it shared a generic name with
`ladder_expectation.p_bull_breakeven` which is the bull-vs-**bear** frame, and the scorecard
compared the floor-framed breakeven against a ±5%-threshold win rate (a third frame). Renamed to
`implied_breakeven_p_vs_floor` (legacy alias kept); the process-calibration block now carries
`frame: "vs_floor_approx"` and names the approximation. **Tests:** `test_calibration::AuditFixTests` (F3 ×2).

## F4 — MED · `replay.py` · Overshoot grading labelled
`gap_closure` reads backward on an overshoot (a name that rockets *past* intrinsic scores negative
convergence). The math is right but misleads. Added `convergence_type ∈ {toward_intrinsic,
overshooting, reversing, widening}` + an explanatory `note` on the overshoot/reverse regimes, so
the number is never read out of context (the grade asks "did price move toward the estimate", not
"did the trade make money"). **Tests:** `test_replay::ConvergenceTypeTests` (×3).

## F5 — LOW-MED cluster
- **Quantile interpolation** (`uncertainty.py`): linear interpolation between order statistics
  instead of index-rounding — removes the ~0.5% P10/P90 bias the PIT coverage test grades against.
  **Test:** `test_uncertainty::QuantileInterpolationTests`.
- **MAD degenerate guard** (`peer_normalization.py`): at n=4 with 3 identical peers + 1 wild one,
  MAD→0 and the outlier silently escaped (and MeanAD self-masks too). The degenerate branch now
  flags on **relative deviation from the consensus median** (>100% ⇒ outlier), down-weights it,
  and emits `outlier_note` — never silent. **Tests:** `test_peer_normalization::OutlierDegenerateMADTests` (×2).
- **T-pillar weight renormalization** (`asymmetry_rating.py`): a config with `kappa+lambda>1` would
  clamp `base_w` to 0 and silently drop the raw-MRI term. Now renormalizes to a convex blend and
  flags `weight_warning`. **Tests:** `test_asymmetry_rating` (F5 ×2).
- **Doc-only:** named the intentional asymmetric real-yield clamp (`regime_posture.py`), the
  `recompute_blend` 0.25 design-floor (`replay.py`), and the `cross_check` `max(|a|,|b|)`
  conservative denominator.

## Suite
`635 passed` (up from 621), `6 failed` (pre-existing environmental: bs4-absent markup test,
yfinance-dependent EngineLiveFeedFlag ×4, openbb async) — unchanged by this round. No new
regression. The only behavior change to an authoritative on-screen number is F1, which raises the
*supplementary* archetype AGA intrinsic toward the engine's (the engine path was already correct).
