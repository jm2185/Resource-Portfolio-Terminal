"""
Macro-signal snapshot — resolve the shared regime inputs ONCE per engine cycle (Arch 5).

The four regime lenses are correctly layered pure modules (regime_lens / commodity_regime /
inflation_regime / regime_posture take their inputs as arguments), but the ENGINE's call sites each
re-resolved the same macro signals from ``terminal_state`` independently — the commodity-tailwind
plumbing and the posture dial both re-read REAL_YIELD / DXY_MOMENTUM / the macro-tape tilt with
their own copy of the metric-lookup closure. Same sources, duplicated resolution code, and a
standing risk of the lenses quietly disagreeing on inputs.

This module is the single resolver. ``snapshot(terminal_state)`` reads the SAME sources with the
SAME precedence the call sites used (the ``metrics`` dict's ``{"value": …}`` unwrap with key
aliases, the macro-tape vote counts / net tilt) and returns a plain dict of RAW values — a signal
that isn't populated stays ``None``. Per-consumer defaults (the tailwind's ``real_yield=2.0`` /
``gsr=80.0`` neutral fallbacks vs the posture's ``None`` = "driver absent") deliberately stay AT
THE CONSUMER: they differ by design, and baking one choice in here would silently change the other.

Pure + dependency-free (stdlib only); graceful on thin/absent state; no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["metric_value", "snapshot"]


def metric_value(metrics: Optional[dict], *keys: str, default: Any = None) -> Any:
    """First non-None value in ``metrics`` under any of ``keys`` — unwrapping the engine's
    ``{"value": x, "status": …}`` metric cells — else ``default``. The one shared copy of the
    lookup closure that was previously redefined at each engine call site."""
    m = metrics or {}
    for k in keys:
        v = m.get(k)
        v = v.get("value") if isinstance(v, dict) else v
        if v is not None:
            return v
    return default


def snapshot(terminal_state: Optional[dict]) -> dict:
    """The shared macro signals, resolved once from ``terminal_state``. RAW values (None when a
    signal isn't populated) — consumers apply their own documented defaults.

    Keys: ``real_yield`` · ``gsr`` · ``uranium_term`` · ``dxy_mom`` (metrics, alias-aware) ·
    ``risk_on`` (signed tape vote ratio ∈ [-1,1], 0.0 on an empty tape) · ``net_tilt`` (the tape's
    label, None until the tape exists)."""
    ts = terminal_state or {}
    m = ts.get("metrics", {}) or {}
    tape = ts.get("macro_tape", {}) or {}
    on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
    risk_on = ((on - off) / max(1, on + off)) if (on or off) else 0.0
    return {
        "real_yield": metric_value(m, "REAL_YIELD", "Real_Yield"),
        "gsr": metric_value(m, "GSR"),
        "uranium_term": metric_value(m, "URANIUM_TERM", "Uranium_Term"),
        "dxy_mom": metric_value(m, "DXY_MOMENTUM"),
        "risk_on": risk_on,
        "net_tilt": tape.get("net_tilt"),
    }
