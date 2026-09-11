#!/usr/bin/env python3
"""
Ingest the 2026-09-11 session handoff — AGA spear death, AG/BRC/SVE rebuild,
TLT sleeve, CEG hold.

The handoff (docs/HANDOFF_2026-09-11_AGA_SPEAR_TLT.md) is a set of MANUAL INPUTS
from the operator/Grok tape. This script puts each in Living Memory so Council,
Sentinel, /replace, and /journal inherit it.

IDEMPOTENT. Every record carries meta.handoff + meta.record_id; a re-run skips
anything already present.

    python scripts/bootstrap/ingest_handoff_2026_09_11.py
    python scripts/bootstrap/ingest_handoff_2026_09_11.py --dry-run

Does NOT mutate v5_config barbell weights, units, or NAV.
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import argparse

from living_memory import LivingMemory

HANDOFF = "2026-09-11-aga-spear-tlt"
DATE = "2026-09-11"
SOURCE = "handoff-2026-09-11"
PROV = "user"
DOC = "docs/HANDOFF_2026-09-11_AGA_SPEAR_TLT.md"


def _already(mem: LivingMemory, record_id: str) -> bool:
    for e in mem.all():
        meta = e.get("meta") or {}
        if meta.get("handoff") == HANDOFF and meta.get("record_id") == record_id:
            return True
    return False


def _write(mem, dry, *, record_id, type, text, ticker=None, tags=None, extra_meta=None):
    if _already(mem, record_id):
        return "skip"
    meta = {"handoff": HANDOFF, "record_id": record_id, "source_doc": DOC}
    if extra_meta:
        meta.update(extra_meta)
    if dry:
        return f"dry:{type}:{record_id}"
    mem.write(
        type,
        text=text,
        ticker=ticker,
        tags=list(tags or []) + ["handoff-2026-09-11"],
        source=SOURCE,
        provenance=PROV,
        meta=meta,
        refs=[DOC],
        ts="2026-09-11T17:00:00Z",
    )
    return "write"


ULYSSES = [
    ("U-2026-09-11-A", "AGA.V",
     "Deal = thesis over. When a junior announces a merger, the thesis is over unless you explicitly want the buyer. AGA → Bunker Hill is that case. Do not sit to November hoping assays or close make you whole."),
    ("U-2026-09-11-B", "AGA.V",
     "Sell the dead name now, buy the replacement later. Exits from stocks you do not want do not wait for FOMC. Entries into AG/BRC/SVE do."),
    ("U-2026-09-11-C", "TLT",
     "No lottery expiry through a known Fed meeting unless that was the bet. Sep-18 TLT calls are done. Sep-30 puts may ride small."),
    ("U-2026-09-11-D", "AGA.V",
     "Do not press a wounded thesis. AGA is not a jugular setup. Size follows a live thesis. Rebuilding silver after the meeting is a new trade."),
    ("U-2026-09-11-E", "CEG",
     "CEG dips are not silver substitutes. Duration mark-to-market on PPAs is not a reason to sell the scarce baseload asset into a rates scare. Add CEG only if the dump is yields and power is still firm."),
    ("U-2026-09-11-F", "TLT",
     "Bond-book leftover, not a new campaign. Harvest/trail the put sleeve. Do not reload Sep-18-style calls, do not turn put P&L into a bigger duration book that eats the silver cash."),
]

THESES = [
    ("TH-AGA-V-CLOSED", "AGA.V", "REJECT",
     "AGA.V silver-spear CLOSED. Bunker Hill combination converts the high-beta U.S. silver explorer into a ratio claim on a restart-plus-exploration vehicle (Zn/Pb/mill-ramp). Pending Red Mountain / Belmont work re-rates the combo, not standalone AGA. Stance REJECT as spear. Stub only if running 0.1724 BNKR/AGA arb and selling BNKR day one."),
    ("TH-AG-REBUILD", "AG", "CONDITIONAL",
     "AG (First Majestic) is the planned post-FOMC producer-torque core of the silver rebuild (~50–60% of the new spear sleeve). Highest Ag revenue share among names that can be traded in size. CONDITIONAL on a post-decision dip and slot decision OI-7 (producer-as-spear-core vs new silver-operator-torque slot). Not yet held via this handoff."),
    ("TH-BRC-V-REBUILD", "BRC.V", "CONDITIONAL",
     "BRC.V (Blackrock Silver, Tonopah West PEA) is the planned junior spear to replace AGA-like convexity. Closest U.S. silver-developer DNA still on a path. CONDITIONAL on /gauntlet before any promote. Size 25–35% of the rebuild sleeve, never like AG. Not yet held."),
    ("TH-SVE-V-REBUILD", "SVE.V", "CONDITIONAL",
     "SVE.V (Silver One, Candelaria NV) is the lottery satellite (10–15%). Earlier, thinner, raise/dead-hole risk. CONDITIONAL on /gauntlet. Not the core. Not yet held."),
]

FORECASTS = [
    ("P-1", None, "2026-09-18",
     "FOMC delivers the priced hike; the 10-year does not stage a lasting rally solely because the hike happened.", 0.60),
    ("P-2", "AG", "2026-09-19",
     "High-beta silver (BRC/SVE/AG) is messier than bullion into and immediately after the decision.", 0.65),
    ("P-3", "AGA.V", "2026-11-30",
     "AGA residual is a ratio claim; pending RM/Belmont news does not restore standalone explorer beta.", 0.80),
    ("P-4", "CEG", "2026-12-31",
     "The Rhode Island State Energy Center bolt-on is not a 2026 CEG thesis change.", 0.75),
]

OPEN_ITEMS = [
    ("OI-1", "AGA.V", "Confirm AGA exit fill (date, units, WS proceeds) and run remove_holding / record_decision."),
    ("OI-2", "AG", "Post-FOMC entry prices actually paid for AG / BRC.V / SVE.V — or none filled."),
    ("OI-3", "TLT", "TLT Sep-30 put: peel / hold / stop after the decision."),
    ("OI-4", "BRC.V", "/gauntlet BRC.V and /gauntlet SVE.V before any promote."),
    ("OI-5", "AGA.V", "Slot language in CLAUDE.md: vacant spear vs AGA still listed as incumbent until OI-1."),
    ("OI-6", None, "Verify session reference levels against engine / issuer / SEDAR+. Do not promote ~ prices."),
    ("OI-7", "AG", "Decide whether silver-spear may include a producer (AG) as core with junior satellites, or AG lives in a new silver-operator-torque slot."),
]

RULES = [
    ("R-9",
     "R-9 — Deal = thesis over. When a junior announces a combination, the held object is the buyer unless you explicitly underwrite the buyer. Holding through close to 'get back to even' is a second bet. (AGA.V / Bunker Hill, 2026-09-11.)"),
    ("R-10",
     "R-10 — Known-event lottery expiry. Do not carry short-dated lottery options through a scheduled macro event unless that expiry *was* the bet. Close or flatten the lottery; the longer expression may ride small. (TLT Sep-18 calls vs Sep-30 puts into FOMC week.)"),
]


def ingest(dry: bool = False) -> dict:
    mem = LivingMemory()
    log = []

    log.append(_write(
        mem, dry, record_id="SIT-2026-09-11", type="regime_snapshot", ticker=None,
        tags=["regime"],
        extra_meta={"event": "CPI-digest-into-FOMC", "cash_pct_session": 50},
        text=("2026-09-11 posture: hike near-certain on prediction markets while the long end "
              "kept selling. CPI hot-then-fade. Operator ~50% cash. Do not force gold/silver "
              "equities into the meeting. Duration overlay is term-premium + oil, not the next 25 bp."),
    ))

    log.append(_write(
        mem, dry, record_id="NOTE-CEG-HOLD", type="note", ticker="CEG",
        tags=["council-context"],
        text=("CEG: hold core through the rates scare. RI State Energy Center bolt-on is negligible "
              "vs cap. Add only on a yields-driven dump while power and data-center demand hold. "
              "A demand-roll-over-with-yields dump is a different tape — wait."),
    ))

    log.append(_write(
        mem, dry, record_id="NOTE-TLT-SLEEVE", type="note", ticker="TLT",
        tags=["tlt-sleeve"],
        text=("TLT sleeve: Sep-18 calls closed flat. Sep-30 puts working (~+20% session). "
              "Do not add on breakdown. Optional 10–15% peel only to lock silver cash. "
              "One add, same-or-smaller, only on a $81.30–82.50 squeeze that is short-covering. "
              "If the gain is gone before the decision, flat — no revenge reload."),
    ))

    for rid, ticker, text in ULYSSES:
        log.append(_write(mem, dry, record_id=rid, type="note", ticker=ticker,
                         tags=["ulysses"], text=text))

    for rid, ticker, stance, text in THESES:
        log.append(_write(
            mem, dry, record_id=rid, type="thesis", ticker=ticker,
            tags=["thesis", stance.lower()],
            extra_meta={"stance": stance, "program_id": "SILVER-SPEAR-REBUILD-2026Q3"},
            text=text,
        ))

    for rid, ticker, resolve_by, text, conf in FORECASTS:
        log.append(_write(
            mem, dry, record_id=rid, type="forecast", ticker=ticker,
            tags=["prediction"],
            extra_meta={"resolve_by": resolve_by, "p_hat": conf, "status": "open"},
            text=text,
        ))

    for rid, ticker, text in OPEN_ITEMS:
        log.append(_write(mem, dry, record_id=rid, type="note", ticker=ticker,
                         tags=["open-item"], text=text))

    for rid, text in RULES:
        log.append(_write(mem, dry, record_id=rid, type="note", ticker=None,
                         tags=["rulebook"], text=text))

    log.append(_write(
        mem, dry, record_id="THREAD-20260911", type="thread", ticker="AGA.V",
        tags=["imported"],
        extra_meta={"source_file": "data/decisions/handoff_AGA_spear_rebuild_20260911.md",
                    "kind": "research_thread"},
        text="AGA spear death / AG-BRC-SVE rebuild / TLT sleeve / CEG hold",
    ))

    return {"log": log, "writes": log.count("write"), "skips": sum(1 for x in log if x == "skip")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    res = ingest(dry=args.dry_run)
    print(f"handoff {HANDOFF}: writes={res['writes']} skips={res['skips']}")
    if args.dry_run:
        for row in res["log"]:
            print(" ", row)


if __name__ == "__main__":
    main()
