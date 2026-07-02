"""
monitor_protocol.py — the shared protocol layer for the SENTINEL / monitor modules.

Six monitors speak the same protocol (pure ``assess`` → ``{flags, events}`` → a ``select_fresh``
dedup → the engine ``_fire_*`` auto-pin): divergence_monitor · correlation_monitor ·
conventional_sentinel · productivity_monitor · oil_supply_monitor · rates_monitor. The scaffolding
they share lives HERE, once — each module keeps its public API (its own ``select_fresh`` /
``*_tooltip`` / config semantics) as a thin wrapper over these helpers, so the engine and the tests
never see the seam.

What is shared (and what deliberately is NOT):
  * ``num``            — the tolerant float coercion (NaN/inf → None) every monitor uses.
  * ``clamp``          — the [lo, hi] clamp the composite-score monitors use.
  * ``tooltip``        — the glossary-entry → multi-line "?" tooltip flattener (what/scale/
                         influence/edge, mirroring ``asymmetry_rating.tooltip_text``).
  * ``merged_config``  — defaults + a named config block, merged one level deep (a dict value
                         merges over a dict default instead of clobbering it). A superset of the
                         flat merge some monitors used: identical behavior when no default is a dict.
  * ``select_fresh``   — the dedup SKELETON (one pin per event per day, keyed on a per-monitor
                         state). The per-monitor SEMANTICS — which field names the ticker, what
                         state defines "the same event", and when a same-day repeat is a NEW event
                         (a sign flip, a worsened correlation bucket, a new zone) — stay in each
                         module as small ``state_fn`` / ``is_repeat`` callables, because they
                         genuinely differ; only the loop is common.

The flag/event payloads themselves stay as inline literals in each monitor: their shapes vary by
design (``corr`` / ``zone`` / ``drift`` / ``ts`` extras) and no shaping helper ever existed to dedup.

Pure + dependency-free (stdlib only); never raises on thin input; no eval().
"""
from __future__ import annotations

from typing import Any, Callable, Optional

__all__ = ["num", "clamp", "tooltip", "merged_config", "select_fresh"]

#: the canonical glossary-entry field order + labels for the "?" tooltip render.
_TOOLTIP_ORDER: tuple = ("what", "scale", "influence", "edge")
_TOOLTIP_LABELS: dict[str, str] = {"what": "", "scale": "Good vs bad: ",
                                   "influence": "Drives: ", "edge": "Note: "}


def num(x: Any) -> Optional[float]:
    """Tolerant float coercion: a finite float, or None (NaN, ±inf, garbage, None all → None)."""
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``x`` into [lo, hi]."""
    return lo if x < lo else hi if x > hi else x


def tooltip(glossary: Optional[dict], key: str) -> str:
    """Flatten one glossary entry ``{what, scale, influence, edge}`` to the multi-line "?" tooltip
    string (mirrors ``asymmetry_rating.tooltip_text``). Unknown key → '' (graceful)."""
    e = (glossary or {}).get(key)
    if not e:
        return ""
    return "\n".join(_TOOLTIP_LABELS[k] + e[k] for k in _TOOLTIP_ORDER if e.get(k))


def merged_config(defaults: dict, config: Optional[dict], block_key: str) -> dict:
    """The monitors' config plumbing: copy ``defaults``, then overlay the caller's ``config[block_key]``
    block (or, when no such block exists, ``config`` itself — so a bare ``{"z_min": 3}`` works in a
    unit test while the engine passes its full v5 config). Dict values merge ONE level deep over a
    dict default (weights/bands blocks tune per-key); everything else replaces. Pure — never mutates
    ``defaults`` or ``config``."""
    cfg = dict(defaults or {})
    block = (config or {}).get(block_key, config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def select_fresh(flagged: Any, fired: Optional[dict] = None, *, today: str = "",
                 ticker_field: str = "ticker",
                 state_fn: Optional[Callable[[dict], dict]] = None,
                 is_repeat: Optional[Callable[[dict, dict], bool]] = None) -> tuple:
    """The shared dedup skeleton: pin ONCE per event per day, not every cycle.

    ``fired`` is the engine's rolling ledger ``{tk: {date, …state}}``. For each flag: read the ticker
    from ``ticker_field``, compute its dedup STATE via ``state_fn(flag) -> dict`` (e.g. the residual
    sign, the correlation bucket, the zone key), and SKIP it only when this ticker already fired
    ``today`` AND ``is_repeat(prev_ledger_entry, state)`` says nothing new happened. A fresh flag is
    kept and its ledger entry becomes ``{"date": today, **state}``. A multi-session signal re-fires
    the next day BY DESIGN (the follow-through is the information). Returns ``(fresh, fired_next)``;
    never mutates ``fired``. Pure."""
    state_fn = state_fn or (lambda r: {})
    is_repeat = is_repeat or (lambda prev, state: True)
    fired_next = dict(fired or {})
    fresh: list = []
    for r in (flagged or []):
        tk = str((r or {}).get(ticker_field) or "").strip()
        if not tk:
            continue
        state = state_fn(r)
        prev = fired_next.get(tk) or {}
        if prev.get("date") == today and is_repeat(prev, state):
            continue                                      # same event already pinned today → skip
        fresh.append(r)
        fired_next[tk] = {"date": today, **state}
    return fresh, fired_next
