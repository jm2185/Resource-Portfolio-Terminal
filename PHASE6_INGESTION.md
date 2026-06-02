# Phase 6 — Open-Source Ingestion Engine

Standalone **Adapter Layer** (`ingestion_pipeline.py`) that pulls macro / fundamental /
sentiment metrics from free, open endpoints, maps them into the exact `data_payload`
schema the `PolymorphicRouter` consumes, and caches the result to
`data/ingestion_cache.json`. The engine overlays that cache onto its live-built payloads
and degrades gracefully when it is missing or stale.

---

## 1. Architecture

### Isolation & dependencies
- All endpoint/parsing logic lives in `ingestion_pipeline.py`. It imports **nothing** from
  `engine.py`; `archetypes.py` is untouched. The only symbol the engine imports back is
  `load_ingestion_cache` (one-directional — no cycle, same rule as `archetypes`).
- **No new dependencies.** It reuses the in-repo idiom already proven in `engine.py`: the
  keyless FRED CSV endpoint (`fredgraph.csv?id=...`) via `requests` + stdlib parsing, and
  direct `data.sec.gov` JSON. `requests`/`yfinance` are imported defensively, so a missing
  dep just makes that one adapter unavailable.

### Provider registry (config-driven extensibility)
- `ADAPTER_REGISTRY` + `@register_adapter("name")` decorator. Every source is a `BaseAdapter`
  subclass declaring a `name`, the `provides` capability tags it emits, `from_config(params)`,
  and `fetch(tickers)`.
- Wired from the `ingestion` block of `v5_config.json`. **Adding a new free source is two
  steps, no refactor:** (1) write a `@register_adapter` subclass; (2) append one entry to
  `ingestion.providers`. The pipeline, cache, mapper, and engine seam never change.

### Adapters shipped
| Adapter | `name` | Capability | Source |
|---|---|---|---|
| `FredMacroAdapter` | `fred` | `macro` | keyless `fredgraph.csv` — `REAINTRATREARAT10Y`, `SOFR`, `M2V`, `TEDRATE` |
| `SecEdgarAdapter` | `sec_edgar` | `financials` | `data.sec.gov` CompanyFacts (US filers only) |
| `YFinanceFundamentalsAdapter` | `yfinance_fundamentals` | `financials` | yfinance (covers TSX / TSX-V) |
| `ManualOverrideAdapter` | `manual_override` | `financials`/`comps`/`conviction_signals` | offline `data/manual_overrides.csv` |
| `SentimentAdapter` | `sentiment` | `conviction_signals` | **opt-in**, structured-only, safe neutral defaults |

### Capability merge & the Canadian-data ladder
`merge_by_capability` composes adapter fragments at **field granularity** by provider
precedence. The fundamentals fallback ladder is just the precedence policy for the
`financials` capability:

```
financials precedence (highest first): manual_override -> sec_edgar -> yfinance_fundamentals
```

- A manual analyst override always wins; SEC is authoritative where it exists; **yfinance is
  the base layer that covers the TSX/TSX-V names SEC EDGAR cannot see.**
- `SecEdgarAdapter.resolve_cik` **skips** foreign-suffixed tickers (`.V`, `.TO`, ...) — both
  because EDGAR won't have them and to avoid silently matching a same-named US ticker.

### Schema mapping & cache
- `PayloadMapper` emits per-ticker `data_payload` dicts mirroring `_archetype_payload`
  (`currency`, `macro`, `comps`, `financials`, `conviction_signals`, `shares_out`) and folds
  the derived primitives `runway_months`, `cash_burn_acceleration`, `dilution_velocity` into
  `financials` (extra keys are harmless — archetypes only read what they need).
- `IngestionCache` writes an atomic, staleness-aware envelope:
  `{schema_version, generated_at, ttl_seconds, sources:{name:{fetched_at,status}}, data:{macro,tickers}}`.

### Engine seam (graceful)
- `engine._archetype_payload` calls `_apply_ingestion_overlay(ticker, payload)` right before
  returning. **Live worker feeds take precedence; the cache only fills gaps.**
- `_ingestion_overlay_data` loads the cache once, **memoized by file mtime** (no per-cycle
  disk churn). Absent/stale/corrupt cache → no-op (+ one log line), so the legacy path is
  byte-for-byte unchanged when no cache is present, and the orchestrator can never be brought
  down by the ingestion layer (anything that slips through still hits `_safe_leg`).

### Verification
- **32 offline, fixture-based tests** (`test_ingestion_pipeline.py`, `unittest` + `mock`) —
  no live internet. Parsers, CIK resolution + foreign-suffix skip, CompanyFacts mapping,
  primitives, manual CSV, sentiment clamping, merge precedence, schema conformance, cache
  round-trip/staleness, orchestrator fail-soft.
- **Contract test**: ingestion-built payloads feed straight into the real
  `PolymorphicRouter.get_valuation` for all four barbell names — no crash, finite legs,
  weights sum to 1, CAD base.
- 42 existing `test_archetypes` tests still green (no regression).
- Offline CLI smoke: `python ingestion_pipeline.py --providers manual_override --tickers AGA.V,URC.TO,GROY,GMX.TO`
  writes a schema-valid cache that `load_ingestion_cache` round-trips.

---

## 2. Data-source evaluation (for our use case)

Evaluated against this stack specifically: the silver-focused **60/15/15/10 barbell**
(`AGA.V`, `URC.TO`, `GROY`, `GMX.TO` — three TSX/TSX-V + one US), the archetype `data_payload`
schema, and our agreed constraints (dependency-light, **no brittle HTML scraping**, graceful
degradation).

| Tool | Verdict | Why, for *us* |
|---|---|---|
| **yfinance** | ✅ **Adopt (already wired)** | Already a repo dep (prices worker, `mri_history`). Reads `.V`/`.TO` natively → it is the backbone of `YFinanceFundamentalsAdapter`, our only real source for the 3 Canadian names. Caveat: scrapes Yahoo's unofficial API → periodic breakage; pin a known-good version, keep the defensive wrappers, don't trust it for forensic-grade statement history. |
| **OpenBB Platform** | ✅ **Keep in engine / optional ingestion tier** | Already a repo dep — engine uses it for FRED (`obb.economy.fred_series`) and CFTC COT. But it's **heavy** (large install, slow import; engine even ships a "signal shield" to silence its worker-thread errors). We deliberately kept `ingestion_pipeline` off it (keyless FRED CSV + direct SEC JSON) to stay light/fast. Could slot in later as an `OpenBBMacroAdapter` via the registry — not required. |
| **investpy** | ❌ **Avoid** | Effectively **dead** — Investing.com blocked its endpoints and it's been broken/unmaintained since ~2021. Adds a brittle dependency that mostly returns errors. The commodity/futures data it promised we already get free from yfinance continuous futures (`SI=F`/`GC=F`/`HG=F`, used in `mri_history`) and FRED. |
| **edgar / sec-api** | ⚠️ **Split** | `sec-api.io` is a **paid, API-key** commercial service → contradicts the free mandate; avoid. Free `edgartools` (MIT, maintained) wraps the *same* `data.sec.gov` endpoints we already call keylessly — its value is the Form 4 (insider) / 13F (institutional) **XML parsers** we'd otherwise hand-roll. That maps to `conviction_signals.insider_net_buying` / `institutional_flow` (today neutral defaults). Gate as an **opt-in** `EdgarInsiderAdapter`. Hard limit unchanged: **US filers only** → benefits GROY (+ future US names), not the Canadian three. |
| **BeautifulSoup4** | ⚠️ **Last resort only** | Lightweight, fine for a *static* HTML table with no JSON/library — but always prefer a hidden JSON/XHR endpoint first (as we do with FRED's CSV). Confine it to a single opt-in adapter; don't build the pipeline around it. |
| **Playwright** | ❌ **Avoid (for now)** | Heavy browser-automation footprint (headless Chromium, hundreds of MB) and brittle/ToS-sensitive — directly contradicts our opt-in, no-screen-scraping sentiment stance. Only revisit if a *critical* metric exists **only** behind JS-rendered pages, and even then isolate it as an opt-in provider. |

### Bottom line
1. **Lean on what's already proven and in-tree:** yfinance (Canadian fundamentals + pricing)
   and OpenBB (FRED/CFTC in the engine). `ingestion_pipeline` stays dependency-light by design.
2. **Add selectively, opt-in, via the registry:** `edgartools` for US insider/13F → upgrade
   `conviction_signals` beyond neutral defaults. Each is a `@register_adapter` subclass + one
   config line — **zero refactor**, which is exactly what the Phase 6 architecture was built for.
3. **Avoid:** investpy (dead), sec-api.io (paid), Playwright (heavy/brittle/ToS). BeautifulSoup
   only as a narrowly-scoped last resort.
