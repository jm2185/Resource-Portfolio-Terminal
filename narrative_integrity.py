"""
narrative_integrity.py — does a management TURNAROUND narrative have receipts, or is it hand-waving?
(Phase 5 of docs/DUAL_SIDED_TIV_BUILD_SPEC.md — the NIS check.)

JSF (forensic_gates) grades ACCOUNTING integrity; the catalyst-verifier grades RESOURCE catalysts;
neither can grade an OPERATING turnaround. The Euronet lesson: the naive "melting ATM value trap"
thesis was largely STALE — management had measurably repositioned (ATM share of EFT ~90%→~60%, the
segment renamed "payments infrastructure", REN/CoreCard winning recurring-revenue deals, EU cash-
access regulation turning ATMs into mandated outsourcing) — and the live risk had RELOCATED from ATMs
to Ria remittance under US immigration policy. A resource-catalyst check sees none of that.

So NIS grades a turnaround claim-by-claim against its RECEIPT (a segment-disclosure trend in the
10-K/10-Q, a contract announcement straight-to-source, a regulatory citation): a claim with a trend-
confirming receipt scores high; hand-waving scores zero; a receipt that has REVERSED (the trend turned
down) is a `narrative_break` — the value-trap confirmation the deep-value lens fears. It also LOCATES
where the live risk now sits. Context-aware by profile (the right receipt system for an operating
turnaround ≠ a drill leak ≠ a royalty NSR), the ``divergence_monitor.explain_context`` pattern.

Pure + dependency-free; feeds the Q pillar (a turnaround with receipts lifts Q, hand-waving caps it)
and a SENTINEL; never raises; thresholds tunable via /confirm (``narrative_integrity.*``); no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_NIS_CONFIG", "NIS_GLOSSARY", "nis_tooltip", "nis_facets", "grade",
           "nis_to_q", "select_fresh"]

DEFAULT_NIS_CONFIG: dict[str, Any] = {
    "confirmed_score": 1.0,    # receipt present AND trend improving/holding
    "partial_score": 0.5,      # receipt present, trend unclear
    "unsupported_score": 0.0,  # NO receipt — hand-waving
    "broken_score": 0.0,       # receipt present but trend has REVERSED (deteriorating)
}

NIS_GLOSSARY: dict[str, dict[str, str]] = {
    "narrative_integrity": {
        "what": "Whether a management turnaround narrative has RECEIPTS (a segment-disclosure trend, a contract, a regulatory citation) vs. hand-waving — graded claim-by-claim into a 0–1 score.",
        "scale": "Each claim: confirmed (receipt + improving trend) · partial (receipt, unclear) · unsupported (no receipt = hand-waving) · broken (receipt REVERSED). Score = mean.",
        "influence": "Feeds the Q pillar's management term (receipts lift Q, hand-waving caps it) and locates where the live risk has RELOCATED — what a resource-catalyst check can't see.",
        "edge": "The Euronet lesson: the 'melting ATM' thesis was stale; the real pressure had moved to Ria remittance under immigration policy. NIS grades the repositioning AND finds the new risk locus.",
    },
    "narrative_break": {
        "what": "A tracked turnaround claim whose RECEIPT has reversed — the segment trend that was improving turned down.",
        "scale": "Fires warn when a claim goes `broken` (deteriorating receipt) — the value-trap confirmation: the discount persists because the segment is structurally melting after all.",
        "influence": "A SENTINEL event (pin + Living-Memory note), never a trade trigger; deduped once per claim.",
        "edge": "It catches the turnaround LOSING its evidence — the moment the deep-value bet flips from mispricing to trap.",
    },
}


def nis_tooltip(key: str) -> str:
    e = NIS_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_NIS_CONFIG)
    block = (config or {}).get("narrative_integrity", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def nis_facets(*, archetype: str = "", lens: str = "", listing: str = "", sector: str = "") -> dict:
    """Type-specific facets so the NIS prompt fits the NAME, not an operating-turnaround template fired
    at an explorer: the right RECEIPT SYSTEM for this profile (segment-disclosure trend for an operating
    turnaround; drill results for an explorer; NSR/stream disclosures for a royalty), whether a drill
    leak even applies, and the right FILING system by listing. Pure; mirrors
    ``divergence_monitor.explain_context``."""
    a = str(archetype or "").strip().lower()
    l = str(lens or "").strip().lower()
    operating = l in ("compounder", "deep_value") or a in ("compounder", "deep_value",
                                                           "capital_margin", "commodity_cyclical")
    if operating:
        kind, drill = "operating_turnaround", False
        receipt_system = ("segment-disclosure trend (10-K/10-Q MD&A) · contract / customer-win "
                          "announcements (issuer PR) · regulatory filings")
    elif a == "option_convexity" or "explor" in a:
        kind, drill = "resource_catalyst", True
        receipt_system = "drill results + resource / PEA updates (SEDAR+ / issuer PR)"
    elif a == "asset_light_yield":
        kind, drill = "royalty", False
        receipt_system = "NSR / stream portfolio disclosures + partner operating updates"
    else:
        kind, drill = "general", False
        receipt_system = "company filings + issuer PR"
    tk = str(listing or "").upper()
    if any(tk.endswith(s) for s in (".V", ".TO", ".CN", ".NE", ".TSX", ".TSXV")):
        filing = "SEDAR+ (Canada)"
    elif tk and ("." not in tk or tk.endswith(".OTC")):
        filing = "SEC EDGAR (US — 10-K / 10-Q / 8-K)"
    else:
        filing = "the issuer's filing system (SEC EDGAR US / SEDAR+ Canada)"
    return {"kind": kind, "receipt_system": receipt_system, "drill_relevant": bool(drill),
            "filing": filing}


def _claim_status(claim: dict, cfg: dict) -> tuple:
    """One claim → (status, score). No receipt ⇒ unsupported (hand-waving). Receipt + reversed trend ⇒
    broken. Receipt + improving/holding ⇒ confirmed. Receipt + unclear ⇒ partial. FAIL-CLOSED: an
    absent receipt is never assumed confirmed."""
    receipt = str((claim or {}).get("receipt") or "").strip()
    trend = str((claim or {}).get("trend") or "").strip().lower()
    if not receipt:
        return "unsupported", float(cfg["unsupported_score"])
    if any(k in trend for k in ("deterior", "down", "revers", "worsen", "falling", "broke")):
        return "broken", float(cfg["broken_score"])
    if any(k in trend for k in ("improv", "up", "rising", "confirm", "holding", "stable", "intact")):
        return "confirmed", float(cfg["confirmed_score"])
    return "partial", float(cfg["partial_score"])


def grade(ticker: str, claims: Any, *, archetype: str = "", lens: str = "", listing: str = "",
          sector: str = "", config: Optional[dict] = None) -> dict:
    """Grade a turnaround narrative claim-by-claim against its receipts → a 0–1 integrity score, the
    per-claim verdicts, the live RISK LOCUS (where the pressure now sits — a `broken`/at-risk claim's
    area), context-aware facets, and the `narrative_break` flags. ``claims`` is a list of
    ``{claim, receipt, trend, source, kind, area?, risk?}``. Empty ⇒ available False. Pure; fail-closed
    (no receipt ⇒ unsupported, never confirmed)."""
    cfg = _cfg(config)
    facets = nis_facets(archetype=archetype, lens=lens, listing=listing, sector=sector)
    graded, scores, flags, events = [], [], [], []
    risk_locus = None
    for c in (claims or []):
        if not isinstance(c, dict) or not c.get("claim"):
            continue
        st, sc = _claim_status(c, cfg)
        area = c.get("area") or c.get("claim")
        graded.append({"claim": c.get("claim"), "status": st, "score": sc,
                       "receipt": c.get("receipt"), "source": c.get("source"), "kind": c.get("kind")})
        scores.append(sc)
        if st == "broken":
            risk_locus = area
            txt = (f"{ticker}: '{c.get('claim')}' receipt REVERSED "
                   f"({c.get('receipt') or 'trend deteriorating'}) — narrative break")
            flags.append({"id": "narrative_break", "ticker": ticker, "level": "warn", "active": True,
                          "claim": c.get("claim"), "text": txt})
            events.append({"type": "narrative_break", "level": "warn", "ticker": ticker, "text": f"SENTINEL: {txt}"})
        elif c.get("risk") and risk_locus is None:
            risk_locus = area
    if not scores:
        return {"available": False, "ticker": ticker, "integrity_score": None, "claims": [],
                "risk_locus": None, "facets": facets, "flags": [], "events": [],
                "read": f"{ticker} narrative integrity n/a (no graded claims)",
                "glossary": {k: nis_tooltip(k) for k in NIS_GLOSSARY}}
    integrity = sum(scores) / len(scores)
    if risk_locus is None:                                     # else: the weakest claim is the live risk
        worst = min(graded, key=lambda g: g["score"])
        risk_locus = worst["claim"] if worst["score"] < float(cfg["confirmed_score"]) else None
    n_conf = sum(1 for g in graded if g["status"] == "confirmed")
    read = (f"{ticker} narrative integrity {integrity:.0%} ({n_conf}/{len(graded)} claims confirmed)"
            + (f"; live risk: {risk_locus}" if risk_locus else "; no live risk locus"))
    return {"available": True, "ticker": ticker, "integrity_score": round(integrity, 3),
            "claims": graded, "risk_locus": risk_locus, "facets": facets, "flags": flags,
            "events": events, "read": read, "glossary": {k: nis_tooltip(k) for k in NIS_GLOSSARY}}


def nis_to_q(integrity_score: Any) -> dict:
    """Map the NIS score to the Q-pillar MANAGEMENT proxy (0–1): a turnaround with receipts lifts the
    management term, hand-waving caps it. Returns ``{management_proxy, note}``; passthrough None when
    the narrative wasn't graded (Q falls back to the supplied management_score). Pure."""
    s = _num(integrity_score)
    if s is None:
        return {"management_proxy": None, "note": "no narrative graded — Q uses the supplied management score"}
    s = max(0.0, min(1.0, s))
    note = ("receipts strong — narrative lifts Q" if s >= 0.7
            else "hand-waving — narrative caps Q" if s < 0.4 else "mixed receipts")
    return {"management_proxy": round(s, 3), "note": note}


def select_fresh(flagged: Any, fired: Optional[dict] = None, *, today: str = "") -> tuple:
    """Dedup so a narrative break pins ONCE per claim, not every cycle. ``fired`` is the engine's
    rolling ledger ``{tk: {date, claim}}``; fresh when the ticker hasn't fired today OR a DIFFERENT
    claim broke. Returns ``(fresh, fired_next)``. Pure; mirrors conventional_sentinel.select_fresh."""
    fired_next = dict(fired or {})
    fresh: list = []
    for r in (flagged or []):
        tk = str((r or {}).get("ticker") or "").strip()
        if not tk:
            continue
        claim = (r or {}).get("claim") or (r or {}).get("id")
        prev = fired_next.get(tk) or {}
        if prev.get("date") == today and prev.get("claim") == claim:
            continue
        fresh.append(r)
        fired_next[tk] = {"date": today, "claim": claim, "id": (r or {}).get("id")}
    return fresh, fired_next
