# Handoff 2026-09-11 — AGA spear death, silver rebuild, TLT sleeve, CEG hold

**Session verdict:** Silver47 (`AGA.V`) ceased to be the silver-spear after the Bunker Hill
combination. Do **not** hold AGA through November close except as a thin merger stub. Rebuild
the spear *after* the next FOMC session, not into it. Core stack: **AG / BRC / SVE**. Hold
**CEG**. Keep the **TLT Sep-30 put sleeve small**; Sep-18 bounce calls already closed flat.
~50% cash into the meeting is the posture, not a cop-out.

This document is the reasoning record from the 2026-09-11 Grok/operator tape (CPI fade → FOMC
week). Operational ingest: `scripts/bootstrap/ingest_handoff_2026_09_11.py` (idempotent;
`--dry-run` prints the plan). Engine state (`v5_config.json` barbell weights, units, NAV) is
**not** mutated here — membership changes still go through `/gauntlet` → `promote_to_eval` /
`add_holding` / `remove_holding` after fills.

---

## Read this first: what is NOT verified

Session prices, RSI prints, option last-trades, merger ratio chatter, PEA NPVs, and
"~50% cash" are **operator/session-supplied**, not engine marks and not SEDAR+/EDGAR pulls.

- TLT ~$80.78 prior close / ~$81.10–81.23 tape, 10y spike toward 4.99%, CPI 0.4%/3.4% headline
  and 0.3%/2.4% core, Brent "$100–105", unemployment 4.1% / payrolls +162k, CEG ~$101B cap and
  −2.7% announcement-day print, AGA exchange **0.1724 BNKR per AGA**, BRC PEA figures, AG/HL
  prices ~$20 — treat as `verified: false` reference levels.
- No `get_world_state` / conviction baskets were available in this pass.
- Nothing downstream should treat these numbers as prints. Open item **OI-6**.

**Nothing here sizes a trade.** It freezes intent so the next Council / `/replace AGA.V` /
`/entry AG` run inherits the argument instead of rediscovering it from a chat log.

---

## Where everything landed

| Handoff section | Store | How to read it back |
|---|---|---|
| §1 situation | Living Memory `regime_snapshot` + `note` | `memory_query(tag="handoff-2026-09-11")` |
| §2 Ulysses pre-commitments | Living Memory `note` tag `ulysses` | `memory_query(tag="ulysses")` |
| §3 AGA thesis CLOSED | Living Memory `thesis` REJECT ticker **AGA.V** | `get_ledger(stance="REJECT")` |
| §4 spear rebuild (AG/BRC/SVE) | Living Memory `thesis` CONDITIONAL tickers **AG**, **BRC.V**, **SVE.V** | `memory_query(type="thesis", ticker=…)` |
| §5 TLT sleeve | Living Memory `note` + `forecast` | `memory_query(tag="tlt-sleeve")` |
| §6 CEG hold | Living Memory `note` tag `council-context` | `memory_query(ticker="CEG")` |
| §7 durable rules R-9, R-10 | Living Memory `note` tag `rulebook` + `docs/RULEBOOK.md` | `memory_query(tag="rulebook")` |
| §8 predictions | Living Memory `forecast` | `forecast_book()` |
| §9 open items | Living Memory `note` tag `open-item` | `memory_query(tag="open-item")` |
| Watchlist bench | `data/watchlist.json` | cockpit WATCHLIST |
| Universe seed | `data/candidate_universe.json` | `discovery_screen(slot="silver-spear")` |

All new Memory rows carry `meta.handoff = "2026-09-11-aga-spear-tlt"` and `provenance: user`.

---

## §1 — Situation (as of Fri 2026-09-11)

August CPI printed hot-then-fade: stocks and gold dumped at 8:30 ET and recovered inside ~20
minutes; the 10-year spiked toward 4.99% then eased. Prediction markets were pricing a hike as
near-certain while **the long end kept selling**. That pairing is the point of the duration
sleeve: a hike that is already priced is a *regime signal* (tighten into an oil/inflation
shock), not a bond-rally catalyst. Term premium, issuance, and energy are pushing the 10-year
independently of the next 25 bp.

Operator posture into FOMC week:

- ~50% cash. Do not force a gold/silver bid this tape.
- CEG: hold core; add only on a *rates-driven* dump while power/data-center demand is intact.
- TLT Sep-18 calls: **closed flat**. Correct.
- TLT Sep-30 puts: working (~+20% at session). Small sleeve. Do not add on breakdown. Add
  only on a squeeze into $81.30–$82.50 if the hike/oil/term-premium thesis is unchanged.
- AGA: sell the bulk *this week*, before FOMC. Assays do not resurrect standalone AGA.

Rough first-principles split used in-session (not a model):

- ~55–60% oil stays high, growth slows, long-end stays elevated → TLT bounce fades.
- ~25–30% policy error / demand break → oil drops, yields fall, TLT rallies (puts hurt).
- ~15% mixed / range.

---

## §2 — Ulysses pre-commitments (verbatim intent)

- **U-2026-09-11-A — Deal = thesis over.** When a junior announces a merger, the thesis is
  over unless you explicitly want the buyer. AGA → Bunker Hill is that case. Do not sit to
  November hoping assays or close "make you whole."
- **U-2026-09-11-B — Sell the dead name now, buy the replacement later.** Exits from stocks
  you do not want do not wait for FOMC. Entries into AG/BRC/SVE do.
- **U-2026-09-11-C — No lottery expiry through a known Fed meeting** unless that *was* the
  bet. Sep-18 TLT calls are done. Sep-30 puts may ride small.
- **U-2026-09-11-D — Do not press a wounded thesis.** AGA is not a jugular setup. Size
  follows a live thesis. Rebuilding silver after the meeting is a *new* trade.
- **U-2026-09-11-E — CEG dips are not silver substitutes.** Duration mark-to-market on PPAs
  is not a reason to sell the scarce baseload asset into a rates scare. Add CEG only if the
  dump is yields and power is still firm.
- **U-2026-09-11-F — Bond-book leftover, not a new campaign.** Harvest/trail the put sleeve.
  Do not reload Sep-18-style calls, do not turn put P&L into a bigger duration book that
  eats the silver cash, do not add a second product (ZB/TBT/TY) to feel in the game.

---

## §3 — AGA.V silver-spear CLOSED

Bunker Hill buys Silver47. Target close after November shareholder meetings. Exchange
**0.1724 BNKR per AGA** (session figure, unverified). Combined vehicle: Idaho restart +
Silver47 U.S. exploration; Bunker Hill holders ~57% / Silver47 ~43%. Mixed silver / zinc /
lead / mill-ramp / financing. Torque and silver purity both drop.

Pending Red Mountain assays and Belmont metallurgy re-rate **Bunker Hill Silver**, not
standalone AGA. Red Mountain is VMS (Ag + Zn/Pb/Au) — more of the dilution the operator
rejected. No collar, no extra cash if holes are monsters.

Graveyard stance: **REJECT** as silver-spear. Optional stub only if running the merger
spread and selling BNKR on day one.

Slot consequence: `silver-spear` is **vacant in spirit** until a replacement graduates.
CLAUDE.md still lists AGA.V as the incumbent until `remove_holding` runs after the fill.
Do not scout "replacements for AGA" as if the old binary-explorer object still exists
inside the surviving ticker.

---

## §4 — Rebuild stack (not yet held)

Operator stack after FOMC, if the dip shows up. **Not equal-weight.**

| Role | Name | Slot-fit | Notes |
|---|---|---|---|
| Producer torque (largest) | **AG** First Majestic | silver-spear *adjacent* — operator, Mexico, ~60% Ag revenue | Closest liquid replacement for *metal-rip this month*. Not explorer DNA. |
| Junior spear | **BRC.V** Blackrock Silver | silver-spear — NV PEA developer, Tonopah West | Closest AGA-like object that still has a path. PEA-stage = slightly *past* classic spear window; treat as rotation-challenger, run `/gauntlet` before any promote. |
| Lottery satellite (smallest) | **SVE.V** Silver One | silver-spear — earlier Candelaria NV optionality | Higher beta, thinner, raise/dead-hole risk. |
| Explicitly skipped | HL | safer producer | Quality duration already sits in CEG. |
| Explicitly skipped as spear | HSLV | mid-tier Peru build + Mercedes | Corani/capex, not U.S. explorer DNA. |
| Explicitly skipped as spear | NEM / AEM | senior gold | Ballast gold, not AGA torque. |
| Gold-royalty satellite (separate sleeve) | VOXR | gold-royalty-ballast challenger | Not a silver replacement. Pullback-only if used. |
| Hybrid / not the spear | OGN.V | already on WATCH | Ermitaño Au-Ag + prospect gen. Does not restore AGA silver beta. |

Workable split *if* all three are cheap after the meeting: **50–60% AG / 25–35% BRC / 10–15% SVE**.
If only one is cheap, buy that one. Do not force all three on the same print.

Entry timing from the session (unverified tape): do not chase mid-range. AG better $18.50–19.50;
HL $19.00–19.60 if used; BRC/SVE expected to gap first and recover last on hawkish hike + risk-off.

**Graduation path is unchanged:** `/screen silver` → WATCHLIST → `/gauntlet` → `promote_to_eval`
→ reweight / `add_holding` on a real Wealthsimple fill. This handoff does **not** skip the gate.

---

## §5 — TLT overlay

Thesis: hike priced + term premium + oil/supply inflation → long end can keep selling even
as front-end futures sit still. Invalidation: growth-scare (equities **and** oil breaking
together) or a dovish shock. Hiking into a supply shock has two historical exits; the
deflationary-recession path is the one that breaks the put.

Rules of engagement frozen this session:

- No add on new lows.
- Optional 10–15% peel only if silver cash must be locked; +20% is not "harvest the whole
  sleeve" if original size is still small.
- One add, same or smaller than the stub, only on a squeeze toward $81.30–$82.50 that is
  short-covering rather than a growth-scare bid.
- After the hike: if they hike and the long end *rallies*, that bounce is the cleaner add.
  If they hike and bonds keep dumping, do not chase.
- Mental stop on the working piece: if the gain is gone before the decision, flat, no
  revenge reload.

---

## §6 — CEG

Rhode Island State Energy Center (Shell, 609 MW gas CCGT, ISO-NE, $715m / ~$580m net after
tax benefits) is **negligible** at ~$101B cap; immediately accretive per issuer; buyback
untouched. Announcement-day −2.7% tracked the CPI/yield tape more than the deal.

A hike into falling bonds hits the **multiple** (long PPAs, AI-power duration) harder than
near-term earnings. Fundamentals can hold or improve if power stays tight. Hold the core.
Add on rates-driven dumps. Wait if power prices and data-center demand roll over with yields.

---

## §7 — New durable rules

See `docs/RULEBOOK.md` R-9 and R-10.

---

## §8 — Predictions (score later)

| id | claim | resolve-by | session confidence |
|---|---|---|---|
| P-1 | FOMC delivers the priced hike; 10y does **not** stage a lasting rally solely because the hike "happened." | first full session after the decision | 0.60 |
| P-2 | High-beta silver (BRC/SVE/AG) is messier than bullion into and immediately after the decision. | 2026-09-19 | 0.65 | **HIT (2026-09-19)** — Sep 10→18: bullion (SI=F) +3.53%, std 1.40%, orderly; AG −1.54% std 3.75% (−3.89% 9/14, −1.66% on decision day vs bullion +1.66%); BRC.V −0.86% std 3.77% (+6.14% 9/17 → −4.96% 9/18); SVE.V −4.60% std 6.30% (+9.52% 9/17 → −9.78% 9/18). Gapped first, recovered last, whipsawed after — exactly the §5 setup. |
| P-3 | AGA residual is a ratio claim; pending RM/Belmont news does not restore standalone explorer beta. | close / first BNKR session | 0.80 |
| P-4 | CEG announcement deal is not a 2026 thesis change. | 2026-12-31 | 0.75 |

---

## §9 — Open items

| id | item | blocks |
|---|---|---|
| OI-1 | Confirm AGA exit fill (date, units, WS proceeds) and run `remove_holding` / `record_decision` | book membership vs reality |
| OI-2 | Post-FOMC entry prices actually paid for AG / BRC / SVE — or "none filled" | rebuild |
| OI-3 | TLT Sep-30 put: peel / hold / stop after the decision | overlay size |
| OI-4 | `/gauntlet BRC.V` and `/gauntlet SVE.V` before any promote | spear integrity |
| OI-5 | Slot language in CLAUDE.md: vacant spear vs AGA still listed as incumbent until OI-1 | agent router |
| OI-6 | Verify session reference levels against engine / issuer / SEDAR+ | any promotion of ~ prices |
| OI-7 | Whether silver-spear may include a *producer* (AG) as core with junior satellites, or AG lives in a new `silver-operator-torque` slot | slot-fit law |

---

## Source

Operator + Grok session 2026-09-11 (CPI digestion into FOMC week). Provenance `user` /
`agent`. Not a filing.
