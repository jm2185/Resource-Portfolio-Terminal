# CommodityEx — Phase V Live-Validation Report
**Date:** 2026-06-20 · **Fixture:** `terminal_state_2026-06-20.json` (run 20:12 UTC) · **Branch:** `claude/magical-heisenberg-13nq6h` (nothing touched `main`, per the phase invariant)

## The standard applied
A number is **trusted-live** only when (a) produced by the live engine on today's data, (b) traced to the live input that drives it, and (c) hand-checked against an independent read. Rule honored throughout: **report, don't resolve** — the one code change made (V1) is a unit-bug wiring fix that V1 explicitly mandates, **not** tuning output toward a synthetic expectation.

---

## V0 — Reproducible live state ✅
Installed the missing live-path deps (`numpy/pandas/yfinance/fastapi/uvicorn/bs4`; PyPI reachable). `_v0_run.py` primes the live price/macro caches through the engine's own workers (`_prices_worker` does one live Yahoo bulk download), then runs one `evaluate_master_architecture` cycle and persists the full `terminal_state` with per-feed freshness. **All P2–P5 blocks present.** Independent yfinance pulls match the fixture exactly (Spot_Ag 64.91, WTI 76.54, DXY 100.85, 10Y 4.45), so the price/rate/FX/commodity layer is genuinely today's.
**Honest feed ages:** `openbb` absent → CFTC + macro-history degrade (flagged `DEGRADED_STALE`); FMP key absent → `treasury_curve` block null (but the yields themselves come live via yfinance); no live BLS feed → productivity null.

## V1 — Signal→scenario chain (make-or-break) ✅ *after fixing a real bug*
**Caught a genuine unit bug.** `scenario_engine._drivers` fed the rates `fiscal_dominance` score (documented **0–100**) straight into the B-weight tilt, while the C driver correctly divides by 100. With the bear-steepener **ON**, the steepener bump's `_clamp(b_sig+0.15)` accidentally saturated the raw score to 1.0 — masking the bug in **every** synthetic test (all had the steepener on). On **live** data the steepener is **OFF**, so the raw `25.8` flowed through unclamped → **scenario B = 0.816 (82%)**.
**Fix (V1-sanctioned):** normalize `fd/100` and clamp before the bump, mirroring the C path. Regression test locks the steepener-OFF + non-trivial-score case.
**Post-fix live trace — each weight traces to its live driver, with delta:**

| Scenario | weight | prior | Δ | live driver |
|---|---|---|---|---|
| A managed-debasement | 0.315 | 0.340 | −0.025 | real-yield **2.45** (high → debasement signal 0; A *below* prior — correct) |
| B fiscal-dominance | 0.235 | 0.220 | +0.015 | fiscal score **25.8/100 = 0.258** |
| C AI-productivity | 0.185 | 0.200 | −0.015 | **no live BLS feed → driver `None`** (honest null, not silent fallback) |
| D reflation | 0.264 | 0.240 | +0.024 | Cu/Au **1.52 → 0.312** |

Sum = 1.000. **GROY robustness #1, AGA.V upside #1 reproduced live**; **scenario-C/uranium hole fires** (C/D hedge 25% < 30%).

## V2 — P1 scores on live numbers ✅ (one sub-item partial)
- **1.1 tailwind:** GROY live **T = 2.975 = alpha 1.017 + regime 0.832 + commodity 1.125** (exact). `commodity_momentum = −0.399` is present, labeled, and **provably absent from the scored T**. GROY's T is moderate because the **live regime** (real-yield 2.45, hostile to debasement) suppresses the gold lean — a regime effect, not a bug. AGA.V T = 5.571 (spear > ballast — correct direction).
- **1.1 residual leaks:** the dxy_mom-driven term is the now-separated `commodity_momentum` (out of T); `vol_edge`/`dxy_mom` appear as **no explicit T contributor** in live data. **Partial:** whether `vol_edge` remains embedded inside `alpha_contribution` upstream isn't decomposable from the fixture alone → feeds V6 #2.
- **1.3 V legibility:** self-inverting callout present verbatim in the live glossary — *"V IS THE ENTRY… High V = the best entry. V COMPRESSES as price rallies up through the floor — that compression is the thesis WORKING, NOT deterioration."* (Both holdings are **above** floor today — coverage AGA 1.08 / GROY 1.09 — so the below-floor render couldn't be shown on a live name; the callout text is confirmed.)
- **1.5 V depth curve:** default `"linear"` confirmed (live V computed linear). Depth sharpens deep-vs-shallow discrimination (φ=1.2 → 0.59 vs linear 0.90; φ=2.5 → 0.99), avoiding the flat shelf — book impact → V6 #1.

## V3 — Monitors vs live feeds (stale-feed trap) ✅ (gaps flagged)
- **2.1 Rates:** 30Y 4.97 / EFFR 4.33 (live, today). Bear-steepener = **honest null** (`"not assessable — need a prior-window snapshot"`), **not** silently 0. `rates_history` **not accumulating** in a one-shot run (needs the persistent loop) — flagged.
- **2.2 Productivity:** zone/breadth/pressure all `None` — **honest null** (no live BLS feed), consistent with C sitting near prior in V1.
- **2.4 Oil:** WTI live (price_break correctly False at 76.54 < 85); OVX/term-structure null (no feed). **Headline `scored: False`** — the no-intent-score anti-pattern holds (verified, not assumed).
- **2.3 Board:** 7 monitors, coverage gap (`uranium_term`) stated honestly. **Gap:** board tiles do **not** expose per-tile data age (freshness lives in `data_freshness`, not on the card) — a recommended enhancement.

## V4 — P5 work-up on the live book ✅
- **5.3 uranium work-up (real candidates):** DML (developer, *cheapest* at 55% discount) and CCO (producer) → **slot-MISMATCH "direct operator"**; U.UN (physical holding) + royalties FIT; BROAD.ROY → **SWAP-CANDIDATE** → `/rotate`. **The value-fix refuses the cheapness trap, live.**
- **5.2 upside:** GMX discovery tail (25%) is **bull-only, ZERO in base** (buy-near-floor discipline intact); GROY shows ramp (12%) + gold leverage (15%) + re-rate (25%) as explicit legs, not one collapsed target.
- **5.1 monitors:** `nav_discount` scored down-is-good (`good="narrowing"`, falling = healthy). Catalyst-calendar currency depends on the ingestion feed (partially live).

## V5 — Action-layer gate (highest bar) ✅
- **5a AGA add gate (live):** **BLOCKED — at the 60% spear ceiling** (live weight 0.60, room 0.0). The synthetic *"ADD 4.2% → 59%"* is **not** reproduced live; the book is already at the hard ceiling. **AND-gate proof:** every hand-built 2-of-3 state → HOLD/BLOCKED, never ADD. `SPEAR_CEILING = 0.60` is a hard invariant. Gate thresholds are static config (fixed before any result is graded).
- **5b no execution:** grep of all P4/P5 paths for `execute/order/trade/set_weight/mutate/auto_` → **none**. Proposal/alert only.
- **5c invalidation:** URC.TO → **WATCH**, `stop_action: "tighten / scout the hedge"` — a **review**, off the real `scenario_c_hole` flag, distinct from a price stop.
- **5d dry-powder:** stance STAGGER ("no compelling entry — ladder in, don't chase") — advisory, doesn't deploy into a correlated name. **Tilt = None** (no live BoC-rate feed for the USD/CAD carry) — honest gap.

## V7 — Loop closed ✅
Full discovery: **8 errors, 0 failures, 65 skipped** (was 17 errors + 1 failure before installing deps). Remaining 8: 6 missing-dep (`openbb` ×1, `matrix_*` ×5 → textual/cosmetic); 2 (`capture_loop`, `conviction_projection`) are a pre-existing **discovery-isolation quirk — they pass in isolation** (15 tests OK). **None are from P1–P5.** All 10 P-module suites pass (**145 tests**). The engine imported and ran a full live cycle (`err=None`), exercising the P5 shared-`holdings`/`usdcad` hoist and the conditionals-after-posture ordering — **introduced nothing.**

---

## Trusted-live vs unverified

**TRUSTED-LIVE** (a+b+c met):
- Price/rate/FX/commodity metrics (10Y, 30Y, DXY, WTI, Spot_Ag, AGA.V $0.56) — match independent pulls.
- Scenario weights A / B / D — each traced to its live driver with delta; B hand-checked (25.8/100).
- GROY tailwind decomposition (momentum separated, verified) and direction (spear T > ballast T).
- GROY robustness #1 / AGA.V upside #1; scenario-C/uranium hole fires.
- AGA add gate = BLOCKED-at-ceiling; AND-gate logic; no-execution; URC WATCH-review.
- Uranium work-up slot-mismatch discipline (DML/CCO refused on slot, not valuation).
- Oil headline never scored; `nav_discount` direction.

**UNVERIFIED (feed absent in-sandbox — honest null, not silent fallback):**
- Scenario **C** weight (no live BLS productivity feed).
- Bear-steepener flag + `rates_history` (one-shot run, no prior window).
- OVX / oil term-structure; `treasury_curve` block (FMP key).
- CFTC silver positioning (`openbb` absent → seed).
- USD/CAD carry tilt (no BoC-rate feed).
- `vol_edge` residual contribution to T (not decomposable from the fixture) → V6 #2.
- Below-floor V render on a live name (no holding below floor today).

> **The action layer is trusted-live for its LOGIC** (gate AND-semantics, ceiling invariant, no-execution, review-not-sell) — verified on live-shaped state. Specific live *outputs* that depend on an absent feed (the dry-powder currency tilt) remain unverified.

## V6 — Pending decisions for human `/confirm` (evidence prepared; NOT auto-applied)
1. **Activate depth-sensitive V curve (`support_curve="depth"`)?** Evidence: depth avoids the linear flat-shelf and sharpens deep-vs-shallow discrimination. Live book impact is small/uniform — both holdings are shallow (φ≈1.08–1.09), so depth lowers both V-supports similarly (low re-rank risk among holdings); the benefit accrues to deep-discount *candidates* in screening. Prior lean: **on**. Recommend surfacing for decision.
2. **Strip residual T momentum terms (`MRI.dxy_mom`, `alpha_option.vol_edge`)?** The dxy_mom momentum is **already separated** out of scored T. The `vol_edge` residual could not be quantified from the fixture — **recommend a dedicated alpha decomposition before deciding;** decision stays pending (negligible → leave; material → propose the strip).

## CALIBRATION note (proposal-gated, like the build notes)
> **2026-06-20 Phase-V live validation.** One real cycle stamped to `terminal_state_2026-06-20.json`. V1 found + fixed a fiscal-dominance score-scaling bug (0–100 fed as 0–1) that inflated scenario B to 82% on live data whenever the bear-steepener was off; regression test added. P1/P3/P4/P5 logic reproduced live (momentum-separated T, GROY robustness #1, slot-fit-first work-up refusing the cheapness trap, AND-gated add ceiling, no-execution). Unverified items are feed-absent honest-nulls, not silent fallbacks. Two human decisions pending (V6). Log via `memory_write(type="note", ...)` when the cockpit is live.
