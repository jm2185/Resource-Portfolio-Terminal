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
                       commodityex_tui.py  ◀── "RECENT CATALYSTS" strip on each card
```

### Components (all additive, dependency-free, guarded)
| File | Role |
|------|------|
| `catalyst_engine.py` | Pure engine: event schema, recency-weighted scoring → bounded overlay (`conviction_delta`, `dilution_velocity`, `permitting_stage`, `p_discovery_delta`, `net_signal`, `recent[]`), + graceful `load_catalyst_feed`. |
| `ingestion_pipeline.py` | New `CAP_CATALYSTS` capability, `@register_adapter("catalyst_manual")` (CSV source), `write_catalyst_feed` / `refresh_catalyst_feed`, and a `--catalysts` CLI path. Mirrors the Phase 6 registry/cache idiom. |
| `data/catalysts.json` | Canonical feed envelope (seed shipped). |
| `engine.py` | `_catalyst_feed` (mtime-memoized loader) + overlay application in `_compute_conviction_mode`; surfaces `catalysts`/`catalyst_signal`/`catalyst_count` per basket. Isolated — can never crash the loop. |
| `commodityex_tui.py` | Compact "RECENT CATALYSTS" strip on each Conviction card. |

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

Covered by `tests/test_catalyst_engine.py` and the catalyst-adapter cases in
`tests/test_ingestion_pipeline.py` (recency decay, caps, dilution accumulation, attribution,
feed loading/merge, refresh semantics). Historical test tallies: `docs/archive/PHASE8_STATUS_LOG.md`.

## 6. V-pillar reactivity + dual automated sources

### A. V-pillar reactivity
Drill results, **grade beats**, **resource expansions**, and major catalysts now move the **upside**,
not just conviction. The catalyst engine carries a second recency-weighted channel (`v_impact_weights`,
`tanh`-squashed) that emits bounded **scenario uplifts**:

| Output | Effect (applied in `_compute_conviction_mode`) |
|--------|-----------------------------------------------|
| `bull_uplift_pct` (cap ±30%) | scales the spear's **bull** scenario target |
| `base_uplift_pct` (cap ±12%) | scales the **base** case |
| `p_discovery_delta` (cap ±0.20) | net discovery-probability shift (surfaced) |
| `v_moved` / `v_drivers` | flags the card that V was catalyst-adjusted, with the driving events |

To avoid double-counting, drill/grade/resource are routed **mostly to V** (their natural home) with a
small Q echo; catalyst/permitting/news stay mostly Q. The card annotates the V pillar (`· catalyst
+17%`) and tags the BULL ladder row `cat-adj` when V has moved.

**Live read (AGA.V, seed feed):** the fresh 1,240 g/t hit + permitting lift **bull $1.95 → $2.28
(+17%)**, upside **+175% → +222%**, **V 8.71 → 8.84**, rating **7.75 → 7.87** — with `v_catalyst`
surfaced on the card. Disable instantly via `catalysts.enabled:false`.

### B. Dual automated sources (primary/fallback)
Both implemented as `@register_adapter` catalyst providers, run in config order with trust-tagged
dedup so structured filings win on forensic-relevant events:

| Provider | Role | Trust | Coverage |
|----------|------|------:|----------|
| `catalyst_manual` | analyst CSV override | 5 | always wins |
| `edgar_filings` | **primary** — `data.sec.gov` recent submissions (8-K/S-1/424B → catalyst/financing) | 3 | **US filers only** (skips `.V`/`.TO`) |
| `rss_news` (company PR feeds) | **primary-ish** — per-feed `ticker` hint = a company's own press-release RSS (every item is that issuer) | 1 | authoritative-ish for the issuer |
| `rss_news` (aggregators) | **secondary** — Mining.com, Resource World, Junior Mining Network, etc., classified & ticker-matched by alias | 1 | broad/timely (drill results, PRs) |
| `sedar_filings` | optional CA filings | 3 | pluggable **stub** (no free SEDAR+ API; off unless an `endpoint` proxy is set) |

Default aggregator feeds shipped in `catalysts.providers.rss_news.params.feeds`:
`mining.com/feed`, `mining.com/tag/silver/feed`, `resourceworld.com/feed`,
`juniorminingnetwork.com/.../feed` — plus a `_company_feeds_example` slot showing how to add an
issuer's own PR feed (with a `ticker` hint so every item is attributed to that name).

- **Parsing best practice (tiered):** `feedparser` → `fastfeedparser` → stdlib `ElementTree`. Each
  tier is defensive, so a malformed feed or a missing library degrades to the next. **Sanitization
  via BeautifulSoup** (`get_text`, strips scripts/markup), with a regex fallback when bs4 is absent.
- **Dedup** (`dedupe_events`): merges the same story across feeds by **link OR (ticker, normalized
  headline, date)** — so one press release picked up by two aggregators under different URLs collapses
  to one; highest `_trust` (then most-populated) wins.
- **Classification** (`classify_headline`, pure/tested): drill keywords (`g/t`, `metres`, `intercept`,
  `intersect`, `assay`, `step-out`), comma-tolerant grade extraction (`1,240 g/t` → grade_beat),
  amount-based dilution magnitude (`C$22M` → larger), permitting stage mapping, + sentiment tilt.
- **Precedence** (`_collapse_by_source_precedence`): for `financing`/`permitting`/`resource_expansion`,
  the highest-trust event per (ticker, type, month) wins — a SEC filing supersedes an RSS rumor of the
  same raise/permit. **`dilution_velocity` / forensic-gate triggers are driven by authoritative
  filings when present.**
- **Graceful degradation:** no network, no feeds, or a missing parser/lib → that adapter yields
  nothing; the others (and the analyst CSV / existing cached feed) still produce a valid feed.
- **Dependencies are optional:** `feedparser`/`fastfeedparser`/`beautifulsoup4` are all preferred-not-
  required — the stdlib parser + regex sanitizer keep the pipeline working when none are installed.

**Refresh:** `python ingestion_pipeline.py --catalysts` runs all enabled providers, dedups + collapses
by precedence, and writes `data/catalysts.json`.

### Honest caveats / future passes
- **SEDAR+** has no stable free API, so the Canadian barbell (AGA.V/URC.TO/GMX.TO) currently leans on
  RSS for breadth; wire a SEDAR+ access path (or a maintained mirror) to make CA filings authoritative.
- EDGAR financing events don't yet parse the exact `share_change_pct` from the prospectus body (the
  type/flag fires the gate; magnitude refinement is a follow-up).
- Generalize per-asset bull/bear bands to every junior (richer V for ballast).
- A "what changed since you last looked" catalyst delta on the card.


---

---

## 7. No-hallucination guarantees (trust hardening)

The pipeline never generates, rewrites, or summarizes a headline — it surfaces only the source's
exact text:

- **Exact title only.** `clean_title()` whitespace-collapses the source string and nothing else;
  `_event_label` returns that verbatim. An item with no clean (non-empty) title is **discarded**, not
  given a fabricated placeholder. RSS uses the exact `<title>`; EDGAR uses the exact filing
  description (form code is a factual prefix), and a filing with no description is discarded.
- **Attribution is scored, weak matches dropped.** `attribute()` returns `(ticker, relevance)` from
  whole-word alias matching — 1.0 for a multi-word company name / ticker symbol, 0.6 for a single
  distinctive word, 0.0 for none. Generic sector news ("silver prices rise") scores 0 → **stays
  unattributed**. Auto-feed items below `min_relevance_score` (0.5) are dropped.
- **Manual override (highest priority).** `data/catalyst_overrides.csv` (`pattern,ticker`) lets an
  analyst permanently **reassign** or **DROP** a persistent misattribution from the auto feeds;
  analyst-authored `catalyst_manual` events are never overridden.
- **Deduplication, exact only.** Exact link match first, then `(ticker, normalized-exact-headline,
  date)` — never fuzzy/semantic.
- **Freshness.** Hard `max_age_days = 60` filter (older items discarded from display/scoring; a
  financing still counts toward `dilution_velocity` over its own 365-day lookback); `dated_after_days
  = 30` flags older items "(dated)".

Config knobs: `max_age_days`, `dated_after_days`, `min_relevance_score`, `min_title_len`,
`manual_override_path` (+ per-provider `min_relevance`).

**Verified (as-of 2026-06-02):** all four baskets show verbatim, correctly-attributed headlines; the
79-day AGA.V placement is dropped from display (stale) while still counting toward dilution; generic
"silver prices rise" attributes to nothing.

---

## 8. Source priority, live wiring & logging

**The engine now drives the live pipeline.** Previously `engine._catalyst_feed` only ever *read*
the static feed file; `refresh_catalyst_feed` (which runs the adapters) was orphaned. It is now
invoked from `_catalyst_feed` behind `catalysts.use_live_feeds` (TTL-throttled by
`live_refresh_seconds` + on-disk `generated_at`; failures log and serve the cached feed).

**Source priority is now live-primary, manual-as-override.** Providers run live-first
(`rss_news`, then `edgar_filings`/`sedar_filings`), with `catalyst_manual` **last**. The manual CSV
(`data/catalysts.csv`) is a **true override**: heavily documented and **empty by default** (prior
seed rows archived to `data/catalysts.archive.csv`). Because it carries the highest trust (5) a
*verified* manual row still wins a dedup conflict, but it never becomes the bulk of the feed. When
the manual CSV is empty, the system shows **live feeds** — never stale/hallucinated data.

**Empty-result policy.** If every provider yields 0 events, the existing feed is *preserved* by
default (resilience against a transient outage) — set `catalysts.blank_feed_on_empty: true` to hard
blank instead. The feed never gains invented rows.

**Detailed logging** (logger `ingestion_pipeline`, INFO). Each refresh prints: a header with the
ticker set; per-RSS-feed `OK/FAILED` with raw-entry and attributed counts; per-EDGAR-ticker CIK
resolution and filing-event counts; the manual override-row count; a `SUMMARY` line
(`raw → after attribution → after dedup/collapse`); providers used + overrides loaded; and the
**per-ticker final tally**. `refresh_catalyst_feed` also returns `raw`/`per_ticker` in its result.

**Robustness/attribution/freshness** (unchanged, reconfirmed): whole-word scored `attribute()`
(generic sector news stays unattributed), exact-only dedup, hard `max_age_days = 60` + `min_relevance`
filters, and graceful per-feed/per-provider error handling (one bad feed never breaks a refresh).

> **Environment note:** live RSS/EDGAR fetch only succeeds if the environment's network policy allows
> the feed hosts (mining.com, juniorminingnetwork.com, resourceworld.com, data.sec.gov). When those
> hosts are blocked (HTTP 403), those providers fail gracefully and — with an empty manual override —
> the feed is empty (correct: nothing shown, never hallucinated). Allow the hosts (or wire a SEDAR+
> proxy `endpoint` for the `.V`/`.TO` names) to see live wire data.

---
