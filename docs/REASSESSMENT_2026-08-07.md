# CommodityEx — Standing Reassessment (2026-08-07)

*A five-task-force sweep under the standing charter, thirty days after the 2026-07-08 sweep and
its execution pass. **The engine was NOT run this session** (offline in this environment; not
authorized) — this is a code/config/data sweep of the committed tree. Method: five parallel deep
scans (one per task force), each briefed to re-grade every 07-08 finding (FIXED / PERSISTS /
PARTIAL / WORSE / MOOT) and audit the ~68 post-07-08 commits from first principles; every headline
finding was independently re-verified by the lead against the tree before shipping. Tags:
**VERIFIED** (lead re-read the code/data), **DELEGATED** (a scan quoted it; the lead did not
independently re-read), **COULD-NOT-VERIFY** (blocker stated). Gate tags are binding: read-only ·
code-behind-tests · propose→confirm · operator-decision. **Session hygiene: nothing was executed
this session beyond this document** — no config, store, code, or tunable change; every gated item
is surfaced, none applied.*

---

## Executive Verdict

The thirty days since 07-08 were the desk's most productive cycle: the gemini lane was genuinely
removed (not defaulted off), the stores stayed tracked and grew, the AGA.V cash was refreshed and
re-sourced, URC.TO was decommissioned honestly ("config-only, never held" — correcting a 07-08
finding), a conventional sleeve (CEG) entered through a purpose-built lane with a frozen
underwriting record, and a wave of well-built new machinery landed (PREDICT desk, forecast ledger,
conviction book, dual-sided valuation, the Fable living-analyst layer, `replay_grade`). And yet
the sweep's four headline findings are all the same story at different layers: **the desk builds
honest machinery faster than it operates it, and in the gaps, silence decides.**

**1. The spear's first real forensic failure passed silently through a gap between two bars
(TF5 — VERIFIED, the sweep headline).** The runway test now fails on *refreshed, sourced* numbers
— no staleness excuse left: `cash_treasury_m 48.0 / monthly_burn_rate 2.75 = 17.45 months`,
below the JSF-internal `runway_min_months: 18.0` bar (`v5_config.json:14,29,996`). The waiver
that would have excused it died fail-closed on 07-16 exactly as designed — still carrying the
verbatim `"PLACEHOLDER — replace with the real basis"` (`v5_config.json:984`) — and **no Memory
entry ever recorded a decision**, despite the desk's own 07-12 note naming the deadline (07-14)
and the fork ("re-base on a real SEDAR+ basis, or lapse and take the JSF dent") in exactly those
terms. But the JSF dent never surfaced: the rating-level forensic gate checks a *different,
three-times-looser* bar — `forensic_gate.min_runway_months: 6.0` (cap 4.5) and
`score_floor: 1.5` (`v5_config.json:782,790` · `asymmetry_rating.py:683-702`) — so a single
failed JSF pillar trips nothing. Verified live: the 2026-08-02 frozen AGA.V decision stamped
`gate {cap: 10.0, reason: "clean"}` (`data/valuation_ledger.jsonl` id `20260802-171347-0892e9`).
The penalty exists (Q-pillar shave, `forensic_penalty≈0.935` on the valuation leg) and is
silently absorbed — no directive change, no band suffix, no flag. The failure the forensic
apparatus was built to catch happened at the desk's largest position, and no surface said so.

**2. The first grades exist — and they are wrong (TF5 — VERIFIED mechanism; magnitudes
DELEGATED from a live read-only run of `replay.grade_ledger`).** The grading loop is warm for
the first time: 3,230 of 3,319 ledger stamps are gradeable at the 30-day horizon. But 07-08
item F (`material_change` hysteresis) never shipped, and the thrash it warned about is now
*proven corrupting rather than hypothetical*: 2,474 of 3,319 rows are GROY `material_change`
stamps [VERIFIED], behind which sit only ~70 distinct floor events — one real GROY floor breach
(2026-07-16) is duplicated **~2,389 times**, collapsing the `floor_reliability` posterior from
an 80% engineering prior to a **0.33% posterior mean** [DELEGATED — recomputed live by the TF5
scan]. The `MIN_N=5` small-n gate (`replay.py:42`) is defeated by construction: duplicates
always clear it. And nothing consumes the output anyway — `replay_grade` is a pure read, no
grade is persisted anywhere, and **no parameter has ever changed as a result of a grade** (the
MRI reweight `0247731` and the goodwill re-source both moved live numbers on zero grades). The
yardstick question from the charter has a precise answer this cycle: *the number has now been
graded once, by this sweep, and the grade is untrustworthy until the ledger stops manufacturing
data points.*

**3. The new surfaces shipped without the honesty rails the old surfaces earned (TF1/TF3/TF4 —
VERIFIED).** The 07-08 sweep named the "letter-not-invariant" fix pattern; this cycle it
recurred at the feature level — five instances, each one a new surface that re-opens a gap the
07-08 execution closed for the old surfaces: (a) the new web glance cockpit renders ratings with
**zero** of the provenance tells (`floor_degraded` / `~proxy` dimming) the TUI rail carries —
the fields ride `/state` and are simply never read (`web/cockpit.html`); (b) `get_world_state` —
the tool CLAUDE.md orders every agent to call first "so you never start blind" — carries **no
data-freshness or degraded-input signal at all** on its online path (zero references in
`world_state.py` [VERIFIED]), and its offline fallback surfaces forecasts-due that the online
path omits — the richer brief exists only when the engine is down; (c) the manifest drift guard
shipped 07-08 to catch new mutating tools is a **prefix snapshot** — `MUTATING_PREFIXES` =
`set_/confirm_/remove_/promote_/demote_/cut_/edit_` (`tests/test_agent_manifest_denylist.py:47`)
— so `add_holding`, `forecast_write`, `watch_update`, `thesis_claim_set`, `predict_fair_value`,
and (registered outside `_PASSTHROUGH_TOOLS` entirely) `record_decision`/`record_conviction`
are invisible to the very guard built to catch exactly this drift; (d) the
`CEX_MCP_READONLY` kill-switch, documented as disabling "all mutating tools entirely"
(`mcp_server/core.py:20`), is not checked by seven of them — `set_nav`, `set_param`,
`confirm_param_change`, `set_barbell_weights`, `cut_holding`, `predict_fair_value`,
`memory_write` [VERIFIED by AST scan] — notably the *older* mutation set, while the newer tools
all check it; (e) `record_decision`/`record_conviction` hard-default `source="user"` and the MCP
wrappers hide the parameter (`mcp_server/server.py:205-219` — the comments say so themselves),
so any subagent's call would enter the calibration flywheel attributed to the operator. Each
mechanism is real; each governs exactly the surfaces that existed when it was written.

**4. Built machinery still never fires, and the loop stops between sessions (TF2/TF4 —
VERIFIED).** Zero `council_verdict` rows exist in the store's entire history [VERIFIED] — the
reconcile law is well-built (`council.py:180-238`), the capture hook that would auto-freeze a
gradeable decision from a verdict sits waiting (`mcp_server/core.py:1314`), and the operator's
own `/council AGA.V` ask on 08-02 died as an ask-note with no verdict. Two of the six coherence
patterns are dead code for the same reason (nothing ever passes `verdicts=`). GROY and GMX.TO
were last contested 06-23 (45 days) — and on 08-02 the engine itself discovered their fair value
is **macro-inert to their own commodity** (gold −15% → intrinsic Δ0.0%; silver-framed
`spot_ref=74.8` on both, a documented unit-mismatch guard whose fix path — metal-framed
`spot_ref` per name — is written in the code's own docstring, `archetypes.py:211-224`
[VERIFIED]) — five days later the finding has no owner and no clock, and the operator's own
skeptical ask ("why is GROY rated 7.2 when its fair value never moves with gold?") sits
unanswered in Memory. The ledger took **8 non-restore rows in six weeks**, all from one 08-02
session; Memory shows two ~18-day dead stretches. Item E (host→repo cadence) is now undecided
across three sweeps. And two clocks are expiring in the open **right now**: forecast P-3 (75%
the 08-06 CEG print reaffirms FY26 guide, resolve-by 2026-08-06) is overdue-unresolved, and the
CEG tranche-2 gate review (claims c1–c4, assessed after the 08-06 call) is due with Memory
silent since 08-02.

**The through-line:** the 07-08 sweep said follow-through was the binding constraint; this sweep
sharpens it — **the binding constraint is that nothing converts silence into a decision.** The
waiver defaulted with the deadline written down. The forecast sits overdue with the contract
written down. The gauge decoupling absorbed a real failure with both thresholds written down.
The cadence question is on its third sweep. In a concentrated book the expensive failure is
false confidence, and this cycle produced the cleanest specimen yet: a rating that printed
"clean" while its own forensic sub-system was failing its own bar.

---

## What changed since 07-08 (verified against the tree)

**Shipped and survived (07-08 execution, re-verified):** all ten code-behind-tests items hold —
the cold-start `INITIAL_BASELINE` seeds (`engine.py:235-261`); the MRI positional-input honesty
scan, which **survived the full MRI reweight** (`engine.py:3742`); the manifest parity test (all
15 manifests, `set_nav`/`set_param` included); `memory_write` provenance clamped at `sourced`;
the PIT validator `pit_violations()` — **live and catching exactly the 3 known GROY seams on
every load** [DELEGATED: TF3 ran it]; headless `--disallowedTools` injection; the day-45
staleness boundary; the φ≥1 proxy-floor directive gate (`asymmetry_rating.py:857-858`); the
book-derived sizer correlation (`engines/sizer.py:203-220`); the UNRATABLE rotation verdict
(`council.py:387-414` — shipped, never yet fired). [VERIFIED except where noted]

**New and good this cycle:** the gemini/agy lane **removed** (code, roster, argv — one doc
comment remains: "subscription cancelled 2026-07", `commodityex_tui.py:6461`) [VERIFIED];
URC.TO decommissioned via `remove_holding` with an honest Memory record — zero config residue
[VERIFIED]; the conventional lane (`add_holding` one-call with dry-plan-then-confirm, CEG
underwritten dual-sided with claims/rules/tranches frozen to Memory *before* the buy, tranche 1
recorded same-day with the fill); `predict_fair_value` genuinely refuses a missing source
(`engine.py:1806-1843`); Kalshi/FMP clients stamped, capped, and degrade loudly; the Data
Freshness panel computes real per-feed ages (`engine.py:3611-3672`); `_valuation_integrity`
(19366e2) is a **genuine invariant fix, not a letter fix** — universal dead-leg/single-driver
detection with directive suspension on a degraded valuation [DELEGATED]; the Fable F1–F3 layer
(`coherence_check.py`, `conclusion_decay.py`) keeps a clean deterministic boundary — pure
functions, flag-never-mutate; the PREDICT desk leads with the verdict and nets fees/FX honestly;
`forecast_ledger.py` maps verbal confidence explicitly and never silently; the run-tag hand-off
has real code support and real production use (`pl:`/`cw:` tags in the store). [DELEGATED
unless marked]

**Not decided (07-08 surfaced items A–G):** A (waiver) — **defaulted, worst outcome**; B (burn
refresh) — cash half done, burn half open, the Q-ended 2026-04-30 MD&A named as the trigger was
apparently never checked; C (GROY cache re-write + $1B-rejection backfill) — open; D (uranium
second source) — MOOT by decommission; E (store cadence) — open, third sweep; F (grading
readiness) — partially overtaken: grading runs but on corrupted input; G (batch:
`survival_exempt_archetypes`, FRED label, hysteresis, `set_nav` routing) — all open. [VERIFIED]

---

## TF1 — Signal & Communication

**(a) First principles.** Every rendered number carries its own confidence; every state mutation
passes a *mechanical* human gate. This sweep's corollary: **a guard that enumerates its subjects
by name governs only the past** — a prefix-list drift guard, a kill-switch that misses seven
tools, and a provenance rail the newest surface doesn't read are all the same defect: the
honesty rails don't propagate to new surfaces by construction, only by memory.

**(b) Hard questions.** What is a kill-switch worth if seven of its subjects don't know it
exists? Why does `confirm_param_change` still POST no `source` — a full audit cycle after the
guard that would refuse it was verified correct (`engine_api.py:215-222` · the unit test proves
the guard works; the only real caller never identifies itself)? Why did `add_holding` — which
writes book membership to `v5_config.json` directly, gated by a self-set `confirm=true` boolean
— not inherit the deny-list treatment of its sibling `remove_holding`? How many audits does the
directive enum refactor need (this is the fourth)? Is it intentional that the *offline* world
state is richer than the online one?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | Endpoint guard inert on the MCP path (`confirm_param_change` posts no `source`; defaults `"cockpit"`; guard admits) | `mcp_server/core.py:794-799` · `engine_api.py:215-222` | PERSISTS unchanged | VERIFIED |
| 2 | Provenance tells: TUI rail FIXED and holds; **web glance cockpit renders none of them** though the fields ride `/state` | `cockpit_widgets.py:441-445` vs `web/cockpit.html` (zero hits) | REGRESSED on the newest surface | VERIFIED |
| 3 | Directive prose keyword-parsed; 0.50 fallback; now a **third** 0.50 collision (`DEGRADED VALUATION`) joins FAIR-VALUE and unknown; `tail[:5]` chip garbage | `council.py:36-57,109-114` · `cockpit_widgets.py:294-312` | PERSISTS (4th audit) | VERIFIED (lead spot-checked the pattern; line detail DELEGATED) |
| 4 | `CEX_MCP_READONLY` documented "disables all mutating tools"; not checked by `set_nav`/`set_param`/`confirm_param_change`/`set_barbell_weights`/`cut_holding`/`predict_fair_value`/`memory_write` | `mcp_server/core.py:20,53` + per-function AST scan | NEW | VERIFIED |
| 5 | `add_holding` writes config directly, self-set `confirm` boolean, in no deny-list, invisible to the drift guard | `mcp_server/core.py:1062-1173` | NEW | VERIFIED |
| 6 | Drift guard is a prefix snapshot — `add_/forecast_/watch_/thesis_/predict_/record_` shapes invisible | `tests/test_agent_manifest_denylist.py:47` | NEW (the exact pattern-gap the 07-08 fix warned about) | VERIFIED |
| 7 | `get_world_state` online path: no freshness, no forecast-due; offline fallback has both | `world_state.py` (0 refs) · `mcp_server/core.py:3245-3353` | NEW | VERIFIED |
| 8 | `set_nav` HTTP endpoint: no `_write_source_ok`, any-URL source (main-session half of 07-08 item G) | `engine_api.py:307-334` · `mcp_server/core.py:751-772` | PERSISTS (3rd cycle) | VERIFIED |
| 9 | Colour band flips on 0.01 wobble; router first-match, no did-you-mean; collapsed council strip seeds verdict slot with raw directive; "— not sourced" ambiguous render; `survival_exempt_archetypes` config/code drift unasserted | `conviction_health.py:23-52` · `cockpit_widgets.py:809` · `commodityex_tui.py:7154` · `:682,688` · `v5_config.json:797-799` | PERSISTS unchanged (batch) | DELEGATED |
| 10 | Positives: PREDICT desk verdict-first and fee-honest; Data Freshness panel real; `/action/ask` honestly scoped (records, never mutates; localhost-only) | `predict_arb_monitor.py:20-60` · `engine.py:3611-3672` · `engine_api.py:126-155` | NEW (good) | DELEGATED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| `confirm_param_change` passes `source="mcp:confirm_param_change"`; registration-loop assertion pairs every passthrough with an endpoint source-check or documented proposal-gate | **ADOPT** — would have caught strains 4/5 by construction | code-behind-tests |
| Widen the drift guard from prefixes to shape (`add_/write_/record_/resolve_/update_` + registration-visibility for tools outside `_PASSTHROUGH_TOOLS`); deny `add_holding` everywhere `remove_holding` is denied | **ADOPT** | code-behind-tests |
| `CEX_MCP_READONLY`: wire into the seven gap-tools (or correct the docstring — only one option is honest) | **ADOPT** | code-behind-tests |
| `set_nav` main-session gate via `/config/propose` | **ADOPT** (carried 3rd time) | code + operator-decision |
| Directive → `(code, display_text)` enum; kills three 0.50 collisions + `tail[:5]` | **ADOPT** (4th audit) | code-behind-tests |
| Web cockpit provenance parity (`floor_degraded`/`~proxy` into `renderBook()`) | **ADOPT** — before this becomes the primary glance surface | code-behind-tests |
| `world_state.build()` online parity: `data_freshness.any_stale` + forecast-due count | **ADOPT** | code-behind-tests |
| Display pilot batch (router reorder, colour hysteresis, strip label, "— not sourced" split) | **PILOT** | read-only display |

**(e) Next steps.** 1) Source-identify + registration assertion. 2) Drift-guard shape-widening +
`add_holding` deny. 3) READONLY honesty. 4) Directive enum. 5) Web + world-state parity.
6) Display batch.

---

## TF2 — Book Construction & Capital Allocation

**(a) First principles.** Concentration must be re-earned by contest; the exit machinery must
actually fire. Two corollaries this sweep adds: **a gauge that measures only part of the book is
a false-negative machine** (the concentration/tail gauges read the resource barbell only; the
coverage gauge reads the whole account — same panel, two books), and **a ceiling only means what
it's measured against** (the 60% spear ceiling is 60% of the *resource sleeve*; as the
conventional sleeve grows, AGA.V's true share of the account silently diverges from the number
on screen — the WS ground-truth snapshot implies ~53% actual).

**(b) Hard questions.** Is every name earning its slot? Machine answer: still no — zero council
verdicts ever, and the one the operator asked for (08-02) produced nothing. Would a rotation
even show the truth for GROY/GMX.TO when their fair value structurally cannot register a gold
move? (A measurement problem hiding behind an inertia problem.) Does `remove_holding`'s
"no residue" hold? In live config yes; in code, no — ≥6 sites still hardcode URC.TO into
fallback ticker universes (`engines/util.py:180` `DEFAULT_BARBELL_WEIGHTS`,
`mcp_server/core.py:994,3537`, `ingestion_pipeline.py:131`,
`scripts/bootstrap/backfill_price_history.py:27`, `engine.py` ballast defaults) — a corrupt or
missing config key silently resurrects a decommissioned name [VERIFIED for util.py; rest
DELEGATED]. Why does the one conventional position have no `target_weight`, making the
rebalance-band tripwire a permanent no-op for the only name it governs?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | 0.60 ceiling centralized; conventional lane correctly walled off (`add_holding` refuses barbell tickers) — but nothing surfaces "60% of resource sleeve ≠ 60% of account" | `book_invariants.py:15` · `mcp_server/core.py:1093-1097` | FIXED, holds; scope-display gap NEW | VERIFIED (lead) / DELEGATED (display) |
| 2 | `_redistribute` ×3 byte-identical copies; only the constant is tested equal | `dynamic_config.py:200-225` · `book_change.py:33-55` · `mcp_server/core.py:2375-2399` | PERSISTS (3rd audit; no 4th copy added) | DELEGATED |
| 3 | Sizer corr book-derived + `corr_source` stamps | `engines/sizer.py:203-220` | FIXED, holds | DELEGATED |
| 4 | Off-sum barbell fallback log-only — and the fallback constant **contains URC.TO** | `engines/util.py:180,196-199` | PERSISTS, sharpened | VERIFIED |
| 5 | Thesis-review clock fields absent on every name incl. new CEG | `v5_config.json` `portfolio_metadata.*` | PERSISTS (3rd audit) | VERIFIED |
| 6 | Rotation gate: UNRATABLE shipped, correct — never fired (zero rotation calls in Memory) | `council.py:387-414` | FIXED code / unexercised | VERIFIED |
| 7 | Flywheel record: 118 Memory rows; 5 decisions, **0 outcomes, 0 council verdicts, 1 conviction (engine-seed)**; GROY/GMX.TO last contested 06-23 (45d) | `data/living_memory.jsonl` | PERSISTS — the headline gap | VERIFIED |
| 8 | **Ballast fair value macro-inert to its own commodity** — silver-framed `spot_ref=74.8` on GROY/GMX.TO; deliberate unit-mismatch guard, now the binding measurement gap; engine's own 08-02 finding, pinned, unactioned, no owner | `archetypes.py:211-224` · Memory `20260802-181710-db74b7` | NEW | VERIFIED |
| 9 | CLAUDE.md slot table still lists URC.TO as held (6 sites); no row for CEG's slot | `CLAUDE.md:15,37,79,86,92,95` | NEW (doc drift) | VERIFIED |
| 10 | `book_factor` concentration/tail read barbell-only; coverage reads whole book — same surface, two "books" | `engine.py:3946-3990,4003-4118` | NEW | DELEGATED |
| 11 | CEG: no `target_weight` → rebalance-band no-op; not sentinel-swept (recorded honestly as `sweep_gap` in the thesis itself); CDR unmarkable (no vendor quote — CEG NASDAQ is the pricing reference) | `v5_config.json` CEG · Memory `20260801-235712-*` | NEW | VERIFIED (memory) / DELEGATED (code) |
| 12 | Positives: URC decommission honest (config-clean, Memory-recorded, corrects 07-08's "lost freeze" to MOOT); counterweight thin-lane held in practice (6 candidates, no council/no scouting); WS ground-truth snapshot taken 08-01 | Memory · `data/candidate_universe.json` | NEW (good) | VERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Metal-framed `spot_ref` for GROY/GMX.TO so ballast fair value responds to its own commodity (the code's own documented fix path) — with a `replay_grade` before/after counterfactual | **ADOPT** — highest-leverage single fix in TF2/TF5 territory | propose→confirm |
| Council GROY and GMX.TO — first verdict rows ever; once before the spot-ref change (baseline), once after | **ADOPT** | operator-decision |
| Purge URC.TO from all hardcoded fallback universes | **ADOPT** — cheap, closes the resurrection class | code-behind-tests |
| Reconcile CLAUDE.md's slot table to the live book (URC.TO out; CEG's `ai-upside-ballast` in, or explicitly scope the table to the resource lane) | **ADOPT** | doc / operator-decision |
| `book_factor` scope honesty: whole-book concentration/tail, or explicit "resource sleeve only" labels; display AGA.V as % of total account beside the ceiling | **ADOPT** labels / **PILOT** whole-book | code / read-only |
| CEG `target_weight`; require it in `add_holding` going forward | **ADOPT** | propose→confirm |
| `_redistribute` consolidation + vector-equality test; thesis-review clock fields | **ADOPT** (carried) | code / propose→confirm |
| WS Activities-CSV importer MVP | **PILOT** — the manual snapshot flow works; build if fill-frequency justifies | operator-decision |

**(e) Next steps.** 1) Spot-ref fix + bracketing councils. 2) URC residue purge + CLAUDE.md
reconcile. 3) `book_factor` scope labels + CEG target_weight. 4) Carried: redistribute
consolidation, review-clock fields. 5) WS importer decision.

---

## TF3 — Data Provenance & Inputs

**(a) First principles.** Grounded-or-silent at the input boundary; the test for every feed is
"when it fails, can the operator tell?" This sweep adds: **the situational-awareness layer is an
input too** — a world-state brief that omits the freshness board makes every downstream judgment
start blind on exactly the risk class this TF exists to catch.

**(b) Hard questions.** Is a 330-day-old peer mark that is structurally invisible to *both*
freshness mechanisms still "sourced," or a hallucination with a URL attached? What is a PIT
detector worth on its fifth audit cycle if nothing ever acts on what it detects (the two GROY
look-ahead entries remain, machine-flagged on every load, never re-written)? Was the burn-review
note's own trigger — "re-derive from the Q-ended 2026-04-30 MD&A when filed" — ever checked?
(That filing was due ~late June; nobody looked.) Is "the operator re-pastes it periodically" a
data pipeline for the account's ground truth?

**(c) Current practice & strains.** The STRONG layer held and grew: the honesty-scan survived
the MRI reweight intact, PIT validation is live, the new input clients (Kalshi, FMP,
`predict_fair_value`) are stamped/capped/refusing correctly, currency display is honest.
[VERIFIED: honesty-scan survival, predict_fair_value refusal; rest DELEGATED]

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | Store cadence (item E): tracked, but appends land in ad-hoc bursts (all six `data:` commits on 08-02); no policy anywhere | `git log -- data/` | PARTIAL — 3rd sweep undecided | VERIFIED |
| 2 | AGA burn asof 2026-01-21 — **198 days**; reviewed-and-retained 07-08 with a re-derivation trigger nobody checked; runway on today's config = 17.45mo < 18.0 bar | `v5_config.json:27-33` | WORSE — decision-critical and now failing | VERIFIED |
| 3 | Waiver: expired 07-15, PLACEHOLDER intact, no decision recorded either way; fail-closed mechanics worked | `v5_config.json:980-987` · `engines/forensic.py:255-259` | PERSISTS — 23 days past its own deadline | VERIFIED |
| 4 | GROY look-ahead cache entries: present, machine-detected on every load, never re-written through `set()` | `research_cache.py:74-113` · cache GROY entries | PERSISTS + detector live | DELEGATED (TF3 ran the detector) |
| 5 | GMX peer mark as_of 2025-09-11 (**~330d**) — outside `HARD_FLOOR_ARGS` *and* invisible to the `data_freshness` panel (whose "peers" feed is a different comps worker) | `holdco_nav_feed.py:46,129-146` · `engine.py:1173` | PERSISTS + confirmed structurally invisible | DELEGATED |
| 6 | URC.TO orphaned data: full NAV block + 2y price series remain in stores; hardcoded into ingestion/backfill default universes | `data/research_cache.json` · `ingestion_pipeline.py:131` · `scripts/bootstrap/backfill_price_history.py:27` | NEW (hygiene didn't follow the decommission) | DELEGATED |
| 7 | FRED label drift (`REAINTRATREARAT10Y` config vs `DFII10` code ×5); dormant-leg-only risk; ingestion fundamentals leg still configured-dormant, undecided | `v5_config.json:1101` · `engines/macro_regime.py` | PERSISTS | DELEGATED |
| 8 | Currency seam: store-level silent-CAD fallback unchanged (5c5c242 fixed the *display* layer, a different bug); real callers resolve currency correctly in practice | `price_history.py:222-223` | Largely mitigated, seam unchanged | DELEGATED |
| 9 | `world_state.py`: zero freshness/degraded references — the mandated first call ships blind on TF3's territory | `world_state.py` | NEW | VERIFIED |
| 10 | WS ground-truth book: hand-pasted Memory note, no refresh path, silently staling (6d) | Memory `20260801-235712-*` · `docs/WS_INTEGRATION_ASSESSMENT.md` | NEW | VERIFIED |
| 11 | AGA cash cache orphan: restated value `48.0` (millions) beside history in raw dollars — harmless only because nothing reads it | `data/research_cache.json` AGA.V.cash | NEW (minor) | DELEGATED |
| 12 | Bare-45.0 MRI fail-safe on the no-detail path | `engines/macro_regime.py:582-589` | PERSISTS (scoped 07-08) | DELEGATED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Burn re-derivation from the Q-ended 2026-04-30 MD&A (verify it's on SEDAR+ — the single highest-value unresolved check) or an explicit recorded non-refresh decision | **ADOPT** — precedes any trustworthy waiver/runway claim | propose→confirm |
| `world_state` freshness fold-in (with TF1's forecast-due parity) | **ADOPT** | code-behind-tests |
| GMX peer-mark soft-staleness watch (`SOFT_VALUE_ARGS`-style, distinct from the hard floor set) | **ADOPT** — 330 days is no longer a nuance | code-behind-tests |
| URC.TO purge from default universes + orphaned-store hygiene | **ADOPT** | code |
| GROY cache re-write through `set()` — unblocked, the detector already proves the fix | **ADOPT** | propose→confirm |
| Store-cadence decision (item E) — even "commit stores at every session end" written down beats three sweeps of silence | **ADOPT** | operator-decision |
| FRED label + cash-units orphan fix | **ADOPT** batch, low urgency | code |
| WS re-snapshot discipline (dated routine short of the full importer) | **PILOT** | operator-decision |

**(e) Next steps.** 1) Burn re-derivation (fused to the TF5 waiver decision). 2) World-state
fold-in. 3) Peer-mark watch + URC purge. 4) GROY re-write. 5) Cadence decision. 6) Label/units
batch.

---

## TF4 — Research Production & the Agentic Layer

**(a) First principles.** Engine owns the reproducible; agents own the contested; the human owns
mutation. This sweep's corollary, forced by the evidence: **a mechanism that is wired but never
exercised is not a safeguard — it is a false sense of one.** The reconcile law, the capture
hook, the UNRATABLE verdict, and two coherence patterns are all real code with zero firings.

**(b) Hard questions.** Why does the flagship dialectic workflow — promoted eight times in
CLAUDE.md's routing table — have no track record at all: is `/council` run and its verdict
discarded, or not run? Now that `record_decision`/`record_conviction` feed the flywheel, why are
they the least-gated mutating tools in the fleet (no deny-list, invisible to the drift guard,
`source` hidden and hard-defaulted to `"user"`)? Is the counterweight thin-lane a lane or a
request (prose-only; nothing in its manifest denies council tools; no test)? Three agents added
six weeks ago have zero Memory traces — earning their seat, or roster inflation? What blocks the
GROY $1B-rejection backfill — a single write, promised two sweeps ago?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | Gemini/agy lane **removed** — routing, argv, roster, contract all gone; not a flag flip | `git show c7df647` · 1 doc-comment residual | FIXED (was the open door) | VERIFIED |
| 2 | Council verdict persistence: never happens — 0 rows ever; capture hook waits; 2 of 6 coherence patterns dead code (`verdicts=` never passed, `engine.py:3004-3005`) | `council.py:180-242` · `mcp_server/core.py:1314` · `coherence_check.py:108-131` | WORSE than graded — flagship product has never fired | VERIFIED |
| 3 | `set_nav` main-session path: unchanged direct write, any-URL source | `mcp_server/core.py:751-772` | PERSISTS (3rd cycle — oldest open TF4 item) | VERIFIED |
| 4 | `memory_write` provenance clamp | `mcp_server/core.py:1270-1305` | FIXED, holds | DELEGATED |
| 5 | `research_cache.verify()` + sourcer≠verifier + GROY backfill | no `def verify` repo-wide · `holdco_nav_feed.py:199-201` | PERSISTS (2nd carry) | DELEGATED |
| 6 | `graduate_candidate` any-vintage receipts | `mcp_server/core.py:2042-2092` | PERSISTS | DELEGATED |
| 7 | `record_decision`/`record_conviction`: `source` hidden by the MCP wrappers, hard-defaulted `"user"`; registered outside `_PASSTHROUGH_TOOLS` (invisible to the drift guard); in no deny-list; conviction-book label keys off `meta.seeded`, not source — a subagent's reading would render as `operator` | `mcp_server/server.py:205-219` · `mcp_server/core.py:1484-1521` | NEW | VERIFIED |
| 8 | Counterweight thin-lane: prose-only invariant; held in practice (candidate/Memory evidence), unenforced in code | `.claude/agents/counterweight.md` | NEW | DELEGATED (practice VERIFIED via TF2) |
| 9 | Roster usage (Memory traces, 118 rows): bear 16 · calibration 13 · scout 12 · bull 12 · verifier 10 · anti-scout 6 · synthesis 4 · value-analyst 4 · counterweight 3 · catalyst-verifier 1 · balance-sheet-analyst 1 · **arbiter 0 · data-integrity-auditor 0 · conviction-analyst 0 · entry-sentinel 0** | `data/living_memory.jsonl` | NEW (measurement) | DELEGATED |
| 10 | Positives: F1–F3 boundary clean (pure, flag-never-mutate, world-state-briefed); run-tag hand-off real in code and in production use; Opus 4.8 pin honest (choke point + 7 frontmatters + seat-truth test); manifest parity test passes as-run | `coherence_check.py:29-32` · `conclusion_decay.py:124` · `cockpit_widgets.py:730` | NEW (good) | DELEGATED |

**Division of labor (the charter question).** Rightly deterministic and clean: the reconcile
guardrails, coherence/decay detection, sizer membership math, slot-fit hard gates, the manifest
cage itself. Duplication/drift risk: value-analyst prose re-deriving engine numbers with no
check against them; agent forensic reads parallel to the JSF gate with no reconciliation;
scout's prose slot-fit beside `discovery_screen`'s mechanical one. The sharpest boundary gap:
**the signal-coherence law lives only inside `/council`** — an anti-scout KILL on the convex
spear, a value-analyst fair-value range, a conviction-analyst commentary are never subject to
the no-narrative-veto/prior-dominance rules; and because verdicts are never persisted, the
coherence patterns that would catch an agent contradicting the engine are dormant. As AI
capability grows, the answer to "what should be newly delegated" is *not more agent seats*
(four have zero traces) but **wiring the existing judgment layer's output back into the
deterministic loop** — verdicts persisted, decisions attributed, grades consumed.

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Wire `/council` end-to-end: arbiter persists `memory_write(type="council_verdict")` after reconcile; fixture test asserts one verdict row per run; then feed `verdicts=` into `_run_coherence_decay` | **ADOPT** — the sharpest gap in the layer; two dormant coherence patterns activate free | code-behind-tests |
| `record_decision`/`record_conviction`: caller attribution (agent identity, not `"user"`), drift-guard visibility, deny-list decision | **ADOPT** | code-behind-tests + operator-decision (deny) |
| `set_nav` main-session gate | **ADOPT** (3rd carry) | code + operator-decision |
| `research_cache.verify()` + GROY backfill; `graduate_candidate` freshness binding | **ADOPT** (2nd carry) / backfill = propose→confirm | mixed |
| Thin-lane invariant made mechanical (manifest deny + lane test) | **ADOPT** | code-behind-tests |
| Sourcer≠verifier as a code check in `graduate_candidate` | **PILOT** | read-only → propose→confirm |
| Roster review after one more operating cycle (measure before retiring the four zero-trace seats) | **PILOT** | operator-decision |

**(e) Next steps.** 1) Council persistence + coherence feed. 2) `record_*` attribution +
drift-guard visibility. 3) `set_nav` gate. 4) verify()/backfill/freshness batch. 5) Thin-lane
mechanical. 6) Roster measurement.

---

## TF5 — The Conviction & Valuation Framework

**(a) First principles.** The rating earns trust two ways: inputs real, outputs graded. Two
additions this sweep: **a threshold must be enforced at the layer it protects, or it is
decorative** (an 18-month bar whose failure surfaces nowhere is not a bar); and **a grading
apparatus is only as honest as its event-counting** (a sound methodology over an
un-deduplicated ledger produces confident nonsense).

**(b) Hard questions.** Is the 6.0-vs-18.0 runway split a deliberate death-spiral/comfort
distinction or unexamined drift between two engineers' thresholds? Should the dead PLACEHOLDER
override dict still sit in config with live-looking `dilution_insulated: true` flags when the
code will never honor it? Is Brier-scoring an un-overridden engine-seeded trail (the store's
exact current state: one conviction row, `seeded=true`, zero operator overrides) a test of the
operator's calibration or the engine grading itself? Was "first principles, zero grades" an
acceptable standard for the MRI reweight — and is it now the *permanent* standard, since
`replay.py` grades price/floor/band and can never grade a regime call? Is "grading maturity
arrived 07-12" even the right frame when the loop takes 8 rows in six weeks — isn't "is anyone
running the loop" the prior question?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | Waiver: PLACEHOLDER verbatim, expired 07-15, **no decision recorded either way**; the desk's own 07-12 note named the deadline and the fork | `v5_config.json:980-987` · Memory `20260712-193415-ca03e0` | PERSISTS → defaulted (the outcome 07-08 called indefensible) | VERIFIED |
| 2 | Runway: fiction resolved (cash refreshed, sourced), failure real — 48.0/2.75 = **17.45mo < 18.0**; and the rating gate checks 6.0/1.5 instead, so the JSF hit is silently absorbed: 08-02 decision stamped `cap 10.0 "clean"` | `v5_config.json:14,29,790,996` · `asymmetry_rating.py:683-702` · ledger `20260802-171347-0892e9` | NEW — the sweep headline | VERIFIED |
| 3 | Grading: warm for the first time (3,230/3,319 gradeable at 30d; 90/180d correctly n=0) but **corrupted by thrash** — 2,474 GROY rows [VERIFIED], ~1 breach event duplicated ~2,389× → `floor_reliability` posterior 0.33% vs 80% prior; `MIN_N=5` defeated by construction; hysteresis (item F) still unshipped (`_FP_INTRINSIC_DECIMALS=3` the only damper) | `replay.py:42` · `valuation_ledger.py:48` · live `grade_ledger`/`ledger_priors` run | PERSISTS → proven corrupting | VERIFIED (mechanism, counts) / DELEGATED (recomputed posterior) |
| 4 | Loop cadence: 8 non-restore ledger rows in six weeks, all one session; two ~18-day Memory dead stretches | store timestamps | NEW — the loop has effectively stopped between sessions | VERIFIED |
| 5 | Brier circularity: `conviction_book` labels provenance honestly for open theses, but close-time Brier (`engine.py:3123`) pulls the whole trail with no `seeded` filter; the first close will grade the engine's prior as the operator's honesty | `calibration.py:399-445` · `engine.py:3097-3145` | NEW — primed, not yet triggered | DELEGATED |
| 6 | `record_outcome` (MCP) never computes Brier; only the engine heartbeat close does — two closing paths, one silently incomplete | `mcp_server/core.py:1417-1439` | NEW | DELEGATED |
| 7 | Posterior store: `update_beta` still pure-ephemeral; nuance corrected — grades no longer *evaporate* (ledger is tracked; every call recomputes) but no trajectory is persisted and **no consumer reads the posterior** (ribbons/thresholds all hardcoded) — the flywheel computes and never feeds back | `base_rates.py:301-314` | PERSISTS, reframed | VERIFIED (no consumer) / DELEGATED (detail) |
| 8 | Fair-value ratchet up-only; goodwill=0→HIGH unchanged; no down-tier pilot ran; both permanently ungradeable by the current apparatus (replay grades price/floor/band only) | `holdco_nav.py:270-365` · cache GROY | PERSISTS | DELEGATED |
| 9 | T-pillar tape leak (`vol_edge 0.35`, `weak_usd`) unstripped; `conviction_lift 0.65` still ungraded — deferral now doing double duty (grades exist but are corrupted) | `engine.py:1219-1258` · `asymmetry_rating.py:754` | PERSISTS | DELEGATED |
| 10 | Positives: `_valuation_integrity` (19366e2) is a genuine universal invariant (dead-leg/single-driver/fail-closed-confidence detection + directive suspension); `forecast_ledger` sound (explicit verbal mapping, supersede-not-overwrite); `dual_sided` archetype-appropriate and honestly self-labeled ("asserted (n=0 realized) until calibration grades…"); MRI reweight config-driven (flywheel-reachable for the first time) | `asymmetry_rating.py:784-835,925-933` · `forecast_ledger.py:38,79-85` · `dual_sided.py:11-23` | NEW (good) | DELEGATED |
| 11 | Overdue forecast in-contract now: CEG P-3 (resolve-by 08-06) open; CEG tranche-2 gate review (post-print) due; Memory silent since 08-02 | Memory `20260731-134858-843248` | NEW, live | VERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| **Decide the waiver on today's real numbers** — sourced SEDAR+ basis + short expiry, or recorded conscious lapse — and delete/neutralize the dead PLACEHOLDER dict so it stops reading as live | **ADOPT** — 24 days overdue; currently decided by silence | operator-decision + propose→confirm |
| Reconcile the two runway bars: justify the 6/18 split explicitly (death-spiral vs comfort *is* a defensible distinction) **and** make a JSF-internal failure visible — band suffix, directive note, or freshness-panel row — even when the rating cap doesn't move | **ADOPT** — the mechanism that let a real failure pass invisibly | code-behind-tests + operator-decision (the bar) |
| Ledger dedup before grading (`(ticker, fingerprint)` or calendar-day collapse in `grade_ledger`) **and** ship the material-change min-delta at the write layer (item F) | **ADOPT** — blocks every downstream number until fixed; now demonstrated, not hypothetical | code-behind-tests |
| Brier: filter/report `seeded` separately at close; wire Brier into `record_outcome` | **ADOPT** — cheap; the live test case (AGA.V) is sitting open right now | code-behind-tests |
| Persist `ledger_priors` output (trajectory) + wire ONE consumer (ribbon width or a forensic threshold) — only after the dedup fix | **PILOT**, sequenced | code-behind-tests |
| Resolve CEG P-3; run the tranche-2 gate review against the 08-06 call | **ADOPT** — mechanical, in-contract, overdue | operator-decision |
| Regime-outcome grading harness for MRI (or accept and label MRI as permanently first-principles-only); goodwill down-tier pilot | **PILOT** / REJECT further reweights until then | read-only → propose→confirm |
| T-pillar strip | **ADOPT** (display-first) | propose→confirm |

**(e) Next steps.** 1) Waiver decision + P-3 resolution + tranche-2 review (today-class).
2) Ledger dedup + hysteresis (this week — everything learns from this substrate). 3) Brier
seeded-filter + `record_outcome` parity. 4) Runway-bar reconciliation. 5) Then — and only then —
first honest grades published, posterior persisted, one consumer wired.

---

## Cross-Cutting Matrix

| Tension | Upstream | Downstream | Who co-signs |
|---|---|---|---|
| **Silence decides** — the waiver defaulted with its deadline written down; P-3 sits overdue with the capture contract written down; cadence is on its third sweep | No mechanism converts a written deadline into a forced choice | The desk's largest position ran 3+ weeks with a failed forensic bar and a "clean" rating; the calibration record rots in the open | Operator (the decisions) + TF1 (surface gated-item age like data staleness — proposed 07-08, never built) |
| **Two bars, one silent failure** | TF3: burn stale-but-retained; TF5: JSF-internal 18.0 vs rating-gate 6.0 | A real runway failure produced a Q-pillar shave nobody can see; "clean" printed on the 08-02 freeze | TF5 reconciles the bars; TF3 refreshes the burn; operator picks the bar |
| **New surfaces don't inherit the rails** | Every new feature (web cockpit, world_state, add_holding, record_*, READONLY-era tools) shipped outside the guards built for the old ones | The 07-08 fixes govern the past; each new surface reopens the class | Fix authors: guards must bind by *shape/registration*, not by name — the drift-guard widening is the template |
| **Built machinery, zero firings** | Council persistence, UNRATABLE, coherence verdict-patterns, replay grades, posterior — all real code | The judgment layer produces nothing durable; the learning loop computes and never feeds back; four agent seats have zero traces | TF4 wires persistence; TF5 wires consumers; operator actually convenes the councils |
| **The account outgrew the book's instruments** | TF2: conventional sleeve outside the barbell invariants (by design) + macro-inert ballast refs | Concentration/coverage gauges read different books; the 60% ceiling quietly means 53% of the account; a gold royalty's rating can't see gold | TF2 labels/extends the gauges; propose→confirm on spot_refs; CLAUDE.md reconciled |

---

## Sequenced Program

Ordering: **the live clocks first, then the measurement substrate (everything learns from it),
then the guard gaps, then surface parity, then the carried refactors.**

### Phase 0 — Decide what silence is currently deciding (operator, days)
| # | Step | Source | Gate |
|---|---|---|---|
| 0.1 | Resolve forecast P-3 against the actual 08-06 CEG print; run the tranche-2 gate review (claims c1–c4) and record it | TF5 | operator-decision |
| 0.2 | **Decide the AGA.V waiver on today's numbers** (17.45mo): sourced re-base + short expiry, or recorded lapse; delete the dead PLACEHOLDER dict either way | TF5 | operator-decision + propose→confirm |
| 0.3 | Check SEDAR+ for the Q-ended 2026-04-30 Silver47 MD&A; re-derive burn (or record why not) | TF3↔TF5 | propose→confirm |
| 0.4 | Store-cadence decision (item E, third ask): write ANY policy down | TF2↔TF3 | operator-decision |

### Phase 1 — Make the measurement honest before anything learns from it
| # | Step | Source | Gate |
|---|---|---|---|
| 1.1 | Ledger dedup in `grade_ledger` + material-change min-delta at the write layer (item F) | TF5 | code-behind-tests |
| 1.2 | Brier `seeded` filter at close + `record_outcome` Brier parity | TF5 | code-behind-tests |
| 1.3 | Runway-bar reconciliation: keep or converge 6/18 explicitly; surface a JSF-internal failure visibly regardless of the rating cap | TF5 | code + operator-decision |
| 1.4 | Council verdict persistence (arbiter → `memory_write(type="council_verdict")` + fixture test); feed `verdicts=` to coherence | TF4 | code-behind-tests |
| 1.5 | Metal-framed `spot_ref` for GROY/GMX.TO with a replay counterfactual; council both names before and after | TF2↔TF5 | propose→confirm + operator-decision |

### Phase 2 — Close the guard gaps by shape, not by name
| # | Step | Source | Gate |
|---|---|---|---|
| 2.1 | Drift-guard widening (shape-based + registration visibility); deny `add_holding`; pull `record_*` into guard scope | TF1↔TF4 | code-behind-tests |
| 2.2 | `CEX_MCP_READONLY` honest coverage (wire the seven, or fix the docstring) | TF1 | code-behind-tests |
| 2.3 | `confirm_param_change` explicit source + registration-loop gate assertion | TF1 | code-behind-tests |
| 2.4 | `set_nav` main-session proposal-routing (3rd carry) | TF1↔TF4 | code + operator-decision |
| 2.5 | `record_decision`/`record_conviction` caller attribution | TF4 | code-behind-tests |
| 2.6 | Thin-lane invariant mechanical (counterweight manifest + lane test) | TF4 | code-behind-tests |

### Phase 3 — Surface parity & hygiene
| # | Step | Source | Gate |
|---|---|---|---|
| 3.1 | Web cockpit provenance tells (`floor_degraded`/`~proxy`) | TF1 | code-behind-tests |
| 3.2 | `world_state` online parity: freshness + forecast-due | TF1↔TF3 | code-behind-tests |
| 3.3 | URC.TO purge from all fallback universes + store hygiene | TF2↔TF3 | code-behind-tests |
| 3.4 | CLAUDE.md slot-table reconcile; `book_factor` scope labels; CEG `target_weight`; GMX peer-mark watch | TF2↔TF3 | doc / code / propose→confirm |
| 3.5 | GROY cache re-write through `set()`; FRED label; cash-units orphan | TF3 | propose→confirm / code |

### Phase 4 — The carried refactors & the warmed loop
| # | Step | Source | Gate |
|---|---|---|---|
| 4.1 | Directive → (code, display_text) enum (5th audit — retire the item) | TF1 | code-behind-tests |
| 4.2 | `_redistribute` consolidation; thesis-review clock fields; `survival_exempt_archetypes` decision + assertion | TF1↔TF2 | code / propose→confirm |
| 4.3 | First honest grades published (post-1.1); persist posterior trajectory; wire one consumer | TF5 | code → propose→confirm |
| 4.4 | `research_cache.verify()` + GROY backfill; graduation freshness; sourcer≠verifier pilot | TF4 | mixed |
| 4.5 | T-pillar strip; goodwill pilot; MRI grading-harness design; roster usage review | TF5↔TF4 | read-only → propose→confirm / operator-decision |

---

## Preserved dissent & could-not-verify

**Dissent, preserved:**
- **The two runway bars may be legitimately different numbers.** A 6-month death-spiral trigger
  (rating cap) and an 18-month comfort bar (JSF scoring) encode different questions. The defect
  argued here is the *silence* — a failed 18-month bar surfacing nowhere — not necessarily the
  split itself. The reconciliation step deliberately allows "keep both, justify both, surface
  both."
- **The ballast macro-inertness is a guard, not a blunder.** The silver-framed `spot_ref`
  neutrality was built deliberately to kill a ~60× phantom-upside bug, and the code documents
  the fix path. The critique is that the *limitation became load-bearing* (a gold royalty rated
  7.2 whose valuation cannot see gold) without an owner — not that the guard was wrong.
- **The conventional sleeve's isolation from the barbell invariants is a defensible design.**
  `add_holding` refusing barbell tickers is correct wall-building. The open question is purely
  display honesty (what does "60%" mean on screen), not the wall.
- **Engine-seeded conviction is by design** — the auto-seed exists so the flywheel never stalls
  waiting for typed input, and the seed is honestly labeled at the read layer. Only the
  close-time scoring path conflates the channels.
- **The quiet loop partly reflects the operating environment**, not only negligence: the desk
  runs in ephemeral cloud sessions, and the heartbeat dies with each sandbox. That is an
  argument *for* deciding item E (cadence), not against the finding.
- **Dedup unit choice changes the answer.** Fingerprint-collapse vs calendar-day-collapse will
  produce different posteriors; the choice should be argued openly in the PR, not defaulted.

**Could not verify (blockers stated):**
- **Live engine behavior** — no run this session. The runway-failure arithmetic is config-certain;
  whether the *live* yfinance dilution/CBA legs also fail, and what the current rating renders,
  were not observed.
- **Whether SEDAR+ holds the Q-ended 2026-04-30 Silver47 MD&A** — no web fetch performed for it
  this session; named as the single highest-value unresolved check.
- **The recomputed grading magnitudes** (0.33% posterior, ~2,389× duplication, 70 distinct
  events) — produced by the TF5 scan's live read-only run of `replay.grade_ledger` /
  `ledger_priors` over the committed stores; the lead verified the row counts (2,474 GROY;
  3,319 total; 8 post-06-24 non-restore rows) and the absent hysteresis, not the full
  recomputation.
- **Host state** — whether any machine holds newer store rows than the committed tree; whether
  any heartbeat currently runs. Everything graded here is the committed tree.
- **Test-suite green** — not executed this session (read-only sweep; TUI deps absent in this
  environment). Last recorded baseline: 1759 passed / 1 pre-existing flake (07-08 execution).
- **DELEGATED rows** — reported by the five scans with quoted anchors; the lead independently
  re-verified every headline and every money-relevant mechanic (the waiver/runway/gate chain,
  the two bars, the 08-02 "clean" stamp, the READONLY AST scan, the drift-guard tuple, the
  `record_*` wrappers, zero council verdicts, the agy removal, the macro-inert guard, the URC
  fallback constant, the world_state blindness, store counts and dates) but did not re-read
  every supporting anchor line-by-line.

*When a claim here conflicts with the tree, the tree wins — re-grep, re-verify, report the
correction.*
