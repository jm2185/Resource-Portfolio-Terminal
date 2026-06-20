# Regime Engine v2 — two-lens split (`regime_lens.py`)

**Ethos: fix interpretation, not data.** The data layer is accurate and fresh (rates, the three ratios,
DXY, real yield all check out live). The defect was aggregation: the blended macro-tape vote mixed two
regimes into one tally, so a broad-market risk-on majority buried the metals-relevant minority — the
panel printed a reassuring "RISK-ON" while the signals that actually drive a concentrated metals book
(elevated real yield, a steepening long end) flashed caution, outvoted.

## G1 — split the MRI/tape vote into two lenses (the core fix)
`regime_lens.assess(macro_tape, rates=…)` partitions the signals — **each into exactly one lens** — and
scores each lens from same-lens signals only:

| Lens | Signals | Role |
|---|---|---|
| **Broad-Market Risk** | VIX · VIX term · HY spread · SOFR spread · CFTC | **context** |
| **Metals Regime** | real yield · DXY/gold · gold/silver · copper/gold · curve tell · DXY | **drives conviction** |

The two render **side by side and are never re-blended** — the disagreement is the signal. Metals is
foregrounded; broad is context. Lens weights are config (`regime_lens.weights`, proposal-gated); the
default is equal-weight vote-counting.

**Verified live (2026-06-20 fixture):** Broad-Market Risk = **RISK-ON** (tilt +0.6) while Metals Regime
= **MIXED** (tilt 0.0) with **divergence flagged** — real yield −1 (headwind) foregrounded, dxy_gold +1
(gold strong, supportive), cu_au 0 (supply caveat), gsr 0 (level only). A user can no longer read a
single "RISK-ON" that masks the metals headwind.

## G2 — wire the curve tell into the bear-steepener logic (shared with P2.1/P3)
The metals-lens curve signal is driven by the **same `rates_dashboard.bear_steepener` flag** the P2.1
rates dashboard and the P3 scenario engine consume — no divergent curve interpretation is possible. A
firing bear-steepener registers as the fiscal-dominance tell it is (a metals-regime caution that also
nudges scenario weight B); a flat / bull-steepening curve stays **dormant**. On today's data the
steepener is off (not assessable without a prior-window snapshot), so the curve reads dormant and the
metals headwind comes from the real-yield level — exactly the live picture.

## G3 — fix the backwards / contradictory labels (at the `_tape` source + the lens)
- **Gold/Silver "Silver leadership" → removed.** A low GSR is a *level* read (silver relatively cheap, a
  setup) — never "leadership" (a direction claim) while the ratio is rising. Relabeled to a level-accurate
  read; GSR is no longer cast as a risk-appetite vote (neutral bias; direction asserted only by the lens).
- **DXY/Gold "Gold dominant → risk_on" → resolved.** Gold strength vs the dollar is a debasement /
  risk-**off** read; label and bias now agree ("Gold strong vs dollar", risk_off broadly) — and the
  metals lens correctly reads that same gold-strength as *supportive* for the book (the exact case the
  lens split exists to disambiguate).
- **Copper/Gold "reflation bid" → caveated.** Copper's level is supply-tightness-driven; the metals lens
  does not score it as a clean reflation read (neutral + caveat).

## G4 — dual-tenor data hygiene
The rates header renders the **live yfinance** 10Y/30Y; the full UST curve block renders a separate
(often cached) **FMP** vintage — the "4.49 vs 4.46" two-values-per-tenor artifact. Fix: the FMP curve
block now labels its **source + as-of date** explicitly, so the overlapping tenors read as different
vintages, not a contradiction. (Engine-side the tape curve and metrics tenors are already single-source —
verified: tape `30Y–10Y` = metrics 30Y − 10Y exactly.)

## Cross-cutting
- **One source feeding both.** The metals lens and the scenario engine both consume the same `macro_tape`
  + `rates_dashboard`; the curve tell is the one shared `bear_steepener` flag — they cannot disagree.
- **Tooltips** state each lens's question and that the two can legitimately diverge (the divergence is
  the signal, not an error).
- **Engine wiring:** `terminal_state["regime_lens"]` is attached after `rates_dashboard` (so it reads the
  shared flag); the TUI regime panel renders the two-lens line (`Broad … │ Metals … ‹drives conviction›
  ⚠ divergence`). Graceful when absent.

## Acceptance — status
- ✅ G1: two same-lens sub-scores, never re-blended; metals drives conviction; verified diverging on live data.
- ✅ G2: curve tell driven by the shared P2.1 bear-steepener flag; dormant when flat; nudges weight B.
- ✅ G3: no label contradicts its bias or the price direction (GSR level≠leadership, DXY/gold agrees, Cu/Au caveat).
- ✅ G4: FMP curve vintage labeled with source + as-of; engine tenors single-source.
- ✅ Invariants: archetype/lens-aware, straight-to-source, proposal-gated weights, no `eval()`, one-directional, nothing touches `main`.

## Deferred (flagged honestly)
- **TUI render not visually verified** — `textual` isn't installable in-sandbox; the panel line is an
  additive, syntax-checked change matching the existing `append`/`Group` idiom, and the `regime_lens`
  data surface is complete and verified live.
- GSR **direction** (rising/falling) is not asserted (no clean GSR series in the fixture) — the lens
  reads level only and says so; wiring a GSR-momentum input would let it flag "silver underperforming".

## Tests
`tests/test_regime_lens.py` (13) — lens partition (no signal in both), live divergence, the G2 curve
tell (active/dormant/reads-the-flag), the G3 reads, config weights. Full discovery green except the
pre-existing missing-dep/isolation set.
