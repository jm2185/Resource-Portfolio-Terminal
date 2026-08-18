"""
Seesaw-day classifier — name WHICH kind of day the bond–metal tape just had.

The regime board decomposes the yield (inflation_regime: Δnominal = Δreal + Δbreakeven) and reads
the metals tape, but nothing JOINS them — so "yields moved and metals moved" stays a vibe the desk
re-derives in chat. The same nominal headline means opposite books depending on the pairing:

  • yields UP  + metals UP    → SEESAW-B    — the distrust/inflation term bid (debasement tape);
                                 the metals bid IS the bond exodus. Book tailwind.
  • yields DOWN + metals DOWN → SEESAW-E    — normalization: trust term unwinding; bonds catch the
                                 bid metals give back. The TLT-call direction.
  • yields UP  + metals DOWN  → COMMON-ENEMY — the real-rate move; both long-duration seats lose.
                                 No rotation story exists — don't hunt for one.
  • yields DOWN + metals UP   → BOTH-BID-A  — easing/repression flavor; both seats win.
  • both down HARD            → LIQUIDATION — margin flow, not macro; correlations→1, floors not
                                 narratives (the July shape).

One-directional — a regime/tape EVIDENCE stamp (feeds the B⇄E axis and Living Memory's day record),
never a name-level score and never an action. Pure + dependency-free; thresholds tunable via
/confirm (``seesaw_day.*``); graceful on thin inputs (no prior day ⇒ dormant); no eval().

The classifier is pure (`classify`); the tiny per-day snapshot store (`record_snapshot` /
`prior_snapshot`) mirrors rates_history so the engine has a yesterday to compare against.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

__all__ = ["DEFAULT_SEESAW_CONFIG", "SEESAW_GLOSSARY", "seesaw_tooltip",
           "classify", "record_snapshot", "prior_snapshot"]

DEFAULT_SEESAW_CONFIG: dict[str, Any] = {
    "y_min": 0.03,        # |Δ10Y| (pp) below this = yields flat / noise
    "metal_min": 0.75,    # |metal day %| below this = metals flat / noise
    "liq_metal": -2.5,    # metal day % at/below this ...
    "liq_dy": 0.06,       # ... WITH Δ10Y (pp) at/above this = liquidation shape (both sold hard)
    "attr_min": 0.02,     # |Δreal| / |Δbreakeven| (pp) below this = attribution treated as flat
    "max_metal_move": 12.0,  # |metal day %| above this = basis discontinuity (mixed sources), not a day
    "max_dy": 0.40,          # |Δ10Y| (pp) above this = basis discontinuity, not a day
}

SEESAW_GLOSSARY: dict[str, dict[str, str]] = {
    "seesaw_day": {
        "what": ("Joint bond–metal day type: pairs the 10Y move with the gold move (and, when the "
                 "inflation_regime decomposition is live, the Δreal/Δbreakeven attribution) into one "
                 "of SEESAW-B / SEESAW-E / COMMON-ENEMY / BOTH-BID-A / LIQUIDATION / QUIET."),
        "scale": ("SEESAW-B = distrust bid (metals tailwind) · SEESAW-E = normalization (TLT-call "
                  "direction) · COMMON-ENEMY = real-rate move, both long-duration seats lose · "
                  "BOTH-BID-A = easing, both win · LIQUIDATION = margin flow, ignore narratives."),
        "influence": ("Regime/tape evidence for the B⇄E axis + the recorded day-type Living Memory "
                      "stamps carry. One-directional — never a name score, never an action."),
        "edge": ("The same 'yields rose' headline is a metals tailwind (B), a both-lose day "
                 "(real-led), or a margin cascade — the PAIRING with metals tells them apart; the "
                 "Δreal/Δbreakeven attribution then names the driving leg."),
    },
}


def seesaw_tooltip(key: str) -> str:
    e = SEESAW_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Types: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_SEESAW_CONFIG)
    block = (config or {}).get("seesaw_day", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


# --------------------------------------------------------------------------- the pure classifier
def classify(*, metal_ret_pct: Any = None, d_y10: Any = None,
             d_real: Any = None, d_breakeven: Any = None,
             config: Optional[dict] = None) -> dict:
    """Classify the joint bond–metal day. ``metal_ret_pct`` = gold day return (%), ``d_y10`` = 10Y
    yield change (pp, day-over-day). ``d_real`` / ``d_breakeven`` (pp, from inflation_regime's
    decomposition) refine the read when present. Graceful: either core input missing ⇒
    ``available=False`` (dormant) — never a fabricated day type."""
    cfg = _cfg(config)
    m, dy = _num(metal_ret_pct), _num(d_y10)
    if m is None or dy is None:
        return {"available": False, "day_type": None, "read": "seesaw n/a (missing metal or 10Y day move)",
                "bias": "neutral", "scenario_hint": None,
                "inputs": {"metal_ret_pct": m, "d_y10": dy},
                "glossary": {k: seesaw_tooltip(k) for k in SEESAW_GLOSSARY}}

    # Basis guard: a "day move" beyond plausible bounds means the snapshot store compared two
    # different price bases (cache swap, symbol change, seeded-vs-live mix) — refuse to classify
    # rather than stamp a fake regime day. (Found live 2026-08-19: seeded true closes vs the
    # engine's internally-cached gold basis produced a nonsense −47% "metal move".)
    if abs(m) > float(cfg["max_metal_move"]) or abs(dy) > float(cfg["max_dy"]):
        return {"available": False, "day_type": None,
                "read": (f"basis discontinuity (metal {m:+.1f}%, Δ10Y {dy:+.2f}) — inputs exceed "
                         "plausible day ranges; snapshot store likely mixed sources"),
                "bias": "neutral", "scenario_hint": None,
                "inputs": {"metal_ret_pct": round(m, 3), "d_y10": round(dy, 4)},
                "glossary": {k: seesaw_tooltip(k) for k in SEESAW_GLOSSARY}}

    y_min, m_min = float(cfg["y_min"]), float(cfg["metal_min"])
    dr, db = _num(d_real), _num(d_breakeven)
    attr_min = float(cfg["attr_min"])

    # attribution tag (only when the decomposition is live)
    attr = ""
    if dr is not None and db is not None:
        if abs(dr) >= abs(db) and abs(dr) >= attr_min:
            attr = f" — real-led ({dr:+.2f} real)"
        elif abs(db) > abs(dr) and abs(db) >= attr_min:
            attr = f" — breakeven-led ({db:+.2f} be)"

    day_type, read, bias, hint = "MIXED", "Unclassified pairing", "neutral", None

    if m <= float(cfg["liq_metal"]) and dy >= float(cfg["liq_dy"]):
        day_type = "LIQUIDATION"
        read = "Bonds AND metals sold hard — margin flow, not macro; correlations→1, floors not narratives"
        bias, hint = "risk_off", "path-risk (July shape) — no scenario evidence"
    elif abs(dy) < y_min and abs(m) < m_min:
        day_type, read, bias = "QUIET", "No joint signal (both legs inside noise)", "neutral"
    elif dy >= y_min and m >= m_min:
        day_type = "SEESAW-B"
        read = f"Yields up, metals up — distrust/inflation term bid{attr}; metals tailwind"
        bias, hint = "risk_off", "evidence for B (fiscal-distrust)"
    elif dy >= y_min and m <= -m_min:
        day_type = "COMMON-ENEMY"
        read = f"Yields up, metals down — real-rate move{attr}; both long-duration seats lose, no rotation story"
        bias, hint = "risk_off", "evidence for real-rate shock (C-adjacent)"
    elif dy <= -y_min and m <= -m_min:
        day_type = "SEESAW-E"
        read = f"Yields down, metals down — normalization flavor{attr}; trust term unwinding (TLT-call direction)"
        bias, hint = "risk_on", "evidence for E (benign normalization)"
    elif dy <= -y_min and m >= m_min:
        day_type = "BOTH-BID-A"
        read = f"Yields down, metals up — easing/repression flavor{attr}; both seats win"
        bias, hint = "risk_on", "evidence for A (managed debasement / easing)"
    elif abs(dy) < y_min:
        day_type = "METAL-LED"
        read = "Metals moved without the bond market — idiosyncratic/commodity flow, no seesaw claim"
        bias = "neutral"
    else:
        day_type = "BOND-DRIFT"
        read = f"Bond move without metals confirmation{attr} — watch, don't conclude"
        bias = "neutral"

    return {"available": True, "day_type": day_type, "read": read, "bias": bias,
            "scenario_hint": hint,
            "inputs": {"metal_ret_pct": round(m, 3), "d_y10": round(dy, 4),
                       "d_real": (round(dr, 4) if dr is not None else None),
                       "d_breakeven": (round(db, 4) if db is not None else None)},
            "glossary": {k: seesaw_tooltip(k) for k in SEESAW_GLOSSARY}}


# --------------------------------------------------------------------------- tiny per-day store
DEFAULT_PATH = os.path.join("data", "seesaw_history.jsonl")
_KEYS = ("gold", "silver", "y10", "real", "be", "vix")


def _today(now: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))


def _snapshots(path: str) -> list[dict]:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except (ValueError, json.JSONDecodeError):
                    continue
    except OSError:
        return []
    out.sort(key=lambda e: str(e.get("day") or ""))
    return out


def record_snapshot(vals: Optional[dict], *, path: str = DEFAULT_PATH,
                    now: Optional[float] = None) -> Optional[dict]:
    """UPSERT today's {gold, silver, y10, real, be, vix} snapshot (any subset; non-numeric dropped).
    Last write of the day wins — early cycles can carry boot-default/stale marks (found live
    2026-08-19: gold 2350 recorded pre-fetch), so the day's row must converge to the final live
    marks rather than freeze the first cycle's. Returns the entry, or None if nothing usable."""
    day = _today(now)
    keep = {k: _num((vals or {}).get(k)) for k in _KEYS}
    keep = {k: v for k, v in keep.items() if v is not None}
    if not keep:
        return None
    entry = {"day": day, **keep}
    rows = [e for e in _snapshots(path) if e.get("day") != day]
    rows.append(entry)
    rows.sort(key=lambda e: str(e.get("day") or ""))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in rows:
            fh.write(json.dumps(e) + "\n")
    os.replace(tmp, path)
    return entry


def prior_snapshot(*, path: str = DEFAULT_PATH, max_age_days: float = 5.0,
                   now: Optional[float] = None) -> Optional[dict]:
    """The most recent snapshot from BEFORE today and at most ``max_age_days`` old — the 'yesterday'
    the classifier compares against. None when history is too thin/stale (honest dormancy)."""
    today = _today(now)
    t_now = now if now is not None else time.time()
    best = None
    for e in _snapshots(path):
        day = str(e.get("day") or "")
        if not day or day >= today:
            continue
        try:
            age = (t_now - time.mktime(time.strptime(day, "%Y-%m-%d"))) / 86400.0
        except (ValueError, OverflowError):
            continue
        if age <= max_age_days + 1.0:
            best = e
    return best
