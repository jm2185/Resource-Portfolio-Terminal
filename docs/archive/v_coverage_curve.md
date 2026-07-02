# P1.5 — V vs floor-coverage (φ) curve audit

Fixed: floor=1.00, bull=4.00 (a 4× spear), base=2.50; price = floor ÷ φ. Archetype=option_convexity (asymmetry mode).

| φ (cov) | price | ρ payoff | support(lin) | **V linear** | support(depth) | **V depth** |
|---:|---:|---:|---:|---:|---:|---:|
| 0.90× | 1.111 | 0.93 | 0.30 | **7.09** | 0.22 | **6.81** |
| 0.95× | 1.053 | 0.93 | 0.40 | **7.47** | 0.29 | **7.09** |
| 1.00× | 1.000 | 0.94 | 0.50 | **7.84**  ← floor | 0.36 | **7.35** |
| 1.02× | 0.980 | 0.94 | 0.54 | **7.99** | 0.38 | **7.45** |
| 1.05× | 0.952 | 0.94 | 0.60 | **8.22** | 0.42 | **7.59** |
| 1.08× | 0.926 | 0.94 | 0.66 | **8.44** | 0.46 | **7.73** |
| 1.10× | 0.909 | 0.94 | 0.70 | **8.59** | 0.48 | **7.82** |
| 1.15× | 0.870 | 0.95 | 0.80 | **8.96** | 0.54 | **8.04** |
| 1.20× | 0.833 | 0.95 | 0.90 | **9.32** | 0.59 | **8.23** |
| 1.25× | 0.800 | 0.95 | 1.00 | **9.69**  ← band top | 0.64 | **8.41** |
| 1.30× | 0.769 | 0.95 | 1.00 | **9.71** | 0.68 | **8.58** |
| 1.40× | 0.714 | 0.96 | 1.00 | **9.73** | 0.75 | **8.86** |
| 1.50× | 0.667 | 0.96 | 1.00 | **9.75** | 0.81 | **9.08** |
| 1.60× | 0.625 | 0.96 | 1.00 | **9.77** | 0.85 | **9.26** |

## Finding

- **Below the floor, the LINEAR support term flat-shelfs at φ=1.25** (support hits 1.0 and stops). Deep margin of safety past ~25%-below-floor earns **nothing** more from support; ρ payoff is already saturated (≈0.95).
- Marginal V over the DEEP region 1.25×→1.50× (linear): **+0.06** points (vs +0.75 over the shallow 1.00×→1.10×). The curve is **near-flat where the margin of safety is deepest** — so 1.02× ≈ 1.40× coverage, over-crediting a marginal entry.
- The proposed **depth** curve keeps rewarding depth: V over 1.25×→1.50× = **+0.67** points — monotonic, concave, never a shelf.

**Verdict:** 1.08× → high V reflects a *threshold* effect more than a *deliberate, steep-enough depth curve*. Recommendation (proposal-gated, /confirm): set `conviction_mode.support_curve = "depth"` so the 45%-weight, fast-compressing pillar rewards margin-of-safety DEPTH, not merely being below the line. Default stays `linear` until approved.

