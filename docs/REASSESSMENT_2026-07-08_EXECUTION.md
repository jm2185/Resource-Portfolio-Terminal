# Standing Reassessment — Execution Record (2026-07-08)

*Execution pass over `docs/REASSESSMENT_2026-07-08.md`. Gate tags are binding: the
**code-behind-tests** items below were implemented with tests; every **propose→confirm** /
**operator-decision** item is NOT applied and is re-surfaced at the bottom with its deadline.
The engine was not run (offline in this environment). Full suite after the changes:
**1759 passed, 1 failed** — the failure is a pre-existing `tests/test_commodityex_tui.py`
async-timer flake that passes in isolation and fails identically on the UNMODIFIED tree under
suite load (verified by stash/run/pop; not a regression). Nothing in
`v5_config.json`, the book, or any tunable was changed.*

*(The store restore — Living Memory / valuation ledger / price history back under version
control at the 06-24 snapshot — was executed with the reassessment itself; see that document's
hygiene note.)*

---

## Executed (code-behind-tests) — all tested

| # | Finding (reassessment) | Change | Files | Tests |
|---|---|---|---|---|
| 1 | **TF3 2.1 — the born-LIVE fix was CFTC-only.** `dxy_status` and `ry_status` seeded fabricated defaults (99.0 / 1.0) badged LIVE | Both cold-start seeds → `INITIAL_BASELINE` (the macro worker flips them to LIVE on first sync, same as CFTC); a source-pinning test asserts all three seeds can never regress to LIVE | `engine.py` | `test_mri_degraded_flag.py::ColdStartSeedsNeverBadgeLive` |
| 2 | **TF3 2.1 — the MRI honesty scan skipped the four positional legs** (silver/real_yield/copper/gold — bare floats, no status), so a fabricated real_yield flowed into the regime read unflagged | `calculate_mri(..., input_status=)` — the caller passes each leg's feed status; non-LIVE legs land in `fabricated_inputs`/`degraded_inputs` with the same vocabulary as the metric scan; absent statuses are skipped, never guessed. Engine call site passes `silver` (with an honest `INITIAL_BASELINE` when the 74.8 fallback stood in) + `real_yield`; copper/gold carry no per-feed status today and are honestly omitted. **MRI number unchanged** (pinned) | `engines/macro_regime.py`, `engine.py` | `test_mri_degraded_flag.py::MriPositionalInputHonesty` (4) |
| 3 | **TF4 #3 / TF1 — `set_nav` was in no deny-list; 3 manifests missed `set_param`; the registration loop invites one-line-append drift** | `mcp__commodity-ex__set_nav` added to all **15** subagent manifests; `set_param` added to the 3 inconsistent ones; new **parity test**: (a) every manifest denies every direct-mutation tool, (b) every denied name is a real registered pass-through (renames can't orphan a deny), (c) any future mutating-named pass-through must be denied or explicitly documented proposal-gated | `.claude/agents/*.md` ×15, new `tests/test_agent_manifest_denylist.py` | 3 tests |
| 4 | **TF4 2.4 — `memory_write` had no provenance param** (the store validated it since 07-02; the MCP surface never passed it) | `provenance` exposed, validated against `PROVENANCE_TIERS`, **clamped at `sourced`** for this channel (`verified`/`engine`/`user` clamp down with an explicit note — an agent asserts at most "I cited a source") | `mcp_server/core.py` | `tests/test_memory_write_provenance.py` (5) |
| 5 | **TF3 2.2 — the promised PIT validator never shipped** (the +42 lines were the book-value guard); the two hand-edited GROY look-ahead entries + out-of-vocab confidence sat undetected | Pure `pit_violations()` scan (confidence ∈ vocab; `as_of ≤ fetched_at + 1d grace`) run on every load — **non-fatal, surfaced via logging**; detects exactly the 3 known GROY seams on the live cache. The entry **re-write stays propose→confirm** (item C below) | `research_cache.py` | `tests/test_research_cache_pit.py` (6) |
| 6 | **TF1/TF4 1.4 — headless runners' only write-guard was a prompt string** (carried since 07-02) | `_inject_disallowed_tools()` appends `--disallowedTools <the 8-tool direct-mutation set>` to every claude-CLI `_job_argv`/`_pipeline_argv`; custom `CEX_*_CMD` templates and templates already setting the flag are respected (same rule as `_inject_model_flags`) | `commodityex_tui.py` | `tests/test_headless_disallowed_tools.py` (4) |
| 7 | **TF3 0.4 (code half) — the uranium staleness window tripped on day 46, not 45** (`>` vs `>=`), and the 07-19 cliff was actually 07-20 | `resolve_spot`: `age >= stale_after_days` — day 45 IS stale, as documented; boundary test pins day-45-stale / day-44-fresh | `nav_mark.py` | `test_nav_mark.py::test_stale_window_boundary_day45_is_stale` |
| 8 | **TF1 #4 (carried from 07-02) — φ≥1 `BELOW FLOOR — ACCUMULATE` fired on an unverified floor** while the rail dimmed the same floor as `~proxy` | A degraded floor now yields `BELOW PROXY FLOOR — VERIFY · floor unsourced` — the loudest buy directive never rides a proxy floor. Both keyword parsers updated in the same change: council prior `("BELOW PROXY FLOOR", 0.58)` (positive lean, never the sourced-floor 0.72) and a `VERIFY` stance chip; the sync-guard snapshot re-pinned. The rating NUMBER is unchanged (pinned) — the gate is display/directive honesty, not a re-score | `asymmetry_rating.py`, `council.py`, `cockpit_widgets.py` | `test_asymmetry_rating.py` (gate), `test_directive_council_sync.py` (4), `test_rail_directive_action.py` |
| 9 | **TF2 #3 — sizer hardcoded the GROY/URC/GMX trio at 0.50-if-missing over `/3.0`** — phantom-0.50 residue after a remove_holding, silently-fictive diversification | Ballast set now DERIVED from `book_tickers(cfg)` minus the (max-weight) spear; real count denominator; every pair stamped `corr_source: measured\|default` + a `corr_default_pairs` list in the sizing detail. Full-book numbers identical to legacy (pinned) | `engines/sizer.py` | new `tests/test_sizer_corr_membership.py` (4) |
| 10 | **TF2 #6 — the rotation gate's silent REJECT on null ρ** hid "we can't rate the incumbent" as "the challenger lost" for three audits | `swap_verdict` now returns a distinct **`UNRATABLE`** decision naming the unratable side(s) — a book-health fact, never a merit verdict; ρ is never synthesized | `council.py` | `tests/test_council_swap.py` |

**Test evidence:** targeted files `39 passed` (tranche 1) + directive/sizer/council batches green
(tranche 2); full suite after tranche 2 `1759 passed, 1 failed` — the failure is a
`test_commodityex_tui.py` async-timer test that passes in isolation and fails identically on the
UNMODIFIED tree under suite load (verified by `git stash` → run → `git stash pop`; pre-existing
flakiness, noted for a future hardening pass).

## Boundary notes (scoping honesty)

- **The gemini/agy lane (TF4 N2) is NOT closed by #6**: `agy` takes different flags, so
  `_inject_disallowed_tools` deliberately leaves it alone. The agy lane holds no MCP config today
  (its risk is output-quality, not tool mutation), but the caller-identity gating recommended in
  the reassessment (Phase 1.2) remains open — it needs a design decision on where the gate lives
  (argv vs `core.py`), not a mechanical patch.
- **`set_nav` remains callable by the main session and the cockpit** — the line is the subagent
  boundary, per the 07-02 preserved dissent. Whether `set_nav` should *also* route through the
  proposal queue for the main session is Phase 1.1's remaining half: **operator-decision**.
- **The MRI number still computes on defaults and the 45.0 fail-safe scalar remains** — callers
  expect a float; the exception path already prints and now flags its detail. Making the number
  itself refuse is a behavior change to the regime read: **propose→confirm** if ever wanted.
- **copper/gold MRI legs are unflagged** until they carry a real per-feed status — omitting them
  beats mislabeling them under `prices_status` (they come from a different worker). Follow-up
  belongs with the last-good-cache work in TF3.

## Surfaced for the operator — NOT applied (gated), with deadlines

| # | Item | Deadline | Gate |
|---|---|---|---|
| A | **AGA.V waiver decision** — still `PLACEHOLDER`, expiry **2026-07-15**; refresh cash FIRST (item B), then source a real SEDAR+ basis + short expiry OR consciously lapse (honest JSF/intrinsic haircut). Recompute: paper runway 19.3 mo vs ~13.8 mo at config burn | **07-14** | operator-decision + propose→confirm |
| B | **REP-floor cash/burn refresh** (`asof 2026-01-21`, 168 days; AGA cash sourced to a Kitco opinion) from the two filed Silver47 quarters | before A | propose→confirm |
| C | **Re-write the two GROY cache entries through `set()`** (now machine-detected on every load by #5) + backfill the GROY $1B rejection to Living Memory | with Phase 2 | propose→confirm |
| D | **Uranium second source** (Sprott U.UN NAV-implied / Numerco) before the — now correctly day-45 — cliff **2026-07-19** | 07-18 | read-only pilot → propose→confirm (window) |
| E | **Host→repo cadence for the restored stores** — the repo holds the 06-24 snapshots; define when the engine host commits its appends so the record never silently forks again | this week | operator-decision |
| F | **Grading readiness by 07-12**: on the host — `repair_currency` dry-run, run the backfill, keep the heartbeat up; publish first grades with small-n CIs | **07-12** | data-store / operator |
| G | `survival_exempt_archetypes` value alignment; FRED label (`DFII10`); material_change hysteresis; `set_nav` proposal-routing; gemini-lane gate design | Phase 2-3 | propose→confirm / operator-decision |

*Nothing gated was applied. When a claim here conflicts with the tree, the tree wins.*
