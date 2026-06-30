# Wealthsimple Integration — Capability Assessment (2026-06-30)

*The book is held and traded on Wealthsimple (see `CLAUDE.md`). This assesses connecting that account
to the engine so the calibration flywheel can grade the desk's **IRL decisions** — what was actually
bought/sold/held and what it returned — not just the model against the market. Grounded in the
codebase (file:line) and in straight-to-source research (URLs + as_of 2026-06-30). Nothing is built;
this is a capability assessment.*

---

## Verdict

**Build it as a CSV importer for Wealthsimple's own "Activities export" — the sanctioned, ToS-clean,
zero-credential path. It yields exactly the grading data the flywheel is starved of.** There is **no
official Wealthsimple API**. A maintained *unofficial* GraphQL library (`gboudreau/ws-api-python`)
delivers the same data live — but it holds **trade-capable tokens that "can be used to empty your
account," violates Wealthsimple's ToS, and breaks without notice** (it already broke the entire prior
library generation). The convenience of live sync is not worth that risk when a first-party CSV export
carries the identical executed-fill + cost-basis data. **Recommend: CSV-export MVP now; the unofficial
API only ever as an opt-in, read-only, never-auto-trade fallback if unattended sync is later required.**

The prize is real: the flywheel today grades the **model vs the market**; it has **no idea what the
operator actually did**. Closing that loop is the highest-leverage fix for the reassessment's central
finding — *"is the yardstick proven against what actually happened?"* — because Wealthsimple is where
"what actually happened" lives.

---

## (a) First principles — what this is for

The engine produces a verdict (rating · directive · entry zone · sizing). The operator acts on it **on
Wealthsimple**. Realized P&L happens **on Wealthsimple**. Today the loop is open: the engine never sees
the operator's side. A WS connection closes it —

```
engine rating/directive  →  operator's REAL trade on Wealthsimple  →  realized P&L  →  graded back into the flywheel  →  learned base rates  →  next underwrite
                                         └────────────── the missing arrow ──────────────┘
```

Wealthsimple is the **source of realized truth** for the desk. The integration's job is to carry that
truth — executed fills (ticker, side, qty, price, date, account) and positions (cost basis) — into the
grading loop, **deterministically and provenance-stamped**, so the desk learns whether its *real*
calls, at its *real* fill prices, actually paid.

## (b) Hard questions

- **Are we grading the model or the operator?** Today, only the model-vs-market. We claim a calibrated
  desk while never checking whether the operator *followed* the calls or what they *made*. That's a
  yardstick graded against a simulation, not reality.
- **Is the book even what we think it is?** Config says `barbell_weights` = AGA/GROY/URC/GMX; the
  operator says URC is gone. We found that drift by accident. WS positions are ground truth; without
  them, config-vs-reality drift is invisible until someone trips on it.
- **What's the worst that the easy path can do?** The unofficial API stores tokens that can empty a
  brokerage account. Is unattended convenience worth a catastrophic-leak surface on a research tool?
- **Do imported fills get the same trust scrutiny as any other fed data?** A mis-parsed CSV silently
  corrupts the flywheel. First-party fills are high-trust, but the *parser* is not — it needs the
  verify-before-wire discipline (validate against a real export; stamp provenance; human-confirm).

## (c) Current practice & the gap (grounded)

- The flywheel grades a frozen decision against a **`realized_price`** via
  `calibration.score_outcome(decision, realized_price, …)` (`calibration.py:80`) — computing
  `realized_return = realized_price/p0 − 1`, which ladder leg it hit, upside-capture, etc.
- That `realized_price` is a **cached market close** from `price_history`, *never the operator's fill*:
  *"the realized price is exogenous… a replay is reproducible"* (`replay.py:6`, `calibration.py:793`);
  the heartbeat close uses *"the live ladder price as the realized mark"* (`calibration.py:855`).
- The write surface already exists and is thin: `record_decision(ticker, verdict, source)`
  (`mcp_server/core.py:1153`), `record_outcome(ticker, realized_price, horizon_days)` (`:1195`),
  `record_conviction(…)` (`:1220`), `calibration_scorecard(…)` (`:1450`). These are the exact ports a
  WS feed would write — **realized fills → `record_outcome` with the operator's price, not a proxy.**
- **No broker/Wealthsimple scaffolding exists** (repo-wide grep: only the unrelated archetype
  `calculate_cost_basis` legs). This is greenfield, and the flywheel is starved — Phase 0 found
  `replay graded=0`, Living Memory = 3 decisions / 0 closed. The loop has the ports; it lacks the data.

**Where it strains:** the desk reports calibration it cannot actually compute (no realized-execution
data), and the book's membership/weights can silently diverge from the real account.

## (d) The capability — three high-leverage unlocks

1. **Grade REAL execution, not a market proxy.** Feed actual fills + realized P&L into
   `record_outcome`/`record_decision` → the Druckenmiller objective (slugging · expectancy ·
   upside-capture · containment) runs on *real money*. This is the realized-outcome data the loop needs
   to stop being "graded against nothing." *Highest leverage — it directly answers the ungraded-yardstick finding.*
2. **Auto-reconcile the book.** WS positions = ground truth for membership + weights → the engine flags
   `barbell_weights`-vs-reality drift automatically. **This is exactly the URC case** ("we don't hold
   URC" while config did) — it would have raised its own hand.
3. **Calibrate entry/execution.** The entry-sentinel's "am I top-blasting" zones and the directives get
   graded against *actual* fill timing + slippage — did acting on the call at the real entry price pay,
   or did the operator chronically buy the top of the zone?

## (e) Feasibility & options (straight-to-source, as_of 2026-06-30)

| Path | What it yields | ToS / risk | Verdict |
|---|---|---|---|
| **★ Native "Activities export" CSV** (my.wealthsimple.com → Activity/Statements → Download; pick account + date range) | Buys/sells/deposits/options events per account, with dates/amounts; + monthly statement CSV-in-ZIP. First-party. | **Clean** — first-party export, no creds, stable, no reverse-engineering to break. | **ADOPT (MVP)** |
| `gboudreau/ws-api-python` / `-php` (unofficial GraphQL, **maintained**, last push 2026-06-01) — `getActivities()` (DIY_BUY fills), `getIdentityPositions()` (cost basis: `bookValue`, `averagePrice`, `unrealizedReturns`), quotes | Same grading data, live + richer per-field structure. | **Severe** — stores tokens that "can be used to empty your account"; violates the anti-scraping ToS; trade-side use is **actively detected + bannable**; no contract → breaks (already killed the 2020–22 REST libs). | **FALLBACK ONLY** — opt-in, read-only, never auto-trade |
| SnapTrade (official-ish aggregator bridge) | Read positions/balances/activities w/ permission | Paid third party that *itself* custodies WS credentials; per-field detail unpublished. | **PILOT** if a managed live feed is wanted later |
| Wealthica (Canada investment aggregator) | Managed investment-account feed | Third-party custody; Canada-specialist. | Alternative to SnapTrade |
| Plaid / Flinks | **Bank-account linking only** — not brokerage positions/fills | n/a | **REJECT** — wrong data |
| Manual entry via existing `record_decision`/`record_outcome` | Whatever the operator types | None | Stopgap / always available |

*No official API exists* (SnapTrade's own page: *"Wealthsimple does not offer a developer API"*).
Auth on the unofficial path is email+password+**2FA TOTP** → access+refresh tokens with auto-refresh;
the library's own README warns never to store the session in a git repo. **Could-not-verify:** the
exact CSV **column schema** (explicit ticker/qty/price columns vs. a description string) is not in
source docs — **validate against one real export before building the parser.** Token TTL and rate
limits are also unpublished.

*Sources:* snaptrade.com/brokerage-integrations/wealthsimple-api · github.com/gboudreau/ws-api-python
(README) · github.com/MarkGalloway/wealthsimple-trade (legacy API.md) · wealthsimple.com/en-ca/legal/terms ·
help.wealthsimple.com (Request a custom statement / monthly statements).

## Recommended MVP — sequenced, gated

1. **Validate the export schema (operator action).** Get one real Activities-export CSV; confirm the
   actual columns (the one unverified fact). *No code until the schema is known — grounded-or-silent.*
2. **Parser → normalized fills** (`ws_import.py`, deterministic, engine-side): export CSV →
   `{ticker, side, qty, price, date, account}`, each **provenance-stamped** `{source: "WS export <file>",
   as_of, confidence: high}` (a first-party reported fill is high-trust — like a filing line, *unlike*
   a derived estimate). Unit-tested against the real export. *Code-behind-tests.*
3. **Book reconciler (read-only):** WS positions vs `barbell_weights` → a drift report (the URC
   detector). Surfaces in the cockpit; never auto-edits the book. *Read-only.*
4. **Wire fills → the flywheel** through the existing `record_decision`/`record_outcome` ports —
   **behind operator confirm** (the import is shown and confirmed before it grades; mis-parses can't
   silently corrupt the loop). *propose→confirm.*
5. **Cadence:** run on import (monthly, or after any rotation). Then `replay.grade_ledger` +
   `calibration.scorecard` finally run on **real** outcomes.
6. **Only if unattended sync is later wanted:** add `ws-api-python` as a read-only fetch adapter behind
   the same parser interface — **opt-in, env-gated credentials never in the repo, never auto-trade**,
   with the hardened-runner discipline from the reassessment's TF4. *Operator decision.*

**Discipline carried over:** engine stays the single source of truth (it still computes ratings; WS
only feeds *realized* outcomes); deterministic import lives **engine-side**, not in the agentic layer
(parsing a CSV needs no judgment); the agents only come in to *interpret* the graded result (did we
follow our calls? why did we deviate?). Imported fills are provenance-stamped; the reconciler is
read-only; the grade-wiring is human-confirmed — the same trust chain as the verify-before-wire gate.

## Top risks

1. **Security (live API only):** trade-capable tokens that can empty the account — catastrophic on leak.
   The CSV path carries **none** of this. *This alone is why CSV is the MVP.*
2. **ToS termination (unofficial API):** anti-scraping violation; trade-side use actively detected +
   bannable. CSV export is a sanctioned first-party feature.
3. **Breakage (unofficial API):** no contract; already broke once. CSV is stable.
4. **CSV schema unknown:** validate the parser against a real export before trusting it (step 1).
5. **Mis-parse corrupting the flywheel:** mitigated by provenance-stamping + the operator-confirm gate
   before any imported fill grades.

---

*Assessment only — nothing built. The MVP above is a proposal; each step's gate is marked. The
Wealthsimple-as-execution-venue context is recorded in `CLAUDE.md` for future conversations.*
