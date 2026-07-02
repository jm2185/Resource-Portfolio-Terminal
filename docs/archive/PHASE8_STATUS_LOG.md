# Phase 8 — status log (archived from PHASE8_CATALYSTS.md)

> Dated test tallies and review banners moved out of the living catalyst-layer spec in the
> 2026-07 token-optimization pass.

## 5. Tests

- `test_catalyst_engine.py` (17): recency decay, cap, dilution accumulation, latest permitting stage,
  net-signal sign, window cutoff, graceful garbage, feed loader (missing/corrupt/valid/seed), config merge.
- `test_ingestion_pipeline.py` (+5): catalyst adapter CSV read + numeric coercion + ticker filter,
  missing-file grace, feed write/roundtrip, refresh no-op vs write.
- `test/dashboard_overflow_test.dart`: catalysts render on the card; ballast ladder collapses; no overflow.
- **All green: 156 Python + 10 Flutter; `flutter analyze` clean.**


- **All green: 156 Python + 10 Flutter; `flutter analyze` clean.** (and later rounds: 177 Python)

[PHASE 8 CORE IMPLEMENTED — AWAITING REVIEW]
[PHASE 8 FOLLOW-UP COMPLETE — AWAITING REVIEW]
[CATALYST HALLUCINATION FIX COMPLETE — AWAITING REVIEW]
[CATALYST SOURCE FIX + LOGGING IMPLEMENTED — AWAITING REVIEW]
