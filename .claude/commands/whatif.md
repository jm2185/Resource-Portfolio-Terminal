---
description: Scenario what-if on a holding — revalue under macro/peer/regime overrides
argument-hint: <TICKER> [silver=+5] [ry=-0.5] [vol=+10%] [peer=+20%] [mri=-3] [gold=+50]
---
Run a valuation scenario with the `run_valuation_whatif` MCP tool.

Parse `$ARGUMENTS`: the **first token is the ticker**; everything after it is overrides
(space-separated `knob=value`). Call `run_valuation_whatif(ticker, overrides)` with the
overrides joined back into a single string.

Then report concisely:
- which knobs moved (from → to),
- base vs scenario **intrinsic** and **upside %**,
- the **deltas** (intrinsic %, upside pp),
- one grounded line on what it implies for conviction — don't overstate, and say plainly
  if the engine was offline or the name wasn't recognized.

Knobs: `silver`/`ag`, `gold`, `ry` (real yield), `vol`, `peer` (EV/oz), `mri`, `dxy`.
Values: absolute `79.8` · delta `+5` / `-0.5` · percent `+20%`.
