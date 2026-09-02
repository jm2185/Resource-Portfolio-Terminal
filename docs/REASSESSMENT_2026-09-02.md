# CommodityEx — Standing Reassessment (2026-09-02)

*A five-task-force sweep under the standing charter, 56 days after the 2026-07-08 sweep. **The
engine was NOT run this session** (offline in this environment; not authorized) — this is a
code/config/data sweep of the committed tree at `69963e4` (main; branch
`claude/commodityex-standing-reassessment-41o3l9`). Method: four parallel deep scans (TF1–TF4),
each briefed to re-grade every 07-08 finding (FIXED / PERSISTS / PARTIAL / WORSE / NEW) and audit
the tree from first principles; the TF5 scan died on an API rate limit before producing anything,
so the lead ran TF5 directly. Every headline finding was independently re-verified by the lead
against the tree, the data stores, an offline run of the pure grading modules, and the test
suite. Tags: **VERIFIED** (lead re-read the code/data or ran it), **DELEGATED** (a scan quoted it;
the lead did not independently re-read), **COULD-NOT-VERIFY** (blocker stated). Gate tags are
binding: read-only · code-behind-tests · propose→confirm · operator-decision · data-store.
Staleness is computed as of 2026-09-01 (the last close before the sweep). Nothing was executed
beyond this document — no config, book, tunable, store, or manifest was changed.*

---

## Executive Verdict

**The desk moved; the engine did not.** Since 07-08 the operator changed almost everything about
the book — URC.TO decommissioned as never-held, GMX.TO sold, CEG built to a 12% ceiling in a new
conventional lane, a macro sleeve formalized around a realized +60% TLT round-trip, a SNAG.V
tracker bought, and the spear itself signed into a fixed-ratio all-share merger with Bunker Hill
(0.1724 BNKR/AGA, vote ~Nov 15) — and produced its best research of the summer in prose: the arb
math, the zero-premium line, the vote-indifference threshold, the arrangement-agreement read. The
engine still describes the July book, ran on 26 calendar days out of 82 (none in July, none since
08-25), and — the sweep's headline — has been stamping its own cold-start constants into the
track record it is supposed to be graded against. Five findings dominate:

**1. The book the engine models is not the book the operator holds (TF2 — VERIFIED).** The
manual and the slot table still describe a four-name resource barbell (AGA/GROY/GMX/URC). The
Wealthsimple export the desk reconciled on 08-29 (Living Memory `20260829-1429`) says: AGA.V
5,400 sh = 54.7% (basis ~C$0.946, −C$950), GROY 330 sh = 20.1% plus a Jan-2028 $5 call, CEGS 54
CDRs = 13.4% (**above** the 12% ceiling by drift), a 1,000-share SNAG.V tracker, a UROY call
stub, cash — unrealized −9.9%, all of it the spear. The config's `barbell_weights` is
`{AGA.V .6, GROY .4}`; `archetype_barbell_weights` is a 0.75-sum residue (`{AGA.V .6, GROY .15}`)
under a comment that still says "60/15/15/10"; SNAG.V is badged ◇EVAL "rated, not held" while it
is in fact held; the CEG ceiling exists only in Memory (no `target_weight`, so the conventional
sentinel's rebalance band is dormant); `ai-upside-ballast` is in no slot taxonomy; and the
committed-tree NAV is `target_capital` 5,360 against a ~C$7.6k book. Most consequentially:
**`portfolio_metadata.AGA.V.corporate_action` has zero code readers**, no feed carries BNKR, and
the engine prices, rates, and Kelly-sizes AGA.V as a standalone option-convexity explorer (REP
floor, `red_mtn_drill` probabilities, ρ 5.4 / φ 0.72 / "THESIS INTACT — MONITOR" on 08-25)
while it trades as a BNKR-ratio instrument with a vote option. The single most valuable
analytical object of the moment — the spread, the C$3.91 zero-premium line, the D > 0.67A vote
threshold — lives only in prose notes.

**2. The price layer's cold-start constants are in the track record (TF3↔TF5 — VERIFIED).** The
chain: the engine seeds `state_cache["prices"]` with hardcoded constants badged `"prices_status":
"LIVE"` (`engine.py:236-242`; GROY 3.22 × the seeded 1.38 FX = **4.444**, AGA.V 0.72) → the
valuation ledger's `daily` trigger fires on "the first stamp after a UTC date roll"
(`valuation_ledger.py:322-324`), i.e. the cold-start cycle → `_record_valuation_ledger` writes
every basket's `snap["price"]` into the replay ground-truth store via `record_mark` with **no
stale/fallback check** (`engine.py:3252-3256`) → the mark becomes immutable at the date roll
(`price_history.py:60-83`). Evidence: **13 of 13** August AGA.V `daily` rows carry 0.72 while the
store's own closes read 0.65–0.81; **7 of 7** GROY `daily` rows from 08-17 to 08-25 (a Sunday
included) carry 4.444; `data/price_history.json` holds 8 GROY dates at 4.444 and AGA.V 08-02 at
0.72; the 06-23 GROY flywheel decision (`φ 1.001 — at the floor`) and the 08-13 GMX.TO decision
(2.04 = the seed) were frozen on constants; on 08-14 the GROY directive flipped CORE HOLD →
BELOW FAIR VALUE — ACCUMULATE → FAIR VALUE — HOLD minute-to-minute as seed and real prices
alternated (ledger 12:10–14:03). `data/seesaw_history.jsonl` is seven rows of gold 2350 / silver
74.8 / real-yield 1.0-or-1.8 — the seeds, alternating between two different fabricated defaults
for the same leg. The 07-08 fix ("the last-good cache never holds a fallback") is true and
irrelevant to this path, and the 09-01 dashboard commit now serves the contaminated store as
"live closes." Letter-not-invariant, instance five.

**3. The grading loop has produced zero real grades, one contaminated prior, and the yardstick's
one honest read has never been surfaced (TF5 — VERIFIED).** Fifteen decisions, four outcomes —
all `SCRATCH +0.0%`: AGA's is correctly quarantined as `suspect`; GMX's two are seed-vs-seed and
a same-moment close. The learned base rate the flywheel rolls forward (`asset_light_yield`, n=2,
expectancy 0.0, downside containment 1.0) is derived entirely from those artifacts. The
Conviction Book holds two rows, both engine seeds at 50%. The forecast book is the live
calibration instrument (34 rows in five weeks, 2 resolved, Brier .06/.16) — but it grades the
operator's macro and merger calls, never the rating or a ladder leg. Meanwhile the replay
harness, run offline this session for the first time anyone has looked: at 30 days it reports
**P10–P90 coverage 5.5% against a claimed 80%** and **the floor tested on 2,728 of 2,733
snapshots and held on none** (60 days: coverage 87.7%, floor held 0/2,728; 90 days: n=0) — with
n inflated ~100× by the stamp storm (GROY is 2,394 of the 2,733). Read honestly: **both names'
stamped floors were breached inside the window** (GROY's book-value floor by ~20% in July, AGA's
REP floor on 07-29), which is the margin-of-safety yardstick failing its first test. Nobody has
read this number because nothing surfaces it. `data/dynamic_config.sqlite` has 0 overrides, 0
pending, 0 audit rows: **no tunable has ever been changed through propose→confirm** — every
constant in the rating ("reasoned, not backtested — TUNE") is at its hand-set default.

**4. The chat is the desk's instrument panel, and the conductor has been writing notes instead
of playing the instruments (TF4↔TF1 — VERIFIED).** The manual's own contract is that the chat
IS the recording device: hear a rule, write a thesis claim; hear conviction, price it; hear a
decision, record it; convene the Council when a thesis is contested. The instruments exist and
work — `thesis_write` claims and the trigger grammar, `record_conviction`, `sentinel_sweep`,
`/council`, `forecast_write` — and the one the conductor did drive (the forecast ledger: 34 rows
in five weeks) is the one part of the calibration loop that is alive. Everywhere else the
conductor reached for `memory_write(note)`: 339 Memory rows in August (~11/day), 58% without a
ticker; the operator's standing rules (the AGA month-24 review rule, sell-half-at-a-double, the
TLT exit ladder, the storm-ticket sizing doctrine, the sourcing standard, fit vetoes) are prose
notes rather than the thesis claims the Sentinel evaluates; the operator's stated convictions
went to prose or to forecasts, never to `record_conviction`; the Council has **never** persisted
a verdict (0 `council_verdict` rows; the strip has only ever rendered its fallback); the Sentinel
ran once (07-31, thesis-only); the Thesis Check that ROADMAP calls "substantially shipped" has no
trigger. This is not "the desk should run the engine more" — it is that the conversational layer
must route judgment into the typed instruments as a matter of course, because every note that
should have been a claim is a rule the Sentinel cannot fire and a grade the flywheel cannot
score. The gate side compounds it: the disconfirmation gate is satisfiable by two receipts
(both SNAG graduations cite the same entry as verifier *and* forensic) and `memory_write`
accepts gate types (`graduation`, `promotion`, `outcome`) from any agent. And the test suite now
**pins the old book**: 8 tests fail on the committed tree (GMX.TO/URC.TO membership ×6, CEG
`units == 24`, the barbell key set), CI has failed on every push since at least 08-28 (784 runs;
the last 25 all failed or cancelled), and the last two commit messages call the failures "known
pre-existing live-config regressions." A red suite nobody reads is worse than no suite.

**5. Follow-through went the way the 07-08 sweep warned, and the repository lost its own
history (all TFs — VERIFIED).** The AGA.V waiver lapsed by default on 07-16 (still the verbatim
`PLACEHOLDER`, expiry 2026-07-15); the real dilution/CBA tests re-engaged on an 81-day-old
working-capital proxy whose runway (C$48M / C$2.75M = 17.45 mo) fails the 18-month bar on the
config's own numbers. `material_change` hysteresis is unshipped (3,437 of 3,515 ledger rows are
stamp-storm rows; 602 GROY rows on 06-23 alone). The directive enum is unshipped for the fourth
audit (eight keyword parsers, plus a second legacy directive vocabulary on `/state`). And on
08-28 the repo was re-initialized: 50 commits, root `4e8bad7`; the 07-08 document's SHAs no longer
resolve; `v5_config.json` sits in `.gitignore:20` and is only force-tracked; the July run-history
hole is permanent. The store fork recurred in a new shape — the ledger stops 08-25, Memory runs
to 08-30, and AGA closes for 08-24..28 were hand-added.

**The through-line:** every mechanism this desk built to keep itself honest — the append-only
stores, the PIT discipline, the replay harness, the flywheel, the test gate, the human confirm —
is present and mostly well-made, and each is currently either measuring a book that no longer
exists, grading constants against constants, reporting a failure nobody reads, or waiting for
the conversation to call it. In a
concentrated book the expensive failure is still false confidence; this quarter's form of it is a
cockpit that renders a 7.2 HIGH QUALITY on a ballast whose price it has not seen in a week, and
a THESIS INTACT on a spear that is now a merger arb.

---

## What changed since 07-08 (verified against the tree)

**Shipped and survived (07-08 execution, re-verified):** `dxy`/`ry` cold-start seeds →
`INITIAL_BASELINE` (`engine.py:246,253,262`); the MRI positional-input honesty scan
(`engines/macro_regime.py:404-410`, caller passes silver + real_yield); `set_nav` in every
manifest deny-list and `_HEADLESS_DISALLOWED`; `memory_write(provenance=…)` clamped at `sourced`;
the research-cache PIT validator — **`pit_violations()` returns `[]` today, the two GROY entries
were re-written** (execution item C, first half); `--disallowedTools` injected on the job and
pipeline lanes; the uranium day-45 boundary; the φ≥1 `BELOW PROXY FLOOR — VERIFY` gate with the
council prior and chip in sync; the sizer's book-derived ballast set with `corr_source`; the
`UNRATABLE` rotation verdict. [VERIFIED mechanics; DELEGATED for the manifest and lane details]

**New and good (07-08 → 09-01):** the dual-sided provenance sidecar with the `basis` vocabulary
(`filed | derived | modeled | street`) and `provenance_flags` — the CEG street-number lesson made
structural (`dual_sided.py:508-560`); AGA ounces re-stated per district (`in_ground_by_district`,
2026-08-13); the GMX holdco NAV re-strike that preceded the sale; the seesaw-day classifier;
the Garage lane; the web dashboard's isolated render steps and health chip; the gemini/agy lane
**retired** (the 07-08 open door closed by removal, not by gating); the forecast ledger in
daily use with supersession discipline; the handoff rulebook R-1..R-8 in Memory and docs.
[VERIFIED for dual_sided, ounces, pit scan, retirement; DELEGATED otherwise]

**Not decided / not done (07-08 surfaced items A–G):**

| # | Item | Status today | Evidence |
|---|---|---|---|
| A | AGA.V waiver decision (expiry 07-15) | **Lapsed by default** — `PLACEHOLDER` still in config; `_override_active` returns False on expiry (`engines/forensic.py:255-259`) so the real tests have run since 07-16 | VERIFIED |
| B | Cash/burn refresh from filed quarters | **PARTIAL** — cash C$48M as_of 06-12 is an issuer-PR working-capital proxy (81 d); burn C$2.75M as_of 01-21 retained 07-08 "no grounded basis to lower"; runway on config inputs 17.45 mo < 18 | VERIFIED |
| C | GROY cache re-write + Memory backfill of the $1B rejection | Re-write **FIXED** (`pit_violations()` = []); backfill not found in Memory | VERIFIED / DELEGATED |
| D | Uranium second source | Re-stamped US$86.48 as_of 08-08, but URC.TO is out and no code consumes the stamp (UROY call marked by operator note) | DELEGATED |
| E | Host→repo cadence for the stores | **Recurred in a new form** — repo re-initialized 08-28; ledger last row 08-25 vs Memory 08-30; AGA closes hand-added in `b9b768f`; no written cadence | VERIFIED |
| F | Grading readiness by 07-12 | **Missed** — zero engine run-days in July; first grades are the artifacts in finding 3 | VERIFIED |
| G | `survival_exempt_archetypes` alignment · FRED label · hysteresis · `set_nav` proposal-routing · gemini gate | Alignment PERSISTS (config `["asset_light_yield"]` vs code `+compounder,deep_value`); FRED label PERSISTS (dormant); hysteresis **PERSISTS** (no code); `set_nav` still direct for the main session; gemini lane retired | VERIFIED (hysteresis, alignment) / DELEGATED (rest) |

---

## TF1 — Signal & Communication

**(a) First principles.** The cockpit exists to hand a solo operator one decision-ready read per
name — a verdict with its own confidence attached — and to make every mutation pass a mechanical
human gate. Two corollaries this sweep adds. First, **a number rendered without its uncertainty
is a claim, not a signal**: a 7.2 printed on a price the engine has not seen for a week is not
"precise," it is wrong to one decimal. Second, **the router is only as honest as the state it
routes into** — a natural-language table that describes a four-name book routes the operator's
questions to the wrong object.

**(b) Hard questions.** Why does the rail print φ to two decimals and the rating to one on
inputs whose own stamp says `confidence: low` and `age 389 d`, while the P10–P90 band the engine
computes for exactly that purpose appears nowhere but a detail card? Why has the Council strip's
verdict slot rendered its fallback 100% of the time for three months, and why does nothing on
the face say so? Why is the directive still a prose string parsed by keyword in eight places —
fourth audit — with a second, legacy book-level vocabulary on `/state` that no parser knows?
Why does the daily brief say nothing about a forecast past its resolve-by date, a waiver 48 days
lapsed, a garage week unclosed, or a corporate action on 55% of the book? Why can `add_holding`
and `garage_set_ladder` write `v5_config.json` from any subagent or headless seat when every
tunable needs a human confirm — and why does the drift guard that was built to catch exactly
this only look at name prefixes?

**(c) Current practice & strains.** The production chain is coherent (one `asymmetry_rating`
output dict, one `regime_posture`, one `/state`), and the provenance tells on the rail, the
φ≥1 proxy-floor gate, and the deny-list parity test all held through the summer's refactors.
The strains are in what reaches the operator's eye and what can mutate state without a gate.

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | Directive = prose contract parsed in **8** sites (council prior, widgets `tail[:5]`, cockpit_events, calibration ×2, coherence_check, matrix board, world_state `split('—')[-1][:18]`); silent 0.50 fallback; FAIR-VALUE≡0.50 collision; plus a legacy book-level directive vocabulary published at `engine.py:4578-4590` | `council.py:49,109-114` · `cockpit_widgets.py:287-312` · `calibration.py:68-76,857-870` · `world_state.py:117` | **WORSE** (enum unshipped, 4th audit) | DELEGATED |
| 2 | Uncertainty never on the face: the ribbon appears only on the detail card/dossier (`commodityex_tui.py:1444,2383`); the web has no ribbon field; agents receive the 2-dp rating (`core.py:915`) while the operator sees 1-dp; P10/P90 rendered nowhere | `asymmetry_rating.py:960` · `web/cockpit.html:656-662` | PERSISTS (never asked before) | DELEGATED (render) / VERIFIED (ribbon exists in every ledger row and reaches no surface) |
| 3 | The ribbon decorates a different centre than the point: AGA.V 08-25 row `intrinsic 1.125` (the spear's scenario base, `engine.py:3348-3352`) vs `ribbon p50 1.70` (the distribution over the triangulation legs cost 0.74 / market 2.33, `asymmetry_rating.py:741-750`); ribbon `quality: full` on a 389-day-old ounce input | `data/valuation_ledger.jsonl` (id `20260825-215250`) | NEW | VERIFIED |
| 4 | Endpoint confirm-guard still inert on the MCP path (`confirm_param_change` POSTs no `source`, endpoint defaults `"cockpit"`); deny-list remains the sole closure | `mcp_server/core.py:794-798` · `engine_api.py:289` | PERSISTS (Phase 1.3 unshipped) | DELEGATED |
| 5 | Two config writers outside every cage: `add_holding` (`core.py:1144-1154`) and `garage_set_ladder` write `v5_config.json` on self-`confirm=true`; in **0/15** manifests' deny-lists, not in `_HEADLESS_DISALLOWED` (`commodityex_tui.py:6789-6792`), invisible to the prefix-based parity guard (`test_agent_manifest_denylist.py:47`) | as cited | **NEW** | VERIFIED (deny-lists, headless set) / DELEGATED (guard) |
| 6 | `set_nav` still a direct research-cache write for the main session and cockpit; gate = any `source_url` string | `core.py:751-772` · `engine_api.py:307-340` | PERSISTS (07-08 item G) | DELEGATED |
| 7 | Council strip verdict slot has never shown a verdict (0 `council_verdict` rows); the collapsed strip seeds it with the raw directive | `commodityex_tui.py:7154-7160` · store | PERSISTS, now known to be the only path ever rendered | VERIFIED (store) / DELEGATED (render) |
| 8 | Brief blind spots: no due/overdue forecasts (one overdue today: the TLT fill forecast, resolve-by 08-28), no unclosed garage weeks, no waiver expiry, no corporate action, no proposal age; offline hook = one line | `.claude/hooks/daily_brief.py:29-31` · `core.py:3356-3399` | NEW | VERIFIED (overdue forecast) / DELEGATED (flags) |
| 9 | Pins/highlights: no TTL, not persisted, highlights expire only when the next annotation arrives; `conclusion_decay` inert (0 rows carry `meta.assumptions`) | `engine.py:2607-2634` · `conclusion_decay.py` | NEW | DELEGATED |
| 10 | Web computes its own signal: conventional-row directive/φ/upside synthesized client-side (`cockpit.html:1101-1110`), two-colour band, a hard-coded 0.60 concentration bar while the engine publishes `single_factor_threshold` | `web/cockpit.html:383,701-703` · `book_factor.py:104` | NEW | DELEGATED |
| 11 | 13 engine keys computed every cycle and read by no surface (`sentinel_board`, `thesis_monitors`, `conventional_zones`, `conditionals`, `seesaw_day`, `rates_dashboard`, `inflation_regime`, `macro_regime`, `valuation_detail`, …) | grep across TUI/widgets/web/core/world_state | NEW | DELEGATED |
| 12 | Router: 86 registered tools, 47 with a CLAUDE.md row, **27 truly dark** (`catalyst_write`, `thesis_claim_set`, `sentinel_ack`, `sentinel_sweep`, `forecast_resolve`, `set_barbell_weights`, `backfill_decisions`, …); first-match dispatch with the "runway" collision; no did-you-meant | `cockpit_widgets.py:806-823` · `commodityex_tui.py:6449-6457` | PERSISTS + inventory | DELEGATED |
| 13 | Colour band flips on a 0.01 wobble (no hysteresis) — and did, minute-to-minute, on 08-14 GROY | `conviction_health.py:23-49` · ledger 08-14 | PERSISTS, now observed in data | VERIFIED (data) / DELEGATED (code) |
| 14 | Grid/brief truncate the longer directives (`[:22]`, `[:18]`: "BELOW PROXY FLOOR — VE") | `commodityex_tui.py:1101` · `world_state.py:117` | NEW (minor) | DELEGATED |

**(d) Alternatives.**

| Option | Trade-off | Recommendation | Gate |
|---|---|---|---|
| **Directive → `(code, display_text, side, prior)` enum** emitted once by `asymmetry_rating`; every parser keys off `code`; retire the legacy book-level string | 8-site refactor; one-time re-pin of the council prior snapshot; the sync-guard test becomes trivial | **ADOPT** — fourth audit asking; the 08-14 flip shows the cost of prose | code-behind-tests |
| **Uncertainty-first face**: render `P10–P90` (or `± band · quality`) beside every rating/φ/ρ on rail, council strip, web; round the rating to the ribbon (1-dp when quality ≠ full, hide 2-dp from agents too); a `~stale price` glyph whenever `prices_stale[tk]` | Rail width; some operator re-learning | **ADOPT** — this is the "false precision" cut the charter asks for | code-behind-tests |
| **One `signal_state` per name** published by the engine (`rating, band_step, directive_code, phi_txt, rho_txt, ribbon_txt, tells[], price_source`) so TUI / web / world_state / matrix become pure renderers; the web's client-side conventional synthesis moves engine-side | Medium refactor; kills the two-surface drift class (#10, #14) | ADOPT after the enum | code-behind-tests |
| **Mutation registry in the registration loop**: `MUTATING = {tool: GateClass}` in `server.py`; every passthrough is `READ`, `LOG` (append-only), `CONFIRM`, or `PROPOSE`; manifests and `_HEADLESS_DISALLOWED` generated from it; explicit `source="mcp:<tool>"` on every POST so `_write_source_ok` finally bites | Cheap; only cost is naming a class for ~30 gate-less tools | **ADOPT** — closes #4, #5, #6 in one seam | code-behind-tests + operator-decision (which append-only writers stay open to agents) |
| **Brief = due-list first**: overdue/due forecasts, unclosed garage weeks, waiver `days_until_expiry`, proposal age, open corporate actions; online `get_world_state` reuses the offline readers | None material — all readers exist | ADOPT | code-behind-tests |
| Pin TTL (7 d default, `sticky` opt-out), highlights pruned on `publish_state`, both persisted to Memory; auto-seed `meta.assumptions` (φ, runway, MRI) so `conclusion_decay` has something to sweep | Slight write volume | PILOT | code-behind-tests |
| Surface diet: retire or fold the 13 unread engine keys and the panels nothing populates | Loses optionality on future panels | PILOT (read-only inventory first) | read-only → operator-decision |

**(e) Next steps.** 1) Mutation registry + explicit MCP `source` (closes the two open config
writers this week). 2) Directive enum. 3) Uncertainty-first face + `~stale price` glyph (rides
on TF3 Phase 1). 4) Brief due-list. 5) `signal_state` consolidation. 6) Pin TTL / surface diet
pilots.

---

## TF2 — Book Construction & Capital Allocation

**(a) First principles.** The barbell is a *shape* — one convex spear whose downside is
structurally bounded, plus ballast that survives the scenarios the spear does not — and the
book's structure must be the sharpest expression of the thesis *the operator actually holds*,
not of the thesis the config was written for. The operator's own recorded doctrine governs
(Memory 08-14: "concentration isn't a bad thing … if we've done the work on the name";
"concentration flags MEASURE and surface shape, never veto — sizing is the operator dial"; 08-11:
"Kelly multiple formally OVERRULED by operator"). So the engine's job in this task force is not
to size — it is to **measure the book that exists**, honestly, in its current instrument form.
The corollary this sweep adds: **membership is what Wealthsimple says it is**, and every
structural gauge (ceiling, coverage, concentration, sizing directive) is only as true as the
membership and weights it reads.

**(b) Hard questions.** Is 55% of a C$7.6k book in a fixed-ratio merger arb with a vote option
still "the spear," and if the desk believes it is (Memory 08-21: "slot-breaking does not mean the
ownership factors broke"), why does no line of code know the instrument changed? Why does the
config still carry a 60/15/15/10 residue, a phantom GMX node, four-name hardcoded lists in the
comps worker and price fetch, and a default barbell that would **resurrect URC and GMX as members
on a weight typo** (`engines/util.py:180,196-199`)? Why is the 12% CEG ceiling — the one sizing
rule the operator wrote down and then breached by drift (13.4% on 08-29) — a Memory note rather
than a `target_weight` the sentinel already knows how to band? Why does a two-name resource
barbell with a 0.40 ballast sleeve run under a 0.20 single-position cap, so that the sizer can
never deploy more than half of NAV and the health radar reads a permanent TRIM? Is every name
earning its slot — the machine still cannot say: 0 council verdicts, 0 swap verdicts, GROY's ρ
is null so `/rotate` is UNRATABLE by construction, and the only ballast has never been counciled.

**(c) Current practice & strains.**

| # | Strain | Anchor | Status vs 07-08 | Confidence |
|---|---|---|---|---|
| 1 | **Spear priced/rated/sized as a standalone explorer** while it trades as a BNKR-ratio instrument: `corporate_action` has 0 code readers; no BNKR in the worker ticker list (`engine.py:731-734`); no vote row in `catalyst_calendar.jsonl`; `catalyst_probabilities` still `red_mtn_drill 0.73` etc.; the sizer's Kelly runs on the standalone `u_implied` (`engines/sizer.py:227-250`) and its liquidity cap on AGA's own ADV | `v5_config.json` AGA.V block · grep | **NEW — the decisive strain** | VERIFIED |
| 2 | Two-name barbell under a four-name cap: GROY `0.40` sleeve vs `max_single_position_pct 0.20` → deployable NAV = 50% (`sizer.py:297-308`: cap = NAV × limit / w) → `allocation_ratio ≥ 2.0` = the `trim_ratio` → permanent OVER-ALLOCATED directive / TRIM priority on the rail | `sizer.py:305-308` · `engines/health_radar.py:153-158` · `v5_config.json` guardrails | **NEW** (created by the 4→2 reduction) | VERIFIED (mechanics) / live values inferred |
| 3 | Membership ≠ WS truth in both directions: SNAG.V held (1,000 sh) but `eval_only` — no NAV term, skipped by the flywheel, badged "rated, not held"; the UROY call is a hardcoded NAV term, not config; no config↔export drift check; committed-tree NAV = `target_capital` 5,360 vs ~C$7.6k | `v5_config.json:498-505` · `engine.py:3720-3730` | **NEW** | VERIFIED (config, Memory) / DELEGATED (NAV code) |
| 4 | No tool can add a resource name to `barbell_weights` (`add_holding` refuses barbell names; `set_barbell_weights` validates against existing keys) — "the reweight flow" is a hand edit | `core.py:1093-1097` · `dynamic_config.py:176-182` | NEW | DELEGATED |
| 5 | `archetype_barbell_weights` = `{AGA.V .6, GROY .15}` (0.75) after `remove_holding` pops without renormalizing; the "supplementary CAD book intrinsic" is misweighted; comment still says 60/15/15/10 | `core.py:2485` · `v5_config.json` | NEW | VERIFIED |
| 6 | Four-name residue: `util.py:180` default barbell; `engine.py:1133` corr frame and `:782` price fetch still name GMX/URC; GMX phantom node (`engine.py:4654-4658`, rendered); `core.py:994` offline fallback; docs (`CLAUDE.md` slot table, `WALKTHROUGH.md`, `COCKPIT.md`); tests pin the old book (8 failures) | as cited · `tests/test_v5_engine.py`, `test_archetypes.py`, `test_sizer_corr_membership.py`, `test_conventional_holdings.py` | **NEW** | VERIFIED (tests, config) / DELEGATED (code sites) |
| 7 | Conventional lane rules live only in Memory: no `target_weight` → `rebalance_band` dormant; no credit-sentinel or tranche gate in code; scenario coverage takes CEG at the tranche-1 `book_share_fallback 0.073`, not ~13% | `conventional_sentinel.py:123-153` · `v5_config.json` CEG block · `scenario_engine.py:315-317` | NEW | VERIFIED (config) / DELEGATED (coverage) |
| 8 | `ai-upside-ballast` in no slot taxonomy (`discovery_screen.py:43-69` has four slots); CLAUDE.md slot table still lists GMX.TO and URC.TO's closed slot | as cited | NEW | VERIFIED (docs) / DELEGATED (screen) |
| 9 | Rotation gate unfireable on the only ballast: GROY ρ null on 08-25; friction fails closed to 0.22 with no `adv_median_90` anywhere; 0 swap rows ever | ledger · `council.py:368-369,404-414` | PARTIAL (UNRATABLE shipped; fire-ability not) | VERIFIED (ledger) / DELEGATED (code) |
| 10 | 0 `council_verdict` rows; all flywheel decisions are engine seeds; GROY's only open decision was frozen on the seed price (06-23, 4.444) and reaches its 90-day horizon **~09-21** — it will close as another phantom unless voided | store · `calibration.py:873-935` | WORSE | VERIFIED |
| 11 | `_redistribute` ×3 copies; no thesis-review clock; the 07-08 items unchanged | `dynamic_config.py:200` · `book_change.py:33` · `core.py:2375` | PERSISTS | DELEGATED |
| 12 | The removals left no receipts: 0 `decommission` rows, no `.mcp_backups`, no pre-08-28 history — URC (08-01, "CONFIG-ONLY, never held") and GMX (08-13/14) exist only as operator notes | store · git | NEW | VERIFIED |

**Data facts.** Fifteen decisions (3 engine-flywheel seeds 06-23; CEG t1 08-01; AGA HOLD/NO-ADD
08-02; AGA flywheel 08-10; CPI hedge PASS 08-11; CEG ceiling 12% 08-12; GMX flywheel TRIM 08-13;
GMX SELL 547 sh 08-14; TLT 2× Jan-27 85C 08-18; CEG t2 → 44 08-18; SIT TIGHT + TLT limit 08-25;
TLT sold +60% 08-28; CEG +10 → 54 08-29). Operator-recorded structure: resource sleeve ~75% of
book with GROY's structural target confirmed at 30% (08-20); the standing sourcing rule
(capital-efficiency edge, LEAP-ability, one-sentence fit); fit vetoes on RPRX and G; the
"binary overlay" protocol; the macro sleeve mandate (08-29).

**(d) Alternatives.**

| Option | Gain | Cost / trade-off | Gate |
|---|---|---|---|
| **(i) A merger-arb instrument state for the spear until close**: a `corporate_action` reader that (a) adds BNKR to the worker list, (b) publishes the ratio-implied mark `0.1724 × BNKR`, the spread, and the zero-premium line as engine facts, (c) swaps the ladder to a bounded payoff with the vote/dissent/superior-proposal optionality as the convexity leg, (d) suspends the `red_mtn_drill`-style probability blend and adds the Nov-15 vote to the calendar, (e) sizes the instrument held; identity sweep at close as the config already promises | Ends #1; the desk's arb notes become engine inputs; the Sentinel can watch the spread | A new archetype/state + tests for a ~3-month condition; risk of over-building — mitigated by keeping it a *state* on the existing archetype, not a new class | code-behind-tests + propose→confirm (ladder, calendar) |
| **(ii) Formally a two-name resource barbell + a conventional core + a macro sleeve**: retire the four-name residue everywhere (config defaults, hardcoded lists, docs, tests), renormalize `archetype_barbell_weights`, add `ai-upside-ballast` and `conventional` to the slot taxonomy, and make the single-position cap slot-aware (a ballast sleeve may carry its structural weight) | Ends #2, #5, #6, #8; docs stop lying; CI goes green for the right reason | Loosening `max_single_position_pct` for ballast is a real risk decision — it is a tunable (propose→confirm); the 60% spear ceiling is not touched | code-behind-tests (residue) + propose→confirm (cap) |
| **(iii) Membership = WS truth**: a pure `reconcile(export_rows, cfg)` → drift report (held-not-member: SNAG.V, UROY; member-not-held; units/weight drift; CEG vs `target_weight`) surfaced at session start; a resource-add tool (`barbell_weights` with a new key, redistribution proposed) | Ends #3, #4, #7 detection; turns the 08-29 hand-typed reconciliation into a computed one | The export stays a manual drop (gitignored, as it should be); parser needs one real export (the 06-30 assessment's unverified column schema) | code-behind-tests → operator (export) |
| **(iv) CEG ceiling as config**: `target_weight 0.12` + the credit-sentinel claim as a thesis rule the Sentinel evaluates | The one operator-written sizing rule becomes mechanical; the 13.4% drift would have flagged itself | None material | propose→confirm |
| **(v) Route or fence the diversified-book sizing**: feed the cause ("GROY sleeve vs 20% cap") into the directive text, and gate the TRIM priority on `n_resource_names ≥ 3` | Stops a structural artifact reading as a risk signal | Loses nothing (ES/VIX throttles still compose onto posture) | code-behind-tests |
| **(vi) Dollar-risk expression at C$5–8k**: caps in C$ (min lot, spread, FX round trip) rather than ADV%; the liquidity cap is ~4.5× NAV and can never bind | Honest at this scale | Needs measured WS friction — none captured | operator-decision → code |
| (vii) Void-and-refreeze the seed-priced GROY decision before ~09-21; freeze a real one at a live mark | Prevents the next phantom grade | Requires a live engine cycle with a fresh GROY quote | data-store / operator |

**(e) Next steps.** 1) The spear's instrument state (i) — before the vote, ideally before the
assays. 2) Void/refreeze GROY (vii) before ~09-21. 3) Residue purge + slot taxonomy + green CI
(ii). 4) `target_weight` for CEG (iv). 5) WS reconcile (iii). 6) Sizing fence (v); dollar-risk
pilot (vi).

---

## TF3 — Data Provenance & Inputs

**(a) First principles.** Grounded-or-silent at the input boundary: when a feed fails the
operator must be able to tell, and — the corollary this sweep adds — **a failed feed must not be
able to write**. A store that accepts a fabricated value once and then protects it as immutable
history has inverted the point-in-time discipline: it now guarantees the fabrication survives.
Freshness honesty is not a flag on the number; it is a property of what the number is allowed
to do (be stamped, be graded, drive a directive).

**(b) Hard questions.** How did seven consecutive GROY "daily" marks at exactly 3.22 × 1.38 get
into the replay ground-truth store, and why did the 07-08 fix that "killed the real↔fallback
oscillation" not cover the one write path that matters? Why does the engine seed `prices_status:
"LIVE"` over hardcoded prices after two sweeps fixed the identical pattern on `dxy`, `ry`, and
`cftc`? Why does a seed silver of 74.8 and a seed gold of 2350 sit in `seesaw_history.jsonl` as
if they were the tape, and why does `spot_ag_status` inherit a holdings-only `prices_status`? Why
is the spear's only survival input an 81-day-old working-capital proxy from an issuer PR, with
the filed MD&A "not located — SEDAR+ bot-walled," when that number now decides a failing runway
test? Why does no feed carry the acquirer of 55% of the book? What is the repository's audit
trail worth if the history before 08-28 no longer exists in it?

**(c) Current practice & strains.** The strong layer holds: `resolve_freshness` stamps
provenance and staleness per ticker, `merge_last_good` refuses to carry a fallback, the research
cache validates confidence vocabulary and look-ahead on every load (`pit_violations()` = [] today),
the dual-sided sidecar makes `basis: street` loud, and the forecast ledger is in daily use. The
strains are where honest metadata stops short of changing behaviour.

| # | Strain | Anchor | Sev | Confidence |
|---|---|---|---|---|
| 1 | **Seed/fallback marks written into the replay store and the ledger** with no stale guard; the daily trigger fires on the cold-start cycle; immutability then protects the constant (GROY 4.444 ×8 dates incl. Sunday 08-23; AGA.V 0.72 on 08-02 and on 13/13 August daily rows) | `engine.py:236-242,3252-3256` · `valuation_ledger.py:322-324` · `price_history.py:60-113` · stores | **High** | VERIFIED |
| 2 | Cold-start seeds recorded as macro history (gold 2350 / silver 74.8 / real 1.0 alternating with the macro default 1.8) | `data/seesaw_history.jsonl` (7 rows) · `engine.py:252-256` · `macro_regime.py:229` | High | VERIFIED |
| 3 | `prices_status` still seeds `"LIVE"` (the born-LIVE pattern, fixed for 3 keys, not for the one that feeds every mark); `spot_ag_status` piggybacks on the holdings-only status, so a fabricated silver reads LIVE into the MRI | `engine.py:242,814-815,3698-3700` | High | VERIFIED (seed) / DELEGATED (spot_ag path) |
| 4 | Heartbeat gap and store fork: 26 run-days of 82; ledger stops 08-25, Memory 08-30; AGA closes 08-24..28 hand-added (`b9b768f`); repo re-initialized 08-28 (07-08 SHAs unresolvable; `v5_config.json` gitignored-but-tracked; a `.bak` tracked) | git · stores · `.gitignore:20` | High | VERIFIED |
| 5 | Waiver expired unreplaced; the real tests run on cash C$48M (issuer-PR proxy, 06-12) / burn C$2.75M (01-21, "modeled"): runway 17.45 mo < 18 on the config's own inputs; whether the live JSF used feed-derived burn is unknowable offline | `v5_config.json` `forensic_overrides`, `cash_burn`, `rep_floor_params` · `engines/forensic.py:255-291` | High | VERIFIED (inputs, code) / COULD-NOT-VERIFY (live score) |
| 6 | No BNKR feed; the worker's ticker list is hardcoded and still fetches GMX.TO/URC.TO; the ratio-implied AGA mark and spread are not computable by the engine | `engine.py:731-734` | Med-High | VERIFIED |
| 7 | AGA merged ounce base (2025-08-01, **396 d**, `confidence: high`) still copied into every ledger row beside the new district table; ribbon quality reads `full` | `data/research_cache.json` · ledger `inputs` | Med | VERIFIED |
| 8 | Staleness never changes a number: `uncertainty.py`'s 180-day half-life is inert because the only caller passes no `leg_age_days`; the uranium "cliff" only widened a ribbon; the MRI still computes on defaults with a 45.0 fail-safe | `asymmetry_rating.py:741-745` · `uncertainty.py:41-84` · `macro_regime.py:376-382,586` | Med | DELEGATED |
| 9 | Catalyst layer: `catalysts.json` 7 d past its 1-day TTL; 12/22 feed events without a URL (manual CSV has no URL column); `catalyst_lifecycle.reconcile` has no caller — the CEG Q2 window (08-06) is still `pending` 26 d later; `catalyst_probabilities` hand-set, no source/as_of, default 0.50 | `data/catalysts.json` · `data/catalyst_calendar.jsonl` · `catalyst_lifecycle.py:98-110` · `engine.py:4593-4600` | Med | VERIFIED (calendar row, config) / DELEGATED (rest) |
| 10 | Provenance schema half-shipped: CEG stamps 6/11 dual-sided inputs (`cap_years, quality, management_score, conviction, regime_alpha` unstamped and outside `PROVENANCE_LOAD_BEARING`); the guard is flag-only; the live CEG thesis still carries `bear_case_usd: 297` (street) — P1.2 unshipped | `dual_sided.py:508-560` · `v5_config.json` CEG · Memory `20260801-235712-8ef014` | Med | DELEGATED |
| 11 | FRED label drift (config/ingestion `REAINTRATREARAT10Y` vs code `DFII10`); ingestion fundamentals leg configured-but-dormant (cache file absent) | `v5_config.json` ingestion · `ingestion_pipeline.py:133` · `macro_regime.py:185` | Low (dormant) | DELEGATED |
| 12 | Stores with no `as_of`: `price_history.json` carries no currency/source per mark; `peer_set.json` undated; `sentinel_watch.json` 14 watches last reviewed 07-31 | data files | Low-Med | DELEGATED |
| 13 | GROY hard-floor layers 244 d old (> the 136-d staleness bar) on the only ballast; the $1B re-rate the verifier REJECTED and the LOW-confidence $60M blue-sky still in every ledger `inputs` | `holdco_nav_feed.py:62,134-146` · research cache | Med | DELEGATED (bar) / VERIFIED (entries) |

**Freshness ledger (as of 2026-09-01).** Price store: AGA.V last 08-28 (448 obs; 08-19/20
force-edited, 08-24..28 hand-added), GROY last 08-25 (517 obs; 08-17→08-25 all 4.444), OGN.V last
07-31, SNAG.V one observation, **GMX.TO / CEG / BNKR: none** (GMX was held to 08-13 with 32 ledger
rows and no closes — ungradeable). Research cache: 67 entries, 28 older than 180 d, 5 LOW; the
load-bearing stale ones are AGA cash (81 d, PR proxy), AGA burn (223 d, modeled), AGA merged
ounces (396 d), GROY producing-CF and G&A layers (244 d), GROY pipeline/blue-sky (LOW). Catalyst
feed generated 08-25. Forecast book: one row past resolve-by unresolved (TLT fill, 08-28 — the
desk recorded the outcome in prose the same morning), three due by 09-11.

**The un-auditable, load-bearing list (ranked).** 1) AGA cash/burn — decides runway, the REP
floor, and the EV that normalizes CBA. 2) Spot silver/gold/real yield whenever a feed dies —
seeds proven to persist for days into state and stores. 3) The AGA merged ounce table. 4)
`catalyst_probabilities`. 5) `management_score` / `fraser_index` (Q pillar, jurisdiction lens;
undated, unsourced; written by `promote_to_eval` from agent input). 6) GROY $1B re-rate + $60M
blue-sky. 7) CEG wacc/growth/stressed FCF + five unstamped tilts. 8) GROY hard-floor layers. 9)
The MRI static-fallback legs (copper/gold unflagged; CFTC seed). 10) Peer ounces (DV.V 1,434 d
LOW).

**(d) Alternatives.**

| Option | Trade-off | Recommendation | Gate |
|---|---|---|---|
| **Freshness that changes behaviour**: refuse `record_mark` and the `daily` stamp when `prices_stale[tk]` or `source == hardcoded-fallback`; seed `prices_status: INITIAL_BASELINE`; give `spot_ag`/copper/gold their own status; feed `leg_age_days` into the band; hold the directive at VERIFY when a load-bearing input exceeds its budget | More "dark" cycles and a thinner ledger — but a dark store beats a fabricated one | **ADOPT** (stamp guard, seeds, `leg_age_days` = code-behind-tests; the directive hold = propose→confirm) | mixed |
| **Quarantine the contamination**: mark the 8 GROY / 1 AGA seed dates and the seesaw seed rows as `fallback` (or `force_set` from the vendor close, provenance-stamped), and exclude `daily` rows whose price equals a seed from grading | Rewriting history is exactly what the PIT rule forbids — so it must be a *labelled correction*, never a silent overwrite | ADOPT as a labelled repair with a receipt in Memory | propose→confirm (data-store) |
| **One `provenance` record** `{source, as_of, confidence, basis}` validated at every numeric write — config via `propose_param_change`, cache `set()`, thesis `expected` — with `street` and `agent-est` as first-class values that modeled fields refuse | ~11 bare config numbers and the thesis block to migrate | ADOPT | code-behind-tests + propose→confirm (migration) |
| **BNKR feed + ratio-implied AGA mark + spread** as engine facts (one ticker in the worker list; a second stamped source until close) | Cheap; the spread becomes a visible deal-risk read | **ADOPT** | code-behind-tests |
| **Store cadence decision**: auto-commit appends on the engine host at session end vs a separate stores branch; and a written rule that the ledger, price store, Memory, and config are committed together | Auto-commit pollutes code history with a 7 MB ledger; a stores branch keeps code history clean | operator must finally choose — either beats "commit when a human remembers" | operator-decision |
| Catalyst hygiene: wire `catalyst_lifecycle.reconcile` into the heartbeat; require a URL on manual rows; replace hand-set probabilities with base-rate priors stamped `agent-est` + as_of, keeping the operator's number as a labelled override | Loses nothing; gains gradeability | ADOPT (wiring) / PILOT (priors) | code / propose→confirm |
| AGA cash/burn from the filed MD&A (SEDAR+), not a PR; runway re-derived; the waiver decision taken consciously (source a basis + short expiry, or lapse and accept the haircut) | The operator has said the month-24 review reads "drill results and resource math only" — this is survival math, not price, so it is in scope | **ADOPT** — the dependency for TF5's gate honesty | propose→confirm + operator-decision |

**(e) Next steps.** 1) Stamp guard + honest seeds (this week, before the next engine session
writes another constant). 2) Labelled quarantine of the contaminated dates. 3) BNKR feed +
implied mark. 4) Cash/burn refresh → waiver decision. 5) Provenance record + catalyst wiring.
6) Store cadence decision.

---

## TF4 — Research Production & the Agentic Layer

**(a) First principles.** The engine owns the reproducible; agents own the contested; the human
owns mutation — and **the chat is where the three meet**. The conductor's job in conversation is
to detect intent and call the instrument: a rule becomes a `thesis` claim, a conviction becomes
`record_conviction`, a contested thesis convenes the Council, a held name gets a Sentinel
sweep, a forecast is frozen in one line. The corollary this sweep adds: **judgment that never
becomes a typed record is not research the desk can learn from** — and the instruments are not
"idle" because the operator failed to use them; they are idle because the conductor answered in
prose where the manual told it to call a tool. A Council that argues in prose and persists
nothing, a Sentinel that reads rules nobody wrote as rules, and a gate satisfied by whatever
entry carries the right tag are the same failure seen from three sides: text where the engine
needed a fact.

**(b) Hard questions.** Why, after three sweeps, has the Council never written a verdict — and
why does the cockpit not show the operator that the Council strip is a fallback? Why do the
operator's own rules (the month-24 drill-results-only review, sell-half-at-a-double, the TLT
ladder, the storm-ticket sizing doctrine) exist as notes when `thesis_write` claims and the
trigger grammar were built precisely so the Sentinel could evaluate them — and why did the
conductor, hearing each of them in chat, reach for `memory_write(note)` instead? Why does the
forecast ledger work (the conductor calls it reflexively) while `record_conviction` has never
been called by anyone but the engine's seeder? Why can any agent
write a `graduation` row with `memory_write` when the whole point of the disconfirmation gate is
that only the gate writes it — and why did both SNAG graduations pass with the same entry as
verifier and forensic receipt? Why is the entry-sentinel doing arithmetic on self-fetched OHLCV
in a prompt while `price_history.py` sits next to it? Why is the desk's sharpest recent analysis
— the merger timeline forensics, the no-vote threshold — produced by the conductor in chat,
persisted as prose, and consumed by nothing?

**(c) Current practice & strains.** Inventory (DELEGATED, spot-checked): 86 MCP tools (78
pass-throughs + 8 adapters); 15 agent manifests, all with prompt-only output contracts (the only
code-parsed agent outputs are tool arguments: `council_reconcile` claims, `thesis_write`,
`promote_to_eval` inputs, `add_candidate`, `forecast_write`, `predict_fair_value`); the
scheduler's 13 job kinds on a `propose` dial that has never produced a result. What the layer
has actually produced: 437 Memory rows; 5 scout candidates; 4 graduations; 2 promotions; 1
demotion (the bare-SNAG mis-ID, operator-caught); 3 run tags reached a verdict (`pl:techbio-0811`,
`pl:respear-0821`, `cw:CE-holes-0802`); **0 council verdicts; 6 seats never present** (bull,
bear, arbiter as a council, conviction-analyst, data-integrity-auditor, entry-sentinel).

| # | Strain | Anchor | Sev | Confidence |
|---|---|---|---|---|
| 1 | Council has never persisted a verdict; the capture hook, `book_change`'s verdict attach, and the coherence-check verdict path are dead; `engine.py:3010` calls `check_state` without `verdicts` | `core.py:1314` · `coherence_check.py:109-131` · store | High | VERIFIED (store) / DELEGATED (paths) |
| 2 | **Gate types forgeable**: `memory_write` accepts `graduation` / `promotion` / `council_verdict` / `outcome` from the agent channel (no type gate in the tool); `promote_to_eval` only checks a `graduation` row exists | `core.py:1256-1325,2189-2191` · `living_memory.py:53-57` ("written only by the gate" — not enforced) | High | VERIFIED (no type gate) / DELEGATED (probe) |
| 3 | Three-receipt gate satisfied by two entries: both SNAG graduations cite `verifier == forensic` (`20260821-153716-7e767c`; `…-bd766d`); `graduate_candidate` auto-resolve has no distinctness, freshness, or run-tag binding | graduation rows · `core.py:2059-2063` | Med | VERIFIED (rows) / DELEGATED (resolve) |
| 4 | Provenance clamp bypassed by the `source` string: an agent note stamped `source=engine` derives `provenance=engine` (row `20260802-181710-db74b7`) | `living_memory.py:91-101` · `core.py:1296-1305` | High | DELEGATED (probe + row) |
| 5 | Operator/agent split in the forecast ledger rests on a default pointing the wrong way: `confidence_source` defaults to `"operator"` on the agent channel (17/34 rows) | `core.py:2920` | Med | VERIFIED (default) / DELEGATED (count) |
| 6 | The `_ask_argv` lane (every `/council`, `/gauntlet`, in-chat `/pipeline`, `@agent` brief) injects model flags only — no `--disallowedTools`; `add_holding` absent from the block set everywhere | `commodityex_tui.py:6823-6845,6789-6792` | Med | VERIFIED (block set) / DELEGATED (lane) |
| 7 | Division-of-labor muddles: `catalyst_probabilities` (judgment as unlabeled constants), `management_score`/`fraser_index` (agent-asserted into engine fields via `promote_to_eval`, no provenance), council convergence math on **self-declared** `grounded/field/provenance`, the entry-sentinel's Entry Risk Score computed by the LLM from hand-fetched Yahoo JSON with no code and no test, `counterweight`'s ρ asked of the agent while `correlation_check` exists | manifests · `council.py:117-128` · `entry-sentinel.md:41-155` · `core.py:2119-2120` | Med | DELEGATED |
| 8 | The Thesis Check is not wired: no sentinel→council trigger; `cockpit_triggers.py:39-45` only pins/highlights; the Sentinel ran once (07-31); 14 watches unreviewed since | ROADMAP:17-18 · triggers · store | Med | VERIFIED (store) / DELEGATED (triggers) |
| 9 | **The conductor writes notes where the manual says call the instrument**: the AGA thesis freeze (08-18), the win/loss ladder (08-11), the month-24 rule (08-14), the TLT ladder, the storm-ticket doctrine, the sourcing standard — none are `thesis` claims/rules (thesis rows: CEG, MU, HG.CN only); stated convictions never reached `record_conviction`; contested theses (GMX capital-efficiency, the BNKR ratio) never convened `/council`; held names never got a `sentinel_sweep`. The contrast is the forecast ledger, which the conductor does drive (34 rows) | store · `CLAUDE.md` "Scorecard capture" contract | **High** | VERIFIED |
| 10 | `counterweight` manifest instructs a `memory_write(type="counterweight_candidate")` that would raise (type not in `ENTRY_TYPES`); the one live run wrote `scout_candidate` | `counterweight.md:83` · `living_memory.py:38-65` | Low | DELEGATED |
| 11 | Same-model red-team after the agy retirement (the outside foil "folds into @bear"); residue branches left in scheduler/surfaces | `cockpit_widgets.py:699-701` · `cockpit_scheduler.py:108` | Low | DELEGATED |
| 12 | The test gate is red and treated as ambient: 8 membership-pinned failures; CI failing on every push; commit messages normalize it | `tests/*` · `.github/workflows/tests.yml` · GitHub Actions runs 760–784 | High | VERIFIED |

**(d) Alternatives.**

| Option | Trade-off | Recommendation | Gate |
|---|---|---|---|
| **A typed `verdict` record and a `verdict_write` tool** (`{seat, stance, claims[], receipts[], run_tag, ts}`) that validates schema, stamps `source` from the tool not the caller, enforces receipt distinctness + freshness, and becomes the **only** writer of gate types (`memory_write` refuses `graduation/promotion/council_verdict/outcome/conviction`) | Migration of the five tagged note writers; the prose contracts survive as the narrative field of a typed row | **ADOPT** — closes #2, #3, #4, #5 in one seam and makes verdicts gradable | code-behind-tests |
| **Instrument-first chat contract**: extend the manual's "Scorecard capture" table so every judgment class has one instrument and the note is the fallback, never the default — a rule with a metric and threshold ("sell all if assays AND met miss", "TLT ≥ 88 → sell one") → `thesis_claim_set` / `thesis_write` rule; "I'm 70% / this feels cheap" → `record_conviction`; a contested thesis or a book-structure question → `/council`; any held name touched in a session → `sentinel_sweep`; a buy/sell/pass → `record_decision`. Make the typed path the path of least resistance: `memory_write` returns a *redirect hint* when the text pattern-matches a rule/conviction/decision, and the brief shows a per-session instrument scorecard (notes vs typed rows) | Slight friction in the chat; the trigger grammar already fails closed; the hint is advisory, never a refusal | **ADOPT** — this is the whole of finding 4: the fix lives in the conductor's practice and in making the instruments the easy call | operator-decision (contract) + code-behind-tests (hint, scorecard, heartbeat sweep) |
| **Move deterministic explainers into the engine**: conviction-analyst → an `explain_rating` tool over glossary + story card; entry technicals → `price_history.py` RSI/SMA/spike functions + a pure `entry_risk.py` with tests, the agent only narrates | Two seats with zero Memory footprint retire; the 14-signal table becomes config | ADOPT | code-behind-tests |
| **Sentinel-triggered council**, rate-limited (cooldown + max/day) through the scheduler's propose dial, on `engine_break` / JSF trip / posture flip / a corporate action | Token burn and verdict spam — mitigated by the dial; makes the Thesis Check real | PILOT | code + operator-decision (dial) |
| **`agent-est` provenance class** for every number an agent asserts (p̂, ρ_to_spear, management_score, catalyst probabilities, the 0.82 p(close)); modeled fields refuse it (the `basis: street` rule generalized) | Touches `promote_to_eval` meta and the config loader | ADOPT with TF3's provenance record | code-behind-tests |
| Collapse 15 seats → ~5 role-agnostic seats with schema outputs | Loses the readable per-seat culture; gains gradability | DEFER until the verdict record exists — schema first, seat count second | — |
| **Tests assert invariants, not membership**: replace the GMX/URC/24-unit pins with `book_tickers(cfg)`-driven fixtures; make CI a merge gate the desk actually reads | One afternoon; CI green for the right reason | **ADOPT** | code-behind-tests |

**(e) Next steps.** 1) The instrument-first chat contract — the conductor starts calling the
instruments this session, before any code ships. 2) `verdict_write` + gate-type refusal in
`memory_write`. 3) Tests → invariants; CI green. 4) Redirect hint, instrument scorecard,
heartbeat Sentinel sweep. 5) Explainers into the engine. 6) `agent-est` class. 7)
Sentinel-triggered council pilot.

---

## TF5 — The Conviction & Valuation Framework (and its grading loop)

**(a) First principles.** The rating earns trust two ways: inputs real, outputs graded. A
yardstick nobody has graded is a belief; a yardstick graded against fabricated marks is a worse
belief, because it now carries a number. The corollary this sweep adds: **the grade must be
read** — a replay harness that reports floor reliability 0/2,728 into a JSON nobody opens has
not graded anything.

**(b) Hard questions.** Is the 0–10 rating sound? It is a reasoned construction — T (MRI
posture blended with an archetype lean κ and a commodity lean λ), Q (forensic 0.35 / quality
0.40 / management 0.25), V (ρ payoff via `rho_half` 2.0 and φ support over `[0.75, 1.25]`,
0.65/0.35), a per-archetype blend, a conviction lift toward the standout pillar scaled by floor
support, capped by the forensic gate — every constant labeled "reasoned, not backtested — TUNE,"
and **not one has ever been changed through the gate built for it** (`dynamic_config.sqlite`:
0 overrides, 0 pending, 0 audit). Is it targeted? For a spear that is now a fixed-ratio merger
arb, V still reads standalone upside (bull 2.04 vs a consideration bounded by 0.1724 × BNKR) and
T still reads the silver tailwind on a name whose payoff is BNKR-denominated. Is it proven?
Fifteen decisions, four zero-percent artifacts, a learned base rate of n=2 from constants, a
Conviction Book of two engine seeds, and a replay that says the floors did not hold. Which of
the two conservatism scalars (0.85 on the REP floor, 0.88 on intrinsic) is the margin of
safety, and what does φ mean when the floor it measures against was breached by ~20% on the
ballast in July? Why did the posture dial flip DEFENSIVE↔BALANCED↔SPEAR EXPLOIT eight times in
26 minutes on 06-23 (MRI 40.2–43.7) — a master temperature dial with no hysteresis?

**(c) Current practice & strains.** The formula chain is clean and testable
(`asymmetry_rating.py:884-940`: `a_raw = Σ pw·pillar`; `lift = strength · confidence ·
max(0, anchor − a_raw)` shrunk by the ribbon's `rel_width` and zeroed on degraded integrity;
`rating = min(a_raw + lift, gate.cap)`; directive by mode at `:814-870`). The forensic gate
caps only on JSF < 1.5, dilution ≥ 10%/yr without floor support, or runway < 6 months
(`:647-710`), so the waiver's lapse does not cap AGA today (08-25 row: `gate clean, cap 10`).
The loop's parts exist: `plan_flywheel_actions` skips stale marks and short-held stance flips
(`calibration.py:873-935`), `replay.grade_ledger` grades convergence / PIT coverage / floor
reliability against the price store, `forecast_ledger` Brier-scores the operator. What they run
on is the problem.

| # | Strain | Anchor | Sev | Confidence |
|---|---|---|---|---|
| 1 | **Grades on constants**: the 06-23 GROY decision and both GMX outcomes are seed-priced; all 4 outcomes `+0.0%`; the learned base rate (n=2, expectancy 0.0, containment 1.0) rolls forward into underwriting; GROY's open decision matures ~09-21 on the seed | store `decision`/`outcome`/`calibration_snapshot` rows · finding 2 | **High** | VERIFIED |
| 2 | **The replay's honest read is unread**: offline run this session — 30 d: n 2,733, PIT coverage 0.055 vs 0.80 claimed, floor tested 2,728 / held 0; 60 d: coverage 0.877, floor held 0/2,728; 90 d: n 0. Both names' stamped floors were breached inside the window (GROY ~20% in July vs its book-value floor; AGA on 07-29). No surface, brief, or Memory row carries any of it | `replay.py:72-150,168-256` · run output | **High** | VERIFIED |
| 3 | n inflated ~100× by the stamp storm: 3,437 `material_change` rows (98%) from 26 run-days and 2–4 names; GROY 2,394 of the 30-d grades; the fingerprint includes 4-dp ribbon quantiles and the live tick, so every tick is a "material change"; hysteresis (07-02 item F) unshipped | `valuation_ledger.py:44-47,322-327` · ledger | High | VERIFIED |
| 4 | No tunable has ever passed through propose→confirm; every rating constant is at its hand-set default (κ 0.66, λ per archetype, `support_band`, `rho_half`, `conviction_lift 0.6`, `q_weights`, the two conservatism scalars, `catalyst_probabilities`, `management_score`) | `data/dynamic_config.sqlite` · `v5_config.json` | Med | VERIFIED |
| 5 | The spear's V and T read a standalone explorer (bull 2.037, ρ 5.45, T on the silver lean) while the payoff is ratio-bounded until close; the ladder carries no consideration leg, no vote leg | ledger 08-25 · TF2 #1 | High | VERIFIED |
| 6 | Posture has no hysteresis: stance is decided by the `net_tilt` string with MRI thresholds only as fallback (`regime_posture.py:60-72`); 16 `regime_snapshot` rows are all 06-23/24 flips; posture read `spear_exploit` at MRI 35.7–39.8 through August | `regime_posture.py` · store | Med | VERIFIED |
| 7 | Ribbon centre ≠ point (TF1 #3): the spear's `intrinsic` is the scenario base while the P10/P50/P90 is the triangulation distribution — the coverage test grades the point against a band built around a different number | `engine.py:3348-3352` · `asymmetry_rating.py:741-750` | Med | VERIFIED |
| 8 | Two conservatism scalars (`rep_floor_params.conservatism_scalar` 0.85 on the floor; top-level 0.88 on intrinsic), both undated; `survival_exempt_archetypes` config ≠ code | `engines/valuation.py:82,141,280` · `asymmetry_rating.py:323,670` | Low-Med | VERIFIED |
| 9 | The forecast book is the only calibration instrument in daily use (34 rows, supersession discipline, 2 resolved) — and it grades macro/merger/tape calls, not the rating; `confidence_source` defaults to `operator` on the agent channel | store · `core.py:2920` | Med | VERIFIED |
| 10 | Conviction Book = 2 engine seeds (0.5, "discovery_to_mine ≈ 0.5") for AGA; the operator's stated conviction ("I'm 82% p(close)", the 0.75 GROY call view) went to the forecast ledger, never to `record_conviction` | store | Low-Med | VERIFIED |
| 11 | Fair-value ratchet, goodwill materiality, T-pillar tape leak, `update_beta` posterior store — carried unchanged from 07-08 | `holdco_nav.py` · `base_rates.py:301-314` · `engine.py:1175-1214` | PERSISTS | DELEGATED (07-08 anchors) |

**(d) Alternatives.**

| Option | Trade-off | Recommendation | Gate |
|---|---|---|---|
| **Grade what is gradable, on a clean substrate**: after TF3's stamp guard and the labelled quarantine, re-run `grade_ledger` **de-duplicated to one snapshot per name-day** (the daily row, or the last real-priced row of the day), publish convergence / coverage / floor reliability per name with small-n CIs and `data_limited`, and put the floor-reliability line on the rail and in the brief | Honest n is ~26 per name — small, but real; the storm rows must not count | **ADOPT** | code-behind-tests (dedup + publish) · read-only (first grades) |
| **Void-and-refreeze the seed-priced decisions** (GROY 06-23; GMX rows already closed as artifacts get a `suspect` supersession), re-seed the learned base rate from a clean set | Rewrites nothing; supersedes with a receipt | ADOPT before ~09-21 | propose→confirm (data-store) |
| **Shrink the yardstick to two gradable primitives** — floor-hold probability and upside-realization ratio (realized / projected bull) — as the headline of every grade; keep T/Q as context and the 0–10 as a display composite | The 0–10 stays for the rail; the *grade* stops pretending to score a composite it cannot falsify | ADOPT (grading side only) | read-only → propose→confirm (if the band moves) |
| **Distributional verdict**: render and grade the P10/P50/P90 (with the point forced to the P50 of the same distribution — fixes #7) instead of a point; widen the sigma map only when the PIT test says so, through `/confirm` | A one-model rule (scenario base *is* the distribution's P50) may move the spear's intrinsic; must be pinned | ADOPT | code-behind-tests + propose→confirm |
| **Merger-arb state for AGA (TF2 i)** with V read on the ratio-implied consideration and the vote/dissent optionality as the convex leg; T's commodity lean re-pointed at BNKR's zinc/lead/silver mix until close | Same trade-offs as TF2 (i) | ADOPT | code + propose→confirm |
| **Posture hysteresis**: a stance changes only after N consecutive cycles or a Δ-MRI beyond a band; stamp posture events with cause | Slower dial | ADOPT | propose→confirm |
| Hysteresis on `material_change` (min-Δ on rating/band/directive/legs at display precision; ribbon quantiles excluded from the fingerprint) | Thinner ledger | **ADOPT** (07-02 item F, third audit) | propose→confirm (threshold) + code |
| Retune κ/λ/bands/lift | — | **REJECT** until a clean first grade exists — the 07-08 deferral stands, and is now evidence-backed: the loop has never produced a number the constants could be tuned against | — |

**(e) Next steps.** 1) Clean substrate (TF3 Phase 1) → dedup → first honest grades, published.
2) Void/refreeze the seed decisions before ~09-21. 3) Floor-hold + upside-realization as the
grade headline; floor-reliability on the rail. 4) One-model ribbon. 5) Posture + stamp
hysteresis. 6) Merger-arb state (with TF2).

---

## Cross-Cutting Matrix

| Tension | Upstream | Downstream | Who co-signs |
|---|---|---|---|
| **The book moved; the model didn't** | TF2: the July config, the four-name residue, the standalone spear | TF1 renders a THESIS INTACT on a merger arb and a ◇EVAL on a held name; TF5 grades a payoff that no longer exists; TF4's tests pin the old book and CI is red | TF2 owns the instrument state and the residue purge; the operator decides the slot table and the cap |
| **Seeds in the track record** | TF3: cold-start seeds badged LIVE + a stamp path with no guard + immutable-after-roll | TF5's decisions, outcomes, learned prior, replay n, and the dashboard's "live closes" all carry constants | TF3 guard + quarantine; TF5 void/refreeze; TF1 `~stale price` glyph |
| **The letter-not-invariant pattern, instance five** | Fixes scoped to the finding's wording (three seeds fixed, the fourth not; last-good fixed, the stamp path not; deny-list by prefix, the two new writers not) | Every invariant leaks one layer over | Fix authors grep for siblings and name the pattern in the close — now a standing rule, not a suggestion |
| **The chat writes notes where it should play the instruments** | TF4: the conductor answers in prose; rules as notes, convictions unpriced, verdicts never typed, gate types forgeable | TF5 cannot grade what was never typed; TF1's Council strip renders a fallback forever; the Sentinel evaluates rules nobody wrote as rules | TF4 `verdict_write` + the instrument-first chat contract in CLAUDE.md; the conductor owns the practice, the engine makes it the easy call |
| **Gated items have no clock, and defaults decide** | 07-08 items A–G: the waiver lapsed by default; the store cadence never chosen; hysteresis and the enum carried four audits | The spear's survival gate now runs on a PR proxy; the ledger is 98% storm; the repo lost its history | The operator; the cockpit should show gated-item age and "decided-by-default" the way it shows staleness |
| **A red test gate nobody reads** | TF4: membership pinned in tests; CI failing on every push | The suite no longer discriminates a regression from a book change — the next real regression will be "known pre-existing" too | TF4 rewrite to invariants; TF2 supplies `book_tickers(cfg)` fixtures |

---

## Sequenced Program

Ordering: **stop writing constants before the next engine session; then the clocks (GROY
~09-21, the vote ~11-15, the assays); then the book's identity; then grade; then the carried
refactors.**

### Phase 0 — Before the engine runs again
| # | Step | Source | Gate |
|---|---|---|---|
| 0.1 | `record_mark` + `daily` stamp refuse stale/fallback marks; `prices_status` seeds `INITIAL_BASELINE`; `spot_ag`/copper/gold carry their own status; seesaw rows refuse seeds | TF3 #1-3 | code-behind-tests |
| 0.2 | Labelled quarantine of the 8 GROY / 1 AGA seed dates and the 7 seesaw rows (supersession receipts in Memory; `force_set` only from a vendor close, provenance-stamped) | TF3↔TF5 | propose→confirm (data-store) |
| 0.3 | BNKR into the worker list; ratio-implied AGA mark + spread published on `/state` | TF3 #6 · TF2 #1 | code-behind-tests |
| 0.4 | Void/refreeze the seed-priced GROY decision; supersede the GMX artifact outcomes as `suspect`; re-seed the learned base rate from the clean set | TF5 #1 | propose→confirm (data-store) |
| 0.5 | Store cadence rule (ledger + price store + Memory + config committed together at session end; or a stores branch) | TF3 #4 | operator-decision |

### Phase 1 — The clocks
| # | Step | Source | Gate |
|---|---|---|---|
| 1.1 | AGA cash/burn from the filed MD&A; runway re-derived; the waiver decided consciously (basis + short expiry, or lapse + accepted haircut), recorded to Memory | TF3 #5 · TF5 | propose→confirm + operator-decision |
| 1.2 | The spear's merger-arb instrument state (ratio ladder, vote calendar row, probability blend suspended, sizing on the instrument held); identity sweep scheduled for close | TF2 (i) · TF5 #5 | code-behind-tests + propose→confirm |
| 1.3 | Resolve the overdue TLT-fill forecast; the 09-04 / 09-11 forecasts straight-to-source; the brief surfaces due items | TF1 #8 | read-only / data-store |
| 1.4 | CEG `target_weight 0.12` + the credit-sentinel claim as a thesis rule | TF2 (iv) | propose→confirm |

### Phase 2 — The book's identity
| # | Step | Source | Gate |
|---|---|---|---|
| 2.1 | Residue purge: default barbell, hardcoded lists, GMX phantom node, offline fallback, slot table, docs; `archetype_barbell_weights` renormalized; `ai-upside-ballast`/`conventional` in the taxonomy | TF2 (ii) | code-behind-tests |
| 2.2 | Tests assert invariants (`book_tickers(cfg)`), not membership; CI green and read | TF4 #12 | code-behind-tests |
| 2.3 | Slot-aware single-position cap (or the ballast sleeve's cap raised) — the operator decides the risk | TF2 #2 | propose→confirm |
| 2.4 | WS reconcile (export → drift report at session start); a resource-add tool; SNAG.V's status decided (held-and-rated vs eval) | TF2 (iii), #3 | code-behind-tests + operator-decision |

### Phase 3 — Grade honestly
| # | Step | Source | Gate |
|---|---|---|---|
| 3.1 | `material_change` hysteresis (ribbon quantiles out of the fingerprint; min-Δ at display precision); posture hysteresis | TF5 #3, #6 | propose→confirm + code |
| 3.2 | `grade_ledger` de-duplicated per name-day; first honest grades with CIs, published on the rail and in the brief; floor-hold + upside-realization as the headline | TF5 (d) | code-behind-tests → read-only |
| 3.3 | One-model ribbon (point = P50); `leg_age_days` fed; staleness that changes the number | TF5 #7 · TF3 #8 | code-behind-tests + propose→confirm |
| 3.4 | Provenance record everywhere; `agent-est` class; catalyst probabilities as stamped priors; `catalyst_lifecycle.reconcile` on the heartbeat | TF3 (d) · TF4 (d) | code + propose→confirm |

### Phase 4 — The agentic layer produces facts
| # | Step | Source | Gate |
|---|---|---|---|
| 4.1 | `verdict_write` typed record; `memory_write` refuses gate types; receipt distinctness + freshness; `forecast_write` source honest by construction | TF4 #2-5 | code-behind-tests |
| 4.2 | Mutation registry in the registration loop; explicit MCP `source`; `add_holding`/`garage_set_ladder` gated; `_ask_argv` hardened | TF1 #4-6 · TF4 #6 | code-behind-tests + operator-decision |
| 4.3 | Instrument-first chat contract in CLAUDE.md (rule → claim, conviction → `record_conviction`, contested → `/council`, held → `sentinel_sweep`, call → `record_decision`); `memory_write` redirect hint + brief instrument scorecard; Sentinel sweep on the heartbeat; Council on GROY and on the AGA/BNKR instrument — the first verdict rows | TF4 (d) | operator-decision (contract) + code-behind-tests |
| 4.4 | Explainers into the engine (rating explain, entry technicals); sentinel-triggered council pilot | TF4 (d) | code-behind-tests / pilot |

### Phase 5 — The carried refactors (fourth audit)
| # | Step | Source | Gate |
|---|---|---|---|
| 5.1 | Directive enum + one compose; legacy vocabulary retired; `signal_state` per name; uncertainty-first face | TF1 (d) | code-behind-tests |
| 5.2 | `_redistribute` consolidation; thesis-review clock; `survival_exempt_archetypes` decision + assertion; FRED label; `set_nav` routing | TF2/TF3/TF1 | code + propose→confirm |
| 5.3 | Retune of κ/λ/bands/lift **only** against Phase 3 grades | TF5 | propose→confirm (never before 3.2) |

---

## Preserved dissent & could-not-verify

**Dissent, preserved:**
- **"The engine isn't the desk anymore, and that may be right."** The operator's best work this
  quarter was conversational — forecasts frozen in one line, the arb math, the agreement read —
  and the forecast ledger graded it. A counter-position to this sweep is that the engine should
  shrink to a price/provenance/grading substrate and let the chat be the research surface. This
  sweep does not adopt it, because the substrate is exactly what is currently broken; but if the
  operator prefers that shape, Phases 0 and 3 are the whole program and Phase 5 can be dropped.
- **The stamp-guard will darken the ledger.** A name with no fresh quote gets no daily row. That
  is the intended cost; the alternative — a row with a constant in it — is the failure this
  sweep documents. The dissent is that a *flagged* row (price stamped `fallback`, excluded from
  grading) preserves the run-day record; either is acceptable if the flag actually excludes.
- **The four-name residue was not carelessness.** The book changed twice in six weeks under
  live conditions; `remove_holding` did most of what it promised. The finding is that the purge
  must be *complete* (defaults, lists, tests, docs) or the residue re-enters as a member on a
  typo.
- **Letting the waiver lapse was a defensible branch** in July; the indefensible part is that it
  happened by default and the desk did not know. With the filed cash it may still be the
  honest branch.
- **Rewriting contaminated store dates is a PIT violation in form.** The sweep recommends a
  labelled supersession with a receipt precisely so the correction is itself an auditable event.
- **A slot-aware cap loosens a guardrail.** The 0.20 single-position cap was written for a
  four-name book; the alternative to loosening it for the ballast sleeve is to accept the
  permanent TRIM signal as a feature. The operator decides; the engine should at least say why
  the signal fires.

**Could not verify (blockers stated):**
- **Live behaviour**: no engine run — the JSF sub-scores AGA carries today (config runway fails;
  a feed-derived burn may pass), the rail's actual ribbon quality per name, the TRIM priority's
  rendering, the posture at today's MRI.
- **The operator's host**: whether newer Memory/ledger/price-store rows exist locally; the
  `.cache/` last-good state; why GROY's quote failed 08-17→08-25 (Yahoo symbol, network policy,
  or the engine only cold-starting once per day).
- **History before 2026-08-28**: the repo root is `4e8bad7`; the 07-08 SHAs do not resolve here;
  whether the prior history survives in another repository (the MCP config points at
  `/Users/joeymason/Macro/`) is unknown.
- **DELEGATED rows**: reported by scans with quoted anchors; the lead re-verified every headline
  finding, every money-relevant mechanic (the seed chain, the gate, the sizer cap, the replay,
  the tests, the CI), and spot-checked the delegated claims that feed the program (corporate
  action readers, `add_holding` gating, the forecast default, the seesaw rows, the memory type
  gate, the SNAG receipts) — but did not re-read every supporting anchor line-by-line.
- **Test suite**: run this session under `unittest` (2,002 tests: 3 failures, 8 errors — 3 of
  the errors were environment-only `pytest` imports; those three files pass under pytest, 39/39)
  and the 8 real failures are all book-membership pins. The TUI async-timer flake noted on
  07-08 did not reproduce.

**Session hygiene note:** this session changed nothing in the tree beyond adding this document.
No config, book, tunable, store, manifest, or test was modified; the pure grading modules were
run read-only against the committed stores; the test suite was executed in a scratch environment
with the repo's requirements installed. Every recommendation touching config, the book, a store,
or a tunable is marked propose→confirm, operator-decision, or data-store and is NOT done. When a
claim here conflicts with the tree, the tree wins — re-grep, re-verify, report the correction.
