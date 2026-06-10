# CommodityEx Codebase Audit — June 9, 2026

Full-codebase scan per the Fable 5 onboarding mandate: Task A (bugs / violations / debt /
performance), Task B (prioritized improvements), Task C (feature proposals). Every finding cites
file + line. Severity: **CRITICAL** (wrong money-relevant output or crash in a live path),
**HIGH** (invariant erosion, silent data corruption, money-relevant fragility), **MED/LOW** (debt).

Method: direct line-by-line audit of the Forge core (living_memory, trigger_grammar, sentinel,
council, calibration, thesis_ledger, dynamic_config, regime_posture, mcp_server) plus three
delegated deep scans (engine/archetypes/asymmetry, TUI/dashboard, ingestion/catalyst/data layer).
Delegated findings marked ⚠ were independently re-verified where they headline; one was **refuted**
(see §A1.8) and is reported corrected.

---

## A0 — Invariant compliance scorecard (the seven hard lines)

| # | Invariant | Status |
|---|---|---|
| 1 | Engine is the single source of math truth | **VIOLATED** by `dashboard.py` (re-derives conviction + directives locally, §A2.1); TUI is largely compliant |
| 2 | 60% ceiling permanent, never tunable | **HOLDS in code** (`engine.py:1945-1953` clamps, flex never exceeds; NOT in the dynamic-config ALLOWLIST) — but the value lives in editable `v5_config.json` (§A2.3) and `PHASE7_CONVICTION_MODE.md` row 1 still instructs REMOVING the cap (§A3.1, stale spec) |
| 3 | living_memory.jsonl append-only, supersede-never-overwrite | **HOLDS** — no mutation path exists; but two read-side bugs leak wrong views (§A1.6, §A1.7) |
| 4 | No eval()/exec() in trigger path | **HOLDS** — `trigger_grammar.py` is a closed-whitelist tokenizer → recursive-descent parser → hand-walked AST; `eval` at line 273 is a method name on the safe evaluator. Confirmed no `eval(`/`exec(`/`compile(` anywhere in the trigger path |
| 5 | Config changes proposal-gated | **SOFT** — `propose → confirm` exists and works (`dynamic_config.py:184-209`), but MCP `set_param` (`mcp_server/core.py:631`) lets any agent self-supply `confirm=true` and the audit row mislabels the writer as `source="cockpit"` (§A2.4) |
| 6 | Catalyst dates grounded straight-to-source | **PARTIAL** — EDGAR adapter can emit fabricated headline events with no URL (§A1.5); `catalyst_calendar.write()` accepts an empty `source_url`; an RSS aggregator runs as a trust-2 secondary source against design decision #3 (mitigated by the supersede hierarchy, §A2.5) |
| 7 | Grounded or silent | **VIOLATED at the data layer** — stale cache served with no staleness flag on FMP budget exhaustion and on 429/503 (§A1.3, §A1.4); `dashboard.py` renders hardcoded May-2026 prices (§A3.4) |

Also: **IBKR and Kensho are not wired at all** — zero references in the codebase (IBKR: none;
Kensho: docs/citations only). The stack diagram in the onboarding overstates the data layer.
**RESOLVED (2026-06-10):** the only IBKR vestige — `CommodityExMonitor.__init__`'s
`host/port=4002/client_id` scaffolding — was confirmed dead (assigned, never read; no IB import,
no connect, no API calls) and removed. The operator does not trade on IBKR; market data is Yahoo +
FMP + yfinance only, and that is now the intended, documented design — not a gap. The remaining
M0 item is decoupled: positions/weights are still config-sourced (`engine.py` PortfolioSizer),
which is fine for an assessment terminal but means the book isn't reconciled against a live
brokerage feed. `FORGE_BUILD_SPEC.md` is still **not checked into the repo**.

---

## A1 — CRITICAL & HIGH bugs

### A1.1 CRITICAL — Council forensic-gate guardrail fails at the most severe cap (falsy-zero)
`council.py:141` — `severe_gate = gate_applied and float(gate.get("cap", 10.0) or 10.0) <= 5.0`.
A JSF gate cap of `0.0` (a full block, the most severe state possible) is falsy, so `or 10.0`
substitutes 10.0 and `severe_gate` is **False**: the Bull is NOT capped at 0.25 exactly when the
engine screams loudest, and `engine_break` (line 153) loses its first leg too — so the
no-narrative-veto guardrail can also keep a broken spear alive. One-line fix:
`cap = gate.get("cap"); severe_gate = gate_applied and cap is not None and float(cap) <= 5.0`.

### A1.2 CRITICAL — Sentinel sweep crashes on a non-numeric claim metric (TypeError)
`sentinel.py:189-196` — `thesis_integrity` checks `mv is None` but not numeric-ness; a string
metric value (e.g. a status word that drifted into the context) passes the None check, then
`cmp(_num(mv), thr)` calls the comparator lambda with `None < float` → uncaught `TypeError`,
killing the whole `sweep_name` for that ticker. The module's contract is "evaluation never
raises". Fix: `mvn = _num(mv)` and treat `mvn is None` as `"unknown"` (fail closed), mirroring
trigger_grammar's `_cmp`.

### A1.3 CRITICAL — No retry/backoff on 429/503; stale cache served as fresh ⚠
`ingestion_pipeline.py:270-295` — `_http_get_text/_http_get_json` swallow HTTP errors (bare
`except Exception`), return `None`, and the caller falls back to cache with `cached: bool(entry)`
but **no staleness flag or age**. A rate-limited FMP day silently becomes "yesterday's data
presented as today's". Same class at `fmp_client.py:96-98`: when the daily budget is exhausted it
returns stale `entry["data"]` with `budget_exhausted: True` — which `market_data.snapshot()` never
checks. Violates invariant 7 directly. Fix: exponential backoff (2s/4s/8s) on 429/503, and a
uniform `{"stale": bool, "age_s": float}` envelope on every cache-served response, surfaced in the
cockpit header.

### A1.4 CRITICAL — Blocking sync I/O in the Textual event loop ⚠
`commodityex_tui.py:95-111` — `_get()`/`_post()` use synchronous `urllib.request.urlopen` and are
called directly from action handlers and timer callbacks: `_fetch_fundamentals` (≈4076),
`_do_save`/`_do_confirm`/`_do_reject` (≈6750-6772), and the what-if debounce path (≈6600). With
the engine slow or down (timeout window), the whole TUI freezes mid-keystroke. `refresh_data` is
correctly a thread worker; these are not. Fix: route every `_get`/`_post` call site through
`@work(thread=True)` or an async httpx client; `_clip_copy`'s `subprocess.Popen` (≈3608) needs a
timeout.

### A1.5 CRITICAL — Catalyst events fabricated without source URLs ⚠
`ingestion_pipeline.py:985-992` — the EDGAR adapter synthesizes a headline
(`"{form} filing — {ticker} ({date})"`) when the filing description is empty, with **no URL
attached**, and `write_catalyst_feed` (≈1061-1083) strips `_source`/`_trust` metadata on write.
`catalyst_calendar.py:91-129` accepts `source_url=""` without complaint, and `macro_windows()`
(≈323) passes `source: "company_guidance"` (a type, not a URL). Invariant 6 says a catalyst
without a straight-to-source URL must not enter the record. Fix: make a non-empty https URL a
write-time validation for `kind != macro` (mirror `thesis_ledger.validate_thesis`'s
reject-at-save discipline), and preserve `_source`/`_trust` through the feed write.

### A1.6 HIGH — Living Memory warm-cache incoherence under multi-process writes
`living_memory.py:124-132` + `147-170`. The design promise is multi-writer safety (cockpit + MCP
agents + engine all append). After a write, the writer refreshes `self._mtime` from disk; if
another process appended in the same window, the file mtime now *includes* the other entry but the
warm `self._cache` does not — and `all()` (line 154) sees `mtime == self._mtime` and serves the
incomplete cache indefinitely (until the next disk mtime change). Result: a Council verdict
written by the MCP process can be invisible to the cockpit's queries. Fix: after a write, don't
trust own-cache + fresh mtime — invalidate (`self._cache = None`) instead of appending, or compare
file *size* as well as mtime.

### A1.7 HIGH — Two append-only read-side leaks
1. **Torn lines silently dropped**: O_APPEND interleaving is only atomic up to ~PIPE_BUF (4KB);
   a long Council verdict or thesis entry written concurrently from two processes can interleave,
   and the reader (`living_memory.py:163-166`) *silently skips* unparseable lines — append-only
   storage with quiet data loss. Fix: single-writer lockfile (`fcntl.flock`) around the append, or
   length-check + fsync; at minimum count and surface skipped lines in `stats()`.
2. **Retraction tombstones leak into live queries**: `retract()` (lines 279-286) supersedes the
   original (correctly hidden) but the tombstone itself — text `"(retracted)"`,
   `meta.retracted=True` — is a *live* entry that `query()` (180-213) does not filter. Every
   consumer sees "(retracted)" noise rows. Fix: `query()` should drop `meta.retracted` entries
   unless `include_superseded=True`.

### A1.8 HIGH — JSF/Sloan share-series ordering is assumed, never enforced (CORRECTED finding)
`engine.py:927-928, 1122, 3738-3746`. A delegated scan claimed the dilution formula's sign is
backwards; **that is wrong** — `iloc[0]` is the *most recent* period in yfinance statement frames,
so `(shares_t0 − shares_t1) / shares_t1` is the correct (current−prior)/prior, and line 1123
clamps buyback negatives to 0. The real defect is that newest-first ordering is an undocumented
yfinance convention the code never verifies: the frames are not sorted by column date before
`iloc[0]`/`iloc[1]` are taken, and the same assumption underpins the Sloan accrual deltas
(≈950-966). If the provider ever returns oldest-first, dilution velocity reads ~0 (clamped) and
accruals flip sign — silently. Fix: sort statement columns descending by date once, in
`fetch_forensic_metrics`, and assert `t0_date > t1_date`.

### A1.9 HIGH — Engine shared-state race ⚠
`engine.py:2108` creates `state_lock`, but it is held only by the background `_macro_worker` /
`_comps_worker`; the main eval loop (≈4611+) and request handlers read/write `terminal_state`
unlocked, and four background tasks are fired via `asyncio.create_task` (≈2440-2443) untracked —
a crashed worker leaves the loop serving stale data with no health signal. Fix: one lock (or an
immutable-snapshot swap pattern: build the new state dict fully, then a single reference
assignment) + task supervision that surfaces worker death into `/state.status`.

### A1.10 HIGH — Fail-open defaults in two money-relevant gates
The Forge discipline is fail-*closed* (trigger grammar, liquidity runway). Two gates do the
opposite:
1. `sentinel.py:291` — `dilution_ok = (dil_vel is None) or (dil_vel < sieve_qoq)`: missing
   dilution data is scored **clean**, credits the financing-window's full `W_DILUTION` weight, and
   makes `death_spiral` (line 160) structurally unable to fire for any name lacking share-count
   history. The names most likely to lack clean data are precisely the death-spiral candidates.
   Fix: a `None` sieve should drop the term from the renormalized blend (like the other legs) and
   disqualify the death-spiral *clean* verdict, noting "dilution data missing" in provenance.
2. `council.py:282-290` — `estimate_friction(days_90=None)` treats missing liquidity runway as
   `0.0` days → friction = re-entry only (2%): the *least*-known incumbent gets the *cheapest*
   exit assumption, biasing `swap_verdict` toward SWAP. Fix: missing `days_90` → assume
   `slip_max` (fail-closed), or return REJECT-for-missing-data like the missing-ρ path
   (`council.py:324-326`).

### A1.11 HIGH — catalyst_engine date handling ⚠
`catalyst_engine.py:206-209` — naive date parsing (Z stripped) works today by accident and breaks
the moment any tz-aware datetime enters; `≈261-272` — `float(cfg.get(...))` raises `TypeError` on
a None/string config value (no `_num` guard) in the squashing path. Fix: normalize all catalyst
timestamps to UTC-aware at the parse boundary; `_num()`-guard config reads.

**RESOLVED (2026-06-10):** added `_cfg_num(cfg, key, default)` (logs + degrades a malformed/None/inf
value to the default, never a `TypeError`) and routed every `float(cfg.get(...))`/`int(cfg.get(...))`
read in `summarize_catalysts` through it; the `impact_weights`/`v_impact_weights` blocks are now
`or {}`-guarded. `_parse_date` parses to an aware-UTC datetime then takes `.date()` (mirrors
`catalyst_calendar._parse`), so a tz-offset timestamp can no longer shift `age_days`. Pinned by
`TestConfigHardeningAndDates` in `tests/test_catalyst_engine.py`.

### A1.12 HIGH — Scheduler/job-store race ⚠
`cockpit_scheduler.py:116-129` — `load_jobs()`/`save_jobs()` are unsynchronized
read-modify-write on one JSON file; two concurrent callers lose edits, and a lost "ran" mark
re-fires jobs. Fix: `fcntl.flock` around load-modify-save, or move jobs into the existing
`dynamic_config.sqlite` (which already has the lock discipline).

---

## A2 — Architectural violations

### A2.1 CRITICAL — dashboard.py re-derives engine math ⚠
`dashboard.py:75-115` rebuilds conviction/asymmetry from raw state, and `751-757` recomputes
ACCUMULATE/TRIM/HOLD directives locally instead of rendering the engine's `directive` field; line
93 hardcodes `is_spear = (tkr == "AGA.V")`. If engine logic moves, the dashboard silently
disagrees with the cockpit — two screens, two answers. Fix: consume `conviction_mode` verbatim;
delete the local derivations. (The Textual TUI is largely compliant — its `data/*.json` writes are
UI-session state, not engine state.)

**RESOLVED (2026-06-10):** the re-derivation is gone. `dashboard.py` no longer imports the rating
math; `_conviction_from_state` is deleted and `render_conviction_mode` projects
`state["conviction_mode"]` verbatim (absent → an honest "needs the live feed", never a rebuilt
rating). The Barbell-Execution ORDER column renders the engine's per-name `directive` (presentation-
only colour map keyed off the directive text); the local ACCUMULATE/TRIM/HOLD computation is removed.
Spear identity reads from config (`thesis_slot == "silver-spear"`), and the hardcoded May-2026
price/share fallbacks (`0.72`/`0.71`/`4.81`/… and `5000`/`161`/…) now render "—" when the feed is
missing (the blended edge fails closed to ~0 leverage, not a fabricated number). Pure helpers
extracted to `dashboard_projections.py`; pinned by `tests/test_dashboard_projections.py`.

### A2.2 — set_param gate is advisory, and the audit trail mislabels agents
`mcp_server/core.py:631-641` — `set_param(confirm=True)` is callable by any MCP client; the
"needs_confirmation" bounce is a client-side convention an agent satisfies by re-calling with the
flag, and the engine write is posted with `source="cockpit"` regardless of who called — so the
audit log (the "seed of the decision journal", `dynamic_config.py` docstring) cannot distinguish a
human from an agent. Fix: pass the real caller identity through to `source`, and have the engine
reject `set_param` writes whose source is not the cockpit/human channel (agents get `propose`
only). The ALLOWLIST + range validation in `dynamic_config.py` is otherwise well built.

**RESOLVED (2026-06-10):** the engine-side half landed. `POST /config/param` now rejects any
`source` not in `{"cockpit", "human"}` (e.g. the honestly-labelled `"mcp:set_param"`) and writes
nothing — agents must use `/config/propose` → `/config/confirm`. The `/config/confirm` route
(which calls `dconfig.confirm()` → `set_param` internally) is untouched. Pinned by
`TestConfigParamProposalGate` in `tests/test_audit_fixes.py`. (The MCP-label honesty half was
resolved earlier.)

### A2.3 — The 60% ceiling should be a code constant, not a config default
`engine.py:1843, 4474` read `v5_guardrails.max_spear_position_pct` from `v5_config.json` with a
0.60 fallback. It is correctly absent from the dynamic-config ALLOWLIST, but a hand-edit of the
JSON (or a bad merge) raises it with no guard. Invariant 2 says permanent: enforce
`min(config_value, 0.60)` in code with a comment marking it structural, so config can only ever
*tighten* it.

### A2.4 — Stale spec contradicts the standing invariant
`PHASE7_CONVICTION_MODE.md` (row 1 of the decision table) still instructs: *"Hard spear ceiling
(60%) … REMOVE as a cap; REPURPOSE as a passive readout."* The operator's standing decision is the
opposite (ceiling permanent). The code follows the invariant; the spec is wrong. Supersede that row
with an explicit note — the next engineer told "if code contradicts a spec, the code is wrong"
would *remove the ceiling*.

### A2.5 — RSS aggregator as catalyst source vs design decision #3
`ingestion_pipeline.py:779-844` — `RssNewsAdapter` aggregates "company + mining-news RSS" at trust
2. Design decision #3 is straight-to-SEDAR+/EDGAR/GlobeNewswire, no RSS aggregators. The
supersede-by-trust hierarchy (≈1039-1185) mitigates for authoritative types, and per-company
GlobeNewswire/Newsfile PR feeds are within the letter of the rule — but generic mining-news feeds
plus substring-alias attribution (≈823-844; `GENERIC_TERMS` blocks "gold"/"silver" but not
"mining") can attribute a sector story to a held name. Fix: restrict the adapter's feed list to
issuer-scoped PR feeds; demote anything else to display-only (never a catalyst record).

**RESOLVED (2026-06-10):** each feed now carries an `issuer_scoped` flag (default **False** =
fail-closed). `RssNewsAdapter` tags events from non-issuer feeds `display_only: True`, and both
`_collapse_by_source_precedence` and `write_catalyst_feed` exclude `display_only` events from the
authoritative catalyst record (they remain available to news-display surfaces). In `v5_config.json`
only the per-company Newsfile PR feed is marked `issuer_scoped: true`; the generic mining-news /
industry / Yahoo per-symbol feeds stay display-only. `_trust` semantics unchanged. Pinned in
`tests/test_ingestion_pipeline.py` (`TestCatalystSources`).

---

## A3 — Technical debt (selected, money-adjacent first)

1. **Hardcoded book everywhere**: barbell weights dict `engine.py:1935-1940`; tickers across
   `commodityex_tui.py` (≈565-613) and `ingestion_pipeline.py:131`; spear identity in
   `dashboard.py:93,755,762`. One source: `v5_config.json → portfolio_metadata` (which already
   carries `thesis_slot`). Any rotation today requires a multi-file code edit. **(M)**
2. **`dashboard.py:490-493, 740-747` hardcoded prices/shares** (`p_aga = 0.72` …): renders stale
   marks as live. Should consume `market_data.snapshot()`/engine state or show "—". **(S)**
3. **Tooltip mandate unmet** ⚠: only ~14 of ~28+ Conviction-Mode metrics have `?` explain
   handlers (`commodityex_tui.py:2012-2028`); JSF, runway, Sloan, ES95, CBA, spear-cap, etc.
   missing; `dashboard.py:128-157` keeps a *second*, drifting tooltip dictionary. Single
   glossary source = engine `get_glossary`. **(M)**
4. **Three duplicated book renderers** in the TUI (`_render_book` ≈1960, `_render_book_detail`
   ≈2135, `_render_profile` ≈2926) extracting the same fields; plus the 6,851-line monolith
   class. Split screens into modules; one projection helper. **(L, refactor)**
5. **Three parallel HTTP/cache stacks** (`market_data.py`, `fmp_client.py`,
   `ingestion_pipeline.py`) each with its own TTL semantics and no shared staleness contract.
   One client with retry/backoff/staleness envelope fixes §A1.3 everywhere at once. **(M)**
6. **trigger_grammar depth-counter leak**: `_Parser._not` (lines 134-137) increments `depth` and
   never decrements, so depth is cumulative across the expression — ~64 NOTs anywhere in one rule
   spuriously fail to parse. Cosmetic today, but it's the security-critical file; fix to true
   recursion depth. Also `BOOL_METRICS` (line 48) is dead. **(S)**
   **RESOLVED (2026-06-10):** `_not` decrements `depth` after the recursive call (true nesting depth,
   restored on unwind) so flat sequential NOTs no longer stack; the 64 bound still guards genuine
   nesting. `BOOL_METRICS` deleted. Pinned by `DepthBoundTests` in `tests/test_trigger_grammar.py`
   (70 sequential NOTs parse; 70 nested parens still raise `GrammarError`).
7. **`research_cache.set()` overwrites silently** (research_cache.py:48-58) — last-writer-wins
   with no as-of/provenance comparison, in the store that feeds JSF gap inputs. **(S)**
   **RESOLVED (2026-06-10):** `set()` is now as-of-aware — an older-dated write is refused (returns
   the kept entry + `reason`, nothing written), equal/newer writes stash the displaced entry one
   level deep under `previous`, and `force=True` overrides (still stashing). Pinned in
   `tests/test_data_layer.py` (`ResearchCacheTests`); `seed_research_cache.py` re-runs clean.
8. **dynamic_config `confirm()` TOCTOU** (dynamic_config.py:200-209): pending-row read outside
   the lock; two concurrent confirms double-apply (benign value, duplicate audit). **(LOW)**
   **RESOLVED (2026-06-10):** `confirm()` now CLAIMS the pending row (read + conditional
   `status='applied'` flip) in ONE locked transaction before applying it (apply runs outside the
   lock — `set_param` takes the same non-reentrant lock), so exactly one caller wins. Pinned by
   `test_double_confirm_is_rejected` in `tests/test_dynamic_config.py`.
9. **Sentinel alert copy uses module constant, not the configured value**
   (`sentinel.py:336` prints `DEATHSPIRAL_RUNWAY_MONTHS` instead of `ds_runway`). **(LOW)**
10. **living_memory `ts` parameter allows backdating** any entry (line 111) — fine for imports,
    but nothing marks backdated entries; add `meta._backdated` when `ts` is caller-supplied, to
    keep the track record honest. **(LOW)**
    **RESOLVED (2026-06-10):** `write()` stamps `meta["_backdated"] = True` whenever the caller
    supplies `ts` (the seed importer does; `reaffirm`/`supersede` do not, so they stay unmarked).
    Pinned by `test_caller_supplied_ts_is_marked_backdated` / `test_supersede_stays_unmarked` in
    `tests/test_living_memory.py`.

## A4 — Performance

- The blocking-I/O items in §A1.4 are the only user-visible ones.
- `LivingMemory._superseded_ids()` rescans all entries per query — fine at 4-name scale; revisit
  only if the journal grows past ~50k lines.
- TUI polls full `/state` every 3s; targeted `/decisions` is already throttled (1-in-4 polls).
  Acceptable. No missing prompt-caching found on Kensho (not wired) or FMP (engine-cached,
  budget-capped — correct design, wrong staleness signaling per §A1.3).

---

## B — Prioritized improvements (what / why / where / effort / milestone)

| # | What | Why (principle) | Where | Effort | Milestone |
|---|---|---|---|---|---|
| 1 | Fix falsy-zero severe-gate check | Signal coherence — forensic gate must cap the Bull | `council.py:141,153` | S | M6 |
| 2 | Fail-closed `thesis_integrity` compare | Sentinel must never crash a sweep | `sentinel.py:189-196` | S | M3 |
| 3 | Retry/backoff + uniform staleness envelope | Grounded-or-silent | `ingestion_pipeline.py:270-295`, `fmp_client.py:96-110`, `market_data.py:66-102` | M | M0/data |
| 4 | Worker-thread every TUI `_get`/`_post` call site | Cockpit must stay responsive when the engine doesn't | `commodityex_tui.py:95-111` + call sites | M | cockpit |
| 5 | Require source URL at catalyst write; keep `_source/_trust` through the feed | Catalyst grounding (invariant 6) | `catalyst_calendar.py:91-129`, `ingestion_pipeline.py:985-992,1061-1083` | S | M1 |
| 6 | Memory cache invalidation + flock on append + filter retracted | Append-only must also be *read-correct* | `living_memory.py:124-170,180-213` | S | M2 |
| 7 | Fail-closed dilution sieve + friction | The gates exist to catch the names with the worst data | `sentinel.py:291`, `council.py:282-290` | S | M3/M6 |
| 8 | Delete dashboard.py local math; render engine fields | Engine is the single source of truth | `dashboard.py:75-115,751-757` | S | cockpit |
| 9 | Sort statement frames by date before `iloc` deltas | JSF integrity under provider drift | `engine.py:920-970,3738-3746` | S | engine |
| 10 | Code-side `min(cfg, 0.60)` ceiling clamp + fix PHASE7 doc row | 60% ceiling is structural | `engine.py:1843`, `PHASE7_CONVICTION_MODE.md` | S | engine |
| 11 | Engine state lock / snapshot-swap + supervised workers | Correct numbers under concurrency | `engine.py:2108,2440-2443,4611+` | M | M0 |
| 12 | `set_param` source integrity + agent rejection engine-side | Proposal gate is a *hard* line, not etiquette | `mcp_server/core.py:631-641`, engine `/config/param` | S | governance |
| 13 | Single config source for book composition (kill hardcoded weights/tickers) | Rotation without code edits; slot discipline | `engine.py:1935-1940`, TUI, dashboard, ingestion | M | engine |
| 14 | Complete `?` tooltip coverage from one glossary | Conviction-Mode clarity (design decision #4) | `commodityex_tui.py:2012-2028`, `dashboard.py:128-157` | M | cockpit |
| 15 | flock the scheduler job store | No double-fired jobs | `cockpit_scheduler.py:116-129` | S | cockpit |
| 16 | Check `FORGE_BUILD_SPEC.md` into the repo | The north star must be in-tree and versioned | repo root | S | M0 |

Items 1, 2, 5, 6, 7, 9, 10 are each ≤ ~20 lines and individually testable — they are the first PR.

## C — Feature proposals

Honest status first: **two of the five "known missing" features already exist in the Forge layer
and are missing only their cockpit surface and data wiring.** Building them again would be waste.

1. **Financing-Window Reflexivity Lens — EXISTS, surface it.** `sentinel.py:122-172`
   (`financing_window`) already computes premium-to-last-placement, REP-floor headroom, 52-wk
   percentile, dilution sieve, window open/closing, and the death-spiral flag. Gaps: (a)
   `last_placement_price` provenance is frequently missing (sweep provenance shows it), so the
   directest reflexivity leg silently drops out of the blend — wire it from research_cache with a
   required source URL; (b) not shown in Conviction Mode — add a `WINDOW open/closing` chip per
   junior. Effort S-M. Milestone: M3 surface.
2. **Narrative Integrity Score (NIS%) — EXISTS, surface it.** `sentinel.py:176-207`
   (`thesis_integrity`) is exactly NIS% (holds/total over load-bearing claims, with a 60% floor
   flag). Gaps: claims must actually be seeded per name (`thesis_write`), the §A1.2 crash fixed,
   and the score given a Conviction-Mode column. Effort S. Milestone: M3 surface.
3. **Dilution-Adjusted Asymmetry Ceiling — NET-NEW, highest-value engine change.** Confirmed:
   `asymmetry_rating.py:485` computes ρ = U / max(Df, δ) on the *current* share count; upside legs
   never haircut for the raise a pre-revenue junior must do. Implementation: engine-side projected
   diluted count = shares + (months-to-catalyst burn ÷ assumed raise price at a configurable
   discount-to-market, e.g. 15%), recompute U on diluted NAV/share, publish `rho_diluted` next to
   ρ (never silently replace — the delta IS the signal). Uses only fields the engine already has
   (burn, runway, price). Effort M. Milestone: net-new M8 candidate; unblocks honest spear sizing.
4. **Spot-Breathing NAV for royalty ballast — NET-NEW.** Engine-side: Asset-Light Yield leg
   recomputed on spot deltas between full evals (cheap: NAV sensitivity ∂NAV/∂spot is already
   implicit in the leg math; publish `nav_spot_breathing` + spot-stamp in `/state`). Surfaces in
   Conviction Mode for GROY/URC.TO so a $5 silver move is visible without a re-run. Effort M.
   Milestone: M8 candidate. Invariant 1 respected: lives in the ENGINE, never the TUI.
5. **Regime-Conditional Target Book — NET-NEW.** The engine already has RIV per archetype and
   `regime_posture.compute()`; the missing piece is the cross product: target archetype mix given
   current MRI/posture vs the actual mix, with a drift number. Keep it a *readout*, not an
   optimizer — no MPT, no rebalancing engine; it answers "is the book shaped for this regime?"
   Effort M. Milestone: M7-adjacent (feeds calibration's regime-stamped outcomes).

Assessed from the "potentially high-value" list:
- **Pre-mortem base-rate injection into Council** — mostly exists (`calibration.candidate_anchor`,
  `brief_prior`); the gap is injecting the archetype prior + spear-backstop into `reconcile()`'s
  facts so the Arbiter *sees* the outside view. Effort S. Do it with M6. **Recommended.**
- **SEDAR+ semantic filing diff** — net-new and on-thesis (catalyst precision for AGA.V's
  NI 43-101 chain), but blocked on a reliable SEDAR+ fetch layer first (`ingestion_pipeline.py:
  1006` admits SEDAR+ breadth is the gap). Sequence after B#3/B#5. Effort L.
- **IBKR real-time book reconciliation** — cannot start: IBKR is not wired at all (zero
  references). Flagged as the M0 blocker it is. Until then the terminal sizes against assumed
  weights, which is the single largest gap between the terminal and reality. **Highest-priority
  net-new data work.**
- **Macro Lens (Tier 0-4 triage)** — real value but the largest scope with the least leverage on
  the current four names; defer behind everything above.

---

*Scan coverage: engine.py, archetypes.py, asymmetry_rating.py, commodityex_tui.py, dashboard.py,
ingestion_pipeline.py, catalyst_engine.py, catalyst_calendar.py, fmp_client.py, market_data.py,
living_memory.py, trigger_grammar.py, sentinel.py, council.py, calibration.py, thesis_ledger.py,
dynamic_config.py, regime_posture.py, base_rates.py (via calibration), research_cache.py,
cockpit_scheduler.py, mcp_server/{server,core}.py, v5_config.json, data/*.json, and the spec set
(CLAUDE.md, ENGINE_DESIGN.md, COCKPIT.md, PHASE7/8, STATE_FIELDS.md).*
