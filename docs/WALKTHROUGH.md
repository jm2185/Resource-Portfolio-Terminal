# CommodityEx — Technical Walkthrough (current system)

> The living, end-to-end tour of the cockpit. For **day-to-day operation** see `CLAUDE.md` (the
> natural-language router / operating manual) and `COCKPIT.md`. For **deep detail** see
> `ENGINE_DESIGN.md`, `METRIC_COMPASS.md`, `STATE_FIELDS.md`, and `docs/FORGE_LAYER.md`. Historical
> release notes live in `docs/archive/CHANGELOG_v5.1.md` and `docs/archive/`.

## What this is

A Druckenmiller-style **asymmetric silver / junior-mining barbell** research cockpit. One rule governs
everything: **the engine is the single source of truth.** It computes all valuation, regime, and
sizing; every other layer (cockpit, MCP tools, Forge layer) *reads, interprets, remembers, and
alerts* — it never re-prices.

The book is a **spear** (`AGA.V` — Silver47, option-convexity) plus **ballast** royalty/holdco names
(`GROY` Gold Royalty, `GMX.TO` Globex, `URC.TO` Uranium Royalty). The lens is always: margin of safety
(REP floor), asymmetric upside (ρ/φ), regime awareness (MRI), and forensic discipline (JSF).

## How the pieces fit

```
   data feeds / SEDAR+ filings           (async background workers, provenance-stamped)
            │
            ▼
   ENGINE   engine.py  (FastAPI :8000)              ← single source of truth
     • thread-safe state_cache · sub-ms CPU tick (no network in the hot loop)
     • valuation · regime (MRI) · sizing · forensics (JSF)
     • serves /state · /action/whatif · /config/* · /ui/*
            │  /state
            ▼
   COCKPIT  commodityex_tui.py  (Textual)           ← the PRIMARY screen, a thin consumer
     • views 1–5:  Book · Council · What-If · Regime · Dossier
     • NL command bar:  note:  catalyst:  claim:  rule:  focus  what-if
            │  calls
            ▼
   MCP SERVER  mcp_server/   ← the tools agents + the cockpit invoke
   FORGE LAYER  the connective intelligence (below)
```

*Secondary / legacy frontends: `dashboard.py` (Streamlit) and `lib/main.dart` + `macos/` (Flutter
desktop). The Textual cockpit is the live primary screen.*

## The valuation core (engine)

- **REP floor** — the margin-of-safety, "sold-for-parts" value per share:
  `(cash + Σ effective_oz·$0.65 + infra) · 0.85 / shares`, where `effective_oz` applies a symmetric
  **50% haircut to Inferred** ounces. (See `STATE_FIELDS.md`.)
- **T / Q / V conviction rating** — **T**ailwind (regime fit) · **Q**uality (resource + JSF + mgmt) ·
  **V** value/asymmetry (ρ payoff, φ floor coverage). Blended, lifted toward the standout pillar when
  the thesis is earned, then **capped by the forensic gate**. (See `METRIC_COMPASS.md`.)
- **ρ / φ asymmetry** — ρ = upside ÷ downside payoff ratio; φ = floor coverage (price vs REP floor).
  The numbers the Council debates.
- **MRI (regime)** — composite macro index on **rolling-percentile dynamic bounds**
  (`mri_dynamic_bounds`), which replaced static min-max ranges that saturated in the $70+ silver
  regime.
- **JSF forensic gate** — Junior Survival Factor: runway, burn acceleration, dilution, Sloan accruals.
  Caps the rating; relaxed when price sits at/below the floor (a junior raising to drill below
  liquidation value is normal).

## The Forge layer (connective intelligence)

The engine supplies facts; the Forge layer remembers **why** a position exists and alerts the instant
that why breaks. Full detail in `docs/FORGE_LAYER.md`.

| Module | Role |
|---|---|
| `living_memory.py` | Append-only, typed, regime-stamped shared record. Every view reads/writes it; corrections supersede, never overwrite. |
| `council.py` | Dialectic Council — Bull + Bear + Arbiter → one reconciled verdict; plus the **swap system** (challenger vs incumbent under a friction hurdle + catalyst lock). |
| `regime_posture.py` | The master temperature dial (SPEAR EXPLOIT / BALANCED / DEFENSIVE + size cap) that composes onto every verdict. |
| `catalyst_calendar.py` | Catalysts as **windows** (drill results, financings, macro), straight-to-source. |
| `thesis_ledger.py` | The underwriting record: intangibles + load-bearing **claims** + pre-commitment **rules** (Ulysses contracts). |
| `trigger_grammar.py` | A **safe** expression language for rules — tokenizer → AST → evaluator, **no `eval`**; fails closed. |
| `sentinel.py` | Watches each held name: **liquidity-runway** gate (the disciplined replacement for the ADV cap — the 60% ceiling stays), **financing-window / death-spiral** read, **thesis-integrity**, and fired pre-commitment rules. |
| `calibration.py` + `base_rates.py` | Grades closed decisions on the Druckenmiller objective (slugging / expectancy / upside-capture / containment), seeded with published mining base rates so it's useful from day one. |

## Data & provenance (no hardcoded inputs)

- **`research_cache.py`** — filings-derived facts no market API provides (in-ground oz, AISC, NAV,
  placement prices), each stamped `{value, source, as_of, confidence}`. Absent ⇒ "pending," never a
  fake default.
- **`v5_config.json`** holds static defaults; **`dynamic_config.py`** holds overrides on top
  (hot-reloaded). Tunable changes route **propose → `/confirm`** (the human gate); agents never set
  params unprompted.

## Running it

- **Cockpit:** `./cockpit.sh` (tmux + Textual) or double-click `start-cockpit.command`. Needs
  `pip install textual`.
- **Engine:** launched by the cockpit / MCP `run_engine`; serves `:8000/state`.
- **Tests:** `python -m unittest discover -s tests -t .` — the deterministic suite under `tests/`.
  One suite per module (e.g. `tests/test_sentinel.py` ↔ `sentinel.py`); each formula has a
  hand-checked fixture.

## Where to read next

| For… | See |
|---|---|
| engine math & formulas | `ENGINE_DESIGN.md`, `METRIC_COMPASS.md` |
| the Sentinel's data contract | `STATE_FIELDS.md` |
| the Forge layer in depth | `docs/FORGE_LAYER.md` |
| day-to-day operation (NL router) | `CLAUDE.md`, `COCKPIT.md` |
| roadmap | `docs/ROADMAP.md` |
| history (v5.1 release, earlier phases) | `docs/archive/CHANGELOG_v5.1.md`, `docs/archive/` |
