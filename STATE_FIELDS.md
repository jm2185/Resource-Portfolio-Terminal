# STATE_FIELDS.md — the Sentinel's data contract (Forge M0)

> **Gate:** no Forge math proceeds until this map is green. Every Sentinel input (M3) is mapped
> below to its live `/state` path, or marked a GAP with the agreed graceful-degradation fallback.
> The rule (global invariant #1) is absolute: **if a number can come from the engine, it comes from
> the engine.** Forge reads, interprets, remembers, and alerts — it never re-prices. A missing field
> degrades to `—` (the cockpit's existing provenance pattern); it is **never** fabricated.

The engine's `/state` is served by `engine.py` (`@app.get("/state")`, line ~4593) from
`self.terminal_state`. Paths below are dotted from the root of that object. Verified against
`engine.py` at build time.

---

## 1. Per-name liquidity & position

| Sentinel input | `/state` path | Status | Units / sign | Fallback when absent |
|---|---|---|---|---|
| `pos_shares` | `nodes.<TK>.shares` | ✅ present | shares (float) | `0` → runway `—` |
| `price` | `nodes.<TK>.price` (also `conviction_mode.baskets[].ladder.price`) | ✅ present | CAD/share | basket ladder price |
| `adv90` — 90-session **median** ADV (shares) | `nodes.<TK>.adv_median_90` | ⛔ **GAP** | shares/day | `research_cache.value(TK, "adv_median_90")` → else `—` |

**ADV gap detail.** The engine *computes* a robust 90-session ADV internally
(`engine._robust_adv_shares`, used for peer normalization ~L693 and the ES95 sizing path ~L1805)
but does **not** surface it per name — `nodes.<TK>` is only `{price, role, shares}` (engine.py
~L4464). Two ways to make this green, in priority order:

1. **Preferred (engine PR, optional):** add `adv_median_90` to each `nodes.<TK>` dict where the
   engine already has the series. One-line addition next to `price`/`shares`. Until then →
2. **Shipped fallback:** Sentinel reads `research_cache.value(TK, "adv_median_90")`, agent/operator
   populated straight-to-source (exchange/issuer ADV), provenance-stamped like every other
   research-cache field. Absent ⇒ the liquidity-runway gate shows `—` and **does not block** — it
   simply cannot *grant* a band exception (fail-safe: no ADV ⇒ no runway exception).

## 2. Book-level tail risk

| Sentinel input | `/state` path | Status | Units / sign | Note |
|---|---|---|---|---|
| `es95` | `portfolio_stats.expected_shortfall_95` | ✅ present | **negative PERCENT** (e.g. `-4.5` = −4.5%) | ⚠ unit reconciliation required |

**⚠ Unit reconciliation (load-bearing).** `engine.calculate_expected_shortfall` returns the mean of
the worst-5% daily returns — a **negative fraction** — and the engine stores `round(es_95 * 100, 2)`,
i.e. a **negative percent** (engine.py ~L4337). The M3 liquidity-runway formula is written in
**fractions** (`free = 0.05`, `max(0, -es95 - free)`). Sentinel therefore divides by 100:
`es95_frac = state.portfolio_stats.expected_shortfall_95 / 100.0` before the stress term. This is the
same class of check as the engine's `$4.64 → $1.69` reprice reconciliation — got it wrong and the
stress clamp pins to 0.25 forever. Covered by a deterministic fixture in `test_sentinel.py`.

## 3. Per-name survival (JSF components)

| Sentinel input | `/state` path | Status | Note |
|---|---|---|---|
| `runway_months` | `conviction_mode.baskets[].runway_months` | ⚠ **spear only** | `None` for ballast (engine.py ~L3773) → `research_cache.value(TK, "runway_months")` else `—` |
| `dilution_sieve_pass` | derived from `conviction_mode.baskets[].dilution_velocity` | ✅ **derivable** | sieve fails at **≥ 2% QoQ** dilution (glossary ~L2334); `dilution_ok = dilution_velocity < forensic_thresholds.dilution_sieve_qoq` (default `0.02`) |
| `jsf` / `cba` | `conviction_mode.baskets[].gate` `{applied, cap, reason}` | ✅ present | gate cap is the JSF proxy already used by `calibration.decision_from_rating` |

## 4. Asymmetry & ladder (the frozen-thesis comparands)

| Sentinel input | `/state` path | Status |
|---|---|---|
| `rho` (ρ) | `conviction_mode.baskets[].pillars.V.rho` | ✅ present |
| `phi` (φ, floor coverage) | `conviction_mode.baskets[].pillars.V.floor_coverage` | ✅ present |
| `upside_pct` | `conviction_mode.baskets[].pillars.V.upside_pct` | ✅ present |
| `floor` (REP floor) | `conviction_mode.baskets[].ladder.floor` | ✅ present |
| `bear/base/bull` legs | `conviction_mode.baskets[].ladder.{bear,base,bull}` | ✅ present |
| `mri` | `mri` (root) | ✅ present |

> The agent-facing projection (`mcp_server/core.py::_project_conviction_basket`) already flattens
> these into `asymmetry.{rho,floor_coverage,upside_pct,...}`, `gate`, `ladder`. The Sentinel consumes
> the **projected basket** (via `get_conviction_ratings`), not raw pillars — one reader, one shape.

## 5. Financing-window / reflexivity (the Soros leg)

| Sentinel input | Source | Status | Fallback |
|---|---|---|---|
| `last_placement_price` | `research_cache.value(TK, "last_placement_price")` | ⛔ **GAP** (no market API supplies it) | absent ⇒ `prem_to_placement` term **omitted**, weights renormalized over the remaining terms |
| `rep_floor` | basket `ladder.floor` | ✅ present | — |
| `lo52` / `hi52` (52-wk range) | `get_fundamentals(TK)` (FMP, engine-cached) or `research_cache` | ⚠ not in `/state` | absent ⇒ `pctile_52w` term omitted, renormalize |
| `dilution_ok` | derived (see §3) | ✅ | — |

**Placement gap detail.** `last_placement_price` is exactly the class of fact `research_cache.py` was
built for ("filings-derived fundamentals that NO market API provides"). M1's catalyst-verifier writes
it when it sources a `financing_window`/placement catalyst from SEDAR+/issuer PR. Until populated, the
reflexivity score is computed over whatever terms ARE available and **renormalized** — never
fabricated, and the missing term is reported in the Sentinel card's provenance line.

---

## Degradation summary (fail-safe directions)

- **No ADV** ⇒ liquidity-runway shows `—`, cannot grant a size-band exception (conservative).
- **No runway_months** (ballast) ⇒ death-spiral leg that needs it is suppressed, not assumed-false.
- **No last_placement / 52w** ⇒ window score over remaining terms, renormalized; provenance noted.
- **Engine down** ⇒ Sentinel sweep no-ops with a single status line; it never runs on stale guesses.

Every degradation is **toward caution**: the new gate can withhold an exception but can never
manufacture one from missing data. That keeps M0's invariant intact — the 60% ceiling and the
liquidity gate only ever *tighten* on absent data, never loosen.
