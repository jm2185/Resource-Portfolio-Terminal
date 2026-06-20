"""
Per-name thesis-variable monitors (action-plan P5.1).

P4.2 gives each holding its discrete invalidation *trip lines*; this is the finer-grained companion —
the **named variables each thesis actually lives or dies on**, tracked continuously, so the desk sees
a thesis *drifting* off-track before it trips. It is the authoritative "what to watch per name": the
framework is defined here (which variables, which direction is good, which are thesis-breakers); the
engine/agents supply the live reads from the data they hold.

Each variable carries: the read direction (`good`), whether it is **hard** (a thesis-breaker — off-track
⇒ the whole thesis is off-track), and a source. The rollup is deliberately conservative: any hard
variable off-track ⇒ OFF-TRACK; any soft variable off-track or any hard variable unknown ⇒ WATCH;
all-known-on-track ⇒ ON-TRACK. Unknowns never read as healthy (they read as gaps).

Pure + dependency-free; the per-slot variable sets are a reasoned first calibration, tunable via
/confirm (`thesis_monitor.*`). No eval(); graceful on absent reads.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["THESIS_VARIABLES", "THESIS_GLOSSARY", "thesis_tooltip", "assess"]

#: What each thesis slot lives or dies on. `good`: the healthy direction. `hard`: a thesis-breaker.
THESIS_VARIABLES: dict[str, list[dict]] = {
    "silver-spear": [
        {"id": "silver_price", "label": "Silver price (commodity beta)", "good": "up", "hard": False, "source": "macro/FMP"},
        {"id": "catalyst_delivery", "label": "Binary catalyst (43-101 / PEA / drilling)", "good": "advancing", "hard": True, "source": "issuer PR / SEDAR+"},
        {"id": "floor_coverage", "label": "REP floor coverage (margin of safety)", "good": "high", "hard": True, "source": "engine REP floor"},
        {"id": "jsf_integrity", "label": "JSF forensic integrity", "good": "clean", "hard": True, "source": "engine JSF gate"},
        {"id": "financing_runway", "label": "Financing runway (months of cash)", "good": "high", "hard": False, "source": "filings"},
    ],
    "gold-royalty-ballast": [
        {"id": "gold_price", "label": "Gold price", "good": "up", "hard": False, "source": "macro/FMP"},
        {"id": "royalty_cash_flow", "label": "Royalty cash flow / GEOs growth", "good": "up", "hard": False, "source": "filings"},
        {"id": "counterparty_production", "label": "Counterparty mine production", "good": "stable", "hard": True, "source": "operator reports"},
        {"id": "nav_per_share", "label": "NAV per share", "good": "up", "hard": False, "source": "filings/consensus"},
    ],
    "project-generator-holdco": [
        {"id": "nav_discount", "label": "Holdco discount to NAV", "good": "narrowing", "hard": False, "source": "NAV vs price"},
        {"id": "portfolio_nav", "label": "Portfolio NAV", "good": "up", "hard": False, "source": "filings"},
        {"id": "discovery_pipeline", "label": "Discovery optionality (investee drilling)", "good": "advancing", "hard": False, "source": "investee PR"},
        {"id": "cash_position", "label": "Treasury / cash position", "good": "high", "hard": True, "source": "filings"},
    ],
    "electrification-royalty": [
        {"id": "uranium_term_price", "label": "Uranium term price (structural, not spot)", "good": "up", "hard": True, "source": "TradeTech LTP"},
        {"id": "royalty_cash_flow", "label": "Royalty / holding cash flow", "good": "up", "hard": False, "source": "filings"},
        {"id": "electrification_demand", "label": "Electrification demand (U/Cu/grid)", "good": "up", "hard": False, "source": "macro/sector"},
        {"id": "vehicle_structure", "label": "Vehicle structure (royalty/holding, NOT operator)", "good": "intact", "hard": True, "source": "filings/structure"},
    ],
}

_GOOD_UP = {"up", "high"}        # numeric-RISING is healthy; "narrowing"/"down"/"low" ⇒ falling is healthy
_STATUS = {"on_track", "watch", "off_track", "unknown"}

THESIS_GLOSSARY: dict[str, dict[str, str]] = {
    "thesis_monitor": {
        "what": "The per-name thesis-variable dashboard — the specific variables each holding's thesis lives or dies on, tracked continuously so drift shows before a trip.",
        "scale": "Per name: ON-TRACK (all known healthy) · WATCH (soft drift or a hard unknown) · OFF-TRACK (a hard variable off-track).",
        "influence": "The finer-grained companion to the P4 invalidation lines; a hard variable off-track is the thesis-breaker.",
        "edge": "Unknowns never read as healthy — a data gap is a WATCH on a hard variable, not a pass.",
    },
}


def thesis_tooltip(key: str) -> str:
    e = THESIS_GLOSSARY.get(key)
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


def _resolve_status(var: dict, reading: Any) -> tuple[str, str]:
    """Resolve a variable's status + a short detail from its reading. Reading may be an explicit
    status string, or a dict with {status} / {value,min} / {value,prior}, or absent."""
    good = var.get("good")
    if reading is None:
        return "unknown", "no read"
    if isinstance(reading, str):
        s = reading.strip().lower()
        return (s if s in _STATUS else "unknown"), (reading if s in _STATUS else f"unrecognized '{reading}'")
    if isinstance(reading, dict):
        if isinstance(reading.get("status"), str) and reading["status"].lower() in _STATUS:
            return reading["status"].lower(), str(reading.get("detail", reading["status"]))
        val = _num(reading.get("value"))
        if val is not None and reading.get("min") is not None:
            mn = _num(reading["min"])
            ok = (val >= mn) if mn is not None else None
            if ok is not None:
                return ("on_track" if ok else "off_track"), f"{val:g} vs min {mn:g}"
        if val is not None and reading.get("prior") is not None:
            pr = _num(reading["prior"])
            if pr is not None:
                rising = val >= pr
                healthy = rising if good in _GOOD_UP else (not rising)
                return ("on_track" if healthy else ("watch" if abs(val - pr) <= 1e-9 else "off_track")), f"{val:g} vs prior {pr:g}"
        if val is not None:
            return "unknown", f"value {val:g} (no rule)"
    return "unknown", "uninterpretable read"


def assess(holding: Optional[dict], readings: Optional[dict] = None, *, config: Optional[dict] = None) -> dict:
    """Assess one holding's thesis variables. ``holding``: {ticker, slot|thesis_slot}. ``readings``:
    {var_id: status|dict}. Returns the per-variable status, the rollup thesis health, and the
    off-track / watch / unknown breakdowns."""
    holding = holding or {}
    slot = holding.get("slot") or holding.get("thesis_slot")
    cfg_vars = (config or {}).get("thesis_monitor", {}).get("variables") if config else None
    variables = (cfg_vars or {}).get(slot) if isinstance(cfg_vars, dict) else None
    variables = variables or THESIS_VARIABLES.get(slot, [])
    readings = readings or {}

    rows, off, watch, unknown = [], [], [], []
    hard_off = hard_unknown = False
    for var in variables:
        status, detail = _resolve_status(var, readings.get(var["id"]))
        rows.append({"id": var["id"], "label": var["label"], "good": var["good"],
                     "hard": bool(var.get("hard")), "status": status, "detail": detail})
        if status == "off_track":
            off.append(var["id"])
            if var.get("hard"):
                hard_off = True
        elif status == "watch":
            watch.append(var["id"])
        elif status == "unknown":
            unknown.append(var["id"])
            if var.get("hard"):
                hard_unknown = True

    if hard_off:
        health = "OFF-TRACK"
    elif off or watch or hard_unknown:
        health = "WATCH"
    elif rows and not unknown:
        health = "ON-TRACK"
    elif rows:
        health = "WATCH"          # only soft unknowns left — incomplete, not healthy
    else:
        health = "UNKNOWN"        # no framework for this slot

    return {"ticker": holding.get("ticker"), "slot": slot, "variables": rows,
            "thesis_health": health, "off_track": off, "watch": watch, "unknown": unknown,
            "glossary": {k: thesis_tooltip(k) for k in THESIS_GLOSSARY}}
