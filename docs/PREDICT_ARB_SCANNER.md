# PREDICT_ARB_SCANNER — Wealthsimple Predict arbitrage scanner (design & build plan)

**Status:** BUILT — Phase 0 + the L2 plumbing (2026-07-30). Companion to
`WS_INTEGRATION_ASSESSMENT.md` (brokerage side); this doc covers the *prediction-markets* side.
**Date:** 2026-07-29 · **Branch:** `claude/wealthsimple-arb-scanner-9qc89b`

## What exists (Phase 0 build, validated against the live Kalshi API)

| Piece | Where |
|---|---|
| Read-only Kalshi public client (rate-limited, TTL-cached, both wire vintages normalized; **no order endpoints by construction**) | `kalshi_client.py` |
| The pure brain: constraint graph (partitions · threshold ladders), L1 parity/partition/ladder sweeps, first-class fee+FX netting, book-walk depth validation, L2 band-gated value edges + capped Kelly, dedup semantics | `predict_arb_monitor.py` |
| Engine wiring: supervised `_predict_worker` (two-stage fetch: quotes → depth for candidates only), pure sweep each eval cycle → `terminal_state["predict_arb"]`, `_fire_predict_arb` (Signals note + Living-Memory sentinel + append-only `data/predict_ledger.jsonl`) | `engine.py` |
| HTTP surface: `GET /predict` · `POST /predict/refresh` · `POST /predict/fair_value` | `engine_api.py` |
| MCP tools: `predict_scan` · `predict_opportunities` · `predict_fair_value` | `mcp_server/core.py` + `server.py` |
| Config block (fee placeholders + thresholds) & proposal-gated tunables (`theta_struct`, `theta_value`, `min_size`, `scan_interval_s`, `max_days_to_settlement`; fee fields deliberately file-only) | `v5_config.json` · `dynamic_config.py` |
| Cockpit: the ⚡ PREDICT lens card (pure builder `render_predict_arb`) | `cockpit_widgets.py` · `commodityex_tui.py` |
| Tests (40): pure math · client normalization · engine wiring (all green; no live network in the suite) | `tests/test_predict_arb_monitor.py` · `test_kalshi_client.py` · `test_predict_arb_engine_wiring.py` |

L2 today takes its p̂ from `predict_fair_value` (sourced, band-gated — operator or agent supplied);
the dedicated `prob_models/` (options-implied · OIS · nowcast · climatology) remain Phase 1.
Everything below this line is the original plan, kept as the design record.

---

## 0. Verdict first

**Build the scanner on Kalshi's official public API, day one — before Predict even fully
launches — and treat the Wealthsimple leg as a friction model, not a data feed.**

The structural fact that makes this tractable: **Wealthsimple Predict is a routed front-end to
Kalshi.** Orders flow WS → clearing agent → Kalshi; the ~4,000 contracts Canadians will see *are*
Kalshi's contracts (CIRO-limited to economic indicators, financial markets, climate; 30+ day
settlement; no sports/elections). Kalshi's market data — including full order books — is public,
official, unauthenticated, ~30 req/s. So the true executable book for every contract in Predict
is freely queryable **without touching any unofficial Wealthsimple API at all**.

That inverts the risk profile of the obvious plan. The unofficial-WS-API route
(`gboudreau/ws-api-python` etc.) is the *last* phase, optional, read-only, and only exists to
measure Predict-side quote staleness and to calibrate the fee model from real fills. The scanner
itself — the math, the alerts, the terminal integration — runs entirely on official public data.

Three opportunity lanes, in order of rigor:

| Lane | What it is | Executable by a Canadian via Predict? |
|---|---|---|
| **L1 — Structural (Dutch books)** | Internal probability-axiom violations *inside Kalshi's own books*: YES/NO parity, partition sums ≠ 1, ladder monotonicity breaks | **Yes** — the same contracts are listed on Predict; arb survives iff profit > WS frictions |
| **L2 — Model-vs-market** | Kalshi price vs a first-principles probability (options-implied, OIS-implied, nowcast, climatology) | **Yes** — as a value bet, Kelly-sized, Brier-tracked; not riskless |
| **L3 — Venue basis** | Predict displayed price vs Kalshi live book (staleness / fee-naive retail quoting on a brand-new platform) | **Signal only** until Phase 3 — needs a Predict-side price observation; and a two-leg cross-venue arb is impossible anyway (Canadians can't trade Kalshi directly — that's the whole point of Predict) |

Honesty note carried through everything below: with one executable venue, "arb" means
(a) genuine one-venue Dutch books net of fees (rare, small, real), and (b) high-edge value
bets priced from first principles (the bread and butter). The scanner labels which is which
and never conflates them.

---

## 1. Market structure — what is known and what is not

**Known (sourced):**
- WS Predict announced 2026-06-18; standalone app; beta now, public launch "summer 2026";
  second CIRO-approved dealer for event contracts (approval March 2026).
  [newsroom.wealthsimple.com](https://newsroom.wealthsimple.com/wealthsimple-to-launch-prediction-markets-trading-app)
- ~4,000 Kalshi contracts; categories restricted to **economic indicators, financial markets,
  climate**; contracts must settle **30+ days out** (CIRO); sports/elections prohibited in Canada.
  [BetaKit](https://betakit.com/wealthsimple-launches-prediction-markets-app-through-us-exchange-kalshi/) ·
  [CBC](https://www.cbc.ca/news/business/prediction-markets-wealthsimple-9.7239575)
- Order path: WS → clearing agent → Kalshi. WS charges a commission per contract and pays
  Kalshi + clearing fees. [The Globe and Mail](https://www.theglobeandmail.com/investing/personal-finance/article-wealthsimple-kalshi-partnership-prediction-markets/)
- Contracts are binary, settle $1/$0; price ≈ market-implied probability.
- Kalshi API: REST + WebSocket at `api.elections.kalshi.com/trade-api/v2`; public market data
  (markets, events, order books, trades, candlesticks) needs **no auth**, ~30 req/s; order book
  is bids-only both sides (YES bid at p ≡ NO ask at 1−p).
  [docs.kalshi.com](https://docs.kalshi.com/api-reference/market/get-market-orderbook)

**Unknown (the fee-model gap — first-principles placeholder until launch):**
- WS commission per contract — undisclosed.
- Currency: CAD display with FX conversion, or USD balance — undisclosed. WS Trade's USD
  corridor has historically been ~1.5%; assume that as the ceiling until measured.
- Order types on Predict (limit? market-only?), quote refresh cadence, whether the full Kalshi
  depth is shown or just top-of-book.

Every unknown becomes a **config field with a conservative default**, updated the day the app
launches from the first real fills (the same "validate the schema against a real file before
writing the parser" gate the WS assessment imposed).

---

## 2. The arb math, from first principles

All prices in probability space, per contract, $1 notional. Let `f_ws` = total WS-side friction
per contract-dollar (commission + clearing + Kalshi fee + FX round-trip, from the fee model §3).

### L1 — Structural violations (riskless if net-positive)

**(a) Binary parity.** For one market, buying YES at ask `a_y` and NO at ask `a_n` pays $1 at
settlement regardless of outcome:

```
profit = 1 − (a_y + a_n) − 2·f_ws        → flag iff > θ_struct
```

On Kalshi's book this is near-impossible by construction (bids-only book enforces
`a_n = 1 − b_y`), so its real use is validating the pipeline and catching L3-style display
divergence on Predict later.

**(b) Partition (Dutch book).** For a mutually-exclusive, exhaustive event set
{m₁…mₙ} (e.g. a CPI bracket ladder, "Fed decision" outcome set):

```
Buy-all-YES:  profit = 1 − Σ ask_yi − n·f_ws            (exactly one leg pays $1)
Buy-all-NO:   profit = (n−1) − Σ ask_ni − n·f_ws        (n−1 legs pay $1)
```

Either > θ_struct → alert. These *do* appear on Kalshi in thin multi-bracket ladders,
especially near open/close and right after data prints. n legs of fees kill most of them —
which is exactly why the friction model is first-class.

**(c) Monotonicity on threshold ladders.** For "X > k" contracts, k₁ < k₂ implies the k₂ event
⊆ k₁ event, so any pricing with `bid(X>k₂) > ask(X>k₁)` is a pure dominance violation:

```
buy YES(X>k₁) at ask, buy NO(X>k₂) at ask → payoff ≥ $1 in every state
profit ≥ 1 − ask_y(k₁) − ask_n(k₂) − 2·f_ws
```

Same logic for calendar dominance ("above X by June" ≥ "above X by May") and implication pairs
(A ⇒ B requires P(A) ≤ P(B)). The scanner builds a small **constraint graph** per event family
(partition sets, ladders, calendars) from Kalshi's event/market metadata and sweeps it every
cycle. This is the genuinely novel compute; everything else is plumbing.

### L2 — Model-vs-market (value, not arb — labeled as such)

For each contract family, derive an independent probability `p̂` and compare with the market:

| Contract family | First-principles `p̂` | Source already in / near the terminal |
|---|---|---|
| Index/equity thresholds ("S&P > X on date D") | Risk-neutral P from the options chain (digital ≈ −∂C/∂K at K=X), with a risk-premium haircut | FMP (options/quotes already wired) |
| Rate decisions / "Fed funds at X" | OIS-implied path / FedWatch-style distribution from futures | FMP economics + rates_monitor machinery |
| CPI / econ prints | Nowcasts (Cleveland Fed inflation nowcast), consensus dispersion → distribution over brackets | WebFetch, cached |
| Climate ("hottest month", "hurricane count") | NWS/ECMWF ensembles + climatology base rates | WebFetch, cached; base-rate-first |
| BTC/crypto thresholds | Deribit options-implied distribution | Public API |

```
edge = p̂ − price          (buy YES if edge > 0, buy NO if < 0)
EV   = |edge| − f_ws
Kelly fraction (buy YES at cost c):  f* = (p̂ − c) / (1 − c),  capped by posture size-cap
```

Alert iff `EV > θ_value` **and** the model's own uncertainty band doesn't contain the price.
Every alert the operator acts on flows into the existing flywheel: `record_decision` at entry,
`record_conviction` with `p̂` as the confidence reading, Brier-scored at settlement — the
conviction book (H5) machinery grades the scanner's probability models with zero new
calibration code.

### L3 — Venue basis (Phase 3, observation-gated)

`basis = price_predict − price_kalshi_mid`, fee-adjusted. On a brand-new retail platform the
plausible edges are quote staleness (Predict lags the Kalshi book during fast markets — data
prints, Fed days) and any display rounding to whole cents in CAD. Not executable as two-leg
arb; useful as **entry-timing signal** for L1/L2 executions ("Kalshi already moved, Predict
hasn't — your WS fill will be at the stale price, for or against you"). Requires a Predict-side
price feed → Phase 3 only.

---

## 3. The friction model (first-class, config-driven)

```json
"predict_arb_monitor": {
  "_comment": "WS Predict arb scanner. Fee fields are PLACEHOLDERS until launch — calibrate from first real fills. All thresholds net-of-friction.",
  "fees": {
    "ws_commission_per_contract": 0.02,
    "kalshi_taker_fee_formula": "ceil_cents(0.07 * P * (1-P))",
    "clearing_fee_per_contract": 0.00,
    "fx_spread_oneway": 0.015,
    "fx_applies": true
  },
  "theta_struct": 0.01,
  "theta_value": 0.05,
  "min_book_depth_usd": 500,
  "max_days_to_settlement": 120,
  "scan_interval_s": 60,
  "fast_scan_families": ["CPI", "FED", "GDP"],
  "fast_scan_interval_s": 5
}
```

Notes: Kalshi's published taker-fee formula is ~7% of `P(1−P)` per contract (worst case ~1.75¢
at P=0.5) — verify against current schedule at build time. FX is the sleeper: if Predict
converts CAD↔USD per trade at a ~1.5% corridor, a 3% round-trip erases nearly every structural
arb — in which case the scanner's honest output is "L1 is dead on this venue, L2 only," and
*knowing that with numbers* is itself the deliverable. Depth gate: an "arb" you can't fill at
displayed size isn't one; profit is computed by walking the book, not from top-of-book.

---

## 4. Architecture — following the grain of the codebase

Exactly the `divergence_monitor` pattern (pure tested helper → thin engine consumer → MCP →
TUI), plus one new fetch worker. The engine stays the single source of truth; deterministic
fetch/parse lives engine-side; agents only interpret.

```
kalshi_client.py           NEW  pure stdlib HTTP client for the public market-data API
                                (markets, events, orderbook, trades). Rate-limited, cached,
                                no auth, no order endpoints — read-only by construction.
predict_arb_monitor.py     NEW  the pure brain: constraint-graph builder (partitions/ladders/
                                calendars from event metadata), L1 sweep, L2 edge calc,
                                friction model, book-walking fill simulator.
                                Exports DEFAULT_PREDICT_ARB_CONFIG, PREDICT_ARB_GLOSSARY,
                                predict_arb_tooltip, assess(), assess_book(), select_fresh().
                                Stdlib only, never raises on thin input,
                                monitor_protocol.merged_config for config.
prob_models/               NEW  one small pure module per L2 family (options_implied.py,
                                rates_implied.py, nowcast.py, climatology.py) — each takes
                                cached inputs, returns (p_hat, uncertainty_band, provenance).
engine.py                  MOD  _predict_worker in start_background_tasks (own cadence,
                                writes state_cache["predict_markets"]); in the eval loop:
                                terminal_state["predict_arb"] = assessment, then
                                _fire_predict_arb() — the _fire_divergence twin
                                (select_fresh dedup → record_annotation pin + Living
                                Memory sentinel entry, tags ["sentinel","predict_arb",lane]).
engine_api.py              MOD  GET /predict (state slice) — ~5 lines.
mcp_server/core.py         MOD  predict_scan() (on-demand sweep, returns ranked opps),
                                predict_opportunities() (current state), predict_fair_value
                                (ticker) (L2 decomposition for one contract).
mcp_server/server.py       MOD  three names appended to _PASSTHROUGH_TOOLS.
cockpit_widgets.py         MOD  pure markup builder for the opportunity table.
commodityex_tui.py         MOD  Collapsible "PREDICT ⚡" card first (cheap); promote to a
                                BlendSurface tab if the lane earns it.
v5_config.json             MOD  the predict_arb_monitor block (§3); thresholds allowlisted
                                in dynamic_config.ALLOWLIST → cockpit-tunable, propose/confirm-gated.
data/predict_universe.json NEW  cached contract/event metadata + constraint graph.
data/predict_ledger.jsonl  NEW  append-only: every alert with full pricing context at fire
                                time — the scanner's own track record, replay-gradeable.
tests/                     NEW  test_predict_arb_monitor.py (pure math: parity, partitions,
                                monotonicity, fee netting, book-walking — synthetic books),
                                test_predict_arb_engine_wiring.py (make_engine_stub: pin +
                                LM entry + dedup), test_kalshi_client.py (parsing, canned
                                fixtures, no live network).
```

**Notification path** (no push exists in the terminal today, and Predict arbs are perishable):
tier 1 = the standard pin/Living-Memory/Signals-rail path, always on. Tier 2 (worth it for L1,
which decays in minutes): a `notify_command` config hook — the engine shells a user-supplied
command (e.g. `ntfy.sh`/webhook) on `severity ≥ high` alerts. Off by default, additive, and the
only genuinely new notification machinery in the plan.

**Agent layer** (thin, later): a `@predict-verifier` pass that sanity-checks an L2 alert's
`p̂` provenance before the operator acts — same disconfirmation discipline as the gauntlet.
No council, no per-name resource scouting — this is a lane like `counterweight`, kept thin.

**Context-aware by default:** the constraint-graph builder and the L2 model router key off the
contract family (econ print vs index threshold vs climate) exactly the way
`divergence_monitor.explain_context` keys off archetype — a pure `family → (model, peers,
cadence, thresholds)` helper, unit-tested, so a CPI-ladder rule never fires on a hurricane
contract.

---

## 5. Phased roadmap (each phase ships something usable alone)

**Phase 0 — now, before Predict launches. Kalshi-only scanner.** `kalshi_client` +
`predict_arb_monitor` L1 + config + tests + `predict_scan` MCP tool. Universe filtered to the
CIRO categories (econ/financial/climate, ≥30d settlement) so it *is* the future Predict
universe. Deliverable: the terminal shows live structural opportunities and — critically —
measures how often they exist and at what size, with fees at zero (pure Kalshi baseline).
This answers "is there anything here?" with data before you can even trade.

**Phase 1 — L2 probability models.** `prob_models/` one family at a time, starting where the
terminal already has the data: index thresholds via FMP options, then rates via OIS. Alerts
flow to the conviction book. Deliverable: a ranked value board with model provenance per line.

**Phase 2 — launch day.** You get access; first fills calibrate the fee model (commission, FX,
order types) — a 30-minute config edit, gated on real numbers like the WS assessment's schema
gate. L1 thresholds go from "Kalshi baseline" to "net of WS frictions"; the scanner's verdict
on whether structural arb survives the fee stack is now empirical.

**Phase 3 — optional, opt-in: Predict-side observation.** Only now touch the unofficial
surface, and read-only: capture the Predict app's own API traffic (likely the WS GraphQL
gateway or a dedicated service — discover from your own session), price-poll only, no
trade-capable scopes if separable. Enables L3 staleness/basis measurement. Inherits every
caveat from `WS_INTEGRATION_ASSESSMENT.md`: ToS risk, breaks without notice, fallback-tier,
**never auto-trade** — the scanner alerts, the operator executes in the app, always.

**Phase 4 — flywheel closure.** Settled contracts auto-grade (Kalshi publishes resolution):
Brier score per model family per lane, `replay_grade`-style, from `predict_ledger.jsonl`.
The scanner learns which of its models deserve trust — the same expectancy-first discipline
as the book.

---

## 6. Risks & discipline

- **No auto-execution, ever.** Read-only by construction (`kalshi_client` has no order
  endpoints; Phase 3 explicitly excludes trade scopes). Alerts → human executes in-app.
- **ToS / unofficial-API exposure is confined to Phase 3** and optional. Phases 0–2 use only
  official public Kalshi data. This is the plan's core risk-inversion.
- **Fees may kill L1.** Likely, even. The scanner is built to prove it either way; L2 is the
  durable lane and works regardless.
- **30-day settlement floor** = slow capital velocity on L2 value bets; Kelly caps + the
  posture dial (SPEAR EXPLOIT/BALANCED/DEFENSIVE composes onto sizing) keep it small. This
  book is a satellite lane, never competing with the barbell for weight.
- **Model risk on L2**: risk-neutral ≠ real-world probability (variance risk premium biases
  options-implied `p̂`); haircuts + uncertainty bands + Brier feedback are the containment.
- **CIRO category set may shift** (WS says it will engage regulators to expand) — the universe
  filter is config, not code.

## 7. Definition of done (Phase 0)

- `python -m unittest` green including the three new suites; no live network in tests.
- Engine boots with the worker; kill the network → `DEGRADED_WORKER_DOWN` surfaces, scanner
  degrades to stale-cache with staleness stamped, never crashes the loop.
- `predict_scan` returns a ranked, fee-netted, depth-gated opportunity list over the CIRO
  universe; every fire leaves a pin + Living Memory entry + ledger line.
- A week of ledger data answers: how many L1 violations/day, median size, median lifetime.

---
*Sources: [WS newsroom](https://newsroom.wealthsimple.com/wealthsimple-to-launch-prediction-markets-trading-app) · [BetaKit](https://betakit.com/wealthsimple-launches-prediction-markets-app-through-us-exchange-kalshi/) · [Globe and Mail](https://www.theglobeandmail.com/investing/personal-finance/article-wealthsimple-kalshi-partnership-prediction-markets/) · [CBC](https://www.cbc.ca/news/business/prediction-markets-wealthsimple-9.7239575) · [Kalshi API docs](https://docs.kalshi.com/api-reference/market/get-market-orderbook) · [ws-api-python](https://github.com/gboudreau/ws-api-python) · [wealthsimple-python](https://github.com/henryhuangh/wealthsimple-python)*
