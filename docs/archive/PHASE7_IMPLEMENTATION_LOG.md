# Phase 7 — implementation & tuning log (archived from PHASE7_CONVICTION_MODE.md)

> Dated shipped-status / review-pass / tuning-round records, moved out of the living spec in the
> 2026-07 token-optimization pass. The operative outcomes are folded into the spec's §2.5;
> `v5_config.json → conviction_mode` is authoritative for all weights and bands.

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

