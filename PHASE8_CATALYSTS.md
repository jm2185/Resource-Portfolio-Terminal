# Phase 8 — Live Catalyst & Signal Reactivity Layer

Brings real-world junior-miner events — **drill results, financings/dilution, permitting
milestones, material catalysts** — into Conviction Mode so the TQV rating and cards **react** to
new information. Built additively on the Phase 6 ingestion pattern and the Phase 7 rating; it adds
**no** MPT/sizing machinery to Conviction Mode.

---

## 1. Architecture

```
 data/catalysts.csv ──▶ CatalystManualAdapter ──┐
 (analyst-editable)      (ingestion_pipeline)    │ refresh_catalyst_feed()
                                                 ▼
                                       data/catalysts.json  ── canonical feed (envelope)
                                                 │ load_catalyst_feed()  (graceful, mtime-memoized)
                                                 ▼
        catalyst_engine.summarize_catalysts()  ── recency-weighted scoring ──▶ signal overlay
                                                 │
   engine._compute_conviction_mode() applies the overlay to the TQV inputs and attaches the
   recent-catalyst list to each basket ──▶ terminal_state.conviction_mode.baskets[*].catalysts
                                                 │
                       lib/main.dart  ◀── "RECENT CATALYSTS" strip on each card ──▶  dashboard.py
```

### Components (all additive, dependency-free, guarded)
| File | Role |
|------|------|
| `catalyst_engine.py` | Pure engine: event schema, recency-weighted scoring → bounded overlay (`conviction_delta`, `dilution_velocity`, `permitting_stage`, `p_discovery_delta`, `net_signal`, `recent[]`), + graceful `load_catalyst_feed`. |
| `ingestion_pipeline.py` | New `CAP_CATALYSTS` capability, `@register_adapter("catalyst_manual")` (CSV source), `write_catalyst_feed` / `refresh_catalyst_feed`, and a `--catalysts` CLI path. Mirrors the Phase 6 registry/cache idiom. |
| `data/catalysts.json` | Canonical feed envelope (seed shipped). |
| `engine.py` | `_catalyst_feed` (mtime-memoized loader) + overlay application in `_compute_conviction_mode`; surfaces `catalysts`/`catalyst_signal`/`catalyst_count` per basket. Isolated — can never crash the loop. |
| `lib/main.dart`, `dashboard.py` | Compact "RECENT CATALYSTS" strip on each Conviction card. |

## 2. How events become signal (reactivity)

Each event is **recency-weighted** by an exponential half-life (`w = 0.5^(age/half_life)`,
default 45 days) and ignored beyond `recent_window_days` (180). Then:

| Event type | Effect | Pillar / mechanism |
|------------|--------|--------------------|
| `drill_result`, `catalyst`, `permitting`, `news` | signed `impact·magnitude·type_weight·w` summed → `tanh`-squashed → **conviction nudge** (capped at `conviction_delta_cap`, default ±0.35) | **Q** (conviction term) |
| `permitting` (`stage_to`) | latest stage advances the **permitting lens** | **Q** (resource checklist) |
| `financing` (`share_change_pct`) | accumulated over `dilution_lookback_days` → `dilution_velocity`; ≥ `aggressive_dilution` **trips the forensic gate** | **forensic gate** (caps rating ≤ 4.5) |
| `drill_result` (`p_discovery_delta`) | surfaced as `p_discovery_delta` (scenario re-run is a Phase-8 follow-up) | V (future) |

The nudge uses `tanh`, so it **fades with age, stacks with count, and stays bounded** — a single
stale event barely moves the score; several fresh hits push toward the cap without ever running away.

**Live read (seed feed, as-of 2026-06-02):** AGA.V → +0.249 conviction (fresh 1,240 g/t hit +
permitting→PFS + PEA), stays **STRONG**; GMX.TO → its C$22M bought-deal (14%/yr dilution) **trips the
gate → "FORENSIC DECAY — AVOID."**

## 3. Surfacing (calm, non-noisy)

Each card gains a compact **RECENT CATALYSTS** strip: newest-first, capped at `max_display` (3), a
small impact dot (amber positive / red negative / grey neutral), a one-line headline, and the age in
days. It sits below the asymmetry ladder so the card still reads *headline → why → what's new*. No
other card real-estate changes; the Phase 7 calm aesthetic is preserved.

**Bundled Phase 7 fix:** single-point (ballast) baskets now collapse the ladder to
**FAIR VALUE · PRICE · FLOOR** instead of showing empty `BULL/BEAR n/a` rows.

## 4. Config (`v5_config.json → catalysts`)

| Key | Meaning |
|-----|---------|
| `enabled` | Master switch (false → neutral no-op). |
| `feed_path` | Canonical feed JSON the engine reads. |
| `half_life_days` / `recent_window_days` | Recency decay and hard cutoff. |
| `conviction_delta_cap` / `delta_softness` | Max conviction nudge and `tanh` sensitivity. |
| `dilution_lookback_days` | Window over which financings accumulate into `dilution_velocity`. |
| `impact_weights` | Per-type weight on the conviction nudge. |
| `max_display` | Catalysts shown per card. |
| `providers` | Catalyst adapters to run on refresh (default `catalyst_manual` ← `data/catalysts.csv`). |
| `as_of` | ISO date override for deterministic scoring (tests). |

**Refresh the feed:** `python ingestion_pipeline.py --catalysts` (runs the configured catalyst
providers and writes `data/catalysts.json`; a missing source is a graceful no-op that preserves the
existing feed).

## 5. Tests

- `test_catalyst_engine.py` (17): recency decay, cap, dilution accumulation, latest permitting stage,
  net-signal sign, window cutoff, graceful garbage, feed loader (missing/corrupt/valid/seed), config merge.
- `test_ingestion_pipeline.py` (+5): catalyst adapter CSV read + numeric coercion + ticker filter,
  missing-file grace, feed write/roundtrip, refresh no-op vs write.
- `test/dashboard_overflow_test.dart`: catalysts render on the card; ballast ladder collapses; no overflow.
- **All green: 156 Python + 10 Flutter; `flutter analyze` clean.**

## 6. Follow-ups (not in core)
- Feed `p_discovery_delta` / grade beats into the **spear scenario bands** (V), not just Q.
- Real source adapters (news/RSS, SEDAR+ filings, Form-4 insider) as opt-in `@register_adapter`s.
- Generalize per-asset bull/bear scenario bands to every junior (richer V for ballast).
- A catalyst-driven "what changed since you last looked" delta on the card.

---

[PHASE 8 CORE IMPLEMENTED — AWAITING REVIEW]
