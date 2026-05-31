# CommodityEx Engine Design Reference Manual (v5.1)

This design manual details the mathematical formulas, first principles, and structural architecture of the **CommodityEx Monitor v5.1** core valuation and sizing engine.

---

## 0. v5.3 Phase 0 Structural Patches (supersedes the noted formulas below)

Three pro-cyclicality / bias defects were patched ahead of the Phase 4 valuation rebuild. Where these
conflict with the original formulas in later sections, **these supersede**. Full rationale and schemas
are in `PHASE4_ARCHITECTURE.md`.

1. **ADV liquidity cap → robust 90-session volume (supersedes §4).** The position liquidity cap is now
   denominated on a **90-session median** (config `adv_method`, EWMA alternative) of daily volume rather
   than a 10-day ADV. A 10-day average spikes in panics and pro-cyclically *expands* the dollar cap
   exactly when exit liquidity should be assumed scarcer; a 90-session median cannot be moved by a single
   spike. Applied to both the spear liquidity cap and the peer liquidity-weighting.

2. **CBA → Enterprise-Value normalization (supersedes §2.1).**
   $$\text{CBA} = \frac{\text{Current Quarter Burn} - \text{Prior Quarter Burn}}{\max(\text{EV floor},\ \text{Enterprise Value})}$$
   Dividing by Total Cash penalized micro-cap explorers running an intentionally lean treasury. EV $\gg$
   cash, so the gate moves from $0.15$ (fraction of cash) to $\approx 0.03$ (fraction of EV, config
   `max_burn_acceleration_ev_pct`). Falls back to the cash-based test + $0.15$ gate when EV is unavailable.

3. **MRI bounds → rolling percentile rank (supersedes the static bands in §1.2).** Each configured MRI
   component scores its live value by its **percentile rank within a trailing window** (default 5y) instead
   of a static min-max band, so the signal no longer saturates at $0/100$ once a price leaves its historic
   range (e.g. silver pinned at $100$ in the $\$70+$ regime). Components lacking $\ge$ `min_obs` cached
   observations fall back to the static norm, so a cold cache never blocks; with no history supplied the
   score is **identical** to the legacy static computation.

---

## 1. Macro Regime Index (MRI)

The Macro Regime Index (MRI, formerly BVS) is a regime-adjusted, five-dimensional index designed to evaluate systemic liquidity stress, yield curves, tail volatility, physical supply dynamics, and speculative capitulation.

The index yields a score on a scale of $[0, 100]$. Higher values represent acute systemic stress (defensive regime), while lower values indicate high-conviction deployment zones (risk-on expansion).

### 1.1 Min-Max Normalization Function
To scale heterogeneous financial datasets onto a uniform $[0, 100]$ interval:

$$\text{norm}(x, \text{low}, \text{high}) = \max\left(0, \min\left(100, \frac{x - \text{low}}{\text{high} - \text{low}} \times 100\right)\right)$$

### 1.2 Five Regimes of the MRI

1. **Liquidity & FX Score ($L$)**: Measures the aggregate tightening of dollar funding and credit stress.
   $$L = 0.30 \times \text{norm}(\text{DXY} - 100, -5, 8) + 0.20 \times \text{norm}(\text{TED}, 0.1, 0.9) + 0.30 \times \text{norm}(Y_{\text{real}}, 0.5, 3.5) + 0.20 \times \text{norm}(\text{DXY}_{\text{mom}}, -2.0, 2.0)$$
   Where:
   - $Y_{\text{real}}$ is the 10Y US Real Yield (TIPS).
   - $\text{DXY}_{\text{mom}}$ is the 10-day momentum of the US Dollar Index.

2. **Yield & Curve Score ($Y$)**: Tracks interest rate curves and short-rate pressure.
   $$Y = 0.50 \times \text{norm}(Y_{30\text{Y}} - Y_{10\text{Y}}, -0.5, 1.5) + 0.50 \times \text{norm}(Y_{10\text{Y}}, 3.0, 5.5)$$

3. **Systemic Stress & Volatility Score ($V$)**: Measures tail-risk and credit default swap swaps.
   $$V = 0.50 \times \text{norm}(\text{VIX}, 12, 35) + 0.50 \times \text{norm}(\text{Spreads}, 2, 7)$$
   Where $\text{Spreads}$ represents high-yield corporate option-adjusted spreads.

4. **Physical Commodity Regimes ($C$)**: Tracks physical commodity structural strength via industrial copper/gold and silver spot ratios.
   $$C = 0.60 \times \text{norm}\left(\frac{\text{Copper}}{\text{Gold}}, 0.0014, 0.0022\right) + 0.40 \times \text{norm}\left(\frac{\text{Spot Silver}}{30}, 0.8, 1.4\right)$$

5. **Speculative Capitulation Score ($S$)**: A contrarian sentiment indicator built from net speculative long contracts in CFTC Commitment of Traders (COT) reports.
   $$S = \text{norm}(\text{CFTC}_{\text{NetLong}}, -15000, 85000)$$

### 1.3 Blended MRI Formula
The final index blends the five dimensions linearly:

$$\text{MRI} = (L \times 0.30) + (Y \times 0.20) + (V \times 0.20) + (C \times 0.15) + (S \times 0.15)$$

---

## 2. Conditional Forensics (Junior Shield Evaluator)

To prevent structural valuation decay, v5.1 introduces conditional accounting forensics. Pre-revenue explorers are judged on cash-burn efficiency, while producers are judged on accrual-basis accounting quality.

### 2.1 Pre-Revenue Explorer Evaluation (type == "explorer")

For explorers, operating accrual ratios are irrelevant. The engine checks cash burn acceleration and QoQ share dilution.

1. **Cash Burn Acceleration (CBA)**: Evaluates whether cash outflow is expanding faster than capital buffers.
   $$\text{CBA} = \frac{\text{Current Quarter Burn} - \text{Prior Quarter Burn}}{\text{Total Cash}}$$
   Where:
   - $\text{Burn} = -\text{CFO}$ (negative cash flow from operations).
   - $\text{Total Cash} = \text{Cash and equivalents}$ from the balance sheet.
   
   *Rule*: If $\text{CBA} > 0.15$, deduct 1.0 from the Junior Forensic Shield (JSF) score (CBA Test Fails).

2. **Weighted Dilution Sieve**: Explorers suffer heavy valuation decay from share count expansion. The weight of the **Dilution Sieve** is expanded to **35%** of the total penalty risk.
   $$\text{weighted\_penalty} = 0.35 \times P_{\text{dilution}} + 0.2167 \times (P_{\text{runway}} + P_{\text{cba}} + P_{\text{sga\_drag}})$$
   $$\text{Penalty Factor} = 1.0 - 0.30 \times \text{weighted\_penalty}$$
   Where $P_{\text{test}} \in \\{0, 1\\}$ is $1$ if the test fails and $0$ if it passes.

### 2.2 Producing Asset Evaluation (type == "royalty" or "producing")

Producers are judged on operating cash flows and accruals:

1. **Sloan CFO Accrual Ratio**: Checks whether net earnings are backed by true cash flows.
   $$\text{Sloan}_{\text{CFO}} = \frac{\text{Net Income} - \text{CFO}}{\text{Total Assets}}$$
   *Rule*: If $\text{Sloan}_{\text{CFO}} > 0.05$, deduct 1.0 from JSF score.

2. **Sloan Balance Sheet Accrual Ratio**:
   $$\text{Sloan}_{\text{BS}} = \frac{(\Delta \text{Current Assets} - \Delta \text{Cash}) - \Delta \text{Current Liabilities} - \text{D&A}}{\text{Total Assets}}$$

3. **Equal Sieve Weighting**:
   $$\text{Penalty Factor} = 0.70 + 0.30 \times \left(\frac{\text{JSF Score}}{4.0}\right)$$

---

## 3. Symmetric Inferred Haircuts

To prevent asset value inflation, v5.1 mandates mathematical symmetry. Resource ounces are penalized equally across the peer universe and the target portfolio.

### 3.1 Mathematical Haircut Formula
For any explorer resource calculation, ounces classified under the "Inferred" confidence tier are penalized by a strict **50% haircut** before multiple application:

$$\text{Effective Ounces} = (\text{Measured \& Indicated Ounces} \times 1.0) + (\text{Inferred Ounces} \times 0.50)$$

This is implemented using project-specific confidence factors:

$$\text{Effective Ounces} = \text{Total Ounces} \times \left(R_{\text{MI}} \times 1.0 + (1.0 - R_{\text{MI}}) \times 0.50\right)$$

Where $R_{\text{MI}}$ is the Measured & Indicated percentage of the target project resource base.

---

## 4. Dynamic ADV Sizing Cap

To prevent illiquidity trapping under high macro volatility, the ADV position sizing cap scales down inversely as macro stress rises.

$$\text{Cap Percentage} = \max\left(0.02, 0.15 \times \left(1.0 - \frac{\text{MRI}}{100.0}\right)\right)$$

$$\text{Max Position Capital (CAD)} = \text{Average Daily Volume (10D)} \times \text{Cap Percentage} \times \text{Price}$$

*Implication*: As sovereign stress ($\text{MRI}$) approaches $100$, exit liquidity limits contract automatically to a defensive **2%** ADV cap, shielding the portfolio from liquidity locks.

---

## 5. Portfolio Sizing (Fractional Kelly, ES95 Throttle, Hard Barbell Ceiling)

The `PortfolioSizer` converts the blended implied edge into a constrained capital target. v5.1 hardens three properties: dimensional coherence, tail-risk responsiveness, and a non-negotiable concentration ceiling.

### 5.1 Dimensionally-Coherent Fractional Kelly

The continuous Kelly criterion is $f^{*} = \mu / \sigma^{2}$, which is only valid when the expected return $\mu$ and variance $\sigma^{2}$ share a horizon. The blended implied edge $u_{\text{implied}}$ is a **total** convergence-to-intrinsic return, whereas portfolio variance is **annualized** ($\sigma = \text{std}(r_{\text{daily}}) \times \sqrt{252}$). The total edge is therefore first amortized into an expected annualized drift over the assumed convergence window:

$$\mu_{\text{ann}} = \frac{u_{\text{implied}}}{T_{\text{conv}}}, \qquad T_{\text{conv}} = \max\left(0.25, \frac{\text{intrinsic\_convergence\_months}}{12}\right)$$

$$\text{Raw Kelly} = \frac{\mu_{\text{ann}}}{\max(0.04,\ \sigma_{\text{port}}^{2})} \times \text{fractional\_kelly}$$

The default convergence window is **18 months**. This removes the prior unit mismatch where a one-shot upside was divided by a per-period variance.

### 5.2 ES95 Tail-Risk Throttle

Aggregate leverage is scaled down as the **daily** 95% Expected Shortfall deteriorates (negative = loss), fulfilling the documented ES95 → Sizer relationship:

$$\text{throttle} = \begin{cases} 1.0 & \text{ES} \ge \text{no\_penalty\_pct} \\[4pt] 1.0 - r_{\max}\cdot \dfrac{\text{no\_penalty\_pct} - \text{ES}}{\text{no\_penalty\_pct} - \text{max\_penalty\_pct}} & \text{otherwise} \end{cases}$$

Defaults: `no_penalty_pct = -5%`, `max_penalty_pct = -12%`, `max_reduction` $r_{\max} = 0.5$ (leverage halved at or beyond $-12\%$ daily ES). Thresholds mirror the Health Radar ES bands.

$$\text{Target Leverage} = \min(\text{Raw Kelly},\ L_{\max}(\text{VIX})) \times \text{corr\_penalty} \times \text{throttle}$$

### 5.3 Hard Barbell Ceiling

The single-position guardrails are absolute. The alignment flexibility multiplier ($1.25\times$ when MRI $< 45$ and JSF $\ge 3.5$) loosens only the liquidity/ADV cap; it is explicitly clamped out of the structural caps:

$$\text{limit}_{\text{eff}} = \min(\text{limit}_{\text{base}} \times \text{flex},\ \text{limit}_{\text{base}})$$

Because the spear carries a $0.60$ portfolio weight against a $0.60$ position cap, this guarantees the spear (AGA.V) can **never** exceed **60%** of portfolio capital, preserving the 60/40 barbell under all regimes.

---

## 6. Continuity & Smoothing (v5.1 Phase 2)

To eliminate cliff/saturation artifacts and align model behavior with reality, three formulas were made smooth and monotonic. Each was calibrated to preserve the live operating point (silver $\approx \$75.6$, $Y_{30} \approx 4.99$) so the refactor does not silently move live valuations.

### 6.1 Smooth Jurisdiction Uplift
The discontinuous gate $(\text{spot\_ag} > 50 \Rightarrow 1.35\ \text{else}\ 1.15)$ is replaced by a logistic ramp:

$$\text{uplift} = \text{low} + \frac{\text{high} - \text{low}}{1 + e^{-k(\text{spot\_ag} - \text{center})}}$$

Defaults: $\text{low}=1.15,\ \text{high}=1.35,\ \text{center}=50,\ k=0.30$. At $\$50$ the value is the midpoint $1.25$; it asymptotes to $1.15$ / $1.35$ and removes the $\sim17\%$ valuation jump on a one-cent silver move.

### 6.2 Smooth Capital-Cost Discount
The hinge $\max(0.40,\ 1.0 - 0.12\,(Y_{30}-4.0))$ gated at $Y_{30}>4.0$ is replaced by softplus-smoothed hinges (softplus $\zeta_\beta(x) = \tfrac{1}{\beta}\ln(1+e^{\beta x})$):

$$\text{discount} = \text{floor} + \zeta_{\beta_f}\!\Big(\big(1 - \text{slope}\cdot\zeta_{\beta_o}(Y_{30}-\text{onset})\big) - \text{floor}\Big)$$

Defaults: $\text{onset}=4.0,\ \text{slope}=0.12,\ \text{floor}=0.40,\ \beta_o=8,\ \beta_f=25$. This removes the slope-kinks at the onset and the floor while preserving the live value $(Y_{30}=4.99 \Rightarrow 0.8808)$ to 4 dp.

### 6.3 Continuous, Convex ES95 Health Penalty
The discrete two-step lookup (capped at $-1.0$) is replaced by a continuous convex penalty anchored at the documented reference point:

$$\text{ES Penalty} = k \cdot \big(\max(0,\ -\text{ES} - \text{free})\big)^{\gamma}, \qquad k = \frac{\text{ref\_penalty}}{(\text{ref} - \text{free})^{\gamma}}$$

Defaults: $\text{free}=5\%,\ \text{ref}=10\%,\ \text{ref\_penalty}=1.0,\ \gamma=1.5 \Rightarrow k \approx 0.0894$. Behavior: $-5\%\to0$, $-10\%\to1.0$ (anchor preserved), $-15\%\to2.83$, $-30\%\to11.18$. The penalty is **uncapped** so deep tails dominate; the Health Rating itself remains clamped to $[1.0, 10.0]$.
