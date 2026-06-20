# CALIBRATION AUDIT — T·Q·V scoring factors (2026-06-20)

**Desk:** CALIBRATION · **Scope:** action-plan P1 (scoring-engine fixes) · **Status:** append-only.
Verifies every scoring factor (1) **measures what it claims** (forward-vs-backward, value-type,
quality-basis) and (2) is **archetype-aware and consistent**, so any cross-archetype comparison
surfaced in Conviction Mode is either valid or explicitly flagged. Each factor's definition is
restated below. Code: `asymmetry_rating.py`, `commodity_regime.py`. Tests:
`tests/test_asymmetry_rating.py`, `tests/test_commodity_regime.py`.

---

## T — Macro Tailwind  → **FORWARD-STRUCTURAL** (fixed: P1.1)

**Claims to measure:** the forward structural / secular outlook for the archetype + its metal over
the multi-year thesis horizon. **Must be forward, never backward tape.**

**Definition (restated):** `T = 10·(κ·α + λ·c + base·m)` where `m` = regime posture from MRI,
`α` = archetype regime lean (`regime_alpha`), `c` = commodity structural lean (`commodity_regime`),
and (κ, λ, base) is a convex blend (κ high for explorers). Built from **LEVELS** — the regime, the
real-yield level, the GSR level.

**Audit finding (before):** the commodity-lean field blended **backward-looking momentum** into the
structural tailwind:
- `uranium_regime` was **100% `uranium_mom`** (1-month price momentum).
- `gold_regime` was **40% `dxy_mom`** (10-day dollar momentum).
- `silver_regime` carried ~20% `dxy_mom` + a risk-on positioning/sentiment term.

**Fix (shipped):** `commodity_regime.compute()` is now **structural-only** (real-yield level, GSR
level, uranium term-market read). Backward-looking tape is split into a **separate, labeled**
`compute_momentum()` that is **echoed for display only and never summed into T** (asset key
`commodity_momentum`; passthrough in `_pillar_macro_tailwind`). A strong-secular / weak-tape name
now scores a HIGH tailwind — verified: a gold-royalty (GROY-shape) tailwind **rises ~+1.1 points**
when the dollar-momentum drag is removed (`commodity_regime` +0.25 → +0.75 at a deep-negative real
yield). Uranium's structural lean is **neutral (0.0)** until the SENTINEL term monitor (action-plan
2.3) feeds `uranium_term` — never a momentum stand-in.

**Deferred (engine-level, proposal-gated — not changed this pass):** two smaller backward-looking
terms remain upstream, inside the MRI / regime-vector that feed `m` and `α`:
- MRI Liquidity block carries `dxy_mom` (~6% of MRI) — `engine.py` ~655.
- `alpha_option` carries `vol_edge` = 60-day **realized volatility** (~35% of that lean) —
  `engine.py` ~3356/4952. (Realized vol is a regime/risk read, not directional momentum, so it is
  less clearly offside than `dxy_mom`/`uranium_mom`, but it is backward-looking and should be
  reviewed.)
- CFTC positioning / VIX-term voting feed the macro-tape `risk_on` (~2% of MRI). 

These are **weight/definition changes to live engine internals** → route through
`propose_param_change` (/confirm), not a silent edit. Recommended next: relabel the MRI momentum
term and the `alpha_option` vol term as a **separate near-term factor** (mirroring the
commodity-regime split), so T is forward end-to-end.

---

## Q — Company Quality  → **VERIFIED-FIXED, archetype-aware** (locked: P1.2)

**Claims to measure:** the asset on its own merits, **in a vacuum**, archetype-tagged — an
explorer's checklist is not a royalty's cash-flow read.

**Definition (restated):** `Q = 10·(w_f·JSF/4 + w_q·resource + w_m·mgmt)`. Confirmed correct and
**more complete than the original spec**, with four locked behaviors now pinned by regression tests:
1. **Archetype tag survives** end-to-end (never silently collapsed to `_default`).
2. **Stage penalty** for pre-PEA names (`_STAGE_QUALITY`: RESOURCE 0.40, PEA 0.45 … PRODUCING 1.0)
   — an unproven developer cannot score producer-grade quality.
3. **Archetype-specific pillar weight** — Q = 0.22 for `option_convexity` vs 0.55 for
   `asset_light_yield` (no flat/absolute Q; every archetype has an explicit weight row).
4. **JSF is a dual role** — a Q sub-pillar **and** a universal hard gate (JSF < 1.5 caps the whole
   rating, every archetype; royalties are exempt only from the dilution/runway burn triggers).

**Cross-archetype safety:** because Q is different-basis, different-weight, archetype-tagged, the old
"AGA 7.2 ≈ GROY 7.0" concern is a non-issue — there is no raw cross-archetype Q comparison in
Conviction Mode. The Q glossary now states the light-Q / heavy-V trade for the spear explicitly.

---

## V — Valuation  → **MEASURABLE, archetype-aware; legibility deepened** (P1.3) + curve audited (P1.5)

**Claims to measure:** ASYMMETRY (explosive bull-vs-floor) for explorers; VALUE (fair-value-centred)
for cash-flow names. The heaviest pillar for the spear (0.45).

**Definition (restated, asymmetry mode):** from three legible inputs — the REP/liquidation **floor**,
the **coverage ratio φ = floor÷price** (φ≥1 = buying below liquidation = asset-backed downside), and
the **payoff ρ = upside ÷ downside-to-floor** → `V = 10·(0.65·payoff + 0.35·support)`.

**P1.3 — legibility (shipped):** V's tooltip now matches Q's depth (inputs + bands shown), states the
**self-inverting property** prominently — *"V grades the entry, not the destination; high V = best
entry, and V compressing as price rallies up through the floor is the thesis WORKING, not
deteriorating"* — and **cross-links V↔Q** so the 22/45 split reads as one convex-spear story. The TUI
breakdown (`_metric_breakdown`) renders the payoff/support decomposition + the bold self-inverting
callout inline.

**P1.5 — depth-sensitivity audit (see `docs/v_coverage_curve.md`):** the shipped **linear** support
term **flat-shelfs at φ=1.25** — marginal V over the deep 1.25×→1.50× region is **+0.06** points (vs
+0.75 over the shallow 1.00×→1.10×), so "barely below floor" (1.02×) ≈ "deeply below" (1.40×),
**over-crediting a marginal entry**. ρ payoff is already saturated (≈0.95) below the floor, so depth
enters almost entirely through support — which caps. **Verdict:** a threshold effect, not a
deliberate steep-enough depth curve.
**Proposal (proposal-gated, /confirm — default stays `linear`, no live number moves):** set
`conviction_mode.support_curve = "depth"` — a monotonic, concave, never-flat curve
`tanh(beta·(φ-lo))` that keeps rewarding margin-of-safety depth (+0.67 over the same deep region).
Implemented and test-pinned behind the config flag; awaiting human approval before activation.

---

## Forensic gate · Confidence ribbon (unchanged — restated for completeness)

- **Gate:** a hard `min` cap (never a smooth subtraction). JSF<1.5 is **universal**; dilution/runway
  are cash-burn **survival** triggers, exempt for recurring-cash-flow archetypes; caps are relaxed
  toward 10 by floor support (a junior funding drilling below liquidation is not slammed to "avoid").
- **Ribbon:** dispersion → a ± **information band**, never a point-estimate penalty; a wider band only
  shrinks the conviction *lift* (fail-closed on stale/low-confidence inputs).

## Archetype-awareness matrix (consistency check — all explicit, none falling back to flat)

| Archetype | Pillar weights T·Q·V | V mode | Commodity weight λ | Burn-gate exempt |
|---|---|---|---|---|
| option_convexity | 0.33 · 0.22 · 0.45 | asymmetry | 0.20 | no |
| commodity_cyclical | 0.30 · 0.35 · 0.35 | value | 0.40 | no |
| asset_light_yield | 0.15 · 0.55 · 0.30 | value | 0.45 | **yes** (JSF still universal) |
| pure_macro_delta | 0.45 · 0.25 · 0.30 | value | 0.00 | no |

**Conclusion:** every factor measures what it claims after P1.1 (forward T) and the P1.5 proposal; Q
and V are archetype-aware and consistent; cross-archetype Q/V comparisons are mode- and weight-
distinct, so none is a raw apples-to-oranges read. Two upstream engine momentum terms (T) remain,
flagged above for a proposal-gated follow-up.
