"""
Cross-check — the retail-data defense (Phase 4 of docs/archive/VALIDATION_FLYWHEEL_PLAN.md).

Institutions triangulate data sources; this book runs on free feeds, so the defense is: for every
field a market API can independently supply (shares outstanding, cash, debt, market cap), compare
the filings-derived research-cache value against the market-API print. On disagreement beyond a
threshold: **flag, never average** (fail-closed) — the field's confidence is demoted to ``low``
(which, through the Phase-3 distributional ribbon, mechanically widens the estimate band and
shrinks conviction), the conflict is written into the field's note, and the caller gets a
structured conflict record to surface (DATA & TRUST panel / Sentinel).

The market values are PASSED IN by the caller (the ingestion cadence / an MCP tool that already
holds an FMP snapshot) — this module does no network I/O, so it is pure and fully testable.
"""
from __future__ import annotations

from typing import Optional

#: relative disagreement beyond which two sources are in CONFLICT (tunable; 10% default —
#: generous enough for timing differences, tight enough to catch a wrong share count).
DEFAULT_THRESHOLD = 0.10

#: research-cache field → the market-API keys that can independently confirm it.
CROSS_CHECKABLE = {
    "shares_out": ("sharesOutstanding", "shares_outstanding", "shares"),
    "cash": ("cashAndCashEquivalents", "totalCash", "cash"),
    "debt": ("totalDebt", "debt"),
    "market_cap": ("marketCap", "mktCap", "market_cap"),
}


def relative_disagreement(a, b) -> Optional[float]:
    """|a−b| / max(|a|,|b|), or None when either side is missing/non-numeric/zero.

    Denominator is max(|a|,|b|), not the midpoint (audit F5): this is the CONSERVATIVE choice —
    it yields the SMALLER relative gap, so the conflict gate fires less eagerly (fewer
    false-positive confidence demotions). A midpoint denominator would be more symmetric but more
    trigger-happy; for a fail-closed flag we prefer to demote only on a clear disagreement."""
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if fa != fa or fb != fb:
        return None
    denom = max(abs(fa), abs(fb))
    if denom <= 0:
        return None
    return abs(fa - fb) / denom


def check_field(rc, ticker: str, field: str, market_value, market_source: str = "market-api",
                *, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Compare one research-cache field against an independent market print.

    Agreement (or one side missing) → ``{"status": "ok"|"single_source", ...}``.
    CONFLICT → demote the cached field's confidence to ``low`` with the conflict in its note
    (history preserved — ``set()`` pushes the prior entry; this is a visible restatement, not a
    silent rewrite), and return the structured conflict record. The values are NEVER averaged."""
    entry = rc.get(ticker, field)
    if not entry:
        return {"status": "single_source", "ticker": ticker, "field": field,
                "note": "no filings-derived value cached — nothing to cross-check"}
    dis = relative_disagreement(entry.get("value"), market_value)
    if dis is None:
        return {"status": "single_source", "ticker": ticker, "field": field,
                "note": "market value missing/non-numeric — cross-check not possible"}
    if dis <= threshold:
        return {"status": "ok", "ticker": ticker, "field": field,
                "disagreement": round(dis, 4), "threshold": threshold}
    detail = (f"DATA CONFLICT: filings {entry.get('value')!r} vs {market_source} "
              f"{market_value!r} ({dis:.0%} apart > {threshold:.0%}) — flag, never average; "
              f"confidence demoted to low (fail-closed) until reconciled")
    rc.set(ticker, field, entry.get("value"), entry.get("source", ""),
           entry.get("as_of", ""), confidence="low", note=detail[:300])
    return {"status": "conflict", "ticker": ticker, "field": field,
            "filings_value": entry.get("value"), "market_value": market_value,
            "market_source": market_source,
            "disagreement": round(dis, 4), "threshold": threshold,
            "action": "confidence demoted to low; band widens; values NOT averaged",
            "note": detail}


def cross_check_ticker(rc, ticker: str, market_values: dict, *,
                       threshold: float = DEFAULT_THRESHOLD,
                       market_source: str = "market-api") -> dict:
    """Cross-check every CROSS_CHECKABLE field present on both sides. ``market_values`` is the
    caller-supplied market snapshot (any of the alias keys per field). Returns the per-field
    results + a conflicts list for the DATA & TRUST panel / Sentinel."""
    results, conflicts = {}, []
    for field, aliases in CROSS_CHECKABLE.items():
        mv = next((market_values[k] for k in aliases if k in (market_values or {})
                   and market_values[k] is not None), None)
        if mv is None:
            continue
        res = check_field(rc, ticker, field, mv, market_source, threshold=threshold)
        results[field] = res
        if res.get("status") == "conflict":
            conflicts.append(res)
    return {"ticker": str(ticker).upper(), "checked": len(results),
            "conflicts": conflicts, "results": results}


# --------------------------------------------------------------------------- #
#  Store-seam defense (the GROY currency lesson, 2026-07-03)
# --------------------------------------------------------------------------- #
def store_seam_check(pairs: list, *, threshold: float = 0.15) -> dict:
    """Detect a SEAM between two stores that must agree: the valuation ledger's stamped price and the
    price-history close for the SAME ticker on the SAME date. They are written by different paths
    (engine mark vs ingestion/backfill), so a systematic divergence means one store is on a different
    basis — the exact failure that poisoned GROY's replay grades (a USD Yahoo backfill next to CAD
    ledger marks: every same-date pair ~40%% apart, i.e. the FX rate). Flag, never average.

    ``pairs``: [(ticker, date, ledger_price, store_close)] — assembled by the caller (replay), so this
    stays pure/no-I/O. Returns per-ticker stats: a ticker is ``seamed`` when the MEDIAN same-date
    divergence exceeds ``threshold`` over ≥3 pairs (median so one restated print can't trip it, and a
    real basis seam shifts every pair, not one). Consumers must treat a seamed ticker's grades as
    untrustworthy and say so — never report them as model failures."""
    by_tk: dict = {}
    for tk, day, lp, sc in pairs or []:
        try:
            lp_f, sc_f = float(lp), float(sc)
        except (TypeError, ValueError):
            continue
        if lp_f <= 0 or sc_f <= 0:
            continue
        by_tk.setdefault(str(tk).upper(), []).append(abs(sc_f / lp_f - 1.0))
    out = {}
    for tk, divs in by_tk.items():
        divs.sort()
        med = divs[len(divs) // 2] if len(divs) % 2 else (divs[len(divs) // 2 - 1] + divs[len(divs) // 2]) / 2
        seamed = len(divs) >= 3 and med > threshold
        out[tk] = {"pairs": len(divs), "median_divergence": round(med, 4), "seamed": seamed,
                   **({"note": f"stores disagree by ~{med:.0%} on the same dates — different basis "
                               f"(currency/source); grades for {tk} are untrustworthy until reconciled"}
                      if seamed else {})}
    return out
