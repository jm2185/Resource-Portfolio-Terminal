# Per-name frameworks + uranium work-up — P5

The final phase: the per-name analytical layer. Three pure, fully-tested modules that the cockpit and
research agents consume (conviction-analyst, story_card, `/rotate`).

## 5.1 Per-name thesis-variable monitors (`thesis_monitor.py`)
The finer-grained companion to the P4 invalidation *trip lines*: the **named variables each thesis
lives or dies on**, tracked continuously so a thesis is seen *drifting* before it trips. The framework
is authoritative here (which variables, healthy direction, which are **hard** thesis-breakers); the
engine/agents supply the live reads.

| Slot | Hard thesis-breakers | Soft variables |
|---|---|---|
| silver-spear | catalyst delivery · REP floor coverage · JSF integrity | silver price · financing runway |
| gold-royalty-ballast | counterparty production | gold price · royalty cash-flow · NAV/share |
| project-generator-holdco | cash position | NAV discount · portfolio NAV · discovery pipeline |
| electrification-royalty | uranium term price · vehicle structure | royalty cash-flow · electrification demand |

Rollup is conservative: any **hard** variable off-track ⇒ **OFF-TRACK**; soft drift or a **hard
unknown** ⇒ **WATCH**; all-known-healthy ⇒ **ON-TRACK**. Unknowns never read as healthy (a data gap is
a gap). Reads resolve from explicit status, a `value/min` threshold, or a `value/prior` trend that
respects the variable's good direction (e.g. a *narrowing* holdco discount is healthy as it falls).
Engine: `terminal_state["thesis_monitors"]` (one per holding; reads agent-fed).

## 5.2 Ballast upside frameworks (`upside_framework.py`)
The spear's upside is option-convexity (ρ); the ballast names are **structural and durable**, and
measuring them with the spear's lens buries them. So each gets its own decomposition:

- **GROY** = royalty cash-flow / GEO growth + gold-price leverage + a P/NAV re-rate. *Base* = growth +
  gold leverage; *bull* = + the re-rate. Smoke (GEO 12%, gold 15%, P/NAV 0.8→1.0): **base 27% / bull 52%**.
- **GMX** = portfolio NAV growth + holdco discount-close + discovery optionality. *Base* = NAV growth +
  discount-close; *bull* = + the discovery kicker. Smoke (NAV 10%, disc 40%→20%, disc-opt 25%): **base
  43% / bull 68%**.

Each returns the legs (% contribution), the base/bull range, and the key driver — the ballast analog
of the spear's asymmetry, so the ballast is sized on its own merits. Consumed by `story_card` / @synthesis.

## 5.3 Uranium-vehicle replacement work-up — RETIRED (module removed)
The standalone `electrification_workup.py` module was removed in the 2026-07 token-optimization
pass: it was never production-wired (imported only by its own test). Its two-gate, slot-fit-first
doctrine survives in the live path — the `electrification-royalty` slot definition in
`v5_config.json` / CLAUDE.md (electrification exposure + ballast stability, never a direct
operator), enforced by `thesis_monitor.py`, `discovery_screen.py`, and the `/rotate` slot gate.

## Acceptance — status
- ✅ 5.1: per-name thesis variables with hard breakers + conservative health rollup; unknowns ≠ healthy; wired as a live surface.
- ✅ 5.2: GMX & GROY upside frameworks — structural legs, base/bull range, key driver (ballast lens, not ρ).
- ✅ 5.3: slot-fit-first doctrine live via the slot gates (standalone work-up module retired, see above).
- ✅ Tunables proposal-gated (`thesis_monitor.* / upside_framework.*`); no `eval()`.

## Deferred (flagged honestly)
- **Live per-name reads for 5.1** (price trends, JSF, floor coverage, term price) come from the
  conviction pipeline / agents; until wired, variables read 'unknown' and the rollup reads WATCH.
- **Real candidate universe for 5.3**: the work-up scores whatever candidates it's handed; populating
  them is `@scout` / `add_candidate` (the existing scout→universe loop), not this module.
- **TUI panels** for all three (the data surfaces are complete).

## Tests
`tests/test_thesis_monitor.py` (12) · `tests/test_upside_framework.py` (11) ·
`tests/test_electrification_workup.py` (14). 388 green across the affected dependency-free suites.
