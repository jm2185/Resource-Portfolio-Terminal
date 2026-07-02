# CommodityEx — Standing Reassessment (2026-07-02)

*A five-task-force sweep of the research cockpit under the standing charter, edited into one
verdict. **The engine was run LIVE this session** (a first for these sweeps) in a sandboxed cloud
environment: dependencies installed, engine booted on :8000, full test suite executed (**1644
passed, 1 skipped**), and live `/state` polled repeatedly. The sandbox proxy degraded outbound
feeds (Yahoo rate-limited, FRED intermittent), so live observations are scoped to what they truly
test — **how the engine labels itself under feed failure** — and per-name live marks stayed
unavailable (`conviction_mode.baskets = 0` throughout; see Could-Not-Verify). Everything else is
mechanisms read from code/config/data, re-verified line-by-line. Nothing tunable/book/config was
changed; every recommendation touching them is marked propose→confirm or operator-decision and is
NOT done.*

*Method: five parallel deep scans (one per task force), each briefed to re-grade every 06-26
finding (FIXED / PERSISTS / WORSE / PARTIAL) and to audit the 13 post-06-26 commits from first
principles. Every headline finding was independently re-verified by the lead before shipping —
tags below are **VERIFIED** (lead re-read the code/data), **DELEGATED-UNVERIFIED** (a scan reported
it; the lead did not independently re-read), or **COULD-NOT-VERIFY** (blocker stated). Gate tags
are binding: read-only · code-behind-tests · propose→confirm · operator-decision.*

---

## Executive Verdict

Since 06-26 the desk shipped exactly one phase of its own program (Phase 0: the four read-only
audits and the directive↔Council sync guard) and then built something new and good instead — the
verify-before-wire seam that caught and rejected the GROY $1B re-rate. **Every load-bearing hole
named on 06-26 is still open**, several are now time-critical, and this sweep found one new
structural hole bigger than anything it re-confirmed. Four findings dominate:

**1. The propose→confirm gate is hard on the propose side and open on the confirm side (TF1 —
VERIFIED, new).** `set_param` force-routes every agent write to the proposal queue
(`mcp_server/core.py:639-655`) and `/config/param` refuses non-cockpit sources
(`engine.py:6690-6694`) — but `confirm_param_change` is itself an exposed MCP tool with no source
check (`mcp_server/server.py:237-239`), `/config/confirm` trusts a self-declared
`body.get("source", "cockpit")` (`engine.py:6745`), `dynamic_config.confirm()` checks nothing
(`dynamic_config.py:313-322`), and no agent manifest denies it (`.claude/agents/*.md:5` denies only
`set_param`). An agent can propose and self-confirm a tunable in two calls. `remove_holding` and
`promote_to_eval` self-confirm on the same channel — the "user approves the write plan" step is
conversational protocol, not mechanism. The house's single most important invariant — human owns
the trigger — is enforced everywhere except at the trigger.

**2. The 06-26 program stalled after Phase 0, and the clock has caught up with three of its
holes (TF3/TF5 — VERIFIED).** The AGA.V placeholder forensic waiver on the 60% spear is now **13
days from expiry** (2026-07-15, `v5_config.json:951-957`); expiry mechanics are fail-closed
(`engine.py:1236,1294`; pinned by `tests/test_v5_engine.py:535-543`), so on that date the real
dilution/CBA tests silently re-engage against a placeholder-documented position — resolution
becomes automatic-by-default rather than decided. The REP-floor cash/burn inputs are now **162
days stale** (`monthly_burn_rate_asof: "2026-01-21"`, `v5_config.json:28`) with two Silver47
quarters likely filed since. The uranium stamp (as_of 2026-06-04) crosses its own 45-day staleness
cliff on **2026-07-19** with no second source piloted. And the calibration flywheel is frozen:
`data/living_memory.jsonl` has **zero writes since 2026-06-24** — still 3 decisions, 0 outcomes, 0
council verdicts, 0 conviction readings — while 13 commits of real research (the entire GROY
re-rate saga) left no Memory trace at all.

**3. The regime layer's fabrication surface was observed live this session — it is worse than
the 06-26 write-up (TF3 — VERIFIED, live).** The MRI fail-closed fix never shipped:
`calculate_mri` still silently defaults all seven sub-inputs (`engine.py:617-623`) and returns a
confident `45.0` on any exception (`engine.py:719`). New precision from the live run: the
`state_cache` cold-start initializes `"cftc_net_longs": 35000.0, "cftc_status": "LIVE"`
(`engine.py:2462-2463`) — the fabricated default is **born badged LIVE**, and the honest
`INITIAL_BASELINE` badge (`engine.py:2522`) lives in a parallel dict the eval loop overwrites
(`engine.py:5534→5644`). Observed running: the CFTC worker synced the **real** net-spec number
(+23,389 — 33% below the default) early in the boot, yet `/state` kept serving
`{"value": 35000.0, "status": "LIVE"}` with `data_freshness.cftc.age_seconds ≈ 0.1` for roughly
**50 minutes**, until an eval cycle finally displaced it — the freshness stamp records "worker
wrote", not "real data arrived", and slow feeds head-of-line block the cycle that would correct
it. The desk's own price workers were
re-engineered to "NEVER a fabricated constant"; the regime layer still fabricates with a LIVE badge.

**4. The one new mechanism is the right pattern with convention-grade plumbing (TF3/TF4 —
VERIFIED).** Verify-before-wire genuinely fails closed in code — three independent gates
(`holdco_nav.py:238,284-292`, `holdco_nav_feed.py:200-201`), 194 lines of test pin
(`tests/test_royalty_rerate.py`), and it already caught a live ~38% valuation error (the GROY $1B
rejected; anchor stayed at audited $3.13). But the `verified` bit has **no API** — it was
hand-edited into `data/research_cache.json`, bypassing `set()`'s vocabulary and stamps: an
out-of-vocabulary `"confidence": "low-med"`, a shared round `fetched_at` = 2026-06-27T00:00:00Z,
and one entry whose `as_of` (2026-07-02) **postdates its own fetched_at** — a look-ahead seam in
the point-in-time store. Nothing checks who verified; a bare `"verified": true` bool passes
(`tests/test_royalty_rerate.py:148-149`); the rejection is invisible to `memory_query` and to the
graduation gate. The desk built the right gate and then walked around its own store to feed it.

**The through-line:** the structural cage and the test discipline are excellent and getting better
(1644 tests green; the sync guard, the anti-crush gate, and verify-before-wire are all real,
pinned mechanisms). What is failing is **follow-through and symmetry**: programs stall after their
free phase; write-discipline is enforced in the API and bypassed by hand; propose is mechanical
and confirm is conversational; the engine labels its inputs honestly at birth and dishonestly one
layer up. In a concentrated book the expensive failure is still false confidence — and the places
it leaks are now enumerated to the line.

---

## What the live run added (unique to this session)

The operator authorized installing dependencies and running the engine. Grounded observations,
each scoped to what a degraded-feed sandbox can honestly test:

- **Boot honesty is bimodal (VERIFIED, live).** `macro_regime: "Pending Data..."` and global
  `status: DEGRADED_STALE` are honest; simultaneously every per-feed badge in `data_freshness`
  read `LIVE / stale:false / age≈0.1s` while the log showed CFTC erroring, FRED timing out, and
  Yahoo returning 429 — the per-feed stamp measures worker write-time, not data arrival.
- **The CFTC born-LIVE default (finding 3 above)** — cold-start `35000.0/LIVE` at
  `engine.py:2462-2463`; the real synced `+23,389` took ~50 minutes to reach `/state`, during
  which the fabricated default was served badged LIVE.
- **MRI computed confidently on partial defaults (VERIFIED, live):** first cycle `mri: 39.4` with
  `drivers.cftc_positioning: 50.0` and `drivers.silver: 50.0` (neutral defaults) blended
  indistinguishably with real reads (VIX 16.5, DXY 99.0) — no `degraded` flag anywhere in
  `mri_decomposition`. After full warm: `mri: 37.6`, regime `Expansion / Risk-On`.
- **Three of four held names are running `floor_degraded: True` RIGHT NOW, and the cockpit shows
  none of it (VERIFIED, live — the TF1 headline made flesh):** live baskets after warm-up:
  URC.TO `7.41 HIGH QUALITY — QUALITY — CORE HOLD` with `floor_degraded: True` **and**
  `quality_proxy_only: True`; GROY `7.24` and GMX.TO `6.98` both `floor_degraded: True`; only
  AGA.V's floor is sourced. The operator's screen renders all four identically clean. (Caveat:
  this session's feeds were degraded, which is plausibly *why* the flags are set — but that is
  precisely the condition under which the operator most needs to see them.)
- **The eval loop is head-of-line blocked by slow feeds (live observation; exact mechanism
  COULD-NOT-VERIFY):** for ~50 minutes after boot, `conviction_mode.baskets = []` and
  `v4_valuation = {}` while serialized macro-fetch timeouts kept the full valuation/rating cycle
  from completing — stale-or-default metrics served as LIVE the whole time. A production transient
  feed outage would reproduce this shape.
- **The live run gave the post-06-25 valuation base its first point-in-time record:** 4 new
  ledger rows stamped under today's sha (`1403ff4`) — before this session, every valuation-base
  commit since 06-25 postdated the last ledger row (06-24, sha `197ef6c`) and was therefore
  unrecorded, not merely ungraded (TF5).
- **The heartbeat, once running, feeds the flywheel exactly as designed (VERIFIED, live):** the
  restarted engine deterministically froze **URC.TO's first-ever decision row**
  (`2026-07-02T16:41:18Z`, source `engine-flywheel`, `QUALITY — CORE HOLD @ 4.82`) — the first
  Living Memory write since 06-24 and the store's **first non-None `provenance`** value. TF2's
  "URC.TO has never been decision-frozen" was true for the preceding 8 days and is remedied as of
  this session; the finding it supports (the loop starves whenever the engine is off) stands.
- **The test suite is green at full depth (VERIFIED, live):** `1644 passed, 1 skipped` — every
  "code-behind-tests" gate tag below is real, not aspirational.

---

## TF1 — Signal & Communication

**(a) First principles.** The signal layer is the cockpit's contract surface: engine facts
(T/Q/V, ρ/φ, JSF, ladder, regime) become a glance-trustworthy verdict, and operator language
becomes gated action. Two irreducible obligations: every rendered number carries its own
confidence (a sourced floor must not look like a proxy floor; a verified blue-sky must not look
like a scenario guess; an engine directive must not look like a Council verdict), and every state
mutation passes a *mechanical* human gate, not a conversational one.

**(b) Hard questions.** Why can an agent apply its own proposal — the A2.2 audit hardened
`/config/param` against agent sources and left `/config/confirm` source-blind one route below it?
What is a fail-closed provenance flag the operator cannot see — `floor_degraded` is computed,
commented "→ render 'pending'" (`engine.py:5349`), and honored by exactly one consumer
(`bench.py:70`), which covers the watchlist bench and not one of the four held names? Why does the
new VALUE LADDER print a med-confidence peer mark and a high-confidence audited book identically?
Why does the blue-sky line render the spear's *scenario* bull and GROY's *verified* increment in
the same teal, when the engine spent a commit series building exactly that distinction? Why is
the directive still a prose string parsed by keyword in **three** places?

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 06-26 | Confidence |
|---|---|---|---|---|
| 1 | `confirm_param_change` exposed MCP tool, no source check anywhere in the chain; `remove_holding`/`promote_to_eval` self-confirm on the same channel | `mcp_server/server.py:237-239` · `engine.py:6739-6745` · `dynamic_config.py:313-322` · `.claude/agents/*.md:5` | **NEW** | VERIFIED |
| 2 | `floor_degraded`/`quality_proxy_only` computed on every rating, rendered nowhere in the TUI (zero grep hits); the redesigned rail ladder prints `floor $X φY.YY fair $Z +N% blue-sky $W` with no degraded/confidence tell | `asymmetry_rating.py:885,889` · `commodityex_tui.py:4166-4189` · sole consumer `bench.py:70` | PERSISTS (unflagged surface count **grew** with the rail redesign) | VERIFIED |
| 3 | φ≥1 `BELOW FLOOR — ACCUMULATE` directive fires without checking the floor is real | `asymmetry_rating.py:802-803` | PERSISTS | VERIFIED |
| 4 | Directive is prose keyword-parsed in three places (council prior, stance chip, book row); runtime fallback still a **silent 0.50**; FAIR-VALUE≡0.50 collision pinned-but-unfixed; but rename drift now breaks CI | `council.py:104-109` · `commodityex_tui.py:312-335,4587` · `tests/test_directive_council_sync.py:79-125` | PARTIAL (guard shipped 06-26; refactor not) | VERIFIED |
| 5 | Council strip: expanded view now labels the ARBITER line "(engine directive)" and says "No Council verdict yet — run /council" — honest; the **collapsed** strip still puts the raw directive in the verdict slot, distinguished only by colour | `commodityex_tui.py:10591,10649-10656` | PARTIAL | VERIFIED |
| 6 | Colour band flips on a 0.01 internal wobble (display now 1dp; colour still keyed to the 2dp value against hard thresholds) | `conviction_health.py:23-29` · `asymmetry_rating.py:894` | PERSISTS (colour) / PARTIAL (precision) | VERIFIED |
| 7 | Router: first-match keyword rules, silent orchestrator fallback on miss; "runway" still routes to balance-sheet before the sentinel by list order | `commodityex_tui.py:757-775,9875-9883` | PERSISTS | VERIFIED |
| 8 | Forensic-exemption divergence — config `["asset_light_yield"]` vs code default `+compounder,deep_value`; the merge makes **config win** (`merge_conviction_config` flat-updates), so the conventional-core lane the code intends to exempt gets burn-gated whenever the engine passes v5_config; no load-time assertion | `v5_config.json:761-763` · `asymmetry_rating.py:317,383-387` | PERSISTS (now understood to be behavioral, not cosmetic) | VERIFIED |
| 9 | New rail mislabels: a sourced bull ≤ base×1.02 renders "— not sourced"; the stance-chip fallback prints `tail[:5]` garbage on an unknown directive | `commodityex_tui.py:4183-4189` · `:334-335` | NEW (minor) | VERIFIED / DELEGATED-UNVERIFIED (chip fallback) |
| 10 | Positive pattern to copy: the ↻rerate chips DO carry provenance (`↻rerated/↻pending/↻cost`) | `commodityex_tui.py:4206-4211` · `asymmetry_rating.py:920-931` | NEW (good) | DELEGATED-UNVERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Source-check `/config/confirm` mirroring `engine.py:6690-6694`; deny `confirm_param_change` (and the self-confirming write tools) in agent manifests, keeping the cockpit `c`/`/confirm` route as the human channel | **ADOPT** — closes the sweep's top finding; ~10 lines plus manifest edits | endpoint guard = code-behind-tests; agent deny-list = operator-decision |
| Directive → `(code, display_text)`; council prior, stance chip, book row key off the code; nudge FAIR VALUE off 0.50; loud runtime fallback | **ADOPT** — three keyword parsers collapse to one enum; the sync guard makes the refactor mechanical | code-behind-tests |
| Render `floor_degraded`/`quality_proxy_only` on rail + detail card (copy the ↻rerate chip pattern); blue-sky `✓verified` vs `~scenario` tick | **ADOPT** (flags + blue-sky tick) / **PILOT** (fair-value confidence — judge rail clutter) | read-only display |
| Gate φ≥1 directive behind a sourced floor (`BELOW PROXY FLOOR — VERIFY` when degraded) | **ADOPT** — ships naturally after the directive-code change | code-behind-tests |
| Load-time equality assertion on `survival_exempt_archetypes`; separately file the value question (should compounder/deep_value be exempt in config?) | **ADOPT** assertion; value = **propose→confirm** | code-behind-tests / propose→confirm |
| Router: reorder `liquidity-runway` above bare `runway`; pilot a one-line did-you-mean on miss | **ADOPT** reorder / **PILOT** clarifier | code-behind-tests / operator-decision |
| Colour-band step-rounding (`health_color(round(r*4)/4)`); collapse the no-verdict Council debate to the directive line | **PILOT** both | read-only display / operator-decision |
| Rating constants pending the flywheel | **KEEP-AS-IS** | n/a |

**(e) Next steps.** 1) Close the confirm hole (guard + deny-list). 2) Directive→(code,text)
refactor. 3) Render the provenance flags + blue-sky tick. 4) Gate the φ≥1 directive. 5) Exemption
equality assertion. 6) Router reorder + clarifier pilot. 7) Display pilots (colour quantization,
collapsed council line, `— not sourced` and `tail[:5]` fixes).

---

## TF2 — Book Construction & Capital Allocation

**(a) First principles.** A concentrated barbell earns its concentration only if every slot is
periodically re-contested and the exit machinery actually works when conviction breaks. Membership
is correctly data (`barbell_weights` keys); the 60% ceiling is correctly a non-configurable
invariant. But a cage with no review clock, a rotation gate that cannot compute its own edge, and
a flywheel with zero closed outcomes makes holding-by-inertia the default outcome, not an accident.

**(b) Hard questions.** Is every name earning its slot? — still no machine answer: zero
`council_verdict` rows ever, URC.TO has never even been decision-frozen, and GROY's one frozen
mark is price 4.444 against floor 4.446 with `rho: null`. Could the book rotate if it wanted to?
— not today: the gate is **triple-locked** (below). Is the concentration measurable? — 3 of 4
names share `asset_light_yield` and the gauge reads pairwise ρ only, on inputs that default
silently.

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 06-26 | Confidence |
|---|---|---|---|---|
| 1 | No inertia/review-due/thesis-age instrument on held names; `portfolio_metadata` has no `entry_date`/`last_review`/`review_cadence`; Living Memory frozen since 06-24; catalyst calendar = 4 rows, all AGA.V | `mcp_server/core.py:1780` (candidates only) · `data/living_memory.jsonl` · `data/catalyst_calendar.jsonl` | PERSISTS (record staler) | VERIFIED |
| 2 | Rotation gate triple-locked: refuses without a running engine; REJECTs on missing incumbent ρ; and the durable record shows **ρ=null on both ratable ballast names** (GROY, GMX.TO) — so SWAP is mechanically unreachable on any rotatable name today | `mcp_server/core.py:2605-2606` · `council.py:362-364` · `data/living_memory.jsonl` decisions 20-21 | NEW (sharpens 06-26's "calibrated to never fire") | VERIFIED |
| 3 | 0.60 ceiling now duplicated in **five** files (conditionals.py is a fifth copy the 06-26 count missed), no shared constant, no equality assert | `engine.py:2140` · `dynamic_config.py:33` · `book_change.py:27` · `mcp_server/core.py:2108` · `conditionals.py:39` | PERSISTS (count +1) | VERIFIED |
| 4 | Off-sum barbell vector falls back to defaults on a `logging.warning` only — operator-invisible | `engine.py:248-251` | PERSISTS (log-only) | VERIFIED |
| 5 | Correlation defaults: sizer hardcodes the GROY/URC/GMX trio at 0.50-if-missing — silently fictive diversification, and a `remove_holding` leaves the departed name averaged in at a phantom 0.50 (contradicts membership-as-data) | `engine.py:2157-2163` | PERSISTS + NEW residue | VERIFIED |
| 6 | Swap friction self-flagged ("MAY UNDERSTATE the thinnest names"), zero fills ever captured; WS assessment (2026-06-30) confirms nothing is built | `council.py:267-271,289-293` · `docs/WS_INTEGRATION_ASSESSMENT.md` | PERSISTS | VERIFIED (code) / DELEGATED-UNVERIFIED (doc quote) |
| 7 | Archetype overlap unmeasured: 3 of 4 = `asset_light_yield`; gauge reads pairwise ρ only; overlap lens never piloted | `book_factor.py:64-105` · `v5_config.json` portfolio_metadata | PERSISTS | DELEGATED-UNVERIFIED |
| 8 | Payoff learner wired (close-time scenario stamping, shrinkage k=6) but structurally unable to fire — feeder reads `type="outcome"` rows and there are zero; the 3 open decisions can't close before ~2026-09-21 | `engine.py:3854,5104-5106,5911` · `scenario_engine.py:231-247` | PARTIAL (machinery real, activation blocked) | DELEGATED-UNVERIFIED |
| 9 | Three parallel `_redistribute` implementations kept in lockstep by comment; `remove_holding`'s "no residue" claim overstated (sizer trio + `dashboard.py:514-519` hardcoded weights untouched) | `book_change.py:32-54` · `mcp_server/core.py:2111-2135` · `dashboard.py:514-519` | PERSISTS + NEW | VERIFIED (dashboard, sizer) / DELEGATED-UNVERIFIED (book_change internals) |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Thesis-review clock on `portfolio_metadata` (+ "slot un-contested N days" surfacing) — flags, never sizes | **ADOPT** (carried from 06-26; still undone, still #1 for this force) | fields = propose→confirm; surfacing = code-behind-tests |
| Centralize the 0.60 ceiling (5 sites) + equality assert; consolidate the 3 `_redistribute` copies | **ADOPT** — pure hardening, one PR | code-behind-tests |
| Loud degraded-data: barbell-fallback banner; `corr_source: measured\|default` marking; derive the sizer correlation set from `book_tickers(cfg)` | **ADOPT** | code-behind-tests |
| Rotation-gate honesty: a distinct "incumbent UNRATABLE" verdict (surfaced as book-health) instead of silent REJECT on null ρ; do NOT synthesize ρ | **PILOT** verdict / **REJECT** synthetic ρ | code-behind-tests |
| WS Activities-CSV fill importer (per the WS assessment) — unblocks fill-based friction re-fit, outcome grading, and the payoff learner at once | **ADOPT** (MVP) | operator-decision, then code-behind-tests |
| Archetype/subarchetype-overlap lens in book_factor | **PILOT** | code-behind-tests |
| Scheduled SLOT RE-CONTEST; URC.TO first (never decision-frozen, no catalyst record, Sweetwater-impaired), GROY second (frozen at-floor, null ρ) | **ADOPT** as practice | operator-decision |
| Raise the friction/hurdle meanwhile | **KEEP-AS-IS** | read-only |

**(e) Next steps.** 1) Council URC.TO and GROY now — the two loudest inertia signals; writes the
first `council_verdict` rows and un-freezes Memory (operator-decision). 2) Thesis-review clock
(propose→confirm + code). 3) Ceiling centralization + `_redistribute` consolidation (code). 4)
Loud degraded-data + book-driven sizer set (code). 5) WS CSV importer decision (operator). 6)
Pilots: overlap gauge, UNRATABLE verdict (code).

---

## TF3 — Data Provenance & Inputs

**(a) First principles.** Grounded-or-silent at the input boundary: every number the engine
prices, rates, or regimes on is either real-and-current or visibly marked as neither. The test for
every feed is not "does it usually work" but "when it fails, can the operator tell?" — a
wrong-but-labeled number is recoverable; a wrong-but-confident number compounds into sizing.

**(b) Hard questions.** Why, six days after the program named it Phase 2.1, does `calculate_mri`
still fabricate seven inputs silently while the price workers in the same file promise "NEVER a
fabricated constant"? Which FRED series is canonical — the config's declared `REAINTRATREARAT10Y`
or the `DFII10` the code fetches? What stops the *inputs* to the verify-before-wire gate being
hand-edited around `set()` — nothing, as the GROY entries prove. Who notices when the GMX peer
mark (as_of 2025-09-11, ~295 days) turns a year old, given it is not a `HARD_FLOOR_ARGS` member
and so never trips `refresh_due`? What is the corroboration plan for the uranium stamp before its
45-day window quietly arrives on 2026-07-19?

**(c) Current practice & strains.** The STRONG layer re-verified and HOLDS: restatement-as-event
(`research_cache.py:64-69,96-116`), the freshness ladder (`market_data.py:179-223`), two-tier spot
with undated-is-stale (`nav_mark.py:60-77`), the catalyst trust hierarchy
(`catalyst_engine.py:51-84`), fail-closed sigma widening (`uncertainty.py:60-84`). [Ladder/spot/
catalyst/sigma re-verification DELEGATED-UNVERIFIED this sweep; unchanged from 06-26's direct
reads. research_cache API VERIFIED.]

| # | Strain | Anchor | Status vs 06-26 | Confidence |
|---|---|---|---|---|
| 1 | MRI silent defaults ×7 + confident 45.0-on-exception; `calculate_mri` reads `.value`, never `.status`, so the honest cold-start badges (`STALE_FALLBACK`/`INITIAL_BASELINE`, `engine.py:2513-2525`) stop one call short of the number that sets the regime; no fabricated-default sentinel exists | `engine.py:617-623,719,2513-2525` | PERSISTS (Phase 2.1/2.2 unshipped) | VERIFIED (+ live) |
| 2 | `state_cache` cold-start births the CFTC default **already badged LIVE**; live run showed the real synced value never displacing it in `/state` | `engine.py:2462-2463,3265-3266,5534,5644` | NEW (sharpens #1) | VERIFIED (live) |
| 3 | FRED label drift: config declares `REAINTRATREARAT10Y`, engine fetches `DFII10` | `v5_config.json:1034` · `engine.py:462,597` | PERSISTS | VERIFIED |
| 4 | Uranium stamp US$86.10 as_of 2026-06-04 — single-sourced, 28 days old, silently inside the 45-day window (cliff 2026-07-19); only a *momentum* proxy exists (`market_data.py:119-125`), not a spot corroborator | `data/research_cache.json` URC.TO nav_inventory · `nav_mark.py:38` | PERSISTS | VERIFIED (stamp) / DELEGATED-UNVERIFIED (proxy scope) |
| 5 | REP-floor cash/burn 162 days stale, presented to the cent; two Silver47 quarters (ended 2026-01-31, 2026-04-30) likely filed since | `v5_config.json:14,26-28` | PERSISTS (worse by 6 days/quarter) | VERIFIED |
| 6 | Gold fallback 2350 now ~42% below the cached regime (~$4,029) — the silent-fallback distortion has roughly doubled | `engine.py:2457,2990,3001` | WORSE (relative) | VERIFIED (constant) / DELEGATED-UNVERIFIED (cached gold mark) |
| 7 | URC.TO forensic block 19.0 days staler than the rest; freshness layer still reads only file mtime though per-entry timestamps exist inside the file | `.cache/forensic_cache.json` · `engine.py:974,5589-5592` | PERSISTS exactly | VERIFIED (skew) / DELEGATED-UNVERIFIED (mtime path) |
| 8 | Hand-edited GROY cache entries bypassed `set()`: out-of-vocab `"low-med"` confidence, shared round `fetched_at` = 2026-06-27T00:00:00Z, and `holdco_blue_sky_value.as_of` (2026-07-02) **postdates its fetched_at** — a look-ahead defect in the PIT store (`as_at()` reconstructs by fetched_at) | `data/research_cache.json` GROY · `research_cache.py:25,45,109-111` | NEW | VERIFIED (entries) / DELEGATED-UNVERIFIED (as_at mechanics) |
| 9 | Verify-before-wire residue: `rerated_book_ps`/`rerate_uplift_pct` ship in display `components` unconditionally — a REJECTED number can render without its rejection context; `ResearchCache.value()` naively returns the rejected $1B (only `fair_value_inputs_from_cache` knows to check `verified`) | `holdco_nav.py:300-304` | NEW (minor; cannot reach a rating) | VERIFIED (components) / DELEGATED-UNVERIFIED (value() path) |
| 10 | Ingestion schism PARTIAL: the catalyst leg is now genuinely live (`use_live_feeds: true`, per-event provider/trust stamps); the fundamentals/macro overlay remains configured-but-unused (`data/ingestion_cache.json` absent = silent no-op) and `merge_by_capability` keeps no per-field provenance | `engine.py:86,4225-4227` · `ingestion_pipeline.py:1410-1415` | PARTIAL (improved) | DELEGATED-UNVERIFIED |
| 11 | GMX peer holdco NAV: primary-sourced PR → un-benchmarked ~7× multiple → CAD 30M, conf med; as_of 2025-09-11 invisible to any staleness watch (`HARD_FLOOR_ARGS` excludes it) | `data/research_cache.json:152-158` · `holdco_nav_feed.py:46,139` | NEW | DELEGATED-UNVERIFIED |
| 12 | Rates route fail-closed re-verified (OpenBB-first, "[] on any failure; never fabricates"; BEY conversion labeled); one gap: DGS2 stamps `asof = "FRED latest"` — a string, not a date | `engine.py:3532-3549,3600,3629-3633` | NEW surface, sound | DELEGATED-UNVERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| Ship MRI Phase 2.1+2.2: status-aware sub-inputs, a `fabricated_inputs`/`degraded` flag in `mri_decomposition`, no bare 45.0; fix the born-LIVE cold-start (`cftc_status: "INITIAL_BASELINE"` at `engine.py:2463`) | **ADOPT** — the two-audit-old central fix, now with live proof | code-behind-tests |
| research_cache write-discipline validator at load (confidence ∈ vocab, `as_of ≤ fetched_at+ε`, sorted-keys); re-write the two hand-edited GROY entries through `set()` | **ADOPT** validator; re-write = **propose→confirm** | code-behind-tests / propose→confirm |
| Refresh REP-floor cash/burn from the two filed quarters; round to precision honesty (~C$53M) | **ADOPT** — overdue data entry with receipts | propose→confirm (moves the spear floor) |
| Uranium second reference read-only pilot (Sprott U.UN NAV-implied or Numerco) before the 07-19 cliff; then a U-specific window | **PILOT** (carried, still undone) | read-only; window = propose→confirm |
| FRED label: config → `DFII10` (code canonical) | **ADOPT** fix | propose→confirm |
| Per-ticker forensic freshness from in-file timestamps; peer-mark staleness watch (`SOFT_VALUE_ARGS`); gold/copper fallbacks → last-good-cache-first | **ADOPT** all three | code-behind-tests |
| Suppress `components.rerated_book_ps` render when verdict=rejected | **PILOT** (render-side) | code-behind-tests |
| Catalyst `timing_confidence` split | **REJECT** — the 4-tier vocabulary already encodes it; *use* `guided`/`scheduled` when receipts allow | read-only |
| Ingestion fundamentals leg: schedule-with-provenance or mark dormant | operator must choose | operator-decision |

**(e) Next steps.** 1) REP-floor refresh (propose→confirm). 2) MRI fail-closed + born-LIVE fix
(code). 3) Cache validator + GROY entry re-write (code / propose→confirm). 4) Memory-record the
GROY rejection (see TF4). 5) FRED label (propose→confirm). 6) Uranium pilot before 07-19
(read-only). 7) Forensic/peer/gold freshness batch (code). 8) Ingestion decision (operator).

---

## TF4 — Research Production & the Agentic Layer

**(a) First principles.** Engine owns the reproducible and unargued; agents own the genuinely
contested; the human owns state mutation. Corollary set by the desk's own newest commit
(d471756): any agent-sourced *value* that can move a rating must pass an independent check
enforced in code, not prose. The test of this audit is whether the rest of the cockpit lives up to
the standard its newest seam just set.

**(b) Hard questions.** Is the Council a deterministic reconciler or three opus prompts wearing
one — when `reconcile()` still has no wrapper and the seat that is ordered to "feed council.py the
facts" (`arbiter.md:34-40`) still cannot execute it? Does verify-before-wire enforce independence
in code or convention — when no API exists for the `verified` bit and the sourcing seat is
separated from the verifying seat only by session discipline? If the GROY rejection is the pattern
for trusting agent-sourced data, why is it invisible to the pattern's own memory? What should AI
automate next — not judgment but *plumbing*: writing verdicts to Memory, wiring `reconcile()`,
hardening the runner — the deterministic scaffolding that keeps failing by hand.

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 06-26 | Confidence |
|---|---|---|---|---|
| 1 | `reconcile()` has no MCP wrapper (only `council_swap`); every council seat denies Bash; the provenance claim-weighting shipped 06-25 (`PROVENANCE_WEIGHT`, `council.py:63-65`) is therefore **also unreachable at runtime** | `council.py:138` · `mcp_server/core.py:2591` · `.claude/agents/arbiter.md:5,34-40` | PERSISTS (2 audits overdue) | VERIFIED |
| 2 | Flywheel frozen: living_memory byte-stable since 06-24 — 3 decisions / 0 outcomes / 0 council_verdicts / 0 conviction / 57×`provenance:None`; the capture hook (`freeze_decision_if_new` on council_verdict writes) exists and has never fired | `data/living_memory.jsonl` · `mcp_server/core.py:1116-1123` | PERSISTS → WORSE (staleness) | VERIFIED |
| 3 | The `memory_write` MCP tool has **no provenance parameter** — an agent citing a filing can never be weighted above `agent` | `mcp_server/server.py:321-322` · `living_memory.py:88,168` | NEW (sharpens "tiers dead") | VERIFIED |
| 4 | `graduate_candidate` blank-ref auto-resolve accepts receipts of **any vintage** (existence + ticker match only; no ts/run-tag check) | `mcp_server/core.py:1831-1852` | PERSISTS | VERIFIED |
| 5 | Headless runner: env-overridable `CEX_JOB_CMD` (default `claude -p {prompt}`), no `--disallowedTools` injected; the safety line is a prompt string | `commodityex_tui.py:6312,6338-6339` (same shape `:10883`) | PERSISTS | VERIFIED |
| 6 | value-analyst/balance-sheet-analyst still absent from the canonical chain — but they were the **sourcing seats** of the GROY re-rate, i.e. they have drifted into a producer role the docs don't describe (sourcer ≠ verifier is exactly the independence the gate wants) | `.claude/agents/` · `commodityex_tui.py:761-762` · research_cache GROY note | PERSISTS, reframed | VERIFIED (role) / DELEGATED-UNVERIFIED (TUI registry lines) |
| 7 | Verify-before-wire: inertness is code (three gates + 194-line pin); **independence is convention** — no API can flip `verified`, nothing checks who verified, bare `"verified": true` passes (deliberately pinned), the bit was hand-edited + committed | `holdco_nav.py:206,238,284-292` · `holdco_nav_feed.py:199-204` · `tests/test_royalty_rerate.py:104-154` | NEW (good seam, soft plumbing) | VERIFIED |
| 8 | The GROY $1B rejection is durable in the cache + git, **invisible to Living Memory** — `memory_query(ticker="GROY", tag="verifier")` returns nothing; the graduation gate could never cite the desk's best forensic catch | `data/research_cache.json` GROY `verified` block · `data/living_memory.jsonl` | NEW | VERIFIED |
| 9 | `slip_max=0.20` self-graded "engineering — LOW", zero fills captured, cannot be re-fit | `council.py:270,289-293` | PERSISTS | VERIFIED |
| 10 | Pipeline hand-off (run-tag, two channels) still pinned by `tests/test_pipeline_handoff.py` — intact; the irony is the tested substrate hasn't received a live write since 06-24 | `tests/test_pipeline_handoff.py:10-14,54-60` | HOLDS | DELEGATED-UNVERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| `council_reconcile` read-only MCP wrapper + point `arbiter.md` at it — also unlocks the provenance weighting for free | **ADOPT** (carried twice; do it first) | code-behind-tests |
| `research_cache.verify(ticker, field, verdict, by, receipts)` as an MCP tool: dict-verdict-with-receipts required, **sourcer≠verifier refusal**, deprecate the bool-`true` branch | **ADOPT** | code-behind-tests |
| Mirror every `verified` verdict into Living Memory (a `verification` entry, byproduct of the verify API, best-effort like the capture hook); backfill the GROY rejection as the first entry | **ADOPT**; backfill = **propose→confirm** | code-behind-tests / propose→confirm |
| Freshness + run-tag binding on `graduate_candidate` | **ADOPT** check; threshold = **propose→confirm** | code-behind-tests / propose→confirm |
| Inject a fixed `--disallowedTools` set into `_job_argv`/`_pipeline_argv` (the `_inject_model_flags` pattern already exists); allowlist `CEX_JOB_CMD` overrides with an explicit escape hatch | **ADOPT** | code-behind-tests + operator-decision (allowlist) |
| Expose `provenance` on `memory_write` (validated, capped at `sourced` for agent callers) | **PILOT** | code-behind-tests |
| Document value-analyst/balance-sheet-analyst as sourcing seats with a sourcer-never-verifies rule (supersedes 06-26's "consolidate") | **ADOPT** | read-only (docs) + operator-decision (roster) |
| Manual flywheel seeding now (close the 3 open decisions vs cached closes; first conviction readings) vs waiting for engine-ONLINE | **PILOT** — it has been "pending engine" for two audits; a thin manual seed beats a stalled loop | operator-decision |
| Re-fit `slip_max` without fills / retire the deterministic council for opus prose | **KEEP-AS-IS** / **REJECT** | propose→confirm / — |

**(e) Next steps.** 1) `council_reconcile` wrapper (code). 2) `verify()` API + sourcer≠verifier
(code). 3) Memory mirror + GROY backfill (code / propose→confirm). 4) Graduation freshness (code /
propose→confirm). 5) Headless runner hardening (code + operator allowlist). 6) Docs: sourcing-seat
roles (read-only + operator). 7) Flywheel seeding decision (operator).

---

## TF5 — The Conviction & Valuation Framework

**(a) First principles.** The T/Q/V rating is the desk's single comparable verdict, hard-capped by
a forensic survival gate and translated into the band + directive the operator's real Wealthsimple
decisions ride on. It earns trust two ways only: inputs real (fresh floors, sourced forensics,
structural-not-momentum tailwind) and outputs graded against what happened. The architecture for
both exists and is unusually well built — pure, tested, Goodhart-guarded. The validation half has
processed zero outcomes, so every constant remains a reasoned assertion wearing a measured
number's precision.

**(b) Hard questions.** Is the number proven or only built? — built: `replay.grade_snapshot`
requires a close ≥ t0+30d and the earliest snapshot (06-12) matures 2026-07-12, so `graded=0` is
still forced — but for the first time the maturity date is *inside the next two weeks*. What
exactly happens on 2026-07-15 — is the desk *choosing* that outcome or defaulting into it? Is the
anti-crush gate a principle or a preference for the higher number? Is "GROY tangible book = full
equity, HIGH confidence" conservative when the cache note itself concedes the acquisition premium
sits inside the royalty-interest line the goodwill haircut was meant to strip? Does the new
fair-value machinery change what the ungraded 0.65 lift amplifies? (Yes — GROY's V now exceeds Q,
so the lift amplifies the new, equally ungraded fair-value anchor.)

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 06-26 | Confidence |
|---|---|---|---|---|
| 1 | Grading loop grades nothing: ledger froze 06-24 (3,311 rows, 13-day span); price store ≤10 closes/name (URC.TO: 3) — `backfill_price_history.py` shipped and **never run**; 0 outcomes / 0 conviction readings; `update_beta` is **pure and ephemeral** — returns a posterior, persists nothing, no learned-posterior store exists anywhere in `data/` | `replay.py:44,81-84` · `data/price_history.json` · `base_rates.py:219-228,301-314` | PERSISTS → functionally WORSE (frozen); partially unfrozen by this session's live run (+4 rows) | VERIFIED |
| 2 | AGA.V placeholder waiver: honored through 2026-07-15, **dead on 07-16** — automatic, no ceremony (`0 <= days_left`); CBA then re-tests for real (a fail costs 1.0 JSF pt + drops explorer `penalty_factor` to ≈0.935, ~-6.5% intrinsic); dilution survives only via runway insulation (≥18 mo bar) — **whose runway (19.3 mo) is computed on the 162-day-stale January cash**; at config burn, real treasury today is ~CAD 38M ≈ 14 mo — below the bar in reality but not in the model | `v5_config.json:951-957` · `engine.py:1168-1172,1234-1237,1330-1338` · `forensic_gates.py:36,55,59` · `tests/test_v5_engine.py:547,563` | PERSISTS, now time-critical (13 days) | VERIFIED |
| 3 | REP-floor cash/burn stale — the single input feeding φ, ρ's denominator, the gate relaxation, the lift's support scaling, AND the post-expiry runway insulation | `v5_config.json:14,26-28` | PERSISTS verbatim | VERIFIED |
| 4 | GROY thrash + phantom zeros: 2,473/3,311 rows (74.7%), 99.6% of them `material_change`; **81** `intrinsic==0.0` rows banded SOLID/FAIR; no stamp-guard exists (`snapshot_from_basket` takes base unconditionally; `maybe_record` writes on any fingerprint move; only damping is 3-decimal rounding) — Phase 1.2/1.3 NOT shipped, and the engine restart this session began stamping the new base against a ledger with no guard | `valuation_ledger.py:48,183,299-314` | PERSISTS | VERIFIED (counts) / DELEGATED-UNVERIFIED (no-test claim) |
| 5 | `support_curve` still `'linear'` — flat shelf above φ=1.25; `'depth'` implemented, pinned, proposal-gated, not activated (correctly deferred pending first grades) | `v5_config.json:609` · `asymmetry_rating.py:361-373` | PERSISTS (deferral re-affirmed) | VERIFIED |
| 6 | T-pillar tape leak: `vol_edge` is 35% of the spear's `alpha_option` lean, `weak_usd` feeds cyclical/delta alphas — ~23% of the spear's T is elevated silver vol while the glossary claims T is "LEVELS … NOT recent price action"; the P1.1 momentum strip covered only the commodity channel | `engine.py:3395,3433-3434,3497-3499` · `asymmetry_rating.py:61,405,425` | PERSISTS (strip not done) | DELEGATED-UNVERIFIED |
| 7 | **The fair-value ratchet (new):** floor replaced only when HIGHER; metal re-rate only ever UP; blue-sky only additive; anti-crush blocks *below-price* NAVs at MED while *above-price* NAVs wire at MED — each rule locally defensible and test-pinned (the OGN.V lesson; the same-day rollback of the crushing ladder wire), but the composition is direction-biased: no new data source can lower a ballast's base or floor without HIGH confidence, and the confidence tiers are desk-assigned and ungraded | `engine.py:5286-5293,5303-5311` · `holdco_nav.py:284,334,357` | NEW | VERIFIED |
| 8 | GROY goodwill=0 → tangible book = **full** US$722M equity at HIGH — the sourced fact is real (no goodwill line, XBRL-corroborated), but the cache note concedes the 2021 acquisition premium sits inside "Royalties/streaming/other mineral interests US$785.3M (93%)" — a 0-goodwill balance sheet gets zero haircut on a book that is ~93% acquired interests bought at ~$1,800 gold; HIGH is the tier that can assert in *both* directions | `data/research_cache.json` GROY.goodwill · `holdco_nav.py:259-263` | NEW | VERIFIED (mechanics) / DELEGATED-UNVERIFIED (materiality) |
| 9 | GMX RICH—TRIM fix does **not** itself suppress future TRIMs (it *enables* below-price assertion for peer-sourced holdcos; a genuinely rich GMX still emits RICH—TRIM at ≤−15%) — residual risks: a royalty at MED can never assert a below-price NAV (falls back to the archetype blend), and the carve-out trusts bearishly the same MED peer mark (as_of **2025-09-11**) the gate distrusts bullishly | `holdco_nav.py:344-350,357` · `asymmetry_rating.py:796-797` · `tests/test_holdco_nav.py:231` | NEW (net positive, edges noted) | VERIFIED (carve-out) / DELEGATED-UNVERIFIED (blend fallback) |
| 10 | Blue-sky lens display-only **VERIFIED** (value-mode V reads base, not bull; ballast bear leg None keeps it out of the ribbon); the verifier gauntlet cut the agent-sourced GROY blue-sky $165M→$60M before confirming. Forecast-share meter measure-only **VERIFIED** (attached after the rating, try/except, "never load-bearing") | `engine.py:5330-5331` · `asymmetry_rating.py:619-637,956-963` · `forecast_share.py:9,40` | NEW (good) | DELEGATED-UNVERIFIED |
| 11 | `conviction_lift` 0.65 + pillar weights ungraded — and the amplification target moved: value-mode lift anchors on `max(Q,V)`; with carried-book NAV wired into base, V overtakes Q on GROY, so the ungraded lift now amplifies the ungraded new anchor; asymmetry-mode lift scales with the stale January floor | `asymmetry_rating.py:299,849-855` · `v5_config.json:718-720` | PERSISTS + NEW coupling | DELEGATED-UNVERIFIED |

**(d) Alternatives.**

| Option | Recommendation | Gate |
|---|---|---|
| **Decide the waiver, don't default it**: source the real dilution/CBA basis from SEDAR+ MD&A with a real justification + short expiry, OR consciously let it lapse 07-16 and take the honest JSF/intrinsic haircut — record the choice to Memory either way | **ADOPT (either branch, explicitly)** — the board's clock item | sourcing = read-only; override string = propose→confirm; lapse = operator-decision |
| Refresh cash/burn from the latest filing (one input, five consumers) | **ADOPT** — highest information-per-effort on the board | propose→confirm |
| Zero-intrinsic stamp-guard + read-side exclusion of the 81 phantoms; material_change min-delta — **before the engine runs long** (it is running again as of this session) | **ADOPT** guard / threshold = propose→confirm | code-behind-tests / propose→confirm |
| Run `backfill_price_history.py` (reconcile adjusted-close basis first) + keep the heartbeat running; from 2026-07-12 the 06-12 vintage is 30d-gradeable — publish first grades with `data_limited` flags, then decide where `update_beta` posteriors persist (today: nowhere) | **ADOPT** | data-store write; engine ops = operator-decision |
| Wire-gate symmetry audit: every up-only mechanism names its down-path (e.g. a HIGH-confidence sourced floor may *lower* a stale floor; periodic re-confirm of below-price blocks) | **PILOT** — documented, test-pinned, not a reflex (the crush bug is real) | code-behind-tests; activation = propose→confirm |
| Royalty goodwill-classification review: "0 goodwill but ≥X% acquired mineral interests" ⇒ MED, not HIGH | **PILOT** — read-only analysis first; it would down-tier GROY's anchor and possibly its band, which is the point | read-only, then propose→confirm |
| Complete the vol_edge/dxy_mom strip from scored alphas (display-only), with a before/after T delta table | **ADOPT** (completes 06-26 step 7) | propose→confirm |
| Activate `support_curve='depth'` now; re-tune lift/weights/bands now | **KEEP-AS-IS (defer)** / **REJECT** — nothing to tune against until first grades | propose→confirm, after grades |

**(e) Next steps.** 1) Waiver decision by 07-15 (operator + propose→confirm). 2) Cash/burn
refresh (propose→confirm). 3) Stamp-guard + hysteresis BEFORE sustained engine running (code /
propose→confirm). 4) Backfill + heartbeat (data-store write / operator). 5) First grades from
07-12, publish with small-n CIs, persist posteriors (read-only → designed flywheel). 6) T-pillar
strip (propose→confirm). 7) Goodwill review + symmetry audit pilots; defer depth-curve and any
retune until grades exist.

---

## Cross-Cutting Matrix — where the task forces collide

| Tension | Upstream (cause) | Downstream (harm) | Who must co-sign |
|---|---|---|---|
| **The confirm hole makes every propose→confirm verdict conditional** | TF1: `/config/confirm` + `confirm_param_change` source-blind | Every gate tag in this document that says "propose→confirm" assumes a human at the confirm step; today that is convention. TF4's agent-capability boundary and TF2's book-mutation tools (`remove_holding` self-confirms) inherit the same hole | TF1 owns the endpoint guard; TF4 owns the agent deny-list; the operator signs the capability change |
| **One stale number underwrites the spear's post-expiry survival** | TF3: cash/burn dated 2026-01-21 | TF5: on 07-16 the dilution gate's only remaining pass is runway insulation computed from that number — 19.3 mo on paper, ~14 mo at the config's own burn; the model may pass a test reality fails | TF3 re-sources once; TF5 owns the gate consequence; operator owns the waiver decision. **Refresh before expiry or the lapse decision is made on fiction** |
| **The verify-before-wire seam is only as strong as the store under it** | TF4: no API for `verified`; TF3: hand-edited entries bypass `set()` (look-ahead `as_of`, out-of-vocab confidence) | TF5: the wire gate consumes those entries as fact; the PIT store's `as_at()` reconstruction — the future grading substrate — now contains at least one look-ahead row | TF3 (validator) + TF4 (`verify()` API + Memory mirror) land together; neither alone closes it |
| **The flywheel freeze starves four forces at once** | TF4/TF5: 0 outcomes, 0 verdicts, Memory frozen since 06-24 | TF2's inertia question has no machine answer; TF5's constants stay unfalsifiable; TF4's provenance tiers stay dead; TF1's "keep constants pending grade" verdicts weaken. The GROY saga — the desk's best work since 06-26 — is invisible to its own nervous system | Every force. First unblock: write verdicts/verifications to Memory as a *byproduct* of the tools (TF4), not as discipline |
| **Fabricated regime inputs flow into both the rating and the agents** | TF3: MRI silent defaults, born-LIVE badges | TF5: T pillar consumes MRI; TF4: agents read `get_conviction_ratings` and inherit the same fabricated inputs as facts; TF1: the header tint renders it all confidently | TF3 owns the fix; one fabricated-default sentinel serves all four |
| **Hidden provenance flags + a live book actually flying degraded** | TF1: `floor_degraded`/`quality_proxy_only` unrendered | Live this session: 3 of 4 held names degraded-floor, one proxy-Q, screen clean. TF5's φ/ρ and directives ride the same unrendered flags | TF1 render fix; TF5 directive guard (`BELOW PROXY FLOOR — VERIFY`) |
| **The ratchet compounds with the lift on ungraded tiers** | TF5: up-only floor/re-rate/blue-sky + MED-asymmetric anti-crush; desk-assigned confidence tiers | The ungraded 0.65 lift now amplifies V anchors produced by the ratchet (GROY V>Q); nothing can pull a ballast's anchor down short of HIGH-confidence bad news | TF5 symmetry audit + goodwill review; TF3 tier honesty; grading (Phase-grade) is the only durable arbiter |
| **Restart-without-guard writes noise into the immutable record** | TF5: no zero-intrinsic guard, no hysteresis; engine restarted this session | The 74%-GROY thrash pattern resumes against the new valuation base; the future grade inherits the noise | TF5 guard lands before sustained running; TF2's heartbeat plans wait on it |
| **The 0.60 ceiling and `_redistribute` live as 5 + 3 copies** | TF2 | A drift on the book's most important invariant silently diverges sizing from validation from the applied diff; `remove_holding` leaves phantom-0.50 residue in the sizer | TF2 centralization; TF1 surfaces it as signal integrity |

---

## Sequenced Program — one roadmap, gate tags binding

Ordering principle: **beat the clock items first (07-15 waiver, 07-16 restart-noise, 07-19
uranium cliff), close the confirm hole, make the store trustworthy, then warm the loop and only
then re-contest by judgment.**

### Phase 0 — This week, before the clocks run out
| # | Step | Source | Gate |
|---|---|---|---|
| 0.1 | **Waiver decision** on AGA.V: source the real basis or documented lapse; record to Memory | TF5 | **operator-decision** + propose→confirm |
| 0.2 | **Refresh REP-floor cash/burn** from the two filed Silver47 quarters — must precede 0.1's lapse branch (the insulation test runs on it) | TF3↔TF5 | **propose→confirm** |
| 0.3 | **Zero-intrinsic stamp-guard + 81-phantom exclusion**; material_change min-delta — before sustained engine running | TF5 | code-behind-tests / **propose→confirm** (threshold) |
| 0.4 | **Uranium second-reference pilot** (Sprott NAV-implied or Numerco, read-only) before the 07-19 staleness cliff; then propose a U-specific window | TF3 | read-only / **propose→confirm** (window) |

### Phase 1 — Close the confirm hole (the gate everything else assumes)
| # | Step | Source | Gate |
|---|---|---|---|
| 1.1 | Source-guard `/config/confirm` (mirror `engine.py:6690-6694`); refuse non-cockpit/human | TF1 | code-behind-tests |
| 1.2 | Deny `confirm_param_change` + self-confirming write tools (`remove_holding`, `promote_to_eval`) in every agent manifest; keep the cockpit `c`/`/confirm` as the human channel | TF1↔TF4 | **operator-decision** (agent capability) |
| 1.3 | Harden headless runners: inject `--disallowedTools` into `_job_argv`/`_pipeline_argv`; allowlist `CEX_JOB_CMD` | TF4 | code-behind-tests + **operator-decision** (allowlist) |

### Phase 2 — Make the store trustworthy (verify-before-wire earns its plumbing)
| # | Step | Source | Gate |
|---|---|---|---|
| 2.1 | `research_cache.verify()` API + MCP tool: dict-verdict-with-receipts, sourcer≠verifier refusal, deprecate the bool-`true` branch | TF4↔TF3 | code-behind-tests |
| 2.2 | research_cache load-time validator (confidence vocab, `as_of ≤ fetched_at`, API-only invariants); re-write the two hand-edited GROY entries through `set()` | TF3 | code-behind-tests / **propose→confirm** (re-write) |
| 2.3 | Living Memory mirror: every `verified` verdict writes a `verification` entry (byproduct of 2.1); backfill the GROY $1B rejection as the first entry — un-freezes Memory | TF4 | code-behind-tests / **propose→confirm** (backfill) |
| 2.4 | Expose `provenance` on `memory_write` (validated, agent-capped at `sourced`) | TF4 | code-behind-tests (PILOT) |
| 2.5 | Freshness + run-tag binding on `graduate_candidate` | TF4 | code-behind-tests / **propose→confirm** (max-age) |

### Phase 3 — Fail-closed regime layer (two audits overdue)
| # | Step | Source | Gate |
|---|---|---|---|
| 3.1 | MRI status-aware sub-inputs + `fabricated_inputs`/`degraded` flag + no bare 45.0; fix the born-LIVE cold-start (`engine.py:2463`) | TF3 | code-behind-tests |
| 3.2 | FRED label reconciliation (config → `DFII10`) | TF3 | **propose→confirm** |
| 3.3 | Per-ticker forensic freshness from in-file timestamps; peer-mark staleness watch; gold/copper fallbacks → last-good-first | TF3 | code-behind-tests |

### Phase 4 — Restore the unreached determinism
| # | Step | Source | Gate |
|---|---|---|---|
| 4.1 | `council_reconcile` read-only MCP wrapper; point `arbiter.md` at it (unlocks the provenance weighting for free) — carried twice, do it now | TF4 | code-behind-tests |
| 4.2 | Directive → `(code, display_text)`; council prior, stance chip, book row key off the code; FAIR VALUE off 0.50; loud runtime fallback | TF1 | code-behind-tests |

### Phase 5 — Make the signal honest (the live run showed why)
| # | Step | Source | Gate |
|---|---|---|---|
| 5.1 | Render `floor_degraded`/`quality_proxy_only` on rail + detail card (↻rerate-chip pattern); blue-sky `✓verified`/`~scenario` tick | TF1 | read-only display |
| 5.2 | Gate φ≥1 `BELOW FLOOR — ACCUMULATE` behind a sourced floor (`BELOW PROXY FLOOR — VERIFY`) | TF1↔TF5 | code-behind-tests |
| 5.3 | `survival_exempt_archetypes` load-time equality assertion; file the value question | TF1↔TF2 | code-behind-tests / **propose→confirm** (value) |
| 5.4 | Router reorder (`liquidity-runway` above bare `runway`) + did-you-mean pilot; fix `— not sourced` mislabel and `tail[:5]` chip fallback | TF1 | code-behind-tests / **operator-decision** (clarifier) |
| 5.5 | Pilots: colour-band step-rounding; collapsed no-verdict Council line; suppress rejected `rerated_book_ps` render | TF1/TF3 | read-only display |

### Phase 6 — Harden the invariants
| # | Step | Source | Gate |
|---|---|---|---|
| 6.1 | Centralize the 0.60 ceiling (**5** sites) + equality test; consolidate the 3 `_redistribute` copies; loud off-sum barbell fallback | TF2 | code-behind-tests |
| 6.2 | Book-driven sizer correlation set (from `book_tickers`) + `corr_source: measured\|default` marking | TF2 | code-behind-tests |
| 6.3 | Docs: value-analyst/balance-sheet-analyst as sourcing seats; sourcer-never-verifies rule | TF4 | read-only + **operator-decision** (roster) |
| 6.4 | Ingestion fundamentals leg: schedule-with-provenance or mark dormant | TF3 | **operator-decision** |

### Phase 7 — Warm the loop & re-contest (grading begins 2026-07-12)
| # | Step | Source | Gate |
|---|---|---|---|
| 7.1 | Run `backfill_price_history.py` (reconcile close basis first); keep the heartbeat running with the Phase-0.3 guard in place | TF5 | data-store write / **operator-decision** (ops) |
| 7.2 | From 07-12: `replay.grade_ledger` + `calibration_scorecard`; publish first grades with small-n CIs + `data_limited`; decide where `update_beta` posteriors persist (today: nowhere) | TF5 | read-only → designed flywheel |
| 7.3 | Council URC.TO and GROY (the two loudest inertia signals — URC.TO never decision-frozen, GROY frozen at-floor with null ρ); first `council_verdict` rows fire the capture hook | TF2↔TF4 | **operator-decision** |
| 7.4 | Thesis-review clock on `portfolio_metadata` + "slot un-contested N days" surfacing; rotation-gate UNRATABLE verdict pilot; archetype-overlap lens pilot | TF2 | **propose→confirm** (fields) / code-behind-tests |
| 7.5 | WS Activities-CSV fill importer MVP — unblocks friction re-fit, outcome grading, and the payoff learner at once | TF2↔TF4 | **operator-decision**, then code-behind-tests |
| 7.6 | T-pillar strip (vol_edge/weak_usd display-only) with before/after delta table | TF5 | **propose→confirm** |
| 7.7 | With first grades in hand: goodwill-classification review; wire-gate symmetry audit; `support_curve='depth'` proposal; slip_max re-fit against captured fills | TF5/TF2 | read-only → **propose→confirm** each |

---

## Preserved dissent & the could-not-verify list

**Dissent, preserved:**
- **The confirm-hole fix is not unambiguous.** The main-session assistant confirming *on the
  user's explicit spoken "confirm"* is a legitimate flow today; a hard source-guard breaks it
  unless the cockpit channel is kept open. The recommendation is to close the *agent* path, not
  the human-voice path — but where exactly that line sits (is the main session "an agent"?) is an
  operator call, and reasonable people can draw it differently.
- **The fair-value ratchet critique is contested by its own history.** The one time the desk wired
  a conservative NAV symmetrically, it manufactured a false −59% TRIM on GMX and was rolled back
  the same day. The up-only bias is scar tissue, not carelessness. The counter-position — that a
  margin-of-safety engine should err asymmetrically *toward* lower anchors, not higher — is also
  principled. This is routed to a PILOT + operator decision, not auto-applied.
- **The GROY goodwill finding may be immaterial in practice.** Market prices GROY at ≈1.0× book;
  if the acquired interests are worth carrying value, the HIGH tier is fine. The finding is about
  *tier semantics* (HIGH can assert in both directions), not a claim the book is overstated.
- **Manual flywheel seeding vs waiting for the heartbeat** is genuinely unsettled: a thin manual
  seed beats a stalled loop (TF4's view), but hand-graded outcomes are lower-fidelity and the
  06-26 dissent — "no cleverness manufactures realized time" — still stands. The 07-12 maturity
  date softens the urgency either way.
- **Letting the AGA.V waiver lapse is a defensible choice, not only a failure mode.** The lapse
  takes the honest number (JSF dent + intrinsic haircut) instead of a placeholder pass. What is
  not defensible is defaulting into it silently — the finding is about *deciding*, not about which
  branch.

**Could not verify (blockers stated):**
- **Per-name live marks under healthy feeds.** The sandbox proxy rate-limited Yahoo (peer and
  holding fetches) and intermittently timed out FRED; live ratings were computed on last-good
  cached closes (06-24). The live `floor_degraded` flags and the DEGRADED_STALE status are
  therefore *expected* under these conditions — the finding is that the cockpit hides them, not
  that the book is degraded on a healthy desk.
- **The exact eval-loop blocking mechanism.** The ~50-minute warm-up and the stale-default serving
  were observed; the precise serialization path (which fetch blocks which cycle stage) was not
  traced to the line.
- **DELEGATED-UNVERIFIED rows in the tables above** (marked per-finding): principally TF3's
  ingestion-leg detail, uranium momentum-proxy scope, `as_at()` mechanics, DGS2 as-of string; TF2's
  book_change internals, payoff-learner feeder line numbers, WS-doc quotes; TF5's T-pillar leak
  percentages, blend-fallback path, no-zero-intrinsic-test claim; TF1's stance-chip `tail[:5]`
  fallback and TUI registry lines. Each was reported by a scan with quoted code; the lead
  re-verified every headline and every money-relevant mechanic, but did not re-read these
  supporting anchors line-by-line.
- **Whether the 06-26 "runway" router collision has ever misfired in practice** — no routing log
  exists to check.
- **The physical LED panel** (06-26 item 0.4): status unchanged from the Phase-0 audit
  (DORMANT-BUT-WIRED); not re-verified this session.

**Session hygiene note:** running the engine this session appended 4 rows to
`data/valuation_ledger.jsonl`, froze URC.TO's first decision row in `data/living_memory.jsonl`
(the append-only stores working as designed), advanced `data/price_history.json` (one 07-02 close
per name) and `data/catalysts.json`'s generated-at stamp. These runtime byproducts are committed
separately from this document and flagged as live-run stamps, not research edits. Nothing in
`v5_config.json`, the book, or any tunable was changed.

*Nothing above is done. Every tunable/book/config touch is marked propose→confirm or
operator-decision. The engine ran live this session under degraded feeds; every live claim is
scoped accordingly. When a claim here conflicts with the tree, the tree wins — re-grep, re-verify,
report the correction.*
