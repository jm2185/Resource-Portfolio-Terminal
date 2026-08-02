#!/usr/bin/env python3
"""
Ingest the 2026-07-31 session handoff — the CEG add program + the memory-complex surveillance file.

The handoff (docs/HANDOFF_2026-07-31_CEG_MEMORY.md) is a set of MANUAL INPUTS: pre-commitments the
operator made in calm blood, two underwriting records, the tripwires that watch them, the reference
facts a Council run should inherit, eight durable rules, and four dated predictions to be scored
later. This script puts each in the store that actually sweeps it, rather than leaving them in a
document nothing reads:

  §2 Ulysses pre-commitments  -> Living Memory ``note`` (tag ``ulysses``), VERBATIM
  §3 CEG-ADD-2026Q3           -> Living Memory ``thesis`` (CONDITIONAL, ticker CEG)
  §5 MEMORY-SHORT-2027-...    -> Living Memory ``thesis`` (REJECT — the graveyard entry is the point)
  §4/§5 dated triggers        -> ``catalyst_calendar`` windows (conventional-lane kinds)
  §4/§5 undated triggers      -> ``sentinel_watch`` registry (approval state carried per feed)
  §6 reference context        -> Living Memory ``note`` (tag ``council-context``)
  §7 R-1..R-8                 -> Living Memory ``note`` (tag ``rulebook``) + docs/RULEBOOK.md
  §9 P-1..P-4                 -> Living Memory ``note`` (tag ``prediction``), open, with resolve-by
  §8 open items               -> Living Memory ``note`` (tag ``open-item``), flagged to JM

IDEMPOTENT. Every record carries ``meta.handoff`` + ``meta.record_id``; a re-run skips anything
already present. Safe to run repeatedly, and safe to run before or after the engine is up.

GROUNDING — read this before trusting a number out of here. The handoff's ``~`` price levels are
operator-supplied from news flow and are NOT verified prints. The engine was offline and the price
layer does not carry CEG / CEGS.TO / MU (FMP quote + chart endpoints are gated on the current plan),
so verification was NOT possible in this pass. Every such level is written with
``verified: false`` + its provenance, is confined to the thesis body's ``reference_levels``, and is
never written into an engine-owned field. Open item §8.6 stays open until they are checked.

Run from the repo root (or anywhere — it inserts the root on sys.path):

    python scripts/bootstrap/ingest_handoff_2026_07_31.py            # write to the tracked stores
    python scripts/bootstrap/ingest_handoff_2026_07_31.py --dry-run  # print the plan, write nothing
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import argparse
import json

import sentinel_watch as sw
import thesis_ledger as tl
from catalyst_calendar import CatalystCalendar
from living_memory import LivingMemory

#: The batch marker. Every record this script writes carries it, so the whole ingestion is
#: identifiable, auditable, and (with ``record_id``) re-runnable without duplication.
HANDOFF = "2026-07-31-ceg-memory"
DATE = "2026-07-31"
SOURCE = "handoff-2026-07-31"

#: Provenance for the batch: these are the OPERATOR's pre-commitments and reads, not engine numbers
#: and not sourced filings. ``user`` is the honest tier — a consumer weighting by evidence must not
#: mistake a handoff paragraph for a straight-to-source fact.
PROV = "user"


# =============================================================================== §2 Ulysses ledger
# Pre-commitments, appended VERBATIM. The wording is the point: a pre-commitment paraphrased is a
# pre-commitment renegotiated.
ULYSSES = [
    ("U-2026-07-31-A", "Ballast over spear (AI column)", "CEG",
     "Chose ballast over spear in the AI-upside column at ~$252 CEG-equivalent, July 2026, "
     "knowing the spear (MU) had more torque, because the spear had a clock (2027–28 supply "
     "wave) and the book had no attention budget for it. Do not relitigate mid-rally if "
     "memory makes new highs while CEG grinds."),
    ("U-2026-07-31-B", "No memory long", "MU",
     "No MU, SKHY, SNDK, or memory-complex long positions. Interest was generated post-run, "
     "post-crash, on a +18% bounce day — the March-2000 emotional signature. If unable to "
     "articulate why I wasn't interested at $400 but was at $900, the position to manage is "
     "not in memory."),
    ("U-2026-07-31-C", "Instrument/thesis clock matching", None,
     "Daily-reset leveraged products (MUU or any equivalent) are permitted only for theses "
     "measured in days, never weeks/months. Volatility decay converts price bets into path "
     "bets. Options premium, decay drag, and margin risk are the same leverage bill paid at "
     "different windows — there is no free leverage."),
    ("U-2026-07-31-D", "No-leverage invariant (reaffirmed)", None,
     "Case study: Situational Awareness, $45B → forced block liquidation to Citadel at 4x "
     "leverage, July 30 2026, thesis arguably correct. No position in this book may ever "
     "have a mechanism by which a counterparty forces exit at the bottom. Cash sizing only."),
    ("U-2026-07-31-E", "CEG tranche-2 gap-up rule", "CEG",
     "If Aug 6 print CONFIRMS (per §3 criteria) and stock gaps up, tranche 2 still "
     "executes. A worse entry inside an intact underwriting zone ($340–360 target basis) "
     "changes the IRR decimal, not the thesis. Green gap ≠ 'missed it'; red gap on a "
     "confirm ≠ 'knife'."),
]


# =============================================================================== §3 CEG thesis
# The CONFIRM criteria are the load-bearing CLAIMS, deliberately. That is not a filing detail: the
# Sentinel re-checks claims every sweep and flags the thesis when integrity drops below its floor, so
# writing the criteria as claims is what makes R-7 (pre-registered confirm criteria) machine-enforced
# instead of a promise. All are ``manual`` — the operator flips them after listening to the call; no
# engine metric can read a guide. The DISCONFIRM set is exactly their negation.
CEG_CLAIMS = [
    tl.new_claim("FY26 adjusted EPS guide $11–12 reaffirmed or raised (CONFIRM #1). "
                 "Cut or withdrawn = DISCONFIRM and whole-position invalidation.",
                 cid="c1", check="manual", status="unknown"),
    tl.new_claim("No walk-back on the data-center PPA pipeline (CONFIRM #2). Pipeline hedged or "
                 "deferred = DISCONFIRM, tranche 2 cancelled.",
                 cid="c2", check="manual", status="unknown"),
    tl.new_claim("PJM cap regime framed as manageable within guidance, PTC offset stated or implied "
                 "(CONFIRM #3).", cid="c3", check="manual", status="unknown"),
    tl.new_claim("Crane/TMI restart timeline intact into the September NRC final EA (CONFIRM #4).",
                 cid="c4", check="manual", status="unknown"),
    tl.new_claim("Bilateral PPAs price OUTSIDE the capped PJM capacity market, and the nuclear PTC "
                 "acts as an inverse-subsidy revenue floor when market revenues fall — the "
                 "mechanism the whole low-cluster/high-cluster analyst dispute turns on.",
                 cid="c5", check="manual", status="holds"),
    tl.new_claim("The position works on the $340–360 ex-extremes underwriting basis — it does "
                 "NOT require Scotiabank's $441 world.", cid="c6", check="manual", status="holds"),
    tl.new_claim("Post-add CEGS ceiling (% of book) is WRITTEN before order 1 (§8.2). Held "
                 "'unknown' on purpose: it is unanswered, and an unanswered load-bearing claim must "
                 "drag integrity, not sit invisible.",
                 cid="c7", check="manual", status="unknown"),
]

# Rules fire on ``event:<kind>`` — and the grammar's events are CALENDAR KINDS that have been marked
# ``hit`` (catalyst_calendar.hits_by_kind). So each rule below is armed by a real dated window in
# CALENDAR, not by a free-text event name that nothing could ever stamp.
CEG_RULES = [
    tl.new_rule("event:earnings", "review", rid="r1"),
    tl.new_rule("event:regulatory", "review", rid="r2"),
    tl.new_rule("event:contract_award", "alert", rid="r3"),
    tl.new_rule("event:equity_offering", "review", rid="r4"),
]

CEG_THESIS = tl.build_thesis(
    "CEG", archetype="conventional_cashflow", stance="CONDITIONAL",
    claims=CEG_CLAIMS, rules=CEG_RULES, entered_at=DATE,
    expected={
        "underwriting_basis_usd": [340, 360],
        "bear_case_usd": 297,
        "consensus_usd": [352, 372],
        "basis_note": "ex-extremes middle of street; bear case Citi/Levine $297. The position must "
                      "work without Scotiabank's $441.",
    },
    intangibles={
        "program_id": "CEG-ADD-2026Q3",
        "instrument": "CEGS.TO",
        "instrument_note": "CDR, CAD-hedged — an FX-neutral expression, hedge cost ~0.5–0.6% "
                           "annualized embedded; deliberate, consistent with the AI-upside column "
                           "scenario. The UNDERWRITING SUBJECT is CEG (this thesis's ticker); "
                           "CEGS.TO is how it is expressed at the brokerage.",
        "role": "AI-upside column ballast. Primary vehicle for the ~45% combined AI-productivity + "
                "benign probability weight. No spear added to this column (see U-2026-07-31-A).",
        "position_status": "NOT YET HELD — this is an add PROGRAM, frozen before the print. "
                           "Tranche 1 is unexecuted as of the handoff.",
        "idiosyncratic_catalyst":
            "Q2 2026 print + call (2026-08-06, pre-market release, 10:00 ET call) — the gate on "
            "tranche 2. Then the September NRC final EA/FONSI on the Crane restart.",
        "thesis":
            "Price-down-value-up divergence. CEG −35% H1 2026 (52-wk low $228.63 on Jul 1) while "
            "fundamentals accrued: Calpine closed (Jan), Walmart 15-yr nuclear PPA (Jun, ~176 MW), "
            "Q1 beat, FY26 guide $11–12 reaffirmed, 20%+ EPS growth guided through 2029, 20-yr "
            "Meta/Microsoft PPAs anchor. Trading ~21–22x reaffirmed guide. Microsoft Azure print "
            "(Jul 30) = direct demand validation for the largest counterparty class. Bilateral PPAs "
            "price OUTSIDE the capped PJM capacity market; the nuclear PTC acts as an "
            "inverse-subsidy revenue floor when market revenues fall.",
        "macro_prerequisite":
            "The AI-capex demand cycle holds up through the contracting window. The macro "
            "cross-link is live: a bear-steepener / fiscal-dominance repricing compresses the whole "
            "AI complex, CEG included — that watch is already wired (rates monitor).",
        "narrative_invalidation":
            "FY26 guide withdrawn or cut. PRICE WEAKNESS WITH THE GUIDE INTACT IS NOT "
            "INVALIDATION — it is the opportunity the program was built to buy.",
        "forensic_waiver": None,
        "tranches": {
            "t1": {"fraction": "25–33% of intended add (§8.3 — unconfirmed)",
                   "deadline": "2026-08-05 close (print is pre-market Thu 2026-08-06)",
                   "execution": "limit orders at mid; no market orders; avoid the open/close auctions",
                   "size_test": "a −15% gap Thursday must be emotionally invisible"},
            "t2": {"fraction": "balance of the add",
                   "gate": "CONFIRM only (claims c1–c4), assessed AFTER the call review",
                   "rule": "on criteria, never on price action — see U-2026-07-31-E"},
        },
        "special_rule":
            "Headline EPS miss + guide reaffirmed = CONFIRM. If the stock sells off on that "
            "combination it is the GIFT scenario — tranche 2 at better prices. Single-quarter EPS "
            "is explicitly NOT a confirm criterion (est. range $2.00–3.34, refueling-outage "
            "noise) — rule R-8.",
        "pre_work_due":
            "PJM homework, weekend of Aug 1–2 (§8.4): reconcile the low-cluster ($296–305) "
            "model logic against (a) the Jul 14 auction actuals, (b) PTC inverse-subsidy mechanics, "
            "(c) the PPA-bypass revenue share. Purpose — listen to the call as an ADVERSARIAL "
            "TEST, not a bull-narrative confirmation.",
        "reference_levels": {
            "_warning": "OPERATOR-SUPPLIED from news flow, NOT verified prints. The engine was "
                        "offline and the price layer does not carry CEG/CEGS.TO; the FMP quote and "
                        "chart endpoints are gated on the current plan, so this pass could NOT "
                        "verify them. Do not promote any of these into an engine-owned field. "
                        "Open item §8.6.",
            "verified": False,
            "levels": {
                "low_52w_usd": 228.63, "low_52w_date": "2026-07-01",
                "spot_usd_approx": [248, 252],
                "consensus_target_usd": [352, 372],
                "h1_2026_drawdown_pct": -35,
                "jun_secondary": {"shares_m": 11, "price_usd": 281, "proceeds_usd_b": 3.1},
            },
        },
        "open_items": ["§8.1 total intended add size", "§8.2 post-add ceiling (% of book)",
                       "§8.3 tranche 1 fraction"],
        "sweep_gap":
            "NOT covered by sentinel_sweep: the sweep iterates the HELD book's conviction baskets, "
            "and CEG is neither held nor in the eval set, so no engine metric (φ/ρ/JSF/price) is "
            "diffed against these claims. What IS live: the manual claims (operator-flipped) and "
            "the calendar-armed rules. Treat this thesis as a frozen underwriting record + a "
            "tripwire set, not as an engine-swept position.",
    },
    linked_calendar=["CEG:earnings:2026-08-06", "CEG:regulatory:2026-09"],
    source_urls=[],
)


# =============================================================================== §5 memory thesis
# Recorded as a REJECT. That is not a downgrade of the research — the Ledger's graveyard exists
# precisely so a name you PASSED ON keeps being tracked ("tracking them is how you learn what you
# wrongly skipped", thesis_ledger.Ledger.graveyard). The standing short thesis to test in 2027 rides
# in the body; the position today is none.
MEM_CLAIMS = [
    tl.new_claim("No memory-complex long is held (MU, SKHY, SNDK, WDC) — U-2026-07-31-B.",
                 cid="c1", check="manual", status="holds"),
    tl.new_claim("The July 2026 capex wave (SK Hynix +50% to ≥$31B; Samsung P5 restart; Korea "
                 "₩800T national program; CXMT $8.6B STAR IPO) lands as wafers late-2027/2028.",
                 cid="c2", check="manual", status="holds"),
    tl.new_claim("Producer guidance still EXTENDS the shortage (Samsung 'through 2028') while capex "
                 "expands at a record — the R-4 late-cycle tell, on an ~18-month fuse.",
                 cid="c3", check="manual", status="holds"),
    tl.new_claim("Contract pricing — not the stock price — is the thesis clock; the setup "
                 "announces itself in contract data ≥2 quarters before price (P-2).",
                 cid="c4", check="manual", status="holds"),
    tl.new_claim("The R-5 $400/$900 check is UNANSWERED in writing — therefore no entry is "
                 "permitted on either side.", cid="c5", check="manual", status="holds"),
    tl.new_claim("The Jul 29 forced-liquidation low holds on retest (P-1). Flip to broken on a "
                 "breach — that kills the capitulation-low read.",
                 cid="c6", check="manual", status="unknown"),
]

MEM_RULES = [
    tl.new_rule("event:supply_data", "alert", rid="r1"),
    tl.new_rule("event:earnings", "review", rid="r2"),
]

MEM_THESIS = tl.build_thesis(
    "MU", archetype="cyclical_producer", stance="REJECT",
    claims=MEM_CLAIMS, rules=MEM_RULES, entered_at=DATE,
    expected={
        "position": "NONE — surveillance only",
        "short_candidate_ranking": ["SNDK-type (spot NAND, no contract floor, peak multiple)",
                                    "WDC", "SKHY ADR", "MU (take-or-pay floors = worst short)"],
        "window_opens": "2027 (market front-runs a supply wave 2–4 quarters early)",
    },
    intangibles={
        "program_id": "MEMORY-SHORT-2027-RESEARCH",
        "surveillance_only": True,
        "subject_note":
            "Filed under MU as the complex's bellwether and the name actually evaluated and passed "
            "on. The SUBJECT is the memory complex (MU, SKHY, SNDK, WDC, CXMT), not MU alone. The "
            "REJECT stance is the July-2026 verdict on the LONG — it is not a permanent view, and "
            "the standing SHORT thesis below is what the 2027 dataset is being built to test.",
        "idiosyncratic_catalyst":
            "The monthly DRAM/NAND contract print. A rollover starts the clock — that, not a "
            "stock price, is what this file is watching for.",
        "standing_thesis":
            "The largest coordinated memory supply wave in industry history was committed publicly "
            "in July 2026 (SK Hynix capex +50% to ≥$31B; Samsung P5 restart; Korea ₩800T "
            "national program; CXMT $8.6B STAR IPO; reported China DUV progress). Capex lands as "
            "wafers late-2027/2028. Markets front-run supply waves 2–4 quarters early, so the "
            "discounting window opens ~2027. Producer pattern match: record margins + "
            "shortage-extending guidance + max capex = the classic late-cycle tell.",
        "why_no_position":
            "Interest was generated post-run, post-crash, on a +18% bounce day — the March-2000 "
            "emotional signature. The spear had more torque than CEG but it had a CLOCK (the "
            "2027–28 supply wave) and the book had no attention budget for it "
            "(U-2026-07-31-A/B).",
        "narrative_invalidation":
            "For the standing SHORT thesis: a producer capex CUT (cycle discipline restored) or "
            "guidance that stops extending the shortage — both would defuse the 18-month fuse "
            "before it burns. For the P-1 capitulation read: a breach of the Jul 29 low.",
        "reference_levels": {
            "_warning": "OPERATOR-SUPPLIED from news flow, NOT verified prints — the handoff "
                        "itself flags these for verification and the price layer does not carry "
                        "these names (FMP quote/chart gated on the current plan). Open item §8.6.",
            "verified": False,
            "levels": {
                "MU": {"peak_usd": 1213, "peak_date": "2026-06-25", "sa_low_usd": 775,
                       "sa_low_date": "2026-07-29", "jul30_usd_approx": 900},
                "SKHY": {"jul29_close_usd": 126.79},
                "complex_drawdown_pct": [-20, -50],
            },
        },
        "sweep_gap":
            "NOT covered by sentinel_sweep (MU is not held and not in the eval set). In particular "
            "the Jul-29-low retest (c6) is NOT machine-armed: the grammar's ``price``/``floor`` come "
            "from a conviction basket the engine does not compute for MU. It is watched by "
            "sentinel_watch item ``mem.sa_liquidation_low_retest`` — which is PENDING APPROVAL "
            "(§8.5), so nothing is watching it automatically today.",
    },
    linked_calendar=["MU:earnings:2026-09-22"],
    source_urls=[],
)


# =============================================================================== §4/§5 calendar
# ONLY genuinely dated events. The "ongoing"/"event" rows of §4 get no invented window (that would
# break grounded-or-silent) — they go to the watch registry below.
# Confidence is 'guided' not 'scheduled' throughout: a SCHEDULED named-ticker window requires a
# straight-to-source URL, and this batch has none (the handoff is prose). Downgrading is the honest
# move and the calendar enforces it.
CALENDAR = [
    # (ticker, kind, title, start, end, confidence, notes)
    ("CEG", "earnings",
     "Q2 2026 results — pre-market release, 10:00 ET call",
     "2026-08-06", "2026-08-06", "guided",
     "THE GATE on tranche 2 of CEG-ADD-2026Q3. Assess the four CONFIRM criteria (thesis claims "
     "c1–c4) on the call. Quarterly EPS is explicitly NOT a criterion (R-8: refueling-outage "
     "noise, est. $2.00–3.34). Headline miss + guide reaffirmed = CONFIRM, and a sell-off on "
     "that combination is the gift scenario. Date is operator-supplied — no source URL, hence "
     "'guided' not 'scheduled'."),
    ("CEG", "regulatory",
     "NRC Crane/TMI restart — final environmental assessment + FONSI",
     "2026-09-01", "2026-09-30", "estimated",
     "CONFIRM criterion #4 (claim c4) rides on this timeline staying intact. Month-wide window: "
     "the handoff gives 'Sep 2026' with no published date."),
    ("MU", "earnings",
     "FQ4 2026 results — the guidance-language and capex-discipline read",
     "2026-09-22", "2026-09-22", "estimated",
     "Surveillance only, no position. Read the GUIDANCE LANGUAGE (does the shortage still extend?) "
     "and capex discipline per R-4 — not the EPS. A capex cut would defuse the 18-month fuse."),
]


# =============================================================================== §4/§5 watch registry
# The undated half. §5's memory feeds land at pending_approval BY DESIGN — §8.5 asks JM to approve
# them per feed against the API-only/resource-starvation constraint, so counting them as covered
# would be exactly the lie the coverage read exists to prevent.
WATCHES = [
    # --- §4 CEG ---------------------------------------------------------------------------------
    sw.new_watch(
        "ceg.pjm_regulatory", "CEG", "PJM cap/floor regime + data-center backstop procurement",
        signal="Progression of the data-center backstop procurement plan; cap/floor terms set for "
               "the 2029/30 BRA.",
        why="The entire low-cluster ($296–305) vs high-cluster ($362–441) analyst dispute is "
            "about this regime vs the PPA/PTC offset — not about the AI narrative.",
        cadence="monthly", source="PJM + FERC public filings/dockets", status="active",
        feeds=["CEG-ADD-2026Q3"], lands_as="regulatory", added=DATE, last_review=DATE),
    sw.new_watch(
        "ceg.ppa_tape", "CEG", "Hyperscaler / corporate nuclear PPA tape",
        signal="Any new long-dated nuclear PPA signed (the Walmart 15-yr / ~176 MW template).",
        why="The re-rating catalyst — each one prices revenue OUTSIDE the capped PJM capacity "
            "market, which is the mechanism claim c5 rests on.",
        cadence="event", source="Issuer PR / newswire (verify straight-to-source)", status="active",
        feeds=["CEG-ADD-2026Q3"], lands_as="contract_award", added=DATE, last_review=DATE),
    sw.new_watch(
        "ceg.ny_moratorium", "CEG", "NY 1-yr data-center permit moratorium — spread risk",
        signal="Other states adopting an environmental-permit moratorium on large data centers.",
        why="Demand-side political risk to the PPA pipeline (claim c2) that shows up as policy, "
            "not as an earnings line.",
        cadence="monthly", source="State legislative/regulatory trackers (public)", status="active",
        feeds=["CEG-ADD-2026Q3"], lands_as="regulatory", added=DATE, last_review=DATE),
    sw.new_watch(
        "ceg.secondary_overhang", "CEG", "Follow-on secondary block sales by existing holders",
        signal="A registered block/secondary (the Jun template: 11M shares @ $281, $3.1B).",
        why="Supply overhang on the tape — it moves the entry, never the thesis. Relevant to "
            "tranche timing, and a red gap on a CONFIRM is not a knife (U-2026-07-31-E).",
        cadence="event", source="EDGAR (424B/8-K) + newswire", status="active",
        feeds=["CEG-ADD-2026Q3"], lands_as="equity_offering", added=DATE, last_review=DATE),
    sw.new_watch(
        "ceg.reference_levels", "CEG", "Verify the handoff's (~) price levels against a data feed",
        signal="52-wk low $228.63 (Jul 1); spot ~$248–252; consensus ~$352–372; the Jun "
               "secondary at $281.",
        why="§8.6 — unverified levels must not reach an engine-owned field. Until a feed "
            "carries CEG/CEGS.TO these stay stamped verified:false in the thesis body.",
        cadence="weekly",
        source="BLOCKED — the price layer does not carry CEG/CEGS.TO and the FMP quote + chart "
               "endpoints are gated on the current plan. Needs a source decision from JM.",
        status="pending_approval", feeds=["CEG-ADD-2026Q3"], added=DATE, last_review=DATE,
        note="Not a data feed so much as a blocked verification task — tracked here so it cannot "
             "quietly lapse."),

    # --- §5 memory complex (all pending JM per-feed approval, §8.5) -----------------------------
    sw.new_watch(
        "mem.dram_nand_contract_pricing", "memory-complex",
        "DRAM/NAND monthly contract pricing — THE thesis clock",
        subject_kind="theme",
        signal="Monthly contract prints; a rollover starts the clock on the 2027 discounting window.",
        why="Ground truth over stock prices (P-2: the setup announces itself in contract data ≥2 "
            "quarters before price).",
        cadence="monthly", source="TrendForce / DRAMeXchange-class contract series (paid)",
        status="pending_approval", feeds=["MEMORY-SHORT-2027-RESEARCH"], lands_as="supply_data",
        added=DATE, last_review=DATE,
        note="The single highest-value feed in §5 — if only one is approved, this is it."),
    sw.new_watch(
        "mem.cxmt_disclosures", "memory-complex", "CXMT post-IPO STAR disclosures",
        subject_kind="theme",
        signal="Output, yield and capacity adds in the post-IPO filings.",
        why="Narrative vs actuals on the #4 DRAM producer (~8% share) — the supply leg most "
            "likely to be over- or under-stated in the press.",
        cadence="quarterly", source="SSE STAR Market filings (public, CN)",
        status="pending_approval", feeds=["MEMORY-SHORT-2027-RESEARCH"], lands_as="supply_data",
        added=DATE, last_review=DATE),
    sw.new_watch(
        "mem.capex_wafer_conversion", "memory-complex", "Capex → wafer conversion milestones",
        subject_kind="theme",
        signal="Deployment milestones on SK Hynix $31B, Samsung P5, the ₩800T program.",
        why="Times the 18-month fuse (R-4) — the difference between a 2027 and a 2028 window.",
        cadence="quarterly", source="Issuer capex disclosures + trade press",
        status="pending_approval", feeds=["MEMORY-SHORT-2027-RESEARCH"], lands_as="supply_data",
        added=DATE, last_review=DATE),
    sw.new_watch(
        "mem.sa_liquidation_low_retest", "memory-complex",
        "Situational-Awareness forced-liquidation low — retest",
        subject_kind="theme",
        signal="MU ~$775 area (Jul 29) and SKHY ~$126.79 (Jul 29 close) — EXACT PRINTS UNVERIFIED. "
               "A breach kills the capitulation-low read; holding on lower volume confirms it.",
        why="Resolves prediction P-1 (~6-week horizon) and thesis claim c6.",
        cadence="daily", source="BLOCKED — needs a price feed carrying MU/SKHY; not wired today.",
        status="pending_approval", feeds=["MEMORY-SHORT-2027-RESEARCH"], added=DATE, last_review=DATE,
        note="This is the one §5 item with a real clock on it (P-1 resolves ~mid-September). "
             "Unapproved = nobody is watching it."),
    sw.new_watch(
        "mem.leadership_rotation", "memory-complex", "SNDK/MU relative strength — leadership rotation",
        subject_kind="theme",
        signal="Junk-led bounce vs quality rotation; durable bottoms rotate to quality in ~2 weeks.",
        why="Distinguishes a real bottom from a short-cover bounce — also tests P-4 (SNDK the "
            "weakest structural long).",
        cadence="weekly", source="BLOCKED — needs a price feed carrying MU/SNDK.",
        status="pending_approval", feeds=["MEMORY-SHORT-2027-RESEARCH"], added=DATE, last_review=DATE),
    sw.new_watch(
        "mem.hyperscaler_capex", "memory-complex", "Hyperscaler capex prints — the demand-side verdict",
        subject_kind="theme",
        signal="MSFT confirmed (Jul 30, Azure); META cracked (−8%, FCF −91%). AMZN and GOOGL "
               "next prints break the tie.",
        why="The demand leg of BOTH files — it validates the CEG counterparty class and sets the "
            "memory cycle's ceiling.",
        cadence="quarterly", source="Issuer results (public)",
        status="pending_approval",
        feeds=["MEMORY-SHORT-2027-RESEARCH", "CEG-ADD-2026Q3"], lands_as="earnings",
        added=DATE, last_review=DATE,
        note="Cheapest feed in §5 (public prints, no vendor) and it feeds BOTH theses — the "
             "obvious second approval after contract pricing."),
    sw.new_watch(
        "mem.guidance_language", "memory-complex", "Producer guidance language + capex discipline",
        subject_kind="theme",
        signal="Any change to Samsung's 'shortage through 2028' phrasing; any producer capex cut.",
        why="A capex cut is the cycle-discipline signal that defuses the R-4 fuse — the cleanest "
            "way the standing short thesis gets falsified.",
        cadence="quarterly", source="Issuer results + transcripts (public)",
        status="pending_approval", feeds=["MEMORY-SHORT-2027-RESEARCH"], lands_as="earnings",
        added=DATE, last_review=DATE),
    sw.new_watch(
        "mem.macro_cross_link", "memory-complex",
        "Bear-steepener / fiscal-dominance — AI-complex compression risk",
        subject_kind="theme",
        signal="The existing bear-steepener flag firing (rates monitor → regime lens → "
               "scenario weight B).",
        why="The shared risk across BOTH files: a fiscal-dominance repricing compresses the entire "
            "AI complex, CEG included — it does not care which name you picked.",
        cadence="weekly", source="rates_monitor → regime_lens / sentinel_board (ALREADY WIRED)",
        status="active", feeds=["MEMORY-SHORT-2027-RESEARCH", "CEG-ADD-2026Q3"],
        added=DATE, last_review=DATE,
        note="The handoff's 'already configured' row — verified against regime_lens.py "
             "(bear_steepener shares one flag with the P2.1 dashboard and scenario B). The only §5 "
             "feed needing no new source."),
]


# =============================================================================== §6 reference context
REFERENCE = [
    ("REF-CEG-ANALYSTS", "CEG",
     "CEG analyst matrix — a TWO-CLUSTER structure, and the dispute is about the PJM cap regime "
     "vs the PPA/PTC offset, NOT about the AI narrative.\n"
     "LOW: Citi/Levine $297 Neutral (Jul 1, pre-auction) · Bernstein/Ocalan $296 (Jun 17) · "
     "Goldman/Davenport $305 (Jun 18).\n"
     "MID: Mizuho/Crowdell $310 · Barclays/Campanella $324 (cut from $358, kept OW).\n"
     "HIGH: Wells Fargo/Pourreza $362 OW (cut from $384) · MS $364 · TD Cowen/Tucker $368 Buy "
     "(cut from $381) · UBS $380 Buy · Scotiabank/Weisel $441 (Apr 29).\n"
     "Consensus ~$352–372; ~80% buy ratings.\n"
     "PER-ANALYST ACCURACY IS UNVERIFIED — do NOT weight by reputation: accuracy leaderboards in "
     "a trending sector are momentum-contaminated (rule R-6, adjudicate by testable mechanism).",
     {"cluster_low": [296, 305], "cluster_high": [362, 441], "consensus": [352, 372],
      "buy_ratings_pct": 80, "reputation_weighting": "FORBIDDEN (R-6)"}),
    ("REF-PJM-BRA", "CEG",
     "PJM 2028/29 BRA actuals (Jul 14, 2026): cleared at the FERC cap $325/MW-day, −2.5% YoY; "
     "6,831 MW short of the reserve target (up from 6,500); only ~525 MW of new resources. CEG "
     "cleared 18,875 MW (15,700 nuclear + 3,175 fossil/other), up from 17,950 → ~$2.2B capacity "
     "revenue for 2028/29. The cap is a POLITICAL SETTLEMENT (Shapiro/FERC) — an uncapped auction "
     "would have cleared ~18% higher, and the data-center backstop procurement plan is advancing. "
     "Nuclear capacity revenues feed the PTC gross-receipts calc, so the PTC is an INVERSE-SUBSIDY "
     "FLOOR that dampens the downside from capped prices — this is the mechanism the low cluster "
     "does not credit and the whole valuation dispute turns on.",
     {"clearing_price_mw_day": 325, "yoy_pct": -2.5, "reserve_shortfall_mw": 6831,
      "ceg_cleared_mw": 18875, "ceg_capacity_rev_usd_b": 2.2}),
    ("REF-MEMORY-STATE", "MU",
     "Memory complex state (as of 2026-07-31). Correction: the group −20% to −50% from Jun 25 "
     "highs; SOX's worst month since 2008; MU peak ~$1,213 (Jun 25) → ~$775 (Jul 29) → ~$900+ "
     "(Jul 30, +18%). Jul 30 rally catalysts: Samsung record Q2 (op profit ₩89.5T, "
     "shortage-into-2028 guidance, multi-yr DC supply agreements), SK Hynix record Q2 (76% op "
     "margin), MSFT Azure, UBS SKHY initiation Buy $204.\n"
     "SITUATIONAL AWARENESS (Jul 30): $45B fund, 4x leverage, margin calls (GS/JPM/BofA), the "
     "entire public book sold to Citadel in a single block (Millennium underbid); kept the Anthropic "
     "private stake (un-callable). Longs: MU, SKHY, SNDK, Nebius, CoreWeave, Bloom; shorts: "
     "software (ADBE) squeezed. ON RECORD: liquidity provision ≠ conviction buying (R-3); "
     "forced-seller removal = a genuine capitulation candidate; Citadel now holds distributable "
     "inventory.\n"
     "MU fundamentals: FQ3 rev $41.46B (+346% YoY), EPS $25.11, Q4 guide $50B±1B / EPS $31; $22B "
     "take-or-pay commitments, 16 customers, pricing floors; fwd P/E ~6x on PEAK earnings "
     "(normalized more like 12–15x); next report Sep 22.\n"
     "HBM structure: SKHY 50–62% share (~70% of NVDA HBM4 allocation), Samsung recovering to "
     "~28%, MU ~18–21% (from ~5%). HBM4 is the FIRST generation with all three suppliers "
     "qualified (Jensen confirmation Jun 2026) → the moat converts from binary qualification to "
     "yield/price economics. CXMT: world #4 DRAM ~8% vs Samsung 36 / SKHY 29 / MU 24.",
     {"prices_verified": False, "mu_fwd_pe_on_peak": 6, "mu_normalized_pe": [12, 15],
      "hbm4_all_three_qualified": True}),
]


# =============================================================================== §7 durable rules
RULEBOOK = [
    ("R-1", "Instrument clock",
     "Match the instrument's decay/reset profile to the thesis horizon. Daily-reset leverage is "
     "days-horizon only. (See U-2026-07-31-C.)"),
    ("R-2", "Leverage bill",
     "All leverage costs the same bill at different windows — premium (options), decay (LETFs), "
     "forced exit (margin). Choose which one knowingly; never pretend the bill is absent."),
    ("R-3", "Block-trade interpretation",
     "A multistrat absorbing a forced seller's book at a discount is LIQUIDITY PROVISION, not "
     "directional conviction. Do not cite it as 'institutional buying'. 13F lag makes any real-time "
     "institutional-flow claim narrative until proven."),
    ("R-4", "Late-cycle tell",
     "Producer shortage-extending guidance + simultaneous record capex expansion = the cure for high "
     "prices is high prices, on an ~18-month fuse. Applies to memory now; generalizes to all "
     "commodities."),
    ("R-5", "The $400/$900 check",
     "Before ANY momentum-name entry, answer in writing: 'Why wasn't I interested at [pre-run "
     "price]?' No written answer = no entry. (The Druckenmiller March-2000 signature.)"),
    ("R-6", "Mechanism over reputation",
     "When analyst targets diverge, adjudicate by TESTABLE MECHANISM (did reality print?), not by "
     "track-record rankings — accuracy leaderboards in trending sectors are momentum-contaminated."),
    ("R-7", "Confirm-criteria pre-registration",
     "Any earnings-gated add program must have its CONFIRM/DISCONFIRM criteria written BEFORE the "
     "print. Interpretation after the fact is vibes with extra steps."),
    ("R-8", "EPS-noise exclusion",
     "For outage-driven generators (the CEG archetype), single-quarter EPS is excluded from the "
     "confirm criteria; guide integrity is the signal."),
]


# =============================================================================== §9 predictions
# Written as open, resolvable records so calibration can score them at horizon. They are NOT in the
# Brier-scored conviction trail: that trail scores ``conviction`` entries against a FROZEN decision
# with engine legs (ρ/ϕ/price), and none of these names is priced by the engine. Recorded as
# structured notes instead — honest about which loop they are in.
#: ``ticker`` is the entry's ticker key and must be a REAL single ticker or None — a multi-name
#: subject ("MU/SKHY") is carried in ``meta.subject``, never smuggled into the ticker namespace where
#: the data-integrity auditor would rightly flag it.
PREDICTIONS = [
    ("P-1", "MU/SKHY", None, "The Jul 29 forced-liquidation low holds on retest for MU and SKHY.",
     "moderate", "~6 weeks", "2026-09-11"),
    ("P-2", "memory-complex", None,
     "The memory market begins discounting the 2028 supply wave sometime in 2027; the short setup "
     "announces itself in contract-pricing data ≥2 quarters before price.",
     "moderate-high", "2027", "2027-12-31"),
    ("P-3", "CEG", "CEG", "The Aug 6 print reaffirms the FY26 guide.", "moderate-high", "Aug 6",
     "2026-08-06"),
    ("P-4", "SNDK", "SNDK", "SNDK is the weakest structural long in the complex over 12 months.",
     "moderate-high", "Jul 2027", "2027-07-31"),
]


# =============================================================================== §8 open items
OPEN_ITEMS = [
    ("OI-1", "Total intended CEGS add size (CAD $ or % of book).", "BLOCKING tranche 1"),
    ("OI-2", "Post-add CEGS ceiling (% of book) — a hard cap, WRITTEN BEFORE ORDER 1. "
             "Tracked as thesis claim c7, deliberately held 'unknown'.", "BLOCKING tranche 1"),
    ("OI-3", "Tranche 1 fraction (default 25–33% of OI-1).", "BLOCKING tranche 1"),
    ("OI-4", "Confirm the PJM homework slot on the calendar (target: Aug 1–2 weekend).", "Y/N"),
    ("OI-5", "Approve the §5 memory SENTINEL feeds — per feed. All 8 are registered at "
             "pending_approval in sentinel_watch except mem.macro_cross_link (already wired). "
             "Recommended order if the API-only budget is tight: "
             "(1) mem.dram_nand_contract_pricing — the actual thesis clock; "
             "(2) mem.hyperscaler_capex — public prints, no vendor, feeds BOTH theses; "
             "(3) mem.sa_liquidation_low_retest — the only one with a live clock (P-1 resolves "
             "~2026-09-11).", "Y/N per feed"),
    ("OI-6", "Verify the (~) price levels. NOT DONE and not doable in this pass: the engine was "
             "offline and the price layer does not carry CEG/CEGS.TO/MU/SKHY — the FMP quote and "
             "chart endpoints are gated on the current plan. Every level is stored "
             "verified:false inside the thesis bodies and NONE was written to an engine-owned "
             "field. Needs a source decision (JM spot-check, or wire a feed).", "BLOCKED"),
    ("OI-7", "MODELLING CALL made by this ingestion, flagged for review: the memory file is stored "
             "as a thesis with stance REJECT under ticker MU (the Ledger graveyard is the right "
             "home for a name you passed on), with the standing 2027 short thesis in the body and "
             "position=NONE. If you would rather it not sit under MU's ticker, say so and it "
             "supersedes cleanly.", "REVIEW"),
]


# =============================================================================== the ingestion
def _existing_record_ids(mem: LivingMemory) -> set:
    """Every ``record_id`` this handoff has already written (idempotency key)."""
    out = set()
    for e in mem.all():
        meta = e.get("meta") or {}
        if meta.get("handoff") == HANDOFF and meta.get("record_id"):
            out.add(meta["record_id"])
    return out


def _write(mem: LivingMemory, done: set, plan: list, record_id: str, *, dry: bool, **kw) -> bool:
    """Write one memory entry unless its ``record_id`` is already in the store."""
    if record_id in done:
        plan.append(f"  skip  {record_id} (already ingested)")
        return False
    plan.append(f"  WRITE {record_id} — {kw.get('type')} {kw.get('ticker') or '(book)'}")
    if not dry:
        meta = dict(kw.pop("meta", {}) or {})
        meta.update({"handoff": HANDOFF, "record_id": record_id})
        mem.write(meta=meta, source=SOURCE, provenance=PROV, ts=f"{DATE}T00:00:00Z", **kw)
        done.add(record_id)
    return True


def ingest(*, memory_path: str = "", calendar_path: str = "", watch_path: str = "",
           dry_run: bool = False) -> dict:
    """Ingest the whole handoff. Idempotent; returns a report of what was written vs skipped."""
    mem = LivingMemory(memory_path or None)
    cal = CatalystCalendar(calendar_path or "data/catalyst_calendar.jsonl")
    wpath = watch_path or sw.DEFAULT_PATH
    done = _existing_record_ids(mem)
    plan: list = []
    written = {"memory": 0, "calendar": 0, "watches": 0}

    # --- §2 Ulysses ------------------------------------------------------------------------------
    plan.append("§2 ULYSSES LEDGER (verbatim pre-commitments)")
    for rid, label, ticker, text in ULYSSES:
        if _write(mem, done, plan, rid, dry=dry_run, type="note", ticker=ticker,
                  text=f"ULYSSES {rid} — {label}: {text}",
                  tags=["ulysses", "pre-commitment", "handoff"],
                  meta={"kind": "ulysses", "label": label, "verbatim": text}):
            written["memory"] += 1

    # --- §3/§5 theses ----------------------------------------------------------------------------
    plan.append("§3/§5 THESIS LEDGER")
    for rid, body in (("CEG-ADD-2026Q3", CEG_THESIS),
                      ("MEMORY-SHORT-2027-RESEARCH", MEM_THESIS)):
        ok, errors = tl.validate_thesis(body)
        if not ok:                                            # never write an invalid thesis
            raise ValueError(f"{rid} failed validation: {'; '.join(errors)}")
        if _write(mem, done, plan, rid, dry=dry_run, type="thesis", ticker=body["ticker"],
                  text=tl.thesis_summary_line(body),
                  tags=["thesis", body["stance"].lower(), "handoff", rid.lower()],
                  meta=dict(body)):
            written["memory"] += 1

    # --- §6 reference context --------------------------------------------------------------------
    plan.append("§6 REFERENCE CONTEXT (for COUNCIL)")
    for rid, ticker, text, facts in REFERENCE:
        if _write(mem, done, plan, rid, dry=dry_run, type="note", ticker=ticker, text=text,
                  tags=["council-context", "reference", "handoff"],
                  meta={"kind": "reference", "facts": facts, "as_of": DATE}):
            written["memory"] += 1

    # --- §7 rulebook ------------------------------------------------------------------------------
    plan.append("§7 DURABLE RULES (COUNCIL/CALIBRATION rulebook)")
    for rid, label, text in RULEBOOK:
        if _write(mem, done, plan, rid, dry=dry_run, type="note", ticker=None,
                  text=f"RULE {rid} {label} — {text}",
                  tags=["rulebook", "council", "calibration", "handoff"],
                  meta={"kind": "rule", "rule_id": rid, "label": label, "established": DATE}):
            written["memory"] += 1

    # --- §9 predictions ---------------------------------------------------------------------------
    plan.append("§9 CALIBRATION LOG (open predictions)")
    for rid, subject, ticker, text, conf, horizon, resolve_by in PREDICTIONS:
        if _write(mem, done, plan, rid, dry=dry_run, type="note", ticker=ticker,
                  text=f"PREDICTION {rid} ({conf}, horizon {horizon}, resolve by {resolve_by}) "
                       f"— {text}",
                  tags=["prediction", "calibration", "handoff", "open"],
                  meta={"kind": "prediction", "prediction_id": rid, "subject": subject,
                        "confidence": conf, "horizon": horizon, "resolve_by": resolve_by,
                        "status": "open", "made": DATE,
                        "scoring_note": "Not in the Brier-scored conviction trail — that requires "
                                        "a frozen engine decision (ρ/ϕ/price legs) and none of "
                                        "these names is priced by the engine. Score manually at "
                                        "horizon and supersede this entry with the result."}):
            written["memory"] += 1

    # --- §8 open items -----------------------------------------------------------------------------
    plan.append("§8 OPEN ITEMS (JM input required before Wed Aug 5 close)")
    for rid, text, urgency in OPEN_ITEMS:
        if _write(mem, done, plan, rid, dry=dry_run, type="note", ticker=None,
                  text=f"OPEN ITEM {rid} [{urgency}] — {text}",
                  tags=["open-item", "handoff", "jm-input"],
                  meta={"kind": "open_item", "item_id": rid, "urgency": urgency,
                        "due": "2026-08-05", "status": "open"}):
            written["memory"] += 1

    # --- §4/§5 calendar ----------------------------------------------------------------------------
    plan.append("§4/§5 CATALYST CALENDAR (dated triggers only)")
    existing = {(e.get("ticker"), e.get("kind"), e.get("title")) for e in cal.all()}
    for ticker, kind, title, start, end, conf, notes in CALENDAR:
        if (ticker, kind, title) in existing:
            plan.append(f"  skip  {ticker} {kind} — {title[:48]} (already present)")
            continue
        plan.append(f"  WRITE {ticker} {kind} {start} — {title[:48]}")
        if not dry_run:
            cal.write(kind=kind, title=title, ticker=ticker, window_start=start, window_end=end,
                      confidence=conf, source=SOURCE, notes=notes, status="pending")
        written["calendar"] += 1

    # --- §4/§5 watch registry -----------------------------------------------------------------------
    plan.append("§4/§5 SENTINEL WATCH REGISTRY (undated / ongoing triggers)")
    items = sw.load(wpath)
    have = {i.get("id") for i in items}
    for w in WATCHES:
        if w["id"] in have:
            plan.append(f"  skip  {w['id']} (already registered)")
            continue
        plan.append(f"  WRITE {w['id']} [{w['status']}] — {w['label'][:44]}")
        items, _ = sw.upsert(items, w)
        written["watches"] += 1
    ok, errors = sw.validate_registry(items)
    if not ok:
        raise ValueError("watch registry invalid: " + "; ".join(errors))
    if not dry_run and written["watches"]:
        sw.save(items, wpath,
                doc="SENTINEL watch registry — undated/ongoing tripwires with no calendar window "
                    "and no engine metric. pending_approval items are NOT being watched; see "
                    "sentinel_watch.board()['coverage']. Seeded from the 2026-07-31 handoff.")

    board = sw.board(items)
    return {"written": written, "plan": plan, "watch_board": board,
            "watch_summary": sw.summary_line(board), "dry_run": dry_run}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--memory-path", default="", help="override the Living Memory path")
    ap.add_argument("--calendar-path", default="", help="override the catalyst calendar path")
    ap.add_argument("--watch-path", default="", help="override the sentinel watch registry path")
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    rep = ingest(memory_path=args.memory_path, calendar_path=args.calendar_path,
                 watch_path=args.watch_path, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({k: v for k, v in rep.items() if k != "watch_board"}, indent=2))
        return 0
    for line in rep["plan"]:
        print(line)
    w = rep["written"]
    print(f"\n{'DRY RUN — nothing written' if rep['dry_run'] else 'ingested'}: "
          f"{w['memory']} memory entr(ies), {w['calendar']} calendar window(s), "
          f"{w['watches']} watch item(s)")
    print(rep["watch_summary"])
    cov = rep["watch_board"]["coverage"]
    if cov["pending"]:
        print(f"\n⚠ {len(cov['pending'])} watch item(s) PENDING JM APPROVAL — nothing is "
              f"watching these today:")
        for p in cov["pending"]:
            print(f"    · {p['id']}: {p['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
