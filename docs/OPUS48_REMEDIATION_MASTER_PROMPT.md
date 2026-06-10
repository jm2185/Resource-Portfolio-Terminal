# CommodityEx — Opus 4.8 Remediation Master Prompt
*Generated June 10, 2026 · Anchors verified against `main`-lineage HEAD `2758bfa`. Paste this entire
document as the first message of a fresh Claude Opus 4.8 session on the CommodityEx repo.*

---

## PASTE THIS ENTIRE BLOCK INTO OPUS 4.8 AT SESSION START

---

You are a senior principal engineer on **CommodityEx**, a personal institutional-grade Python
research terminal for a concentrated resource investor. Your mandate this session is to implement
the **remaining items from the June-9 codebase audit** (`docs/AUDIT_FABLE5_2026-06-09.md`), in the
batches specified below. This is remediation work on a live, working system: surgical fixes with
regression pins, never rewrites. Read this whole document before touching a line.

## 1. CONTEXT — THE SYSTEM AND ITS PHILOSOPHY

CommodityEx is a Druckenmiller-style "watch the few baskets very closely" terminal for a 4-name
silver/junior-mining barbell (spear: AGA.V ~60%; ballast: GROY, GMX.TO, URC.TO). Architecture:

- **ENGINE** (`engine.py`, FastAPI :8000) — the single source of mathematical truth (TIV legs,
  ρ/φ asymmetry, REP floor, JSF forensic gate, MRI regime). ~4,900 lines.
- **FORGE** (intelligence layer) — pure-stdlib consumer modules: `living_memory.py` (append-only
  JSONL), `sentinel.py`, `council.py`, `calibration.py` + `base_rates.py`, `trigger_grammar.py`
  (the security-critical safe-AST rule language), `catalyst_calendar.py`, `thesis_ledger.py`,
  `regime_posture.py`, `nav_mark.py`, `valuation_actions.py`, `world_state.py`.
- **COCKPIT** (`commodityex_tui.py`, Textual TUI, ~7k lines) + a legacy Streamlit `dashboard.py`.
- **MCP server** (`mcp_server/core.py` + `server.py`) — the agent contract surface.
- **Data**: Yahoo (`market_data.py`) → FMP free tier (`fmp_client.py`) → yfinance (engine
  forensics) → SEDAR+/EDGAR/issuer-PR web fetches (`ingestion_pipeline.py`). **There is NO broker
  integration — IBKR was confirmed vestigial and removed (commit `2758bfa`). Do not re-add it.**

## 2. HARD INVARIANTS — ANY CHANGE VIOLATING THESE IS WRONG, FULL STOP

1. **ENGINE is the single source of math truth.** FORGE/COCKPIT read; they never re-derive.
2. **The 60% spear ceiling is permanent.** It is enforced as a code-side structural constant
   (`SPEAR_CEILING_STRUCTURAL` in `engine.py`; config may only tighten it). Never loosen, never
   make tunable. `PHASE7_CONVICTION_MODE.md` row 1 is marked SUPERSEDED — leave it that way.
3. **`living_memory.jsonl` is append-only.** Corrections supersede; nothing is edited in place.
4. **No `eval`/`exec`/`compile` in the trigger path** (`trigger_grammar.py` is a closed-whitelist
   hand-walked AST). You will touch this file (item A3.6) — keep the boundary absolute.
5. **Config changes are proposal-gated** (`propose_param_change` → human `/confirm`).
6. **Catalyst dates are grounded straight-to-source** (URL required at "scheduled" confidence;
   softer confidences carry `grounded: false`).
7. **Grounded or silent.** Stale/cached data must say so (`stale`/`age_s` envelopes exist — keep
   them); never serve a fabricated default. Never emit `float('inf')` into a serialized payload.

House discipline you must match: **fail-closed** (missing data never reads as the favorable
case), **tests are pins** (change a pinned expectation only when the behavior change is the
deliverable, and say why inside the test), **comments explain constraints, not narration**.

## 3. WHAT IS ALREADY FIXED — DO NOT REDO OR "RE-FIX"

All seven audit CRITICALs and the first-PR list landed June 9-10 (commits `f0cde4a..2758bfa`):
falsy-zero Council gate (A1.1) · Sentinel crash + tri-state dilution sieve (A1.2, A1.10) ·
data-layer retry/backoff + staleness envelopes (A1.3) · catalyst URL gate + provenance through
the feed (A1.5) · Living Memory cache-coherence / retraction filter / torn-line accounting (A1.6,
A1.7) · statement-frame newest-first sort (A1.8) · friction + slot-gate fail-closed (A1.10) ·
scheduler flock (A1.12) · ceiling code-clamp + superseded PHASE7 row (A2.3, A2.4) · `set_param`
MCP label honesty (half of A2.2) · V1 mark-NAV-to-spot (`nav_mark.py`) · V2 ladder breakeven
inversion · D2 scout slot-tagging · D5 `@anti-scout`. If you find these "broken" by your own
expectations, re-read the audit and the tests before changing anything — the current behavior is
deliberate.

## 4. ENVIRONMENT FACTS (verified — believe these over your instincts)

- Run `pip install pytest` first. Test command:
  `python -m pytest tests/ -q --ignore=tests/test_v5_engine.py`
- **Baseline: 538 passed, 13 skipped, 6 failed.** The 6 failures PRE-EXIST and are out of scope:
  5 in `tests/test_ingestion_pipeline.py` (bs4 sanitizer + engine-import-dependent
  `TestEngineLiveFeedFlag`) and 1 in `tests/test_openbb.py` (async plugin missing). Do not fix,
  do not let them grow.
- `engine.py` **cannot be imported in this container** (no yfinance). Verify engine edits with
  `python -c "import ast; ast.parse(open('engine.py').read())"` + pure-module tests + grep
  assertions. Same for `dashboard.py` (no streamlit) and `commodityex_tui.py` (Textual runs, but
  you cannot drive the live cockpit — which is why Batch D is deferred).
- Also run `python mcp_server/selftest.py` after touching `mcp_server/` — must end `ALL PASSED`.
- Line anchors below were verified at HEAD `2758bfa`; they drift as you edit. **Re-grep before
  every edit**; the anchor is a starting point, the pattern is the truth.

## 5. GIT OPERATING RULES

- Work on your session's designated branch. `origin/main` should contain `2758bfa` ("Remove
  vestigial IBKR scaffolding") — if it is behind, fast-forward it or rebase your branch onto the
  newest lineage before starting. If you see commit `a3cb5c4` anywhere, that is an ORPHANED
  pre-force-push line — never merge it (it has unrelated history).
- Before your first commit: `git config user.email noreply@anthropic.com && git config
  user.name Claude` (commit-verification hook requirement).
- One commit per batch (A, B, C1, C2), descriptive message, full test run green (minus the 6
  pre-existing) before each commit. Push after each batch. Never push to `main` unless told.

---

## 6. THE WORK — FOUR BATCHES, IN ORDER

### BATCH A — small, safe, no running app (do first, one commit)

#### A-1 · Audit A2.1 / B8 — delete `dashboard.py`'s re-derived engine math  **(CRITICAL)**
The Streamlit dashboard re-derives what the engine already serves, so two screens can disagree on
ACCUMULATE vs TRIM — a direct invariant-1 violation.
- `dashboard.py:75` `_conviction_from_state(state, config)` rebuilds conviction/asymmetry from
  raw state (consumed at line ~315). Replace with a thin projection of the engine's
  `state["conviction_mode"]["baskets"]` (the engine already publishes rating/band/directive/
  ladder/asymmetry per basket — see `asymmetry_rating.compute_asymmetry_rating`'s return shape).
- `dashboard.py:~751-757` recomputes the ACCUMULATE/TRIM/HOLD directive + colors locally. Render
  the engine's `directive` string; keep only the local *color mapping* keyed off the directive
  text prefix (presentation, not derivation).
- `dashboard.py:93` `is_spear = (tkr == "AGA.V")` — read the spear from config
  (`portfolio_metadata` thesis_slot == "silver-spear") or from the basket's archetype.
- Same file, same batch: `dashboard.py:490-493` and `~740-747` render **hardcoded May-2026
  prices/shares as fallbacks** (`0.72`, etc.). A missing engine state must render "—"/empty —
  grounded-or-silent — never a stale literal.
- **Verify:** `ast.parse` the file; grep-assert no surviving local directive derivation
  (`grep -n "ACCUMULATE" dashboard.py` should hit only color-mapping/copy, not computation);
  if you extract a pure projection helper, unit-test it (no streamlit import in the test path).

#### A-2 · Audit A1.11 — harden `catalyst_engine.py` config reads + date handling  **(HIGH)**
- `catalyst_engine.py:178-182, 216, 260-267` (re-grep `float(cfg.get`): every one of these raises
  `TypeError` on a None/string config value. Use the module's existing `_num(x, default)` pattern
  (add one if absent) so a malformed config degrades to the default with a log line, never a
  crash in the overlay path.
- `catalyst_engine.py:102` `_parse_date` returns naive dates (strips `Z`); `_resolve_as_of`
  (line 118) arithmetic works today only because everything is uniformly naive. Normalize: parse
  to **aware-UTC then take `.date()`** at the boundary, so a future tz-aware input cannot
  silently corrupt `age_days`. Mirror `catalyst_calendar._parse` (already aware-UTC, tolerant).
- **Tests:** extend `tests/test_catalyst_engine.py`: (a) a config with
  `{"half_life_days": None, "max_age_days": "soon"}` produces defaults + no exception;
  (b) an event dated `"2026-06-04T17:36:17Z"` and one dated `"2026-06-04"` yield the same
  `age_days` against the same `as_of`.

#### A-3 · Audit A3.6 — `trigger_grammar.py` depth-counter leak + dead constant  **(security file)**
- Line 135: `_not()` increments `self.depth` and never decrements (the paren path at 154/159 is
  balanced). The counter is therefore *cumulative*, so ~64 NOTs anywhere in one expression —
  nested or not — spuriously fail to parse. Fix to true recursion depth (decrement after the
  recursive `self._not()` returns). **Keep the 64 bound; keep fail-closed parse errors.**
- Line 48: `BOOL_METRICS` is dead (the evaluator already handles bool truthiness). Delete it and
  its comment — dead code in the security boundary is a liability, not documentation.
- **Tests:** in `tests/test_trigger_grammar.py`: an expression with 70 *sequential* (non-nested)
  `NOT` legs (`NOT dilution_ok AND NOT death_spiral AND ...`) parses fine; 70 *nested* parens
  still raise `GrammarError`. Run the whole existing suite — it is the no-eval pin.

#### A-4 · Audit A3.7 — make `research_cache.set()` as-of-aware  **(JSF inputs)**
`research_cache.py:48` overwrites unconditionally — last-writer-wins on the filings-derived
inputs the JSF gate eats. Spec:
- Compare incoming `as_of` (ISO date prefix) against the existing entry's. **Older-dated write →
  refused**: return the existing entry plus `{"kept": "existing", "reason": "incoming as_of ...
  older than ..."}` and do not write. Equal/newer (or either side undated) → write, but preserve
  the displaced entry under a `previous` key inside the new entry (one level deep, not a chain) —
  cheap provenance without a new store.
- Add `force: bool = False` to override (the operator correcting a bad source), which still
  stashes `previous`.
- **Tests:** new `tests/` cases (extend `test_data_layer.py` if it covers this module, else add
  to a new small file): older-refused, newer-overwrites-with-previous, force-overrides, undated
  behaves as before. Check `seed_research_cache.py` still runs clean against the new contract.

### BATCH B — invariant hardening, small (one commit)

#### B-1 · Audit A2.2 / B12 — enforce the proposal gate engine-side  **(governance)**
`engine.py` `@app.post("/config/param")` (grep the decorator) currently forwards any `source`
into `dconfig.set_param`. The MCP layer now honestly labels its writes `"mcp:set_param"` — the
engine must **reject** them: if `source` is not in `{"cockpit", "human"}`, return
`{"error": "...direct set is operator-only; agents must use /config/propose → /confirm"}` with
nothing written. Trap: the `/config/confirm` route goes through `dconfig.confirm()` internally —
do not break it; only the direct-set HTTP route gets the gate. Verify with `ast.parse` + a grep
assertion; if `tests/` has a config-route test add the rejection case, else pin the behavior in
`dynamic_config`-level tests via a thin wrapper if reachable.

#### B-2 · Audit A2.5 — demote non-issuer RSS feeds to display-only  **(catalyst grounding)**
`ingestion_pipeline.py:~779-844` (`RssNewsAdapter`): generic mining-news aggregator feeds violate
design-decision #3; only issuer-scoped PR feeds (per-company GlobeNewswire/Newsfile) should mint
catalyst records. Spec: add an `issuer_scoped: bool` per configured feed (default **False** —
fail closed); events from non-issuer feeds get `"display_only": True` and are excluded by
`merge_authoritative`/`write_catalyst_feed` from the authoritative catalyst record (they may
still surface in news display surfaces). Keep `_trust` semantics intact. Check the existing feed
config (grep `rss_news` / `from_config`) and mark the per-company PR feeds `issuer_scoped: true`.
**Tests:** extend `tests/test_ingestion_pipeline.py` (the PASSING parts — 5 failures there are
pre-existing, leave them): a non-issuer event is display-only and absent from the persisted
feed's events; an issuer-scoped one passes through.

#### B-3 · Audit A3.8 — `dynamic_config.confirm()` TOCTOU  **(low)**
`dynamic_config.py:200`: the pending-row read happens outside `self._lock`; two concurrent
confirms double-apply (benign value, duplicate audit rows). Move the read + status flip into one
locked transaction: re-check `status='pending'` and mark `applied` atomically before applying.
**Test:** confirm the same pid twice → second returns `ConfigError("no pending change ...")`.

#### B-4 · Audit A3.10 — mark backdated Living Memory writes  **(low)**
`living_memory.py` `write(...)`: when the caller supplies `ts`, stamp `meta["_backdated"] = True`
so imported/backdated entries are distinguishable from live ones in the track record. Traps: the
seed importer (`seed_living_memory.py`) passes `ts` intentionally — the marker is the honest
record of that, not a bug; `reaffirm`/`supersede` do NOT pass `ts` and must stay unmarked. Run
`tests/test_living_memory.py` + `tests/test_thesis_ledger.py` + `tests/test_capture_loop.py`;
update any test asserting exact `meta` contents only if the assertion was incidental.

### BATCH C — M-effort correctness, ONE ITEM PER COMMIT, reviewed separately

#### C-1 · Audit A1.9 / B11 — engine shared-state race + unsupervised workers
Anchors (re-grep, these drift): `state_lock` created `engine.py:~2129`, held only at
`~2628/2662/2667` (background workers); four `asyncio.create_task(...)` workers at `~2461-2464`
with no supervision; the main eval loop and FastAPI handlers read/write `terminal_state`
unlocked. Spec — **snapshot-swap, not lock-everything**:
1. The eval loop builds the next state as a **fresh local dict**, fully, then publishes with a
   single reference assignment (`self.terminal_state = new_state`) — atomic under the GIL;
   readers always see a coherent snapshot. Audit every in-place mutation of the *published* dict
   (grep `terminal_state[`) and move it into the build phase or guard it.
2. Never hold `state_lock` across an `await`.
3. Supervise the four workers: keep the task handles, attach done-callbacks that log the
   exception and write a per-worker status into the state (e.g.
   `state["workers"]["macro"] = "dead: <err>"`), so a crashed worker is visible in `/state`
   instead of silently serving stale data.
This is the one batch where you must be conservative: if a mutation site is ambiguous, leave it
and document it in the commit message rather than guess. Verify: `ast.parse`, full suite, and a
written-out reasoning note in the commit body (this file cannot be import-tested here).

#### C-2 · Audit B13 / A3.1 — single-source the book composition
The book is hardcoded in at least: `engine.py:1957` (weights dict `{"AGA.V": 0.60, ...}` in the
PortfolioSizer), `engine.py:3267` (a second fallback copy), `ingestion_pipeline.py:~131`
(`DEFAULT_TICKERS`), `dashboard.py` (spear identity — gone after A-1), and assorted TUI strings
(display-only; out of scope). Spec:
- One accessor (engine-side): read weights from `v5_config.json` (`archetype_barbell_weights`
  already exists — verify its shape) with validation: weights > 0, sum ≈ 1.0 (±0.01), every
  ticker present in `portfolio_metadata`. On any violation, **log + fall back to the current
  hardcoded dict** (fail-safe: a config typo must not zero the sizer) — and surface
  `"weights_source": "config" | "fallback"` in `/state`.
- The spear ticker = the name whose `thesis_slot == "silver-spear"` (single derivation, used by
  the sizer's ceiling clamp).
- `DEFAULT_TICKERS` in ingestion reads from the same config (with its current list as fallback).
- **Interplay trap:** the 60% structural ceiling (invariant 2) is independent of the weights —
  a config weight of 0.70 for the spear must still be clamped by `SPEAR_CEILING_STRUCTURAL`.
  Pin that interaction in `tests/test_v5_engine.py` if importable, else in a pure helper test.

### BATCH D — explicitly OUT OF SCOPE this session (do not start)
- **A1.4 / B4** TUI blocking `_get`/`_post` → workers, **B14** tooltip completion, **A3.4/A3.5**
  monolith split + HTTP-stack unification: all need a drivable cockpit; deferred to a TUI-cluster
  session (pairs with H1 streaming).
- **FORGE_BUILD_SPEC.md** (B16): the file does not exist anywhere in-tree; you cannot check in
  what you do not have. Note it, move on.
- The 6 pre-existing test failures.

---

## 7. DEFINITION OF DONE

- Batches A and B committed (one commit each), C-1 and C-2 committed separately, all pushed.
- Full suite: **everything green except the same 6 pre-existing failures** (no new failures, no
  newly-skipped tests); every behavior change carries a regression pin that states, in the test,
  *why* the old pin changed. `python mcp_server/selftest.py` → `ALL PASSED`.
- `docs/AUDIT_FABLE5_2026-06-09.md`: append a short "RESOLVED (date)" note per closed item, as
  was done for IBKR — the audit doc is the ledger.
- Report at the end: per-item one-liner (what changed, where, test that pins it), anything you
  deliberately left (with the reason), and the updated remaining-items list.

## 8. WHAT GOOD OUTPUT LOOKS LIKE

Specific ("`catalyst_engine.py:178`, `_decay_weight`: `float(cfg.get(...))` → `_num(...,
default)`; pinned by `test_malformed_config_degrades_to_defaults`"), grounded (file:line, test
name), fail-closed by reflex, and philosophy-consistent — every change serves signal integrity
for the four names that matter. When a spec here conflicts with what you find in the tree,
**stop and re-read the relevant audit section** (`docs/AUDIT_FABLE5_2026-06-09.md`) and the
backlog assessment (`docs/BACKLOG_ASSESSMENT_2026-06-10.md`) before improvising; if still
ambiguous, implement the conservative reading and flag the ambiguity in the commit body.

## BEGIN

Confirm the environment first (pytest install, baseline test run, git author config, branch
state vs `2758bfa`), state your batch plan in one short message, then execute Batch A.

Go.
