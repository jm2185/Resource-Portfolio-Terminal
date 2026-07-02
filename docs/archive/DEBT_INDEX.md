# Debt Index — verified state + the forward queue (2026-06-10)

The single living index of what's CLOSED (verified in code, not assumed from the June-9 audit),
what was closed THIS round, and every remaining change — each future item carrying the
**add-ons/prerequisites it needs** so nothing gets picked up half-blocked. Supersedes the "still
open" list in `docs/BACKLOG_ASSESSMENT_2026-06-10.md`; the audit document itself stays frozen as
the dated record.

## Verified CLOSED (re-checked against live code this round — don't re-fix)

| Item | Evidence |
|---|---|
| A1.1–A1.5 (all five CRITICALs) | council falsy-zero gate, sentinel TypeError, staleness envelope, catalyst URL grounding — closed in audit batches 1–4 |
| A1.4 TUI blocking I/O | **fully closed**: every `_get`/`_post` call site verified inside a `@work(thread=True)` worker (scan in this round's session; the one flagged line was a false positive inside `_run_workflow_bg`); `_clip_copy` already has `communicate(timeout=3)` |
| A1.6/A1.7 living-memory read-side | flock on append, skipped-line counter in `stats()`, retraction filter in `query()` |
| A1.10 fail-open gates | `sentinel.py:317` tri-state dilution; `council.estimate_friction` fail-closed on missing `days_90` |
| A1.12 scheduler race | `_job_lock` + `update_jobs` (flock) |
| A2.1 dashboard re-derived math + A3.4 hardcoded prices | live mode reads `v4_valuation`/nodes; sandbox-only local math under an OFFLINE banner (pre-flight round) |
| A2.3 60% ceiling | `SPEAR_CEILING_STRUCTURAL` code clamp — config can only tighten |
| A3.7 research_cache silent overwrite | restatement history + `as_at()` (flywheel Phase 4) |
| B13 (engine half) | `_resolve_barbell_weights(cfg)` is the single weights source incl. the sizer |
| B15 | shipped per backlog |

## Closed THIS round

| Item | What shipped |
|---|---|
| **A1.9 — engine state race + silent worker death** | (a) Atomic snapshot-swap: `publish_state()` deep-copies the working `terminal_state` into `_published_state` at the end of every eval cycle **and** after each interactive mutation (ui_command / annotation / activity / pipeline event); `/state`, the websocket broadcaster, and the GET buses serve the published frame — readers can never observe a half-updated book. (b) `task_supervision.py`: every background worker + the eval loop + the broadcaster are supervised — a crash or impossible-return is recorded in `terminal_state["worker_health"]`, flips status to `DEGRADED_WORKER_DOWN: <name>`, and republishes. Surfacing only, no silent auto-restart by design. |
| **A2.2 — set_param hard gate** | MCP `set_param` can no longer write config at all — even `confirm=true` files a proposal (`proposed_by: "mcp:set_param"`) for the operator's `/confirm`; the engine's `/config/param` independently refuses any non-cockpit/human source (defense in depth). |
| **A2.5 — RSS aggregator scope** | `RssNewsAdapter`: un-hinted (generic aggregator) feeds are skipped by default — issuer-scoped PR wires only, per design decision #3; explicit `allow_generic_feeds` opt-in keeps such items display-only at trust 0, never a superseding catalyst record. |

Tests: `tests/test_debt_closeout.py` (supervision death/return/cancel semantics, set_param
proposal routing, RSS scoping). The publish/swap itself is structurally simple (one deepcopy +
one reference assignment on the single-threaded event loop) but **needs the live smoke** below.

## The forward queue — every remaining change, with its prerequisites attached

Ordered by (operator risk ÷ effort). "Add-ons needed" = what must exist or happen first.

| # | Change | Why | Effort | Add-ons / prerequisites needed |
|---|---|---|---|---|
| 1 | **Live smoke session** — start engine + cockpit once: verify ledger seeds, daily price marks land, `worker_health` populates, `/state` serves published frames, dashboard live numbers match engine print | Everything since the flywheel build is compile-checked + unit-tested but never executed live (this env lacks yfinance) | S | A machine with `yfinance`/`textual`/`fastapi` installed + the FMP key in `.env`; run `price_history.backfill_from_yahoo` (one-time, 4 tickers, 2y) in the same session |
| 2 | **B13 (cockpit half) — kill remaining ticker literals** in `commodityex_tui.py` (≈565-613) and `ingestion_pipeline.DEFAULT_TICKERS`; engine `cad_prices` literal at the conviction call | A rotation must be a config edit, not a code edit. **Do before the first `/rotate` SWAP is executed** | M | None to start; pairs naturally with #6 (TUI split). Acceptance: grep for each held ticker returns only config/data/test fixtures |
| 3 | **4th peer for the spear comp** | n≥4 arms the outlier machinery; BRC.V dominance is a single-point failure on the biggest swing factor | S | **Operator/agent research**: sourced EV + resource oz + stage from filings (straight-to-source URLs) → `dynamic_discovery_v5.peer_registry` + `data/peer_set.json` + research_cache ounces. Do NOT add from memory |
| 4 | **Enrich `data/candidate_universe.json`** (numeric screen fields: fraser/mcap/runway/dilution/cash/EV) beyond the 3 identity-only seeds | The discovery screen is scaffolding until candidates carry numbers | S–M | A scout run with the screen-first brief (scout.md already re-pointed); FMP budget for non-holdings statements |
| 5 | **A1.8 — sort yfinance statement frames by date before `iloc` deltas** + assert `t0>t1` in `fetch_forensic_metrics` | JSF dilution/Sloan silently flip if the provider changes ordering | S | None — pure engine edit + a fixture test; verify in the #1 smoke |
| 6 | **TUI split** (the 8.8k-line monolith → modules; one book-projection helper for the 3 duplicated renderers) | Unblocks D3 (pre-screened bench), H1 (token streaming), H2 (workflow choreography), B14 | L | A running cockpit to verify rendering (#1); do B14 + #2 within it |
| 7 | **B14 — tooltip coverage from one glossary** (~14/28 metrics covered; dashboard keeps a second drifting dict — the live source is `get_glossary`) | Conviction-Mode clarity mandate | M | Ride with #6 (touching the monolith twice is waste) |
| 8 | **A3.5 — one HTTP/cache client** (collapse `market_data` / `fmp_client` / `ingestion_pipeline` stacks; shared retry/backoff + staleness envelope) | The staleness discipline currently exists ×3; future data work pays the tax each time | M | None technically; schedule after #1 so regressions are observable live |
| 9 | **Mode B full counterfactual replay** (re-run `PolymorphicRouter.get_valuation` on frozen snapshot payloads by `config_hash`) | Upgrades golden-ledger reconciliation into a true frozen-input backtest; the receipts engine for bigger /confirm proposals | M | ≥1 quarter of ledger depth to make it worth building; a payload-reconstruction map (snapshot.inputs → router payload fields) |
| 10 | **Brokerage reconciliation (M0)** — positions/weights from a broker export instead of config/CSV trust | "The terminal sizes against assumed weights" — the largest terminal-vs-reality gap | M | **Operator decision + data**: a broker (e.g. IBKR flex report / CSV) export path; deliberately NOT wired today (assessment terminal by design) |
| 11 | **V3 real-options π_opt** (Black-Scholes-on-rock) | Replaces the reasoned option-premium with a model | L | **Blocked on operator sign-off** of model form (vol input, expiry=funding horizon?) per backlog; propose via /confirm-style review first |
| 12 | **Regime-aware comps done right** (V4) | Regime tilt should operate *through* the peer multiple, not stack on the tilt leg | M | A reconciliation test proving the total regime effect applies exactly once (the V4 flag stands until that test exists) |
| 13 | **B16 — check `FORGE_BUILD_SPEC.md` into the repo** | The north star should be in-tree | S | **Operator add-on: the document itself** (it exists outside the repo; cannot be reconstructed honestly from code) |
| 14 | **H5 Conviction Book + Brier** | Per-claim probability grading | L | Blocked per backlog on a semantic memory-recall substrate; `implied_breakeven_p` + V2 breakevens already cover the thin edge |
| 15 | **Sentinel cross-check enrichment** — carry market_value/disagreement (not just the cache note) into the sweep's conflict alerts | Today the sweep shows the flag; the numbers live in the field note | S | Needs #1 first (ingestion writing conflicts in live operation) so the shape is observed, not guessed |

### Standing guardrails for whoever picks these up
- Engine = single source of math truth; the cockpit renders, never re-derives (A2.1 lesson).
- Fail closed; flag, never average; append-only with supersede semantics.
- Param changes through `propose → /confirm` — now mechanically enforced (A2.2).
- No regime double-count (V4); the 60% ceiling is structural (code clamp).
- Every new scorecard surface inherits the `reliability` small-n pattern.
