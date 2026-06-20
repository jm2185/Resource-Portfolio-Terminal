# Rates dashboard — bear-steepener / fiscal-dominance UPSTREAM tell (P2.1)

**Desk:** SENTINEL · **Module:** `rates_monitor.py` (pure) + `rates_history.py` (daily snapshot store)
· **Engine wiring:** `CommodityExMonitor._rates_assessment()` → `terminal_state["rates_dashboard"]`.

## Why
The leading indicator that **precedes** metals moves is the **long end rising while the Fed holds or
eases the front end** — the fiscal-dominance signature. It fires **weeks/months before** silver/gold
respond, so it is framed as an **upstream regime tell** that feeds scenario weights (P3), **never a
name-level score** and **not** a risk-on/off vote in the macro tape (a firing bear-steepener is a
*tailwind* for the metals book, which the binary risk tape would mislabel).

## What it tracks (straight-to-source levels)
| Read | Definition | Source |
|---|---|---|
| 2s10s | DGS10 − DGS2 | FRED / FMP treasury curve (`year2`,`year10`) |
| 5s30s | DGS30 − DGS5 | FRED / FMP treasury curve (`year5`,`year30`) |
| 30Y vs funds | DGS30 − FEDFUNDS | curve + `EFFR`/`FEDFUNDS` |
| MOVE | bond-market implied vol | FRED (`MOVE`) if obtainable — graceful when absent |
| Auction quality | tail (stop − when-issued), bid-to-cover | TreasuryDirect — graceful when absent |

The engine reads the rate **levels it already has** (the FMP `treasury_curve` + Fed funds) — **no new
network fetch** is required for the core tell. `rates_history.record()` appends one snapshot per day
so `rates_history.prior_within(window_days)` can supply the **prior-window value** the bear-steepener
needs ("the long end rising *over a window*").

## The discrete read (`terminal_state["rates_dashboard"]`)
- **`bear_steepener`** — `active` when Δlong ≥ `long_rise_bps` (default +20bps) over the window AND
  Δfront ≤ `front_static_bps` (default +5bps). Distinguishes a **bear-steepener** (fiscal dominance)
  from a **bull-steepener** (front falling = easing) and a **bear-flattener** (Fed hiking) — both of
  which stay dormant. `assessable: false` until the history window fills (honest, never faked).
- **`fiscal_dominance`** — composite 0–100 + label (**DORMANT <20 · BUILDING 20–45 · ELEVATED 45–70
  · ACUTE >70**), blended from the steepener, the 30Y-funds term premium, the MOVE level, and recent
  auction stress (each term drops out gracefully when its input is missing).
- **`flags`** — the discrete `bear_steepener` / `move_spike` flags the panel raises.
- **`events`** — timeline events for MOVE spikes and weak/tailing auctions.
- **`glossary`** — `?`-tooltip text for every read (`rates_monitor.RATES_GLOSSARY`).

## Acceptance (action-plan P2.1) — status
- ✅ Emits a discrete **"bear-steepener active"** flag (long rising / front static-or-falling).
- ✅ Logs **auction tails** and **MOVE spikes** as timeline events.
- ✅ Presents a composite **"fiscal-dominance pressure"** read.
- ✅ Framed explicitly as **upstream of** the metals book (every payload carries the note).
- ✅ Thresholds **proposal-gated** via `v5_config.json → rates_monitor` (/confirm) — `no eval()`.

## Tuning (proposal-gated)
`v5_config.json → rates_monitor`: `window_days` (lookback), `long_rise_bps`, `front_static_bps`,
`move_spike_level`, `auction_tail_bps`. Omitted keys fall back to `rates_monitor.DEFAULT_RATES_CONFIG`.

## Deferred (follow-ups, flagged honestly)
1. **Live MOVE + TreasuryDirect auctions** — the module consumes them and the composite/events light
   up the moment they're wired; until then those terms are simply absent (graceful), and the
   bear-steepener + term-premium + curve reads work from data already in hand.
2. **Dedicated TUI panel render** — the data surface is complete in `terminal_state["rates_dashboard"]`;
   a `_render_rates_dashboard()` panel (and its layout slot) is the remaining UI step. It was left
   out of this pass because the TUI can't be exercised in this environment (no `textual`); agents and
   the world-state already see the surface.
3. **P3 hand-off** — when the scenario-robustness engine lands, `bear_steepener.active` /
   `fiscal_dominance.score` raise the disorderly-fiscal-dominance scenario weight (one-directional).

## Tests
`tests/test_rates_monitor.py` (20) — spreads, bear-steepener vs bull-steepener/bear-flattener, MOVE
spikes, auction tails, the composite, graceful-missing-input. `tests/test_rates_history.py` (7) —
idempotent daily snapshot, `prior_within` window selection, torn-line tolerance.
