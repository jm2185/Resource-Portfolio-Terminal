# Handoff 2026-07-31 — CEG add program & memory-complex surveillance

**Session verdict:** explored a memory-sector long (MU / SKHY / MUU) post-correction and post the
Situational Awareness forced liquidation. Concluded **no memory position**. Redirected to a
two-tranche **CEG/CEGS.TO add program** around the Aug 6 earnings print. Memory demoted to a
**surveillance subject** building a 2027 short-thesis dataset.

This document is the reasoning record. The *operational* content has been ingested into the stores
that actually sweep it — see [Where everything landed](#where-everything-landed) — by
`scripts/bootstrap/ingest_handoff_2026_07_31.py` (idempotent; re-runnable; `--dry-run` prints the
plan).

---

## Read this first: what is NOT verified

The handoff's `~`-marked price levels are **operator-supplied from news flow, not verified prints**,
and this pass **could not verify them**:

- the engine was offline (no `/state`, no conviction baskets);
- the price layer (`data/price_history.json`) carries only the resource book — no CEG, CEGS.TO, MU
  or SKHY;
- the FMP `quote` and `chart` endpoints are **gated on the current plan** (both returned
  `ACCESS DENIED`), so there was no second source to check them against.

Consequently every such level is stored inside the thesis bodies under `reference_levels` with
`verified: false` and a warning string, and **none was written to an engine-owned field**. Open item
**§8.6 stays open**, and watch item `ceg.reference_levels` is registered at `pending_approval`
recording the blockage rather than letting it lapse quietly.

**Nothing downstream should treat these numbers as prints.**

---

## Where everything landed

| Handoff section | Store | How to read it back |
|---|---|---|
| §2 Ulysses pre-commitments (5, **verbatim**) | Living Memory `note` | `memory_query(tag="ulysses")` |
| §3 `CEG-ADD-2026Q3` | Living Memory `thesis`, CONDITIONAL, ticker **CEG** | `get_ledger()` · `memory_query(ticker="CEG", type="thesis")` |
| §5 `MEMORY-SHORT-2027-RESEARCH` | Living Memory `thesis`, **REJECT**, ticker **MU** | `get_ledger(stance="REJECT")` — the graveyard |
| §4/§5 **dated** triggers (3) | `data/catalyst_calendar.jsonl` | `catalyst_query(ticker="CEG")` |
| §4/§5 **undated** triggers (13) | `data/sentinel_watch.json` | `sentinel_watch.board()` |
| §6 reference context (3) | Living Memory `note` | `memory_query(tag="council-context")` |
| §7 durable rules R-1…R-8 | Living Memory `note` + [`docs/RULEBOOK.md`](RULEBOOK.md) | `memory_query(tag="rulebook")` |
| §9 predictions P-1…P-4 | Living Memory `note`, status `open` | `memory_query(tag="prediction")` |
| §8 open items (7) | Living Memory `note` | `memory_query(tag="open-item")` |

All entries carry `meta.handoff = "2026-07-31-ceg-memory"` and a `meta.record_id`, and are stamped
`provenance: user` — the operator's read, deliberately **not** `engine` or `sourced`, so anything
weighting by evidence cannot mistake a handoff paragraph for a filing.

---

## Design decisions worth knowing

### 1. The CONFIRM criteria are `claims[]`, not prose
R-7 ("criteria pre-registered before the print") is only a rule if something enforces it. The four
CONFIRM criteria are therefore the thesis's load-bearing claims **c1–c4**, each `manual` (no engine
metric can read a guide) and each held at status `unknown` until the call. The Sentinel re-checks
claims every sweep and flags a thesis whose integrity drops below its floor — so the DISCONFIRM set
is simply their negation, and post-hoc reinterpretation shows up as a broken claim rather than as a
changed story.

Claim **c7** (the post-add ceiling, §8.2) is held `unknown` **on purpose**: it is unanswered, and an
unanswered load-bearing claim should drag integrity rather than sit invisible.

### 2. Rules fire on events that something can actually stamp
The trigger grammar's `event:<name>` resolves against **calendar kinds that have been marked `hit`**
(`catalyst_calendar.hits_by_kind`). A rule keyed to an invented event name would be a tripwire
nothing could ever pull. Every rule in both theses is therefore keyed to a kind this batch actually
seeds — and a test (`test_every_rule_event_is_a_kind_a_seeded_window_can_stamp`) holds that line.

### 3. The catalyst vocabulary was extended by lane, not stretched
`catalyst_calendar.KINDS` was a junior-mining lifecycle (drill / assay / PEA / permit …). A regulated
generator's catalysts do not fit it, and forcing them in would be exactly the context-blindness
CLAUDE.md names as a bug. Five conventional-lane kinds were added:

`earnings` · `regulatory` · `contract_award` · `equity_offering` · `supply_data`

They are deliberately **absent** from `catalyst_lifecycle.OVERLAY_TO_KINDS`: the realized-overlay
feed is a junior-mining news classifier and cannot read them, so these windows stay **manually
resolved**. An honest gap, documented at the definition.

### 4. The memory file is a REJECT, and that is the point
`thesis_ledger.Ledger.graveyard()` exists so names you **passed on** keep being tracked — "tracking
them is how you learn what you wrongly skipped." A no-position research programme is exactly that.
It is filed under **MU** (the complex's bellwether and the name actually evaluated), with the subject
recorded as the whole complex, `position: NONE`, `surveillance_only: true`, and the standing 2027
short thesis in the body.

**This is a modelling call, flagged as open item OI-7** — if you would rather it not sit under MU's
ticker, say so and it supersedes cleanly (Memory corrections supersede; nothing is overwritten).

### 5. `pending_approval` is a first-class state
§8.5 asks JM to approve the §5 memory feeds **per feed**, against the API-only/resource-starvation
constraint. Registering them as "active" would be precisely the lie the coverage read exists to
prevent. So `sentinel_watch` carries approval as state: **8 of 13 items are `pending_approval` and
are reported as NOT watched**, by id, in `board()["coverage"]`.

The one exception is `mem.macro_cross_link` — the handoff calls it "already configured", and that
checks out: `bear_steepener` is wired through `rates_monitor` → `regime_lens` (G2) → scenario weight
B, one shared flag with no divergent interpretation. It is registered `active`.

---

## Known gaps — read before relying on these tripwires

**Neither thesis is swept by `sentinel_sweep`.** The sweep iterates the **held book's** conviction
baskets; CEG and MU are neither held nor in the eval set, so no engine metric (φ / ρ / JSF / price)
is diffed against these claims. What *is* live:

- the **manual claims** — operator-flipped after the call via `thesis_claim_set(ticker, claim_id,
  status, note)`, one call per criterion (the Aug 6 review is four flips: c1–c4 → `holds` or
  `broken`, each with a note). The flip supersedes the thesis, lands in the claim's `history`, and
  reads back the board (`"N hold · N broken · N unknown"`); the integrity floor still applies;
- the **calendar-armed rules** — once a seeded window is marked `hit`;
- the **watch registry** — for the undated items, at the cadence each declares.

Treat both entries as **frozen underwriting records plus a tripwire set**, not as engine-swept
positions.

Specifically **not machine-armed**: the Jul-29 forced-liquidation-low retest (memory claim c6 /
prediction P-1). The grammar's `price` / `floor` come from a conviction basket the engine does not
compute for MU. It is watched by `mem.sa_liquidation_low_retest`, which is `pending_approval` — so
**nothing is watching it today**, and P-1 resolves ~2026-09-11.

---

## Open items — JM input required before Wed Aug 5 close

| id | item | status |
|---|---|---|
| OI-1 | Total intended CEGS add size (CAD $ or % of book) | **blocking tranche 1** |
| OI-2 | Post-add CEGS ceiling (% of book), hard cap, written **before order 1** | **blocking tranche 1** (thesis claim c7) |
| OI-3 | Tranche 1 fraction (default 25–33% of OI-1) | **blocking tranche 1** |
| OI-4 | PJM homework slot on the calendar (target Aug 1–2 weekend) | Y/N |
| OI-5 | Approve the §5 memory feeds, per feed | Y/N per feed |
| OI-6 | Verify the `~` price levels | **blocked** (see above) |
| OI-7 | Review the MU-ticker modelling call for the memory file | review |

**Recommended approval order for OI-5**, if the API budget is tight:

1. `mem.dram_nand_contract_pricing` — the actual thesis clock (P-2 says the setup announces itself
   here ≥2 quarters before price). Paid vendor series.
2. `mem.hyperscaler_capex` — public issuer prints, no vendor cost, and it feeds **both** theses.
3. `mem.sa_liquidation_low_retest` — the only §5 item with a live clock (P-1, ~2026-09-11).

The remaining five are quarterly/weekly reads that can wait for a budget decision.

---

## Tranche discipline (§3, for the record)

- **Tranche 1** — 25–33% of the intended add, executed **by Wednesday Aug 5 close** (print is
  pre-market Thursday Aug 6, call 10:00 ET). Limit orders at mid, no market orders, avoid the
  open/close auctions. Size test: *a −15% gap Thursday must be emotionally invisible.*
- **Tranche 2** — the balance, **only on CONFIRM**, executed after the call review, **on criteria,
  not on price action**.
- **Special rule** — headline EPS miss **+** guide reaffirmed = **CONFIRM**. A sell-off on that
  combination is the *gift* scenario, not a warning (R-8).
- **Gap rule (U-2026-07-31-E)** — a green gap on a confirm is not "missed it"; a red gap on a
  confirm is not a knife. A worse entry inside an intact $340–360 underwriting basis changes the IRR
  decimal, not the thesis.
- **Invalidation (whole position)** — FY26 guide withdrawn or cut. Price weakness with the guide
  intact is opportunity, not invalidation.

---

## Source

Ingested from the operator's session handoff of 2026-07-31. The §6 reference context (analyst matrix,
PJM 2028/29 BRA actuals, memory-complex state) is preserved in Living Memory under
`tag="council-context"` for the next Council run to inherit — including the standing instruction that
per-analyst accuracy is **unverified and must not be weighted by reputation** (R-6).
