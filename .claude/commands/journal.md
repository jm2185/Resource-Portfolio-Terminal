---
description: The calibration journal — grade closed decisions and show the expectancy scorecard (Druckenmiller objective, per archetype)
argument-hint: [ticker]  (optional — close out a specific name's outcomes first)
---
Run the decision journal on `$ARGUMENTS` (or the whole book if empty). Invoke **@calibration**.

1. **Close out outcomes** for any frozen `decision` in Living Memory past its horizon — stamp the
   realized price with `record_outcome` (ground truth from `get_fundamentals`). If `$ARGUMENTS` names
   a ticker, do that name first.
2. **Pull the scorecard** — `calibration_scorecard(by_archetype=true)` — and report it **objective
   metrics first**: expectancy per decision, slugging ratio, upside capture, downside containment;
   then the per-archetype split; hit-rate and conservatism bias **last** (secondary, never the
   headline).
3. **Name the systematic bias** if there is one (upside calls running hot, floors too conservative),
   and where it lives by archetype — that tells @bull/@bear where to dig.
4. **If the evidence is real, propose with receipts** — `propose_param_change(...)` routed through the
   `/confirm` human gate. Never set a tunable directly.

Report like:
> **Journal** — 9 closed decisions · **expectancy +18%/decision · slugging 2.4x** · upside capture
> 0.61 (under-riding winners) · containment 8/9. By archetype: explorers hot on upside (capture 0.5),
> royalties well-calibrated. Proposing `conservatism_scalar` 0.88→0.92 (floors ran 11% conservative,
> 6 decisions) → awaiting /confirm.

Decision-support only: the scorecard informs; nothing sizes or trades on its own.
