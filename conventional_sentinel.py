"""
conventional_sentinel.py — the archetype-aware SENTINEL tripwires for the conventional core
(Phase 4 of docs/archive/DUAL_SIDED_TIV_BUILD_SPEC.md).

The conventional lane is monitoring-only; these are its tripwires, in the divergence_monitor /
correlation_monitor shape (pure ``assess`` → ``{flags, events}`` → ``select_fresh`` dedup → the engine
``_fire_*`` auto-pin). Two checks (the third, ``correlation_drift``, already shipped in Phase 1):

  • ASYMMETRY-ZONE CROSS — the price crossing into/out of a lens's asymmetry zones, read off the
    dual-sided LADDER (floor / base / bull). The signal is in the TRANSITION, not the level: a deep-
    value name crossing BELOW its asset/FCF floor is an opportunity (good); a compounder crossing ABOVE
    its priced-in-growth ceiling (the bull leg) is extended / torpedo-exposed (warn). Lens-flavored.

  • REBALANCE-BAND — a sleeve's live weight drifting outside an operator-set band around its target.
    It MEASURES the drift and prompts the operator; it NEVER sizes (the book_factor discipline).

Pure + dependency-free (plain math, no numpy/pandas); never raises; thresholds tunable via /confirm
(``conventional_sentinel.*``); no eval().
"""
from __future__ import annotations

from typing import Any, Optional

import monitor_protocol as _mp
from monitor_protocol import num as _num

__all__ = ["DEFAULT_CONVENTIONAL_SENTINEL_CONFIG", "CONVENTIONAL_SENTINEL_GLOSSARY",
           "conventional_sentinel_tooltip", "zone_of", "asymmetry_zone_cross", "rebalance_band",
           "assess_name", "assess_book", "select_fresh"]

DEFAULT_CONVENTIONAL_SENTINEL_CONFIG: dict[str, Any] = {
    "rebalance_band_pct": 0.03,   # |live weight − target| above this (in weight points) ⇒ drift flag
}

#: the four zones a price sits in relative to a lens's ladder, ranked low→high so a CROSS has direction.
_ZONE_RANK: dict = {"below_floor": 0, "accumulate": 1, "fair_to_rich": 2, "extended": 3}

CONVENTIONAL_SENTINEL_GLOSSARY: dict[str, dict[str, str]] = {
    "asymmetry_zone_cross": {
        "what": "The price crossing into/out of a lens's asymmetry zones (below floor · accumulate · fair-to-rich · extended), off the dual-sided ladder.",
        "scale": "Falling BELOW the floor = opportunity (good); rising ABOVE the priced-in-growth ceiling / bull = extended (warn). The signal is the crossing, not the level.",
        "influence": "A SENTINEL event (pin + Living-Memory note), never a trade trigger — it fires once per zone entry, deduped.",
        "edge": "Lens-flavored: a deep-value name below its asset/FCF floor is a discount; a compounder above its bull leg is torpedo-exposed (a growth miss now compresses the multiple).",
    },
    "rebalance_band": {
        "what": "A conventional sleeve's live weight drifting outside an operator-set band around its target.",
        "scale": "|weight − target| beyond ~3 weight points ⇒ a drift flag — the sleeve has grown/shrunk away from its intended size.",
        "influence": "MEASURES the drift and prompts the operator; it NEVER sizes — allocation stays the operator's dial.",
        "edge": "The thin-lane allocation gauge: it keeps a winning conventional sleeve from quietly becoming an oversized bet (or a faded one), without auto-trading.",
    },
}


def conventional_sentinel_tooltip(key: str) -> str:
    return _mp.tooltip(CONVENTIONAL_SENTINEL_GLOSSARY, key)


def _cfg(config: Optional[dict]) -> dict:
    return _mp.merged_config(DEFAULT_CONVENTIONAL_SENTINEL_CONFIG, config, "conventional_sentinel")


def zone_of(price: Any, ladder: Optional[dict]) -> dict:
    """Classify where ``price`` sits on a lens's ladder (floor / base / bull) into one of four zones:
    ``below_floor`` · ``accumulate`` (floor→base) · ``fair_to_rich`` (base→bull) · ``extended`` (≥bull).
    Returns ``{zone, read}``; ``zone=None`` when the ladder is too thin to classify (graceful). Pure."""
    p = _num(price)
    L = ladder or {}
    floor, base, bull = _num(L.get("floor")), _num(L.get("base")), _num(L.get("bull"))
    if p is None or base is None:
        return {"zone": None, "read": "zone n/a (need price + a base intrinsic)"}
    if floor is not None and p < floor:
        z = "below_floor"
    elif p < base:
        z = "accumulate"
    elif bull is not None and p < bull:
        z = "fair_to_rich"
    elif bull is not None:
        z = "extended"
    else:
        z = "fair_to_rich" if p >= base else "accumulate"
    return {"zone": z, "read": f"price {p:.2f} is in the {z.replace('_', ' ')} zone"}


def asymmetry_zone_cross(ticker: str, price: Any, ladder: Optional[dict], *, lens: str = "",
                         prev_zone: Optional[str] = None, config: Optional[dict] = None) -> dict:
    """Detect a price crossing a lens's asymmetry zone since last cycle. Fires ONLY on a transition
    (``prev_zone`` differs from the current zone) — the first observation just records the zone. The
    flag's level reads the DIRECTION: falling into ``below_floor``/``accumulate`` = opportunity (good);
    rising into ``extended`` = torpedo-exposed / rich (warn); other crossings = info (e.g. a discount
    window closing). Lens-flavored text. Pure; graceful when the ladder is thin."""
    zr = zone_of(price, ladder)
    cur = zr["zone"]
    out = {"ticker": ticker, "lens": lens, "zone": cur, "prev_zone": prev_zone,
           "crossed": False, "flags": [], "events": [], "read": zr["read"]}
    if cur is None or prev_zone is None or prev_zone == cur:
        return out                                            # no prior zone, or no transition → record only
    out["crossed"] = True
    rose = _ZONE_RANK.get(cur, 0) - _ZONE_RANK.get(prev_zone, 0) > 0
    is_dv = "deep" in str(lens or "").lower()
    if not rose and cur == "below_floor":
        level = "good"
        why = ("crossed BELOW the asset/FCF floor — a deep-discount opportunity (φ≥1)" if is_dv
               else "crossed BELOW the torpedo floor — priced under the de-rated-multiple value")
    elif not rose and cur == "accumulate":
        level, why = "good", "fell into the accumulate zone (below base intrinsic)"
    elif rose and cur == "extended":
        level = "warn"
        why = ("crossed ABOVE the bull/SOTP — the discount is spent" if is_dv
               else "crossed ABOVE the priced-in-growth ceiling (bull) — extended, torpedo-exposed on a miss")
    elif rose and prev_zone == "below_floor":
        level, why = "info", "reclaimed the floor — the deep-discount window closed"
    else:
        level, why = "info", f"moved from {prev_zone.replace('_', ' ')} to {cur.replace('_', ' ')}"
    txt = f"{ticker} ({lens}) {why}"
    out["read"] = txt
    out["flags"] = [{"id": "asymmetry_zone_cross", "ticker": ticker, "level": level, "active": True,
                     "zone": cur, "text": txt}]
    out["events"] = [{"type": "zone_cross", "level": level, "ticker": ticker,
                      "text": f"SENTINEL: {txt}"}]
    return out


def rebalance_band(ticker: str, weight: Any, target: Any, *, config: Optional[dict] = None) -> dict:
    """Flag a conventional sleeve whose live ``weight`` has drifted outside the band around its
    ``target`` (both fractions, e.g. 0.08 = 8%). MEASURES the drift; never sizes — the flag prompts the
    operator, who decides. Pure; dormant when either input is missing."""
    cfg = _cfg(config)
    w, t = _num(weight), _num(target)
    if w is None or t is None:
        return {"ticker": ticker, "drifted": False, "drift": None, "flags": [], "events": [],
                "read": f"{ticker} rebalance n/a (need live weight + target)"}
    band = float(cfg["rebalance_band_pct"])
    drift = w - t
    drifted = abs(drift) > band
    read = f"{ticker} weight {w:.1%} vs target {t:.1%} ({drift:+.1%})"
    flags, events = [], []
    if drifted:
        read += f" — outside the ±{band:.0%} band; consider rebalancing (operator decides)"
        flags.append({"id": "rebalance_drift", "ticker": ticker, "level": "warn", "active": True,
                      "drift": round(drift, 4), "text": read})
        events.append({"type": "rebalance_drift", "level": "warn", "ticker": ticker, "text": f"SENTINEL: {read}"})
    return {"ticker": ticker, "drifted": drifted, "drift": round(drift, 4), "flags": flags,
            "events": events, "read": read}


def assess_name(ticker: str, *, lens: str = "", price: Any = None, ladder: Optional[dict] = None,
                weight: Any = None, target: Any = None, prev_zone: Optional[str] = None,
                config: Optional[dict] = None) -> dict:
    """Run both conventional tripwires for one name: the zone cross + the rebalance band. Returns the
    combined flags/events, the current zone (for the engine to carry forward as next cycle's
    ``prev_zone``), and the reads. Pure."""
    zc = asymmetry_zone_cross(ticker, price, ladder, lens=lens, prev_zone=prev_zone, config=config)
    rb = rebalance_band(ticker, weight, target, config=config)
    return {"ticker": ticker, "lens": lens, "zone": zc["zone"], "crossed": zc["crossed"],
            "flags": zc["flags"] + rb["flags"], "events": zc["events"] + rb["events"],
            "reads": {"zone": zc["read"], "rebalance": rb["read"]}}


def assess_book(reads: Any, *, prev_zones: Optional[dict] = None, config: Optional[dict] = None) -> dict:
    """Run the conventional tripwires across the conventional sleeves in one pass. ``reads`` is a list
    of ``{ticker, lens, price, ladder, weight?, target?}`` (the lead-lens dual-sided read per name);
    ``prev_zones`` is ``{ticker: zone}`` from last cycle. Returns ``by_ticker``, the fired ``flags``,
    and ``zones_next`` (carry forward). Empty input ⇒ a clean no-op (no conventional holdings yet).
    Pure."""
    prev_zones = prev_zones or {}
    by_t, flags, events, zones_next = {}, [], [], dict(prev_zones)
    for r in (reads or []):
        tk = str((r or {}).get("ticker") or "").strip()
        if not tk:
            continue
        res = assess_name(tk, lens=(r or {}).get("lens", ""), price=(r or {}).get("price"),
                          ladder=(r or {}).get("ladder"), weight=(r or {}).get("weight"),
                          target=(r or {}).get("target"), prev_zone=prev_zones.get(tk), config=config)
        by_t[tk] = res
        flags.extend(res["flags"])
        events.extend(res["events"])
        if res["zone"] is not None:
            zones_next[tk] = res["zone"]
    return {"available": bool(by_t), "by_ticker": by_t, "flags": flags, "events": events,
            "zones_next": zones_next,
            "glossary": {k: conventional_sentinel_tooltip(k) for k in CONVENTIONAL_SENTINEL_GLOSSARY}}


def select_fresh(flagged: Any, fired: Optional[dict] = None, *, today: str = "") -> tuple:
    """Dedup the firing so a zone cross / rebalance drift pins ONCE per event, not every cycle.
    ``fired`` is the engine's rolling ledger ``{tk: {date, key}}``; a flag is FRESH when this ticker
    hasn't fired today OR its key (zone label, or the rebalance id) changed since it last fired (a new
    zone is a new event). Returns ``(fresh, fired_next)``. Pure; the loop is
    ``monitor_protocol.select_fresh`` — only the zone-key semantics live here."""
    return _mp.select_fresh(
        flagged, fired, today=today, ticker_field="ticker",
        state_fn=lambda r: {"key": r.get("zone") or r.get("id"), "id": r.get("id")},
        is_repeat=lambda prev, st: prev.get("key") == st["key"])
