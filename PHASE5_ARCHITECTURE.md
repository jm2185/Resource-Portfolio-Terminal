# Phase 5 — The Polymorphic Archetype Factory
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
backend can value *any* asset in the book, routed **strictly by its cash-flow
lifecycle**, not by GICS sector.

The deliverable is three things plus the CrowdEx-heritage architecture grafted onto them:

1. **`AssetArchetype(ABC)`** — an abstract base enforcing the three-leg triangulation
   (Cost / Market / Income, all CAD), a 0–4 forensic sieve, graceful degradation, a
   uniform FX hook, the Regime Impact Vector, an insider/conviction overlay, and a
   standardized `valuation_summary()`.
2. **Five concrete archetypes** spanning the cash-flow lifecycle.
3. **`PolymorphicRouter`** — a fail-fast, **metadata-driven** registry with explicit
   ticker mappings **and** tag-/score-threshold routing, **historical lifecycle
   versioning**, and a correlation-grouping foundation for future cross-archetype sizing.

**Design constraint honored throughout:** *no double-counting.* Each economic source
enters exactly one leg; the discretionary macro overlay (the Regime Impact Vector) is
applied **once**, to a single designated leg per archetype; and the conviction overlay
is kept **out** of the intrinsic (it is a sizing signal).

**Anchor test bench.** `build_default_router(config)` wires the live **60/15/15/10
barbell** straight from `portfolio_metadata`: AGA.V as the Option Convexity spear, with
royalty (URC.TO, GROY) and cyclical-developer (GMX.TO) ballast — zero regression on the
existing book, with clean extensibility for new sectors.

---

## 1. Why "cash-flow lifecycle", not sector

A silver royalty (GROY), a silver developer (GMX.TO), and a silver explorer (AGA.V) are
all "silver" by sector, yet they are **valued by completely different machinery**: a
royalty is a discounted stream, a developer is a spot-margin business with a build
option, an explorer is a call on a discovery. Routing by sector forces one valuation
path onto three incompatible cash-flow shapes. Routing by **lifecycle** makes the
valuation method a property of *how the asset turns inputs into cash*, which is what
determines whether Cost, Market, or Income should carry the weight.

| # | Archetype | Cash-flow lifecycle | Dominant leg | Anchor |
|---|-----------|---------------------|--------------|--------|
| **I** | `option_convexity` | Pre-revenue / binary-outcome | Market (× `1+π_opt`) | AGA.V |
| **II** | `capital_margin` | Capital-intensive operating (regulated/**defense toggle**) | Income (EPV) | infra / primes |
| **III** | `commodity_cyclical` | Spot-price-dominated margin | Income (spot margin) | GMX.TO |
| **IV** | `asset_light_yield` | High-margin recurring cash flow | Income (stream NAV) | URC.TO, GROY |
| **V** | `pure_macro_delta` | Passive vehicle, no operations | Market (spot delta) | PSLV / futures |

---

## 2. CrowdEx heritage (architectural injection)

The strongest legacy CrowdEx patterns are carried forward as first-class architecture:

* **Metadata-driven archetype DNA** (the old `STOCK_CLASSES` idea). Each archetype is
  declared as an immutable `ArchetypeDNA` in the `ARCHETYPE_DNA` registry — its code
  (I–V), RegimeImpactVector slot, regime tilt leg, base leg weights, per-leg confidence
  priors, routing `tags`, and `risk_factor_tags`. Behaviour reads its DNA; adding a
  sector is "declare DNA + implement four methods".
* **Tag- / score-threshold routing** in the router (see §5): an asset with no explicit
  ticker mapping still routes by the tags or the metric thresholds in its payload.
* **Advanced pre-revenue scoring primitives** on the ABC, shared by the sieves:
  `runway_months`, `cash_burn_acceleration`, and `dilution_velocity` (annualized QoQ).
* **Insider-sentiment / conviction engine** — `calculate_conviction(signals)` returns a
  bounded `[0,1]` score (0.5 neutral) from insider buying, catalyst momentum,
  institutional flow, and short-interest pressure. It is a **sizing** overlay surfaced in
  `valuation_summary`, deliberately **excluded from the intrinsic** to avoid
  double-counting with the forensic penalty and the regime overlay.
* **Correlation foundations** — `risk_factor_exposure()` emits per-archetype loadings on
  shared risk factors (e.g. `silver_beta`, `rates_duration`); the router groups tickers
  by factor (`correlation_groups()`) — the seed for a future cross-archetype sizer.

---

## 3. The `AssetArchetype` contract

Every archetype binds `DNA` to one of `ARCHETYPE_DNA` and **must** implement:

```python
calculate_cost_basis(data: dict) -> float                          # CAD floor / replacement
calculate_market_basis(data: dict, comps: dict) -> float           # CAD comparables
calculate_income_basis(data: dict, regime_vector: tuple) -> float  # CAD DCF / NAV
calculate_forensic_score(financials: dict) -> float                # 0.0–4.0 sieve
```

The base supplies the shared, non-negotiable machinery:

* **Three-leg triangulation in CAD.** Each leg returns CAD (post-FX). The blend is
  **confidence-tilted**: `w_i = (W_i · c_i) / Σ_j(W_j · c_j)`. A leg the data can't
  support gets `c_i = 0` and is renormalized out (weight flows to the trustworthy legs).
* **Uniform FX hook** (`normalize_fx`, base = CAD); unknown currency degrades to ×1.0.
* **Graceful degradation.** A leg lacking inputs raises `SparseDataError`;
  `valuation_summary` catches it, zeroes confidence, records a warning, and reports
  `data_quality ∈ {full, degraded, sparse}` — judged only over legs the archetype
  *expects* live (non-zero base weight), so an explorer's zero income leg never reads
  "degraded".
* **Forensic sieve → penalty.** 0–4 score (missing tests excluded and rescaled; neutral
  2.5 when nothing is determinable) → a `[0.70, 1.0]` haircut applied **once**, to the
  *blended* intrinsic.
* **`valuation_summary()`** returns the standardized dict: blended intrinsic, three legs,
  base & tilted weights, forensic score + penalty, **conviction**, **tags**,
  **risk_factor_exposure**, the regime overlay applied, a per-leg `component_breakdown`,
  `data_quality`, and `warnings`. Pure-JSON-serializable.

### 3.1 Mathematical consistency with Phase 4a

`archetypes.py` is **pure-Python and dependency-free** (no numpy / yfinance), so it runs
anywhere — including environments where the live engine's heavy deps are absent. To avoid
drift, the shared primitives are **faithful replicas** of the audited `ValuationEngine`
methods: `technical_quality` ↔ `calculate_technical_quality`, `option_premium` ↔
`calculate_option_premium`, `capital_discount_factor` ↔ `calculate_capital_discount_factor`,
`spot_linked_fair_value` ↔ `calculate_ballast_fair_value`, and Option-Convexity cost/market
↔ `calculate_rep_floor` + `calculate_spear_intrinsic`. At the live operating point the
Option-Convexity **cost leg reproduces the REP floor to \$0.824/share**.

---

## 4. The Regime Impact Vector (Druckenmiller macro-asymmetry)

```python
RegimeImpactVector = Tuple[float, float, float, float, float]
# (alpha_option, alpha_margin, alpha_cyclical, alpha_yield, alpha_delta) — maps 1:1 to I..V
```

One discretionary coefficient per archetype, clamped to `[-1, 1]`. `alpha > 0` = the
regime is a tailwind for that lifecycle (lean in); `alpha < 0` = headwind (fade). Each
archetype reads **its own** coefficient (`DNA.regime_index`) and tilts **exactly one leg**
(`DNA.regime_tilt_leg`) by `clamp(1 + sensitivity·alpha, 0.5, 1.5)`.

| Archetype | alpha | Tilt leg | Why |
|-----------|-------|----------|-----|
| I. Option Convexity | `alpha_option` | **market** | amplify/fade the convexity lift `(1+π_opt)` |
| II. Capital Margin | `alpha_margin` | **income** | rate-sensitive earnings-power value |
| III. Commodity Cyclical | `alpha_cyclical` | **income** | spot-margin cyclicality |
| IV. Asset-Light Yield | `alpha_yield` | **income** | discount-rate sensitivity of stream NAV |
| V. Pure Macro Delta | `alpha_delta` | **market** | the pure directional spot bet |

**No double-counting.** The overlay is a *discretionary* macro tilt distinct from the
*mechanical* signals already inside the legs (e.g. `π_opt` already prices live vol/carry).
Income-tilted archetypes apply it inside their income leg; market-tilted ones have it
applied in `valuation_summary`, where it is surfaced (`regime_alpha`, `regime_multiplier`,
`regime_tilt_leg`) for audit.

---

## 5. `PolymorphicRouter` — metadata-driven, fail-fast, versioned

```python
router.register_archetype_class(name, cls)                      # plug a concrete class in
router.register_asset(ticker, archetype, *, effective=None, label="")
router.register_tag_rule(tag, archetype_name, *, priority=0)    # tag-based routing
router.register_score_rule(metric, low, high, archetype_name, *, priority=0)  # score-threshold
router.resolve(ticker, data_payload=None, *, as_of=None) -> AssetArchetype
router.get_valuation(ticker, data_payload, regime_vector, *, as_of=None) -> dict
router.migrate_asset(ticker, archetype, effective, label="")    # later lifecycle version
router.lifecycle_history(ticker) -> list ;  router.correlation_groups() -> dict
```

* **Resolution precedence:** (1) explicit ticker mapping (lifecycle-versioned), else
  (2) tag rules (payload `tags` ∩ rule tag, by priority), else (3) score-threshold rules
  (payload metric within band), else **`TickerNotRegisteredError`** — never a silent zero.
* **Lifecycle versioning.** Re-registering at a later `effective` date appends a
  **timeline**; `resolve(…, as_of=date)` returns the archetype in force then (AGA.V
  graduates `option_convexity → commodity_cyclical` as it builds and produces).
* **Correlation foundation.** `correlation_groups()` buckets registered tickers by shared
  `risk_factor_tags` — the seed for the future cross-archetype sizing layer.

### 5.1 `build_default_router(config)` — routing precedence per name

1. explicit `portfolio_metadata[ticker].archetype`, else
2. the `archetype_routing` map (type → archetype, also registered as tag rules), else
3. the built-in `ARCHETYPE_BY_TYPE` fallback. An unknown type is **skipped explicitly**.

---

## 6. Config schema additions (additive; legacy config untouched)

All keys optional — the module falls back to in-code defaults, so the existing engine and
tests are unaffected.

```jsonc
"portfolio_metadata": { "AGA.V": { …, "archetype": "option_convexity" }, … },
"archetype_routing":  { "explorer": "option_convexity", "developer": "commodity_cyclical",
  "royalty": "asset_light_yield", "infrastructure": "capital_margin", "trust": "pure_macro_delta", … },
"archetype_factory": {
  "base_currency": "CAD", "usd_to_cad_fallback": 1.38, "forensic_neutral_default": 2.5,
  "regime": { "sensitivity_default": 0.5, "mult_floor": 0.5, "mult_ceiling": 1.5 },
  "weights": { "<archetype>": {cost,market,income}, … },
  "confidence": { "<archetype>": {cost,market,income}, … },
  "capital_margin":     { "wacc": 0.10, "terminal_growth": 0.02, "defense_moat_premium": 0.15 },
  "commodity_cyclical": { "cost_floor_frac": 0.45, "margin_capitalization_years": 6.0, "default_spot_beta": 1.35 },
  "asset_light_yield":  { "default_discount": 0.09, "default_growth": 0.02, "default_risk": 0.85, "cost_floor_frac": 0.10 },
  "pure_macro_delta":   { "fee_drag_annual": 0.004 }
}
```

---

## 7. Tests & validation

`test_archetypes.py` (pure-stdlib `unittest`, **42 tests, all green**) covers: the abstract
contract + DNA registry (codes I–V, unique regime indices, base weights sum to 1); each
archetype's legs + forensic sieve incl. the REP-floor reconciliation (`cost ≈ $0.824`) and
`cost ≤ blended ≤ market`; **FX** (USD name = CAD twin × 1.38); **graceful degradation**;
the **regime overlay** (right index, clamped, single-leg, single application);
**conviction** (bounded, directional, surfaced but *not* in the intrinsic); the **forensic**
0–4 scale + penalty mapping; helper **parity** + the pre-revenue primitives; the **router**
(fail-fast, tag routing, score-threshold routing, ticker-mapping precedence, lifecycle
versioning); and the **anchor 60/15/15/10 bench** (every name routes, values positive,
weights sum to 1, JSON-serializable) plus **correlation groups** and normalized risk-factor
exposure.

---

## 8. Orchestrator integration (Phase 5b — implemented, additive)

The factory is now bridged into the live `CommodityExMonitor` **purely additively** — the
legacy valuation path (`valuation_detail`, `v4_valuation`) is untouched and runs unchanged in
parallel:

* **At init:** `self.config = load_config(self.config_path)` and
  `self.archetype_router = build_default_router(self.config)`, wrapped in `try/except` so a
  config/router problem can never block startup.
* **Three helpers** on the monitor: `_build_regime_impact_vector(mri, real_yield, silver_vol,
  dxy_mom)` translates the live MRI/yield/vol/USD state into the 5 alphas (clamped `[-1,1]`,
  risk-on ⇒ positive, stress ⇒ negative); `_archetype_payload(...)` assembles each name's
  payload from live state (the spear gets the live peer comp + dynamic AISC; ballast names read
  ref/spot/currency from config); `_compute_archetype_valuations(...)` pushes the **live**
  USD→CAD onto each instance, loops the registered tickers, and rolls the per-name intrinsics
  into the **60/15/15/10** book figure.
* **In the eval loop:** right after `valuation_detail`, the result is stored at
  `terminal_state["archetype_valuation_detail"]` (regime vector, per-name `results`, the
  `barbell` CAD blend, and `correlation_groups`). The whole block is isolated in `try/except`
  and per-ticker `TickerNotRegisteredError`/exception capture, so it can **never** crash the
  loop; income-leg-sparse ballast names degrade gracefully (cost+market still value them in CAD).

`archetype_valuation_detail` is **optional/supplementary** — the cockpit reads it when present.
The Regime Impact Vector and `archetype_factory.*` / `archetype_barbell_weights` config remain
the home for the Druckenmiller macro-asymmetry philosophy as it is refined; the valuation legs
never need to change. Wiring this block through to the Flutter frontend is the next gated step.
