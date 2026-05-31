# Phase 4 — Technical / Geological Grounding & Valuation Triangulation
### Architectural Review, Mathematical Specification & Data Schemas
*CommodityEx Quant Monitor v5.2 → v5.3 · Chief Valuation Architect review · 2026-05-31*

> **Status: REVIEW / SPEC ONLY.** No engine or UI code is changed by this document.
> It is the design contract for Phase 4 plus the immediate (Phase 0) structural patches.
> Implementation waits on sign-off. Everything here is revertible (design doc on a feature branch).

---

## 0. Executive Summary

The current valuation is **directionally reasonable but structurally indefensible** in three ways that a
NI 43‑101 QP, a buy‑side resource quant, and a model‑risk validator would each flag on first read:

1. **One leg, one tower of constants.** Reconstructed from the live cached state
   (spot Ag $75.62, peer EV/oz $2.08 CAD, y30 4.98%), the spear intrinsic is **≈ $4.63/share**, and
   **~93% of it is the single IS‑IAI (market) leg**. That leg is `peer_ev × discovery_premium_factor
   (≈3.28×) × jurisdiction_uplift (≈1.35×) × recovery × capital_discount`. Almost the entire valuation
   rides on a stack of multiplicative magic numbers.

2. **Mislabeled / double‑counted optionality.** `discovery_premium_factor` reduces algebraically to
   `1.68 × (spot − AISC)/AISC` — i.e. an **operating‑leverage / moneyness** term, *not* a discovery term —
   embedded multiplicatively inside the market leg. Meanwhile **ROV** (the *named* optionality metric)
   is **dimensionally incoherent** (a `1.21×` multiplier is *added* as if it were $0.18/share) **and
   effectively dead** (its only live driver, negative real yield, is off; its vol input is hardcoded).
   So silver/operating‑leverage convexity is counted **twice** (once live as the discovery multiple,
   once dead as ROV) — exactly the double‑count the brief warns against.

3. **Ounces are fungible.** There is no Technical‑Quality framework. `jurisdiction_uplift` is a function
   of **silver price**, not jurisdiction; the real `fraser_index` (AGA.V = 84.2) is **never read**.
   Gold recovery is in config but **dropped** (only `rec_silver` is applied to AgEq ounces). Grade,
   depth, metallurgy, and infrastructure are absent. A top‑tier Nevada ounce and a high‑risk‑jurisdiction
   ounce are valued identically.

Phase 4 replaces the multiplier tower with a **stage‑aware, triangulated (Cost + Market + Income/Option)
valuation**, a **transparent Technical‑Quality (TQ) multiplier**, a **strict de‑overlap** of the three
upside channels, a **base/bull/bear scenario range**, and a **single margin‑of‑safety ledger**. The
headline number **will move** (the current one is inflated by an undocumented ≈3.3× embedded multiple);
that movement is the point — it buys defensibility.

---

## PHASE 0 — Mandatory Structural Patches (apply first, as one focused commit)

These are pre‑Phase‑4, surgical, and independently testable. Specs below are implementation‑ready.

### 0.1 ADV pro‑cyclicality trap → 90‑day robust volume
**Where:** `PortfolioSizer.get_liquidity_cap` (engine.py ~1193‑1202, uses `averageVolume10Day`) **and**
`PeerEngine.fetch_and_calculate_weighted_comps` (engine.py ~429, same field for peer liquidity weights).

**Problem:** 10‑day ADV *spikes* during panics, so the dollar liquidity cap **expands exactly when risk
should contract** — pro‑cyclical, backwards.

**Fix:** denominate the cap on a **90‑session median of daily dollar volume** (robust to spikes), with an
EWMA(halflife≈30d) alternative behind a config switch. Median is primary because a single panic day
cannot move a 90‑point median.

```
hist            = yf.Ticker(t).history(period="130d")          # ~90 sessions + buffer
dollar_vol_t    = hist['Volume'] * hist['Close']               # $ traded per session
adv_robust      = median( dollar_vol_t.tail(adv_window_days) ) # default 90
# share-equivalent ADV (engine multiplies by price downstream): adv_shares = adv_robust / price_now
```
Fallback chain: robust(90d) → `averageVolume` (3‑mo) → `averageVolume10Day` → fixed fallback. Apply in
**both** call sites so peer liquidity weights are de‑spiked too.

**Config (`v5_guardrails`):** `"adv_window_days": 90, "adv_method": "median"` (`"median" | "ewma"`,
`"adv_ewma_halflife_days": 30`).

**Test:** inject a 10× volume spike on the last 5 sessions → cap rises < 5% (median) vs ~+100% (10‑day).

---

### 0.2 CBA "lean treasury" bias → normalize by Enterprise Value
**Where:** `ForensicEngine.calculate_jsf_score`, explorer branch (engine.py ~734‑739).

**Problem:** `CBA = (curr_burn − prev_burn) / Total Cash` punishes micro‑caps that *deliberately* run a
lean treasury — a smaller denominator inflates the ratio and trips the burn‑acceleration gate on healthy
companies.

**Fix:** denominate against **Enterprise Value** (preferred) or market cap — a size proxy that does not
reward hoarding cash.
```
EV  = market_cap + total_debt − cash        # from yfinance info.enterpriseValue; fallback market_cap
CBA = (curr_burn − prev_burn) / max(EV_floor, EV)
```
**Recalibrate the threshold.** EV ≫ cash, so the same dollar acceleration yields a much smaller ratio.
Move the gate from `0.15` (fraction of cash) to a config‑driven EV fraction — **proposed `0.03`** — to be
finalized against the live AGA.V EV at implementation. Surface both the old (cash‑based, informational)
and new (EV‑based, governing) CBA so the change is auditable.

**Config (`forensic_thresholds`):** `"cba_denominator": "enterprise_value", "max_burn_acceleration_ev_pct": 0.03, "cba_ev_floor": 5_000_000`.

---

### 0.3 Static MRI bounds (saturated signals) → rolling percentile rank
**Where:** `MacroRegimeEngine.calculate_mri` (engine.py ~336‑358). Even after the v5.2 re‑centering, every
`norm(x, lo, hi)` is **static**, so any component still flat‑lines once price leaves the hard band
(silver pinned at 100, Cu/Au near 0).

**Fix:** replace static min‑max with a **rolling percentile rank** over a trailing window (default 5y) for
the saturating components — ideally all six drivers for consistency:
```
pctile(x | series_5y) = 100 * (count(series ≤ x) / N)
```
Maintain a small trailing series per driver (spot_ag, Cu/Au, DXY, real_yield, VIX, HY spreads, CFTC),
fetched once and cached to `.cache/mri_history.json`, refreshed daily. **Cold start:** if `N < min_obs`
(default 252), fall back to the current static `norm` so the engine never blocks on history. Emit the
percentile alongside each driver so the UI can say *"silver at the 92nd percentile of its 5y range."*

**Config (new `mri_dynamic_bounds`):**
```json
{ "enabled": true, "lookback_years": 5, "min_obs": 252, "refresh_hours": 24,
  "components": ["silver","copper_gold","dxy","real_yield","vix","hy_spread","cftc"],
  "static_fallback": true }
```
**Test:** feed a silver path that crosses the old upper bound → percentile keeps moving (no flat‑line);
with `N < min_obs` the function reproduces today's static output exactly.

> **Cross‑link to Phase 5.** The MRI trailing series built here is the same infrastructure backtesting and
> regime‑stability work will reuse; build it once, cleanly.

---

## 1. Phase 4 Audit Findings (evidence‑backed, severity‑rated)

| # | Severity | Finding | Evidence (live‑state reconstruction) |
|---|----------|---------|--------------------------------------|
| F1 | **High** | **ROV dimensionally incoherent.** A dimensionless multiple (~1.21×) is *added* into a $/share blend (`+0.15·rov`). | Contributes a flat **$0.18/sh (≈4%)**; a "multiplier" masquerading as dollars. |
| F2 | Med | **ROV is dead.** Called without `silver_vol` → vol premium pinned at `(0.25−0.20)·0.5=0.025`; neg‑yield premium = 0 whenever real_yield>1. Doc says VIX‑driven; code says silver_vol. | ROV ≈ 1.18·1.025 = **1.21 constant**; doc/code divergence. |
| F3 | **High** | **"Jurisdiction uplift" is a silver‑price logistic, not jurisdiction.** Real `fraser_index` never read; target asset gets no jurisdiction adjustment. | `calculate_jurisdiction_uplift(spot_ag)`; `fraser_index=84.2` unused in valuation. |
| F4 | **High** | **No Technical‑Quality framework; ounces fungible.** Quality scattered across `mi_pct`, `rec_silver`, a misnamed uplift. **Gold recovery dropped** (only `rec_silver` applied to AgEq). | `rec_gold` present in config, never used. |
| F5 | **High** | **Triple‑counted optionality.** `discovery_premium_factor` = `1.68·(spot−AISC)/AISC` (moneyness) lives in the market leg; ROV (dead) re‑tries it; exploration premium re‑uses the silver‑ramp uplift. | discovery_premium ≈ **3.28×**, the single largest swing in the model. |
| F6 | **High** | **Static blend `0.15/0.70/0.15` ignores stage & confidence.** Same weights for a PEA explorer as would apply to a DFS developer or a royalty. | No stage branch in `ValuationEngine`. |
| F7 | Med | **Ballast = one spot‑linked multiple.** Royalties (GROY, URC) and a developer (GMX) all use `ref_price·base_mult·spot_factor`; no link to reserves, NSR%, NPV. | `calculate_ballast_fair_value`, hardcoded `base_mult` 1.15–1.20. |
| F8 | Med | **Discovery ceiling is ad‑hoc.** `ceiling = 4.2 + 0.90·min(1,spot_dev)·(1−MRI/100)`, `spot_dev=(spot_ag−76.5)/50`. Undocumented constants 76.5, 4.2, 0.90, 50. | — |
| F9 | Low‑Med | **Conservatism applied in scattered places** (0.88 on IS‑IAI, 0.85 on REP, forensic_penalty) with no single visible haircut ledger. | Hard to see total margin of safety. |
| F10 | **High** | **Single point estimate; no range.** No base/bull/bear, no sensitivity. Brief explicitly asks for scenario ranges. | — |

**The structural punchline (F1+F3+F5):** the live valuation is *peer EV/oz × a tower of multipliers*,
and the dominant multiplier is an operating‑leverage/moneyness term mislabeled "discovery," while the
*named* optionality metric is dead. We are not under‑counting silver torque — we are counting it in the
wrong leg, twice, opaquely.

---

## 2. Phase 4 Target Architecture

### 2.1 The spine: an explicit **stage router**
Key valuation off `portfolio_metadata[ticker].{type, stage}`. Every branch returns the **same triangulation
triplet** `{L_cost, L_mkt, L_inc}` in $/share plus a per‑method **confidence** `c_i ∈ (0,1]`; only the
method internals and default weights differ by stage.

| Stage | Cost leg `L_cost` | Market leg `L_mkt` | Income/Option leg `L_inc` | Default `(w_cost,w_mkt,w_inc)` |
|-------|-------------------|--------------------|---------------------------|--------------------------------|
| **Explorer** (AGA.V/PEA) | REP floor | comps·TQ on defined + risked future ounces, lifted by option convexity | (folded into L_mkt via `(1+π_opt)`) | (0.30, 0.70, 0.00) |
| **Developer** (GMX/DFS) | REP floor | comps·TQ, modest `π_opt` | after‑tax NPV/sh × P(build) | (0.15, 0.35, 0.50) |
| **Producer** | REP floor | P/NAV or EV/EBITDA comp | DCF on production profile | (0.10, 0.30, 0.60) |
| **Royalty** (GROY, URC) | minimal | P/NAV multiple | risked NSR/stream NAV | (0.05, 0.25, 0.70) |

**Why this shape:** optionality is always a **multiplier on the market resource leg** (coherent,
asset‑proportional — fixes F1), and its cap **decays by stage** (explorers *are* an option; producers are
cash flows) so silver torque is never double‑counted across `π_opt` and the DCF (fixes F5). Income/DCF
only appears where cash flows are forecastable.

### 2.2 Triangulation with **confidence‑tilted** blending (kills the static 0.15/0.70/0.15)
```
V_intrinsic = Σ_i  w_i · L_i ,     w_i = (W_i^stage · c_i) / Σ_j (W_j^stage · c_j)
```
`c_mkt` falls when comps are stale / peer count is low / ounces are Inferred‑heavy; `c_inc` is low for
explorers (no NPV) and high for producers; `c_cost` is high and stable (cash is hard). When comps degrade,
weight automatically shifts to the cost floor — defensible and self‑documenting.

### 2.3 **Technical‑Quality (TQ) multiplier** — ounces become non‑fungible (fixes F3, F4)
A transparent, bounded product of per‑factor multipliers, each `f_k = lo_k + (hi_k−lo_k)·s_k` with
`s_k∈[0,1]` a documented normalization of a config driver:

| Factor | Driver | Band (lo–hi) | Notes |
|--------|--------|--------------|-------|
| `f_grade` | grade vs peer benchmark | 0.85–1.20 | higher grade ⇒ lower $/oz cost, higher recoverability |
| `f_metallurgy` | **blended** Ag+Au recovery on the AgEq split | 0.80–1.10 | **fixes the dropped‑gold bug** |
| `f_jurisdiction` | **real Fraser/PPI index** | 0.80–1.15 | **fixes the silver‑price misnomer** |
| `f_infrastructure` | power/water/road/permitting status | 0.90–1.15 | |
| `f_depth_continuity` | open‑pit vs deep UG, continuity | 0.85–1.10 | |

```
TQ_p = clamp( Π_k f_k(p),  TQ_min=0.55,  TQ_max=1.70 )
```
**Anti‑double‑count discipline inside TQ:** the M&I↔Inferred *confidence* haircut stays where it already
lives (in `effective_oz`, the symmetric 50% Inferred discount) and is **not** also a TQ factor. TQ carries
*geological/operational* quality only. Each `f_k` and its driver are emitted for a UI breakdown bar.

### 2.4 **De‑overlapped** value channels (the "no double‑counting" mandate)
Each economic source enters **exactly one** leg:
- **Defined ounces** (M&I + 0.5·Inferred) → **Market** only: `comps · TQ`. The opaque
  `discovery_premium_factor` is **removed**; sector re‑rating is already carried by the *live* peer EV/oz.
  The stage gap between AGA.V (PEA) and the peer baseline is handled by the **documented stage multiplier**
  (config already has Explorer 0.70 … Producer 1.30 — a citable Lassonde‑curve re‑rating), **not** by a
  commodity‑leverage tower.
- **Future undiscovered ounces** → **Exploration sub‑leg**, risked **once**:
  `oz_target · P(discovery) · peer_ev · TQ_expl` (with `TQ_expl ≤ 1.0` — undiscovered ounces earn no
  quality premium). Never also re‑rated by an option or discovery multiple.
- **Monetary / operating convexity** → the **option premium `π_opt`** on the market leg, and **only** there.

### 2.5 **Option leg** `π_opt` — coherent, live, bounded (replaces dead ROV + the mislabeled discovery multiple)
Treat the in‑situ resource as a call on silver struck at AISC. `π_opt` is a **fractional** premium (≥0),
applied multiplicatively to the market base:
```
moneyness = clamp( (spot_ag − AISC_dyn) / AISC_dyn, 0, m_cap )          # operating leverage (was discovery_premium)
vol_term  = clamp( k_v · max(0, σ_ag_realized − σ_floor), 0, v_cap )     # LIVE realized silver vol (fixes dead 0.25)
carry_term= clamp( k_c · max(0, real_yield_breakeven − real_yield), 0, c_cap)  # monetary repression convexity (old ROV intent, alive)
π_opt     = stage_optionality_cap · ( w_m·moneyness + w_v·vol_term + w_c·carry_term )
L_mkt     = (V_mkt_defined + V_expl) · (1 + π_opt)
```
`stage_optionality_cap`: Explorer 1.0 → Developer 0.5 → Producer 0.15 → Royalty 0.0, so convexity fades as
the asset becomes a cash‑flow story (prevents `π_opt`↔DCF overlap). Default bands chosen so the **base‑case
`π_opt` reproduces the economic lift the old `discovery_premium_factor` was providing**, but now transparent,
bounded, stage‑decaying, and live‑vol‑driven.

### 2.6 **Scenario engine** — base / bull / bear + tornado (fixes F10)
Re‑run the full triangulation under documented shifts of the dominant swing inputs:

| Input | Bear | Base | Bull |
|-------|------|------|------|
| spot_ag (& gold) | −1.5σ (trailing realized) | live | +1.5σ |
| peer_ev/oz | 20th pct trailing | live | 80th pct |
| real_yield | +50 bps | live | −50 bps |
| P(discovery) | −0.10 | config | +0.10 |
| M&I realization | −10 pts | config | +10 pts |

Outputs `{V_bear, V_base, V_bull}`, an **implied‑upside range**, and a **one‑at‑a‑time tornado** (`∂V/∂input`).
Until a peer‑EV history exists (Phase 5), `peer_ev` bull/bear uses ±35% placeholders, flagged as such.

### 2.7 **Single Margin‑of‑Safety ledger** (fixes F9)
Replace scattered scalars with one emitted list: `[{name, factor, cumulative}]` for every haircut
(stressed $/oz, Inferred 50%, conservatism, forensic_penalty, TQ<1 drags). The UI renders the full
"gross → net" waterfall so total conservatism is visible at a glance.

---

## 3. Mathematical Specification (consolidated)

**Effective ounces (unchanged symmetric Inferred haircut):**
```
eff_oz_p = oz_p · ( mi_pct_p · 1.0 + (1 − mi_pct_p) · 0.5 )
```
**Technical quality:** `TQ_p = clamp(Π_k f_k(p), 0.55, 1.70)`, factor bands per §2.3.

**Blended metallurgical recovery (fix F4):** with AgEq contribution shares `(a_ag, a_au)` per project,
`rec_blend_p = a_ag·rec_ag_p + a_au·rec_au_p`, feeding `f_metallurgy`.

**Market leg (defined):**
```
V_mkt_defined = ( Σ_p eff_oz_p · TQ_p ) · peer_ev · stage_mult(target) · capital_discount(y30) / shares
```
**Exploration sub‑leg (risked once):**
```
V_expl = oz_target · P(discovery) · peer_ev · TQ_expl · expl_weight / shares
```
**Option premium / market lift:** per §2.5 → `L_mkt = (V_mkt_defined + V_expl) · (1 + π_opt)`.

**Cost leg:** `L_cost = REP_floor` (existing, in the MoS ledger).

**Income leg (developer/producer/royalty only):**
```
Developer: L_inc = NPV_after_tax_per_share(spot_deck, AISC_dyn, discount=f(y30,real_yield)) · P(build)
Producer : L_inc = DCF(production_profile, AISC_dyn, discount)
Royalty  : L_inc = Σ_streams  risked_NSR_cashflow_t / (1+discount)^t  / shares
```
**Triangulated intrinsic:** `V_intrinsic = Σ_i w_i·L_i`, confidence‑tilted weights per §2.2.

**Scenario set:** §2.6 → `{V_bear, V_base, V_bull}`, implied‑upside range, tornado.

> **Continuity discipline (house style):** all new bands/caps are calibrated so the **base‑case
> `V_base` reconciles to the current live `AGA_Intrinsic` within a stated tolerance after the F5
> double‑count is removed** — i.e. we deliberately subtract the redundant optionality, then re‑establish
> the legitimate lift through `π_opt` + stage_mult + TQ, and publish the reconciliation (§5).

---

## 4. Data Schemas

### 4.1 `v5_config.json` additions
```jsonc
"technical_quality": {
  "enabled": true, "tq_min": 0.55, "tq_max": 1.70,
  "factors": {
    "grade":          { "lo": 0.85, "hi": 1.20, "benchmark_gpt_ageq": 250 },
    "metallurgy":     { "lo": 0.80, "hi": 1.10, "rec_lo": 0.70, "rec_hi": 0.95 },
    "jurisdiction":   { "lo": 0.80, "hi": 1.15, "fraser_lo": 50, "fraser_hi": 95 },
    "infrastructure": { "lo": 0.90, "hi": 1.15 },
    "depth":          { "lo": 0.85, "hi": 1.10 }
  },
  "projects": {
    "red_mountain":   { "grade_gpt_ageq": 320, "rec_ag": 0.85, "rec_au": 0.94, "ageq_share_ag": 0.7, "ageq_share_au": 0.3, "fraser": 84.2, "infrastructure": 0.7, "depth": 0.8 },
    "belmont_tailings":{ "grade_gpt_ageq": 140, "rec_ag": 0.89, "rec_au": 0.95, "ageq_share_ag": 0.8, "ageq_share_au": 0.2, "fraser": 84.2, "infrastructure": 0.95, "depth": 1.0 },
    "hughes":         { "grade_gpt_ageq": 260, "rec_ag": 0.87, "rec_au": 0.95, "ageq_share_ag": 0.7, "ageq_share_au": 0.3, "fraser": 84.2, "infrastructure": 0.6, "depth": 0.6 },
    "mogollon":       { "grade_gpt_ageq": 300, "rec_ag": 0.78, "rec_au": 0.92, "ageq_share_ag": 0.6, "ageq_share_au": 0.4, "fraser": 84.2, "infrastructure": 0.5, "depth": 0.5 }
  }
},
"option_premium": {
  "enabled": true,
  "weights": { "moneyness": 0.5, "vol": 0.3, "carry": 0.2 },
  "moneyness_cap": 1.5, "vol_floor": 0.20, "vol_k": 1.0, "vol_cap": 0.4,
  "carry_breakeven": 1.0, "carry_k": 0.25, "carry_cap": 0.5,
  "stage_optionality_cap": { "explorer": 1.0, "developer": 0.5, "producer": 0.15, "royalty": 0.0 }
},
"triangulation": {
  "stage_weights": {
    "explorer":  { "cost": 0.30, "market": 0.70, "income": 0.00 },
    "developer": { "cost": 0.15, "market": 0.35, "income": 0.50 },
    "producer":  { "cost": 0.10, "market": 0.30, "income": 0.60 },
    "royalty":   { "cost": 0.05, "market": 0.25, "income": 0.70 }
  },
  "confidence": { "cost": 0.90, "market_base": 0.85, "income_explorer": 0.20, "income_producer": 0.85 }
},
"scenarios": {
  "spot_sigma_mult": 1.5, "real_yield_shift_bps": 50,
  "p_discovery_shift": 0.10, "mi_shift_pts": 0.10, "peer_ev_pct_placeholder": 0.35
}
```
Plus the Phase 0 keys (`adv_window_days`, `cba_denominator`, `mri_dynamic_bounds`, …) from §0.

**Deprecations:** `jurisdiction_uplift_params` (replaced by TQ jurisdiction factor),
`explorer_re_rating_scalar`/`discovery_multiple` paths feeding `discovery_premium_factor`
(replaced by stage_mult + π_opt). Kept readable for one release behind a `legacy_discovery: false` flag.

### 4.2 `terminal_state` output additions (new `valuation_detail` block)
```jsonc
"valuation_detail": {
  "stage": "explorer",
  "legs": { "cost": 0.82, "market": 1.94, "income": 0.0 },
  "weights": { "cost": 0.30, "market": 0.70, "income": 0.0 },
  "confidence": { "cost": 0.90, "market": 0.78, "income": 0.0 },
  "tq_by_project": { "red_mountain": { "tq": 1.06, "factors": { "grade": 1.10, "metallurgy": 0.97, "jurisdiction": 1.07, "infrastructure": 1.0, "depth": 0.97 } } },
  "option_premium": { "pi_opt": 0.21, "moneyness": 1.95, "vol_term": 0.05, "carry_term": 0.0 },
  "mos_ledger": [ { "name": "stressed_$/oz", "factor": 0.65 }, { "name": "inferred_50pct", "factor": 0.88 }, { "name": "conservatism", "factor": 0.88 }, { "name": "forensic_penalty", "factor": 1.0 } ],
  "scenarios": { "bear": 2.9, "base": 4.1, "bull": 6.2, "implied_upside_pct": { "bear": 308, "base": 477, "bull": 773 } },
  "tornado": [ { "input": "spot_ag", "low": 3.1, "high": 5.4 }, { "input": "peer_ev", "low": 3.0, "high": 5.6 } ]
}
```
This block is **purely additive** — existing `v4_valuation` keys remain so the Flutter UI never breaks
mid‑migration; the cockpit reads the new block when present.

---

## 5. Calibration, Reconciliation & Validation Plan

1. **Reconstruct the live base case** in a scratch harness (offline, from `.cache/macro_state.json`) →
   confirm the ≈$4.63 / 93%‑on‑one‑leg figure.
2. **Remove F5 double‑count**, then **re‑tune** `option_premium` + stage_mult + TQ bands so `V_base`
   lands within a **published tolerance** of the prior live intrinsic — and **document the residual delta
   as the value of the removed redundancy** (expected: a modest reduction, because we delete one of the
   two optionality counts). The brief authorizes this ("we can always roll back"); the deliverable is a
   side‑by‑side *old vs new* reconciliation table, not a silent reprice.
3. **Unit tests** (extend `test_v5_engine.py`): TQ monotonicity & clamps; de‑overlap invariant (a +$1
   silver move must raise `peer_ev`/`π_opt` but **not** any removed discovery path); blend‑weights sum to
   1; scenario ordering `V_bear ≤ V_base ≤ V_bull`; Phase‑0 patch tests from §0.
4. **Golden‑file** the new `valuation_detail` at the live operating point to catch silent drift.

---

## 6. Sequencing & Approval Gate

| Step | Scope | File | Risk |
|------|-------|------|------|
| **Phase 0** | 3 mandatory patches + tests | `engine.py` | Low, isolated |
| **Phase 4a** | Stage router, triangulation, TQ, de‑overlap, π_opt, scenarios, MoS ledger + tests | `engine.py` | Medium (core) |
| **Phase 4b** | Cockpit: TQ breakdown bar, triangulation legs, scenario range, tornado, MoS waterfall (Simply‑Wall‑St style) | `lib/main.dart` | Medium (UI only) |
| **Docs** | Update `ENGINE_DESIGN.md` / `METRIC_COMPASS.md` to match | docs | Low |

Per the brief's guardrails, **engine and UI are never written in the same turn.** Recommended order:
**Phase 0 → Phase 4a → Phase 4b → docs**, each its own commit, each reconciled to the live operating point.

**Awaiting sign‑off to proceed.** Default executive recommendation if no objection: ship **Phase 0** first
(small, safe, mandated), then **Phase 4a**.
