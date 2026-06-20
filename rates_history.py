"""
Rates history (action-plan P2.1 support) — a tiny append-only daily snapshot of the Treasury rate
levels, so the rates monitor can detect "the long end rising OVER A WINDOW" (it needs a prior-window
value, which the engine's latest-only metrics don't keep).

Deliberately minimal and file-based (mirrors price_history.py / living_memory.py): one JSON line per
day, idempotent (re-recording the same day is a no-op). Pure stdlib, no engine import — the caller
passes the resolved rate levels. Robust to a torn line (skips it, never crashes).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

DEFAULT_PATH = "data/rates_history.jsonl"
_KEYS = ("dgs2", "dgs5", "dgs10", "dgs30", "fedfunds")


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _today(now: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))


def _age_days(day: str, now: Optional[float] = None) -> Optional[float]:
    try:
        t = time.mktime(time.strptime(day, "%Y-%m-%d"))
    except (ValueError, OverflowError):
        return None
    return ((now if now is not None else time.time()) - t) / 86400.0


def snapshots(path: str = DEFAULT_PATH) -> list[dict]:
    """Every recorded snapshot, oldest-first. Tolerates a torn line."""
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


def record(rates: Optional[dict], *, path: str = DEFAULT_PATH, now: Optional[float] = None) -> Optional[dict]:
    """Append today's rate snapshot, ONCE per day (idempotent). ``rates`` = {dgs2,dgs5,dgs10,dgs30,
    fedfunds} (any subset; non-numeric dropped). Returns the entry, or None if today's already
    recorded or no usable rate is present."""
    day = _today(now)
    vals = {k: _num((rates or {}).get(k)) for k in _KEYS}
    vals = {k: v for k, v in vals.items() if v is not None}
    if not vals:
        return None
    if any(e.get("day") == day for e in snapshots(path)):
        return None                                            # idempotent: one snapshot per day
    entry = {"day": day, **vals}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        fh.write(json.dumps(entry) + "\n")
        fh.flush()
    return entry


def prior_within(window_days: float, *, path: str = DEFAULT_PATH, min_days: float = 5.0,
                 now: Optional[float] = None) -> Optional[dict]:
    """The snapshot whose age is CLOSEST to ``window_days`` ago (among those at least ``min_days``
    old) — the 'prior' the bear-steepener compares against. None when history is too thin (younger
    than ``min_days``), so the monitor honestly reports 'not assessable' instead of a fake window."""
    eligible = []
    for e in snapshots(path):
        age = _age_days(str(e.get("day") or ""), now)
        if age is not None and age >= min_days:
            eligible.append((abs(age - window_days), e))
    if not eligible:
        return None
    eligible.sort(key=lambda t: t[0])
    return eligible[0][1]
