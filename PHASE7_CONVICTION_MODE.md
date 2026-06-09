# CommodityEx Monitor v5.3 — Phase 7: Conviction Mode + Refined Asymmetry Rating

> **🔒 BASELINE LOCKED.** The T·Q·V rating is frozen at this version — archetype differentiation,
> floor-aware forensic gate, and the round-2 conviction lift — as the objective baseline. No further
> upward tuning (avoid overfitting to current holdings). Certified barbell at the operating point:
> **AGA.V 8.6 PRIME CONVICTION · URC.TO 7.1 HIGH QUALITY · GROY 6.8 SOLID/FAIR · GMX.TO 6.3 SOLID/FAIR.**
> Tests green: 189 Python + 11 Flutter. Changes from here should be confined to the Conviction Mode
> layout, not the rating constants.

*Chief Valuation Architect audit & design proposal. Supersedes nothing in the engine; it
**re-frames** what Conviction Mode consumes. All Phase 0/4a/5/6 math remains intact and
available in the secondary **Detailed Analysis** view — Phase 7 changes which numbers are
**headline**, which are **advisory**, and which are **hidden by default**.*

---

## 0. Core Philosophy & Mandate

> *"Keep all your eggs in one or a few baskets and watch them very closely."*

The engine as built (v5.1 → v5.3) is a faithful **institutional diversified-book** model: fractional
Kelly, ES95 throttling, Ledoit-Wolf covariance shrinkage, a hard 60/40 barbell ceiling, ADV exit caps,
and an uncapped convex tail penalty on the Health Rating. Every one of those mechanics exists to
**enforce diversification and dampen concentration** — which is the *opposite* of this operator's
declared edge. A concentrated, high-conviction junior-miner style does not want the model
automatically trimming the spear when volatility (the very source of the asymmetry) rises.

Phase 7 makes **Conviction Mode the primary/default view** and reorganizes the system around three
pillars, applied **per basket, in a vacuum** — not across a portfolio:

1. **Macro regime health** — is the tide coming in for this archetype? (esp. Option Convexity)
2. **Company health in a vacuum** — can this specific name survive and execute?
3. **Quality of upside asymmetry** — how fat is the payoff vs. the hard floor?

The polymorphic archetype system (`archetypes.py`) is retained in full, but repurposed: it picks the
right **valuation lens per asset type**, not the right **portfolio-construction math**.

---

## 1. Audit Report — Math/Logic That Conflicts With Concentrated Conviction

Verdict legend: **REMOVE** (don't compute/consume in Conviction Mode) · **HIDE** (keep computing,
move to Detailed view) · **DEMOTE** (show as passive *awareness*, never as an automatic gate) ·
**REPURPOSE** (keep the number, change its role) · **KEEP** (already aligned).

| # | Mechanic | Where it lives | Conviction-Mode verdict | Reasoning |
|---|----------|----------------|-------------------------|-----------|
| 1 | **Hard spear ceiling (60%)** + `max_single_position_pct` (20%) | `engine.py` PortfolioSizer (`SPEAR_CEILING_STRUCTURAL`); `v5_config.json → v5_guardrails.max_spear_position_pct=0.6, max_single_position_pct=0.2` | ~~REMOVE as a cap~~ **SUPERSEDED — KEEP, permanently.** The 60% ceiling is a standing hard invariant: it stays a clamp, is enforced as a code-side constant (config can only tighten it), and is never a tunable. | *(Original row proposed removing the clamp; the operator's standing decision is the opposite — "the 60% structural ceiling stays. It is not up for debate." The cap is the book's one hard margin-of-safety constraint; conviction is expressed by sizing **up to** it, never through it. The original reasoning is preserved here only as history.)* |
| 2 | **Dynamic ADV exit-liquidity cap** | `engine.py` PortfolioSizer (`~1836`, `adv_cap` waterfall stage); `v5_guardrails.position_liquidity_cap_pct=0.15`, `adv_window_days=90` | **DEMOTE** to an advisory "exit-liquidity note" | Illiquidity in juniors is *real* and worth surfacing — but as information, not as an automatic clamp on the target. A conviction operator accepts illiquidity knowingly. Show "≈ N days to exit at 15% ADV", do not subtract from the signal. |
| 3 | **ES95 tail-risk throttle** (halves leverage at ≤ −12% daily ES) | `engine.py:1733–1747`; `v5_guardrails.es_throttle` | **REMOVE** from Conviction sizing; **DEMOTE** ES95 to a displayed number | This auto-fades the position exactly when tail vol expands — but for a convex junior, fat tails are the *upside engine*, not just downside. Throttling on ES95 systematically de-risks the asymmetry the operator is paid to hold. |
| 4 | **Uncapped convex ES95 Health penalty** | `engine.py:calculate_health_rating` (`~1377–1395`); `health_radar.es_penalty {free −5%, ref −10%, exp 1.5}` | **DEMOTE** — drop the tail term from the Conviction health pillar | A −30% ES drives an **−11.18** point penalty (METRIC_COMPASS §3). It crushes the Health Rating for high-vol names — i.e. it punishes precisely the volatility profile of a high-torque explorer. Keep JSF + stale-data + macro awareness; drop the tail term here. |
| 5 | **Ledoit-Wolf covariance shrinkage** (constant-correlation target) | `engine.py:1572 shrink_correlation`; `v5_guardrails.covariance_shrinkage_intensity=0.30` | **HIDE** (Detailed view only) | Shrinking a pairwise correlation matrix toward a common level is **portfolio-covariance** machinery. With 1–3 baskets there is no meaningful covariance matrix to stabilize. Irrelevant to per-basket conviction. |
| 6 | **Robust/parametric ES95 blend** | `engine.py:1600 robust_expected_shortfall`; `v5_guardrails.es_parametric_blend=0.5` | **HIDE / DEMOTE** | Same family as #3/#5 — a blended portfolio tail estimate. Useful as awareness in Detailed view; never an input to the Conviction signal. |
| 7 | **Barbell correlation penalty** (scales Kelly when AGA.V–ballast corr > 0.30) | `engine.py:~806–812 correlation_penalty` | **REMOVE** | This rewards *decorrelation* between holdings — the literal definition of a diversification benefit. Meaningless and counter-philosophical for a 1–3 name book. |
| 8 | **Fractional Kelly waterfall** + **VIX leverage cap** `max(0.60, 1.5−(VIX−15)·0.045)` | `engine.py:1731` (VIX cap), `5.1` Kelly; `v5_guardrails.fractional_kelly_multiplier=0.5` | **DEMOTE** to a reference readout | Kelly assumes you size *down* to manage ruin across a book. A conviction operator sizes by conviction, not by a variance-derived fraction. Show the Kelly target as *one reference opinion*, not the deployed answer; drop the automatic VIX de-leveraging. |
| 9 | **Portfolio-blended (60/40) intrinsic as the headline signal** | orchestrator rollup of `archetype_valuation` over the 60/15/15/10 barbell | **REPURPOSE** | Keep the **per-asset** triangulation (it's excellent and de-overlapped). Drop the *portfolio blend* as a headline — each basket must stand alone under "company health in a vacuum." The book-level number belongs in Detailed view. |
| 10 | **Heavy model-dispersion / edge-uncertainty penalties** | `v5_guardrails.edge_uncertainty {noise_vol_multiplier, min_confidence}`; prior "BAR" dispersion weighting | **DEMOTE** — convert dispersion into a **confidence ribbon**, not a score deduction | Penalizing a name because models disagree double-counts uncertainty already captured by confidence-tilted weighting (`triangulate`, `archetypes.py:501`). In Conviction Mode, dispersion renders as a ± band around the Asymmetry Rating — *information about precision*, not a haircut to the point estimate. This is the explicit "reduce influence of pure consensus/dispersion vs. earlier BAR" mandate. |
| 11 | **Phase 4a discovery-premium de-overlap** (removed the ~3.3× double-count) | `ENGINE_DESIGN.md §0.5`; `calculate_spear_intrinsic` | **KEEP** | Already clean and first-principles correct. The triangulated Cost·Market·Option per-asset valuation is the foundation Conviction Mode builds on. |
| 12 | **JSF / CBA / dilution / runway forensics** | `engine.py ForensicEngine`; `archetypes.py` pre-revenue primitives (`runway_months`, `cash_burn_acceleration`, `dilution_velocity`) | **KEEP — promote** | Forensic survival awareness is *more* important under concentration, not less. This becomes Pillar 2 and a hard gate on the rating (see §2.4). |
| 13 | **MRI macro regime index + term-structure / backwardation / real-yield carry** | `engine.py MacroRegimeEngine`; `RegimeImpactVector` (`archetypes.py:40`) | **KEEP — promote** | Pillar 1. The per-archetype regime alpha is exactly the right home for the macro-asymmetry lean. |

**Net effect of the audit:** Conviction Mode stops *consuming* mechanics #1–#8 as automatic gates and
stops headlining #9–#10. Nothing is deleted from the engine — the Detailed Analysis view still renders
every throttle, the covariance shrinkage, the Kelly waterfall and the full margin-of-safety ledger for
anyone who wants the institutional read. Conviction Mode simply **does not let that machinery trim,
throttle, cap, or penalize** the high-conviction thesis.

---

## 2. New Asymmetry Rating (0–10) — Definition & Design Principles

### 2.1 Design principles

1. **Three transparent pillars, not a black box.** Every basket gets a Macro (T), Quality (Q), and
   Asymmetry (V) sub-score in `[0,10]`; the final rating is a visible weighted blend. The operator can
   always see *why* a basket scores what it does.
2. **Valuation asymmetry is the heart.** The single most important question — *how fat is realistic
   upside vs. the hard floor?* — carries the most weight.
3. **Dispersion is a confidence ribbon, not a penalty.** Model disagreement widens a ± band around the
   rating; it does not subtract from it. (Mandate: reduce consensus/dispersion influence vs. BAR.)
4. **Forensics is a *floor-aware* gate, not a smooth penalty.** Balance-sheet decay can cap the rating —
   but the cap is **relaxed in proportion to floor support** (price at/below the REP floor). A junior
   funding its drill program while trading *below liquidation value* is normal and must not be slammed to
   "avoid" — its asymmetry should shine. Diluting/burning *at a premium* (price well above floor) is
   fully gated; a genuinely broken balance sheet (very low JSF) stays a heavy penalty even below floor.
   (See §6 — this fixed the case where routine 12%/yr dilution wrongly capped a +476%-upside, below-floor
   AGA.V to 4.5.) Clean forensics never inflates the score — survival is necessary, not sufficient.
5. **Bounded & saturating, never unbounded.** Unlike the uncapped ES penalty being removed, every term
   saturates into `[0,10]`, so no single lever can dominate pathologically.
6. **Archetype-aware weighting.** Option Convexity assets lean more on macro tailwind (the convexity is
   macro-driven); cash-flowing names lean more on quality/valuation.

### 2.2 Pillar 1 — Macro Regime Tailwind `T ∈ [0,10]`

Built from numbers the engine already produces: the MRI and the asset's archetype regime alpha.

$$ m = \mathrm{clamp}\!\left(1 - \tfrac{\text{MRI}}{100},\, 0,\, 1\right) \qquad
   a = \mathrm{clamp}\!\left(\tfrac{1 + \alpha_{\text{arch}}}{2},\, 0,\, 1\right) $$

$$ T = 10 \cdot \big(\kappa \cdot a + (1-\kappa)\cdot m\big) $$

- `m` is macro posture: 1.0 in a risk-on liquidity regime (MRI→0), 0.0 in acute stress (MRI→100).
- `a` re-centers the archetype's discretionary macro-asymmetry coefficient `α ∈ [−1,1]`
  (`regime_alpha`, `archetypes.py:556`) onto `[0,1]` — the Druckenmiller "lean into the tailwind" term.
- `κ` is the macro-lean weight: **`κ = 0.60` for `option_convexity`**, `0.40` otherwise. A pre-revenue
  explorer *is* a macro option, so its regime tailwind dominates; a royalty's cash flows insulate it.

### 2.3 Pillar 2 — Company Health In A Vacuum `Q ∈ [0,10]`

$$ Q = 10\cdot\Big( 0.45\cdot \tfrac{s_f}{4} \;+\; 0.35\cdot q_a \;+\; 0.20\cdot c \Big) $$

- **`s_f ∈ [0,4]`** — forensic/JSF survival score (`calculate_forensic_score`): runway, dilution
  velocity, burn acceleration, corporate drag. Balance-sheet health.
- **`q_a ∈ [0,1]`** — **asset/resource quality**, the real-world lens. For resource archetypes use the
  Technical-Quality multiplier normalized out of its band,
  $q_a = \mathrm{clamp}\!\big(\tfrac{\text{TQ}-0.55}{1.70-0.55},0,1\big)$ (TQ already folds in grade,
  blended Ag+Au metallurgy, **real Fraser-index jurisdiction**, infrastructure, depth — `ENGINE_DESIGN
  §0.5`). For non-resource archetypes substitute the live market-leg confidence.
- **`c ∈ [0,1]`** — **management/conviction credibility**: the CrowdEx conviction overlay
  (`calculate_conviction`, `archetypes.py:408`) — insider net buying, low dilution, catalyst momentum.
  Already kept *out* of intrinsic to avoid double-counting; here it is a quality input, not a price.

### 2.4 Pillar 3 — Valuation Asymmetry `V ∈ [0,10]` (the heart)

Uses the existing **bull / base / bear** scenario band (`run_intrinsic_scenarios`, `engine.py:1317`)
and the **cost leg / REP floor** (the hard, liquidation-style downside).

Let `P` = live price, `B` = **Bull Case Target** (bull scenario intrinsic), `F` = **hard floor**
(cost-leg / REP floor, `engine.py:calculate_rep_floor`), `Bear` = bear scenario intrinsic.

$$ U = \max\!\Big(0,\ \tfrac{B}{P}-1\Big) \quad\text{(realistic upside fraction)} \qquad
   D^{f} = \max\!\Big(0,\ 1-\tfrac{F}{P}\Big) \quad\text{(downside-to-floor fraction)} $$

$$ \rho = \frac{U}{\max(D^{f},\,\delta)} ,\quad \delta=0.10 \qquad
   V_{\text{payoff}} = \frac{\rho}{\rho + 2} $$

$$ \varphi = \tfrac{F}{P} \qquad
   V_{\text{support}} = \mathrm{clamp}\!\Big(\tfrac{\varphi-0.75}{0.50},\,0,\,1\Big) $$

$$ \boxed{\,V = 10\cdot\big(0.65\cdot V_{\text{payoff}} + 0.35\cdot V_{\text{support}}\big)\,} $$

- **`ρ` is the asymmetry ratio**: fractional upside per unit of fractional downside-*to-the-floor*. A
  classic 3:1 setup → `ρ=3 → V_payoff=0.60`; a symmetric coin-flip → `ρ=1 → 0.33`. The half-saturation
  at `ρ=2` (a 2:1 payoff scores the midpoint) keeps it bounded and intuitive.
- **`δ=0.10` floor on downside** rewards genuine floor support: when `P ≤ F` (trading *below*
  liquidation value), `D^f=0`, downside is structurally capped, and `ρ` saturates `V_payoff→1`.
- **`V_support`** independently rewards trading near/below the hard floor: `φ=0.75 → 0` (price 33% above
  floor), `φ=1.0 → 0.5` (price *at* floor), `φ=1.25 → 1.0` (price 20% below floor — "sunk-cost
  arbitrage", METRIC_COMPASS §4). This is the structural-downside-supported signal the operator wants.

### 2.5 Composite rating, weights, gates, and confidence ribbon

$$ A_{\text{raw}} = w_T\,T + w_Q\,Q + w_V\,V $$

| Archetype | `w_T` | `w_Q` | `w_V` | Rationale |
|-----------|------:|------:|------:|-----------|
| `option_convexity` (default conviction target) | 0.33 | 0.22 | 0.45 | Macro-driven convexity + asymmetry dominate; survival is a gate. |
| all others | 0.25 | 0.30 | 0.45 | Cash flows shift weight from macro to company quality. |

**Forensic gate — floor-aware (necessary condition, relaxed by structural support).** A forensic
trigger (low JSF, aggressive dilution, broken runway) computes a raw cap, which is then lifted toward
10 by the **floor support** `s = clamp((F/P − 0.85)/(1.10 − 0.85), 0, 1)` (1.0 when price is at/below
the REP floor):

$$ \text{cap}_i = \text{raw\_cap}_i + (10 - \text{raw\_cap}_i)\cdot s\cdot \text{relax}_i, \qquad
   A = \min\big(A_{\text{raw}},\ \min_i \text{cap}_i\big) $$

with `relax = 1.0` for dilution/runway (fully liftable below floor — routine for juniors) and a
smaller, JSF-scaled `relax` for a broken balance sheet (stays a heavy penalty even below floor). When
price is well above the floor (`s = 0`) the gate bites fully, so diluting/burning *at a premium* is
still capped to ~4.5.

**Confidence ribbon (dispersion → precision, not penalty).** Let `q ∈ {full, degraded, sparse}` be the
triangulation `data_quality` and let `s = (B - Bear)/\max(P, \varepsilon)` be the scenario spread. The
rating is reported as `A ± band(q, s)` — wider when legs are sparse or the bull/bear band is wide.
Crucially, **`band` never moves `A` itself**; it tells the operator how tight the signal is. This is the
deliberate departure from the BAR proposals, where dispersion was subtracted from the score.

### 2.6 Interpretation bands

| `A` | Label | Operator meaning |
|-----|-------|------------------|
| **8.5–10** | **Prime conviction** | Structurally-supported asymmetry **and** macro tailwind **and** clean survival. Watch very closely; size up. |
| **7.0–8.4** | **Strong asymmetry** | Fat payoff, floor holds; one pillar merely good not great. Core watch-list. |
| **5.0–6.9** | **Balanced** | Thesis intact but not screaming — upside priced fairly or tailwind neutral. Monitor. |
| **3.0–4.9** | **Weak / expensive** | Upside largely priced in, thin floor, or soft macro. Trim/avoid adding. |
| **0–2.9** | **Broken / avoid** | Forensic gate tripped (dilution imminent) or negative asymmetry. Not a basket to hold closely. |

### 2.7 Worked example (AGA.V, May 2026 operating point)

Inputs from the live docs: `MRI ≈ 40.2` (risk-on), `α_option` discretionary tailwind `≈ +0.4`,
`P ≈ $0.71`, **Bull** `≈ $1.69×(1+upside band)`, base intrinsic `≈ $1.69` (138% upside vs price,
`ENGINE_DESIGN §0.5`), **REP floor** `F ≈ $0.824` (so `φ = 0.824/0.71 ≈ 1.16` — *price below
liquidation value*), `s_f ≈ 3.5` (clean), conviction `c ≈ 0.6`, `TQ` mid-band `q_a ≈ 0.5`.

- `m = 1 − 0.402 = 0.60`, `a = (1+0.4)/2 = 0.70`, `κ=0.6` → **`T = 10(0.6·0.70 + 0.4·0.60) = 6.6`**
- `Q = 10(0.45·0.875 + 0.35·0.50 + 0.20·0.60) = 10(0.394+0.175+0.12) ≈` **`6.9`**
- `D^f = max(0, 1−1.16) = 0 → ρ` saturates → `V_payoff = 1.0`; `V_support = clamp((1.16−0.75)/0.5)=0.82`
  → **`V = 10(0.65·1.0 + 0.35·0.82) = 9.4`**
- `A_raw = 0.30·6.6 + 0.25·6.9 + 0.45·9.4 = 1.98 + 1.73 + 4.23 =` **`≈ 7.9`**, gate clear (`s_f≥1.5`).

→ **AGA.V ≈ 7.9 / 10 — "Strong asymmetry"**: trading below its hard floor with ~138% base upside and a
favorable macro tailwind, dragged off "Prime" only by mid-band resource quality and a merely-good macro
score. That is exactly the high-signal read a conviction operator wants — *and notice it scores high
precisely because of the low floor / fat upside the ES95-throttle world would have penalized for vol.*

---

## 3. Conviction Mode — Information Architecture

### 3.1 Layout (primary/default view)

Clean, monospace, high-signal, minimal design fluff. One **Conviction Card** per high-conviction basket
(1–3 names), stacked. No portfolio-construction chrome.

```
┌─ CONVICTION MODE ─────────────────────────────────  [ Detailed Analysis ▸ ] ┐
│                                                                              │
│  AGA.V · Option Convexity (explorer/PEA)            ASYMMETRY   7.9 ± 0.6     │
│  "Below floor, ~138% base upside, macro tailwind."  ███████░░░  STRONG        │
│                                                                              │
│  ① MACRO TAILWIND      T 6.6   MRI 40 (risk-on) · α +0.4 · Ag▲ · real-yld▼   │
│                        backwardation: ON                                     │
│  ② COMPANY (VACUUM)    Q 6.9   runway 22mo · dilution 0%/q · JSF 3.5/4        │
│                        resource TQ mid · Fraser 84 (USA) · conviction 0.60   │
│  ③ ASYMMETRY LADDER    V 9.4                                                  │
│         Bull   $1.95  ▲ +175%   ┐                                            │
│         Base   $1.69  ▲ +138%   │  realistic upside                          │
│       › Price  $0.71            │                                            │
│         Bear   $1.05            ┘                                            │
│         FLOOR  $0.82  ▼  price is 16% BELOW liquidation floor  ◀ supported   │
│                                                                              │
│  DIRECTIVE:  BELOW FLOOR — ACCUMULATE · watch closely                        │
│  (advisory) exit-liquidity ≈ 4 days @15% ADV · not a cap                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Key signals (the minimal high-signal set)

Exactly seven things per basket — everything else moves to Detailed Analysis:

1. **Asymmetry Rating** `A` (0–10) + band label + **confidence ribbon** `± band`.
2. **Macro tailwind gauge** `T` — MRI regime + archetype `α`, with the 2–3 live drivers (silver
   momentum, real yield, backwardation flag).
3. **Survival** — runway months & dilution velocity (the forensic gate, front and center).
4. **Resource/company quality** — TQ / Fraser jurisdiction / conviction overlay.
5. **The asymmetry ladder** — Bull / Base / Price / Bear / **REP Floor**, with `upside%` and
   `downside-to-floor%` and the payoff ratio `ρ`.
6. **Floor coverage `φ`** — the single "am I below liquidation value?" number.
7. **One directive line** — `BELOW FLOOR — ACCUMULATE` / `THESIS INTACT — HOLD` / `UPSIDE SPENT — TRIM`
   / `FORENSIC DECAY — AVOID`.

### 3.3 Secondary "Detailed Analysis" view (toggle)

Everything demoted/hidden in §1 lives here, unchanged: full Cost·Market·Option triangulation legs, the
tornado sensitivity, the margin-of-safety ledger, ES95 (empirical + parametric blend), covariance
shrinkage, the fractional-Kelly waterfall with every throttle stage, the 60/40 barbell exposure, and the
VIX leverage cap. Conviction Mode is the lens; Detailed Analysis is the full instrument panel.

### 3.4 Implementation shape (additive & parallel — the Phase 5 pattern)

- New pure function `asymmetry_rating(summary, scenarios, macro, forensics, archetype) → {A, T, Q, V,
  band, gate, directive}`, mirroring how Phase 4a added `valuation_detail` and Phase 5 added
  `archetype_valuation` — no existing math touched.
- Reads only fields the orchestrator already emits: `archetype_valuation` (legs, confidence,
  conviction, TQ), `valuation_detail.scenarios` (bull/base/bear), `rep_floor`, `mri`, `jsf`,
  `regime_alpha`, `data_quality`.
- New config block `conviction_mode { weights_by_archetype, kappa_by_archetype, rho_half: 2.0,
  delta_floor: 0.10, support_band: [0.75,1.25], forensic_gate_score: 1.5, default_view: true }` so every
  constant above is tunable without code changes (consistent with `archetype_factory` conventions).
- Conviction Mode becomes the **default route**; the Kelly/ES95/covariance/ADV machinery is computed as
  today but **not consumed** by the Conviction signal — it renders only in Detailed Analysis.

---

## 4. Summary of Recommendations

1. **Make Conviction Mode the default view**; demote the institutional risk-overlay panel to a
   secondary Detailed Analysis toggle.
2. **Stop auto-consuming diversification math** (spear ceiling, ADV cap, ES95 throttle, covariance
   shrinkage, correlation penalty, VIX de-leveraging, portfolio-blended intrinsic) as gates on the
   high-conviction thesis — keep it all computed and visible in Detailed Analysis only.
3. **Adopt the three-pillar Asymmetry Rating** (Macro Tailwind · Company-in-a-vacuum · Valuation
   Asymmetry), with valuation asymmetry weighted heaviest and forensics as a hard survival gate.
4. **Convert model dispersion from a score penalty into a confidence ribbon** — the explicit move away
   from the BAR proposals.
5. **Promote forensic survival and macro-regime awareness** (JSF, runway, dilution, MRI, backwardation,
   real-yield carry) — these matter *more* under concentration, not less.
6. **Ship additively** (new pure function + `conviction_mode` config block), exactly as Phases 4a/5/6
   shipped, so nothing in the audited engine is removed or destabilized.

---

## 5. Implementation Status (shipped)

Phase 7 is implemented **additively** — nothing in the audited engine was removed; Conviction
Mode simply does not *consume* the demoted machinery, which still renders in Detailed Analysis.

| Area | Change | Files |
|------|--------|-------|
| **Rating engine** | New pure, dependency-free `compute_asymmetry_rating()` / `build_conviction_state()` (the 0-10 T-Q-V math, forensic gate, confidence ribbon, directives) | `asymmetry_rating.py` |
| **Config** | `conviction_mode` block — every weight/gate/band tunable; `default_view: "conviction"` | `v5_config.json` |
| **Orchestrator** | `_compute_conviction_mode()` assembles the per-basket inputs from blocks already computed (`valuation_detail`, `archetype_valuation_detail`, `forensics`, `mri`, CAD prices) and emits `terminal_state["conviction_mode"]`; isolated in try/except so it can never crash the loop. Consumes **none** of the caps/ES95/shrinkage/Kelly machinery. | `engine.py` |
| **Flutter (primary frontend)** | Conviction Mode is the **default view** with a `◎ CONVICTION / ⚙ DETAILED` toggle; clean basket cards (big rating + band + ribbon, three pillar bars, the Bull→Floor asymmetry ladder, directive, gate warning). Detailed Analysis retains the full narrative deck. Graceful when the block is absent. | `lib/main.dart` |
| **Streamlit (analyst cockpit)** | Same primary/secondary split via a view selector; renders the engine's `conviction_mode` block (or recomputes locally from state as a fallback). | `dashboard.py` |
| **Tests** | 22 rating unit tests; engine smoke test of the wiring; 2 new Flutter widget tests (Conviction renders + toggle to Detailed, no overflow). All suites green: **131 Python + 10 Flutter**, `flutter analyze` clean. | `test_asymmetry_rating.py`, `test/dashboard_overflow_test.dart` |

**Live read at the documented operating point:** AGA.V (Option Convexity) scores **≈ 7.8 / 10 —
"STRONG ASYMMETRY · BELOW FLOOR — ACCUMULATE"**, topping the basket ranking; the cash-flowing
ballast names score lower (trading above their floors → thinner asymmetry), exactly as intended
for a concentrated, watch-a-few-closely operator.

---

## 6. Refinements (review pass)

Addressed the four review notes:

1. **Q pillar depth (junior-miner checklist).** Company Quality now scores an explicit mining
   checklist — **grade · scale · jurisdiction · metallurgy · permitting** — each normalized over a
   config band and blended over whatever lenses have live data, plus **management execution**
   (`management_score`, an analyst track-record input blended with the conviction overlay) and JSF
   forensics. The spear's lenses are derived from the config resource model (ounce-weighted head
   grade, total contained AgEq oz, ounce-weighted blended Ag+Au recovery). `Q weights = forensic
   0.35 · asset-quality 0.40 · management 0.25`. AGA.V → grade .74 · scale 1.0 · jurisdiction .76 ·
   metallurgy .71 · permitting .45 (PEA drags) → Q ≈ 7.5.
2. **T pillar weighting (macro is the edge).** `kappa_option` raised to **0.66** and the Option
   Convexity pillar weight to **T 0.33 / Q 0.22 / V 0.45**, so a favorable junior regime — and
   especially **α_option** — meaningfully lifts the score: at the live point α contributes **4.62 of
   T's 6.65**, ≈ 2+ points of final-rating swing from α alone. V stays the heaviest pillar.
3. **Visual cleanliness.** Cards simplified to a calm, high-signal layout: clean pillar names with a
   single faint detail line each, a compact quality-checklist chip row, and the Bull→Floor ladder.
   Removed weight/jargon noise and font-fragile glyphs. A to-scale preview is checked in at
   `conviction_card_preview.png` (generator: `tools_preview_conviction.py`).
4. **V pillar verified on AGA.V.** Bull $1.95 vs REP Floor $0.824 with price $0.71 → upside **+175%**,
   downside-to-floor **0%** (price 16% *below* liquidation), ρ ≈ 17.5 → **V ≈ 8.7**, directive
   **"BELOW FLOOR — ACCUMULATE."** Composite **≈ 7.8/10 "STRONG ASYMMETRY."**

All suites green after the refinement: **134 Python + 10 Flutter**, `flutter analyze` clean. (A
config-comment convention fix also hardened `build_default_router` to skip `_`-prefixed metadata
keys.)

---

## 7. Final polish — layout & information hierarchy

The Conviction card was tuned to feel calm and scannable, focused on *watching one basket closely*:

* **Left accent stripe** keyed to the rating colour, so a ranked list of baskets can be scanned
  straight down the edge (amber = strong, orange = weak, red = gated).
* **Anchor row** — the live **PRICE** row in the Bull→Floor ladder is highlighted (faint amber tint,
  bold) so the eye lands immediately on *where price sits between the bull target and the hard floor*.
* **Gate as a contained flag** — the forensic gate renders as a small bordered `GATE · reason` chip
  beside the directive: clearly visible, never a loud banner.
* **Clean pillars** — each pillar is one labelled bar + a single faint detail line; weight/jargon
  text was removed. The Q checklist sits as a compact chip row (grade · scale · juris · metal ·
  permit). Font-fragile glyphs were removed so nothing renders as a box on any platform.

A to-scale preview of the final card (live AGA.V values, plus a weak and a gated example) is checked
in at `conviction_card_preview.png` (regenerate with `python tools_preview_conviction.py`).

### Final verification (documented operating point)

| Basket | A | ± | T | Q | V | Band / directive |
|--------|---|---|---|---|---|------------------|
| **AGA.V** (spear) | **7.8** | 1.0 | 6.7 | 7.5 | 8.7 | STRONG ASYMMETRY · BELOW FLOOR — ACCUMULATE |
| URC.TO | 3.9 | 0.4 | 5.8 | 7.2 | 0.6 | WEAK / EXPENSIVE · UPSIDE SPENT |
| GMX.TO | 3.8 | 0.8 | 6.0 | 6.5 | 0.8 | WEAK / EXPENSIVE · STAND ASIDE |
| GROY | 3.5 | 0.4 | 5.8 | 6.9 | 0.0 | WEAK / EXPENSIVE · UPSIDE SPENT |

Only the genuinely asymmetric basket (price *below* its hard floor with multi-bagger upside) scores
high; cash-flowing ballast trading above its floor correctly falls away on the V pillar. **V stays the
heaviest pillar (0.45)** and **α drives most of T (4.62 of 6.65)**. The forensic gate caps a broken
balance sheet at ≤ 4.5 (JSF < 1.5 → 4.0; aggressive dilution / short runway → 4.5), and the confidence
ribbon widens with sparse data / wide scenario bands (±0.6 → ±1.7 → ±2.3) **without moving the score**.

---

## 8. How to use Conviction Mode

**What it is.** The default view. One card per high-conviction basket, ranked by the 0–10 **Asymmetry
Rating**. It answers a single question — *"is this a basket worth watching very closely?"* — and
deliberately carries **no** sizing / position-cap / ES95 / Kelly machinery (that lives behind the
**Detailed Analysis** toggle).

**Read a card top-to-bottom:**
1. **Rating + band + directive** — the headline. `BELOW FLOOR — ACCUMULATE` and `STRONG/PRIME` are the
   "watch closely / add" signals; `UPSIDE SPENT`, `STAND ASIDE`, `FORENSIC DECAY — AVOID` are step-back
   signals. The `±` ribbon tells you how firm the number is (wide = thin data or a wide scenario band).
2. **③ Valuation Asymmetry (V)** — the heart. Glance at the **ladder**: how far is the highlighted
   **PRICE** below the **BULL** target, and how close to / below the **FLOOR**? Price below floor with
   a fat bull is the prize setup.
3. **② Company Quality (Q)** — can it survive and execute? JSF (runway/dilution) + the resource
   checklist (grade · scale · jurisdiction · metallurgy · permitting) + management.
4. **① Macro Tailwind (T)** — is the regime behind this archetype right now (esp. α for explorers)?
5. **GATE chip** — if present, the balance sheet is the first problem; the rating is capped on purpose.

**Rule of thumb:** add/watch-closely when the rating is high *because* V is high (structurally
supported downside + real upside), the gate is clear, and the ribbon is tight. Treat a high rating
carried only by T or Q, or with a wide ribbon, as "interesting, verify" rather than "act".

**Key config (`v5_config.json → conviction_mode`):**

| Key | Meaning |
|-----|---------|
| `pillar_weights_by_archetype` | Per-archetype T/Q/V blend (V heaviest; option_convexity leans T). |
| `kappa_by_archetype` | How much T is driven by the archetype α vs raw regime (0.66 for explorers). |
| `q_weights` | forensic / asset-quality / management split inside Q. |
| `quality_lenses` | Mining checklist bands + weights (grade / scale / fraser / recovery / stage). |
| `rho_half`, `delta_floor`, `support_band` | V-pillar shape (payoff half-saturation, floor support). |
| `forensic_gate` | Hard-gate thresholds (JSF floor, aggressive-dilution, min-runway) and caps. |
| `confidence_ribbon` | Ribbon widths by data quality + scenario-spread multiplier. |
| `bands` | Rating → label thresholds. |
| `portfolio_metadata[ticker].management_score` | Analyst execution/track-record input (0–1). |

Every key is optional — omit the block to use the module defaults. Changes are config-only; no code
edits are needed to retune the rating.

---

---

## 9. Rating rebuild — archetype differentiation (the ballast fix)

The rating was producing incoherent results because **one lens (explorer asymmetry) was applied to
every archetype** — royalties/cyclicals scored 3–4 "WEAK/EXPENSIVE" purely for lacking a 5×-vs-floor
setup. The rebuild makes both the **pillar weights** and the **V-pillar measurement** archetype-aware.

**Per-archetype pillar weights**

| Archetype | T | Q | V | V lens |
|-----------|---|---|---|--------|
| `option_convexity` (explorers) | 0.33 | 0.22 | **0.45** | **asymmetry** (bull-vs-floor) |
| `commodity_cyclical` | 0.30 | **0.35** | 0.35 | value |
| `asset_light_yield` (royalties) | 0.15 | **0.55** | 0.30 | value |
| `pure_macro_delta` | **0.45** | 0.25 | 0.30 | value |

**Two V lenses**
- **asymmetry** (explorers): `bull-vs-REP-floor` payoff + floor support — explosive, multi-bagger upside
  over a solid floor is heavily rewarded.
- **value** (cash-flow assets): a **fair-value-centred** score — `value = 0.5 + 0.5·tanh((fair/price−1)/0.40)`
  (≈0.5 at fair value), blended with floor support and a **cash-flow stability** term (royalties 0.85,
  cyclicals 0.50). A quality royalty at fair value lands **mid-range (~5)**, not near zero. Directives use
  value-investor language (`QUALITY — CORE HOLD`, `BELOW FAIR VALUE — ACCUMULATE`, `FAIR VALUE — HOLD`),
  not explorer "trim" calls.

**Rebuilt barbell (operating point):**

| Basket | Archetype | A | Band | Directive |
|--------|-----------|---|------|-----------|
| **AGA.V** | option_convexity | **7.7** | STRONG ASYMMETRY | BELOW FLOOR — ACCUMULATE |
| **URC.TO** | asset_light_yield | **6.5** | BALANCED | FAIR VALUE — HOLD |
| **GROY** | asset_light_yield | **6.1** | BALANCED | FAIR VALUE — HOLD |
| **GMX.TO** | commodity_cyclical | **5.8** | BALANCED | BELOW FAIR VALUE — ACCUMULATE |

(Was: AGA.V 4.5, ballast 3.2–4.2, all "WEAK/EXPENSIVE".)

**Catalyst attribution hardening.** `match_ticker` now requires **whole-word** matches and ignores
ultra-generic fragments (< 5 chars), so a generic "gold mining sector" headline no longer mis-tags a
specific name; config aliases tightened to distinctive company/project names. Events older than the
freshness window are flagged **"(dated)"** on the (collapsed) catalyst strip; cross-feed duplicates are
merged by link **or** normalized headline + date.

All green: **189 Python + 11 Flutter; `flutter analyze` clean.**

---

---

## 10. Tuning round 2 — conviction lift, quality bands, ballast uplift

Three asks: lift clean ballast, let strong asymmetry reach 8.5–9.5 more readily, and tighten catalyst
accuracy.

**Conviction lift (non-linear aggregation).** A weighted average of T/Q/V is inherently conservative
(a 9.2 V is pulled down by a 6.0 T). The score now adds a bounded lift toward the *standout* pillar,
scaled by how **earned** it is — so high conviction can break the average ceiling without inflating
weak names:

$$ A = A_{\text{raw}} + s \cdot c \cdot \max(0,\ \text{anchor} - A_{\text{raw}}), \quad s = 0.65 $$

- **asymmetry mode:** `anchor = V`, `c = floor support` (downside structurally protected).
- **value mode:** `anchor = max(Q, V)`, `c = forensic cleanliness (JSF/4)`.

It never exceeds the anchor pillar; a premium name (support 0) or a forensically weak one (low JSF)
gets little/no lift. The lift is applied **before** the floor-aware gate.

**Value-mode uplift (clean royalties).** The fair-value center is raised (quality deserves a premium)
and the stability weight increased (`asset_light_yield` stability 0.90), so a clean producing royalty
at fair value sits in the 7s rather than ~5.

**Mode-aware band labels.** Cash-flow assets read on a quality scale (`PRIME QUALITY` / `HIGH QUALITY`
/ `SOLID-FAIR` / `RICH-WEAK` / `IMPAIRED`) instead of explorer asymmetry labels.

**Catalyst accuracy.** Freshness threshold tightened to 60 days (older → "(dated)"); a
`min_display_impact` filter drops trivial/neutral noise from the surfaced list; whole-word ticker
matching + tightened aliases prevent generic-headline misattribution; dedup by link **or** normalized
headline+date.

**Tuned barbell (operating point):**

| Basket | A | Band | Directive |
|--------|---|------|-----------|
| **AGA.V** (explorer) | **8.6** | PRIME CONVICTION | BELOW FLOOR — ACCUMULATE |
| **URC.TO** (royalty) | **7.1** | HIGH QUALITY | QUALITY — CORE HOLD |
| **GROY** (royalty) | **6.8** | SOLID / FAIR | FAIR VALUE — HOLD |
| **GMX.TO** (cyclical) | **6.3** | SOLID / FAIR | BELOW FAIR VALUE — ACCUMULATE |

(Round 1: 7.7 / 6.5 / 6.1 / 5.8. Original: 4.5 + ballast 3.2–4.2.)

All green: **189 Python + 11 Flutter; `flutter analyze` clean.**

---

[PHASE 7 AUDIT + NEW ASYMMETRY RATING PROPOSAL COMPLETE]
