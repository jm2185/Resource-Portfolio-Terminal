# CommodityEx — Phase V Completion Report (VP → V7)
**Date:** 2026-06-20 · **Fixture:** `terminal_state_2026-06-20.json` (rates-live) · **Branch:** feature only (nothing touched `main` during the work). Companion to `PHASE_V_VALIDATION_2026-06-20.md` (V0/V1).

## VP — rates-leg data gap closed ✅ (the fix)
FMP's treasury endpoint is plan-gated (ACCESS DENIED) → `treasury_curve` was null and the rates leg ran partly blind (no 2Y/5Y, no 2s10s/5s30s). Fix: `_fetch_treasury_curve_free()` sources the full curve from **free, sandbox-reachable yfinance tickers** quoted in yield — `^IRX` 3M · `2YY=F` 2Y · `^FVX` 5Y · `^TNX` 10Y · `^TYX` 30Y — each with an as-of date, cached ~3h; FRED `DGS2` is an optional fallback (FRED is **blocked** here — 503). FMP stays optional redundancy.

**Live result:** curve = 3M 3.658 / **2Y 3.856** / 5Y 4.225 / **10Y 4.451** / **30Y 4.901** (as-of 06-18). 10Y/30Y match the independent TE check (4.46/4.90). The rates leg now computes **2s10s 0.595, 5s30s 0.676, 30Y-funds 0.571** on live yields; scenario B (driver 0.228 = fiscal 22.8/100), the regime metals-lens curve tell, and the **AGA gate's A+B (55%)** all recompute on the live curve.

## V2 — P1 scores on live data ✅
- **1.1 tailwind:** GROY live **T = 2.975 = alpha 1.017 + regime 0.832 + commodity 1.125** (exact); `commodity_momentum −0.399` separated, **provably out of scored T**. AGA T 5.571 (spear > ballast). GROY's T is moderate because the live regime (real-yield 2.45) suppresses the gold lean — regime, not bug.
- **Residual T momentum (V6#2 evidence):** `MRI.dxy_mom` = **exactly 6%** of MRI (`f_dxymom·0.20` within `liquidity_fx·0.30`); f_dxymom 70 → ~4.2 of 44.5 MRI pts, a small residual into T's regime leg. The direct momentum channel (`commodity_momentum`) is **out of scored T**. `alpha_option.vol_edge` is 35% of the archetype alpha *weight* and flows through AGA's dominant `alpha_contribution` (3.869), but its live **contribution** needs the alpha sub-decomposition (risk_on/vol_edge/neg_yield), not exposed in the pillar output — instrumenting it is the remaining step (V6#2 is deferred, so non-blocking).
- **1.3 V legibility:** AGA **is below floor** (φ = floor÷price = 1.081 → price ~8% under the REP floor); the self-inverting callout is present verbatim ("High V = the best entry… compression is the thesis WORKING").
- **1.5 depth curve (V6#1 evidence — material):** default stays linear; live V unchanged. **At AGA's live φ 1.081 (shallow), activating depth LOWERS AGA's V support −0.203 (0.662→0.459)** — depth is uniformly more conservative and only *relatively* rewards deep discounts (φ≫1). **AGA isn't deeply discounted right now, so the V6#1 "lean: on" premise (depth rewards the spear) does NOT hold on live data** — reconsider before `/confirm`.

## V3 — monitor freshness ✅
Rates tile now **live** (curve as-of stamped). Productivity = honest null (no live BLS). Oil = WTI live, OVX/term null, **headline `scored: False`** (no-intent-score holds). Board coverage gap (`uranium_term`) stated. The earlier stale-but-confident trap (real_yield cache 06-05 stamped LIVE; seed Spot_Ag 74.8) is the reason VP + the freshness stamps matter.

## V4 — P5 work-up on the live book ✅
- **5.3 uranium work-up:** DML (developer, *cheapest* at 55% disc) and CCO (producer) → **slot-MISMATCH (direct operator)**; royalty → **SWAP-CANDIDATE**. The value-fix refuses the cheapness trap, live.
- **5.2 upside:** GMX discovery tail (25%) is **bull-only, ZERO in base** (buy-near-floor intact); GROY ramp + re-rate explicit.
- **5.1:** `nav_discount` scored down-is-good.

## V5 — action-layer gate (highest bar), on rates-live data ✅
- **5a:** AGA add gate = **BLOCKED at the 60% ceiling** (live weight 0.60). Crucially, `regime_supportive` now reads **A+B 55% off the live full curve** — the V1 bug had B at 82%; the gate now reads the corrected weights. **AND-gate proof:** every 2-of-3 hand-construction → HOLD/BLOCKED, never ADD. `SPEAR_CEILING=0.60` hard invariant. The synthetic "ADD 4.2% → 59%" does **not** reproduce live (already at ceiling). Gate thresholds are static config, fixed before grading.
- **5b:** grep of all P4/P5 + regime paths for execute/order/set_weight/mutate → **0 matches**. Proposal/alert only.
- **5c:** URC → WATCH, `stop_action: "tighten / scout the hedge"` — a review off the real `scenario_c_hole` flag, distinct from a price stop.
- **5d:** dry-powder STAGGER (advisory, no deploy into a correlated name); **currency tilt = None** (no live BoC-rate feed) — honest gap.

## V7 — loop closed ✅
Full discovery: **8 errors, 0 failures** — the same pre-existing set (6 missing-dep: `openbb`×1, `matrix_*`×5 → textual; 2 discovery-isolation that pass in isolation). **None from this work.** The engine imported and ran a full rates-live cycle (`err=None`), exercising the VP curve fetch + all prior wiring.

---

## Trusted-live vs unverified (updated post-VP)

**TRUSTED-LIVE** (live + traced + independently consistent):
- Full curve **levels** 3M/5Y/10Y/30Y (yfinance); 10Y 4.45 / 30Y 4.90 match the independent TE check.
- Rate spreads 2s10s / 5s30s / 30Y-funds; scenario weights A/B/D; AGA gate A+B 55% — all on the live curve.
- P1 momentum separation (commodity_momentum out of T); GROY robustness #1 / AGA upside #1.
- AGA gate BLOCKED-at-ceiling + AND-semantics + no-execution; work-up slot-mismatch discipline; GMX discovery zero-in-base; oil headline never scored.
- **dxy_mom = 6% of MRI** (exact, from the weights); AGA below floor (φ 1.081); depth LOWERS AGA's V live.

**UNVERIFIED** (feed absent/blocked in-sandbox — honest null, or live-but-not-independently-checked):
- **2Y (2YY=F 3.856)** — live + curve-coherent but **not independently cross-checked** (FRED/TE blocked; it is the engine's own source). The plan's ~4.20 is a stale vintage (front end rallied).
- **Bear-steepener DELTA** — needs a prior-window snapshot; one-shot run reads live levels, the over-time steepening is "not assessable" until `rates_history` fills over days (not seeded).
- Productivity C (no live BLS); OVX / oil term-structure; CFTC (no `openbb`); USD/CAD carry tilt (no BoC rate).
- `alpha_option.vol_edge` live contribution to T (needs alpha-internal instrumentation; V6#2 deferred).

> The action layer is **trusted-live for its logic AND its live inputs** now that VP made the rates leg live — the AGA gate's A+B reads the live curve, BLOCKED at the ceiling. The one residual is the steepener *delta* (history-dependent) and the dry-powder currency tilt (no BoC feed).

## V6 decisions — live evidence in
- **#1 depth V curve:** V2 1.5 shows depth **lowers** AGA's V at the current shallow φ 1.08 — the "lean on" premise doesn't hold live. The tunable is staged proposable/off (`/set_param conviction_mode.support_curve depth` → `/confirm`); **recommend NOT confirming at current prices.**
- **#2 strip residual momentum:** deferred (per the operator). The dxy_mom momentum channel is already out of T; the MRI residual is ~6%; vol_edge needs instrumentation.

## CALIBRATION note (proposal-gated)
> **2026-06-20 Phase-V completion.** VP closed the rates-leg gap with a free yfinance/FRED curve (FMP gating bypassed; FRED blocked in-sandbox → 2Y via CBOT 2YY=F). The rates leg, scenario B, regime metals lens, and the AGA gate's A+B all now recompute on a live full curve. V2–V5 verified live: P1 momentum separation holds; AGA gate BLOCKED at the 60% ceiling with AND-semantics; work-up refuses the cheapness trap. New live finding: depth-curve activation would LOWER AGA's V at today's shallow discount (φ 1.08), cutting against the V6#1 "lean on". Unverified items are feed-blocked honest-nulls. Log via `memory_write(type="note", …)` when the cockpit is live.
