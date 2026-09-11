# Thread — AGA spear death / AG-BRC-SVE rebuild / TLT sleeve / CEG hold

**Date:** 2026-09-11
**Kind:** session handoff (Grok tape merged into CommodityEx)
**Canonical:** `docs/HANDOFF_2026-09-11_AGA_SPEAR_TLT.md`

## One-line

AGA is no longer the silver spear; sell it before FOMC; rebuild AG / BRC / SVE after the
decision; hold CEG; keep TLT Sep-30 puts small after closing Sep-18 calls flat.

## Decisions frozen

1. Exit AGA.V as silver-spear (REJECT). Merger stub only if explicitly running the ratio.
2. Do not replace AGA with VOXR, HSLV, NEM, AEM, SLVX, or HL-as-core.
3. Planned spear after FOMC: AG (largest) / BRC.V (junior) / SVE.V (satellite).
4. CEG hold; add only on rates-driven dumps with power intact.
5. TLT: no new short-dated calls; puts are a leftover sleeve, add only on squeeze.

## Invalidation

Growth scare (oil + equities breaking together) kills the duration-short overlay and
probably cheapens the silver rebuild further — still wait for the first full post-FOMC
session rather than buying the event.

## Next cockpit actions

- `memory_query(tag="handoff-2026-09-11")`
- `/replace AGA.V` after OI-1 fill is booked
- `/entry AG` and `/gauntlet BRC.V` post-decision
- `record_decision` / `record_outcome` on the AGA exit (calibration tuition on deal risk)
