# CommodityEx Monitor v5.1 // METRIC COMPASS & GLOSSARY
This document serves as the master quant educator reference manual for the CommodityEx Monitor personal investment system. It details the first-principles, mathematical formulas, strategic barbell use cases, metric relationships, and actionable signals for every key metric displayed across both the Streamlit and Flutter views.

---

## 1. Macro Regime Index (MRI)

### First-Principles Definition
The **Macro Regime Index (MRI)** measures the aggregate pressure and liquidity stress inside the global sovereign debt and eurodollar banking system. In reality, junior resource explorers depend heavily on external capital injections and loose credit availability. When global dollar liquidity tightens, banking systems constrict, risk capital retreats, and speculative asset valuations decay—regardless of drill results. The MRI serves as our system's "Macro Weather vane," identifying if we are in an expansionary risk-on regime or a capital-preservation risk-off regime.

### How It Is Calculated Here
The MRI is a five-dimensional, min-max normalized score scaled onto a uniform $[0, 100]$ interval:
$$\text{MRI} = (L \times 0.30) + (Y \times 0.20) + (V \times 0.20) + (C \times 0.15) + (S \times 0.15)$$
Where:
- **Liquidity & FX ($L$)**: Synthesizes DXY, the SOFR Spread (replacing TED), and 10Y US Real Yields.
- **Yield Curve ($Y$)**: Tracks curve steepening ($30\text{Y} - 10\text{Y}$) and absolute interest rate pressure.
- **Systemic Volatility ($V$)**: Blends high-yield corporate option-adjusted spreads and the VIX Index.
- **Commodity Ratio ($C$)**: Blends Copper/Gold ratio (industrial vs. monetary battery) and Spot Silver levels.
- **Sentiment ($S$)**: Contrarian speculator positioning calculated from CFTC net long contract positioning.

### Project-Specific Use Case & Actionability
The MRI is used to scale down our aggregate barbell portfolio exposure as systemic danger mounts.
- *Actionable Example*: If the Fed tightens eurodollar funding causing the **SOFR Spread** to spike to 0.75% and the **DXY** to surge above 104, the MRI will climb above **65**. The Health Radar immediately triggers a **DEFENSIVE PROTECT CAPITAL** directive. We freeze new purchases of our high-grade spear asset (**AGA.V**) and allow capital to accumulate inside stable cash or dividend-producing ballasts (**GMX.TO**, **GROY**), protecting dry powder from a liquidity-driven dilution trap.

### Key Relationships
1. **Inversely modulates the ADV Sizing Cap**: A rising MRI restricts the volume percentage we can trade daily to avoid market impact.
2. **Directly penalizes the Health Rating**: A higher MRI represents a high-uncertainty macro backdrop, lowering total rating integrity.
3. **Caps the Discovery Premium**: Under a high MRI, the market ignores high-grade exploration success; the dynamic re-rating scalar is mathematically capped.

### Warning / Opportunity Signals
- **Opportunity (<40)**: "Green Light." Systemic liquidity is abundant, credit spreads are narrow, and speculative net-shorts are capitulating. Maximum sizer limits allowed.
- **Warning (>65)**: "Red Light." Systemic dollar funding stress is acute. Restrict position sizing ceilings and accumulate ballast assets.

---

## 2. Junior Survival Forensics (JSF) & Cash Burn Acceleration (CBA)

### First-Principles Definition
Pre-revenue exploration juniors like **AGA.V** do not generate income; they are essentially "capital burn engines." Their intrinsic survival relies entirely on the rate at which they consume their cash reserves (runway) and whether management is accelerating spending (accrual expansion) or expanding the share count, diluting existing shareholders to fund overhead. The **Junior Survival Forensics (JSF)** score acts as our forensic shield, inspecting the balance sheet to identify if a developer is allocating capital productively in the ground or destroying equity value through corporate bloat.

### How It Is Calculated Here
The JSF is a discrete 0-4 point checklist:
1. **Runway Sieve**: Cash component divided by monthly operating cash burn must be $\ge 18.0$ months.
2. **Accrual/Burn Sieve**: Cash Burn Acceleration (CBA) must be $\le 15\%$ (or Sloan $\le 5\%$ for producers).
   $$\text{CBA} = \frac{\text{Current Quarter Operating Burn} - \text{Prior Quarter Operating Burn}}{\text{Total Cash}}$$
3. **Dilution Sieve**: QoQ share count growth must be $< 2\%$.
4. **Corporate Drag Sieve**: Quarterly SG&A expenses must represent $< 30\%$ of total cash burn.

### Project-Specific Use Case & Actionability
Protects the barbell from holding a junior during a forced, dilutive capital raise.
- *Actionable Example*: If AGA.V's quarterly financial statements show a cash runway dropping to **10.5 months** due to high G&A burn, and share count expands by **6.5% QoQ**, the JSF Score drops to **1.0/4.0**. The engine immediately triggers the priority **MITIGATE ACCOUNTING STRESS**. This applies a strict **30% forensic penalty** on the IS-IAI valuation of AGA.V, slashing its intrinsic value and halting all buying orders to prevent an equity dilution trap.

### Key Relationships
1. **Modulates the Forensic Penalty factor**: Scales the IS-IAI value down linearly as the score decays:
   $$\text{Forensic Penalty} = 1.0 - 0.30 \times \text{weighted\_penalty}$$
2. **Directly impacts the Health Rating**: The forensics multiplier is a heavy penalty weight on composite safety.
3. **Alters Kelly target allocation limits**: Decayed scores reduce the fractional Kelly multiplier.

### Warning / Opportunity Signals
- **Opportunity (4.0)**: "High Integrity." The explorer has a cash runway exceeding 18 months, share dilution is zero, and cash burn is controlled. Buy orders fully unlocked.
- **Warning (<3.0)**: "Balance Sheet Decay." Corporate drag is bloated and runway is short. Equity dilution is imminent. Cease accumulation.

---

## 3. Model Health Rating (H)

### First-Principles Definition
The **Health Rating** is a synthetic, composite integrity score representing the reliability and signal-to-noise ratio of our valuation outputs. In quant modeling, a model is only as good as its underlying inputs. If our data pipelines are using stale cached prices, macro regimes are highly volatile, or corporate balance sheets are decaying, the "signal quality" of our computed intrinsic value degrades. The Health Rating informs the investor whether to treat model outputs as high-conviction buying targets or high-uncertainty boundaries.

### How It Is Calculated Here
The rating starts at a perfect **10.0** and is penalized dynamically:
$$\text{Health Rating} = 10.0 - \text{JSF Penalty} - \text{Macro Volatility Penalty} - \text{Stale Pipeline Penalty} - \text{ES95 Tail Penalty}$$
- **JSF Penalty**: $(4.0 - \text{JSF Score}) \times 1.25$
- **Macro Penalty**: $(\text{MRI} / 100) \times 1.5$
- **Pipeline Penalty**: $-2.0$ points if yfinance or API inputs are stale.
- **Tail Penalty**: Up to $-1.0$ point if the worst-case 95% Expected Shortfall exceeds risk bounds.

### Project-Specific Use Case & Actionability
Establishes our **Tactical Safety Ceiling** to protect capital from model over-reliance.
- *Actionable Example*: If AGA.V's intrinsic value is computed as **$4.18 CAD** while trading at **$0.72 CAD**, the model reports a massive "Implied Edge." However, if yfinance fetches are degraded due to server dropouts, and the MRI is elevated at **75.0**, the Health Rating drops to **4.5/10 (Red Warning)**. The terminal immediately caps the actual target deployment using the rating as a multiplier:
  $$\text{Tactical Ceiling} = \text{Target Capital} \times \frac{\text{Health Rating}}{10.0}$$
  This restricts our actual buy orders to a fraction of the raw sizer target, protecting us from deploying capital into stale or volatile assumptions.

### Key Relationships
1. **Derived from JSF, MRI, and ES95**: The final mathematical filter synthesizing forensics, macro stress, and tail risk.
2. **Sets the Sizing Safety Ceiling**: Constrains the raw sizer output.
3. **Drives tactical directives**: A rating $\ge 8.5$ generates the "HIGH CONVICTION DEPLOY" directive; $<6.0$ triggers "HIGH NOISE EXTREME CAUTION."

### Warning / Opportunity Signals
- **Opportunity (>=8.5)**: "High Conviction." Fresh data pipelines, pristine balance sheets, and low macro stress. The calculated intrinsic edge is highly actionable.
- **Warning (<6.0)**: "High Noise." Stale caching active, extreme macro volatility, or forensic failures. Treat computed values as speculative upper limits only.

---

## 4. Resource & Permitting Replacement Floor (REP Floor)

### First-Principles Definition
The **REP Floor** represents the stressed, hard-liquidation cost of creating the junior asset from scratch. Discovering high-grade silver, drilling it out to define a geological resource, conducting metallurgical testing, and moving through years of permitting requires millions of dollars in sunk costs. If an explorer's market capitalization drops below this cash and replacement value, the business is trading at a "sunk cost arbitrage." It represents a concrete margin of safety where the buyer gets all the defined silver ounces in the ground and historical exploration success for free.

### How It Is Calculated Here
$$\text{REP Floor} = \frac{\text{Cash Reserves} + (\text{Effective Ounces} \times \text{Stressed Resource Value/oz}) + \text{Permitting Infra sunk costs}}{\text{Shares Outstanding}} \times \text{conservatism\_scalar}$$
Where:
- **Effective Ounces** utilizes a symmetric 50% haircut on Inferred resources:
  $$\text{Effective Ounces} = (\text{Measured \& Indicated} \times 1.0) + (\text{Inferred Ounces} \times 0.50)$$
- **Stressed Resource Value/oz** is conservative ($0.45/oz silver equivalent).
- **Conservatism Scalar** is set to $0.88$ to build in a margin of safety.

### Project-Specific Use Case & Actionability
Identifies the ultimate structural downside limit and highest-conviction buying zones.
- *Actionable Example*: During a broad resource market capitulation, AGA.V's share price drops to **$0.72 CAD**. Our engine computes a **REP Floor** of **$0.824 CAD** based on its $15M cash treasury, permitting progress at its core asset, and 100M effective silver ounces. Since the market price is below the stressed liquidation floor, the terminal triggers **BUY UNDER FLOOR**. We aggressively deploy dry powder into the spear asset, knowing we are acquiring high-grade resources at a discount to their physical creation cost.

### Key Relationships
1. **Forms the base valuation support**: Contributes **15% weight** to the final AGA.V Intrinsic Value synthesis.
2. **Directly scales down with share dilution**: Outstanding share count expansions dilute the per-share asset floor.
3. **Acts as a buying gate filter**: Buying below the floor triggers automatic "BUY" overrides in the execution sieve even if broad margins are tight.

### Warning / Opportunity Signals
- **Opportunity (Price <= REP Floor)**: "Sunk Cost Arbitrage." Market cap has collapsed below cash + stressed asset replacement value. Maximum buying margin of safety.
- **Warning (Price > 2.5x REP Floor)**: "Premium Valuation." The market is pricing in significant future exploration hopes. Downside protection is reduced; rely more heavily on the IS-IAI multiple.

---

## 5. Expected Shortfall (ES95)

### First-Principles Definition
While standard portfolio volatility measures generic swings (standard deviation), it assumes financial returns are normally distributed. In reality, junior resource markets suffer from "fat tails" and extreme catastrophic selloffs. **Expected Shortfall at 95% Confidence (ES95)** measures "tail risk." It answers the critical question: *“In the worst 5% of trading days, what is the average percentage loss we should expect to suffer?”* It is our forensic measure of downside tail exposure.

### How It Is Calculated Here
Derived historically from the joint return covariance matrix of our barbell components:
1. Extract the past 60 trading days of returns for AGA.V, GROY, URC.TO, and GMX.TO.
2. Reconstruct the synthetic historical portfolio returns based on current allocation weights.
3. Sort the daily returns from worst to best.
4. Calculate the average return of the worst 5% of outcomes (the tail).

### Project-Specific Use Case & Actionability
Restricts aggregate portfolio leverage during periods of rising joint correlations and asset stress.
- *Actionable Example*: During a global systemic credit shock, broad correlation coefficients converge toward 1.0, and daily volatility spikes. The computed **ES95** of our barbell rises from a stable **-3.5%** to **-8.2%** (loss of 8.2% in a single day). The Health Radar flags **ELEVATED TAIL RISK** and applies a direct penalty to the Health Rating, forcing our capital sizer to scale down the raw target exposure.

### Key Relationships
1. **Directly penalizes the Health Rating**: Extreme tail losses signal high noise and lower overall system integrity.
2. **Derived from joint historical correlations**: Spikes when the diversification benefits of the barbell break down (e.g. during liquidity liquidation events).
3. **Guides aggregate leverage constraints**: Limits Kelly multiplier scaling.

### Warning / Opportunity Signals
- **Opportunity (ES95 > -4.0%)**: "Contained Tail Risk." Barbell components are decorrelated, and tail risk is bounded. Normal leverage ratios allowed.
- **Warning (ES95 <= -6.0%)**: "Tail Expansion." Severe downside exposure. Reduce target sizer allocations and tighten position exit liquidity caps.

---

## 6. Average Daily Volume Sizing Cap (ADV Cap)

### First-Principles Definition
Pre-revenue juniors like **AGA.V** are highly illiquid. If an investor accumulates a position that represents a large percentage of the daily trading volume, they become "trapped." They cannot sell the position during a crisis without causing massive downward price pressure, destroying their own equity. The **ADV Cap** represents our dynamic "exit liquidity filter." It calculates the maximum dollar allocation we can deploy while guaranteeing we can fully exit the position within a few trading days without moving the tape.

### How It Is Calculated Here
$$\text{Cap Percentage} = \max\left(0.02, 0.15 \times \left(1.0 - \frac{\text{MRI}}{100.0}\right)\right) \times \text{flexibility\_mult}$$
$$\text{ADV Cap (CAD)} = \text{10-Day Average Daily Volume} \times \text{Cap Percentage} \times \text{Spot Price}$$
Where:
- **Cap Percentage** starts at a standard $15\%$ and scales down to $2\%$ as the macro stress index (MRI) approaches $100$.
- **Flexibility Multiplier** is $1.25$ if the engine is "aligned" (MRI < 45 and JSF $\ge 3.5$), granting additional liquidity allowance under pristine regimes.

### Project-Specific Use Case & Actionability
Sets the ultimate absolute maximum position constraint in CAD to prevent liquidity traps.
- *Actionable Example*: If AGA.V's 10-day Average Daily Volume is 150,000 shares at a price of **$0.72 CAD**, and broad macro conditions are stable (MRI = 30.0), the cap percentage scales to **10.5%**, resulting in an **ADV Cap of $11,340 CAD**. If our raw sizer target recommends a deployment of **$15,000 CAD**, the engine's capital waterfall detects that the target exceeds exit liquidity limits. It clamps the actionable deployment to **$11,340 CAD**, preventing us from becoming trapped.

### Key Relationships
1. **Inversely proportional to the MRI**: As broad sovereign liquidity tightens, exit channels contract dynamically to protect the portfolio.
2. **Exposed as the final sieve inside the Capital Sizing Waterfall**: Clamps the raw Kelly allocation to establish the concrete target deployment.
3. **Modulated by Alignment**: Pristine balance sheets and favorable macro regimes expand the liquidity limit.

### Warning / Opportunity Signals
- **Opportunity (Cap percentage > 12%)**: "Liquidity Abundance." Low macro stress allows normal sizing targets.
- **Warning (Cap percentage <= 3%)**: "Exit Constriction." High macro stress. Dynamic caps are severely restricted to protect against liquidity freezes. Cease new purchases.

---

## 7. Real Option Value (ROV)

### First-Principles Definition
Silver is not just an industrial metal; it is a monetary asset and a highly convex call option on the debasement of fiat currency. When real interest rates (nominal interest rates minus inflation) drop deep into negative territory, holding cash guarantees a loss of purchasing power. Capital rushes into physical monetary assets. The **Real Option Value (ROV)** measures the convex, non-linear optionality premium that we assign to silver developers. It represents the "monetary battery premium" that investors are willing to pay for torque during periods of monetary repression.

### How It Is Calculated Here
The ROV premium modulates a base value ($1.18x$ default) based on 10Y US Real Yields and VIX:
$$\text{ROV} = \text{rov\_default} \times (1.0 + \text{Negative Yield Premium}) \times (1.0 + \text{Volatility Premium})$$
Where:
- **Negative Yield Premium**: $\min\left(0.50, \max\left(0.0, 1.0 - \text{Real Yield}\right) \times 0.25\right)$.
- **Volatility Premium**: $\max\left(0.0, \left(\text{VIX} - 20\right) \times 0.50\right)$.

### Project-Specific Use Case & Actionability
Justifies paying a premium over pure discounted cash flows during macro-monetary stress.
- *Actionable Example*: If nominal interest rates are frozen at **4.5%** while inflation surges to **7.0%**, the US Real Yield falls to **-2.5%**. The ROV premium automatically expands from its base **1.18x** to **1.62x**. This increases the intrinsic value of AGA.V, justifying accumulating the developer at a premium because the macro regime has entered a severe "financial repression" phase where monetary battery assets are highly rewarded.

### Key Relationships
1. **Driven by Real Yields and VIX**: High volatility and negative real yields expand option value.
2. **Contributes 15% weight to Intrinsic synthesis**: Blends optionality with resource fundamentals.
3. **Interacts with spot silver momentum**: Tends to lead broad breakouts in physical silver pricing.

### Warning / Opportunity Signals
- **Opportunity (ROV >= 1.40x)**: "Convexity Surge." Real interest rates are deeply negative or volatility is high. Optionality premium is active; accumulate barbell torque.
- **Warning (ROV < 1.18x)**: "Optionality Decay." Rising positive real yields increase the opportunity cost of holding silver. Restrict premium valuations.

---

## 8. Peer EV/oz Multiple

### First-Principles Definition
The stock market rarely values pre-development mineral assets on discounted cash flows, as production is years away. Instead, they are valued on a comparative relative basis: *“How much is the market paying per ounce of silver in the ground for similar developers in safe jurisdictions?”* This is measured as **Enterprise Value per Ounce (EV/oz)**. The **Peer EV/oz** establishes the market-clearing multiple for in-situ resources. It identifies if the broad sector is undergoing accumulation or liquidation.

### How It Is Calculated Here
Rather than a simple average, the engine calculates a **liquidity-weighted, risk-adjusted Comp average**:
$$\text{Comp EV/oz} = \frac{\sum \left(\text{Adjusted EV/oz}_i \times \text{ADV\_CAD}_i\right)}{\sum \text{ADV\_CAD}_i}$$
Where:
$$\text{Adjusted EV/oz}_i = \frac{\text{Enterprise Value}_i}{\text{Effective Ounces}_i} \times (1.0 - \text{Jurisdiction Risk}_i) \times \text{Stage Multiplier}_i$$
- **Effective Ounces** uses the symmetric 50% inferred resource haircut.
- **Stage Multiplier** scales values based on development stage (e.g. PEA vs. Feasibility).
- **ADV_CAD** weights the comps by trading liquidity to prevent tiny, manipulated micro-caps from distorting the multiple.

### Project-Specific Use Case & Actionability
Establishes the relative valuation benchmark to identify sector mispricings.
- *Actionable Example*: If massive institutional silver inflows push the Comp EV/oz multiple from a depressed **$1.50 CAD/oz** up to **$3.50 CAD/oz**, the computed In-Situ valuation (**IS-IAI**) of AGA.V automatically climbs. This raises its intrinsic value, signaling that the entire sector's "tide is rising," and we can raise our buying target limits accordingly.

### Key Relationships
1. **Directly multiplies effective ounces in IS-IAI**: The core multiple driver of resource asset value.
2. **Informs the Discovery Premium**: High comps suggest the market is eagerly rewarding exploration ounces.
3. **Liquidity-weighted**: Dominated by high-volume, standard sector leaders to establish high-integrity multiples.

### Warning / Opportunity Signals
- **Opportunity (Comp EV/oz < $1.80 CAD/oz)**: "Sector Under-accumulation." Silver resources are trading at massive structural discounts. High margins of safety.
- **Warning (Comp EV/oz > $4.50 CAD/oz)**: "Sector Overheating." The sector is pricing in heavy premium assumptions. Reduce new entries; focus allocations strictly on assets trading below their REP Floor.

---

## 9. Dynamic AISC Uplift

### First-Principles Definition
**All-In Sustaining Costs (AISC)** represent the real-world operational cost of extracting an ounce of silver. In mining, major cost drivers are energy, steel, labor, and diesel. If crude oil prices surge, the energy input cost of running haul trucks, mills, and smelters rises rapidly. The **AISC Uplift** dynamically models this cost inflation. It ensures that our valuation models are "regime-aware" and do not assume fixed margins during an inflationary commodity shock.

### How It Is Calculated Here
$$\text{Dynamic AISC} = \text{Base Industry AISC} + \max(0, \text{WTI Crude Oil Price} - 80.0) \times 0.15$$
Where:
- **Base Industry AISC** is pegged at **$18.50/oz** for silver developers.
- **WTI Crude Oil Price** acts as the primary energy proxy. Every $1.00 increase in WTI above $80/oz expands the AISC by **$0.15/oz**.

### Project-Specific Use Case & Actionability
Prevents overestimating mine profit margins during energy crises.
- *Actionable Example*: If WTI Crude Oil spikes to **$110.00/bbl**, the AISC Uplift calculates a dynamic cost increase of:
  $$(110.0 - 80.0) \times 0.15 = +\$4.50/oz$$
  This pushes the dynamic AISC from $18.50 to **$23.00/oz**. The engine's **phi margin** collapses, reducing the **Discovery Premium** and lowering the intrinsic value of AGA.V. This prevents us from overpaying for resources during a cost-inflation squeeze that would render a development project uneconomic.

### Key Relationships
1. **Modulates phi profit margins**: Reduces dynamic profitability indices.
2. **Constrains the Discovery Premium**: High WTI costs compress the re-rating scalar.
3. **Driven by WTI Crude Oil Price**: Links energy markets directly to precious metal development valuations.

### Warning / Opportunity Signals
- **Opportunity (Dynamic AISC < $20.00/oz)**: "Stable Margins." Low energy costs preserve high profit margins for silver assets.
- **Warning (Dynamic AISC >= $24.00/oz)**: "Margin Squeeze." Energy cost inflation is severely eroding the economic viability of development projects. Exercise extreme caution on pre-revenue assets.

---

## 10. Futures Term Structure (Physical Stress Premium)

### First-Principles Definition
Under normal market conditions, commodity futures curves are in **Contango**—meaning future prices are higher than spot prices to account for the storage and interest costs of holding physical metal. However, when immediate physical demand is acute, or refinery supplies are exhausted, the curve enters **Backwardation** (Month 1 futures price is higher than Month 6 futures). This signals intense, structural physical tightness in the spot market. The **Term Structure** metric acts as our physical spot stress indicator.

### How It Is Calculated Here
The engine monitors the physical stress and backwardation gradient:
$$\text{If } M_1\text{ Price} > M_6\text{ Price} \implies \text{PHYSICAL\_STRESS} = \text{True}$$
$$\text{Uplift Premium} = \min\left(0.25, \max\left(0.0, \frac{M_1\text{ Price} - M_6\text{ Price}}{M_1\text{ Price}}\right) \times 5.0\right)$$
This premium directly expands the **Jurisdiction Uplift** multiplier applied to effective resource ounces:
$$\text{Adjusted Jurisdiction Uplift} = \text{Jurisdiction Uplift} \times (1.0 + \text{Uplift Premium})$$

### Project-Specific Use Case & Actionability
Rewards asset valuations with a spot supply premium during intense physical deficits.
- *Actionable Example*: If spot silver Month 1 futures rise to **$76.50/oz** while Month 6 futures are trading at **$71.20/oz**, the curve enters steep backwardation. The engine calculates an **Uplift Premium of 17.3%**. This automatically raises the valuation multiplier on AGA.V's resource ounces, reflecting that its physical assets are becoming exponentially more valuable due to immediate supply deficits.

### Key Relationships
1. **Directly multiplies the Jurisdiction Uplift**: Expands the IS-IAI asset multiple during backwardation.
2. **Triggers the PHYSICAL_STRESS status flag**: Signals intense immediate physical demand.
3. **Informs contrarian speculative signals**: Backwardation during rising net shorts represents a severe physical squeeze setup (highly bullish).

### Warning / Opportunity Signals
- **Opportunity (Backwardation Active)**: "Physical Supply Squeeze." Spot metal is trading at a premium to futures. Immediate physical demand is intense. Bullish expansion active.
- **Warning (Deep Contango)**: "Supply Glut." Futures are trading at a high premium to spot. Physical metal is abundant. Expect quiet, range-bound trading.

---

## 11. Interactive Relationship Mapping & Glow Pathways

The CommodityEx Monitor v5.1 cockpit features an interactive, click-to-highlight educational tracing system. When a primary metric is clicked, the terminal dynamically highlights all related parameters to reveal how market variables propagate. The canonical mapping is defined in the backend metadata and synced automatically.

| Trigger Metric | Primary Role | Glow Pathways (Highlighted Related Metrics) | Strategic Educational Rationale |
| :--- | :--- | :--- | :--- |
| **MRI** (Macro Index) | Sovereign Weather Vane | Health Rating, ADV Cap, Discovery Premium, ROV, Term Structure, AISC Uplift, 10Y, 30Y, TED, DXY, Spreads, VIX, WTI, Spot_Ag, CFTC Position | Traces how sovereign dollar liquidity, interest rates, and macro stress choke off risk capital and compress exit capacities. |
| **JSF** (Survival Forensics) | Explorer Balance Shield | Health Rating, Forensic Penalty, IS-IAI, CBA, Dilution Sieve, Sloan Ratios | Exposes explorer cash runway, share dilutions, and accruals, identifying if resources are discounted by dilution risks. |
| **REP Floor** | Liquidation Support | AGA.V Intrinsic | Highlights the bare-minimum asset replacement cost floor underlying the spear's valuation. |
| **IS-IAI** | Resource Multiple | JSF, Peer EV/oz, Discovery Premium, AGA.V Intrinsic | Links explorer resource ounces in the ground to market peer multiples, exploration premiums, and JSF discounts. |
| **ROV** | Monetary Battery Premium | 10Y, VIX, Spot_Ag, AGA.V Intrinsic | Models the convex optionality silver assets command during monetary debasement or volatility spikes. |
| **Discovery Premium** | Speculative Torque | MRI, Spot_Ag, AISC Uplift, IS-IAI | Measures the speculator reward multiplier for drilling success, constrained dynamically by macro stress. |
