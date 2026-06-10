# Validation Flywheel — build plan (2026-06-10)

> **STATUS (2026-06-10): IMPLEMENTED.** All seven phases landed in one pass:
> `valuation_ledger.py` (+ engine-loop hook `_record_valuation_ledger`, decision↔snapshot join in
> `record_decision`, MCP `valuation_snapshot_now`/`valuation_ledger_query`, world-state ledger
> depth) · `price_history.py` + `replay.py` (Mode A grades, PIT coverage, Mode B
> `recompute_blend`/`counterfactual`, `ledger_priors` → the two new `base_rates` engineering
> priors, MCP `replay_grade`, `valuation_track` on the calibration scorecard) · `uncertainty.py`
> (P10/P50/P90 wired into `_confidence_ribbon` + conviction-lift precision scaling; tunables under
> `v5_config → conviction_mode.uncertainty`) · `cross_check.py` + research-cache restatement
> history/`as_at` · `peer_normalization` outliers/dispersion/leave-one-out + `comp_audit` (the
> empirical market-leg σ, fed to the spear's ribbon) + `data/peer_set.json` + story-card
> `method_spread` · `discovery_screen.py` + `data/candidate_universe.json` + scout.md re-point
> (MCP `discovery_screen`) · `scout_candidate`/`graduation` memory types + MCP
> `graduate_candidate` (refuses without receipts) + `sweep_scout_outcomes` →
> `calibration.scout_scorecard`. Tests: `test_valuation_ledger` · `test_replay` ·
> `test_uncertainty` · `test_cross_check` · `test_discovery_screen` · `test_flywheel_phase7`
> (62 new, all green; full suite 600 passed with only the pre-existing environmental failures).
> Deferred, per plan: the yfinance price-history backfill (run `price_history.backfill_from_yahoo`
> once in the live environment) and the Sentinel `data_conflict` surface (cross_check returns the
> structured conflicts; wiring them into `sentinel.py` rides with the next sentinel pass).

The keystone build: convert the cockpit from a *coherent-opinion generator* into a
*self-correcting, track-recorded apparatus*. This plan is written against the actual code as of
`claude/wonderful-gauss-93ouhc` (post-scrutiny-hardening, post-audit-batches-1-4), from first
principles, with every extension point named.

---

## 0. First principles — what "validated" means here

The criticism being answered: *"you rated the apparatus, not the alpha — show me the alpha."*
The June scrutiny pass (`docs/FORGE_SCRUTINY_FIRST_PRINCIPLES.md`) closed the measurement gaps in
the **calibration loop** — path/ruin, decision-quality-vs-luck, small-n honesty, the capture spine
(freeze → sweep → consume). All eight angles closed. But the loop only grades **decisions**
(verdict + frozen ρ/φ + price). The **valuations themselves** — intrinsic, the ladder, the REP
floor, the band, the inputs they rested on — are never stamped point-in-time, so they can never be
graded. A decision can be scored "win"; the *model that priced it* still has no track record.

From first principles, a valuation apparatus is validated when it can answer four questions with
receipts:

1. **What did you say, exactly, and when?** — point-in-time, immutable, input-attributed output.
   (Today: lost. The engine recomputes every ~60s and keeps nothing.)
2. **Did reality move toward what you said?** — intrinsic→price convergence at fixed horizons,
   graded only from what was knowable at the stamp.
3. **Did your stated uncertainty mean anything?** — band calibration: when you claimed a range,
   did outcomes land in it at the claimed rate? (Today: the ribbon is a heuristic ±, so this
   question isn't even well-posed yet.)
4. **Does grading change the model?** — results flow back into priors (`base_rates.py`) and
   tunables (via the human `/confirm` gate), per archetype. A flywheel, not a report card.

Everything below serves those four questions. Items 1–2 of the sequencing are the unlock: they
cost no data budget and make every subsequent day of operation accumulate gradeable history —
which is why they go first even though the statistical verdict takes months to mature. **The
apparatus must exist before the track record can.**

### The honest constraint, stated up front

The book is 4 names. No replay harness makes n=4 statistically decisive in a quarter. The design
response (already house style — `reliability.data_limited`, CI-only-when-warm in
`calibration.scorecard`) is: build the measurement now, report it with small-n honesty, and let it
warm. What we can validate *immediately* is structural: band coverage events, floor-hold events,
input-restatement events, method-dispersion — these accrue per-name-per-horizon and across the
scout watchlist (Phase 6–7 widens n considerably). What matures slowly is convergence expectancy.
Say so on the scorecard; never print a bare point at n=3.

---

## 1. Current state — what exists, what's missing (the precise gap)

| Capability | Where | Status |
|---|---|---|
| Append-only, flock-guarded, supersede-never-overwrite JSONL | `living_memory.py` → `data/living_memory.jsonl` | ✅ the pattern to clone |
| Decision freeze (verdict, price, legs, frozen ρ/φ, Goodhart guard) | `calibration.decision_from_rating`, `freeze_decision_if_new`, `sweep_outcomes`, `backfill_decisions` | ✅ grades *decisions*, not valuations |
| Druckenmiller scorecard + path/ruin + decision-quality + reliability | `calibration.scorecard` | ✅ |
| Per-archetype priors with provenance + Bayesian update | `base_rates.py` (`estimate`, `update_beta`, `forward_to_production`) | ✅ has nothing feeding it from realized valuations |
| Input provenance: `{value, source, as_of, confidence, fetched_at}` | `research_cache.py` → `data/research_cache.json` | ✅ but **`set()` overwrites in place — no history** (`research_cache.py:56`) |
| Confidence ribbon | `asymmetry_rating._confidence_ribbon` (:575) | ⚠️ heuristic ±: base-by-data-quality + 0.5×scenario-spread + stale-NAV widen, clamp 2.5. Not a quantile; can't be coverage-graded |
| Ladder (floor/bear/base/bull) | `asymmetry_rating.compute_asymmetry_rating` (:718) | ⚠️ scenario legs, not probability quantiles |
| Triangulation legs (cost/market/income) + confidence-tilted blend | `archetypes.py` (pure-Python leg replicas), `v5_config.triangulation` | ✅ computed, but **collapsed to one number**; per-method spread never surfaced |
| Peer comp | `peer_normalization.blended_peer_ev_oz` | ⚠️ per-peer contributions returned, but no inclusion criteria, no outlier handling, no persisted auditable peer file |
| Eval cycle | `engine.evaluate_master_architecture` (~60s FastAPI loop) → per-name `{ladder, asymmetry, gate, directive, conviction}` | ✅ the hook point. Output discarded every cycle |
| Discovery | `@scout` (web-search-led) + slot taxonomy in `scout.md`, `council.slot_gate` at `/rotate` | ⚠️ no quantitative screen, no maintained universe, no grading of scout output |
| Disconfirmation | `@verifier`, `@anti-scout` | ✅ exist; not a *mandatory, logged* graduation gate |
| Historical prices | `market_data` / yfinance / FMP `chart` | ⚠️ live quotes wired; no cached daily-close history store |

**The one-sentence gap:** the engine's output is ephemeral and its uncertainty is a heuristic, so
questions 1–3 above are currently unanswerable; everything else in the stack is ready to consume
the answers.

---

## 2. Design constraints (house rules that bind every phase)

- **Engine is the single source of math truth.** The ledger *records* engine output; it never
  recomputes it on the write path. Replay re-runs engine code on frozen payloads — never a
  parallel model.
- **Append-only, supersede-never-overwrite.** Same discipline as `living_memory` (audit invariant
  #3). Restatements are new records pointing at old ones.
- **Goodhart guard extends.** Ledger snapshots are produced by the engine loop, never accepted
  from an agent payload (same rule as `decision_from_rating`'s legs guard, `GoodhartGuardTests`).
- **Fail-closed.** Absent/stale/conflicting input → wider band → lower conviction, visibly. Never
  a fake default (already the `research_cache` contract — this plan wires it end-to-end).
- **Human gate on tunables.** Replay-derived parameter changes route through
  `propose_param_change` → `/confirm`, with receipts. The flywheel proposes; the operator turns it.
- **No regime double-count.** The V4 flag stands (`docs/BACKLOG_ASSESSMENT_2026-06-10.md`): do not
  regime-condition the peer multiple — the archetype layer already applies `regime_multiplier` to
  the tilt leg.
- **Small-n honesty.** Every new scorecard surface inherits the `reliability` pattern: explicit
  `data_limited`, intervals only when warm, suppressed ratios below thresholds.
- **Stdlib only** for the new core modules (house norm: `base_rates`, `research_cache`,
  `living_memory` are all stdlib; replay/MC must be too — `random.Random(seed)`, no numpy).

---

## 3. Phase 1 — `valuation_ledger.py` (the keystone)

**What:** every name's full valuation state, stamped point-in-time, append-only.

### 3.1 Storage & schema

New module `valuation_ledger.py` → `data/valuation_ledger.jsonl`. Clone `living_memory`'s write
mechanics (O_APPEND + POSIX flock, torn-line tolerance, mtime-invalidated read cache) but keep it
a **separate file**: living_memory is the human/agent research stream and loads fully into RAM on
query; machine-cadence snapshots would pollute its recall and bloat every `memory_query`. Cross-
link by ID instead (see 3.3).

One record per name per snapshot, `schema_version: 1`:

```jsonc
{
  "id": "20260610-210503-a1b2c3", "ts": "...Z", "ticker": "AGA.V", "schema_version": 1,
  "trigger": "daily" | "material_change" | "decision" | "manual",
  "price": 0.61,
  "intrinsic": 1.18,
  "ladder": {"floor": 0.52, "bear": 0.48, "base": 1.05, "bull": 2.10},
  "asymmetry": {"rho": 3.1, "phi": 0.85},
  "rating": 7.8, "band": "STRONG ASYMMETRY", "directive": "…",
  "pillars": {"T": …, "Q": …, "V": …},
  "gate": {"cap": 10.0, "reason": "clean"},
  "ribbon": {"plus_minus": 0.9, "quality": "full"},          // Phase 3 adds p10/p50/p90
  "legs": {"cost": …, "market": …, "income": …, "weights": {…}, "confidences": {…}},
  "rep_floor": {"cash_treasury_m": …, "stressed_resource_per_oz": …, "conservatism_scalar": …},
  "inputs": {                                                  // swing inputs, frozen
    "in_ground_ageq_oz_indicated": {"value": …, "as_of": "…", "confidence": "high", "source_sha1": "…", "age_days": 312},
    "aisc_per_oz": {…}, "shares_out": {…}, "peer_ev_oz_blend": {…}
  },
  "peer_set_hash": "…", "config_hash": "…", "engine_git_sha": "…",
  "regime": {"mri": …, "posture": "…", "net_tilt": …, "real_yield": …, "dxy": …}
}
```

Notes:
- `inputs` is copied **by value** from `research_cache.provenance(ticker)` (swing fields only,
  per-archetype list) — so a later cache restatement can never rewrite what this valuation rested
  on. This is the point-in-time spine.
- `config_hash` = sha1 of the effective config (file + confirmed overrides); `engine_git_sha`
  from `git rev-parse` cached at engine start. Both needed for honest replay (Phase 2 Mode B).
- Size sanity: 4 names × ~2–3 records/day × ~1.5 KB ≈ **<7 MB/year**. No rotation needed for
  years; add year-suffix rotation only if the universe (Phase 6) grows it 50×.

### 3.2 Cadence — when to write (not every 60s cycle)

`valuation_ledger.maybe_record(state_for_name, inputs, regime, ...)` writes when:
1. **Daily mark** — first eval after UTC date roll (one guaranteed gradeable point/day/name).
2. **Material change** — fingerprint = sha1 of (intrinsic rounded to ribbon precision, band,
   directive, `gate.cap`, input fingerprint) differs from the last record for that name. Catches
   restatements, directive flips, gate events between daily marks.
3. **Decision freeze** — `freeze_decision_if_new` (in `valuation_actions.py`) additionally
   triggers a snapshot and stores the snapshot `id` in the decision's meta (and the snapshot
   carries `trigger: "decision"`). Every graded decision now joins to the *full* valuation state
   that produced it, not just legs+ρ/φ.
4. **Manual** — new MCP tool `valuation_snapshot_now(ticker="")`.

### 3.3 Wiring

- **Hook:** the FastAPI service loop in `engine.py`, immediately after
  `evaluate_master_architecture()` returns — one call, behind a try/except that can never break
  the eval cycle (record-or-log, never raise; same contract as sentinel's "evaluation never
  raises").
- **Module purity:** `valuation_ledger.py` takes plain dicts; zero engine imports. Unit-testable
  with a temp JSONL exactly like `tests/test_living_memory.py`.
- **MCP tools** (`mcp_server/core.py`): `valuation_ledger_query(ticker, since, limit)` and
  `valuation_snapshot_now`. `get_world_state` gains a one-line "ledger depth" stat (records,
  span, names) so the operator sees history accruing.
- **Seed:** on first run, snapshot the live book immediately (`trigger: "manual"`, tagged seed) —
  day 1 of the track record starts the day this merges.

### 3.4 Tests / acceptance

- `tests/test_valuation_ledger.py`: append-only (no mutation path), dedup fingerprint (same state
  twice → one record), date-roll trigger, decision-trigger joins (decision meta carries snapshot
  id), torn-line tolerance, multiprocess flock (clone the living_memory test).
- Acceptance: after a simulated day of eval cycles (stubbed state), the ledger holds exactly the
  expected records; a research_cache restatement *after* a snapshot does not alter the snapshot's
  `inputs`.

**Effort: M. Data spend: none.**

---## 4. Phase 2 — replay & grading harness (`replay.py`)

**What:** "given only what was stamped at T, what did the model say, and what happened over the
next N days?" Two modes, four grades, one feedback path.

### 4.1 Ground truth: a daily-close history store

Prerequisite shared with Phase 7: `price_history.py` → `data/price_history.json` —
`{ticker: {"YYYY-MM-DD": close}}`, appended daily by the existing ingestion path (yfinance batch
for the book; FMP `chart` as fallback within the budget envelope, with the B3 staleness
discipline). Backfill 2 years once at build time for the 4 holdings. Grading reads **only** this
store — never a live quote — so replays are reproducible.

### 4.2 Mode A — as-stamped grading (no engine re-run)

For each ledger record at T and horizon N ∈ {30, 90, 180}:

| Grade | Definition | Question it answers |
|---|---|---|
| **Convergence** | sign-agreement of `(intrinsic − price)/price` vs realized return, plus *gap-closure*: `(|gap_T| − |gap_{T+N}|) / |gap_T|` | did price move toward intrinsic? |
| **Band coverage** | did the realized price land inside the claimed band? (Phase 1: ladder `[floor, bull]`; Phase 3: P10–P90 — the real PIT test) | does stated uncertainty mean anything? |
| **Floor reliability** | `min(close)` over the window vs the stamped REP floor — held / broke, and by how much | is the margin-of-safety floor real? |
| **Directive expectancy** | join to the existing `calibration.score_outcome` via the decision↔snapshot link (3.2.3) — no duplicate machinery | already built; now input-attributed |

Output: `replay.grade_ledger(horizon_days)` → per-name and per-archetype grade lists →
`replay.report()` reusing the `scorecard` shape (`reliability` block mandatory: convergence
expectancy suppressed below n thresholds; *event counts* — floor-holds, coverage hits — always
shown, since counts don't lie at small n).

### 4.3 Mode B — counterfactual replay (re-run frozen inputs)

`PolymorphicRouter.get_valuation(ticker, data_payload)` is already payload-driven and
`archetypes.py` carries pure-Python leg replicas — so a replay can reconstruct the payload from a
snapshot's `inputs` + `regime` + config (by `config_hash`) and recompute **with today's code**.
Two uses:

1. **Golden-ledger regression** — a test asserting that current code reproduces a pinned set of
   historical snapshots within ribbon tolerance. Code changes can no longer silently rewrite what
   the model "would have said" — the engine's own audit found exactly this class of drift
   (mos_ledger / REP-floor reconcile in batch 1-4); this institutionalizes the defense.
2. **Evidence engine for `/confirm`** — "would `conservatism_scalar = 0.90` have graded better
   over the whole ledger?" Replay under the candidate param, diff the grades, attach the table to
   `propose_param_change`. This is Idea 2 ④ (ROADMAP) finally given its receipts mechanism.

### 4.4 Feedback into priors

- `base_rates.py` gains ledger-fed posteriors via the existing `update_beta`: per archetype,
  `floor_reliability` (floor-held / floor-tested) and `band_coverage` Betas. Cold-start from the
  engineering prior, sourced + confidence-graded like every other prior in the registry.
- `calibration.brief_prior` → `world_state.render_brief` surfaces the headline ("REP floors:
  held 7/8 tests across the ledger; band coverage 71% vs 80% claimed — bands too narrow") — the
  same consumption spine the capture loop already uses, so every Council seat inherits it free.

### 4.5 Tests / acceptance

- Synthetic ledger + synthetic price paths with known answers (converging, diverging,
  floor-breaking) → grades must match hand-computed values.
- Golden-ledger regression test with 2–3 pinned snapshots.
- Acceptance: `/journal` (the `@calibration` agent) reports the valuation grades beside the
  decision grades, with `data_limited` honesty intact.

**Effort: M. Data spend: none (yfinance backfill is free).**

---

## 5. Phase 3 — distributional intrinsic (P10/P50/P90)

**What:** replace the heuristic ribbon with propagated input uncertainty, fail-closed.

### 5.1 Two bands, kept distinct (precision vs scenarios)

- The **estimate band** (new): "how precisely do we know intrinsic, given input quality?" This is
  what P10/P50/P90 means here, what the ribbon becomes, and what Phase 2's coverage test grades
  against convergence.
- The **scenario ladder** (existing bear/base/bull legs): "what is it worth *if* the bull case
  happens?" These stay scenario legs — they are theses, not quantiles, and `ladder_expectation()`
  (V2) already handles their probability-weighting honestly. Do not conflate the two; the doc and
  glossary entries must name the distinction (`ASYMMETRY_GLOSSARY["ribbon"]` rewrite).

### 5.2 Mechanics

New `uncertainty.py` (stdlib): a light Monte Carlo (~2,000 draws, `random.Random(seed)` —
deterministic, replayable) through the **pure leg replicas in `archetypes.py`** (this is the seam
that makes MC cheap — no async engine in the loop). Swing inputs per archetype:

| Archetype | Sampled inputs |
|---|---|
| option_convexity (spear) | M&I vs inferred ounce mix (`effective_oz` weights), AISC, **peer EV/oz — empirical dispersion across the Phase-5 peer set, not an assumed σ**, shares_out (financing overhang) |
| asset_light_yield / ballast | NAV inputs (`nav_inventory` fields), spot mark (staleness-widened per `nav_mark` tier), discount rate |
| project-generator holdco | sum-of-parts component values at their individual confidences |

Input σ map, a confirmable tunable block in `v5_config.json` (routed via `/confirm`):

```jsonc
"uncertainty": {
  "confidence_sigma_rel": {"high": 0.10, "med": 0.25, "low": 0.50},
  "staleness_widen_halflife_days": 180,   // sigma *= 1 + age_days/halflife (capped)
  "absent_input": "fail_closed",          // missing field -> low-confidence treatment + flag (existing contract)
  "n_draws": 2000, "seed": 47
}
```

Output per name: `{"p10": …, "p50": …, "p90": …, "drivers": [{"input": "peer_ev_oz", "share": 0.61}, …]}`
— variance attribution by one-at-a-time re-simulation, so the Story Card can say *"the width is
61% peer-comp dispersion"* (which is itself the argument for Phase 5).

### 5.3 Wiring (fail-closed, end-to-end)

- `_confidence_ribbon` keeps its dict shape (`plus_minus`, `quality`) for every existing consumer,
  but the producer becomes the quantile band: `plus_minus = (p90 − p10) / (2·p50)`-scaled, with
  `p10/p50/p90/drivers` added. The stale-NAV widen and data-quality base survive as inputs to the
  σ map rather than ad-hoc adders.
- Conviction: the V pillar's support/confidence already feeds `conviction_lift` — wire band width
  in so **wider band ⇒ smaller lift ⇒ lower rating**, mechanically. Stale/low-confidence inputs
  now *automatically* shrink conviction. This is the "data confidence → valuation confidence is a
  wired pathway, not a vibe" requirement.
- Ledger: snapshots record the quantiles + drivers (Phase 2's coverage grading upgrades from
  `[floor, bull]` to P10–P90 — the honest PIT test: claimed 80% containment, measured containment,
  and a `/confirm` proposal when they diverge persistently).

### 5.4 Tests / acceptance

- Determinism (same seed → same quantiles); monotonicity (downgrade an input high→low ⇒ band
  strictly widens ⇒ rating non-increasing — the fail-closed property as an executable test);
  absent-input flag; driver shares sum ≈ 1.
- Acceptance: the dashboard ribbon and Story Card show P10/P50/P90 + top driver; no consumer of
  the old ribbon shape breaks (`tests/test_asymmetry_rating.py` extended, not rewritten).

**Effort: M. Data spend: none.**

---

## 6. Phase 4 — second-source cross-check + point-in-time enforcement

**What:** the retail-data defense — two sources or a visible flag, and history that can't be
silently rewritten.

1. **`cross_check.py`** — for fields a market API can independently supply (shares_out, cash,
   debt, market cap): compare `research_cache` (filings-derived) vs FMP `statements`/profile
   (already wired, budget-capped). Relative disagreement > threshold (default 10%, tunable) ⇒
   **flag, never average**: write a `data_conflict` note onto the field (research_cache `note`),
   demote its effective confidence to `"low"` (which, via Phase 3, mechanically widens the band
   and shrinks conviction), surface in the DATA & TRUST panel and the Sentinel sweep
   (`sentinel.py` gains a `data_conflict` check beside runway/integrity). Run inside the existing
   ingestion cadence — no new loop.
2. **research_cache becomes restatement-proof** — `set()` currently overwrites in place
   (`research_cache.py:56`). Change: before overwrite, append the prior entry to a per-field
   `history` list (bounded, oldest-first), and add `as_at(ticker, field, date)` for
   reconstruction. The ledger's by-value `inputs` copies (Phase 1) already protect stamped
   valuations; this closes the remaining hole — the *cache itself* becomes auditable, and a
   restatement event is detectable (and worth a ledger `material_change` snapshot + a
   memory note, because a big restatement is *signal*).
3. **Paid-tier discipline (optional, later):** if one paid source is ever bought, it goes to the
   spear's resource/AISC/filings inputs only — the Phase 3 driver attribution will *show* that's
   where the width lives; spend where the variance is.

**Tests:** disagreement → flag-not-average; restatement → history preserved + `as_at` correct;
conviction visibly drops on a planted conflict (end-to-end fail-closed test).

**Effort: S–M. Data spend: ~free.**

---

## 7. Phase 5 — auditable peer set + ensemble triangulation

**What:** the biggest single swing factor (peer EV/oz) made inspectable; one-method risk killed.

1. **`data/peer_set.json`** — per peer: ticker, stage, jurisdiction, commodity mix, resource oz,
   EV, as_of, source URL, confidence — plus an explicit `inclusion_criteria` block (stage window,
   jurisdiction tiers, commodity, size band) so membership is reproducible, and an exclusion log
   (who was dropped and why). Maintained via research_cache-style provenance discipline.
2. **`peer_normalization.py` extensions** (the per-peer contribution surface already exists in
   `blended_peer_ev_oz`): median + MAD outlier handling (outliers *flagged and down-weighted*,
   never silently dropped), leave-one-out sensitivity (name the max-swing peer: "the comp moves
   −18% without PeerX"), and **export the cross-peer dispersion** — which becomes the market-leg σ
   in Phase 3's MC (an *empirical* σ replacing an assumed one; the two phases interlock).
3. **Ensemble surfacing** — the legs (cost / market / income, per `v5_config.triangulation`) are
   already 2–3 independent methods, but they're collapsed into one confidence-tilted number.
   Surface each method's standalone valuation + a `method_spread` stat on the Story Card and in
   the ledger snapshot. Tight cluster ⇒ trust; wide spread ⇒ flag + widen the band (a second,
   structural input to the ribbon beside input-σ). For the spear add the market-implied check
   (what EV/oz is the market paying *today* vs the peer curve — the option-implied leg V3 remains
   deferred per the backlog, pending the operator's sign-off on model form).
4. **Guardrail restated:** no regime-conditioning of the multiple (V4 flag — the tilt leg already
   carries the regime once).

**Tests:** inclusion-criteria filter reproducibility; outlier flag; leave-one-out math;
`method_spread` widens ribbon monotonically.

**Effort: M. Data spend: none beyond existing peer sourcing.**

---

## 8. Phase 6 — systematic discovery (screen first, web second)

**What:** discovery becomes a reproducible quantitative screen over a maintained universe;
`@scout`'s web search *enriches survivors* instead of being the discovery.

1. **`data/candidate_universe.json`** — the maintained universe (seeded from prior scout runs,
   exchange/sector lists, peer-set members): ticker, name, slot tags, stage, jurisdiction,
   commodity, mcap, last_review, provenance. Grows over time; staleness-dated like everything else.
2. **`discovery_screen.py`** — hard gates **in order**, each with a logged kill reason
   (auditable: "rejected at gate 3: Fraser tier"):
   1. **Slot-fit** (the mandated first screen — same four-slot taxonomy as `council.slot_gate`
      and `scout.md`, now applied to discovery, not just rotation);
   2. stage window (per slot);
   3. jurisdiction (Fraser tiers via the `technical_quality` factor machinery);
   4. market-cap band;
   5. cash runway + dilution history (the existing JSF / death-spiral machinery — forensic
      snapshot where held, FMP statements for non-holdings, budget-aware);
   6. REP-floor coverage estimate (coarse: cash + stressed in-ground value vs EV).
3. **Base-rate anchor on every survivor** — `candidate_anchor(archetype, stage, commodity)` is
   already stage-chained (T3 fix); attach it to each survivor record so every candidate carries an
   outside-view prior before any narrative ("PEA-stage Ag juniors: ~9–43% reach production
   depending on stage; trade-payoff floor via takeout premium ≈ 35%").
4. **`@scout` re-pointed** — `scout.md` updated: the brief starts from the screen's survivor list
   (`discovery_screen` exposed as an MCP tool), web search fills catalysts/management/story on
   survivors. The shortlist output keeps the existing `slot:` tag contract (D2).

**Tests:** gate ordering + kill log; a fixture universe with known pass/fail names; anchor
attachment.

**Effort: M. Data spend: small (FMP statements for screening calls, inside the budget cap).**

---

## 9. Phase 7 — mandatory disconfirmation gate + grade the scout

**What:** nothing graduates un-disconfirmed; and discovery itself gets a track record (the same
medicine as Phases 1–2, applied to scouting).

1. **Graduation gate** — new Living Memory entry types (extend `ENTRY_TYPES`):
   - `scout_candidate`: frozen at surfacing — price, slot, stage, base-rate anchor, screen-gate
     trail. Written by `@scout`/pipeline for **every** shortlisted name, graduated or not.
   - `graduation`: requires `refs` to (a) a `@verifier` verdict, (b) an `@anti-scout` sweep
     (CLEAN is valid and recorded — D5 contract), (c) the forensic/JSF result. Enforced in a new
     MCP tool `graduate_candidate(ticker)` that **refuses** without all three refs — enforcement
     at the MCP layer, deliberately not inside the 6.8k-line TUI (the D3 deferral stands; the TUI
     watchlist add can call the tool when the split happens).
2. **Scout calibration** — a decaying watch over all `scout_candidate` entries using the Phase-4.1
   price store, swept by the existing `sweep_outcomes` cadence at 90/180d: did surfaced names
   deliver the asymmetry the anchor implied? Did *rejected* names outperform (regret — the
   graveyard discipline `thesis_ledger.graveyard()` already applies to theses, extended to
   scouting)? `calibration_scorecard` gains a `scout` section per regime/archetype: **hit-rate is
   allowed to headline here** — for *discovery* (a funnel), frequency is the right objective,
   unlike the book (expectancy); say so in the section header so the demotion rule isn't
   misread.
3. This is also what fixes the small-n problem upstream: the scout watch adds tens of
   gradeable names per year against the book's four.

**Tests:** graduation refusal without refs; scout sweep grades a fixture watchlist; regret
tracking on a planted rejected-winner.

**Effort: S (the agents and sweep machinery exist). Data spend: none.**

---

## 10. Sequencing, dependencies, definition of done

| # | Build | Solves | Depends on | Effort | Data spend |
|---|---|---|---|---|---|
| 1 | `valuation_ledger.py` + engine-loop hook + MCP tools | "unvalidated" — the record exists | — | M | none |
| 2 | `price_history.py` + `replay.py` (Mode A grades, Mode B golden-ledger + `/confirm` evidence) + base-rate feedback | the track record + regression-proof history | 1 | M | none |
| 3 | `uncertainty.py` P10/50/90 + ribbon/conviction wiring | "don't trust the numbers" — stated, graded uncertainty | 1 (to be graded: 2) | M | none |
| 4 | `cross_check.py` + research_cache history/`as_at` | retail-data risk; restatement-proof inputs | best with 3 (conflict ⇒ wider band) | S–M | ~free |
| 5 | `data/peer_set.json` + peer_normalization extensions + ensemble surfacing | biggest swing factor; single-method risk | 3 (feeds σ), 1 (recorded) | M | none |
| 6 | `data/candidate_universe.json` + `discovery_screen.py` + scout re-point | vibes-discovery | — (parallel-safe) | M | small |
| 7 | graduation gate + scout calibration | discovery validation; widens gradeable n | 2 (price store), 6 | S | none |

**Order of work: 1 → 2 → 3, then 4–5 and 6–7 as two parallel tracks.** Items 1–3 are the unlock
and cost no data budget; everything later both *consumes* them (peer dispersion → σ; screen
survivors → scout_candidates → sweep) and *feeds* them (wider gradeable n).

**Definition of done for the keystone (items 1–2):** the operator can ask `/journal` and get,
beside the decision scorecard: ledger depth, convergence grades (with `data_limited` honesty),
band-coverage and floor-reliability event counts per archetype, and at least one replay-evidenced
`/confirm` proposal pathway demonstrated end-to-end on synthetic data. That is the moment the
criticism flips from "you can't trust it" to "here is its calibrated track record, accruing daily,
and it tells you its own confidence."

### Risks & mitigations

- **Slow statistical maturity (n=4):** named in §0; mitigated by event-count reporting, the scout
  watch (Phase 7) widening n, and `reliability`-pattern honesty everywhere.
- **Ledger pollution of the eval loop:** the hook is try/except-fenced, write-or-log; cadence
  rules cap volume; tested for the never-raises contract.
- **Replay anachronism (using today's knowledge to grade yesterday):** grading reads only
  snapshot-embedded inputs and the price store; `as_at` + history make even the cache honest;
  golden-ledger test pins it.
- **Goodhart on the new grades:** snapshots are engine-loop-produced only (guard + test, same as
  the legs guard); agents can read the ledger, never write it.
- **Double-counting regime in comps:** V4 flag enforced by a reconciliation test if regime-aware
  comps are ever attempted (per the backlog's stated seam).
