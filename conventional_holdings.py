"""
conventional_holdings.py — the conventional lane's missing PRODUCER (the on-ramp).

The consumer side of the conventional lane has existed for a while: the engine's eval cycle reads
``state_cache['dual_sided_reads']`` and runs ``conventional_sentinel`` over it, and ``dual_sided``
prices any conventional name on demand. But nothing ever WROTE ``dual_sided_reads`` — the comment in
engine.py says "the PRODUCER is the conventional-holdings integration" and that integration was never
built. The practical consequence surfaced 2026-08-01: the operator HELD a conventional position
(CEGS — Constellation CDRs) and the dashboard showed a book without it. A cockpit that renders
phantom holdings is a bug (the URC lesson); one that hides real holdings is the same bug mirrored.

This module is that producer, pure and engine-free:

  * **membership** — a conventional holding is a ``portfolio_metadata`` entry with
    ``lane: "conventional"`` (the same test ``dual_sided.is_conventional`` already applies) and a
    ``dual_sided`` underwriting block. NOT ``barbell_weights``: the barbell is the resource
    sizer's domain, and the lane guard's whole point is that conventional names never enter the
    scout/council/sizing machinery.
  * **pricing** — via a caller-supplied ``price_fn(pricing_ref)`` (the engine passes its cached,
    budget-capped FMP client; tests pass a stub). ``pricing_ref`` exists because the traded
    instrument may have no vendor coverage (the CDR problem): you hold CEGS, you price CEG.
    A missing price falls back to the underwriting payload's stored price, STAMPED stale — the
    grounded-or-silent discipline: shown, never silently fresh.
  * **the read** — each name is valued through ``dual_sided.value`` (both lenses + reconciliation)
    and shaped exactly as ``conventional_sentinel.assess_book`` expects
    (``{ticker, lens, price, ladder, weight?, target?}``), plus a compact ``sleeve row`` for the
    cockpit's HOLDINGS rail.
  * **fenced per name** — one bad underwriting block yields an error row, never a dead sleeve.

Pure stdlib + dual_sided. No engine import, no network, no eval().
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import dual_sided

__all__ = ["positions", "build_reads", "sleeve_rows", "ws_symbol_map"]


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- membership
def positions(portfolio_metadata: Optional[dict]) -> list:
    """The conventional-lane holdings declared in ``portfolio_metadata``: entries whose lane is
    conventional AND that carry a ``dual_sided`` underwriting block. An entry with the lane but no
    block is returned too — flagged ``unpriceable`` so the gap is visible (a held name with no
    underwriting is exactly what the sleeve must surface, not skip)."""
    out = []
    for tk, meta in (portfolio_metadata or {}).items():
        if str(tk).startswith("_") or not isinstance(meta, dict):
            continue
        if not dual_sided.is_conventional(str(tk), portfolio_metadata):
            continue
        ds = meta.get("dual_sided")
        out.append({
            "ticker": str(tk).upper(),
            "name": meta.get("name") or str(tk),
            "instrument": meta.get("instrument") or str(tk),
            "units": _num(meta.get("units")),
            "pricing_ref": str(meta.get("pricing_ref") or tk).upper(),
            "lens": str((ds or {}).get("lens") or "compounder"),
            "target_weight": _num(meta.get("target_weight")),
            "inputs": dict(ds) if isinstance(ds, dict) else None,
            "unpriceable": not isinstance(ds, dict),
        })
    return out


def ws_symbol_map(portfolio_metadata: Optional[dict]) -> dict:
    """{brokerage CSV symbol → config ticker} for every conventional entry that declares
    ``ws_symbol`` — the engine's holdings-CSV loader matches through THIS instead of hardcoded
    per-name branches, so registering a new holding (one ``add_holding`` call) is the ONLY step:
    no engine edit, ever. Symbols upper-cased; a missing ws_symbol simply doesn't match (the
    entry's units then come from config alone)."""
    out = {}
    for tk, meta in (portfolio_metadata or {}).items():
        if str(tk).startswith("_") or not isinstance(meta, dict):
            continue
        if not dual_sided.is_conventional(str(tk), portfolio_metadata):
            continue
        ws = str(meta.get("ws_symbol") or "").strip().upper()
        if ws:
            out[ws] = str(tk).upper()
    return out


# --------------------------------------------------------------------------- the reads
def build_reads(pos: list, price_fn: Optional[Callable] = None, *,
                nav: Any = None, unit_prices: Optional[dict] = None,
                config: Optional[dict] = None) -> dict:
    """{ticker: read} for ``state_cache['dual_sided_reads']`` — each read carries the
    conventional_sentinel shape ({lens, price, ladder, weight, target}) plus the full headline for
    the sleeve (rating · band · zone · lens PILLARS). ``price_fn(pricing_ref) -> live price or
    None``; a None falls back to the stored underwriting price, stamped ``price_stale=True``.

    Market value NEVER comes from units × the reference price: the traded instrument can differ
    from the pricing reference (24 CDRs are not 24 CEG shares — the ratio differs), so mv/weight
    are computed only from ``unit_prices[ticker]`` — the instrument's OWN unit price (e.g. from
    the holdings export) — and stay None otherwise. ``nav`` (book NAV, same currency as the unit
    price) turns mv into a live weight; without it the rebalance-band tripwire is a clean no-op.
    Fenced per name."""
    reads: dict = {}
    for p in (pos or []):
        tk = p["ticker"]
        if p.get("unpriceable"):
            reads[tk] = {"ticker": tk, "error": "no dual_sided underwriting block in "
                                                "portfolio_metadata — sleeve shows the gap",
                         "instrument": p.get("instrument"), "units": p.get("units")}
            continue
        try:
            payload = dict(p["inputs"] or {})
            payload["ticker"] = tk
            live = None
            if callable(price_fn):
                try:
                    live = _num(price_fn(p["pricing_ref"]))
                except Exception:
                    live = None
            stale = live is None
            if live is not None:
                payload["price"] = live
            res = dual_sided.value(payload, config=config)
            rec = res.get("reconciliation") or {}
            lens = str(rec.get("lead_lens") or p["lens"] or "compounder")
            lead = res.get(lens) or res.get("compounder") or {}
            ladder = dict(lead.get("ladder") or {})
            price = _num(payload.get("price"))
            units = p.get("units")
            unit_px = _num((unit_prices or {}).get(tk))
            mv = (units * unit_px) if (units is not None and unit_px is not None) else None
            nv = _num(nav)
            weight = (mv / nv) if (mv is not None and nv and nv > 0) else None
            head = rec.get("headline") or {}
            reads[tk] = {
                "ticker": tk, "lens": lens, "price": price, "ladder": ladder,
                "weight": weight, "target": p.get("target_weight"),
                "price_stale": stale,
                "instrument": p.get("instrument"), "units": units,
                "unit_price": unit_px, "market_value": mv,
                "rating": _num(head.get("rating") if head else lead.get("rating")),
                "band": head.get("band") or lead.get("band"),
                "zone": rec.get("zone") or lead.get("zone"),
                "shape": rec.get("shape"),
                "pillars": dict(lead.get("pillars") or {}),   # the lens's T/Q/V-shaped scores
                "narrative_flags": res.get("narrative_flags") or [],
            }
        except Exception as ex:                            # one bad block never kills the sleeve
            reads[tk] = {"ticker": tk, "error": str(ex)[:140],
                         "instrument": p.get("instrument"), "units": p.get("units")}
    return reads


def sleeve_rows(reads: dict) -> list:
    """Compact rows for the cockpit HOLDINGS rail's CONVENTIONAL section — plain data, render-free
    (the TUI builder styles them). Errors and stale prices ride along visibly."""
    rows = []
    for tk in sorted(reads or {}):
        r = reads[tk] or {}
        if r.get("error"):
            rows.append({"ticker": tk, "error": r["error"], "instrument": r.get("instrument")})
            continue
        lad = r.get("ladder") or {}
        rows.append({
            "ticker": tk, "instrument": r.get("instrument"), "units": r.get("units"),
            "lens": r.get("lens"), "rating": r.get("rating"), "band": r.get("band"),
            "zone": r.get("zone"), "shape": r.get("shape"),
            "pillars": r.get("pillars") or {},
            "price": r.get("price"), "price_stale": bool(r.get("price_stale")),
            "floor": _num(lad.get("floor")), "base": _num(lad.get("base")),
            "bull": _num(lad.get("bull")), "weight": r.get("weight"),
            "market_value": r.get("market_value"),
        })
    return rows
