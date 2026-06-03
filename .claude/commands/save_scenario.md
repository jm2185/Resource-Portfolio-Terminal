---
description: Save a named what-if scenario for reuse
argument-hint: <name> silver=+5 ry=-0.5 peer=+20%
---
Parse `$ARGUMENTS`: the **first token is the scenario name**; the rest is the overrides string
(space-separated `knob=value`, knobs: silver/ag, gold, ry, vol, peer, mri, dxy).

Call `save_scenario(name, overrides)`. Confirm it saved, and remind the user they can run it any
time with `/whatif <TICKER> <name>` (or `run_valuation_whatif(ticker, "<name>")`).
