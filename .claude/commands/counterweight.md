---
description: Source uncorrelated conventional diversifiers that cover the book's scenario holes (the @counterweight agent — decorrelation + coverage, not alpha)
argument-hint: [scenario hole | sector | empty]   e.g. "AI-upside", "benign", "payments compounders", or empty to auto-target the holes
---
Invoke **@counterweight** — the conventional core's decorrelation sourcer — on `$ARGUMENTS`. It finds
non-resource, US/Canada cash-flow names that are **independent of the silver spear** (different
reasons, ρ→0) and that **cover the scenario holes** the resource book leaves red. It is **not** an
alpha-scout: it optimises decorrelation + coverage + priceability, and it stays in the thin lane (it
feeds the universe and hands off to `dual_sided_valuation`; it never councils or per-name-scouts).

**Ground the hunt in the book's actual hole first.** Before dispatching, read `get_world_state` (the
`book_factor` block): the **macro-correlation** (is the book genuinely single-factor?) and the
**scenario coverage** (which columns — AI-upside C, benign E, crisis B — are uncovered, and the
weight). Pass the live hole into the agent's brief so it sources for THAT column, not generically.

**Decide the target from `$ARGUMENTS`:**
- A **scenario hole** ("AI-upside", "benign", "crisis") → source names that fill that column.
- A **sector/theme** ("payments", "exchanges", "deep-value cash generators") → source within it, but
  still gated on independence + coverage.
- **Empty** → read the coverage matrix and target the **largest uncovered weight** automatically; say
  which hole you're filling.

**Run it:** dispatch `@counterweight` with the hole + the book's spear/correlation context in the
prompt. It returns a ranked shortlist (each: lens · the hole it fills · measured-or-proxy independence ·
floor/durability · priceability + input gaps · the swing variable · score + risk), freezes each find
(`memory_write type=counterweight_candidate`), and feeds the universe (`add_candidate … lane:conventional`)
so **SCREEN ⟂** ranks them next run.

**Then report with attribution and the hand-off**, e.g.:
> **Counterweight · AI-upside hole (30% weight, uncovered)** — sourced 4 → 1 REDUNDANT (a bank =
> leveraged steepener, rejected) → 3 independent diversifiers: **X.TO** (compounder, fills C, ρ≈0.1),
> **EEFT** (deep-value, fills C/E, ρ≈−0.0), **<staple>** (compounder, fills E). Underwrite **X.TO**
> first via `dual_sided_valuation`. All three written to the universe (lane: conventional) — `/screen
> uncorrelated` now ranks them.

**Rules:** ground every name in filings/web (no fabricated names or numbers); reject anything whose
only case is "cheap / it'll rip" (you source counterweights, not alpha); REDUNDANT-to-the-spear is an
auto-reject; US/Canada listings only; if nothing clears the independence-and-coverage bar, say so
rather than padding. The output feeds the dual-sided engine — it is never the buy decision itself.
