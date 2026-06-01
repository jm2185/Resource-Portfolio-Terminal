# Phase 5 — Polymorphic Archetype Factory
### Multi-sector thematic investment OS · routing by cash-flow lifecycle
*CommodityEx Quant Monitor v5.3 · Chief Valuation Architect · 2026-06-01*

> **Status: SHIPPED as an additive, self-contained module (`archetypes.py`).**
> No live `engine.py` path is rewired by this change — the factory is a parallel,
> independently-tested valuation layer the orchestrator can adopt incrementally.
> Everything here is revertible (new file + additive config keys on a feature branch).

---

## 0. Executive Summary

Phase 4 hardened the valuation math for a **single** asset class — the AGA.V silver
explorer — behind a stage-aware, de-overlapped, triangulated intrinsic. Phase 5
generalizes that exact discipline into a **Polymorphic Archetype Factory** so the
backend can value *any* asset in the book, and route each one **strictly by its
cash-flow lifecycle**, not by GICS sector.

The deliverable is three things:

1. **`AssetArchetype(ABC)`** — an abstract base enforcing the same three-leg
   triangulation (Cost / Market / Income, all in CAD), a 0–4 forensic sieve,
   graceful degradation, a uniform FX hook, the Regime Impact Vector, and a
   standardized `valuation_summary()`.
2. **Five concrete archetypes** spanning the cash-flow lifecycle.
3. **`PolymorphicRouter`** — a fail-fast `ticker → archetype` registry with
   **historical lifecycle versioning** (an asset can graduate across archetypes
   as it matures).

**Design constraint honored throughout:** *no double-counting.* Each economic
source enters exactly one leg, and the discretionary macro overlay (the Regime
Impact Vector) is applied **once**, to a single designated leg per archetype.

**Anchor test bench.** `build_default_router(config)` wires the live
**60/15/15/10 barbell** straight from `portfolio_metadata`: AGA.V as the Option
Convexity spear, with royalty (URC.TO, GROY) and cyclical-developer (GMX.TO)
ballast. The factory is therefore immediately exercisable against the real book.

---

## 1. Why "cash-flow lifecycle", not sector

A silver royalty (GROY), a silver developer (GMX.TO), and a silver explorer
(AGA.V) are all "silver" by sector, yet they are **valued by completely different
machinery**: a royalty is a discounted stream, a developer is a spot-margin
business with a build option, an explorer is a call on a discovery. Routing by
sector would force one valuation path onto three incompatible cash-flow shapes —
exactly the "ounces are fungible" error Phase 4 spent its effort eliminating.

Routing by **lifecycle** makes the valuation method a property of *how the asset
turns inputs into cash*, which is what actually determines which of Cost / Market
/ Income should carry the weight.

| # | Archetype | Cash-flow lifecycle | Dominant leg | Anchor example |
|---|-----------|---------------------|--------------|----------------|
| **I** | `option_convexity` | Pre-revenue / binary-outcome | Market (× `1+π_opt`) | AGA.V explorer |
| **II** | `capital_margin` | Capital-intensive operating business (regulated infra / **defense toggle**) | Income (EPV) | utilities / primes |
| **III** | `commodity_cyclical` | Spot-price-dominated margin business | Income (spot margin) | GMX.TO |
| **IV** | `asset_light_yield` | High-margin recurring cash flow | Income (stream NAV) | URC.TO, GROY |
| **V** | `pure_macro_delta` | Passive commodity vehicle, no operations | Market (spot delta) | PSLV / futures |

---

## 2. The `AssetArchetype` contract

Every archetype inherits from `AssetArchetype(ABC)` and **must** implement:

```python
calculate_cost_basis(data: dict) -> float                       # CAD floor / replacement
calculate_market_basis(data: dict, comps: dict) -> float        # CAD comparables
calculate_income_basis(data: dict, regime_vector: tuple) -> float  # CAD DCF / NAV
calculate_forensic_score(financials: dict) -> float             # 0.0–4.0 sieve
```

The base class supplies the shared, non-negotiable machinery so every archetype
behaves identically where it must:

* **Three-leg triangulation in CAD.** Each leg returns a CAD figure (post-FX).
  The blend is **confidence-tilted**, reusing the Phase 4a formula
  `w_i = (W_i · c_i) / Σ_j(W_j · c_j)`: a leg the data can't support gets
  `c_i = 0` and is renormalized out, so weight flows to the legs that *can* be
  trusted (e.g. an explorer with stale comps leans on its cost floor).
* **Uniform FX normalization hook** (`normalize_fx`, base = CAD). Every leg passes
  through it; an unknown currency degrades to ×1.0 rather than raising. This is
  the single guarantee that all outputs are CAD — crucial for GROY (USD) sitting
  in a CAD book.
* **Graceful degradation.** A leg that lacks its inputs raises `SparseDataError`
  internally; `valuation_summary` catches it, zeroes that leg's confidence, and
  records a warning. `data_quality ∈ {full, degraded, sparse}` reports the result
  — judged only over legs the archetype *expects* to be live (non-zero base
  weight), so an explorer's intentionally-zero income leg never reads as
  "degraded".
* **Forensic sieve → penalty.** `calculate_forensic_score` returns a 0–4 score
  (4 named pass/fail tests; missing tests are excluded and the score rescaled,
  defaulting to a neutral 2.5 when nothing is determinable). `forensic_penalty`
  maps it to a `[0.70, 1.0]` haircut (`0.70 + 0.30·score/4`, cf. ENGINE_DESIGN
  §2.2) applied **once**, to the *blended* intrinsic — never buried in a leg.
* **`valuation_summary()`** returns the standardized dict: blended intrinsic,
  the three legs, base & confidence-tilted weights, forensic score + penalty,
  the regime overlay actually applied, a per-leg `component_breakdown`, and
  `data_quality` + `warnings`. It is pure-JSON-serializable (no numpy / dates).

### 2.1 Mathematical consistency with Phase 4a

`archetypes.py` is **pure-Python and dependency-free** (no numpy / yfinance), so
it runs anywhere — including environments where the live engine's heavy deps are
absent. To avoid math drift, the shared primitives are **faithful replicas** of
the audited `ValuationEngine` methods, cross-referenced at each call site:

| Factory helper | Mirrors `ValuationEngine.` |
|----------------|----------------------------|
| `technical_quality()` | `calculate_technical_quality` |
| `option_premium()` | `calculate_option_premium` |
| `capital_discount_factor()` | `calculate_capital_discount_factor` |
| `spot_linked_fair_value()` | `calculate_ballast_fair_value` |
| `OptionConvexityArchetype` cost/market | `calculate_rep_floor` + `calculate_spear_intrinsic` |

At the live operating point (peer EV/oz ≈ \$2.08, spot Ag \$75.6, y30 4.99) the
Option-Convexity **cost leg reproduces the REP floor to \$0.824/share** and the
triangulated blend lands in the Phase 4a band — the factory is the Phase 4a spear,
generalized.

---

## 3. The Regime Impact Vector (Druckenmiller macro-asymmetry)

```python
RegimeImpactVector = tuple[float, float, float, float, float]
# (alpha_option, alpha_margin, alpha_cyclical, alpha_yield, alpha_delta)
```

One discretionary coefficient per archetype, in roughly `[-1, +1]` (clamped). It
encodes the strategist's *macro asymmetry view*: `alpha > 0` means the regime is a
tailwind for that lifecycle (lean in), `alpha < 0` a headwind (fade). Each
archetype reads **its own** coefficient (`REGIME_INDEX`) and tilts **exactly one
leg** (`REGIME_TILT_LEG`) by a bounded multiplier:

```
regime_multiplier = clamp(1 + sensitivity · alpha,  mult_floor,  mult_ceiling)   # default [0.5, 1.5]
```

| Archetype | `alpha` read | Tilt leg | Rationale |
|-----------|--------------|----------|-----------|
| I. Option Convexity | `alpha_option` (0) | **market** | amplify/fade the convexity lift `(1+π_opt)` |
| II. Capital Margin | `alpha_margin` (1) | **income** | rate-sensitive earnings-power value |
| III. Commodity Cyclical | `alpha_cyclical` (2) | **income** | spot-margin cyclicality |
| IV. Asset-Light Yield | `alpha_yield` (3) | **income** | discount-rate sensitivity of stream NAV |
| V. Pure Macro Delta | `alpha_delta` (4) | **market** | the pure directional spot bet |

**No double-counting.** The overlay is a *discretionary* macro tilt distinct from
the *mechanical* signals already inside the legs (e.g. `π_opt` already prices live
vol and carry). It is applied once: income-tilted archetypes apply it inside their
income leg; market-tilted archetypes have it applied in `valuation_summary`, where
it is reported (`regime_alpha`, `regime_multiplier`, `regime_tilt_leg`) for audit.

> This is the macro-asymmetry knob the brief flagged as "still needs refining."
> It is deliberately **bounded, single-application, and fully surfaced** so the
> refinement (which signals feed each alpha, how `sensitivity` is calibrated) can
> happen in config without touching the valuation legs.

---

## 4. Per-archetype valuation map

All legs return **CAD** (post-FX). `comps` carries peer multiples; `data.macro`
carries spot/rates/vol context; `data.financials` feeds the forensic sieve.

### I. Option Convexity — pre-revenue / binary (AGA.V)
* **Cost** — REP floor: treasury + stressed in-situ resource (symmetric Inferred
  haircut) + infra premium, ÷ shares.
* **Market** — quality-graded *defined* ounces × peer EV/oz × capital discount ×
  conservatism, **plus** a once-risked exploration sub-leg, lifted by `(1+π_opt)`.
  `alpha_option` tilts this leg.
* **Income** — `0` by design (no recurring cash flow). Confidence 0 → drops out.
* **Forensic** — explorer sieve: runway / CBA(EV) / dilution / SG&A drag.

### II. Capital Margin — capital-intensive operating (regulated infra / defense)
* **Cost** — `(invested_capital − net_debt)/shares` (or book value/share).
* **Market** — EV/EBITDA comp: `(EBITDA·ev_ebitda − net_debt)/shares` (P/Book fallback).
* **Income** — earnings-power value `FCF/(wacc−g)`. The **defense/regulated toggle**
  (`data.defense_or_regulated`) widens the moat → lower effective discount.
  `alpha_margin` tilts this leg.
* **Forensic** — producer sieve: Sloan CFO/BS + leverage + dilution.

### III. Commodity Cyclical — spot-margin dominated (GMX.TO)
* **Cost** — stressed reserve NAV/share, book, or a conservative fraction of the
  spot-linked NAV (graceful fallback chain; the proxy floor carries lower confidence).
* **Market** — spot-linked fair value `ref × mult × spot_factor` with operating
  `spot_beta` (decoupled from the name's own share price).
* **Income** — spot-margin capitalization: `production × (spot − AISC) × years/shares`.
  `alpha_cyclical` tilts this leg.
* **Forensic** — producer sieve.

### IV. Asset-Light Yield — recurring high-margin cash flow (URC.TO, GROY)
* **Cost** — thin tangible floor (cash/book, or a small fraction of NAV).
* **Market** — P/NAV spot-linked value, `spot_beta ≈ 1` (pass-through). **FX-critical**
  for GROY (USD).
* **Income** — risked perpetuity stream/NSR NAV `cashflow × risk/(discount − growth)`
  — the dominant leg. `alpha_yield` tilts it (falling real yields lift NAV).
* **Forensic** — producer sieve.

### V. Pure Macro Delta — passive vehicle, no operations (trusts, futures)
* **Cost** — NAV anchor (per-unit holdings at the reference frame).
* **Market** — spot delta `nav_ref × (spot/spot_ref) × delta` (pure pass-through).
  `alpha_delta` tilts this leg.
* **Income** — negative carry (management/storage fee drag); informational (weight 0).
* **Forensic** — passive sieve: NAV tracking / fee load / liquidity / backing
  (defaults clean — there are no accruals to examine).

---

## 5. `PolymorphicRouter` + historical lifecycle versioning

```python
router.register_asset(ticker, archetype, *, effective=None, label="")
router.get_valuation(ticker, data_payload, regime_vector, *, comps=None, as_of=None) -> dict
router.resolve(ticker, as_of=None) -> AssetArchetype
router.migrate_asset(ticker, archetype, effective, label="")   # later lifecycle version
router.lifecycle_history(ticker) -> list[dict]
```

* **Fail-fast.** An unregistered ticker raises `TickerNotRegisteredError` — never a
  silent zero. `register_asset` rejects non-`AssetArchetype` instances with
  `ArchetypeConfigError`.
* **Lifecycle versioning.** Re-registering a ticker at a later `effective` date
  appends a **timeline** rather than overwriting. As AGA.V matures explorer →
  producer, it migrates `option_convexity → commodity_cyclical`; `get_valuation(…,
  as_of=date)` resolves the archetype in force on that date (default: latest). This
  is the same infrastructure the Phase 4 doc earmarked for backtesting.

### 5.1 `build_default_router(config)` — routing precedence

For every name in `portfolio_metadata`:
1. explicit `portfolio_metadata[ticker].archetype`, else
2. the `archetype_routing` map (type → archetype), else
3. the built-in `ARCHETYPE_BY_TYPE` fallback.

An unknown type is **skipped explicitly** (never guessed into an archetype).

---

## 6. Config schema additions (additive; legacy config untouched)

All keys are optional — the module falls back to in-code defaults, so the existing
engine and tests are unaffected.

```jsonc
"portfolio_metadata": {
  "AGA.V":  { …, "archetype": "option_convexity" },
  "GROY":   { …, "archetype": "asset_light_yield" },
  "GMX.TO": { …, "archetype": "commodity_cyclical" },
  "URC.TO": { …, "archetype": "asset_light_yield" }
},
"archetype_routing": { "explorer": "option_convexity", "developer": "commodity_cyclical",
  "royalty": "asset_light_yield", "infrastructure": "capital_margin", "trust": "pure_macro_delta", … },
"archetype_factory": {
  "base_currency": "CAD", "usd_to_cad_fallback": 1.38, "forensic_neutral_default": 2.5,
  "regime": { "sensitivity_default": 0.5, "mult_floor": 0.5, "mult_ceiling": 1.5 },
  "weights":    { "<archetype>": { "cost": …, "market": …, "income": … }, … },
  "confidence": { "<archetype>": { "cost": …, "market": …, "income": … }, … },
  "capital_margin":     { "wacc": 0.10, "terminal_growth": 0.02, "defense_moat_premium": 0.15 },
  "commodity_cyclical": { "cost_floor_frac": 0.45, "margin_capitalization_years": 6.0, "default_spot_beta": 1.35 },
  "asset_light_yield":  { "default_discount": 0.09, "default_growth": 0.02, "default_risk": 0.85, "cost_floor_frac": 0.10 },
  "pure_macro_delta":   { "fee_drag_annual": 0.004 }
}
```

---

## 7. Tests & validation

`test_archetypes.py` (pure-stdlib `unittest`, **33 tests, all green**) covers:

* the abstract contract (base un-instantiable; all five implement it; regime
  indices `0..4` unique & complete);
* each archetype's legs + forensic sieve, incl. the REP-floor reconciliation
  (`cost ≈ $0.824`) and `cost ≤ blended ≤ market`;
* **FX**: a USD name equals its CAD twin × 1.38 (the blend is linear in the legs);
* **graceful degradation**: missing comps → market leg drops, blend falls to the
  cost floor; total sparsity → `0.0`, no crash;
* **regime overlay**: alpha read at the right index & clamped; `+alpha` amplifies /
  `−alpha` fades; applied to exactly one leg, once;
* the **forensic** 0–4 scale, neutral default, and `[0.70,1.0]` penalty mapping;
* helper **parity** (TQ monotonic & clamped; `π_opt` vol-sensitive & stage-decaying;
  capital discount ≈ 0.8808 at y30 4.99; spot-linked decoupled from share price);
* the **router** (register, fail-fast, lifecycle versioning + `as_of`); and
* the **anchor 60/15/15/10 bench** wired from config (every name routes, values
  positive, weights sum to 1, JSON-serializable).

---

## 8. Integration path (deliberately incremental)

Per the house guardrail ("engine and UI are never written in the same turn"), this
ships as a **parallel module**, not a live rewire. The orchestrator
(`CommodityExMonitor`) can adopt it incrementally:

1. construct `router = build_default_router(cfg, fx_rates={"USD": usd_to_cad})` once;
2. assemble a `data_payload` per name from the data it already fetches
   (price, shares, `macro`, `comps`, `financials`);
3. call `router.get_valuation(ticker, payload, regime_vector)` and read the
   standardized dict into `terminal_state` as an **additive** `archetype_valuation`
   block — exactly as Phase 4a added `valuation_detail` without breaking the UI.

The Regime Impact Vector is the natural home for the Druckenmiller macro-asymmetry
philosophy as it is refined: tune `archetype_factory.regime.*` and the per-alpha
calibration in config; the valuation legs never need to change.
