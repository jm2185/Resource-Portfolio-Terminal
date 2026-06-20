# SENTINEL signal layer — P2.2 / P2.3 / P2.4

Three additions that complete the upstream-tell layer, all pure + unit-tested, all one-directional
(they feed scenario weights in P3, never a name-level score) and consolidated onto one surface.

## P2.2 — AI-productivity monitor (`productivity_monitor.py`) — the thesis-breaker watch
The debasement tilt is a bet the economy stays **real-but-narrow** (genuine productivity, but
concentrated → pick-and-shovel intact). It breaks if productivity goes **broad AND accelerating**
(scenario C — grow out of the debt without debasing). Watches two variables:
- **breadth** — concentrated vs broadening (derived from the industry decomposition: 1 − normalized HHI).
- **trajectory** — settling toward trend vs accelerating to a sustained ~2%+ output/hour.

Sustained **broadening AND acceleration together** trips `debasement_at_risk` ("re-weight toward
pick-and-shovel"). Composite `scenario_c_pressure` (0–100, SOFT→BROAD-ACCELERATING) feeds scenario C.
*Sources:* BLS output/hour + revisions, BEA GDP, Fed regional decomposition. Engine read:
`terminal_state["productivity_monitor"]` (graceful/dormant until the BLS series is wired).

## P2.4 — oil-supply-risk flag (`oil_supply_monitor.py`) — let the tape price the geopolitics
Monitors the signed-MOU assumption via **objective proxies only** — **explicitly NO intent score**
(the plan's anti-pattern; the market prices intent better than any model). Proxies:
- **price level break** (WTI/Brent through a threshold), **OVX spike** (oil-vol tail),
  **term-structure → backwardation** (front richer than deferred — the cleanest *physical*-stress tell).
- a **headline flag** (Hormuz/ceasefire keywords) that is **context only, human-read, never scored**.

When price + vol + term-structure fire **together** → `oil_supply_risk` elevated and
`armed_energy_royalty_watch = true` (arms 5.4). Dormant (and unarmed) while the glut holds. Engine
read: `terminal_state["oil_supply"]` (graceful until WTI/Brent/OVX/futures are wired).

## P2.3 — SENTINEL board (`sentinel_board.py`) — the single consolidated surface
One panel of uniform **cards** — each `{id, label, read, value, flag, feeds_scenario}` — gathering:
- the **new** monitors: rates (P2.1) · productivity (P2.2) · oil-supply (P2.4);
- the **existing** macro-tape signals: silver positioning (CFTC) · macro regime (DXY/real-yield/GSR)
  · copper (Cu/Au);
- **USD/CAD carry + trend** (`sentinel_board.usdcad_carry`) — the dry-powder currency tilt (→ P4.3).

A pure consumer — it **normalizes, never recomputes** (one-directional). **Coverage is explicit**: a
monitor the plan expects but that isn't wired (the uranium term market) is listed under
`coverage.missing`, never silently absent. Active flags bubble up tagged with their monitor; the
`net_read` summarizes flag count, coverage %, and which scenarios are flagged. Engine read:
`terminal_state["sentinel_board"]`.

Smoke (all monitors hot): **7/8 monitors, 88% coverage, 4 flags** — rates→B, productivity→C,
oil→arms-5.4 — with `uranium_term` honestly listed missing.

## Acceptance — status
- ✅ P2.2: each release updates breadth + trajectory; broadening+acceleration trips the flag; feeds C.
- ✅ P2.4: price/vol/term-structure together → "oil-supply-risk elevated" + arms 5.4; headline unscored; no intent model; dormant ⇒ unarmed.
- ✅ P2.3: single surface; each monitor exposes read + flag; all feed P3; coverage gap explicit.
- ✅ Thresholds proposal-gated (`v5_config.json → productivity_monitor / oil_supply_monitor`); no `eval()`.

## Deferred (flagged honestly)
- **Live feeds**: BLS productivity series (P2.2), WTI/Brent/OVX + futures strip (P2.4), the uranium
  term market and a Bank-of-Canada policy rate for the carry. Each monitor consumes its feed the
  instant it's wired; until then it reads dormant/graceful and the board lists the gap.
- **TUI panel render**: the data surfaces (`terminal_state["sentinel_board"]` etc.) are complete; the
  dedicated `_render_sentinel_board()` panel is the remaining UI step (left out — the TUI can't be
  exercised without `textual` here).

## Tests
`tests/test_productivity_monitor.py` (13) · `tests/test_oil_supply_monitor.py` (14) ·
`tests/test_sentinel_board.py` (10). 252 green across the affected dependency-free suites.
