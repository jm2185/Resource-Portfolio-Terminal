# Standing Reassessment — Execution Record (2026-07-02)

*Execution pass over `docs/REASSESSMENT_2026-07-02.md`. The gate tags in that document are binding,
so "execute" meant three different things: the **code-behind-tests** and **read-only** items were
implemented with tests; the **propose→confirm** / **operator-decision** items are NOT applied — they
are surfaced below with the exact change ready. The engine was run LIVE and the full suite is green
(**1671 passed, 1 skipped**, up from 1644 — 27 new tests, zero regressions). Nothing in
`v5_config.json`, the book, or any tunable was changed.*

---

## Executed (code-behind-tests / read-only display) — all VERIFIED, all tested

| # | Finding (reassessment) | Change | Files | Test |
|---|---|---|---|---|
| 1 | **Exec #1 — the confirm hole.** `/config/confirm` + `confirm_param_change` applied a mutation with no source guard; an agent could propose then self-confirm | Extracted a shared `_write_source_ok()` human-only guard; applied it to `/config/confirm` (mirroring `/config/param`); **added the four direct-mutation MCP tools** (`confirm_param_change`, `remove_holding`, `promote_to_eval`, `demote_from_eval`) to every **subagent** deny-list — they already denied `set_param` | `engine.py` (guard + both endpoints); `.claude/agents/*.md` ×15 | `tests/test_confirm_gate.py` (4) |
| 2 | **Exec #4 / TF4 — the Council reconciler was unreachable.** `reconcile()` had no MCP surface; the Arbiter (denies Bash) could only apply the rules by feel | Added `council_reconcile` as a **pure read-only** MCP tool (pulls live ρ/φ/gate/ladder/directive/posture, writes nothing); pointed `arbiter.md` at it | `mcp_server/core.py`, `mcp_server/server.py`, `.claude/agents/arbiter.md` | `tests/test_council_reconcile.py` (6) |
| 3 | **TF2 — the 60% ceiling lived as 5 bare literals** kept in lockstep by comment only | Centralized into one shared constant `book_invariants.SPEAR_CEILING`; wired all five consumers to it (engine, dynamic_config, book_change, conditionals, mcp_server/core) | new `book_invariants.py` + 5 sites | `tests/test_spear_ceiling_central.py` (3) |
| 4 | **TF5 — 81 phantom `intrinsic=0.0` rows banded SOLID/FAIR** poison the ledger and would corrupt the grade on restart | Zero-intrinsic stamp-guard: auto-cadence never stamps a failed valuation; an explicit write is flagged `valuation_failed`; the grader excludes both the flag and pre-existing phantom zeros | `valuation_ledger.py`, `replay.py` | `tests/test_zero_intrinsic_guard.py` (6) |
| 5 | **Exec #3 / TF3 — the CFTC default is born badged LIVE**; MRI fabricates silently with no degraded flag | Cold-start `cftc_status` → `INITIAL_BASELINE` (aligns state_cache with the metrics dict); `calculate_mri` now stamps `degraded` / `data_fabricated` / `fabricated_inputs` / `degraded_inputs` in its detail (metadata only — the MRI **number is unchanged**, pinned by `test_v5_engine`) | `engine.py` | `tests/test_mri_degraded_flag.py` (4) |
| 6 | **Exec #6 / TF1 — provenance flags hidden.** `floor_degraded` / `quality_proxy_only` computed on every rating, rendered nowhere (confirmed LIVE: 3 of 4 held names run `floor_degraded=True` with zero tell) | Pure `_provenance_tell()` helper; the rail now marks a degraded floor (`~proxy`, dims the φ) and a proxy Q (`Q~proxy`) | `commodityex_tui.py` | `tests/test_provenance_tell.py` (5) |

**Test evidence:** full suite `1671 passed, 1 skipped` (127s). Confirm-gate verified live
(`_write_source_ok('cockpit')→True`, `('agent'|'mcp:…'|'engine-flywheel')→False`). MRI degraded
flag and the ceiling wiring verified live via `import engine` (`SPEAR_CEILING=0.6`).

### A note on the confirm-hole boundary (preserved dissent, resolved conservatively)
The reassessment flagged that "is the main session an agent?" is an operator call. This execution
draws the line at the **subagent** boundary only: the 15 isolated research subagents (bull, bear,
arbiter, scout, verifier, …) lose the four direct-mutation tools — they run with no human in the
loop and have no business confirming config or mutating the book. The **main session** (the
operator's proxy) and the **cockpit UI** keep them, so the `/confirm` skill still works. The endpoint
guard is the defense-in-depth layer; the manifest deny-list is the load-bearing closure. Whether to
*also* gate the main session (a cockpit-only confirm) remains the operator's call — not taken here.

---

## Surfaced for the operator — NOT applied (propose→confirm / operator-decision)

These are gated by charter discipline (any change to a tunable, the book, or config is
propose→confirm or operator-decision — a more capable model raises that bar, it does not lower it).
None is a proposal-queue tunable (they are static config values or module constants), so each is
listed with the exact change **ready for the operator to apply**, not auto-filed.

| # | Item | Why gated | Exact change ready |
|---|---|---|---|
| A | **AGA.V forensic waiver expires 2026-07-15** (13 days) — placeholder justification on the 60% spear | operator-decision (source the real basis or lapse) + propose→confirm (override string) | `v5_config.json:951-957`: either replace the `justification` with a SEDAR+ MD&A basis + new expiry, or let it lapse and re-engage the real dilution/CBA tests |
| B | **REP-floor cash/burn 162 days stale** (`monthly_burn_rate_asof: "2026-01-21"`), presented to the cent | propose→confirm (moves the spear floor); needs sourced data | Refresh `rep_floor_params.cash_treasury_m` + `cash_burn.*` from Silver47's two filed quarters (ended 2026-01-31, 2026-04-30) |
| C | **FRED label drift** — config declares `REAINTRATREARAT10Y`, engine fetches `DFII10` | propose→confirm; series choice = operator-decision | `v5_config.json:1034`: `"real_yield": "REAINTRATREARAT10Y"` → `"DFII10"` (config-matches-code) |
| D | **Uranium stamp** (US$86.10, as_of 2026-06-04) hits its 45-day cliff **2026-07-19**, single-sourced | read-only pilot (second reference) + propose→confirm (U-specific window) | Pilot a Sprott/Numerco cross-check before day 45; propose a `STALE_AFTER_DAYS` < 45 for uranium |
| E | **`survival_exempt_archetypes` diverges** — config `["asset_light_yield"]` vs code `+compounder,deep_value`; the merge makes config win, burn-gating the conventional-core lane | assertion = code-behind-tests, but the VALUE alignment is operator-decision (a load-time `assert` would crash until the values agree) | Decide whether compounder/deep_value should be exempt in `v5_config.json:761-763`; then the equality assertion can ship |
| F | **material_change hysteresis** to end the 74% GROY thrash | propose→confirm (sensitivity threshold `_FP_INTRINSIC_DECIMALS` / a min-delta) | Tune vs the 13-day ledger to confirm it still catches real re-ratings |
| G | **Backfill the price store + keep the heartbeat running** (grading matures from 2026-07-12) | data-store write / operator (engine ops) | `python backfill_price_history.py` on the host after reconciling adjusted-close vs engine price basis |
| H | **research_cache hand-edited GROY entries** (look-ahead `as_of`, out-of-vocab confidence) + the GROY $1B rejection missing from Living Memory | code-behind-tests (a load-time validator) + propose→confirm (re-write / Memory backfill) | Add an API-only invariant validator; re-write the two entries through `set()`; append the rejection as a `verification` Memory entry |

*The `council_reconcile` tool now makes the flywheel's first real write cheap: an Arbiter run that
persists a `council_verdict` fires the calibration capture-hook (`core.py:1116-1123`) — the loop that
has been frozen since 06-24. That is an operator action (convene the Council), now unblocked.*

---

*Nothing gated was applied. The engine ran live under degraded sandbox feeds; the confirm-gate and
imports were verified live, the born-LIVE badge and MRI flag are pinned by unit tests. When a claim
here conflicts with the tree, the tree wins.*
