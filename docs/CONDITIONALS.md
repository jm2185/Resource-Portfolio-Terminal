# Conditional-action layer — P4 (`conditionals.py`)

P1–P3 describe the world; P4 turns it into **standing, pre-committed conditional actions** — rules set
in the cold light of day, executed against the live state. Three gates, all pure consumers of the
upstream layers (they read scenario weights + SENTINEL flags + posture; they never re-compute them).

## 4.1 AGA proportional-add gate
Adding to the convex spear is the fastest way to blow up a concentrated book, so it's gated on **three
conditions, all required**:
1. **thesis intact** — not INVALIDATED, JSF not severe;
2. **entry not extended** — entry ∈ {LOAD, SCALE-IN}, not WAIT / AVOID-EXTENDED (an *unverified* entry
   fails closed — silence never green-lights an add);
3. **regime supportive** — posture not DEFENSIVE **and** the spear-favorable `A+B` scenario weight ≥ 0.45.

The add is **proportional**: `room-to-ceiling × condition-strength × posture cap`, and the structural
**60% spear ceiling is a hard, read-only invariant** (mirrored from `calculate_sizing`, never moved by
config). Decisions: `ADD` (all pass, room left) · `HOLD` (a condition fails) · `BLOCKED` (at ceiling or
invalidated). Smoke: spear 0.55, A+B 63%, LOAD entry → **ADD 4.2% toward 59%** (room 5.0%).

## 4.2 per-thesis invalidation / stop lines
Each holding carries named invalidation lines (per slot), wired to the SENTINEL flags (P2.3) + the
scenario engine + per-name forensics:

| Flag / signal | Touches | Severity → status |
|---|---|---|
| `uranium_term_invalidation` | electrification-royalty (URC.TO) | hard → **INVALIDATED** (exit / rotate) |
| `scenario_c_hole` | electrification-royalty (URC.TO) | watch → **WATCH** (size / scout the hedge) |
| `debasement_at_risk` | silver-spear + gold-royalty-ballast | watch → **WATCH** |
| `jsf_severe` (per-name) | that name | hard → **INVALIDATED** |
| `floor_breached` (per-name) | that name | hard → **INVALIDATED** |
| `bear_steepener`, `oil_supply_risk` | — | **context only** — a tailwind/armed-watch, never a stop |

Status ∈ INTACT / WATCH / INVALIDATED, each with a stop action. The bear-steepener-as-context detail
matters: a firing tailwind must never be misread as a thesis breakdown.

## 4.3 dry-powder deployment
**Where** powder waits — the USD/CAD carry tilt (`sentinel_board.usdcad_carry`, P2.3): hold dry powder
in the carry-favored currency. **Whether** to deploy: `HOLD` under a defensive posture · `DEPLOY` into
names with a clean entry · `STAGGER` (ladder in) otherwise; a **convexity tranche is reserved** when
the crisis (B) weight is rich. Smoke: carry +1.58pp USD, LOAD on AGA.V → **DEPLOY, hold powder in USD**.

## Engine wiring
`engine.py` (`evaluate_master_architecture`, after posture is set) attaches
`terminal_state["conditionals"]` = `{aga_add, invalidation, dry_powder, flags, glossary}`, fed by the
`holdings`/`usdcad_read` built once and shared with P2.3/P3. Graceful throughout: missing entry reads
⇒ the add gate holds; missing posture ⇒ degrades, doesn't crash.

## Acceptance — status
- ✅ AGA add gate: 3 conditions, proportional sizing, hard 60% ceiling, fails closed on unverified entry.
- ✅ Per-thesis invalidation lines wired to the SENTINEL flags + per-name forensics; tailwinds kept as context.
- ✅ Dry-powder deployment driven by the USD/CAD carry tilt + posture + scenario weights.
- ✅ Tunables proposal-gated (`conditionals.*`); spear ceiling is a non-configurable invariant; no `eval()`.

## Deferred (flagged honestly)
- **Entry reads + per-name forensics** (`entries`, `name_signals`) come from `@entry-sentinel` and the
  conviction ratings (JSF) — the agent layer supplies them; until wired, the add gate fails closed and
  invalidation runs on the SENTINEL flags (the wired path).
- **TUI panel**: the data surface is complete; a dedicated "playbook" panel render is the remaining UI step.

## Tests
`tests/test_conditionals.py` (25) — the add gate (all branches incl. ceiling / fail-closed / cap
scaling), invalidation (flag-driven + forensic + context), dry-powder, and the consolidator. 351 green
across the affected dependency-free suites.
