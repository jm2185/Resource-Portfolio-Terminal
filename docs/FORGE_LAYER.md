# The Forge Layer — build status (Sentinel-first iteration v0.1)

> *"This is defense instrumentation — the ceiling stays, the runway is the new gate."*

The connective-intelligence layer that remembers **why** a position exists and alerts the instant that
why breaks. The engine supplies the facts; the Forge layer reads, interprets, remembers, and alerts —
**it never re-prices** (global invariant #1).

## The one non-negotiable — honored
The **60% structural single-position ceiling is untouched.** The mechanical ADV cap is *replaced* by a
**liquidity-runway gate** (M3) that is an **additional** survival constraint: it can only ever *tighten*
(withhold a size-band exception) and, on missing data, fails toward caution — it can never manufacture
a loosening. There is no code path in this layer that raises the ceiling. The value here is
instrumentation, not leverage.

## What shipped (M0–M4, M6, M7 — the book that watches itself + learning)

| Milestone | Module(s) | Tests | Notes |
|---|---|---|---|
| **M0** data contract | `STATE_FIELDS.md` | — | Every Sentinel input mapped to a `/state` path or a fail-safe fallback. Flags the **ES95 negative-percent → fraction** reconciliation. |
| **M1** catalyst calendar | `catalyst_calendar.py` | 12 | Window-based, append-only/supersede, name vs macro, grounded-or-silent macro seeder (COT/NFP deterministic; CPI estimated; FOMC never invented). |
| **M2** trigger grammar | `trigger_grammar.py` | 20 | Safe expression language — **no `eval`/`exec`**, closed whitelist, fail-closed at parse (save) and eval (fire). |
| **M2** thesis + ledger | `thesis_ledger.py`, `living_memory.py` | 31 | Underwriting record (intangibles + `claims[]` + Ulysses `rules[]`), validated at save; graveyard/hall-of-fame view. |
| **M3** Sentinel | `sentinel.py` | 18 | Liquidity-runway, financing-window/death-spiral, thesis-integrity, fired pre-commitment rules. Pure consumer; hand-checked fixtures. |
| **M4** operator surface | `commodityex_tui.py` (NL), `core.py` tools | — | `catalyst:` / `claim:` / `rule:` NL entry; `thesis_write` / `sentinel_ack` tools. |
| **M6** Council swap | `council.py` | 23 | Friction-adjusted hurdle + catalyst lock — Darwinian high-grading without over-trading. |
| **M7** calibration priors | `base_rates.py`, `calibration.py` | 32 | Researched mining base rates as Bayesian priors with credible intervals; cold-start scorecard; bias-proposals (never auto-apply). |

**MCP tools** (`mcp_server/server.py`): `catalyst_write/query/seed_macro`, `thesis_write`, `get_ledger`,
`sentinel_sweep`, `sentinel_ack`, `council_swap`; `calibration_scorecard` now folds in priors + bias
proposals. **Scheduler:** a `sentinel` job kind (6h) runs the sweep on the autonomy dial.
**Config:** a `forge.{sentinel,swap}` section in `v5_config.json`, the key gates registered in the
`dynamic_config` allowlist (range-validated, propose/confirm).

Full suite at ship: **399 tests pass** (12 pre-existing skips), no regressions.

## Open decisions — how they were answered
1. **Book scope → multi-commodity.** Nothing in this layer is silver-specific; the calendar kinds,
   archetype→prior map, and gates are commodity-agnostic. (M5's supply lens stays the metals-first
   spec when built, widening later.)
2. **Liquidity-runway params** (`forge.sentinel`): `liq_part=0.20`, `liq_k=1.0`, `liq_free=0.05`,
   `liq_runway_max=5`, `stress_floor=0.25`. Reasoned first calibration for a concentrated,
   thin-liquidity junior book — exits modelled at ≤20% of ADV with volume stressed down in the tails;
   a position may exceed the soft band only if it clears 90% within 5 days. All tunable via /confirm.
3. **Swap hurdle / lock** (`forge.swap`): `hurdle=0.35`, `lock_window=30` (mid of the 21–45 band).
4. **Reflexivity weights:** `w_prem=0.30`, `w_floorhead=0.20`, `w_pct52=0.30`, `w_dilution=0.20`
   (premium-to-placement and 52-wk percentile carry the reflexivity signal; renormalized when a term
   is missing). `last_placement_price` is a research_cache field (M0 gap, populated by the
   catalyst-verifier on a financing-window sourcing); absent ⇒ term omitted, never fabricated.
5. **Sentinel autonomy → autonomous for alerts only.** Alert-level findings auto-pin; trims/exits
   surface as **proposals** to acknowledge — the runner never exits a position unattended.
6. **Calibration priors — researched straight-to-source.** Seeded from **MinEx Consulting / Schodde**
   (discovery→mine 45%, n=4,676 — the strongest anchor) and **S&P Global Market Intelligence / SNL
   Metals & Mining** (15.7yr lifecycle n=127; junior gold/silver M&A premia ~35% median). Folklore
   (the "1-in-1,000" grassroots odds) and the Lassonde-curve magnitudes are seeded **anchored but
   deliberately wide** (no primary source quantifies them) — flagged low-confidence in `base_rates.py`.

## Deferred (with the planned approach)
- **M3/M4 full cockpit rendering.** The data + tools + NL entry are in; the visual surface — name-card
  `liquidity runway` / `thesis integrity` / `window` badges + death-spiral chip, the Hub **SENTINEL
  card** (fired-rule queue with one-click act/snooze/void), the next-30d **calendar strip**, and the
  **Thesis Ledger** view — is the remaining work in `commodityex_tui.py` (a 247 KB Textual file best
  iterated with the app running to verify visually). `sentinel_ack` already records the ack semantics.
- **M5 OpenBB feeds (infra).** Mount `openbb-mcp-server` (SSE/streamable-http, dynamic tool discovery)
  for CFTC COT (2-day lag — say so in alert copy), FRED real-yields/DXY/SOFR (cross-check MRI, flag
  divergence), and the metals supply lens; a thin adapter maps outputs into calendar entries / memory
  notes. Left as an infra step (external server + network) rather than half-wired blind.

## Safety rails (all enforced)
No `eval`/`exec` of memory content (fixed AST only) · the runner emits drafts/proposals, never commits
or auto-exits · config changes are proposals through `/confirm` · the 60% ceiling is inviolable ·
straight-to-source for every catalyst/date, fail-safe on missing data.
