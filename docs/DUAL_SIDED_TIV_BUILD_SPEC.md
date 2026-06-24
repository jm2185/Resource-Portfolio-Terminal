# Dual-Sided TIV — the conventional-core valuation engine (build spec, 2026-06-24)

> **STATUS (2026-06-24): SPEC + Phases 1–2 landed.** This is a clean Claude Code handoff in the
> `docs/VALIDATION_FLYWHEEL_PLAN.md` milestone format: first principles → honest constraints → the
> precise gap → house rules → numbered phases (each with schema, wiring, tests, effort) → sequencing
> table → risks. Build in the order of §10; nothing changes engine math without a `/confirm` gate.
>
> **Phase 1 (the correlation / independence monitor — §3) is IMPLEMENTED:** `correlation_monitor.py`
> (pure stdlib — Pearson, the INDEPENDENT/PARTIAL/REDUNDANT verdict, the candidate pre-add screen, the
> 60d→120d drift trend, lane-aware book independence; 28 tests in `tests/test_correlation_monitor.py`,
> all green) · the engine held-book monitor + 120d matrix cache + `_fire_correlation_drift` auto-pin
> (`engine.py`, mirroring the `book_factor`/`divergence` wiring, with `tests/test_correlation_engine_
> wiring.py`) · MCP `correlation_check` (held-book role check + candidate screen; `core.py`/`server.py`).
>
> **Phase 2 (the two solvers + the shared schema — §4) is IMPLEMENTED:** `dual_sided.py` (pure stdlib
> — `solve_compounder` reverse-DCF/expectations with the implied-growth solve + torpedo floor;
> `solve_deep_value` SOTP + asset/FCF floor with the fail-closed manual-segment fallback; `value()`
> runs both; the shared schema; the `lane_of`/`guard_conventional` lane guard keeping the core
> monitoring-only; 15 tests in `tests/test_dual_sided.py`, all green) · the two new archetypes
> registered as pure dict additions in `asymmetry_rating.py` (pillar weights, V-mode, stability,
> burn-gate exemption — so both lenses flow through the existing `compute_asymmetry_rating` unchanged).
> Realized WITHOUT the invasive `RegimeImpactVector` 5→7 tuple change (§4.1 refinement): conventional
> names route through the new orchestrator, which reuses `compute_asymmetry_rating`'s scalar regime
> inputs, so the resource regime system is untouched. Phases 3–6 (the divergence spread + reconciliation
> & MCP/ledger wiring, the SENTINEL zones, NIS, the base-rate seed) remain spec.

The keystone build: give the book a **second, genuinely independent thesis** — a conventional-equity
core that compounds cash flows in the AI-upside (C) and benign (E) scenarios the resource book leaves
red — without corrupting the resource satellite that earns the alpha. The engine extension that makes
it safe is a **dual-sided valuation** (two archetype-tuned solvers run on *every* conventional name,
reconciled to a divergence spread) plus a **correlation/independence monitor** that proves the second
thesis wins and loses for *different reasons* than the spear. This plan is written against the actual
code as of `claude/dreamy-brahmagupta-ymqk22` (post-validation-flywheel, post-book-factor,
post-scenario-E), from first principles, with every extension point named.

---

## 0. First principles — what a "second thesis" means here

The criticism being answered: *"your book diversifies across tickers and commodities but stays
concentrated in a single macro factor."* `book_factor.factor_concentration` already MEASURES this —
silver, the royalties, and even uranium share one risk-appetite/debasement/real-rates beta wearing
different costumes (`book_factor.py:64-105`), and `scenario_coverage` shows the consequence: the book
is a wall of green in Debasement (A) and Fiscal-crisis (B) and red/thin in AI-upside (C) and Benign
(E) — two scenarios carrying ~45% of the operator's own probability weight, effectively un-hedged
(`book_factor.py:108-148`; `docs/scenario_matrix.md`). The fix is not another commodity (that adds a
name, not a thesis); it is the half of the investable world that **compounds cash flows** rather than
riding a commodity price.

The Druckenmiller reframe is the whole point: **concentration applies *within* a thesis; multiplicity
applies *across* theses.** A multi-thesis book is what *funds* the giant concentrated silver bet,
because the operator is no longer risking everything on it. The test of a real second thesis is not
"different ticker" or "different sector" — it is **"does it win and lose for different reasons?"** Two
positions at ρ 0.8 are one bet with extra commissions. That test is a *number the engine must
settle*, not a narrative I assert — and it is not built today.

### Four design commitments, stated up front

1. **Core/satellite split with asymmetric engine attention.** The **resource satellite** keeps the
   full FORGE stack (SCOUT · COUNCIL · SENTINEL · CALIBRATION · JSF/Lassonde/REP-floor) because that
   is where the operator's edge and the engine's machinery genuinely earn alpha. The **conventional
   core** gets a *thin* lane: **valuation + correlation/role monitoring + rebalance-band watch only.**
   It is explicitly excluded from **@scout discovery** and **per-name @council deliberation** — the
   engine does not try to be clever where the operator has no edge over the market.

2. **The third invariant.** Today's rules are *"the engine owns the math"* and *"FORGE never
   recomputes what the engine owns."* This plan adds the third: **FORGE does not try to generate alpha
   where it has none.** The conventional core's only engine-relevant question is a role check — *is
   this sleeve still doing its job of not correlating with the spear?* (plus "own what you can price"
   valuation). This is a *constraint*, deliberately limiting scope, not a feature.

3. **Reuse the valuation seam; do not bolt on a parallel engine.** The clean move is NOT a second
   equities-alpha engine. It is **two new archetypes** (`compounder`, `deep_value`) that plug into the
   *existing* `PolymorphicRouter` / leg / `triangulate` / `compute_asymmetry_rating` / ledger machinery
   (`archetypes.py`, `asymmetry_rating.py`, `valuation_ledger.py`) — so the engine still owns the math
   and everything downstream (ledger, replay, conviction, ribbon) consumes them for free. The *new*
   seam is a thin orchestrator that, for a conventional name, runs **both** solvers and reports the
   spread, instead of the router picking one archetype.

4. **Render-not-compute, extended.** Every conventional surface adapts to the name's profile (lens ·
   sector · the live swing variable · listing) exactly as `divergence_monitor.explain_context` adapts
   the decoupling triage to archetype (`divergence_monitor.py:91-134`). A compounder lens fired at a
   deep-value turnaround (wrong failure mode, wrong floor, wrong swing variable) is a **bug, not a
   shortcut** — the same first principle that governs the resource satellite.

### The honest constraints, carried forward (do not bury these)

- **The base-rate library is asserted, not earned.** Until enough conventional theses *close* and are
  graded by CALIBRATION, every probability the engine prints on a swing variable is an **engineering
  prior with n=0 realized** — sourced and confidence-graded, but not a frequency the book has lived.
  The tooltips MUST say so (§8, §9). This is the *exact* discipline already shipped for
  `rep_floor_reliability` / `band_coverage` (`base_rates.py:216-232`) — deliberately weak Betas that a
  season of evidence overwrites — applied to the new priors.
- **The deep-value solver is data-hungrier than the compounder.** A clean sum-of-the-parts needs
  segment-level splits FMP will not always provide. The solver therefore requires a **proposal-gated
  manual-input fallback**: when segment data is absent it fails *closed* (wider band, lower
  conviction, a visible flag), and the operator can supply the splits through a `/confirm`-gated
  override block, with research-cache provenance discipline (§4.3).
- **n=4 → conventional core is small too.** The core starts at 1–2 names (TMX, EEFT). No statistic is
  decisive at that n; the design response is the house one (`reliability.data_limited`,
  event-counts-not-ratios, intervals-only-when-warm) — build the measurement now, report it with
  small-n honesty, let it warm.

---

## 1. Current state — what exists, what's missing (the precise gap)

| Capability the conventional core needs | Where it would live / nearest existing code | Status |
|---|---|---|
| One-archetype-per-ticker routing | `PolymorphicRouter.resolve` / `get_valuation` (`archetypes.py:1323-1354`) | ✅ but picks **one** archetype; no dual-solver path |
| Forward valuation: cost/market/income legs → one blended intrinsic | `AssetArchetype.triangulate` confidence-tilted blend (`archetypes.py:624-633`) | ✅ this **is** the "one blended TIV" the critique names — collapses the two poles |
| Operating-business archetype (closest conventional analog) | `capital_margin` — EV/EBITDA market leg + `FCF/(wacc−g)` income leg (`archetypes.py:861-906`) | ⚠️ forward-only; no reverse/implied-expectations solve |
| Reverse-DCF / expectations ("what growth is priced in, is it real?") | — | ❌ **does not exist** ("forward valuation only" — confirmed) |
| Sum-of-the-parts (general, segment-level) | partial: option_convexity project buckets (`archetypes.py:765-771`), asset_light additive stream (`:1060`) | ⚠️ no general conventional SOTP, no segment splits |
| Asset/FCF floor (conventional analog of REP floor) | REP floor in option_convexity / asset_light cost legs (`archetypes.py:739-752`, `:1037-1066`) | ⚠️ resource-shaped; needs a conventional asset/stressed-FCF floor |
| T-Q-V asymmetry rating, ladder, ribbon, band, directive | `compute_asymmetry_rating` (`asymmetry_rating.py:740-829`) | ✅ archetype-tuned via `pillar_weights_by_archetype` (:252), `v_mode_by_archetype` (:260) — extend, don't rewrite |
| Distributional intrinsic P10/P50/P90 | `uncertainty.intrinsic_distribution` via `_confidence_ribbon` (`asymmetry_rating.py:637-693`) | ✅ consumes legs → reuse for both solvers |
| Point-in-time valuation record (the track record) | `valuation_ledger.snapshot_from_basket` (`valuation_ledger.py:161-218`) | ✅ tolerant schema — add `lens` / `divergence_spread` / `swing_variable` |
| **Cross-method** dispersion (cost vs market vs income) | `valuation_ledger.method_spread` (`valuation_ledger.py:134-158`) | ✅ exists — must NOT be confused with the new cross-LENS spread |
| **Divergence spread** (compounder lens vs deep-value lens) | — | ❌ **does not exist** — the elegant output of the whole engine |
| Held-book correlation level + ballast→spear ρ flag | `book_factor.factor_concentration` → `ballast_correlated` (`book_factor.py:64-105`) | ⚠️ **level** check on the cached 60d matrix; **held names only** |
| Candidate-vs-book correlation (pre-add independence verdict) | — | ❌ **does not exist** — this is what would screen the banks/URNJ OUT |
| Correlation **drift** (trend toward ρ→1, not just level) | — | ❌ **does not exist** |
| Return-correlation primitive (β, residual σ from aligned returns) | `divergence_monitor.baseline_from_returns` (`divergence_monitor.py:232-260`) | ✅ the cov/var math to reuse for Pearson ρ |
| Daily-close history store (for candidate returns) | `price_history.py` → `data/price_history.json` (flywheel Phase 4.1) | ✅ reuse; extend to non-held candidates (FMP `chart`, budget-capped) |
| Narrative-Integrity check for **operating turnarounds** (receipts vs hand-waving) | — | ❌ **does not exist** (JSF/`forensic_gates` grade accounting; catalyst-verifier grades resource catalysts) |
| Base-rate priors for conventional swing variables | `base_rates.PRIORS` + `calibration.ARCHETYPE_PRIOR` (`base_rates.py:153-233`, `calibration.py:47-51`) | ❌ no conventional priors; the **seam** to seed them exists |
| SENTINEL: price-crosses-a-zone / asymmetry-zone trigger | nearest: `thesis_integrity` below-floor (`sentinel.py:191-226`); ladder zones from the rating | ❌ no zone-cross trigger |
| MCP exposure (a tool the cockpit/agents call) | `@mcp.tool()` wrapper → `core.py` impl (`server.py:42-55`; `core.py`) | ✅ pattern ready — add the new tools |

**The one-sentence gap:** the engine prices conventional equity with a single forward-blended number
that mis-prices both poles, cannot say whether a candidate is a *second thesis or a redundant bet*,
and has no way to grade a turnaround narrative — so the conventional core cannot be underwritten
safely; everything downstream (ledger, replay, conviction, SENTINEL) is ready to consume the answers.

---

## 2. Design constraints (house rules that bind every phase)

These extend the `VALIDATION_FLYWHEEL_PLAN.md §2` rules; the resource rules still hold verbatim.

- **Engine owns the math; FORGE renders.** Both solvers live in engine-owned modules; agents/cockpit
  read the result, never recompute it (same rule the ledger's Goodhart guard enforces,
  `valuation_ledger.py:166-172`).
- **The third invariant — no alpha where there is none.** The conventional lane is monitoring-only.
  A **lane tag** (`portfolio_metadata[ticker].lane = "conventional"`) gates it OUT of `@scout` and
  per-name `/council`; its engine attention is valuation + correlation + SENTINEL + rebalance-band
  measurement. The lane guard is named and tested (§4.4), not implicit.
- **Two distinct things, kept distinct (the house discipline).** The plan introduces two spreads and
  must never conflate them: the **method spread** (cross-method, cost/market/income within one lens —
  `valuation_ledger.method_spread`) and the **divergence spread** (cross-lens, compounder vs
  deep-value). Glossary and tooltips name the distinction, exactly as the flywheel kept the *estimate
  band* distinct from the *scenario ladder* (`VALIDATION_FLYWHEEL_PLAN.md §5.1`).
- **Fail-closed.** Absent/stale segment splits → SOTP runs on what it has, flags the hole, widens the
  band, lowers conviction — never a fake default (the `research_cache` contract, wired end-to-end via
  the ribbon, `asymmetry_rating.py:637-693`).
- **Asserted-not-earned honesty.** Every base-rate probability is tagged with its `confidence` and a
  `data_limited`/n=0 caveat until CALIBRATION has graded enough closed conventional theses
  (`calibration.py:34`, the `MIN_PERSONAL_N` pattern). No bare % on a swing variable, ever.
- **Human gate on tunables.** New thresholds (`dual_sided.*`, `correlation_monitor.*`,
  `narrative_integrity.*`) ship as module `DEFAULT_*_CONFIG` and route to `v5_config.json` only via
  `propose_param_change` → `/confirm`.
- **No regime double-count.** The regime enters exactly one leg per archetype
  (`DNA.regime_tilt_leg`, `archetypes.py:660-663`); the new archetypes obey it (`income` leg for both,
  §4.2). The valuation does **not** re-condition on the scenario weights — the scenario engine
  consumes the valuation, never the reverse.
- **Stdlib only** for the new core modules (`dual_sided.py`, `correlation_monitor.py`,
  `narrative_integrity.py`) — the house norm (`book_factor`, `divergence_monitor`, `valuation_ledger`
  are all stdlib, no numpy/pandas), so the whole thing is unit-testable off the engine.
- **It MEASURES; it never sizes.** Correlation, drift, rebalance bands, the divergence spread — all
  are read-only gauges. Allocation stays the operator's dial (the `book_factor` discipline,
  `book_factor.py:16`).

---

## 3. Phase 1 — the correlation / independence monitor (`correlation_monitor.py`) — load-bearing

**What:** the gauge that decides whether a conventional name is a *second thesis* or a *redundant
bet*. It is Phase 1 because the entire justification for the sleeve rests on it, and because it
*screens candidates before any valuation work is spent on them*.

### 3.1 The module (pure, stdlib — clone the `book_factor` / `divergence_monitor` shape)

New `correlation_monitor.py`. Reuses the cov/var primitive already proven in
`divergence_monitor.baseline_from_returns` (`divergence_monitor.py:232-260`).

```python
DEFAULT_CORRELATION_CONFIG = {
    "window_short": 60,        # the live read (matches the engine's cached 60d matrix)
    "window_long": 120,        # the slow read, for the drift trend
    "independent_max": 0.30,   # ρ ≤ this vs the book ⇒ genuinely INDEPENDENT (a real 2nd thesis)
    "partial_max": 0.60,       # ρ in (0.30, 0.60] ⇒ PARTIAL — diversifies, but shares a beta
    "redundant_min": 0.60,     # ρ > this ⇒ REDUNDANT — one bet with extra commissions
    "drift_warn": 0.10,        # ρ_short − ρ_long ≥ this ⇒ a sleeve creeping toward the spear
    "min_n": 30,               # too few aligned points ⇒ verdict "insufficient", never a guess
}
```

Public surface:
- `pearson(a_returns, b_returns, *, min_n)` → ρ over date-aligned returns (cov / σ·σ), `None` when
  thin. (The β/σ regression already exists; ρ is the same frame.)
- `independence_verdict(rho, *, config)` → `INDEPENDENT | PARTIAL | REDUNDANT | INSUFFICIENT` + a
  Druckenmiller "different reasons" read string.
- `assess_candidate(cand_returns, book_returns_by_ticker, *, spear="AGA.V", weights, config)` → ρ to
  the **spear** specifically, ρ to the **book** (weighted blend), the verdict, and the SENTINEL flag
  if `REDUNDANT`. This is the **pre-add screen** hook.
- `drift(rho_short, rho_long, *, config)` → the trend gauge + the `correlation_drift` flag when a
  *held* sleeve's short-window ρ to the spear is rising past `drift_warn` above its long-window ρ.
- `assess_book_independence(corr_matrix, lanes, *, spear, config)` → the ongoing read over the cached
  matrix, **lane-aware**: it separates the conventional sleeves (which *should* be low-ρ to the spear)
  from the resource ballast, so a conventional name drifting toward the spear is the alarm that
  matters most. This is the **drift** hook.

Every flag is the house schema `{id, active, level, text, ticker?, corr?}`; the module returns
`{available, flags, events, read, glossary}` and never raises (the SENTINEL contract).

### 3.2 How it reconciles with what already exists

`book_factor.factor_concentration` already flags a **held** ballast at ρ ≥ 0.85 to the spear
(`ballast_correlated`, `book_factor.py:92-96`) off the engine's cached, shrunk 60d matrix
(`engine.py:3304/3345`). This phase **does not duplicate** that; it adds the two things it cannot do:

1. **Pre-add candidate verdict** — `book_factor` only sees names already in the book. A *candidate*
   (TMX, EEFT, and the names to reject) has no row in the held matrix. `assess_candidate` computes its
   ρ to the spear from a returns series fetched on demand (§3.3) and returns the INDEPENDENT/PARTIAL/
   REDUNDANT verdict *before* a position exists. **This is the gate that screens the banks out** (see
   §3.4).
2. **Drift, not just level** — `ballast_correlated` is a threshold on today's ρ. `drift` is the slope:
   ρ_short vs ρ_long. "A ballast that *was* ρ 0.4 and is *now* ρ 0.7 and climbing" fires before it
   crosses the static 0.85 line — which is exactly when a ballast quietly stops being ballast.

The static `ballast_decoupled_min` (0.85) stays as the hard level alarm; `redundant_min` (0.60) is the
softer *independence* bar a second thesis must clear at entry. Both are tunable.

### 3.3 Returns source (reuse the flywheel's store)

Grading reads `price_history.py` → `data/price_history.json` (the daily-close store the flywheel
already maintains, `VALIDATION_FLYWHEEL_PLAN.md §4.1`). For a non-held candidate, backfill ~1y of
closes once via FMP `chart` (budget-capped, the existing `get_fundamentals` envelope) or the yfinance
batch; thereafter the candidate rides the daily append. Correlations are computed from this store, not
a live quote, so a verdict is reproducible. Returns are date-aligned by the caller (the engine pulls
both legs from the same frame), tail-aligned in the module — identical to `baseline_from_returns`.

### 3.4 Worked examples (the capability, demonstrated — these become test fixtures)

These are the conversation's own candidates; the monitor is what *settles* them with numbers instead
of my reasoning:

- **The banks (AX / OZK / OFG)** — a leveraged version of the steepener bet gold already gives the
  book, plus credit risk. Expectation: ρ to the spear high enough to land **REDUNDANT** (or PARTIAL at
  best) → screened OUT. *This is the capability working as a preview.*
- **Junior-uranium basket (URNJ)** — different commodity, but shares AGA.V's junior-mining
  risk-appetite beta. Expectation: **REDUNDANT/PARTIAL** despite the different metal — proving the test
  is "different reasons," not "different sector."
- **TMX Group (X.TO)** — capital-light monopoly compounder; sidesteps the credit tail and the bond-
  duration tail. Expectation: **PARTIAL** (its Capital Formation segment earns fees on the same TSXV
  junior financings the book participates in — a real, *named* partial correlation, not zero) — a
  defensible second thesis whose one overlap is disclosed.
- **Euronet (EEFT)** — payments toll-taker; risks are immigration policy, EU regulation, the Apple
  cliff. Expectation: **INDEPENDENT** — the cleanest decorrelation, which is the point of the name.

### 3.5 Wiring, tests, effort

- **Hooks:** (a) `discovery_screen.py` / a new MCP tool calls `assess_candidate` as a **gate** for
  conventional candidates (slot-fit is N/A for the core; the *independence* verdict replaces it as the
  first gate). (b) the engine eval loop calls `assess_book_independence` each cycle and fires
  `correlation_drift` via the existing `_fire_divergence` auto-pin + Living-Memory path
  (`engine.py:3814-3857`), deduped by `select_fresh` semantics.
- **MCP:** `correlation_check(ticker)` (core.py impl + server.py `@mcp.tool()` wrapper) → verdict +
  ρ-to-spear + ρ-to-book + drift; `get_world_state` gains a one-line conventional-independence read.
- **Tests** (`tests/test_correlation_monitor.py`): Pearson math vs hand-computed; verdict thresholds;
  `min_n` → INSUFFICIENT not a guess; drift fires on a rising series and stays quiet on a flat one;
  the four §3.4 fixtures land in their expected buckets; lane-awareness (a conventional name's drift
  outranks a ballast's). Pure, no network.

**Effort: M. Data spend: small (one ~1y backfill per candidate, then free daily appends).**

---

## 4. Phase 2 — the two solvers + the shared output schema (`dual_sided.py` + two archetypes)

**What:** price the two poles of conventional equity correctly and emit **one common schema** so a
premium monopoly and a deep-value turnaround can be weighed on one Conviction-Mode screen.

### 4.1 The solvers (two new archetypes on the existing seam)

Add to `ARCHETYPE_DNA` (`archetypes.py:256`), `ARCHETYPE_REGISTRY` (`:1224`), the `RegimeImpactVector`
(`:38-47`, +1 slot each — keep the one-leg-per-archetype regime discipline), `ARCHETYPE_BY_TYPE`
(`:1233`), `asymmetry_rating.pillar_weights_by_archetype` / `v_mode_by_archetype` / `stability_by_
archetype` (`asymmetry_rating.py:252/260/266`), and `calibration.ARCHETYPE_PRIOR` / `ARCHETYPE_RHO_BAR`
(`calibration.py:40-51`).

**Solver A — `compounder` (reverse-DCF / expectations).** *"What growth and duration is priced in, and
is it real?"*
- **Method:** invert the `capital_margin` income leg. Given EV (price·shares + net debt), current
  FCF/NOPAT, and WACC, **solve for the market-implied growth × competitive-advantage-period (CAP)** —
  the expectations the price embeds (Rappaport/Mauboussin *Expectations Investing*). Then forward-DCF
  at a **base-rate-anchored** achievable growth (p50/p10/p90 from §8) to get the ladder.
- **Legs:** `income` = forward-DCF at base-rate growth (the lead leg, carries the regime tilt);
  `market` = peer multiple (EV/EBITDA, EV/FCF) sanity leg; `cost` = a weak asset floor (book / capex
  replacement — thin for a capital-light name, by design).
- **Margin of safety lives in:** the *durability* of compounding (the CAP). **Failure mode:** the
  **torpedo** — multiple compression on a growth miss. The asymmetry is therefore *upside if
  compounding sustains vs. downside to the de-rated multiple*, not floor coverage — `phi` is weak and
  honestly so; `rho_compounder = (bull_dcf/price − 1) / max(price/torpedo_floor − 1, δ)` where
  `torpedo_floor` = value at the de-rated (peer-trough) multiple. V runs in **value mode**
  (fair-value-centric, `asymmetry_rating.py:551-566`).
- **The single swing variable:** the **priced-in growth/CAP vs. achievable** — surfaced with its base
  rate (`compounder_growth_persistence`, §8). This is the load-bearing number the whole lens turns on.

**Solver B — `deep_value` (sum-of-the-parts + asset/FCF floor).** *"What are the pieces worth, and
where's the floor?"*
- **Method:** **SOTP** — value each segment at a segment-appropriate multiple (EV/EBITDA or EV/FCF) and
  sum; net out corporate/debt. The **floor** is the conventional analog of REP: net asset value or a
  **stressed-FCF capitalization** (lowest defensible cash-flow value), the same role the REP floor
  plays for the spear (`archetypes.py:739-752`).
- **Legs:** `market` = SOTP at peer multiples (lead); `cost` = the asset/stressed-FCF floor;
  `income` = a whole-company FCF cap (carries the regime tilt) as a cross-check on the SOTP.
- **Margin of safety lives in:** the **entry discount** (price vs. SOTP) — so `phi` (floor coverage)
  is *strong and meaningful* here, and V can run closer to **asymmetry mode** (the discount is the
  convexity). **Failure mode:** the **value trap** — the discount persists because a segment is
  structurally melting.
- **The single swing variable:** the **load-bearing segment** (e.g., Euronet's Ria remittance under
  US immigration policy, or the ATM/EFT melt rate) — surfaced with `deep_value_discount_closes` (§8).

Both solvers reuse `triangulate` (`archetypes.py:624-633`) for the within-lens blend and
`uncertainty.intrinsic_distribution` (via `_confidence_ribbon`, `asymmetry_rating.py:637-693`) for the
P10/P50/P90 estimate band. The difference from the resource path is that the **router does not pick
one** — the orchestrator runs **both** (§5).

### 4.2 The shared output schema (the keystone — both solvers emit this)

One schema, extending the engine's existing valuation output (`compute_asymmetry_rating`,
`asymmetry_rating.py:795-829`) and the ledger snapshot (`valuation_ledger.py:182-218`) so every
downstream consumer works unchanged. Per lens:

```jsonc
{
  "lens": "compounder" | "deep_value",
  "ticker": "X.TO", "archetype": "compounder",
  "intrinsic": 52.0,                                  // central estimate (= ladder.base)
  "ladder": {"floor": 38.0, "bear": 44.0, "base": 52.0, "bull": 71.0},
  "asymmetry": {"rho": 1.8, "phi": 0.73, "upside_pct": 12.0, "downside_to_floor_pct": 24.0, "mode": "value"},
  "pillars": {"T": 5.1, "Q": 7.8, "V": 5.4},          // compute_asymmetry_rating, new-archetype weights
  "rating": 6.6, "band": "HIGH QUALITY", "directive": "QUALITY — CORE HOLD",
  "confidence_ribbon": {"plus_minus": 0.9, "quality": "full", "p10": 46.0, "p50": 52.0, "p90": 64.0},
  "legs": {"values": {"cost": 38.0, "market": 49.0, "income": 53.0}, "weights": {...}, "confidence": {...}},
  "method_spread": {"spread_pct": 28.8, "n_methods": 3},   // cross-METHOD (within this lens)
  "swing_variable": {                                  // the single load-bearing variable
    "name": "priced-in FCF growth × CAP",
    "value": "9%/yr for 11 yrs implied vs ~6%/8yr base-rate-plausible",
    "base_rate_name": "compounder_growth_persistence",
    "base_rate": {"mean": 0.34, "ci90": [0.12, 0.61], "confidence": "low", "source": "..."},
    "probability": 0.34, "asserted": true,            // n=0 realized — NOT an earned frequency
    "read": "market prices an above-base-rate runway; the torpedo is a growth miss"
  },
  "data_completeness": {"segments_supplied": null, "fallback_used": false},  // deep_value SOTP only
  "inputs": { /* by-value provenance copy, inputs_from_provenance (valuation_ledger.py:110-131) */ }
}
```

Notes:
- `pillars`/`rating`/`band`/`directive`/`ladder`/`confidence_ribbon`/`asymmetry` are produced by the
  **existing** `compute_asymmetry_rating` once the new archetype's pillar weights and V-mode are
  registered — no new rating math. The solver's job is to produce the legs + ladder + swing variable
  that feed it.
- `method_spread` is the **existing** cross-method stat (`valuation_ledger.method_spread`,
  `:134-158`). It is intentionally in the per-lens block to keep it distinct from the cross-lens
  `divergence_spread` (§5).
- `asserted: true` is the n=0 honesty flag (§8); it drives the tooltip caveat and is cleared by
  CALIBRATION only when the prior has earned data.

### 4.3 The deep-value manual-input fallback (the data-hunger caveat, made safe)

FMP's `statements` will not always carry clean segment splits. The deep-value solver therefore:
1. Attempts SOTP from FMP segment data when present.
2. On absence/partial: **fails closed** — runs SOTP on the segments it has, sets
   `data_completeness.segments_supplied = <list>`, `fallback_used = true`, widens the band (low-
   confidence legs → `uncertainty` σ map), and lowers conviction mechanically (the ribbon→conviction
   pathway, `asymmetry_rating.py` V-pillar support). The hole is **visible**, never a default.
3. The operator may supply segment EBITDA/FCF + multiples through a **`/confirm`-gated override
   block** in `v5_config.json → dual_sided.sotp_overrides[ticker]`, stored with research-cache
   provenance (`{value, source, as_of, confidence}` — `research_cache` discipline). A manual segment
   carries its own confidence and is graded like any other input.

### 4.4 The lane guard (the third invariant, enforced)

A conventional name is tagged `portfolio_metadata[ticker].lane = "conventional"`. The dual-sided path
runs for it; **`@scout` and per-name `/council` refuse it** with a one-line "conventional lane —
monitoring only, no discovery/deliberation" (the same refuse-with-reason pattern as
`graduate_candidate`'s missing-receipts refusal). Resource names (`lane` absent or `"resource"`) are
untouched. The guard is a named function, unit-tested.

### 4.5 Tests, effort

- `tests/test_dual_sided.py`: the reverse-DCF inversion round-trips (forward-DCF at the solved-for
  growth reproduces price); SOTP sums correctly and the floor is a true lower bound; fallback flags +
  widens the band + lowers conviction (the fail-closed property as an executable test); both lenses
  emit the schema and pass through `compute_asymmetry_rating` unchanged; the lane guard refuses scout/
  council; TMX lands compounder-led, EEFT deep-value-led (§5 fixtures).
- `tests/test_archetypes.py` extended: the two new archetypes register, route, and triangulate; the
  regime tilt hits exactly one leg (no double-count).

**Effort: L (the reverse-DCF solve + general SOTP are genuinely new). Data spend: small (FMP
statements for non-holdings, inside the cap).**

---

## 5. Phase 3 — reconciliation & the divergence spread (`dual_sided.reconcile`)

**What:** the elegant output — the spread *between* the two lenses, which is the single number that
tells the operator which kind of conventional bet this is.

### 5.1 The orchestrator

`dual_sided.value(ticker, payload, regime)` runs **both** solvers and returns `{compounder, deep_value,
reconciliation}`. `reconcile(compounder, deep_value, price)` computes:

```jsonc
"divergence_spread": {
  "compounder_intrinsic": 52.0, "deep_value_intrinsic": 41.0, "price": 47.0,
  "spread_pct": 23.9,                         // (compounder − deep_value) / median
  "leader": "compounder",                     // the higher-intrinsic lens
  "shape": "premium-franchise" | "mispricing-flag" | "converged",
  "lead_lens": "compounder",                  // which lens drives the HEADLINE rating/directive
  "read": "..."
}
```

### 5.2 The three shapes (the interpretation logic)

- **`premium-franchise`** — wide spread, **compounder leads** (compounder ≫ deep-value, price between
  them). The franchise premium the operator is *knowingly* paying: MoS is the moat (durability), not
  the discount; the asset floor sits far below price. **TMX.** Directive flavour: *"premium franchise
  — MoS is the moat; the watch is the torpedo (multiple compression on a growth miss)."*
- **`mispricing-flag`** — **inverted** spread, **deep-value leads** (deep-value > compounder, and the
  parts may exceed price while the compounder lens shows the market pricing *decline*). The market
  prices a melting compounder; the pieces are worth more. **EEFT.** Directive flavour: *"mispricing
  flag — priced as a melting compounder, parts worth more; the swing is [load-bearing segment]."*
- **`converged`** — tight spread (within the combined ribbon): both lenses agree → high confidence in
  the central estimate; the rating stands on a firm base.

`lead_lens` selection (drives the one-line directive): **deep-value leads** when `phi` is strong and
the discount is the thesis; **compounder leads** when the name trades above its asset floor and
durability is the thesis; on `converged`, lead with the higher-confidence ribbon. The screen shows
*both* lens ratings; the lead is only for the headline.

### 5.3 Distinct from `method_spread` — say it in the schema and the glossary

`method_spread` = dispersion across cost/market/income **within one lens** (do the three methods
agree?). `divergence_spread` = dispersion across the two **lenses** (which *kind* of bet is this?).
They are orthogonal; a name can have a tight method spread in each lens and a wide divergence spread
between them (that is precisely the premium-franchise signal). The glossary entries (§9) and the
ledger keys keep them separate, the same way the flywheel kept the estimate band distinct from the
scenario ladder.

### 5.4 Ledger + conviction wiring

- `valuation_ledger.snapshot_from_basket` (`valuation_ledger.py:161-218`) gains optional `lens`,
  `divergence_spread`, and `swing_variable` keys; `fingerprint` (`:221-236`) folds in the lead-lens
  intrinsic + the swing-variable value (a shape flip or a swing-variable restatement is a
  `material_change` worth a snapshot). Replay (`replay.py`) then grades conventional valuations with
  the same machinery as resource ones (convergence, band coverage, floor reliability) — the
  divergence spread accrues a track record too.
- `_project_conviction_basket` (`mcp_server/core.py:836-894`) carries the dual-sided block for
  conventional names so `get_conviction_ratings` / the Conviction-Mode screen renders both lenses +
  the spread + the swing variable on one surface.

### 5.5 Tests, effort

- `tests/test_dual_sided.py` (reconcile): the three shapes classify correctly on fixtures (TMX →
  premium-franchise/compounder-led; EEFT → mispricing-flag/deep-value-led; a fair-priced staple →
  converged); spread math; lead-lens selection; ledger round-trips the new keys; fingerprint changes
  on a shape flip.

**Effort: S–M (pure reconciliation over §4 outputs). Data spend: none.**

---

## 6. Phase 4 — archetype-aware SENTINEL triggers

**What:** the conventional lane's tripwires, in the exact `divergence_monitor` shape (pure `assess` →
`{flags, events}` → `select_fresh` dedup → engine `_fire_*` auto-pin + Living-Memory write).

### 6.1 `asymmetry_zone_cross` — price crossing a solver's zone

The ladder + band the rating already produces define each lens's zones; this trigger fires on a
**crossing** (the information is in the transition, not the level):
- **Deep-value:** price crossing **below the asset/FCF floor** (`phi ≥ 1`) → opportunity (`good`);
  crossing back **above SOTP base** → zone exit / upside spent (`info`). (e.g., *EEFT below its
  floor*.)
- **Compounder:** price crossing **above the priced-in-growth ceiling** (market-implied growth >
  base-rate-plausible p90) → **extended / torpedo-exposed** (`warn`); crossing **below base DCF** →
  accumulate zone (`good`). (e.g., *TMX above its priced-in growth band*.)

`DEFAULT_*_CONFIG` carries the band multipliers; the trigger reads the live ladder/ribbon, so it
inherits the archetype tuning for free. Levels per the `_LEVEL_BY_ACTION` taxonomy
(`sentinel.py:230-234`).

### 6.2 `correlation_drift` — the ballast-stops-being-ballast alarm

Defined in Phase 1 (`correlation_monitor.drift`/`assess_book_independence`); surfaced here as a
SENTINEL flag (`warn`) when a conventional sleeve's short-window ρ to the spear rises past
`drift_warn` above its long-window ρ. It is the *trend* companion to `book_factor`'s static
`ballast_correlated` level alarm — both fire onto the same board.

### 6.3 Rebalance-band watch (the thin lane's allocation gauge — measures, never sizes)

A light read flagging when a sleeve's weight drifts outside an operator-set band (`dual_sided.rebalance_
band`), prompting the operator — consistent with `book_factor`'s "MEASURES; never sizes" discipline
(`book_factor.py:16`). No auto-rebalance; a `flag`/`alert`-level surface only.

### 6.4 Wiring, tests, effort

- Engine eval loop calls the new `assess_*` each cycle for conventional names; fresh flags pin once
  via `select_fresh` and write to Living Memory (`engine.py:3814-3857`). Autonomy dial gates auto-pins
  (`mcp_server/core.py:2414-2419`).
- `tests/test_sentinel_conventional.py`: zone-cross fires on a crossing and not on a level held;
  drift integration; dedup (one pin per event, re-fire on direction flip); fail-closed on thin inputs.

**Effort: S–M (the SENTINEL template is mature). Data spend: none.**

---

## 7. Phase 5 — Narrative Integrity for operating turnarounds (`narrative_integrity.py`)

**What:** grade whether a *management turnaround narrative* has **receipts** versus hand-waving, and
**locate where the real risk now sits** — the operating-business analog of the JSF forensic gate and
the catalyst-verifier's straight-to-source discipline. (NIS does not exist today; this builds it.)

### 7.1 Why a resource-catalyst NIS would miss it (the Euronet lesson)

The naive "melting ATM value trap" thesis on Euronet was largely **stale**: management measurably
repositioned (ATM share of the EFT segment ~90% pre-COVID → ~60%; segment renamed "payments
infrastructure"; REN/CoreCard winning recurring-revenue deals; EU cash-access regulation turning ATMs
into mandated outsourcing). A resource NIS (drill results, PEA milestones) cannot grade that, and
cannot see that the pressure **relocated** from ATMs to **Ria remittance under US immigration policy**.
NIS must be **context-aware by profile**, exactly like `divergence_monitor.explain_context`
(`divergence_monitor.py:91-134`).

### 7.2 The check

`narrative_integrity.grade(ticker, claims, receipts, *, profile)`:
- **Claims** = the turnaround thesis decomposed into discrete, falsifiable statements ("ATM share
  falling," "recurring revenue rising," "regulation tailwind real").
- **Receipts** = each claim mapped to a verifiable source — a **segment-disclosure trend** in the
  10-K/10-Q, a **contract announcement** straight-to-source (issuer PR / EDGAR), a **regulatory
  citation**. A claim with a trend-confirming receipt scores high; a claim with hand-waving scores
  low.
- **Output:** `{integrity_score (0–1), claims:[{claim, receipt, status: confirmed|partial|unsupported,
  source}], risk_locus, read}` where `risk_locus` names where the live risk has *moved to* (Euronet:
  "Ria remittance / immigration policy," not "ATMs"). Context-aware facets (which receipt *system*
  applies — segment trend vs drill leak vs royalty NSR) come from a pure `profile → facets` helper,
  the `explain_context` pattern.

### 7.3 Where it plugs in

- **Q pillar:** for conventional names, the NIS score feeds the **Q (Quality)** pillar's management/
  conviction term (`asymmetry_rating.py:485-506`) — a turnaround with receipts lifts Q; hand-waving
  caps it. It is the conventional analog of how the forensic gate caps the resource Q
  (`forensic_gates.py`).
- **SENTINEL:** a `narrative_break` flag (`warn`) when a tracked claim's receipt *reverses* (a segment
  trend that was improving turns down) — the turnaround losing its evidence is exactly the value-trap
  confirmation the deep-value lens fears.

### 7.4 Tests, effort

- `tests/test_narrative_integrity.py`: confirmed/partial/unsupported scoring; the risk-locus locator
  on the Euronet fixture; context-aware facets differ by profile; a reversed receipt fires
  `narrative_break`; fail-closed on missing receipts (unsupported, never assumed confirmed).

**Effort: M (new construct; lighter than the dual-sided engine). Data spend: web/filings, straight-
to-source, no new budget loop.**

---

## 8. Phase 6 — the base-rate library (seed + the asserted-not-earned spine)

**What:** the priors the swing variables rest on — seeded honestly, graded into frequencies as theses
close.

### 8.1 New priors (in `base_rates.PRIORS`, `base_rates.py:153-233`)

All shipped `confidence: "low"`, deliberately **weak Betas** (small a+b) so a season of graded
outcomes overwrites them fast — the *exact* pattern of `rep_floor_reliability`/`band_coverage`
(`base_rates.py:216-232`). Each carries a real `source` + `url` (compounding-persistence / fade
literature for the compounder priors; value-vs-glamour / mean-reversion studies for the deep-value
priors):

```jsonc
"compounder_growth_persistence": { "kind": "beta", "a": 4, "b": 8, "confidence": "low",
  "source": "competitive-advantage-period / sales-growth-persistence base rates (Mauboussin 'Measuring the Moat'; ...)",
  "note": "P(a premium compounder sustains its priced-in growth × CAP). ASSERTED — n=0 realized." },
"multiple_compression_on_miss": { "kind": "beta", "a": 6, "b": 4, "confidence": "low",
  "source": "post-miss de-rating studies (...)",
  "note": "the torpedo: P(material multiple compression | growth miss). ASSERTED." },
"deep_value_discount_closes": { "kind": "beta", "a": 4, "b": 6, "confidence": "low",
  "source": "value-vs-glamour reversion / SOTP-discount-closure studies (...)",
  "note": "P(a deep-value SOTP discount closes within ~3y vs. stays a trap). ASSERTED." }
```

Map them in `calibration.ARCHETYPE_PRIOR` (`calibration.py:47-51`): `compounder → compounder_growth_
persistence`, `deep_value → deep_value_discount_closes`; set `ARCHETYPE_RHO_BAR` (`:40-41`) for each
(a compounder's "well-shaped" bar is lower than the spear's; a deep-value's sits between).

### 8.2 The asserted-not-earned spine (reuse, do not reinvent)

The honesty is the *existing* machinery, not a new flag: `estimate` already returns the `confidence`
grade + a 90% CI and never a bare % (`base_rates.py:253-269`); `update_beta` already tracks `n_prior`
vs `n_data` + `shrinkage` (`:272-285`); the scorecard already emits `data_limited` below
`MIN_PERSONAL_N` (`calibration.py:34`). The schema's `swing_variable.asserted = true` (§4.2) is set
whenever `n_data == 0`, and every tooltip that prints the probability appends the caveat (§9). When
CALIBRATION grades a closed conventional thesis (did the priced-in growth materialize? did the
discount close?), `update_beta` folds the outcome in and `asserted` flips to false once warm —
identical to how `replay.ledger_priors` feeds floor/band posteriors (`replay.py:240-264`).

### 8.3 Tests, effort

- `tests/test_base_rates.py` extended: the new priors estimate with CIs; `update_beta` shifts the
  posterior; `ARCHETYPE_PRIOR` resolves the new archetypes; a swing variable with n=0 reports
  `asserted: true` and the caveat text.

**Effort: S (the registry + grading seam exist). Data spend: none (sourcing is one-time research).**

---

## 9. Tooltip / glossary copy (the `*_GLOSSARY` + `*_tooltip` pattern)

Following `DIVERGENCE_GLOSSARY` + `divergence_tooltip` (`divergence_monitor.py:55-71`) and
`ASYMMETRY_GLOSSARY` — each entry is `{what, scale, influence/drives, edge/note}`. Ship at least:

- **`divergence_spread`** — *what:* the gap between the compounder lens and the deep-value lens.
  *scale:* wide+compounder-led = premium franchise (paying for durability); inverted+deep-value-led =
  mispricing (parts worth more than a melting-compounder price); tight = converged. *drives:* the
  headline lens + directive flavour; never a sizing call. *note:* **distinct from method spread**
  (that is cost/market/income agreement *within* one lens).
- **`compounder` lens** — *what:* reverse-DCF/expectations — the growth × CAP the price embeds vs.
  what's achievable. *edge:* margin of safety is the moat's durability; the failure mode is the
  torpedo.
- **`deep_value` lens** — *what:* SOTP + asset/FCF floor — what the pieces are worth and the floor
  beneath them. *edge:* margin of safety is the entry discount; the failure mode is the value trap.
- **`swing_variable`** — *what:* the single load-bearing variable the thesis turns on, with its base
  rate. *note:* **the probability is an ASSERTED prior (n=0 realized) until enough theses close — a
  sourced engineering estimate, not a frequency the book has lived.** (Mandatory caveat while
  `asserted`.)
- **`independence_verdict`** — *what:* ρ of the name's returns to the spear/book. *scale:* ≤0.30
  INDEPENDENT (a real 2nd thesis) · ≤0.60 PARTIAL · >0.60 REDUNDANT (one bet, extra commissions).
  *edge:* the Druckenmiller test is "different *reasons*," not "different sector" — URNJ and the banks
  fail it despite different exposures.
- **`correlation_drift`** — *what:* short-window ρ to the spear rising above the long-window ρ.
  *drives:* a SENTINEL warn — a ballast quietly stopping being ballast, before it crosses the static
  0.85 level.
- **`asymmetry_zone_cross`** — *what:* price crossing into/out of a lens's asymmetry zone (deep-value
  below floor; compounder above the priced-in-growth ceiling). *note:* the signal is in the crossing,
  not the level.
- **`narrative_integrity`** — *what:* whether a turnaround narrative has receipts (segment-trend /
  filing / contract) vs hand-waving, and where the live risk relocated. *edge:* a resource-catalyst
  check can't grade an operating turnaround — this one is profile-aware.

---

## 10. Sequencing, dependencies, definition of done

| # | Build | Solves | Depends on | Effort | Data spend |
|---|---|---|---|---|---|
| 1 | `correlation_monitor.py` + candidate screen + drift SENTINEL + MCP `correlation_check` | "is it a 2nd thesis or a redundant bet?" — the load-bearing test | `price_history` (flywheel) | M | small |
| 2 | `compounder` + `deep_value` archetypes + `dual_sided.value` + shared schema + lane guard + manual fallback | mis-pricing the two poles; the thin-lane boundary | — | L | small |
| 3 | `dual_sided.reconcile` + divergence spread + ledger/conviction wiring | "which kind of bet is this?" — the elegant output | 2 (and 1 to record independence beside it) | S–M | none |
| 4 | `asymmetry_zone_cross` + `correlation_drift` + rebalance-band SENTINELs | archetype-aware tripwires | 1, 3 | S–M | none |
| 5 | `narrative_integrity.py` → Q pillar + `narrative_break` SENTINEL | grading operating turnarounds | 2 (Q wiring) | M | web/filings |
| 6 | base-rate priors + `ARCHETYPE_PRIOR` mapping + asserted-not-earned spine | honest swing-variable probabilities | 2 (archetypes), best with 3 | S | none |

**Order of work: 1 → 2 → 3, then 4–6 as a fan-out.** Phase 1 first because it *screens candidates
before valuation spend* and *justifies the whole sleeve*; 2–3 are the dual-sided engine the synthesis
called "the most spec-ready piece"; 4–6 enrich and protect it. Phase 6 must precede *trusting* any
printed probability (until then, `asserted: true` everywhere).

**Definition of done:** the operator can hand the engine a conventional candidate (TMX, EEFT) and get,
on one Conviction-Mode screen and stamped into the ledger:
1. an **independence verdict** vs the spear/book (INDEPENDENT/PARTIAL/REDUNDANT) — and the banks/URNJ
   land REDUNDANT/PARTIAL, the capability working;
2. **both lens valuations** (compounder + deep-value) with the shared schema, ladder, and ribbon;
3. the **divergence spread** and its shape (TMX → premium-franchise; EEFT → mispricing-flag);
4. the **single swing variable** with its base rate, **visibly tagged asserted (n=0)** until warm;
5. the **NIS** read (receipts vs hand-waving + where the risk relocated) for a turnaround name;
6. the new **SENTINEL zones** armed (asymmetry-zone cross, correlation drift, rebalance band).

That is the moment the book can carry a second, genuinely independent thesis that compounds in the AI-
upside and benign columns — *funding* the concentrated silver bet instead of diluting it — without the
engine pretending to an edge it does not have in conventional equity.

### Risks & mitigations

- **Asserted priors read as earned.** Mitigated by the `asserted`/`data_limited` spine (§8.2) and the
  mandatory tooltip caveat (§9); CALIBRATION flips them only when warm.
- **SOTP data hunger.** Mitigated by the fail-closed fallback + `/confirm`-gated manual segment block
  (§4.3); the band widens and conviction drops when splits are thin — visibly.
- **Scope creep into an equities-alpha engine.** Mitigated by the lane guard (§4.4) and the third
  invariant (§0): conventional names get valuation + monitoring only, never SCOUT or per-name COUNCIL.
- **Spread confusion (method vs divergence).** Mitigated by keeping both in the schema with distinct
  keys + glossary entries (§5.3) — the house "two-distinct-things" discipline.
- **A "ballast" silently de-diversifying.** Mitigated by `correlation_drift` (trend) firing before the
  static `ballast_correlated` level (§3.2, §6.2).
- **Regime double-count.** Mitigated by the one-leg-per-archetype tilt (§4.1) and the rule that the
  valuation never re-conditions on scenario weights (§2).
- **Reverse-DCF false precision.** The implied-growth solve is reported as a *range vs. a base-rate
  band*, never a point; the ribbon carries the uncertainty, and the swing variable names the
  assumption explicitly.
