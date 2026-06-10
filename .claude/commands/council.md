---
description: Run the Dialectic Council (bull → bear → arbiter) on a name — one reconciled verdict, dissent as caveat, written to Living Memory
argument-hint: [ticker]   e.g. "AGA.V", "GROY"   (empty = current focus)
---
Convene the **Dialectic Council** on `$ARGUMENTS`. You are the conductor: seat the two advocates and
the judge, ground everything in the engine, and land **one** reconciled verdict — never two competing
numbers. This is the per-name signal-coherence layer made concrete.

**Resolve the name:** a ticker in `$ARGUMENTS`, else the current focus (`get_ui_context`). If neither,
ask which name.

**Stream the debate** so the desk watches the rounds land (the cockpit's Council/PIPELINE panels track
it): `pipeline_event(stage="bull", ticker=…, message="…")`, then `stage="bear"`, then
`stage="arbiter"`, and `status="done"` at the end with the reconciled verdict in `result`.

**Run the three seats:**
1. **@bull** — strongest asymmetric long case, every claim grounded in `get_conviction_ratings`
   (ρ, φ, upside, the commodity tailwind), clearing the JSF gate. Archetype-aware (spear → asymmetry;
   royalty → cash-flow durability). Returns tagged bull claims.
2. **@bear** — the invalidation case + Liquidity Sentinel: the **hard invalidation level**, φ/ρ at the
   base leg, dilution/liquidity/exit, jurisdiction/permitting, regime vulnerability. Returns tagged
   bear claims with the invalidation level flagged. (It sharpens; it does not veto the spear.)
3. **@arbiter** — reconcile via `council.py` under the five rules (engine prior dominant, grounded >
   narrative, no narrative-veto on the spear, gate caps the bull, one verdict + dissent as caveat).
   Emit the verdict line, the convergence split (flag CONTESTED in 45–55), the named tension, the
   caveats. Pass the live **posture** if the book has one (it composes onto the size, e.g. 0.75x cap).

**Persist + surface (how the Council stays "living"):** the Arbiter writes the verdict to Living
Memory (`memory_write type=council_verdict`) so the next run, the What-If, and the Book verdict-tension
inherit it, and leaves **one** cockpit trace (`pin_insight` keyed to the stance; `highlight_ticker
level=warn` if contested).

**Then report the chain with attribution**, e.g.:
> **Council · AGA.V** — Bull (φ 1.28, ρ 3.1, convex drill stack) vs Bear (hard invalidation $0.58,
> dilution into tightening). Arbiter: **RE-AFFIRM • BELOW FLOOR — ACCUMULATE (0.75x cap)**, 54/46
> contested. Tension: liquidity/dilution in the spear under tightening. Pinned; verdict in Memory.

**Rules:** ground every claim in a live field or a filing (no vibes); the Bear's invalidation always
survives as a caveat on the one verdict; if the split is contested, say so (calibrated disagreement is
signal); leave one clean trace per name, not a log.
