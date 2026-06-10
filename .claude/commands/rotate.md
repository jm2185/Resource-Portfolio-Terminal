---
description: Rotation gate — should a challenger swap into the book for an incumbent? Slot-fit first, then the friction-adjusted ρ-edge under the catalyst lock. One verdict, written to Living Memory.
argument-hint: <incumbent> <challenger>   e.g. "URC.TO NXE.TO", "GROY WPM"
---
Run the **Rotation Gate** on `$ARGUMENTS` (`<incumbent> <challenger>`). You are the conductor of a
Darwinian high-grading decision — swap only when the *net* edge clears the bar AND the challenger
fits the incumbent's thesis slot. Never churn a concentrated book on a narrow edge.

**Resolve the pair:** the first token is the incumbent (a current holding), the second the challenger.
If only one name is given, ask which it's replacing.

**Run the gate (the math is the engine's, not yours):** call `council_swap(incumbent=…, challenger=…)`.
It enforces, in order:
1. **Slot-fit — non-negotiable, ahead of valuation.** If the challenger fills a *different* thesis
   slot than the incumbent, the tool returns `REJECT · slot-mismatch` WITHOUT scoring edge. Report
   that plainly: a better-valued name in the wrong slot is still a REJECT. (A challenger with no
   configured slot passes flagged `slot_unverified` — call that out and confirm fit before acting.)
2. **Off-book challenger.** If the challenger isn't in the live book, the tool sources its ρ from the
   research cache. If it returns `needs: "valuation"`, the challenger has no asymmetry to compare —
   say so and route to **`/pipeline <challenger>`** or **@synthesis** first, then re-run `/rotate`.
3. **Friction-adjusted ρ-edge under the catalyst lock.** `edge = ρ_chl/ρ_inc − 1`,
   `net_edge = edge − friction` (friction from the incumbent's liquidity runway); a near catalyst on
   the incumbent (≤ lock window) → **DEFER** (don't sell into the drill result). `SWAP` only when
   `net_edge ≥ hurdle`, else `REJECT`.

**Surface it visually (leave the desk a trace, not a log):**
- `pin_insight(<challenger or incumbent>, "<verdict line>", level=…)` — `good` for SWAP, `warn` for
  DEFER/slot-unverified, `risk` for REJECT.
- For a live SWAP/DEFER candidate, `apply_scenario` on the challenger so the side-by-side is loaded.
- The tool already writes the verdict to Living Memory — don't double-write.

**Then report the chain with attribution + the arithmetic**, e.g.:
> **Rotation · URC.TO ← NXE.TO** — slot-fit ✓ (both electrification-royalty). Edge +52% − friction
> 9% = **net +43% ≥ 35% hurdle → SWAP**, no catalyst lock. Pinned; verdict in Memory.
> *or* — **REJECT · slot-mismatch**: GROY fills gold-royalty-ballast, URC.TO holds electrification-
> royalty. Not scored on edge — a rotation must fit the slot first.

**Rules:** slot-fit is the first screen, always; never invent a ρ — if the challenger isn't valued,
say so and send it to the pipeline; the incumbent's near catalyst always wins (DEFER survives as the
verdict); one clean trace per run.
