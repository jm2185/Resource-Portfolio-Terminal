# CommodityEx — Standing Reassessment (2026-07-08)

*A five-task-force sweep under the standing charter, six days after the 2026-07-02 sweep and its
execution pass. **The engine was NOT run this session** (offline in this environment; not
authorized) — this is a code/config/data sweep of the committed tree, which turned out to be the
point: the sweep's headline finding is about what the committed tree no longer contains. Method:
five parallel deep scans (one per task force), each briefed to re-grade every 07-02 finding
(FIXED / PERSISTS / PARTIAL / WORSE) and audit the post-07-02 commits from first principles;
every headline finding was independently re-verified by the lead against the tree before shipping.
Tags: **VERIFIED** (lead re-read the code/data), **DELEGATED** (a scan quoted it; the lead did not
independently re-read), **COULD-NOT-VERIFY** (blocker stated). Gate tags are binding: read-only ·
code-behind-tests · propose→confirm · operator-decision. One action was executed this session and
is disclosed in the hygiene note: the restore of the three untracked memory stores.*

---

## Executive Verdict

The 07-02 execution pass was real: six code fixes shipped, and all six **survived three heavy
refactors intact** (the engines/ split, the TUI split, the MCP registration loop) — the test
discipline is doing exactly what it is for. But this sweep found that the same night the desk
wrote its reassessment, it also **untracked its own memory**, and the six days since have decided
none of the eight operator-gated items while all three clocks kept running. Four findings dominate:

**1. The desk deleted its audit trail from version control the night it audited itself (ALL
TFs — VERIFIED, new).** Commit `83f092c` (2026-07-02 22:06, "Tier 2 of token-optimization audit")
untracked `data/living_memory.jsonl`, `data/valuation_ledger.jsonl`, and `data/price_history.json`
— the append-only nervous system, the graded track record, and the replay ground truth. The 07-03
fix (`3830fed`) restored **only** `research_cache.json` after the wipe collapsed GROY's floor, and
wrote a `.gitignore` block declaring all four stores "SOURCED / ACCUMULATED state — TRACKED …
NOT regenerable caches"; the tree never fulfilled it — `git ls-files` showed three of the four
absent until this session's restore. Consequences, each verified: (a) every fresh clone — including
the cloud sessions this desk actually works in — had **no memory, no ledger, no price store**;
(b) the 07-02 live run's writes (**URC.TO's first-ever decision freeze**, the 4 ledger rows, the
07-02 closes) were never committed and are **lost with that session's sandbox** — the restored
snapshot ends 2026-06-24 and URC.TO's row is not in it; (c) grading maturity arrives **2026-07-12
— four days from now** — and until this session the repo had literally nothing to grade. The house
principle is "corrections supersede, never overwrite — the audit trail is the track record"; for
six days the track record was an untracked local file on whichever machine last ran the engine.

**2. Every clock item named on 07-02 arrives this week, and none has been decided (TF3/TF5 —
VERIFIED).** The AGA.V forensic waiver on the 60% spear is still the verbatim `"PLACEHOLDER —
replace with the real basis"`, expiry **2026-07-15 — seven days**; on 07-16 both waivers die
automatically (`engines/forensic.py`, fail-closed, no ceremony) and the dilution gate's only pass
is runway insulation (≥18 mo) computed on cash/burn now **168 days stale**. Recomputed stakes: the
stale inputs give 53.07/2.75 ≈ **19.3 months on paper**; at the config's own burn, implied
treasury today is ~CAD 38M ≈ **13.8 months — below the bar in reality but not in the model**. The
model will pass a test reality fails, silently, by default, at the desk's largest position. The
uranium stamp (US$86.10, as_of 2026-06-04) crosses its staleness window **2026-07-19/20** with no
second source piloted — and this sweep found the "cliff" is softer than advertised: a `>` 45.0
comparison makes it land on day 46, and it only sets a flag and widens the ribbon; the mark keeps
computing on the 34-day-old number indefinitely.

**3. The fixes ship exactly as far as the finding was worded — the letter, not the invariant
(TF1/TF3 — VERIFIED).** A pattern, now with four instances. The born-LIVE fix re-badged the CFTC
cold-start `INITIAL_BASELINE` with a comment citing the finding — while **two lines above it**
`"real_yield": 1.0, "ry_status": "LIVE"` is the identical defect, unfixed (`engine.py:235-236`),
and the MRI honesty scan loops over only the seven metrics-dict inputs, never the four positional
ones (silver/real-yield/copper/gold), so a fabricated real yield flows into the regime read with
no flag at all. The confirm-gate fix guarded the endpoint — but `confirm_param_change` POSTs
`{"id"}` with **no source field**, the endpoint defaults it to `"cockpit"`, and `_write_source_ok`
waves it through: the endpoint guard **never actually refuses the MCP path**; the agent-manifest
deny-list is the sole closure (VERIFIED: `mcp_server/core.py:713` → `engine_api.py:213`). The
provenance tells shipped on the rail — but the φ≥1 `BELOW FLOOR — ACCUMULATE` directive still
fires ungated on a degraded floor. The MRI flags shipped — metadata-only, number unchanged, and
the bare `45.0`-on-exception survives on the no-detail path. Each fix is real; each stopped one
seam short of the invariant it was defending.

**4. Two write paths sit entirely outside the cage (TF4 — VERIFIED, new).** First: `set_nav` — an
exposed MCP tool that writes a ballast's `nav_adj_per_share` fair-value anchor "effective next
eval cycle" with **no proposal, no confirm, no deny-list entry**; its only gate is "a source_url
is required," which any URL satisfies. Every other rating-adjacent mutation routes through
propose→confirm; the NAV path — the exact artifact class (GMX −59%) the desk built
verify-before-wire for — does not. Second: the **gemini lane**. `scout` and `catalyst-verifier`
route to `agy -p {prompt}` (env-overridable `CEX_AGY_CMD`/`CEX_AGY_HEADLESS`), and the code's own
comment states a Gemini seat "carries none of the .claude subagent contract" — the manifest
deny-lists that the 07-02 execution called "the load-bearing closure" **do not apply to these
seats at all**, and the scout's output contract is enforced in the prompt, not in code. The cage
was hardened on the Claude door while two other doors stand open.

**The through-line:** the desk's mechanisms are strong and its follow-through is now the binding
constraint — 0 of 8 operator-gated items from 07-02 were decided in six days, while the code side
shipped six fixes plus two refactors. The asymmetry is structural: code-behind-tests items have an
executor (these sessions); propose→confirm items have a queue; **operator-decision items have
neither a clock nor an owner**, and three of them expire this week. In a concentrated book the
expensive failure is still false confidence — and this week it is specifically the spear's
survival gates re-engaging against fictional cash while the model reports a pass.

---

## What changed since 07-02 (verified against the tree)

**Shipped and survived (07-02 execution, re-verified today):** the `_write_source_ok` confirm
guard (`engine_api.py:139,157,214`); the four-tool deny-list across all 15 subagent manifests;
`council_reconcile` as a read-only MCP tool with the provenance weighting now reachable
(`mcp_server/core.py:2673`, `council.py:63,122`); `book_invariants.SPEAR_CEILING` wired to six
consumers with a byte-equality test; the zero-intrinsic stamp-guard + read-side phantom exclusion
(`valuation_ledger.py:237-243`, `replay.py:187-190`); the CFTC `INITIAL_BASELINE` cold-start; the
`_provenance_tell` rail markers (`cockpit_widgets.py:431-443`). All survived the engines/ split,
the TUI split, and the MCP registration loop. [VERIFIED]

**New and good (07-03 batch):** `reconciled_book_value()` — a genuinely **symmetric** units guard
that blocked the GROY 10× floor collapse and is pinned to catch both directions
(`research_cache.py:29-68`); the store-seam refusal — `grade_ledger` refuses a basis-mismatched
ticker instead of fabricating a −30% failure (`replay.py:150-194`); the price-store CAD
normalization; archetype-aware `engine_break` with a reason string (`council.py:144-172`) —
retires the false break on every healthy ballast; canvas seat-truth (nodes show who actually ran);
heavy-ask timeout detection in natural language. [VERIFIED mechanics; DELEGATED test claims]

**Not decided (07-02 surfaced items A–H):** all eight remain open — waiver (A), cash/burn refresh
(B), FRED label (C), uranium second source (D), `survival_exempt_archetypes` alignment (E),
material_change hysteresis (F), backfill + heartbeat (G), cache re-write + Memory backfill (H).
[VERIFIED]

---

## TF1 — Signal & Communication

**(a) First principles.** Unchanged from 07-02 and re-affirmed: every rendered number carries its
own confidence, and every state mutation passes a *mechanical* human gate. The new corollary this
sweep adds: **a gate is only closed when every path through it is closed** — an endpoint guard
that never fires, a deny-list one CLI lane never reads, and a directive one flag never gates are
all the same defect at different layers.

**(b) Hard questions.** Why does the endpoint confirm-guard exist if the only caller it would
refuse never identifies itself (`confirm_param_change` omits `source`; the endpoint defaults
`"cockpit"`)? Why is the directive still a prose string parsed by keyword in three places, two
audits after the enum refactor was specified — with FAIR-VALUE still indistinguishable from
unparseable at 0.50? Why does a φ≥1 directive shout ACCUMULATE on a floor the same commit-series
taught the rail to dim as `~proxy`? Who is allowed to add the next MCP tool — the registration
loop makes a mutating passthrough a one-line append with no gate wired by construction?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-02 | Confidence |
|---|---|---|---|---|
| 1 | Confirm hole (endpoint + deny-lists) | `engine_api.py:214` · `.claude/agents/*.md:5` ×15 | **FIXED** — but see #2 | VERIFIED |
| 2 | Endpoint guard inert on the MCP path: `confirm_param_change` POSTs no `source`, defaults `"cockpit"`, guard passes; deny-list is the sole closure; any new `_PASSTHROUGH_TOOLS` append inherits zero backstop | `mcp_server/core.py:713` · `engine_api.py:213` · `server.py:61-136` | **NEW** | VERIFIED |
| 3 | Provenance tells on the rail (`Q~proxy`, floor `~proxy`, φ dimmed) | `cockpit_widgets.py:431-443` · `commodityex_tui.py:644-665` | **FIXED**, survived TUI split | VERIFIED |
| 4 | φ≥1 `BELOW FLOOR — ACCUMULATE` still fires with no `floor_degraded` check; blue-sky still prints flat teal, no ✓verified/~scenario tick | `asymmetry_rating.py:802-803` · `commodityex_tui.py:677-685` | PERSISTS | VERIFIED |
| 5 | Directive prose keyword-parsed ×3; silent 0.50 on unknown; FAIR-VALUE≡0.50 collision; `tail[:5]` chip garbage | `council.py:44,104-109` · `cockpit_widgets.py:287-310` | PERSISTS (refactor unshipped) | VERIFIED |
| 6 | Collapsed council strip seeds the verdict slot with the raw directive (expanded view honest) | `commodityex_tui.py:7131-7132` vs `:7190,7196` | PARTIAL (unchanged) | DELEGATED |
| 7 | Colour band flips on 0.01 wobble (raw score vs hard thresholds) | `conviction_health.py:49-51` | PERSISTS | DELEGATED |
| 8 | Router first-match; bare "runway" → balance-sheet above sentinel; no did-you-mean | `cockpit_widgets.py:794-812` · dispatch `commodityex_tui.py:6391-6397` | PERSISTS | DELEGATED |
| 9 | `survival_exempt_archetypes` config `["asset_light_yield"]` vs code `+compounder,deep_value`; config wins; no assertion | `v5_config.json:761-763` · `asymmetry_rating.py:317,664` | PERSISTS (behavioral) | VERIFIED |
| 10 | Headless runner: no `--disallowedTools` in `_job_argv`/`_pipeline_argv`; safety is a prose guard string | `commodityex_tui.py:2803-2837,7418-7433` | PERSISTS (Phase 1.3 unshipped) | VERIFIED |
| 11 | Deny-list inconsistency: `conviction-analyst`, `catalyst-verifier`, `data-integrity-auditor` omit `set_param` (mitigated by the proposal route, but audit-tripping) | `.claude/agents/*.md:5` | NEW (minor) | DELEGATED |
| 12 | Sourced-bull ≤ base×1.02 renders "— not sourced" | `commodityex_tui.py:679,685` | PERSISTS (minor) | DELEGATED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Make the endpoint guard load-bearing: mutating MCP tools pass explicit `source="mcp:<tool>"` so `_write_source_ok` refuses them; add a registration-loop assertion that every mutating passthrough has an endpoint source-check | **ADOPT** — converts the deny-list from sole defense to defense-in-depth | code-behind-tests |
| Directive → `(code, display_text)` enum; kill the 0.50 fallback, the FAIR-VALUE collision, `tail[:5]`; key chip/row/prior off the code | **ADOPT** — third audit asking; the sync-guard test makes it mechanical | code-behind-tests |
| Gate φ≥1 behind a sourced floor (`BELOW PROXY FLOOR — VERIFY`); blue-sky ✓/~ tick | **ADOPT** — ships with the enum | code-behind-tests |
| `--disallowedTools` injection into `_job_argv`/`_pipeline_argv` (+ the agy lane, see TF4) | **ADOPT** | code-behind-tests + operator-decision (allowlist) |
| `survival_exempt_archetypes`: decide the value, then land the equality assertion | **ADOPT** assertion; value = **propose→confirm** | mixed |
| Router reorder + did-you-mean; colour step-rounding; collapsed-strip label; "— not sourced" fix | **PILOT** batch | read-only display |

**(e) Next steps.** 1) Explicit `source` on mutating MCP tools + registration-loop assertion.
2) Directive enum refactor (carried third time — do it). 3) φ≥1 proxy-floor gate. 4) Runner
hardening. 5) Exemption decision + assertion. 6) Display pilot batch.

---

## TF2 — Book Construction & Capital Allocation

**(a) First principles.** Unchanged: concentration must be re-earned by contest, and the exit
machinery must actually fire. This sweep adds: **the book's record IS book machinery** — a
rotation gate, an inertia clock, and a payoff learner are all inert if the substrate they read
was never committed.

**(b) Hard questions.** Is every name earning its slot? Still no machine answer — and for six days
the question was *unaskable from the repo*: zero council verdicts ever (confirmed in the restored
57-row store), the one URC.TO decision freeze lost with a sandbox. Could the book rotate if
conviction broke? Still no: the gate remains triple-locked (engine-running refusal, silent REJECT
on null ρ, fail-closed friction), no UNRATABLE verdict shipped. Is the sizer honest about
diversification? It still averages a hardcoded GROY/URC/GMX trio at 0.50-if-missing over a
hardcoded `/3.0` — one import away from `book_tickers(cfg)`, which now exists.

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-02 | Confidence |
|---|---|---|---|---|
| 1 | 0.60 ceiling: centralized, byte-equality-tested; **no new bare literals from the split** | `book_invariants.py:15` + 6 consumers | **FIXED** | VERIFIED |
| 2 | `_redistribute` ×3 copy-pasted bodies "kept in lockstep" by comment (dashboard 4th copy MOOT — retired) | `dynamic_config.py:192` · `mcp_server/core.py:2085` · `book_change.py:33` | PERSISTS (constant fixed, algorithm not) | DELEGATED |
| 3 | Sizer corr: frozen trio, 0.50-if-missing, `/3.0`, phantom-0.50 after remove_holding, no `corr_source` — defect moved verbatim into `engines/sizer.py:204-209`; fix helper (`engines/util.py:203 book_tickers`) unused one import away | `engines/sizer.py:204-209` | PERSISTS + sharpened | DELEGATED |
| 4 | Off-sum barbell fallback still log-only | `engines/util.py:196-199` | PERSISTS | DELEGATED |
| 5 | No thesis-review clock (`entry_date`/`last_review`/`review_cadence` absent); slot-*identity* shipped (`thesis_slot_desc`), slot-*age* not | `v5_config.json:371-443` | PERSISTS (adjacent progress) | DELEGATED |
| 6 | Rotation gate triple-locked; no UNRATABLE verdict (grep=0); null-ρ incumbent still exits as bare REJECT | `mcp_server/core.py:2491` · `council.py:363-364,399-401` | PERSISTS | DELEGATED |
| 7 | Flywheel record: restored store confirms 3 decisions / **0 outcomes / 0 council_verdicts / 0 conviction**, frozen 06-24; URC.TO's 07-02 row lost; catalyst calendar still 4 rows all AGA.V (as_of 06-17) | `data/living_memory.jsonl` (restored) · `data/catalyst_calendar.jsonl` | WORSE (record was untracked; now restored at 06-24 state) | VERIFIED |
| 8 | Payoff learner correct and cold (shrinkage k=6, prior stands at n=0); zero outcome rows | `scenario_engine.py:96,231` | PARTIAL (unchanged) | DELEGATED |
| 9 | WS fill importer: assessment 8 days old, stationary; zero fills ever captured; `slip_max` still "engineering — LOW" | `docs/WS_INTEGRATION_ASSESSMENT.md` · `council.py:326,442` | PERSISTS | DELEGATED |
| 10 | Book composition unchanged: 60/15/15/10; 3 of 4 names still `asset_light_yield`; overlap lens never piloted | `v5_config.json:6-12` | PERSISTS | VERIFIED |
| 11 | Positive: archetype-aware `engine_break` + reason string ends the false break on healthy ballast (the hand-annotated GMX φ0.36 case) | `council.py:144-172,286` | NEW (good) | VERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Keep the stores tracked (restored this session); define the host→repo commit cadence for runtime appends so the record can never silently fork again | **ADOPT** — the precondition for every other TF2 instrument | operator-decision (cadence) |
| Consolidate `_redistribute` ×3 into `book_invariants`/`book_math` with a vector-equality test | **ADOPT** — one PR | code-behind-tests |
| Sizer: derive ballast set from `book_tickers(cfg)`, real count denominator, `corr_source: measured\|default` stamp | **ADOPT** — kills the phantom-0.50 in the same change | code-behind-tests |
| Thesis-review clock fields + "slot un-contested N days" surfacing | **ADOPT** (carried third time) | propose→confirm (fields) / code |
| UNRATABLE rotation verdict (never synthesize ρ) | **ADOPT** (was PILOT; the silent REJECT has now hidden the same fact for three audits) | code-behind-tests |
| Council URC.TO and GROY — first verdict rows, re-freeze URC.TO's lost decision | **ADOPT** as practice | operator-decision |
| WS Activities-CSV importer MVP | **ADOPT** decision this cycle — 3 findings block on it | operator-decision |

**(e) Next steps.** 1) Store cadence decision (operator). 2) Council the two inertia names — this
also re-creates the lost URC.TO freeze. 3) Sizer + `_redistribute` + UNRATABLE batch (code).
4) Review-clock fields (propose→confirm). 5) WS importer decision.

---

## TF3 — Data Provenance & Inputs

**(a) First principles.** Grounded-or-silent at the input boundary; the test for every feed is
"when it fails, can the operator tell?" This sweep adds the store corollary: **the point-in-time
store is an input too** — if the ground-truth stores aren't versioned, provenance has no
provenance.

**(b) Hard questions.** What is a point-in-time discipline worth if the PIT store itself lived
outside version control for six days? Why is the born-LIVE fix one-metric-wide when the defect is
a pattern (`real_yield` seeds `LIVE` two lines below the fixed CFTC comment)? Why does the MRI
honesty scan check the seven metrics-dict inputs and skip the four positional ones that carry the
commodity and real-yield legs? What does the uranium "cliff" actually do — nothing but a flag on
day 46, on a mark that keeps pricing a 60-day-old number forever? Who re-writes the two GROY
look-ahead entries now that the promised load-time validator turned out to be a different guard?

**(c) Current practice & strains.** The STRONG layer holds and grew: restatement-as-event, the
freshness ladder, two-tier spot, catalyst trust hierarchy, sigma widening [DELEGATED, unchanged];
plus new this cycle: last-good-cache-first for copper/gold (largely closing the 2350 distortion),
the store-seam refusal, and the symmetric `reconciled_book_value` guard [VERIFIED].

| # | Strain | Anchor | Status vs 07-02 | Confidence |
|---|---|---|---|---|
| 1 | Ground-truth stores untracked by `83f092c`; only research_cache restored (`3830fed`); `.gitignore` documented "TRACKED" intent unfulfilled; 07-02 live-run rows never committed, lost | `git ls-files data/` pre-restore · `.gitignore:85-91` | **NEW — the sweep headline** (restored this session at 06-24 state) | VERIFIED |
| 2 | MRI: flags shipped but metadata-only (number still computed on silent defaults); bare 45.0 survives the no-detail path; scan covers 7 metrics-dict inputs, **not** the 4 positional ones | `engines/macro_regime.py:340-346,354-360,453-466` | PARTIAL + NEW hole | VERIFIED (seed) / DELEGATED (scan scope) |
| 3 | Born-LIVE: CFTC fixed; `real_yield: 1.0, ry_status: "LIVE"` identical defect two lines above, unfixed | `engine.py:235-236,244-246` | PARTIAL (fix was finding-shaped, not pattern-shaped) | VERIFIED |
| 4 | Uranium stamp US$86.10 as_of 2026-06-04 — 34 days, single-sourced; window trips day 46 (`> 45.0` off-by-one, 2026-07-20); trip = flag + ribbon widening only, mark never recomputes or goes dark | `data/research_cache.json` URC.TO · `nav_mark.py:73-76,137` | PERSISTS + NEW precision | VERIFIED (stamp) / DELEGATED (mechanics) |
| 5 | REP-floor cash/burn `asof 2026-01-21` — **168 days**; AGA cash `as_of 2026-01-29` sourced to a Kitco opinion piece | `v5_config.json:26-28` · research_cache AGA.V | PERSISTS (worse by 6 days) | VERIFIED |
| 6 | GROY hand-edited entries: `"low-med"` out-of-vocab, `as_of` postdates `fetched_at` on BOTH re-rate entries (3-day and 5-day look-aheads in the PIT store); restore did not re-write them; **the promised load-time validator did not ship** — the +42 lines were the (good, different) book-value guard | `data/research_cache.json` GROY:390-431 · `research_cache.py:76-81,98-99` | PERSISTS + corrected attribution | VERIFIED |
| 7 | FRED label drift (config `REAINTRATREARAT10Y` vs code `DFII10` ×5 sites) | `v5_config.json:1034` · `engines/macro_regime.py:185-320` | PERSISTS | DELEGATED |
| 8 | GMX peer mark as_of 2025-09-11 — **~300 days**, still outside `HARD_FLOOR_ARGS`, no `SOFT_VALUE_ARGS` watch shipped | `holdco_nav_feed.py:46,139-146` | PERSISTS | DELEGATED |
| 9 | Ingestion fundamentals leg still configured-but-dormant silent no-op | `engine.py:1977-1990` | PERSISTS | DELEGATED |
| 10 | Currency seam residual: untagged USD name defaults to CAD storage silently; seam refusal is the backstop, not a preventer | `price_history.py:222-223` | NEW (minor) | DELEGATED |
| 11 | Copper/gold: last-good-cache-first shipped; 2350/4.2 now cold-start-only seeds | `engine.py:701-781` | largely FIXED | DELEGATED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Pattern-complete the cold-start honesty: `ry_status: INITIAL_BASELINE`; extend the MRI scan to positional inputs; kill the bare-45.0 path | **ADOPT** — finishes a fix now 4/7 shipped | code-behind-tests |
| Ship the actual load-time validator (confidence ∈ vocab, `as_of ≤ fetched_at+ε`); re-write the two GROY entries through `set()` | **ADOPT** / re-write = **propose→confirm** | mixed |
| Uranium: second reference (Sprott U.UN NAV-implied / Numerco) read-only before 07-19; fix the `>` off-by-one; decide whether day-46 should widen sigma harder or hold the NAV leg | **ADOPT** pilot; behavior = **propose→confirm** | mixed |
| Cash/burn + AGA cash refresh from the two filed Silver47 quarters, sourced to SEDAR+ (not Kitco) | **ADOPT** — the board's highest information-per-edit, now fused to the waiver clock | propose→confirm |
| FRED label; GMX peer `SOFT_VALUE_ARGS` watch; currency-tag requirement for non-CAD adds | **ADOPT** batch | propose→confirm / code |
| Ingestion fundamentals leg: schedule or mark dormant | operator must finally choose | operator-decision |

**(e) Next steps.** 1) Cash refresh before the waiver decision (the dependency, see TF5). 2)
Cold-start pattern-complete (code). 3) Validator + GROY re-write. 4) Uranium pilot before 07-19.
5) FRED/peer-watch/currency batch. 6) Ingestion decision.

---

## TF4 — Research Production & the Agentic Layer

**(a) First principles.** Engine owns the reproducible; agents own the contested; the human owns
mutation. This sweep adds: **the boundary must hold for every lane, not just the default one** —
a capability cage enforced in `.claude/agents/*.md` governs exactly the agents that read those
files, and nothing else.

**(b) Hard questions.** What is the deny-list worth when two research seats run on a CLI that, in
the code's own words, "carries none of the .claude subagent contract"? Why can any subagent move a
ballast's NAV anchor with one tool call and one URL when every tunable needs a human confirm —
which mutation is more rating-proximate? Why does the desk's best forensic catch (the GROY $1B
rejection, now richly structured in the cache) still have no Memory mirror — and for six days, no
Memory to mirror into? Is a prompt-enforced output contract a contract, or a request?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-02 | Confidence |
|---|---|---|---|---|
| 1 | `council_reconcile` shipped, read-only, provenance weighting reachable end-to-end | `mcp_server/core.py:2673` · `council.py:63,122` · `arbiter.md:35-46` | **FIXED** | VERIFIED |
| 2 | Flywheel: store was untracked (not merely frozen); restored at 57 rows — 0 council_verdicts ever, capture hook never fired; URC.TO's only decision row lost with the 07-02 sandbox | `data/living_memory.jsonl` (restored) · `83f092c` | WORSE → substrate restored, record still cold | VERIFIED |
| 3 | `set_nav`: direct write to the fair-value anchor, no proposal, no confirm, no deny-list entry; gate = any `source_url` | `mcp_server/core.py:667-688` | **NEW** | VERIFIED |
| 4 | Gemini lane bypasses the manifest closure entirely (`agy -p`, env-overridable, no tool restriction); scout contract prompt-only — tests pin the *prompt*, nothing validates the *output* | `commodityex_tui.py:6448-6480,7373-7382` · `test_scout_output_contract.py` | **NEW** | VERIFIED |
| 5 | `memory_write` still has no `provenance` param — `living_memory.py:152` now accepts+validates it, the MCP surface never passes it; agents still can't ground above `agent` | `mcp_server/core.py:1051,1086` | PERSISTS (half-built) | DELEGATED |
| 6 | No `research_cache.verify()` API; sourcer≠verifier enforced nowhere; bare-bool `verified` still passes (`bool(_ver)` branch); GROY rejection structured in cache but unmirrored | `holdco_nav_feed.py:199-204` · `research_cache.py` | PERSISTS (cache entry itself improved) | VERIFIED (entry) / DELEGATED (branch) |
| 7 | `graduate_candidate` auto-resolve: any-vintage receipts, no ts/run-tag check | `mcp_server/core.py:1805-1826` | PERSISTS | DELEGATED |
| 8 | Headless runner unhardened (see TF1 #10); `CEX_JOB_CMD` and now `CEX_AGY_*` both env-overridable | `commodityex_tui.py:2803-2837` | PERSISTS + widened | VERIFIED |
| 9 | Sourcing-seat independence: partially documented (read-only framing), explicit sourcer-never-verifies rule still unwritten | `value-analyst.md:11-30` · `balance-sheet-analyst.md:11,29` | PARTIAL | DELEGATED |
| 10 | Registration loop: no Claude-side capability drift (only `council_reconcile` added; mutating tools all gated or denied — except `set_nav`) | `server.py:61-136` | HOLDS | DELEGATED |
| 11 | Positive: canvas seat-truth + heavy-ask timeout both close silent-failure seams (wrong-model advertising; killed councils that never wrote verdicts) | `cockpit_widgets.py:1264+` · `hub_gist.py` | NEW (good) | DELEGATED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Gate `set_nav`: route through `/config/propose` (or a verify-before-wire check requiring an independent verifier), add to deny-lists meanwhile | **ADOPT** — the sharpest open write path | code-behind-tests + operator-decision (deny) |
| Close the gemini lane: inject tool restrictions into `_agy_argv` (the `_inject_model_flags` pattern exists); enforce caller-identity gating at the `core.py` layer so the cage doesn't depend on which CLI reads which manifest; add a code-level scout-output validator | **ADOPT** | code-behind-tests |
| `research_cache.verify()` API: dict-verdict-with-receipts, sourcer≠verifier refusal, deprecate `bool(_ver)`; mirror verdicts to Memory as a byproduct; backfill the GROY rejection as the first `verification` entry | **ADOPT** / backfill = **propose→confirm** | mixed |
| Finish `memory_write(provenance=…)` — the store already validates it; pass it through, agent-capped at `sourced` | **ADOPT** (was PILOT; it is now a 3-line change) | code-behind-tests |
| Graduation freshness + run-tag binding | **ADOPT** | code / propose→confirm (max-age) |
| Runner hardening (`--disallowedTools` + agy equivalent; allowlist env overrides) | **ADOPT** (carried third time) | code + operator-decision |

**(e) Next steps.** 1) `set_nav` gate. 2) Gemini-lane closure. 3) `verify()` + Memory mirror +
GROY backfill. 4) `memory_write` provenance pass-through. 5) Runner hardening + graduation
freshness.

---

## TF5 — The Conviction & Valuation Framework

**(a) First principles.** The rating earns trust two ways: inputs real, outputs graded. Both
halves are now in the same week-shaped hole: the inputs' freshest survival-critical number is 168
days old, and the grading half reaches its first maturity date (**07-12**) with a substrate that
was, until this session, not in the repo at all.

**(b) Hard questions.** Will the desk *choose* the waiver outcome or default into it — seven days
out, the justification is still the word PLACEHOLDER? What does a dilution gate protect when its
runway test runs on January cash — 19.3 months on paper, ~13.8 at the config's own burn?
Will 07-12 produce grades, or a shrug — the ledger and price store were untracked; even restored,
grading needs a running heartbeat and a `repair_currency`-checked store on the host? Is the
fair-value ratchet's up-bias now *evidence-backed* scar tissue (the crush guard proved symmetric
guards are buildable) or still an unexamined preference for the higher number — the goodwill
review went the *other* way (goodwill=0 re-sourced to harden HIGH, not down-tiered to MED)?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-02 | Confidence |
|---|---|---|---|---|
| 1 | Waiver: verbatim PLACEHOLDER, expiry 07-15; on 07-16 both waivers die fail-closed; CBA re-tests (fail = −1.0 JSF + explorer penalty ≈ −6.5% intrinsic); dilution passes only via ≥18 mo runway — computed on the stale January cash | `v5_config.json:951-957` · `engines/forensic.py:242-261,321-404` | PERSISTS — **7 days, undecided** | VERIFIED |
| 2 | Runway fiction: paper 53.07/2.75 = 19.3 mo; implied treasury after 5.5 months of config burn ≈ CAD 37.9M → **~13.8 mo, below the 18-mo bar**; the gate will pass on numbers reality has left | `v5_config.json:14,26-28` · `engines/forensic.py:373-404` | PERSISTS, now decision-critical | VERIFIED (inputs) / arithmetic by lead |
| 3 | Grading substrate: ledger+price store were untracked; restored this session at 06-24 state (3,311 rows incl. the 81 phantoms; ≤10 closes/name); 07-02 live rows lost; backfill script fixed twice but never run; whether the host can grade on 07-12 is unknowable from here | `data/valuation_ledger.jsonl` · `data/price_history.json` (restored) | WORSE → partially recovered | VERIFIED |
| 4 | GROY grading hazard: store-seam refusal will *exclude* GROY from first grades if the host store holds unrepaired USD closes; the restored snapshot is CAD-scale (checked: ~4.0), but the host store's state is unknown — run `repair_currency` dry-run before grading either way | `replay.py:150-194` · `price_history.py` | NEW | VERIFIED (mechanism + snapshot) / COULD-NOT-VERIFY (host) |
| 5 | Zero-intrinsic guard + read-side phantom exclusion shipped; **material_change hysteresis (item F) did not** — 3-decimal rounding is still the only damper on the 74% GROY thrash pattern | `valuation_ledger.py:237-243,296-297` · `replay.py:187-190` | PARTIAL | VERIFIED (guard) / DELEGATED (no-hysteresis) |
| 6 | Fair-value ratchet intact (floor-only-higher `engine.py:3040-3047`; re-rate only-UP, blue-sky additive, anti-crush MED asymmetry `holdco_nav.py:270-365`); no down-path/re-confirm shipped; nuance: the new `reconciled_book_value` guard IS symmetric and pinned both directions — proof the desk can build bidirectional guards when the rule is *units*, not *confidence tiers* | `holdco_nav.py` · `research_cache.py:29-68` | PERSISTS, critique sharpened | VERIFIED |
| 7 | GROY goodwill=0 → full US$722M equity at HIGH: re-sourced (XBRL, later fetched_at) to *reinforce* HIGH; the 93%-acquired-interests materiality concern unaddressed; MED down-tier pilot not run | research_cache GROY · `holdco_nav.py:259-268` | PERSISTS (moved away from the pilot) | VERIFIED (entry) / DELEGATED (materiality) |
| 8 | T-pillar tape leak: `alpha_option.vol_edge 0.35`, `weak_usd` in cyclical/delta — unstripped; alphas still in `engine.py` (not moved by the split) | `engine.py:1175-1214` | PERSISTS | DELEGATED |
| 9 | `conviction_lift` 0.65 ungraded on `max(Q,V)`; `support_curve` linear — deferral pending first grades remains correct | `asymmetry_rating.py:299,850` · `v5_config.json:607-609` | PERSISTS (correctly) | DELEGATED |
| 10 | `update_beta` still pure-and-ephemeral; no posterior store anywhere — from 07-12, graded outcomes would evaporate | `base_rates.py:301-314` | PERSISTS | VERIFIED |
| 11 | engines/ split faithful on the conviction path (JSF/waiver/re-rate spot-checks byte-for-behavior) | `engines/forensic.py:273-414` | HOLDS | DELEGATED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| **Decide the waiver by 07-14, cash-first**: refresh treasury/burn from the two filed quarters, THEN choose — sourced basis + short expiry, or conscious lapse with the honest JSF/intrinsic haircut; record either to Memory | **ADOPT** — the board's only 7-day item; the lapse decision is only honest against current cash | propose→confirm + operator-decision |
| Pre-07-12 grading readiness: host `repair_currency` dry-run; run the backfill; keep the heartbeat up with the stamp-guard in place; publish first grades with small-n CIs and `data_limited` | **ADOPT** | data-store write / operator (ops) |
| Designate the `update_beta` posterior store (a `data/learned_priors.json` with provenance) before first grades exist | **ADOPT** — 3 files touch it; without it 07-12 produces numbers that vanish | code-behind-tests |
| material_change min-delta (item F) before sustained running | **ADOPT** | propose→confirm (threshold) |
| Goodwill-classification pilot ("0 goodwill but ≥X% acquired mineral interests ⇒ MED") — read-only analysis with the ratchet-symmetry audit; document down-paths, don't reflex them (the crush risk is real and re-proven by the guard history) | **PILOT** | read-only → propose→confirm |
| T-pillar strip; retune lift/weights/bands | **ADOPT** strip (display-first) / **REJECT** retune until grades | propose→confirm / — |

**(e) Next steps.** 1) Cash refresh → waiver decision, in that order, before 07-14. 2) Grading
readiness on the host (repair_currency, backfill, heartbeat). 3) Posterior store. 4) Hysteresis.
5) Goodwill + symmetry pilots after first grades.

---

## Cross-Cutting Matrix

| Tension | Upstream | Downstream | Who co-signs |
|---|---|---|---|
| **The store fork** — runtime truth lives on one host, committed truth in the repo, and for six days they silently diverged | The Tier-2 untracking (83f092c); no host→repo cadence | Every TF: TF2's inertia question unaskable, TF5's 07-12 grades substrate-less, TF4's Memory mirror had nothing to mirror into, TF3's PIT discipline void. Restored this session at 06-24 state; the *cadence* decision remains | Operator (cadence) + TF3 (store invariants) |
| **One stale number decides the spear's gate** | TF3: cash/burn asof 01-21 (168d) | TF5: 07-16 dilution pass rides a 19.3-mo paper runway vs ~13.8 real | TF3 refreshes; TF5 owns the consequence; operator decides the waiver — **cash-first or the decision is fiction** |
| **The letter-not-invariant fix pattern** | TF1/TF3: each fix scoped to the finding's wording (CFTC-only, endpoint-only, metadata-only, rail-only) | The invariant each fix defended still leaks one layer over (real_yield LIVE; MCP source-default; MRI number; φ≥1 directive) | Fix authors: every close names the *pattern* it instances and greps for siblings before shipping |
| **Two doors outside the cage** | TF4: `set_nav` ungated; gemini lane manifest-blind | TF1's confirm architecture and TF5's NAV-anchored valuations are both bypassable without touching a guarded path | TF4 gates; TF1 endpoint-source assertion; operator signs the deny/allow lists |
| **The ratchet vs the crush guard** | TF5: up-only confidence-tier rules; but the units guard is symmetric and pinned | The lift amplifies ratcheted anchors; yet the desk demonstrably CAN build bidirectional guards — the asymmetry is a choice that should be argued, not inherited | TF5 pilots (goodwill, symmetry audit) after first grades |
| **Operator-gated items have no clock** | 8/8 surfaced items undecided in 6 days; 3 expire this week | Automatic-by-default outcomes at the largest position | Operator; the cockpit should surface gated-item age the way it surfaces data staleness |

---

## Sequenced Program

Ordering: **the week's clocks first, then the two open doors, then the store discipline, then the
carried refactors.**

### Phase 0 — Before the clocks (by 07-14)
| # | Step | Source | Gate |
|---|---|---|---|
| 0.1 | Refresh AGA.V treasury/burn from the two filed Silver47 quarters (SEDAR+ receipts) | TF3↔TF5 | **propose→confirm** |
| 0.2 | **Decide the waiver** on the refreshed numbers; record the branch to Memory | TF5 | **operator-decision** |
| 0.3 | Host grading readiness: `repair_currency` dry-run, backfill, heartbeat with guard; commit the runtime stores back (cadence decision) | TF5↔TF2 | data-store / **operator-decision** |
| 0.4 | Uranium second-reference pilot + fix the day-46 off-by-one | TF3 | read-only / code |

### Phase 1 — Close the two open doors
| # | Step | Source | Gate |
|---|---|---|---|
| 1.1 | Gate `set_nav` (propose-route or verify-before-wire); deny-list meanwhile | TF4 | code + **operator-decision** |
| 1.2 | Gemini lane: tool restrictions in `_agy_argv`; caller-identity gating in core; code-level scout output validator | TF4 | code-behind-tests |
| 1.3 | Explicit `source` on mutating MCP tools + registration-loop source-check assertion | TF1 | code-behind-tests |
| 1.4 | `--disallowedTools` into `_job_argv`/`_pipeline_argv` + agy equivalent; allowlist env overrides | TF1↔TF4 | code + **operator-decision** |

### Phase 2 — Pattern-complete the honest-inputs layer
| # | Step | Source | Gate |
|---|---|---|---|
| 2.1 | `ry_status` INITIAL_BASELINE; MRI scan over positional inputs; kill bare-45.0 | TF3 | code-behind-tests |
| 2.2 | research_cache load-time validator; re-write the two GROY look-ahead entries through `set()` | TF3 | code / **propose→confirm** |
| 2.3 | `research_cache.verify()` + sourcer≠verifier + Memory mirror; backfill the GROY rejection | TF4 | code / **propose→confirm** |
| 2.4 | `memory_write(provenance=…)` pass-through; graduation freshness binding | TF4 | code / **propose→confirm** |
| 2.5 | FRED label; GMX peer staleness watch; currency-tag requirement | TF3 | **propose→confirm** / code |

### Phase 3 — The carried refactors (third audit)
| # | Step | Source | Gate |
|---|---|---|---|
| 3.1 | Directive → (code, display_text); φ≥1 proxy-floor gate; collision + fallback fixes | TF1 | code-behind-tests |
| 3.2 | Sizer book-derived corr + `corr_source`; `_redistribute` consolidation; UNRATABLE verdict; loud off-sum fallback | TF2 | code-behind-tests |
| 3.3 | `survival_exempt_archetypes` decision + assertion | TF1↔TF2 | **propose→confirm** + code |
| 3.4 | Posterior store for `update_beta`; material_change hysteresis | TF5 | code / **propose→confirm** |

### Phase 4 — Warm the loop & re-contest (from 07-12)
| # | Step | Source | Gate |
|---|---|---|---|
| 4.1 | First grades with small-n CIs + `data_limited`; persist posteriors | TF5 | read-only → designed flywheel |
| 4.2 | Council URC.TO and GROY — first verdict rows; re-freeze the lost URC.TO decision | TF2↔TF4 | **operator-decision** |
| 4.3 | Thesis-review clock; WS CSV importer MVP decision | TF2 | **propose→confirm** / **operator-decision** |
| 4.4 | With grades: goodwill pilot, symmetry audit, T-pillar strip, depth-curve proposal | TF5 | read-only → **propose→confirm** |

---

## Preserved dissent & could-not-verify

**Dissent, preserved:**
- **The Tier-2 untracking was not malicious and had a real motive** — the ledger was the largest
  blob in git history (~6 MB) and runtime stores churn every cycle. The counter-position (adopted
  here, following the desk's own `.gitignore` declaration and the `3830fed` precedent) is that
  non-regenerable accumulated state belongs in version control regardless of size. If the operator
  prefers the ledger out of git, the honest alternative is an explicit, documented host-backup
  path — not an untracked file and a comment claiming it is tracked.
- **Restoring the stores at the 06-24 snapshot is itself a judgment call.** If the operator's host
  holds newer copies, the host state supersedes on its next commit (append-only files reconcile
  forward). The restore makes the repo honest about what it can prove; it does not claim to be the
  freshest truth.
- **The ratchet critique remains contested by its own history** (the GMX false-TRIM rollback; the
  crush guard's deliberate refusal to force GROY's producing-CF floor). The new evidence cuts both
  ways: the units guard proves symmetric guards are buildable; the goodwill re-source shows the
  desk reaching for the higher-confidence higher number when given the chance. Routed to pilots,
  not reflexes.
- **Letting the waiver lapse is still a defensible branch** — with refreshed cash it may be the
  *honest* branch (the gate should arguably fail at ~13.8 months). The indefensible outcome is the
  silent default on stale inputs.
- **The gemini lane's freedom is partly deliberate** — it exists precisely because the agy CLI is
  a differently-authenticated, differently-capable backend. The finding is not "shut the lane" but
  that its *cage* must be enforced somewhere the lane actually passes through (argv or core), not
  in manifests it never reads.

**Could not verify (blockers stated):**
- **The operator's host state**: whether newer Living Memory/ledger/price-history rows exist
  locally; whether `backfill_price_history.py`/`repair_currency()` were run; whether the heartbeat
  is up. Everything graded here is the committed tree.
- **Live behavior**: no engine run this session — worker displacement of the `ry_status` seed,
  live floor_degraded states, and the eval-loop serialization were not re-observed.
- **DELEGATED rows above**: reported by scans with quoted code; the lead re-verified every
  headline and every money-relevant mechanic (the four new findings, the clock items, the store
  restore) but did not re-read every supporting anchor line-by-line.
- **Test-suite green**: commit messages claim 1704/1712 passing; not executed this session.

**Session hygiene note:** this session executed exactly one change beyond this document: restoring
`data/living_memory.jsonl`, `data/valuation_ledger.jsonl`, and `data/price_history.json` from the
last tracked snapshot (`83f092c^`, state as of 2026-06-24), completing the restore that `3830fed`
began and the `.gitignore` block already declares. Nothing in `v5_config.json`, the book, any
tunable, or any agent manifest was changed. Every recommendation touching them is marked
propose→confirm or operator-decision and is NOT done. When a claim here conflicts with the tree,
the tree wins — re-grep, re-verify, report the correction.*
