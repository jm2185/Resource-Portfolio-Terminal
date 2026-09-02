# Standing Reassessment — Execution Record (2026-09-02)

*First execution pass over `docs/REASSESSMENT_2026-09-02.md`, on the operator's "ok start —
you're free to run the engine." Gate tags are binding: the **code-behind-tests** items below were
implemented with tests; the **instrument** items were done through the desk's own tools (the
instrument-first contract, finding 4); every **propose→confirm** / **operator-decision** item is
NOT applied and is re-surfaced at the bottom. The engine WAS run this session — in the sandbox,
deliberately on a dark feed (Yahoo rate-limits this host; OpenBB absent; FRED timing out) as a
live test of the stamp guard. Full suite after the changes: **2,015 tests, OK** (the three
pytest-only files pass separately, 39/39). `v5_config.json` gained one identity block
(`merger_terms`, facts from the arrangement PR — not a tunable); no tunable, weight, or store
row was altered or removed.*

---

## Executed — code-behind-tests

| # | Finding | Change | Files | Tests |
|---|---|---|---|---|
| 0.1a | **TF3 #1 — seed marks written into the ledger and the price store.** The daily stamp fired on the cold-start cycle and `record_mark` had no staleness check | New pure `mark_guard.py`: `trustworthy(ticker, prices_stale, prices_status, prices_ts)` fails closed on `seed` / `no-sync` / `sync-stale` / `stale` / `unknown`; `plan_stamps()` splits a cycle's baskets. `_record_valuation_ledger` now skips **both** `maybe_record` and `record_mark` for any untrustworthy mark, publishes `terminal_state.ledger_guard {stamped, skipped{ticker: reason}}`, and logs once per change | `mark_guard.py`, `engine.py` | `tests/test_mark_guard.py` (7 guard + 2 seesaw + 2 regime) |
| 0.1b | **TF3 #3/#7 — the seed still badged `prices_status: LIVE`** (the born-LIVE pattern, fourth key) with a fresh `prices_ts` | Seed → `"prices_status": "INITIAL_BASELINE"`, every seed ticker `prices_stale: True`, `prices_ts: 0.0` (no sync yet); the worker flips them on first sync. The flywheel's existing `prices_ts` gate now also holds at cold start | `engine.py` | `test_mri_degraded_flag.py::ColdStartSeedsNeverBadgeLive` (+ `prices_status`) |
| 0.1c | **TF3 #2 — seed macro values recorded as the tape** (`seesaw_history`: gold 2350 / silver 74.8 / real 1.0\|1.8 ×7 days) | `mark_guard.seesaw_trusted()` requires a live silver mark AND a LIVE real-yield leg; the engine records the snapshot only then and publishes `seesaw_guard {recorded, reason}` | `mark_guard.py`, `engine.py` | `test_mark_guard.py::SeesawTests` |
| 0.1d | **TF3 #3 — `spot_ag_status` inherited the holdings-only `prices_status`** | Silver leg badged `INITIAL_BASELINE` on a seed, `DEGRADED_STALE` on a dated/last-good mark, else the feed status; the `Spot_Ag` metric carries it | `engine.py` | live run (below) |
| 0.1e | **TF5 #6 — posture flips persisted on seed inputs** (the 16 rows of 06-23/24) | `mark_guard.regime_trusted()`: a posture event is persisted as a `regime_snapshot` only when `macro_status == LIVE` and prices are not seeds; the ephemeral tape line still shows it | `mark_guard.py`, `engine.py` | `test_mark_guard.py::RegimeTests` |
| 0.3 | **TF2 #1 / TF3 #6 — no BNKR feed; the merger has zero code readers** | New pure `merger_arb.py` (implied consideration · spread · premium to undisturbed · zero-premium acquirer price; stale-flagged, never filled). Config contract `portfolio_metadata[<t>].merger_terms`; the price worker fetches every declared acquirer (intraday quote included); the engine publishes `terminal_state.merger_arb` every cycle | `merger_arb.py`, `engine.py`, `v5_config.json` (AGA.V `merger_terms`) | `tests/test_merger_arb.py` (6: reproduces the PR's C$0.93 / 38%, the 08-24 spread, the C$3.91 line, honest nulls) |
| 2.2 | **TF4 #12 — the suite pinned the old book** (8 failures; CI red on every push) | The eight tests now assert invariants — the config's own barbell keys, a spear + ≥1 ballast, the CEG units the config carries, the router's registered names, distinct ballast subarchetypes — with the legacy 4-name fixtures pinned explicitly via a temp config where the legacy math is the point | `tests/test_v5_engine.py`, `test_sizer_corr_membership.py` (+1 live-book invariant test), `test_archetypes.py`, `test_conventional_holdings.py`, `test_ingestion_pipeline.py` | suite green |
| 4.3 | **Finding 4 — instrument-first chat contract** | `CLAUDE.md` "Scorecard capture" gains the instrument map (rule → `thesis_write`/`thesis_claim_set`; conviction → `record_conviction`; contested → `/council`; held name → `sentinel_sweep`; call → `record_decision`; forecast → `forecast_write`; note = fallback) and the engine-down rules | `CLAUDE.md` | — (practice) |

## Executed — through the instruments (finding 4, first calls)

| Instrument | What was recorded | Memory id | Result |
|---|---|---|---|
| `thesis_write("AGA.V", CONDITIONAL)` | The operator's own AGA rules, verbatim-sourced: the floor leg and optionality legs (08-18 freeze), sell-half-at-a-double `price >= 1.37` (alert), the no-news tripwire `price <= 0.585 AND no_catalyst_within_days(30)` (review — never an auto-sell), `event:assay` → the month-24 results-only evaluation + the vote framework, `event:metallurgy` → the assays-AND-met kill, `runway_months < 12` (flag); one **engine claim** `runway_months >= 18` written to read BROKEN on the config's stale cash/burn by design; the ratio-too-cheap and zero-premium claims; modeled legs labelled modeled, `street_targets: null` | `20260902-113726-063c26` | 8 claims · 5 rules, every trigger parsed by the grammar |
| `thesis_write("GROY", APPROVE)` | Ballast identity; the engine claim `phi >= 0.9` ("is the ballast still ballast" — the July breach made this the honest read); Tether as a floor-defending buyer; the operator's 30% structural target with T1/T2 add zones as a claim; rules `phi >= 1.0` (alert: the add zone), `phi < 0.8` (review the floor's 244-day-old layers), `event:financing_window` (accretion, not dilution) | `20260902-113726-84eed9` | 5 claims · 3 rules |
| `sentinel_sweep("AGA.V")` (thesis-only — engine down by choice) | **Integrity 4/8, 1 new alert**: `THESIS INTEGRITY on AGA.V 4/8 (50%) below floor 60%` — four load-bearing claims are *unknown* (assays publish · first-batch grade · met recovery · the runway engine claim). That is the correct state of a pre-binary thesis, and it is now a Sentinel alert instead of a feeling | `20260902-113954-46fb11` | alert `AGA.V:integrity` (warn) |
| `sentinel_sweep("GROY")` (thesis-only) | Integrity 3/5, no alert (two unknowns: the φ engine claim awaits a live mark; the $5-by-Jan-28 view awaits its date) | `20260902-113954-677ba6` | clean |

**Not called, and why:** `record_conviction` — the operator has stated no numeric confidence on the
open AGA thesis (the 0.82 is an agent estimate of deal completion, not thesis conviction); the
next session should ask for one number and record it. `/council` — a three-seat run on the
AGA/BNKR instrument is the right next call, deferred to a session with the engine on a live feed
so the Arbiter reads real ρ/φ. `record_decision` — no new buy/sell/pass was voiced.

## The live run (engine in the sandbox, dark feed)

Two eval cycles with Yahoo rate-limiting the host, OpenBB absent, FRED timing out. Result:
`seesaw_guard = {recorded: false, reason: "silver:seed"}`; `Spot_Ag = {74.8, INITIAL_BASELINE}`;
`DXY = {99.0, INITIAL_BASELINE}`; `merger_arb.AGA.V` published with `acquirer_px: null`,
`implied: null`, `stale: true`, `zero_premium_acquirer_px: 3.8863`. **Stores after the run:**
`valuation_ledger.jsonl` 3,515 rows (unchanged), `price_history.json` and
`seesaw_history.jsonl` byte-identical (md5 unchanged), Living Memory +4 rows — the two theses
and the two sentinel sweeps, nothing engine-written. **Boundary note:** in this run the
conviction baskets were empty (the peer/forensic workers could not fetch), so
`_record_valuation_ledger` returned before the ledger guard's per-name path executed; that path
is covered by the unit tests, not yet by a live cycle with baskets. The next engine session on a
real feed should confirm `terminal_state.ledger_guard` shows `stamped` names and, on a partial
feed, the skipped ones by reason.

## Boundary notes (scoping honesty)

- **The contaminated dates are still in the stores** (8 GROY / 1 AGA seed marks; the 7 seesaw
  rows; the seed-priced 06-23 GROY decision). The guard stops the next fabrication; the labelled
  quarantine and the void/refreeze are **propose→confirm (data-store)** — items 0.2 and 0.4 below.
- **`merger_terms` is config.** It carries verified facts from the arrangement PR (ratio, dates,
  undisturbed close, source) and is read only by `merger_arb.py`; it is not a tunable and moves
  no rating. Remove it at close/termination with the identity sweep the config already promises.
- **The ratio-implied AGA mark is published, not yet consumed** by the ladder, V, or the sizer —
  the merger-arb *instrument state* (Phase 1.2) is a separate change.
- **`price` in the trigger grammar is the engine's CAD mark** — the GROY rules were therefore
  written on `phi`, not on USD levels; the USD ladder lives in the claim text.
- **Thesis integrity counts an `unknown` claim against the floor** (the CEG c7 rationale). The
  AGA alert is that policy working, not a bug; if the desk prefers unknowns to be neutral, that
  is a `forge.sentinel.integrity_floor` question — propose→confirm.

## Surfaced for the operator — NOT applied (gated), with deadlines

| # | Item | Deadline | Gate |
|---|---|---|---|
| 0.2 | Labelled quarantine of the seed dates (GROY 08-02, 08-17..25; AGA 08-02; the 7 seesaw rows) — supersession receipts, `force_set` only from a vendor close | before the next replay grade | propose→confirm (data-store) |
| 0.4 | Void/refreeze the seed-priced GROY decision `20260623-215431-2282e3` (matures ~**09-21** on 4.444); supersede the GMX artifact outcomes as `suspect`; re-seed the learned base rate | **09-19** | propose→confirm (data-store) |
| 1.1 | AGA cash/burn from the filed MD&A; runway re-derived; the waiver decided consciously — the AGA thesis's engine claim `runway_months >= 18` is written to grade it | before the assays | propose→confirm + operator-decision |
| 1.3 | Resolve the overdue TLT-fill forecast (`20260825-222939-e9969a`, NO per the 08-28 record); the 09-04 post-JH 30Y forecasts and the 09-11 memory-low forecast straight-to-source | 09-04 / 09-11 | data-store |
| 1.4 | CEG `target_weight 0.12` so the sentinel's rebalance band arms; the credit-sentinel claim as a thesis rule | this week | propose→confirm |
| 2.3 | Slot-aware single-position cap (the 0.40 ballast sleeve under a 0.20 cap → permanent TRIM) | with 2.1 | propose→confirm |
| 0.5 | Store cadence rule (stores + config committed together at session end) | this week | operator-decision |
| — | One number: the operator's live confidence on the AGA thesis → `record_conviction` | next session | operator |

*Nothing gated was applied. When a claim here conflicts with the tree, the tree wins.*
