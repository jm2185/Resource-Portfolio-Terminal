# First-Principles Scrutiny — the 5 Forge features (H3 · D1 · H4 · D4 · V5)

A red-team of the calibration flywheel, rotation gate, disconfirm-by-default, base-rate anchoring,
and the Story Card — assessed from first principles against eight named angles of attack, each
**demonstrated on a runnable case** (see `tests/` + the probe in this doc), not asserted.

**Meta-finding:** the codebase already contains most of the cure (stage-conditional priors in
`base_rates.py`, `beta_ci`, the φ floor, the posture size-cap). The shortcomings are overwhelmingly
*"the rigorous machinery exists but isn't composed into the new surfaces."* That is a good place to be.

Distinguish two failure types throughout:
- **Measurement gap** — the *learning loop* (`calibration.py`) can't see it, so the book can't learn from it.
- **Design choice** — a deliberate thumb on the scale (e.g. the Bear can't veto the spear); fine, but must be *named and monitored*, not silent.

---

## Index of current state & shortcomings (ordered by severity)

| # | Angle (who) | Feature | What works | Shortcoming | Type | Sev |
|---|---|---|---|---|---|---|
| 1 | **Taleb** — ergodicity / ruin | H3 | `downside_containment`, φ-floor + posture cap manage path risk *upstream* | The scorecard's objective is the **arithmetic ensemble mean**. Demonstrated: +150%, +150%, −90% → **expectancy +0.70R** while the book **ends at 0.625× (−38%)**. No geometric return, no drawdown, no ruin term. The loop can't *learn* it's over-risking the path. | Measurement | **HIGH** → ✅ **FIXED (T1)** |
| 2 | **Duke** — resulting | H3 | The AVOID inversion (a passed name that falls = process win) is genuine process-thinking. The 5% scratch band buffers noise. | For **long** decisions (most of the book) the grade *is* the realized print. `score_outcome` **never reads rho/phi** (captured at freeze, then ignored). Demonstrated: a rho-1.05 bet drifting +6% = **win**; a rho-5.0 bet = at best **scratch**. With small n the loop learns superstition. | Measurement | **MED-HIGH** → ✅ **FIXED (T1)** |
| 3 | **Druckenmiller** — friction realism | D1 | Friction model is the right *shape* (illiquid incumbent → costlier exit); fully config-overridable. | `SLIP_PER_DAY=0.012`, `SWAP_HURDLE=0.35`, `SLIP_MAX=0.20` are **bare constants with no provenance or confidence grade** — the one module that *doesn't* apply `base_rates.py`'s sourcing discipline. The `SLIP_MAX` cap may *understate* true cost for the thinnest tape (error in the dangerous direction — waves swaps through). | Design | **MED** → ✅ **FIXED (T2)** |
| 4 | **Flyvbjerg** — reference class | D4 | Outside-view-first is correct discipline; honest `{}` for the ballast (no invented authority). | `candidate_anchor` returns a **flat, stage-blind** `discovery_to_mine = 0.50` — no stage/commodity/single-asset param, **even though `base_rates.py` already holds the stage gates** (`deposit_to_pea`…`construction_to_production`). And "becoming a mine" ≠ "the asymmetric **trade** paying off" (a junior can fail to mine yet 5× on the discovery pop / a buyout) — arguably the wrong outcome variable. | Measurement | **MED** → ✅ **FIXED (T3)** |
| 5 | **Tetlock** — false precision at low n | H3 | Cold-start is real for `win_probability` (Beta(1,1), intervaled, flagged); `bias_proposals` refuses to fire at n<5. | The **headline** Druckenmiller metrics are bare points even at n=2: demonstrated `slugging = 5.0` off **one win / one loss**, `expectancy = 0.6` with no interval, while `win_probability` *is* intervaled. Half-finished honesty. | Measurement | **MED** → ✅ **FIXED (T2)** |
| 6 | **Janis / Popper** — token dissent | H4 | The Bear produces a falsifiable **invalidation level** (real Popper — a thesis with a defined breakpoint). | By Arbiter law the Bear **"never narrative-vetoes the convex spear."** A structurally-defanged dissent is exactly Janis's *false comfort*. Defensible as a convexity choice — **but only if the H3 backstop catches bad spears**, and H3 is itself weakened by #1/#2. The two compound. | Design | **MED** |
| 7 | **Gelman** — prior sensitivity | D4/H3 | `beta_ci` is exact; the *mean* (~0.46–0.50) is robust across concentrations. | `Beta(12,12)` is a **hand-set concentration** (raw data implies ≈Beta(2120,2556)); the pseudo-count `a+b=24` silently decides how fast 4 personal decisions override the prior. CI width swings **0.024 → 0.46** across plausible choices. No sensitivity note or test. | Design | **LOW-MED** → ✅ **FIXED (T3)** |
| 8 | **Goodhart** — bar as target | H3 | **Structurally defused**: legs come from `basket['ladder']` (engine), price is exogenous, side is rule-inferred. The agent is told to "clear this bar" but **can't move the measuring stick.** | The defense is **implicit** — nothing asserts "legs must stay engine-sourced," no test guards it. A future refactor that let an agent supply legs would silently re-open it. | Design | **LOW** |

---

## Plan of action (tiered by leverage)

### Tier 1 — the money-relevant measurement gaps (do first)

1. **Path/ruin layer in the scorecard** *(closes #1 Taleb)* — `calibration.py::scorecard`.
   Add alongside expectancy: **geometric return per decision** `g = exp(mean(ln(1+r))) − 1`, **max
   drawdown** over the decision sequence, and a **ruin flag** (any single floor-break beyond a size-
   adjusted threshold). Surface `g` next to `expectancy_per_decision` in `render_brief` so the agent
   sees *"+0.70R arithmetic but −14.5%/decision geometric — you're over-risking the path."* ~M.

2. **Decision-quality axis, separate from outcome** *(closes #2 Duke, half of #5)* — `score_outcome`.
   Use the **frozen rho/phi** (already captured, currently ignored): grade *bet shape* (was ρ ≥ the
   archetype bar, did φ cover the floor) independently of the realized print, and report a
   **Brier-style calibration** of the engine's implied win-prob vs realized over the sample. The
   headline stays expectancy; this adds a "was the *decision* sound regardless of luck" column. ~M-L.

### Tier 2 — honesty & precision

3. **Interval the headline at low n** *(closes #5 Tetlock)* — `scorecard`.
   Bootstrap (or analytic) CI on expectancy; **suppress `slugging` when wins<3 or losses<2** (show
   "n too thin" instead of `5.0`). ~S.

4. **Source-grade the friction constants** *(closes #3 Druckenmiller)* — `council.py`.
   Give `SLIP_PER_DAY / SWAP_HURDLE / SLIP_MAX / REENTRY_COST` the same provenance+confidence
   treatment `base_rates.py` gives every prior (even if the source is "engineering prior — wide,
   overwrite with fills"). Re-examine `SLIP_MAX=0.20` against real micro-cap round-trip costs; if it
   understates, the gate is too permissive. ~S.

### Tier 3 — reference-class refinement

5. **Stage/commodity-aware candidate anchor** *(closes #4 Flyvbjerg)* — `calibration.py::candidate_anchor`.
   Add an optional `stage`/`commodity` and **compose the stage gates already in `base_rates.py`**
   (chain the conditional probabilities from the candidate's stage forward) instead of the flat
   top-level rate. Add a second reference class for **trade-payoff** (discovery pop / takeout), not
   only mine-conversion. ~M.

6. **Prior-sensitivity note + test** *(closes #7 Gelman)* — `base_rates.py` + `tests/`.
   Document the `Beta(12,12)` concentration as a deliberate "let 4 decisions move it" choice; add a
   test asserting the mean is robust and the CI behaves across pseudo-counts. ~S.

### Tier 4 — process discipline (mostly doc + one calibration cut)

7. **Name & monitor the H4 bear asymmetry** *(closes #6 Janis)* — `docs/` + a calibration cut.
   State plainly that the Bear can't veto the spear *by design*, and wire H3 to track **spear
   false-positives specifically** (the defanged dissent's safety net), so the choice is monitored,
   not silent. ~S.

8. **Assert the Goodhart defense** *(closes #8)* — comment in `decision_from_rating` + a test that
   legs are engine-sourced (never agent-supplied). Cheap insurance against a future refactor. ~S.

---

## Resolution log

### Tier 1 — shipped (the money-relevant gaps)

**#1 Taleb / ergodicity** — `calibration.py::scorecard` now carries a `path` block over the decisions
actually *held* (avoids excluded — they don't compound your book) and a `path_warning`:

| metric | before | after (same +150/+150/−90 case) |
|---|---|---|
| `expectancy_per_decision` | +0.70R (only number) | +0.70R (unchanged headline) |
| `geometric_return_per_decision` | — | **−0.145** |
| `ending_wealth_mult` | — | **0.625×** |
| `max_drawdown` | — | **0.90** |
| `ruin_events` | — | **1** |
| `path_warning` | — | *"PATH RISK: geometric −14.5%/decision while arithmetic expectancy is +0.70R … ergodicity gap"* |

Surfaced into every agent brief via `brief_prior` → `world_state.render_brief` (the ⚠ line). The
φ-floor + posture cap (the real *upstream* defenses, duly credited) now have a *measurement* that can
learn when they're being overrun.

**#2 Duke / resulting** — `score_outcome` now reads the **frozen rho/phi** (previously captured then
ignored) and emits an outcome-independent `decision_quality` ∈ {well_shaped, thin, unknown} plus
`implied_breakeven_p = 1/(1+ρ)`. `scorecard.process` splits expectancy by decision-quality and adds an
aggregate calibration (realized win-rate vs implied breakeven):

| case | before (grade) | after |
|---|---|---|
| rho-3.0 bet that **won** | `win` | `win` · **well_shaped** |
| rho-3.0 bet that **lost** | `loss` | `loss` · **well_shaped** (same bet, graded the same) |
| lucky rho-1.05 bet **+6%** | `win` | `win` · **thin** (luck, not skill) |
| process edge (shaped − thin expectancy) | — | **+1.2R** |

The AVOID-inversion and the 5% scratch band (the existing partial defenses) are retained and built on,
not replaced.

*Tests:* `tests/test_calibration.py::PathRiskTests` (5) + `DecisionQualityTests` (6). Full suite
**478 passed**; the 13 failures + 1 error are the pre-existing environmental set (textual-widget
`#proposals`, ingestion feed-deps, openbb asyncio, v5_engine/yfinance) — none touch the changed files.

### Tier 2 — shipped (honesty)

**#5 Tetlock / false precision** — `scorecard` now carries a `reliability` block: `data_limited`
(n < 5), `slugging_reliable` (needs ≥3 wins **and** ≥2 losses before the win/loss averages mean
anything), and `expectancy_ci90` — a frequentist interval *only once warm* (`None` + a DATA-LIMITED
note below threshold; the legitimate small-n number remains `win_probability`'s Bayesian interval).
`/journal` and `@calibration` inherit it automatically.

**#3 Druckenmiller / friction realism** — `council.py` gains `SWAP_PARAM_PROVENANCE` +
`swap_param_provenance()`: every friction constant now carries a basis + confidence grade (all
**engineering priors**, base_rates.py discipline), and the `slip_max` caveat names the
**permissive-direction error** explicitly (a cap that understates thin-tape cost waves swaps through).
`swap_verdict` returns a `friction_basis` note so each verdict is self-documenting.

*Tests:* `ReliabilityTests` (3) + `FrictionProvenanceTests` (3).

*Deferred (medium-term, per review):* regime-conditioning of friction & reference class (read
MRI/VIX/SSI so the book isn't sticky in the wrong regime) — noted, not yet wired.

### Tier 3 — shipped (reference-class refinement)

**#4 Flyvbjerg / reference class** — `base_rates.py` gains `forward_to_production(stage)`: the
reference class is now **chained from the candidate's actual stage** (the per-gate Betas already
existed; the composition was missing), with a moment-matched product CI. `candidate_anchor` /
`candidate_base_rate` take `stage=` and `commodity=`; they also name the **outcome-variable
correction** — mine-conversion is a conservative *floor on the trade* (which can pay via a takeout
[`ma_premium_20d` ≈ 35%] or a stage re-rate) — and add the precious-metals advancement tilt. Threaded
into `@scout` and `@synthesis`.

| stage | flat rate | stage-conditional P(reach production) |
|---|---|---|
| grassroots/deposit | 0.50 | ~0.09 (5 gates remain) |
| fs | 0.50 | ~0.43 (fs→construction × construction→production) |
| construction | 0.50 | ~0.86 (1 gate remains) |

**#7 Gelman / prior sensitivity** — `base_rates.py` gains `prior_sensitivity(name)` +
`CONCENTRATION_RATIONALE`: the `Beta(12,12)` pseudo-count is now documented as a deliberate
"let personal outcomes move it fast" choice, and the sensitivity table (mean robust, CI width tracks
concentration) is auditable rather than silent.

*Tests:* `StageChainTests` (3) + `PriorSensitivityTests` (2) in `test_base_rates.py`;
`StageAwareAnchorTests` (4) in `test_calibration.py`.

### Tier 4 — pending (see plan above).

---

## Reproduce

- Feature suites: `python -m pytest tests/test_calibration.py tests/test_valuation_actions.py
  tests/test_council_swap.py tests/test_world_state.py -q` → 56 pass.
- The eight-angle probe that produced the demonstrations above is reproducible from the cases in this
  doc (each row's "Demonstrated:" line is a 3-line construction against the public module API).
