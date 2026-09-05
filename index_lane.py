"""
index_lane.py — the INDEX-DIVERSIFIER lane (the fourth lane; built 2026-09-05).

The book had no home for a broad, liquid index vehicle. The resource satellite is single-name
convexity behind the disconfirmation gate; the conventional lane is US/Canada SINGLE-NAME cash flow
priced dual-sided; the garage lane is a savings ladder. When the desk measured XEC.TO (iShares Core
MSCI EM, CAD) at ρ 0.24–0.28 to EVERY book holding — more decorrelated than any ballast the book has
ever held — the only honest answer to "can the book own it?" was "it has no slot" (Memory
20260905-010024). This module is that slot, from first principles:

  * **Purpose: decorrelation + scenario coverage, NEVER alpha.** Same third invariant as the
    conventional lane (monitoring only — no scout, no council, no discovery, no pipeline; the guard in
    ``dual_sided.guard_conventional`` covers both lanes). A diversifier earns its place by what it does
    for the BOOK's shape, so the lane optimises what the @counterweight mandate optimises.
  * **Membership gate is MEASURED, not narrative — the GMX lesson as an ENTRY rule.** A candidate must
    carry a *decorrelation receipt*: its trailing ρ to the spear must sit at least ``rho_margin``
    BELOW the book's average pairwise ρ (the same ``DIVERSIFIER_MARGIN`` the coherence checker uses
    to catch a diversifier being CUT on a taxonomy argument — imported, so the two can never drift).
    "It's an index, of course it diversifies" is exactly the sentence this gate refuses.
  * **It must name the hole it covers.** ``scenario_payoffs`` with at least one positive payoff — the
    same field the scenario engine already merges for conventional names, so the coverage gauge reads
    book truth the moment the position exists. A diversifier that covers nothing is just beta.
  * **Vehicle gates — the EMBX lesson (20260904-163351-5ca612).** Book currency (a USD-listed vehicle
    against weekly CAD contributions pays ~3% round trip in FX), liquidity (median daily notional),
    breadth (constituent count — single-name risk is the OTHER lanes' job), and a fee cap.
  * **No single-name underwriting; the read is INDEX-level and STREET by construction.** An index has
    no FCF, no management, no REP floor. Its inputs are consensus forward P/E, its OWN multiple
    history, and its EMPIRICAL drawdown — every one of them ``basis: street`` or ``basis: empirical``,
    and the read says so on its face. It is deliberately NOT run through the T/Q/V asymmetry rating:
    Q is meaningless for an index and V's floor-coverage semantics assume a modeled floor. The lane
    produces a ZONE (via ``conventional_sentinel.zone_of`` — the same ladder shape, so the existing
    sentinel consumes it unchanged), never a RATING.
  * **A floor as well as a ceiling.** The conventional ceiling governs adds. A diversifier ALSO needs
    a floor: below some weight it moves nothing and is noise wearing a ticker. Both are config, both
    MEASURE — the operator sizes. Ceiling governs adds; no forced sale (the CEG ruling, 2026-08-29).
  * **Thin by design.** No council, no gauntlet. The decorrelation receipt IS the gate; it is written
    to Memory at add time so the reasoning survives.

Pure stdlib + the two pure siblings it reuses (``conventional_sentinel.zone_of``,
``coherence_check.DIVERSIFIER_MARGIN``). No engine import, no network.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import conventional_sentinel
from coherence_check import DIVERSIFIER_MARGIN

__all__ = ["LANE", "MONITORING_LANES", "DEFAULT_INDEX_LANE_CONFIG", "is_index", "is_monitoring_lane",
           "positions", "decorrelation_gate", "vehicle_gate", "coverage_declaration", "value",
           "weight_band", "build_reads", "sleeve_rows", "admission"]

#: the lane tag in ``portfolio_metadata[ticker].lane``
LANE = "index"
#: lanes the engine PRICES and WATCHES but never scouts / councils / sizes (the third invariant)
MONITORING_LANES: frozenset = frozenset({"conventional", LANE})

DEFAULT_INDEX_LANE_CONFIG: dict[str, Any] = {
    "_comment": ("Index-diversifier lane (index_lane.py). Weights are fractions of book. "
                 "rho_margin is bound to coherence_check.DIVERSIFIER_MARGIN — a config override is "
                 "honoured but the shipped default cannot drift from the coherence checker's."),
    "ceiling": 0.15,                    # governs ADDS; no forced sale above it
    "floor": 0.05,                      # below this a diversifier moves nothing — noise wearing a ticker
    "rho_margin": DIVERSIFIER_MARGIN,   # ρ_to_spear must be ≤ avg_pairwise − margin to count as diversifying
    "corr_window_days": 250,            # the receipt's minimum trailing window
    "receipt_max_age_days": 45,         # a receipt older than this must be re-measured before an add
    "min_constituents": 100,            # breadth: single-name risk belongs to the other lanes
    "min_median_notional": 1_000_000,   # book-currency notional/day; thin vehicles are the EMBX lesson
    "max_expense_ratio": 0.0035,        # fee cap (0.35%)
    "book_currency": "CAD",
    "erp_thin": 0.02,                   # earnings yield − 10Y below this = expensive vs bonds (warn)
    "scenario_covered_min": 0.05,       # a payoff ≥ this in some scenario = the hole it covers
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    out = dict(DEFAULT_INDEX_LANE_CONFIG)
    blk = (config or {}).get("index_lane") if isinstance(config, dict) else None
    if isinstance(blk, dict):
        out.update({k: v for k, v in blk.items() if not str(k).startswith("_")})
    return out


# --------------------------------------------------------------------------- membership
def _lane_of(ticker: str, portfolio_metadata: Optional[dict]) -> str:
    md = portfolio_metadata or {}
    entry = md.get(ticker) or md.get(str(ticker).upper()) or {}
    return str((entry or {}).get("lane") or "resource").strip().lower()


def is_index(ticker: str, portfolio_metadata: Optional[dict]) -> bool:
    return _lane_of(ticker, portfolio_metadata) == LANE


def is_monitoring_lane(ticker: str, portfolio_metadata: Optional[dict]) -> bool:
    """True for any lane the engine prices/watches but never scouts/councils/sizes (conventional OR
    index). ``"conv"`` substring-matches to stay tolerant of the existing ``conventional`` spellings."""
    lane = _lane_of(ticker, portfolio_metadata)
    return lane == LANE or "conv" in lane


def positions(portfolio_metadata: Optional[dict]) -> list:
    """The index-lane holdings declared in ``portfolio_metadata``: entries whose lane is ``index``.
    An entry with the lane but no ``index_lane`` read block is returned too — flagged ``unpriceable``
    so the gap is visible (a held vehicle with no read is exactly what the sleeve must surface)."""
    out = []
    for tk, meta in (portfolio_metadata or {}).items():
        if str(tk).startswith("_") or not isinstance(meta, dict):
            continue
        if not is_index(str(tk), portfolio_metadata):
            continue
        blk = meta.get("index_lane") if isinstance(meta.get("index_lane"), dict) else None
        out.append({
            "ticker": str(tk), "name": meta.get("name") or str(tk), "lane": LANE,
            "units": _num(meta.get("units")) or 0.0,
            "ws_symbol": (meta.get("ws_symbol") or "").upper() or None,
            "pricing_ref": str(meta.get("pricing_ref") or tk).upper(),
            "currency": str(meta.get("currency") or "").upper() or None,
            "thesis_slot": meta.get("thesis_slot") or "index-diversifier",
            "index_lane": dict(blk) if blk else None,
            "scenario_payoffs": dict(meta["scenario_payoffs"]) if isinstance(meta.get("scenario_payoffs"), dict) else None,
            "unpriceable": blk is None,
        })
    return out


# --------------------------------------------------------------------------- the gates
def decorrelation_gate(rho_to_spear: Any, avg_pairwise: Any, *, config: Optional[dict] = None,
                       window_days: Any = None, as_of: Any = None, today: Any = None) -> dict:
    """The MEASURED membership gate. Passes only when ρ(candidate, spear) ≤ avg_pairwise − rho_margin
    over a window of at least ``corr_window_days``. Missing numbers FAIL (grounded-or-silent — an
    unmeasured diversifier is a narrative). ``as_of``/``today`` (YYYY-MM-DD) age the receipt."""
    cfg = _cfg(config)
    rho, avg = _num(rho_to_spear), _num(avg_pairwise)
    margin = float(cfg["rho_margin"])
    reasons = []
    if rho is None or avg is None:
        reasons.append("no measured ρ — a diversifier that is not measured is a narrative")
        return {"passed": False, "rho_to_spear": rho, "avg_pairwise": avg, "bar": None, "margin": margin,
                "reasons": reasons, "read": "decorrelation gate FAILED: " + reasons[0]}
    bar = round(avg - margin, 4)
    if rho > bar:
        reasons.append(f"ρ{rho:+.2f} to the spear is not ≥{margin:.2f} below the book's avg pairwise "
                       f"ρ{avg:.2f} (bar {bar:+.2f}) — inside the cluster, not outside it")
    wd = _num(window_days)
    if wd is not None and wd < float(cfg["corr_window_days"]):
        reasons.append(f"window {wd:.0f}d < the {cfg['corr_window_days']}d minimum")
    age = _age_days(as_of, today)
    if age is not None and age > float(cfg["receipt_max_age_days"]):
        reasons.append(f"receipt is {age:.0f}d old (> {cfg['receipt_max_age_days']}d) — re-measure")
    ok = not reasons
    read = (f"decorrelation gate PASSED: ρ{rho:+.2f} to the spear vs bar {bar:+.2f} "
            f"(avg pairwise ρ{avg:.2f} − margin {margin:.2f})" if ok
            else "decorrelation gate FAILED: " + "; ".join(reasons))
    return {"passed": ok, "rho_to_spear": rho, "avg_pairwise": avg, "bar": bar, "margin": margin,
            "window_days": wd, "age_days": age, "reasons": reasons, "read": read}


def _age_days(as_of: Any, today: Any) -> Optional[float]:
    from datetime import date
    try:
        a = date.fromisoformat(str(as_of)[:10]) if as_of else None
        t = date.fromisoformat(str(today)[:10]) if today else date.today()
    except ValueError:
        return None
    if a is None:
        return None
    return float((t - a).days)


def vehicle_gate(meta: Optional[dict], *, config: Optional[dict] = None) -> dict:
    """The vehicle-quality gates (the EMBX lesson): book currency, liquidity, breadth, fee cap. Reads
    ``meta['index_lane']`` (``constituents``, ``median_notional``, ``expense_ratio``) and
    ``meta['currency']``. A missing input FAILS its check by name — never silently passes."""
    cfg = _cfg(config)
    m = meta or {}
    blk = m.get("index_lane") if isinstance(m.get("index_lane"), dict) else {}
    checks, failures = {}, []

    ccy = str(m.get("currency") or blk.get("currency") or "").upper()
    ok = bool(ccy) and ccy == str(cfg["book_currency"]).upper()
    checks["currency"] = {"value": ccy or None, "required": cfg["book_currency"], "passed": ok}
    if not ok:
        failures.append(f"currency {ccy or 'unknown'} ≠ book currency {cfg['book_currency']} "
                        f"(FX toll on every contribution and every rung sale)")

    n = _num(blk.get("constituents"))
    ok = n is not None and n >= float(cfg["min_constituents"])
    checks["constituents"] = {"value": n, "required": cfg["min_constituents"], "passed": ok}
    if not ok:
        failures.append(f"constituents {n if n is not None else 'unknown'} < {cfg['min_constituents']} "
                        f"(breadth — single-name risk belongs to the other lanes)")

    liq = _num(blk.get("median_notional"))
    ok = liq is not None and liq >= float(cfg["min_median_notional"])
    checks["median_notional"] = {"value": liq, "required": cfg["min_median_notional"], "passed": ok}
    if not ok:
        failures.append(f"median daily notional {liq if liq is not None else 'unknown'} < "
                        f"{cfg['min_median_notional']:,.0f} (a thin vehicle is the EMBX lesson)")

    er = _num(blk.get("expense_ratio"))
    ok = er is not None and er <= float(cfg["max_expense_ratio"])
    checks["expense_ratio"] = {"value": er, "required": cfg["max_expense_ratio"], "passed": ok}
    if not ok:
        failures.append(f"expense ratio {er if er is not None else 'unknown'} > "
                        f"{cfg['max_expense_ratio']:.4f} cap")

    return {"passed": not failures, "checks": checks, "failures": failures,
            "read": "vehicle gate PASSED" if not failures else "vehicle gate FAILED: " + "; ".join(failures)}


def coverage_declaration(meta: Optional[dict], *, config: Optional[dict] = None) -> dict:
    """A diversifier must NAME the hole it covers: ``scenario_payoffs`` with at least one payoff ≥
    ``scenario_covered_min``. This is the same field ``scenario_engine.merge_conventional`` merges,
    so declaring it here is what makes the coverage gauge read book truth once the position exists."""
    cfg = _cfg(config)
    sp = (meta or {}).get("scenario_payoffs")
    if not isinstance(sp, dict) or not sp:
        return {"declared": False, "covers": [], "read": "no scenario_payoffs declared — a diversifier that "
                                                        "covers nothing is just beta"}
    thr = float(cfg["scenario_covered_min"])
    covers = sorted(s for s, v in sp.items() if _num(v) is not None and _num(v) >= thr)
    if not covers:
        return {"declared": False, "covers": [], "read": f"scenario_payoffs declared but none ≥ {thr:.2f} — "
                                                        f"it covers no hole"}
    return {"declared": True, "covers": covers, "read": f"covers scenario {', '.join(covers)}"}


def admission(meta: Optional[dict], *, spear_rho: Any = None, avg_pairwise: Any = None,
              config: Optional[dict] = None, today: Any = None) -> dict:
    """The whole on-ramp in one call: decorrelation receipt + vehicle gates + coverage declaration.
    The receipt comes from ``meta['index_lane']['decorrelation_receipt']`` (``rho_to_spear``,
    ``avg_pairwise``, ``window_days``, ``as_of``, ``source``) unless overridden by the keyword
    arguments (an engine with a live corr matrix passes its own numbers). Pure."""
    m = meta or {}
    blk = m.get("index_lane") if isinstance(m.get("index_lane"), dict) else {}
    rc = blk.get("decorrelation_receipt") if isinstance(blk.get("decorrelation_receipt"), dict) else {}
    dg = decorrelation_gate(spear_rho if spear_rho is not None else rc.get("rho_to_spear"),
                            avg_pairwise if avg_pairwise is not None else rc.get("avg_pairwise"),
                            config=config, window_days=rc.get("window_days"), as_of=rc.get("as_of"),
                            today=today)
    vg = vehicle_gate(m, config=config)
    cd = coverage_declaration(m, config=config)
    if not rc.get("source") and spear_rho is None:
        dg = dict(dg, passed=False, reasons=list(dg["reasons"]) + ["receipt carries no source"],
                  read=dg["read"] + "; receipt carries no source")
    admitted = bool(dg["passed"] and vg["passed"] and cd["declared"])
    return {"admitted": admitted, "decorrelation": dg, "vehicle": vg, "coverage": cd,
            "read": ("ADMITTED — " + dg["read"] + "; " + vg["read"] + "; " + cd["read"]) if admitted
            else "REFUSED — " + "; ".join(r for r in (
                "" if dg["passed"] else dg["read"], "" if vg["passed"] else vg["read"],
                "" if cd["declared"] else cd["read"]) if r)}


# --------------------------------------------------------------------------- the read
def value(payload: dict, *, config: Optional[dict] = None) -> dict:
    """The INDEX read — street by construction, said so on its face. Inputs (all optional, each
    missing one is named in ``data_completeness``):

      price · fwd_pe (consensus forward P/E, basis street) · pe_hist {p10,p50,p90} (the index's OWN
      trailing multiple distribution) · max_drawdown (fraction, EMPIRICAL — the worst peak-to-trough
      over the lookback) · y10 (10Y yield, fraction).

    Ladder — the same {floor, base, bull} shape the conventional sentinel consumes:
      floor = price × (1 − max_drawdown)      ← EMPIRICAL crash floor, NOT a modeled REP floor
      base  = price × (pe_p50 / fwd_pe)       ← reversion to the index's own median multiple
      bull  = price × (pe_p90 / fwd_pe)       ← its own 90th-percentile multiple (extended above)
    Plus the earnings-yield-vs-bonds read (ERP = 1/fwd_pe − y10) and where the current multiple
    sits in its own history. No T/Q/V rating — an index gets a ZONE, never a RATING."""
    cfg = _cfg(config)
    p = _num(payload.get("price"))
    pe = _num(payload.get("fwd_pe"))
    hist = payload.get("pe_hist") if isinstance(payload.get("pe_hist"), dict) else {}
    p10, p50, p90 = _num(hist.get("p10")), _num(hist.get("p50")), _num(hist.get("p90"))
    dd = _num(payload.get("max_drawdown"))
    y10 = _num(payload.get("y10"))
    missing = [k for k, v in (("price", p), ("fwd_pe", pe), ("pe_hist.p50", p50), ("pe_hist.p90", p90),
                              ("max_drawdown", dd), ("y10", y10)) if v is None]
    completeness = {"missing": missing, "score": round(1 - len(missing) / 6, 2)}
    base = {"lens": LANE, "ticker": payload.get("ticker"), "archetype": LANE, "available": False,
            "basis": "street", "price": p, "data_completeness": completeness}
    if p is None or pe is None or pe <= 0 or p50 is None:
        return dict(base, ladder=None, zone=None,
                    read=f"index read unavailable — missing {', '.join(missing) or 'inputs'}")

    floor = round(p * (1.0 - dd), 4) if dd is not None and 0.0 <= dd < 1.0 else None
    base_v = round(p * (p50 / pe), 4)
    bull = round(p * (p90 / pe), 4) if p90 is not None else None
    ladder = {"floor": floor, "base": base_v, "bull": bull,
              "basis": {"floor": "empirical" if floor is not None else None, "base": "street", "bull": "street"}}
    zone = conventional_sentinel.zone_of(p, ladder)

    ey = 1.0 / pe
    erp = round(ey - y10, 4) if y10 is not None else None
    # where the current multiple sits in its own history (piecewise-linear across p10/p50/p90)
    pct = None
    if p10 is not None and p90 is not None and p90 > p10:
        if pe <= p50 and p50 > p10:
            pct = 0.10 + 0.40 * (pe - p10) / (p50 - p10)
        elif pe > p50 and p90 > p50:
            pct = 0.50 + 0.40 * (pe - p50) / (p90 - p50)
        pct = round(min(max(pct, 0.0), 1.0), 3) if pct is not None else None

    flags = []
    if erp is not None and erp < float(cfg["erp_thin"]):
        flags.append({"id": "erp_thin", "level": "warn",
                      "text": f"earnings yield {ey:.1%} − 10Y {y10:.1%} = ERP {erp:+.1%} < {cfg['erp_thin']:.0%}: "
                              f"expensive vs bonds"})
    if zone.get("zone") == "extended":
        flags.append({"id": "multiple_extended", "level": "warn",
                      "text": f"fwd P/E {pe:.1f} above its own p90 {p90:.1f} — extended vs its history"})

    read = (f"{payload.get('ticker') or 'index'} @ {p:.2f}: fwd P/E {pe:.1f} vs own p50 {p50:.1f}"
            + (f" / p90 {p90:.1f}" if p90 is not None else "")
            + (f" ({pct:.0%}ile of own history)" if pct is not None else "")
            + f" → base {base_v:.2f}" + (f", floor {floor:.2f} (empirical −{dd:.0%})" if floor is not None else "")
            + f"; {zone.get('read')}"
            + (f"; ERP {erp:+.1%}" if erp is not None else "")
            + " — STREET inputs, no modeled floor, no rating")
    return dict(base, available=True, ladder=ladder, zone=zone.get("zone"), earnings_yield=round(ey, 4),
                erp=erp, pe_percentile=pct, flags=flags, read=read)


def weight_band(weight: Any, *, config: Optional[dict] = None) -> dict:
    """Where a live weight sits against the lane's floor/ceiling. MEASURES; the operator sizes.
    ``add_frozen`` is True at/above the ceiling (the CEG ruling: ceiling governs ADDS, no forced sale)."""
    cfg = _cfg(config)
    w = _num(weight)
    lo, hi = float(cfg["floor"]), float(cfg["ceiling"])
    if w is None:
        return {"zone": None, "weight": None, "floor": lo, "ceiling": hi, "add_frozen": False,
                "read": "weight band n/a (need a live weight)"}
    if w >= hi:
        z, rd = "above_ceiling", f"weight {w:.1%} ≥ ceiling {hi:.0%} — ADD-FROZEN (no forced sale)"
    elif w < lo:
        z, rd = "below_floor", f"weight {w:.1%} < floor {lo:.0%} — too small to diversify anything; size up or out"
    else:
        z, rd = "in_band", f"weight {w:.1%} inside the {lo:.0%}–{hi:.0%} band"
    return {"zone": z, "weight": w, "floor": lo, "ceiling": hi, "add_frozen": w >= hi, "read": rd}


# --------------------------------------------------------------------------- reads + sleeve
def build_reads(pos: list, price_fn: Optional[Callable] = None, *, config: Optional[dict] = None,
                nav: Any = None, unit_prices: Optional[dict] = None) -> dict:
    """Price + value each index-lane position. ``price_fn(pricing_ref)`` returns a live price or None;
    a dead feed falls back to the read block's stored price STAMPED stale. ``unit_prices`` (per
    ticker) mark the traded instrument when it differs from the pricing reference. Each name is
    fenced: one bad block yields an error row, never a dead sleeve. Shape per name:
    ``{lens, price, ladder, zone, weight?, band, ...}`` — what ``conventional_sentinel.assess_book``
    consumes, plus the lane's own band."""
    out: dict = {}
    up = unit_prices or {}
    navf = _num(nav)
    for p in pos or []:
        tk = p["ticker"]
        try:
            blk = p.get("index_lane") or {}
            if not blk:
                out[tk] = {"ticker": tk, "lens": LANE, "error": "unpriceable", "available": False,
                           "read": f"{tk}: index lane entry with no index_lane read block — pass fwd_pe / "
                                   f"pe_hist / max_drawdown / y10 to price it"}
                continue
            live = None
            if price_fn:
                try:
                    live = _num(price_fn(p.get("pricing_ref") or tk))
                except Exception:
                    live = None
            stale = live is None
            price = live if live is not None else _num(blk.get("price"))
            v = value({**blk, "ticker": tk, "price": price}, config=config)
            unit_px = _num(up.get(tk)) if up.get(tk) is not None else price
            units = _num(p.get("units")) or 0.0
            mv = round(units * unit_px, 2) if unit_px is not None and units else None
            w = round(mv / navf, 4) if (mv is not None and navf) else None
            r = dict(v)
            r.update({"ticker": tk, "lens": LANE, "stale": stale, "units": units, "unit_price": unit_px,
                      "market_value": mv, "weight": w, "band": weight_band(w, config=config),
                      "thesis_slot": p.get("thesis_slot"), "name": p.get("name"),
                      "coverage": coverage_declaration(p, config=config)})
            if stale:
                r["read"] = (r.get("read") or "") + " [STALE: no live price — stored read price]"
            out[tk] = r
        except Exception as e:  # pragma: no cover — the fence itself
            out[tk] = {"ticker": tk, "lens": LANE, "error": f"{type(e).__name__}: {e}", "available": False}
    return out


def sleeve_rows(reads: dict) -> list:
    """Compact rows for the cockpit's HOLDINGS rail — stale/error states SHOWN, never hidden."""
    rows = []
    for tk, r in (reads or {}).items():
        if not isinstance(r, dict):
            continue
        if r.get("error"):
            rows.append({"ticker": tk, "lane": LANE, "error": r["error"], "read": r.get("read") or r["error"]})
            continue
        rows.append({"ticker": tk, "lane": LANE, "name": r.get("name"), "price": r.get("price"),
                     "stale": bool(r.get("stale")), "units": r.get("units"),
                     "market_value": r.get("market_value"), "weight": r.get("weight"),
                     "zone": r.get("zone"), "band": (r.get("band") or {}).get("zone"),
                     "add_frozen": bool((r.get("band") or {}).get("add_frozen")),
                     "erp": r.get("erp"), "covers": (r.get("coverage") or {}).get("covers") or [],
                     "basis": "street", "read": r.get("read")})
    return rows
