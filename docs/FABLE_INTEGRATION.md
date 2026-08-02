# FABLE_INTEGRATION — the living-analyst plan

**Status:** review draft (plan only — no engine code changed by this document).
**Scope:** how frontier-model reasoning (Fable-class, esp. mathematical derivation) integrates into
the terminal as a *continuous* second analyst — one that scrutinizes the engine's values and the
desk's conclusions on its own heartbeat, without ever becoming a number the desk depends on.

---

## 0. The organizing principle — the model doubts, the engine repeats

The engine's job is deterministic, reproducible numbers (ρ/φ/T-Q-V/JSF/regime/valuations). A model
in that path is a bug: irreproducible, drifts run-to-run, ungradeable by `replay.py`. So the
division of labor is fixed from first principles:

| Layer | Does | Never does |
|---|---|---|
| **Engine** | computes, repeats, grades itself against cached closes | reasons about *why* |
| **Model (Fable)** | independently re-derives, attacks, and upgrades what the engine computes; writes durable findings into pure tested code | produce a load-bearing number at runtime |

Corollary — **crystallization**: every expensive model reasoning pass should, where possible, end as
a pure deterministic artifact (an invariant test, a tailored helper, a graded proposal) that the
engine then runs for free forever. Model creativity compounds; per-query cleverness evaporates.

All of this rides existing rails — no new safety surface:

- **Autonomy dial** (`cockpit_scheduler.decide`): auto / propose / manual stays the only boundary
  between "due" and "ran". Default `propose`.
- **Drafts, not commits**: scheduler jobs emit review artifacts to `data/agent_drafts/` + Living
  Memory. Code and param changes route through `/confirm` (`propose_param_change`) or ordinary
  human-reviewed commits. Nothing here loosens that.
- **Grounded-or-silent**: every model finding carries its derivation and sources, or it is not
  written.

---

## Phase F1 — Invariant mining (crystallized skepticism)

*The cheapest, most compounding integration: one reasoning pass → a check that runs forever.*

### What
Fable reads each engine module and **proposes the mathematical properties the outputs must
satisfy** — then ships each as a property test. Candidate classes:

- **Monotonicity**: valuation non-decreasing in the underlying commodity override; REP floor
  non-increasing in AISC; band width non-decreasing in input uncertainty.
- **Ordering**: floor ≤ base ≤ bull on every `engines/valuation.py` output, every archetype, every
  scenario overlay.
- **Bounds**: ρ, φ, correlations, scenario weights, Brier components in-range; `SPEAR_CEILING`
  consumers never above `book_invariants.SPEAR_CEILING` (extends the existing
  `test_spear_ceiling_central.py` pattern).
- **Coherence**: `regime_posture` size caps only tighten as MRI deteriorates; `book_factor`
  uncovered-weight + covered-weight mass ≈ 1; `calibration.score_outcome` sign conventions
  consistent with `infer_side`.
- **Conservation**: `remove_holding` redistribution sums to 1.0; barbell weights re-normalize.

### Design
- `tests/test_mined_invariants_*.py` — plain pytest + `hypothesis` (already the house style per
  `conftest.py`), grouped per module. Each test docstring states the property *as a mathematical
  claim* and cites the deriving draft.
- A `mine-invariants` job kind in `cockpit_scheduler.JOB_KINDS` (cadence ~ weekly, kind `build`
  semantics): the prompt asks for **a review draft** — the property stated formally, a sketch of why
  it must hold, and the test as a fenced patch. Human reviews → commits. The job never edits
  tracked files itself (invariant 2 of the scheduler).
- Findings where a property *fails* on live state are the payoff: pinned via `pin_insight`
  (`level=warn`) + a Living Memory `note` tagged `invariant-violation`.

### Acceptance
- ≥ 15 mined invariants merged as passing tests across `engines/valuation.py`, `book_factor.py`,
  `regime_posture.py`, `calibration.py`.
- ≥ 1 real discrepancy found during mining (historically these passes always find one) filed as a
  pinned finding or `/confirm` proposal.

**Effort:** small. **Runtime model dependency added:** none.

---

## Phase F2 — Tail dependence: is the ballast still ballast on the worst days?

*Upgrade the book's most important risk statistic from first-order to crash-honest.*

### What
`book_factor.factor_concentration` reads average pairwise ρ from the cached 60d correlation
matrix — exactly the statistic that lies in a crash, when ballast correlations converge to 1. Add a
**lower-tail dependence** gauge: on the worst-k% days of the spear, what fraction of the time does
each ballast also print in its own lower tail?

### Design
- New pure helper `tail_dependence.py` (the `explain_context` pattern — profile in, tailored facets
  out, no I/O):
  - `lower_tail_dependence(returns_a, returns_b, *, q=0.10) -> Optional[float]` — empirical tail
    copula estimate λ̂_L = P(B ≤ Q_B(q) | A ≤ Q_A(q)); `None` below a minimum-observation floor
    (small-n honesty: with ~250 cached closes and q=0.10 that's ~25 tail days — report the n).
  - `book_tail_read(closes_by_ticker, weights, *, spear, config) -> dict` — per-ballast λ̂_L to the
    spear + the calm-vs-crash gap (λ̂_L vs plain ρ), flagging any ballast whose crash-correlation
    materially exceeds its calm ρ ("diversifier in calm, spear-beta in stress").
- **Data**: daily closes from `price_history.py` (`data/price_history.json`) — the same
  reproducible store the replay harness grades against, so the read is point-in-time honest and
  never depends on a live quote.
- **Surface**: folded into `book_factor`'s output block on `terminal_state["book_factor"]` as a
  `tail` sub-dict; `get_world_state` inherits it. Thresholds under `book_factor.tail_*` tunables
  (proposal-gated, like the existing three).
- **Measures, never sizes** — same contract as the rest of `book_factor.py`. The conviction dial
  stays the operator's.
- Tests: synthetic return pairs with known copulas (independent → λ̂_L ≈ q; comonotonic → λ̂_L ≈ 1;
  a t-copula-ish heavy-tail pair between), plus the small-n `None` floor.

### Fable's role
Derivation + validation, once: choose the estimator (empirical vs parametric t-copula fit given
~250-close depth), derive the minimum-n floor and confidence treatment, prove the estimator's
bias direction on small samples — then it's crystallized into the pure helper and Fable exits the
loop.

### Acceptance
- Unit tests pass on synthetic copulas; live run over the cached store produces per-ballast λ̂_L
  with stated n; a ballast whose λ̂_L − ρ gap exceeds the tunable prints a `warn` flag.

**Effort:** small-medium. **Runtime model dependency added:** none.

---

## Phase F3 — The living part: coherence-on-heartbeat + conclusion decay

*This is the phase that delivers "constantly scrutinizing" — cheap resident passes on state deltas,
full agents only when a flag fires.*

### F3a — Coherence checker (the terminal must never argue with itself, enforced at runtime)

The signal-coherence law is documented (ROADMAP §"Signal coherence"); nothing enforces it live.

- **Deterministic first** (crystallization again): a pure `coherence_check.py` over one engine
  cycle's state diff, encoding the *known* contradiction patterns as code:
  - directive ACCUMULATE ∧ entry-sentinel AVOID-EXTENDED on the same name;
  - posture cap tightened ∧ any same-cycle verdict that sized *up*;
  - a Council verdict whose stance contradicts the engine directive without a recorded dissent
    caveat (`council.reconcile` output carries it);
  - a pinned insight referencing a superseded Memory entry (`LivingMemory._superseded_ids`).
  Output: a list of contradiction triples `{names, signals, why}` → `pin_insight(level=warn)`.
- **Model second**: a `coherence` job kind (cadence ~ daily, dial-gated) hands Fable only the
  **cycle diff** (what moved, not the whole state) and asks one question — *do these moves cohere,
  given what moved upstream?* Anything the deterministic pass can't express (semantic
  contradictions between a verdict's *text* and the numbers) is its lane. Findings that recur get
  crystallized into `coherence_check.py` as new deterministic patterns.

### F3b — Conclusion decay (verdicts expire when assumptions die, not on a timer)

- **At write time**: Council verdicts and synthesis notes get their load-bearing assumptions
  extracted as **structured claims** on the Memory entry — `assumptions: [{claim, metric, op,
  value}]` (e.g. `{"claim": "financing window > 12mo", "metric": "runway_months", "op": ">",
  "value": 12}`). The arbiter prompt already produces claims (`council.Claim`); this persists the
  checkable subset. Free-text assumptions that can't be structured are stored as text and swept by
  the model pass instead.
- **A sweeper** (`decay_sweep`, scheduler kind, cadence ~ daily): re-evaluates each *open* entry's
  structured claims against live `terminal_state`. A dead claim ⇒ the entry is flagged
  `decayed` — surfaced in the Council view thread and `get_world_state`, and the entry is
  **superseded, never deleted** (`LivingMemory.supersede` — the audit trail is the track record).
  Unstructured assumptions route to a model pass, dial-gated, which may only *propose* a decay
  flag.
- **Event-triggered dispatch** (closing the loop): material-change stamps the valuation ledger
  already writes become triggers — divergence fired → schedule `@anti-scout` on the name; floor
  breached → propose `/council`; forecast due (`forecast_book`) → propose resolution. All through
  the existing `cockpit_triggers.py` / scheduler rails, all dial-gated.

### Acceptance
- Deterministic pass catches a seeded contradiction fixture set (≥ 5 patterns) with zero false
  positives on a clean state; decayed-verdict flag round-trips through Memory supersede; at least
  one trigger→dispatch path (divergence → anti-scout proposal) demonstrated end-to-end in `propose`
  mode.

**Effort:** medium. **Runtime model dependency added:** optional, dial-gated, degrade-to-silent
(engine down or model unavailable ⇒ the deterministic pass still runs).

---

## Second wave (staged after F1–F3 are catching the mechanical failures)

### F4 — Blind re-derivation (N-version programming for the valuation stack)
A `rederive` job kind: nightly, pick the value carrying the most decision-weight (the spear's
directive; the REP floor nearest its price) and have Fable **re-derive it blind from raw inputs** —
its own methodology, never shown the engine's formula (anchoring kills the check). Diff vs the
engine number; agreement is cheap confirmation, divergence is a pinned discrepancy with both
derivations attached. Same pattern for conclusions: a fresh arbiter seat re-judges the evidence
without seeing the recorded verdict; drift is the "is this conclusion still true" signal.
*Depends on F1/F3 filtering out mechanical noise so this hunts genuine methodology errors.*

### F5 — Price the spear as an actual option
AGA.V is described everywhere as option-convexity; nothing prices it as one. A real-options helper
(project NAV as underlying; PEA/permitting milestones as the expiry structure; financing as a
dilution-adjusted strike) yields model-implied Δ/Γ and the implied vol being paid — then
`conviction_book` confidence can be checked for *consistency* with it. Fable derives the model
once; it crystallizes as a pure helper the What-If tab can drive.

### F6 — Hierarchical base rates
`calibration.learned_base_rates` are small-n per-archetype frequencies. Partial pooling
(hierarchical Bayes across archetypes, conjugate Beta treatment consistent with the existing
`_beta_ci`) gives credible intervals instead of point rates — the flywheel stops overreacting to
4-observation cells and `candidate_anchor` inherits honest uncertainty.

### F7 — Kalshi structural arb as a formal no-arb problem
The predict scanner's L1 lane is pairwise. Formalize the live contract set as a small LP (net of
the fee+FX stack, per house rule) so multi-leg structural arbs a pairwise scan can't see are found.
Fable formalizes; the LP solves deterministically each sweep.

### F8 — Grade the analyst itself
Per-seat scoring of Council verdicts against realized outcomes (`calibration.brier_score` extended
to seats): did arbiter verdicts beat the engine directive alone; was the bear's invalidation the
right stop? Over time the arbiter learns how much weight each seat has *earned*. And every
model-proposed param change carries **proof-of-work**: a counterfactual `replay.grade_ledger` run
showing the proposed value would have scored better on the ledger's history, attached to the
`/confirm` proposal. Evidence-gated self-improvement, human-approved, machine-checkable.

---

## Build order

| # | Phase | Payoff | Effort | Model in runtime loop? |
|---|---|---|---|---|
| 1 | F1 invariant mining | compounds forever | S | no |
| 2 | F2 tail dependence | book's core risk question, crash-honest | S–M | no |
| 3 | F3 coherence + decay | the "living analyst" feel | M | optional, dial-gated |
| 4 | F4 blind re-derivation | catches methodology errors | M | yes (scheduled, propose) |
| 5 | F6 hierarchical base rates | honest small-n flywheel | S–M | no |
| 6 | F5 real-options spear | conviction-consistency check | M | no |
| 7 | F7 Kalshi LP | multi-leg L1 finds | S | no |
| 8 | F8 grade-the-analyst | closes the meta-loop | M | no |

F1→F2→F3 first; each is independently shippable and none blocks another. F4 deliberately second
wave — it is the most model-dependent and works best once the deterministic layers are catching
the mechanical failures.

## Guardrails (restated so they can't be lost in the build)

1. The autonomy dial is the only boundary between due and ran; default `propose`.
2. Model jobs emit drafts and proposals — never commits, never `set_param`, never state edits.
3. Every model finding is grounded (derivation + sources attached) or not written.
4. No load-bearing number is model-produced at runtime; model outputs crystallize into pure,
   tested, deterministic code or remain advisory pins.
5. Memory is append-only; decay and correction supersede, never overwrite.
