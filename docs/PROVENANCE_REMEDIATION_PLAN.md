# Provenance & Confidence Remediation Plan

*Written 2026-08-13. **Plan only — nothing here is executed.** Triggered by the CEG bear-case error
(a sell-side price target quoted for a week as a modeled bear case) and the provenance audit that
followed (Living Memory `20260812-213534-40b404`, `20260812-213817-bf912e`).*

---

## The finding in one paragraph

The **research cache is well-disciplined** — every resource-name input carries `source` (URL),
`confidence`, and `as_of`, straight to SEDAR+/SEC/issuer. The guardrail even *worked* under test:
`AGA.V.nav_per_share` is deliberately `None` with the note *"Investing.com / Kitco (targets, not
NAV)"* — the exact trap CEG fell into was caught and refused there. CEG slipped through because
**the conventional lane's numbers don't live in the research cache at all.** They live in
`v5_config.json` as bare values with no source, no as-of, no confidence — and the thesis file's
`expected` block has the same gap, which is where a price target came to be stored in a field named
`bear_case_usd`. Two classes of work follow: **fix the structure so it can't recur**, and **refresh
the specific stale/low-confidence values now feeding live decisions.**

---

## Priority 0 — Blocks a decision already on the calendar

### P0.1 · GMX holdco NAV inputs — **before Friday's slot decision**
| | |
|---|---|
| **Symptom** | GMX's "+6.6% to base" (C$1.98 vs C$1.86) rests on three low-confidence modeled NPVs and a stale portfolio mark. |
| **Evidence** | `research_cache.GMX.TO.holdco_pipeline_assets` — Mont Sorcier $69M / Battery Hill $26M / Bell Mountain $5.5M, `conf: low`, notes say "US$50M **modeled**"; `holdco_peer_portfolio_value` $30M, `as_of: 2025-09-11` (**11 months stale**). |
| **Why it matters now** | Friday's interims decide whether GMX keeps its slot or funds the counterweight lane. A three-way gate (reclaim C$2.01 / chop / break C$1.83) resting on a soft NAV is a decision made on sand. |
| **Definition of done** | Peer-portfolio mark re-struck from current market values of the listed holdings (Globex publishes the portfolio; price each line). Pipeline NPVs either (a) re-derived from the latest NI 43-101 / FS with the discount rate and metal-price deck stated inline, or (b) explicitly de-weighted in the NAV until they can be. Mont Sorcier's FS was due Q2-2026 — check whether it landed; if so, the $69M model is replaceable with filed economics. |
| **Verify** | Re-run the holdco NAV; compare base FV before/after; if the base moves materially, the Friday framework's C$2.01/C$1.83 levels need restating. |
| **Owner** | `@value-analyst` (re-mark), `@data-integrity-auditor` (sweep after). |

### P0.2 · CEG independent underwriting basis — **before tranche 2 completes**
| | |
|---|---|
| **Symptom** | The thesis's $340–360 "underwriting basis" is *street-derived* (ex-extremes middle of analyst targets) and disagrees with the engine's independent DCF base ($274.83) by ~25%. The desk quoted whichever flattered the trade. |
| **Evidence** | Thesis `expected.basis_note`: *"ex-extremes middle of street; bear case Citi/Levine $297."* Engine `dual_sided` legs: floor $103.59 · bear $128.59 · base $274.83 · bull $675.07. |
| **Definition of done** | An FCF-based case the operator actually believes, built from CEG's own disclosures (post-Aug-6 guidance raise: FY26 adj EPS $11.50–12.50, ~920MW new PPAs, 20%-growth-through-2029 path), with the PPA-contracted vs merchant revenue split made explicit — that split *is* the bull/bear fork. Store `bear_case_usd` as a **modeled** number; move any analyst target to a separate, clearly-named `street_targets` field. |
| **Consequence to accept in advance** | If the independent number lands near $275, CEG is **hold-what-you-have** at spot and the second tranche wants the $260s. The 12% ceiling stands either way — it's a cap. |
| **Owner** | `@value-analyst`, then the operator confirms the basis before the balance of tranche 2. |

### P0.3 · AGA research refresh — **before the assays land**
| | |
|---|---|
| **Symptom** | Core AGA inputs predate the company's current shape. In-ground ounces `as_of 2025-08-01` (the Summa merger PR) — **before** the Belmont 2.74 Moz AgEq tailings resource (Jul 2026) and all 2026 drilling. `shares_out` `as_of 2026-06-04`; `cash` C$48M `as_of 2026-06-12` (the runway number the JSF gate reads). |
| **Why it matters now** | When the Red Mountain assays print, the desk revalues on the spot — with a year-old ounce base and a two-month-old treasury. Clean inputs must exist *before* the binary, not after. |
| **Definition of done** | Ounces re-stated as a per-district table (Red Mountain / Mogollon / Hughes-Belmont) rather than one merged figure; cash + shares refreshed from the latest SEDAR+ filing (the Q-ended 2026-04-30 MD&A, per the config's own burn-rate note); runway re-derived. |
| **Owner** | `@catalyst-verifier` (source discipline), `@data-integrity-auditor`. |

---

## Priority 1 — Structural: stop it recurring

### P1.1 · Provenance schema for the conventional lane
**Root cause of the CEG error.** `portfolio_metadata.<ticker>.dual_sided` holds bare numbers —
`fcf: 3.1e9`, `stressed_fcf: 2.2e9`, `wacc: 0.08`, `growth.p50: 0.10` — with no `source`, `as_of`, or
`confidence`, unlike every research-cache entry. RPRX, WRB, and every future conventional name will
inherit the gap.

**Proposed fix:** allow each numeric input to carry a sibling provenance record (source URL, as-of,
confidence, and `basis: filed | derived | modeled | street`), mirroring the research-cache shape.
Then: **`dual_sided_valuation` refuses to run — or runs with a loud degraded flag — when a
load-bearing input carries `basis: street` or lacks provenance entirely.** The `basis` vocabulary is
the actual fix; "street" becomes a first-class, visible category rather than something that quietly
looks like a model.

**Verify:** re-run CEG's valuation; it should now surface *"underwriting basis: street-derived"* on
the face of the output rather than in a note nobody reads.

### P1.2 · Thesis `expected` block — separate models from targets
`bear_case_usd: 297` held a price target. Rename/split the schema so a target can never occupy a
modeled field: `modeled_bear`, `modeled_base`, `street_targets: {low, high, source, as_of}`. Sweep
the other thesis files (MU, and any future ones) for the same pattern.

### P1.3 · Corporate-action trigger
The AGA `single_asset` staleness (fixed 2026-08-13) existed because **the data-integrity auditor
fires on config changes, but a merger is a real-world change with no config trigger.** Nothing ever
prompted the re-sync — and the config was internally inconsistent for months (the burn-rate note
modeled concurrent Hughes + Red Mountain programs while the identity block said single-asset).

**Proposed fix:** a standing rule — any merger, acquisition, disposition, or resource re-statement on
a held name triggers an identity + metadata sweep (`sector_tags`, `thesis_slot_desc`, ounce/asset
tables, CLAUDE.md slot row). Cheapest implementation: a periodic `@data-integrity-auditor` pass whose
brief explicitly includes *"has the company's shape changed since these fields were written?"*, rather
than only checking internal consistency.

---

## Priority 2 — Engine-flagged violations (contained, but live)

The engine's point-in-time checker already prints these on every startup — they are **known and
unfixed**, which is the worst state for a flagged item to sit in:

```
research_cache: 3 point-in-time violation(s) —
  GROY.holdco_blue_sky_value: confidence_vocab
  GROY.holdco_blue_sky_value: look_ahead_as_of
  GROY.royalty_book_rerated_value: look_ahead_as_of
```

| Item | Value | Issue |
|---|---|---|
| `GROY.holdco_blue_sky_value` | $60M | `confidence: "low-med"` is outside the allowed vocabulary; `as_of` fails the look-ahead test |
| `GROY.royalty_book_rerated_value` | $1B | `as_of` fails the look-ahead test |

**Why it matters:** GROY is 20.9% of the book and the engine's only ACCUMULATE. A $1B re-rated
royalty-book value and a $60M blue-sky adder are material to its ladder.

**Definition of done:** confidence normalized to the allowed vocabulary; `as_of` dates corrected to
the actual publication date of the underlying evidence (a point-in-time violation usually means the
stamp is later than the data it describes, i.e. the value was available to the model before it
existed in the world — the exact bug that makes backtests lie). Then the startup log goes quiet,
which restores the signal value of that log line.

---

## Priority 3 — Hygiene refreshes

| Item | Current | Fix |
|---|---|---|
| CEG stored `price` | $263.56 (~1 week stale) | Refresh; it anchors the DCF base slightly low |
| `URC.TO.nav_inventory.spot_usd` | $86.10 U3O8, `as_of 2026-06-04`, manually stamped ("no free live feed") | Re-stamp; matters for the UROY Jan-27 call's valuation, the only remaining electrification exposure |
| `GMX.TO.quality_cashflow_coverage` | 0.29 (`as_of 2025-12-31`) | Refresh from Friday's interims — this is the metric the whole royalty-revenue-quality watch turns on |

---

## Sequencing & effort

| Phase | Items | Trigger | Rough effort |
|---|---|---|---|
| **A** | P0.1 (GMX NAV) | Before Friday's print, or immediately after with the fresh interims in hand | One `@value-analyst` run |
| **B** | P2 (GROY violations) + P3 hygiene | Any time — mechanical, no research required | Under an hour of edits |
| **C** | P1.1 + P1.2 (schema) | Before RPRX/WRB are underwritten — the gap is only cheap to fix while the lane has one occupant | Half a day: schema + `dual_sided` guard + tests |
| **D** | P0.2 (CEG basis) | Before the balance of tranche 2 | One `@value-analyst` run + operator confirm |
| **E** | P0.3 (AGA refresh) | Before the Red Mountain assays print | One `@catalyst-verifier` + one auditor sweep |
| **F** | P1.3 (corporate-action rule) | With C | Documentation + auditor brief edit |

**Suggested order given the calendar:** A → B → E → D → C → F. (A is date-forced; B is free; E is
racing an unknown clock; D gates real capital; C is the durable fix but has no deadline until RPRX;
F rides along with C.)

---

## What "done" looks like, globally

1. Every number that reaches a valuation carries **basis + source + as-of + confidence**, and
   `street` is a visible category that cannot masquerade as a model.
2. The engine's point-in-time log is **quiet** — so when it speaks again, it means something.
3. No held name's identity block describes a company that no longer exists.
4. The desk can answer *"where did this number come from?"* for any leg of any ladder, in one lookup,
   without reading a note.

---

*Nothing in this plan is executed. Each item awaits the operator's go, in the sequence above or any
other.*
