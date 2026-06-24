"""
book_factor.py — is this a PORTFOLIO, or one bet wearing different tickers?

Two READ-ONLY gauges over data the engine already computes, so a "you're too concentrated / your
scenarios have holes" critique becomes MEASURED fact instead of a vibe:

  • factor_concentration — the realized single-factor read: the average pairwise correlation across the
    book (high ⇒ "diversified by NAME, concentrated in one macro factor"), plus each ballast name's
    correlation to the SPEAR (a ballast whose ρ→1 has quietly stopped being ballast). Computed from the
    cached 60d correlation matrix.
  • scenario_coverage — the book's probability-weighted payoff in EACH scenario and the UNCOVERED weight
    (futures the book has no answer to). The critique's "portfolio-why" matrix collapsed to one number,
    built from the scenario-engine's own per-name payoffs × book weights.

This MEASURES; it never sizes, allocates, or recommends a buy — the conviction dial stays the operator's.
Pure + dependency-free (plain math, no numpy/pandas). Tunables under ``book_factor.*`` (proposal-gated).
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_BOOK_FACTOR_CONFIG", "factor_concentration", "scenario_coverage"]

DEFAULT_BOOK_FACTOR_CONFIG: dict[str, Any] = {
    "single_factor_corr": 0.60,      # avg pairwise correlation at/above which the book reads single-factor
    "ballast_decoupled_min": 0.85,   # a ballast name correlated to the spear above this has stopped being ballast
    "scenario_covered_min": 0.05,    # book payoff ≥ this = covered; ≥0 = thin; <0 = an active headwind
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_BOOK_FACTOR_CONFIG)
    block = (config or {}).get("book_factor", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def _corr(corr_matrix: Optional[dict], a: str, b: str) -> Optional[float]:
    """Symmetric correlation lookup that tolerates either key order and casing. None if absent."""
    m = corr_matrix or {}
    for x, y in ((a, b), (b, a)):
        row = m.get(x)
        if not isinstance(row, dict):
            row = m.get(x.upper()) if isinstance(m.get(x.upper()), dict) else None
        if isinstance(row, dict):
            v = _num(row.get(y))
            if v is None:
                v = _num(row.get(y.upper()))
            if v is not None:
                return v
    return None


def factor_concentration(corr_matrix: Optional[dict], tickers: Any, *, spear: str = "AGA.V",
                         config: Optional[dict] = None) -> dict:
    """The realized single-factor read for the book. ``corr_matrix`` is the engine's cached nested
    correlation dict ``{t1: {t2: ρ}}``; ``tickers`` is the book (held names). Returns the average
    pairwise correlation (high ⇒ one factor), each non-spear name's correlation to the spear, and a
    flag per ballast name that has drifted toward ρ→1 with the spear (it has stopped diversifying).
    Pure; graceful when correlations are missing."""
    cfg = _cfg(config)
    tks = [str(t).strip() for t in (tickers or []) if str(t or "").strip()]
    pairs = []
    for i in range(len(tks)):
        for j in range(i + 1, len(tks)):
            c = _corr(corr_matrix, tks[i], tks[j])
            if c is not None:
                pairs.append(c)
    avg = round(sum(pairs) / len(pairs), 3) if pairs else None

    spear_corr = {}
    for t in tks:
        if t == spear:
            continue
        c = _corr(corr_matrix, spear, t)
        if c is not None:
            spear_corr[t] = round(c, 3)

    thr = float(cfg["single_factor_corr"])
    single = bool(avg is not None and avg >= thr)
    bd = float(cfg["ballast_decoupled_min"])
    flags = []
    for t, c in spear_corr.items():
        if c >= bd:
            flags.append({"id": "ballast_correlated", "ticker": t, "level": "warn", "corr": c,
                          "text": f"{t} ρ{c:.2f} to {spear} — moves WITH the spear; not diversifying risk"})
    if avg is None:
        read = "factor concentration n/a (need ≥2 book names with cached correlations)"
    else:
        read = (f"avg pairwise ρ {avg:.2f} across {len(tks)} names — "
                + ("ONE factor wearing different tickers (diversified by name, not by risk)"
                   if single else "genuinely multi-factor"))
    return {"available": avg is not None, "n": len(tks), "spear": spear, "avg_pairwise": avg,
            "spear_corr": spear_corr, "single_factor": single, "single_factor_threshold": thr,
            "flags": flags, "read": read}


def scenario_coverage(scenario_result: Optional[dict], *, config: Optional[dict] = None) -> dict:
    """Book-level scenario coverage from the scenario-engine result. For each scenario it computes the
    book-weighted expected payoff (held names only, weighted by ``book_weight``) and classifies it
    covered / thin / headwind; the UNCOVERED weight is the probability mass on scenarios the book has no
    answer to. The critique's coverage matrix as one gauge: 'X% of your own scenario weight is
    un-hedged'. Pure; never an allocation call."""
    cfg = _cfg(config)
    sr = scenario_result or {}
    weights = sr.get("weights") or {}
    rows = sr.get("rankings") or []
    held = [r for r in rows if isinstance(r, dict) and (_num(r.get("book_weight")) or 0.0) > 0]
    total_w = sum((_num(r.get("book_weight")) or 0.0) for r in held)
    covered_min = float(cfg["scenario_covered_min"])
    scen_keys = list(weights.keys()) or ["A", "B", "C", "D"]

    by_scenario, holes, uncovered_w = {}, [], 0.0
    for s in scen_keys:
        sw = _num(weights.get(s)) or 0.0
        if held and total_w > 0:
            bp = sum((_num(r.get("book_weight")) or 0.0) * (_num((r.get("payoffs") or {}).get(s)) or 0.0)
                     for r in held) / total_w
        else:
            bp = None
        status = ("n/a" if bp is None else "covered" if bp >= covered_min
                  else "thin" if bp >= 0 else "headwind")
        by_scenario[s] = {"weight": round(sw, 4),
                          "book_payoff": (round(bp, 3) if bp is not None else None), "status": status}
        if bp is not None and bp < covered_min:
            uncovered_w += sw
            holes.append({"scenario": s, "name": (sr.get("scenarios") or {}).get(s, {}).get("name"),
                          "weight": round(sw, 4), "book_payoff": round(bp, 3), "status": status})
    uncovered_w = round(uncovered_w, 4)
    if not held:
        read = "scenario coverage n/a (no held names carry scenario payoffs)"
    else:
        read = (f"{uncovered_w:.0%} of scenario weight is under-/un-covered"
                + (f" (holes: {', '.join(h['scenario'] for h in holes)})" if holes
                   else " — every scenario has an answer"))
    return {"available": bool(held), "by_scenario": by_scenario, "uncovered_weight": uncovered_w,
            "covered_weight": (round(max(0.0, 1.0 - uncovered_w), 4) if held else None),
            "holes": holes, "read": read}
