# Standing Reassessment — Phase 0 Findings (2026-06-26)

*Phase 0 of the sequenced program in `docs/REASSESSMENT_2026-06-26.md`: the four read-only
audits (free, no gate; engine offline). Nothing in the engine/config/book was changed. The only
repo change this phase is one new **test** (`tests/test_directive_council_sync.py`) — a sync guard
that touches no config and adds a regression check, not behaviour. Every value below was read from
current code; file:line are exact unless flagged "could not verify".*

---

## Verdict

The audits **confirm the reassessment and, in two places, make it worse than written.** 0.1 found the
fabrication surface is broader than TF3 flagged — most dangerously, **cold-start macro inputs
(`real_yield=1.0`, `cftc_net_longs=35000`) are badged `status="LIVE"`**, not degraded, and the MRI
returns a confident **`45.0` on any exception** (`engine.py:719`). 0.3 found **three of four held names
show inertia** — GMX.TO has *no catalyst record of any kind on disk*, URC.TO has *no engine decision
row at all* and is live-impaired by the Sweetwater acquisition, and **no held name has ever been
Council'd** in the durable record. 0.2 is the one piece of good news made durable: the directive↔Council
string contract is **in sync today** (all directives resolve to real priors), and there is now a test
that fails the instant a rename breaks it. 0.4 settled the LED panel: **DORMANT-BUT-WIRED** — inert in
current operation, the engine has zero dependency on it, but retirement needs an operator's word.

The through-line for Phase 1: **the inputs that will corrupt the grade are real and now enumerated**,
and **the book's inertia is no longer a suspicion — it is documented per name.**

---

## 0.2 — Directive↔Council sync guard (TF1) — DONE, with an artifact

**Finding: the contract is in sync today; the brittleness is real but latent.** `asymmetry_rating._directive`
(`asymmetry_rating.py:778-805`) emits 10 distinct human-readable directive strings. `council._directive_prior`
(`council.py:104-109`) keyword-matches that prose to a bull-share prior via the ordered `_DIRECTIVE_PRIOR`
list (`council.py:36-52`); an **unrecognized** directive falls silently to `0.50` (neutral) with no error
or log. Traced all 10 by hand and in code: **every one currently matches a real key** — none falls to the
silent fallback — and each maps to a *distinct* prior. So the contract is healthy *now*; the danger is pure
drift (rename "BELOW FLOOR" → "SUB-FLOOR" on either side and every spear Council verdict quietly goes neutral).

**One latent ambiguity, documented:** `"FAIR VALUE — HOLD"` legitimately matches the `FAIR VALUE` key
whose prior is `0.50` — the *same value* as the unknown-directive fallback. A recognized FAIR-VALUE
directive and an unrecognized typo are therefore indistinguishable by prior alone. Pinned in the test so
any future change is conscious; a later fix may want to nudge the `FAIR VALUE` key off `0.50`.

**Artifact shipped:** `tests/test_directive_council_sync.py` (new; no source/config touched). It reads the
directive literals **live from `_directive`'s source** (so a rename is picked up automatically and
re-checked), and pins four guarantees:
1. extraction is not vacuous (guards a refactor that hides the literals);
2. **every** directive resolves to a recognized prior, never the silent `0.50` (the core guard — fails the
   moment either side drifts);
3. a snapshot of the full directive→prior mapping (catches a value/ordering drift that changes a prior
   without removing coverage);
4. the `FAIR VALUE — HOLD` == `0.50` collision is documented and pinned.

**Result:** `Ran 4 tests … OK` (and the existing `tests/test_council` suite still passes, 17/17). This is
the regression guard the charter's roadmap item 0.2 / 3.2 asks for; it makes the directive→`(code, text)`
refactor (Phase 3.2) safe to attempt, because the guard will catch any mapping it breaks.

---

## 0.1 — Fabrication-Surface Map (TF3)

*Read-only audit of `engine.py`, `v5_config.json`, `data/research_cache.json`, and the five support
modules. The desk's stated discipline is "grounded-or-silent / fail-closed" — a missing input must widen
uncertainty or return `None`, never pass as a confident point estimate. The table marks where that holds
and where it breaks.*

### The surface

| Input | file:line | Default/constant | Stands in for | Second-sourced? | Fails OPEN (silent) / CLOSED (degrades/None)? | Risk if wrong |
|---|---|---|---|---|---|---|
| MRI `DXY` | engine.py:617 | `100` | Live DXY level | N | **OPEN** — `.get('DXY',{}).get('value',100)`, no status demote | Mis-scores liquidity/FX block (30% of MRI); 100 reads as neutral dollar |
| MRI `TED` | engine.py:618 | `0.3` | TED/SOFR spread | N | **OPEN** | Funding-stress term mis-set silently |
| MRI `VIX` | engine.py:619 | `18` | Live VIX | N | **OPEN** | Vol block (20% of MRI) defaults to calm |
| MRI `Spreads` | engine.py:620 | `3.5` | HY OAS (BAMLH0A0HYM2) | N | **OPEN** | Credit-stress term defaults to benign |
| MRI `10Y` | engine.py:621 | `4.2` | 10Y nominal | N | **OPEN** | Curve block mis-set |
| MRI `30Y` | engine.py:622 | `4.4` | 30Y nominal | N | **OPEN** | Curve slope mis-set |
| MRI `CFTC_Silver_Net_Longs` | engine.py:623 | `35000.0` | COT net spec longs | N (no free COT history, cmt 676-681) | **OPEN** | Spec-positioning block (15%) anchored to a guess |
| MRI exception return | engine.py:719 | `45.0` (+ empty blocks) | Whole MRI index | N | **OPEN** — any calc exception returns a confident 45.0 | **Entire regime read fabricated on a silent exception** |
| MRI silver static bound | engine.py:672 | `norm(spot_ag, 50, 100)` | Live percentile of silver | partial (dynamic if ≥252 obs) | degrades to static (labeled `bounds_basis`) | Saturates 0/100 outside band — the pin-at-100 bug it patches |
| MRI cu/au ratio guard | engine.py:670 | `0.00136` (if gold≤0) | copper/gold ratio | N | **OPEN** | Commodity block mis-set if gold missing |
| Real-yield series **contradiction** | v5_config.json:1034 declares `REAINTRATREARAT10Y`; engine.py:462,597 fetch `DFII10` | — | Config vs engine disagree on canonical real-yield series | N | OPEN (engine ignores config) | Two real-yield definitions in one system; config documents fiction |
| Real-yield L3 proxy | engine.py:490,503 | `^TNX − 2.0` (clamp ≥0) | DFII10 real yield | N | CLOSED-ish — `status="DEGRADED_STALE"` (498) | Crude "minus 2%" breakeven substitutes for real series |
| Real-yield cache cold default | engine.py:506-507 | `1.8` | Real yield | N | OPEN at L4 (inside DEGRADED branch) | Last-resort 1.8% if no cache + no proxy |
| **Cold-start `real_yield`** | engine.py:2453-2454 | `1.0` **status "LIVE"** | Real yield pre-first-cycle | N | **OPEN — badged LIVE** | Fabricated real yield reads as *live* until first worker cycle |
| **Cold-start `cftc_net_longs`** | engine.py:2462-2463 | `35000.0` **status "LIVE"** | COT positioning | N | **OPEN — badged LIVE** | Confident, live-badged guess at startup |
| Cold-start `usd_to_cad` | engine.py:2451 | `1.38` | USD/CAD FX | N | OPEN (cold-start) | All USD→CAD conversions wrong if cycle never runs |
| `usd_to_cad` runtime fallback | engine.py:3097,3288,4112,4156,4190 | `1.38` | Live FX | N | OPEN | NAV/comps FX silently uses 1.38 |
| DXY momentum cold/fallback | engine.py:527,2448 | `mom=0.0, dxy=99.0` | DXY 10d momentum | N | CLOSED — `DEGRADED_STALE` (526) | Momentum reads flat |
| Copper / Gold parse fallback | engine.py:2990,3001 | `copper=4.2, gold=2350.0` | Live HG=F / GC=F | N | **OPEN** — GSR/MRI built from it | GSR + commodity block on stale constants; 2350 gold far below 2026 tape |
| `_get_fallback_price` table | engine.py:2871-2877 | AGA.V 0.71 / GROY 3.22 / GMX.TO 2.04 / URC.TO 4.82 / SI=F 74.8 / CL=F 89.5 / DXY 99.0 / VIX3M 18.5 | Live last price | N | **CLOSED** — flagged `hardcoded-fallback, stale:True`, demotes to DEGRADED (2967-2987) | If freshness layer is bypassed, book marked at stale constants |
| `spot_ag` resolution default | engine.py:5629 | `74.8` | Live silver | N | partial — inherits `prices_status` (5632) | Spear valuation core input |
| GSR zero-guard | engine.py:5639,3495 | `80.0` | gold/spot_ag | N | OPEN | Relative-value read defaults |
| `silver_vol` fallback | engine.py:6028 | `0.30` (`_realized_vol(...) or 0.30`) | Realized 60d silver vol | N | **OPEN** — no status demote | Option-premium convexity term on the spear fabricated |
| `silver_vol` signature defaults | engine.py:1449,1576,1756 | `0.25`/`0.30` | Silver vol | N | OPEN if called bare | Vol term default if caller passes nothing |
| Peer EV/oz weighted fallback | engine.py:902,915 | `2.50` | Live peer EV/oz comps | N | partial — on empty weights / fetch-fail | Spear intrinsic anchored to a constant if comps fail |
| Peer EV/oz cold-start | engine.py:725,2428 | `2.5` | Peer comps | N | OPEN (cold-start, intentional) | First eval cycle uses 2.5 |
| `avg_disc_cost` fallback | engine.py:901,917 | `0.48` | Avg discovery cost/oz | N | partial | Discovery-cost term defaults |
| `runway` zero-burn guard | engine.py:1198 | `99.0` | cash/burn months | N | OPEN | Zero/missing burn reads as infinite runway (JSF passes) |
| `curr_burn` proxy | engine.py:1217 | `monthly_burn*3.0` (if cfo missing) | Quarterly CFO | N | OPEN | Accrual/burn test uses modeled burn not actual CFO |
| `monthly_burn_rate` | v5_config.json:26 | `2750000` CAD | AGA.V cash burn | **Y — full provenance** (asof:28, source:29, ccy:27) | n/a (sourced) | The model for sourced inputs; low risk |
| `management_score` priors | v5_config.json:387,404,422,439 | AGA 0.62 / GROY 0.60 / GMX 0.55 / URC 0.58 | Analyst mgmt-quality → Q pillar | **N — no source/asof/audit field** | **OPEN** — bare floats feed the rating | Subjective Q input, zero audit trail, un-second-sourced & un-dated |
| Uranium spot stamp | research_cache.json:453-454 | `86.1` USD/lb, `as_of 2026-06-04`, "no free live feed; UxC/Numerco ref" | Live U3O8 spot (URC NAV mark) | **N — single analyst stamp** | CLOSED — nav_mark ages it, ribbon widens >45d (nav_mark.py:74-77,108-109) | URC NAV rides one un-corroborated stamp; staleness visible, value single-sourced |
| `ballast_multiples` floors | v5_config.json:326-328 | URC 1.15 / GROY 1.15 / GMX 1.2 | Book-value floor multiples | **N — no source field** | OPEN | Hand-stamped floor multiples, no provenance |
| `ballast_valuation.spot_ref` | v5_config.json:336,344,352 | `74.8` on **all three** (URC=U, GROY=Au, GMX=diversified) | Per-commodity reference spot | N — **wrong commodity** (74.8 is silver) | OPEN (cmt 331: "legacy anchors", real floors from research_cache) | Silver price stamped as the gold/U/diversified anchor — residue of the all-silver bug |
| `holdco_pipeline_assets` NPVs | research_cache.json:160-186 | Mont Sorcier 69M / Battery Hill 26M / Bell Mtn 5.5M | GMX royalty-stream value | **N — confidence:"low", "MODELED… not operator-published"** | partial (confidence flag) | GMX floor leg leans on modeled NPVs no operator published |
| `live_portfolio_value` floor | engine.py:5648 | `cfg.target_capital` (5360.0) | Computed equity if <1000 | N | OPEN | Book value floored to a constant if calc collapses |
| Forensic metrics on fetch-fail | engine.py:1135,1151-1152 | `None` | yfinance statements | n/a | **CLOSED — None, no cache → None (correct)** | The discipline done right; JSF can't pass on fabricated forensics |

**Support modules — clean (grounded-or-silent by construction; no input substitution):**
- `market_data.py` — explicit "NO hardcoded values; absence recorded as 'unavailable'" (5-6,144,175); stale marks never overwrite a good one (231-234). Clean.
- `commodity_regime.py` — `None` on unknown commodity / bad input (98-103,139-144); no fabricated tailwind. *Latent:* signature defaults `real_yield=2.0` (46,53), `gsr=80.0` (53), `uranium_term=0.0` (72) only fire if called bare — engine passes live values, but the defaults exist.
- `nav_mark.py` — two-tier spot, `None` when neither usable (66,77,96-109); undated stamp is stale-by-definition (74); NRV floor prevents negative uplift (112). Exemplary fail-closed.
- `inflation_regime.py` — `available=False`/`None` on missing legs (79-80,107-109); the constants (30-32) are tunable **thresholds**, not input substitutes.
- `rates_monitor.py` — every term drops to `None`/next-best proxy on missing input (160-173, `wsum>0` guard 287); constants (41-56) are tunable bands, not fabricated inputs.

### The 5 most dangerous fabrications (load-bearing × fails-open × un-sourced)

1. **MRI exception → confident `45.0`** (`engine.py:719`) — any uncaught error in the regime calc returns a precise mid-regime MRI with empty decomposition, badged like a real read; the whole posture/temperature dial can be silently fabricated.
2. **Cold-start `real_yield=1.0` and `cftc_net_longs=35000` badged `status="LIVE"`** (`engine.py:2453-2454,2462-2463`) — fabricated macro inputs that read as *live*, not degraded, until the first worker cycle; a direct fail-open violation of the stated discipline.
3. **MRI per-sub-input silent defaults** (`engine.py:617-623`) — six block inputs substitute "benign" constants with no status demotion, so a partially-missing macro frame produces a falsely calm MRI.
4. **`management_score` priors with zero provenance** (`v5_config.json:387/404/422/439`) — bare analyst floats (0.55-0.62) feeding the Q pillar, no source/asof/audit field; `monthly_burn_rate` (line 26) shows exactly the provenance shape that's missing here.
5. **Copper/gold parse fallback `4.2 / 2350.0`** (`engine.py:2990,3001`) substituted in-line — silently feeds the MRI commodity block and the GSR; 2350 gold is far below live tape, skewing the regime read and every gold-relative signal with no flag.

*(Runner-up: the uranium spot stamp `86.1`, `research_cache.json:453` — single analyst stamp, "no free live feed," drives URC's entire NAV; fails closed on staleness but the value is un-corroborable.)*

### Could-not-verify
- **Ingestion-side use of `REAINTRATREARAT10Y`** (`v5_config.json:1034`): confirmed the engine's live path fetches `DFII10` (`engine.py:462,597`), but did not read the ingestion provider code that consumes `series_map`, so cannot confirm whether the config series is used anywhere or is dead — only that engine and config disagree.
- **Per-name forensic-block freshness in `research_cache.json`**: there is **no `forensic`/`sloan`/`accrual` block** in `research_cache.json` (grep: no matches); forensic metrics are fetched live from yfinance per cycle (`engine.py:983-1152`). So "each name's forensic block freshness" does not exist as a cached artifact — forensic inputs are live-or-None (correct fail-closed). A brief assumption that did not hold against the code.

---

## 0.3 — De-facto Thesis-Age Audit (TF2)

*READ-ONLY, engine OFFLINE. Established by hand from the durable on-disk record as of 2026-06-26.
Sources: `data/living_memory.jsonl` (58 lines), `data/catalysts.json`, `data/catalyst_calendar.jsonl`,
`data/catalysts.csv`, `v5_config.json`.*

### The instrument gap (confirmed first — it frames everything)

`v5_config.json → portfolio_metadata` carries **NO `entry_date`, NO `last_review`, NO `review_cadence`,
and NO thesis-age field of any kind.** Confirmed two ways: a regex sweep for
`entry_date|last_review|review_cadence|thesis_age` returned no matches, and a direct read of all four
blocks (`v5_config.json:373-442`) shows only `type, jurisdiction, fraser_index, stage, archetype,
subarchetype, sector_tags, management_score, thesis_slot, thesis_slot_desc`. There is no per-name
timestamp the book can read to know how long a name has sat unchallenged. **This audit is the manual
stand-in for that missing inertia clock.** Management scores on disk: AGA.V 0.62 (`:387`), GROY 0.60
(`:404`), GMX.TO 0.55 (`:422`), URC.TO 0.58 (`:439`).

### Per-name table

| Ticker | Slot | Last Council verdict | Last decision/note | Last PAST catalyst | Next UPCOMING catalyst | Days since last *genuine contest* | Inertia? |
|---|---|---|---|---|---|---|---|
| **AGA.V** | silver-spear | **None found** | `decision` THESIS INTACT — MONITOR @0.72, **2026-06-23** (`jsonl:22`) | Red Mountain 10,000 m drill commenced 2026-06-12 (newsfile, `catalysts.json:21-30`) | **Yes** — 4 grounded windows (Red Mtn assays 07-15→12-31; Hughes 06-17→09-30; Mogollon; Hughes met) (`catalyst_calendar.jsonl:1-4`) | ~3 days (engine) | **N** — freshly marked, dense live + forward catalysts |
| **GROY** | gold-royalty-ballast | **None found** | `decision` QUALITY — CORE HOLD @4.444 [floor 4.446], **2026-06-23** (`jsonl:20`) | 6-K filing 2026-06-15 (edgar, `catalysts.json:8-17`); prior 6-Ks back to 03-20 | **None on the calendar** (AGA.V only) | ~3 days (mark only) | **PARTIAL** — engine-marked, never Council'd/anti-scouted; only catalysts are routine 6-Ks, none forward |
| **GMX.TO** | project-generator-holdco | **None found** | `decision` QUALITY — CORE HOLD @2.04 [floor 0.71, φ 0.348], **2026-06-23** (`jsonl:21`) | **None in the feed** — zero rows in any catalyst file | **None** | ~3 days (mark only) | **YES** — sole touch is the automated engine mark; no catalyst of any kind, past or future, anywhere on disk |
| **URC.TO** | electrification-royalty | **None found** | No ticker-keyed decision/note; contested only indirectly via anti-scout on U-UN.TO (`jsonl:32`, 2026-06-23) flagging URC's **Sweetwater** acquisition as a SEPARATE-FINDING DEGRADE; gauntlet thread (`jsonl:36`) escalates | **None in the feed** | **None on calendar**; live event in Memory: Sweetwater vote July-2026, close Q3-2026 (issuer PR 2026-04-16) | ~3 days, and touched **adversely** | **YES (live-impaired, not stale)** — no engine decision row at all; only contact says the incumbent's own slot-fit "may be materially impaired" |

**Living-memory entry counts** (across 58 lines): AGA.V **2**, GROY **1**, GMX.TO **1**, URC.TO **3** (two
scheduler no-output stubs + the anti-scout aside). No `council`/`council_verdict`/`synthesis`/`verifier`/
`forensic`/`scenario`/`anti_scout` entry is keyed to **any** held name — those types on disk all attach to
*candidates* (ARS.CN, OGN.V, U-UN.TO, DEFN.V…), never to a holding.

### Per-name verdict
- **AGA.V — FRESHLY UNDERWRITTEN.** Fresh engine decision + a live grounded forward-catalyst slate. No dead-catalyst risk. (Caveat: never Council'd either — "the engine watches it" is doing all the contesting.)
- **GROY — PARTIAL INERTIA (marked, not contested).** Fresh monthly engine mark, but never Council'd/anti-scouted/verified, and its only catalysts are recurring 6-Ks with nothing forward. *Re-marked* by automation, not *re-contested*.
- **GMX.TO — INERTIA.** The single touch in the entire durable record is the automated engine row. **No catalyst entry anywhere on disk.** Clearest "squatting on an absent catalyst" signal in the book.
- **URC.TO — INERTIA, LIVE-IMPAIRED (most urgent).** No engine decision row, no own-name analysis; the only substantive contact is an anti-scout aside warning Sweetwater (soda ash ≠ electrification; ~41% dilution; US$625M debt; vote July-2026) may break URC's slot fit. A thesis actively decaying with a dated Q3 trigger, never formally contested. `jsonl:36` explicitly recommends a `/screen electrification-royalty` + Council on URC *before the Q3 close* — that has not happened.

### Could-not-verify
- **No Council verdict exists for ANY held name** — the column is empty for all four.
- **GMX.TO and URC.TO have no catalyst record of any kind** — their catalyst columns are *unverifiable from disk*, not merely empty.
- `catalysts.csv` is header-only (the manual-override file, intentionally blank).
- `catalyst_calendar.jsonl` covers **AGA.V only**.
- URC.TO's "decision age" is borrowed from the anti-scout aside (`jsonl:32`), not a real underwrite.
- The two oldest URC entries (`jsonl:6`) are scheduler "no output — check `CEX_JOB_CMD` permission flags" failures — a scheduled contest was *attempted* ~20 days ago and **produced nothing**; whether it re-ran is unverifiable. *(Cross-ref TF4 #3.3: the headless-runner hardening.)*

---

## 0.4 — LED Matrix Panel: Active or Vestigial? (TF4)

The `matrix/` subsystem renders engine `/state` to a **physical ESP32-S3 WiFi LED panel** (firmware
v2.0.8) over HTTP — mDNS host `esp32s3-cb15f8.home.local` (`matrix/device.py:27`, `matrix/config.py:48`).
The host daemon polls the engine, builds frames with PIL, encodes `anim.bin`, POSTs to the device
(`matrix/orchestrator.py:1-16`, `matrix/device.py:36-100`). Complete, well-engineered, fully unit-tested —
the question is whether it is *driven* in normal operation.

### Evidence ledger
**FOR active use:**
- Fully wired into the launcher: `start_matrix()` (`cockpit.sh:185-194`) is called on every cockpit boot (`cockpit.sh:213`); daemon `python -m matrix --host "$CEX_MATRIX_HOST"` (`cockpit.sh:191`).
- Per-holding logo assets generated & committed 2026-06-24 — `data/matrix_logos/{AGA.V,GROY,GMX.TO,URC.TO}.png` (commit `bb2a83f`); only used by the detail-card render path (`matrix/orchestrator.py:212-213`).
- A curated, operator-authored watch-bench: `data/matrix_bench.json` (3 names, detailed `_doc`).
- pid/bench files tracked in git.

**AGAINST (vestigial/dormant):**
- **The launch is OPT-IN and the gate is OFF.** `start_matrix()` returns immediately unless `CEX_MATRIX_HOST` is set: `[ -n "${CEX_MATRIX_HOST:-}" ] || return 0` (`cockpit.sh:186`); unset in this environment. Self-documented "OPT-IN background daemon" (`cockpit.sh:183,46`, `matrix/__main__.py:12`).
- **The committed PID is stale.** `data/matrix.pid` = `8344`; not running; no matrix process.
- **The runtime log never materialized.** `data/matrix.log` is gitignored and absent — the daemon produced no captured output in this checkout.
- **Zero integration outside its own subsystem.** Full-repo grep for `matrix` outside `matrix/`+`tests/` returns only the *mathematical* sense (correlation/covariance). `book_change.py:13` explicitly says it does **not** touch the matrix. The engine has **no awareness of and no dependency on** the panel; data flow is strictly one-way and best-effort (`matrix/orchestrator.py:124-128`).
- Runtime deps not even installed (`import PIL`, `import yfinance` fail here).
- Tests are extensive and **entirely device-free** (all I/O injected/mocked, `tests/test_matrix_orchestrator.py:1-5,40-51`; `tests/test_matrix_device.py:1,8`). They prove the *code* works; they say nothing about a panel being plugged in.

### Verdict: **DORMANT-BUT-WIRED.**
Deciding fact: the daemon launch is gated behind `CEX_MATRIX_HOST` (unset, `cockpit.sh:186`) and the
committed pid points at a dead process — so a normal boot here never starts it, and the engine has zero
dependency on it. The code is complete and recently touched (curated bench, fresh logos), so it was real,
but it is **inert in current operation**. Whether it runs at all depends on an operator-set env var pointing
at a physical panel on the operator's home network — unobservable from here.

### Recommendation
**Read-only audit → operator decision to retire; no removal without sign-off.** Do not retire on this
evidence alone: confirm with the operator whether they still boot with `CEX_MATRIX_HOST` set against a live
panel. If "no", the subsystem + assets are safe to decommission; if "yes", it is genuinely ACTIVE and stays.
Either way, retirement is a config/code change behind the operator gate, not a read-only step.

---

## What Phase 0 changes about the roadmap

- **Phase 1 is confirmed and slightly enlarged.** Add to the input-honesty work (Phase 2): the **cold-start `status="LIVE"` badging** (`engine.py:2453-2463`) is arguably worse than the MRI silent-default (it lies about freshness, not just value) and should ship in the same fail-closed pass. The **wrong-commodity `spot_ref: 74.8`** on all three ballast names (`v5_config.json:336/344/352`) is a config-hygiene fix (propose→confirm) even though it's self-labeled legacy.
- **The inertia case (Phase 6.1) is now evidenced, not asserted.** GMX.TO (no catalyst anywhere) and URC.TO (live-impaired by Sweetwater, never contested) are the two names the thesis-review clock would have caught. **URC.TO is time-sensitive** — the Sweetwater vote is July-2026; a `/screen electrification-royalty` + Council on URC before the Q3 close is an operator call worth surfacing now, ahead of the clock being built.
- **0.2's guard de-risks Phase 3.2** (directive → `(code, display_text)`): the refactor now has a test that fails if it breaks the Council mapping.
- **0.4 keeps the LED panel a live question**, not a retirement: it needs one operator answer (`CEX_MATRIX_HOST` — set against a real panel, or dark?).

*Nothing above touched the engine, config, or book. The only repo change is the new test. All
load-bearing fixes remain behind propose→confirm / operator decision per the master roadmap in
`docs/REASSESSMENT_2026-06-26.md`.*
