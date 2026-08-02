#!/usr/bin/env python3
"""
Resolve open item §8.6 of the 2026-07-31 handoff — verify the ``~`` price levels.

The first ingestion pass recorded every ``~`` level as ``verified: false`` because the engine was
offline and the FMP ``quote``/``chart`` endpoints are gated on the current plan. That was an
incomplete read of the situation: ``fmp_client.py`` documents ``profile`` as one of the endpoints
that DOES survive the free tier, and it carries price + 52-week range. Google Finance corroborates
it independently, and dated daily closes are available from stockanalysis.com. So the levels are
verifiable after all, and two of them turned out to be materially wrong.

Corrections applied (both move a number the desk would act on):

  * **CEG spot** — the handoff's ``~$248–252`` is stale. The Jul 30 close was **$263.56** (Jul 29:
    $257.95). The program's entry level is ~5% above what tranche 1 was sized against. It does NOT
    touch the $340–360 underwriting basis, but it does move the fill and the §8.1/§8.3 sizing.
  * **MU Jul 29 low** — the handoff's ``~$775`` was the area, not the print. The close was
    **$739.00**. This is the level claim c6 / prediction P-1 are measured against, so the tripwire
    sits ~4.6% lower than recorded.

Confirmed exactly, for the record: CEG's 52-wk low $228.63, MU's $1,213.56 peak close (Jun 25), and
SKHY's $126.79 Jul 29 close.

Also corrects an INSTRUMENT identifier error: the handoff calls the vehicle ``CEGS.TO``. CEGS is a
CIBC Canadian Depositary Receipt listed on **Cboe Canada**, not the TSX — the ``.TO`` suffix is
wrong, and neither FMP nor Google Finance returns a quote under it (or under ``:NEO``). Per the
operator, **CEG is the pricing reference** for the CDR; the CDR itself has no data-vendor coverage
here, which is a standing limitation on marking the actual holding.

Corrections SUPERSEDE (never overwrite) — the original entries stay in the record, because what the
desk believed on the morning of the 31st is part of the track record.

    python scripts/bootstrap/verify_handoff_levels_2026_07_31.py [--dry-run]
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

import argparse

import sentinel_watch as sw
import thesis_ledger as tl
from living_memory import LivingMemory

HANDOFF = "2026-07-31-ceg-memory"
VERIFIED_AT = "2026-07-31"
SOURCE = "handoff-2026-07-31-verify"

#: Where each figure came from. Two independent sources agree on the last close for every name, so
#: these are recorded as ``sourced`` rather than as the operator's read.
SOURCES = {
    "last_close": "FMP profile endpoint (free tier — the same one fmp_client.py uses) AND "
                  "Google Finance quote pages; the two agree to the cent on every name.",
    "dated_closes": "stockanalysis.com daily history (Google Finance quote pages carry no "
                    "historical table).",
    "as_of": "Last completed session = 2026-07-30. Quoted pre-market figures are 2026-07-31.",
}

CEG_LEVELS = {
    "_note": "VERIFIED 2026-07-31 against two independent sources. Prices in USD on CEG (NASDAQ) — "
             "the underwriting subject. The CDR (CEGS, Cboe Canada) has no vendor coverage; CEG is "
             "the pricing reference for it, per the operator.",
    "verified": True, "verified_at": VERIFIED_AT, "sources": SOURCES,
    "low_52w_usd": 228.63, "low_52w_date": "2026-07-01",
    "low_52w_note": "$228.63 is the INTRADAY 52-wk low; CEG closed that day at $236.50.",
    "high_52w_usd": 412.70,
    "close_2026_07_29_usd": 257.95,
    "close_2026_07_30_usd": 263.56,
    "premarket_2026_07_31_usd": 268.99,
    "consensus_target_usd": [352, 372],
    "corrections": {
        "spot": "handoff said ~$248–252 — STALE. Actual Jul 30 close $263.56 (Jul 29: $257.95), "
                "so the entry level is ~5% above what tranche 1 was sized against. The $340–360 "
                "underwriting basis is unaffected; §8.1/§8.3 sizing is not.",
    },
    "confirmed": ["low_52w_usd $228.63 — exact"],
}

MEM_LEVELS = {
    "_note": "VERIFIED 2026-07-31 against two independent sources (USD).",
    "verified": True, "verified_at": VERIFIED_AT, "sources": SOURCES,
    "MU": {"peak_close_usd": 1213.56, "peak_date": "2026-06-25",
           "close_2026_07_29_usd": 739.00, "close_2026_07_30_usd": 874.66,
           "premarket_2026_07_31_usd": 912.36,
           "range_52w_usd": [103.38, 1255.00], "beta": 2.142,
           "drawdown_peak_to_low_pct": -39.1},
    "SKHY": {"close_2026_07_29_usd": 126.79, "close_2026_07_30_usd": 149.00,
             "premarket_2026_07_31_usd": 158.53,
             "range_52w_usd": [124.80, 194.80], "beta": 2.322,
             "listing_note": "ADR IPO'd 2026-07-10; daily history begins 2026-07-13 ($152.35). "
                             "Roughly three weeks of listed price history — a thin base for any "
                             "level-retest read."},
    "SNDK": {"last_close_usd": 1279.96, "range_52w_usd": [40.10, 2354.39], "beta": 4.741962,
             "note": "Beta 4.74 vs MU 2.14 and SKHY 2.32 — independent support for P-4 (SNDK the "
                     "weakest structural long in the complex)."},
    "corrections": {
        "mu_jul29_low": "handoff said ~$775 — the close was $739.00 (~4.6% lower). This is the "
                        "level claim c6 and prediction P-1 are measured against, so the tripwire "
                        "sits lower than recorded. $775 may have been an intraday area; the CLOSE "
                        "is the verified figure.",
    },
    "confirmed": ["MU peak close $1,213.56 on 2026-06-25 — exact",
                  "SKHY 2026-07-29 close $126.79 — exact",
                  "complex drawdown −39.1% peak-to-low, inside the handoff's −20%/−50% range"],
}


def _superseded_already(mem: LivingMemory, record_id: str) -> bool:
    for e in mem.all():
        if (e.get("meta") or {}).get("record_id") == record_id:
            return True
    return False


def verify(*, memory_path: str = "", watch_path: str = "", dry_run: bool = False) -> dict:
    mem = LivingMemory(memory_path or None)
    wpath = watch_path or sw.DEFAULT_PATH
    plan, done = [], {"theses": 0, "notes": 0, "watches": 0}

    if _superseded_already(mem, "VERIFY-8.6"):
        plan.append("skip — §8.6 verification already recorded")
        return {"plan": plan, "written": done, "dry_run": dry_run}

    # --- supersede both theses with verified levels + the instrument correction -------------------
    for ticker, levels in (("CEG", CEG_LEVELS), ("MU", MEM_LEVELS)):
        entry = mem.latest_thesis(ticker)
        if not entry:
            plan.append(f"skip — no thesis found for {ticker}")
            continue
        body = dict(entry.get("meta") or {})
        body["reference_levels"] = levels
        if ticker == "CEG":
            body["instrument"] = "CEGS (CIBC CDR, Cboe Canada)"
            body["instrument_note"] = (
                "CORRECTED 2026-07-31: the handoff's 'CEGS.TO' suffix is wrong — CEGS is a CIBC "
                "Canadian Depositary Receipt listed on Cboe Canada, not the TSX. Neither FMP nor "
                "Google Finance returns a quote under CEGS.TO or CEGS:NEO, so the CDR has no "
                "data-vendor coverage available to this desk. Per the operator, CEG (NASDAQ) is "
                "the PRICING REFERENCE for the CDR; the CAD-hedged CDR is still how the position "
                "is expressed at the brokerage (hedge cost ~0.5–0.6% annualized embedded). "
                "Practical consequence: the actual holding cannot be marked automatically — only "
                "its reference can.")
        ok, errors = tl.validate_thesis(body)
        if not ok:
            raise ValueError(f"{ticker} correction failed validation: {'; '.join(errors)}")
        plan.append(f"SUPERSEDE thesis {ticker} ({entry['id']}) — verified levels"
                    + (" + instrument correction" if ticker == "CEG" else ""))
        if not dry_run:
            mem.supersede(entry["id"], "thesis", text=tl.thesis_summary_line(body), ticker=ticker,
                          tags=["thesis", body["stance"].lower(), "handoff", "verified"],
                          meta={**body, "handoff": HANDOFF,
                                "record_id": f"{body.get('program_id')}#verified"},
                          source=SOURCE, provenance="sourced")
        done["theses"] += 1

    # --- resolve OI-6 ------------------------------------------------------------------------------
    oi6 = [e for e in mem.query(tag="open-item", limit=0)
           if (e.get("meta") or {}).get("item_id") == "OI-6"]
    if oi6:
        plan.append(f"SUPERSEDE OI-6 ({oi6[0]['id']}) — resolved")
        if not dry_run:
            mem.supersede(
                oi6[0]["id"], "note", ticker=None,
                text="OPEN ITEM OI-6 [RESOLVED 2026-07-31] — the (~) price levels ARE verifiable: "
                     "the FMP 'profile' endpoint works on the current plan (it is the one "
                     "fmp_client.py itself uses) and Google Finance corroborates it; dated closes "
                     "came from stockanalysis.com. TWO LEVELS WERE MATERIALLY WRONG — CEG spot was "
                     "~$248–252 vs an actual $263.56 Jul 30 close (~5% low, moves the tranche-1 "
                     "fill and §8.1/§8.3 sizing), and the MU Jul 29 low was ~$775 vs an actual "
                     "$739.00 close (~4.6% high, and it is the level c6/P-1 are measured against). "
                     "CEG's $228.63 52-wk low, MU's $1,213.56 peak close and SKHY's $126.79 close "
                     "were exact. Levels are now stamped verified:true in both thesis bodies. "
                     "REMAINING GAP: the CDR itself (CEGS, Cboe Canada) has no vendor coverage, so "
                     "the actual holding cannot be marked — only CEG, its reference.",
                tags=["open-item", "handoff", "resolved"],
                meta={"kind": "open_item", "item_id": "OI-6", "status": "resolved",
                      "urgency": "RESOLVED", "handoff": HANDOFF, "record_id": "VERIFY-8.6",
                      "resolved_at": VERIFIED_AT},
                source=SOURCE, provenance="sourced")
        done["notes"] += 1

    # --- the verification note (the standing record of what disagreed) ----------------------------
    plan.append("WRITE verification note (VERIFY-LEVELS)")
    if not dry_run:
        mem.write("note", ticker=None,
                  text="LEVEL VERIFICATION 2026-07-31 — handoff (~) levels checked against two "
                       "independent sources. CONFIRMED EXACT: CEG 52-wk low $228.63 (intraday "
                       "Jul 1; close that day $236.50) · MU peak close $1,213.56 (Jun 25) · SKHY "
                       "Jul 29 close $126.79. CORRECTED: CEG spot ~$248–252 → $263.56 (Jul 30 "
                       "close; Jul 29 $257.95) · MU Jul 29 ~$775 → $739.00 close. CONTEXT: MU "
                       "drawdown −39.1% peak-to-low, inside the −20%/−50% band. SKHY has only ~3 "
                       "weeks of listed history (ADR IPO 2026-07-10, first close in the table "
                       "2026-07-13) — a thin base for a level-retest read. SNDK beta 4.74 vs MU "
                       "2.14 / SKHY 2.32, which independently supports P-4. Jul 31 pre-market had "
                       "the complex extending the bounce (CEG $268.99 · MU $912.36 · SKHY "
                       "$158.53).",
                  tags=["verification", "handoff", "council-context"],
                  meta={"kind": "verification", "handoff": HANDOFF, "record_id": "VERIFY-LEVELS",
                        "sources": SOURCES, "ceg": CEG_LEVELS, "memory_complex": MEM_LEVELS},
                  source=SOURCE, provenance="sourced")
    done["notes"] += 1

    # --- re-point the watch items ------------------------------------------------------------------
    items = sw.load(wpath)
    for i, it in enumerate(items):
        if it.get("id") == "ceg.reference_levels":
            plan.append("UPDATE watch ceg.reference_levels — pending_approval -> active")
            items[i] = {**it, "status": "active", "last_review": VERIFIED_AT,
                        "source": "FMP 'profile' endpoint (free tier, the one fmp_client.py uses) "
                                  "+ Google Finance quote pages; dated closes from "
                                  "stockanalysis.com.",
                        "signal": "CEG last close + 52-wk range. NOTE: the CDR (CEGS, Cboe Canada) "
                                  "has no vendor coverage — CEG is the pricing reference.",
                        "note": "§8.6 RESOLVED 2026-07-31. Kept active to re-check the entry level "
                                "before each tranche."}
            done["watches"] += 1
        elif it.get("id") == "mem.sa_liquidation_low_retest":
            plan.append("UPDATE watch mem.sa_liquidation_low_retest — exact levels pinned")
            items[i] = {**it, "last_review": VERIFIED_AT,
                        "signal": "VERIFIED levels: MU 2026-07-29 close $739.00 (NOT the ~$775 in "
                                  "the handoff) and SKHY 2026-07-29 close $126.79. A breach kills "
                                  "the capitulation-low read; holding on lower volume confirms it.",
                        "note": "Still PENDING APPROVAL — the levels are now exact but nothing is "
                                "watching them. P-1 resolves ~2026-09-11. SKHY has ~3 weeks of "
                                "listed history, so its level is a weak base."}
            done["watches"] += 1
    ok, errors = sw.validate_registry(items)
    if not ok:
        raise ValueError("watch registry invalid: " + "; ".join(errors))
    if not dry_run and done["watches"]:
        sw.save(items, wpath)

    return {"plan": plan, "written": done, "dry_run": dry_run}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--memory-path", default="")
    ap.add_argument("--watch-path", default="")
    args = ap.parse_args(argv)
    rep = verify(memory_path=args.memory_path, watch_path=args.watch_path, dry_run=args.dry_run)
    for line in rep["plan"]:
        print(" ", line)
    w = rep["written"]
    print(f"\n{'DRY RUN — nothing written' if rep['dry_run'] else 'recorded'}: "
          f"{w['theses']} thesis correction(s), {w['notes']} note(s), {w['watches']} watch update(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
