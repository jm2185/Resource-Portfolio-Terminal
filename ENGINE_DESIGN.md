# CommodityEx Engine Design Reference Manual (v5.1)

This design manual details the mathematical formulas, first principles, and structural architecture of the **CommodityEx Monitor v5.1** core valuation and sizing engine.

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
