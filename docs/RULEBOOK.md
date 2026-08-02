# The rulebook — durable decision rules for COUNCIL & CALIBRATION

Rules the desk established the hard way and agreed to apply *before* the next argument starts. They
are not thesis-specific: a rule earns its place here by generalizing past the name that taught it.

**How to use them.** The Council seats (`@bull` / `@bear` / `@arbiter`) and `@calibration` should read
these as standing constraints on how an argument may be made — not as facts about any name. A claim
that violates a rule is not thereby wrong, but it must be *argued past the rule explicitly*, in the
open, rather than around it.

**Where they live.** Each rule is also a Living Memory `note` tagged `rulebook`, so an agent can
recall them without reading this file:

```
memory_query(tag="rulebook")
```

This document is the human-readable canon; Memory is the machine-readable one. They are written
together by `scripts/bootstrap/ingest_handoff_2026_07_31.py` — if you add a rule, add it in both.

---

## R-1 — Instrument clock
Match the instrument's decay/reset profile to the thesis horizon. Daily-reset leverage is
days-horizon only.

*Why:* a daily-reset product converts a price bet into a path bet. Being right about the destination
does not pay if the route is volatile. (Established with U-2026-07-31-C.)

## R-2 — Leverage bill
All leverage costs the same bill at different windows — premium (options), decay (LETFs), forced
exit (margin). Choose which one knowingly; never pretend the bill is absent.

*Why:* the three forms feel different and are the same. The dangerous one is the third, because it
comes due at the worst possible moment and is paid by someone else's decision.

## R-3 — Block-trade interpretation
A multistrat absorbing a forced seller's book at a discount is **liquidity provision**, not
directional conviction. Do not cite it as "institutional buying." 13F lag makes any real-time
institutional-flow claim narrative until proven.

*Why:* the single most available bullish-sounding fact after a forced liquidation is also the one
that carries no information about direction.

## R-4 — Late-cycle tell
Producer shortage-extending guidance **plus** simultaneous record capex expansion = the cure for high
prices is high prices, on an ~18-month fuse. Applies to memory now; generalizes to all commodities.

*Why:* the two signals are individually bullish and jointly bearish. Producers are least able to see
the top when their margins are proving them right.

## R-5 — The $400/$900 check
Before **any** momentum-name entry, answer in writing: *"Why wasn't I interested at [pre-run
price]?"* No written answer = no entry.

*Why:* the Druckenmiller March-2000 signature. If the only thing that changed is the price and the
coverage, the thesis is the coverage. Requiring it *in writing* is the whole control — the question
is easy to answer glibly and hard to answer on paper.

## R-6 — Mechanism over reputation
When analyst targets diverge, adjudicate by **testable mechanism** (did reality print?), not by
track-record rankings. Accuracy leaderboards in trending sectors are momentum-contaminated.

*Why:* in a sector that has trended for two years, the "accurate" analysts are the ones who were
long. Ranking by them imports the momentum you were trying to test.

## R-7 — Confirm-criteria pre-registration
Any earnings-gated add program must have its CONFIRM/DISCONFIRM criteria written **before** the
print. Interpretation after the fact is vibes with extra steps.

*Enforcement:* write the criteria as thesis `claims[]`, not as prose. The Sentinel re-checks claims
every sweep and flags the thesis when integrity drops below its floor, which is what converts R-7
from an intention into a mechanism. (`CEG-ADD-2026Q3` claims c1–c4 are the worked example.)

## R-8 — EPS-noise exclusion
For outage-driven generators (the CEG archetype), single-quarter EPS is excluded from the confirm
criteria; **guide integrity is the signal**.

*Why:* a refueling outage moves a quarter by more than the thesis does. Gating on the noisy series
guarantees you will act on noise. The archetype-specific form of a general principle — *know which
series carries your signal before the print, not after.*

---

### Establishment record
R-1 … R-8 were established 2026-07-31 (the CEG add program / memory-complex surveillance session).
See `docs/HANDOFF_2026-07-31_CEG_MEMORY.md` for the reasoning that produced them.
