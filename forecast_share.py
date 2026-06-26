"""
forecast_share.py — the Lynch guardrail: how much of a rating is a MACRO FORECAST vs the business.

Peter Lynch's objection to macro isn't "ignore it" — it's "don't let a *forecast* (what the economy
will do, which nobody calls reliably) masquerade as knowledge about the *business* (is the deposit
real, can it permit, will it run out of cash)." This module makes that split VISIBLE, per name, as one
number.

It MEASURES, it never SIZES — the same law as the concentration/coverage book_factor. It does not change
a single rating; it tells you how much of the rating you should *trust as a business read* versus *hold
loosely as a regime bet*. The dial stays the operator's.

The measure is the SHADOW RATING — "what's left when you turn the forecast off":
  * full      = the rating as-is.
  * macro_off = the SAME rating recomputed with the forecast inputs neutralized (MRI→50, regime_alpha→0,
                commodity_regime→0 ⇒ the Tailwind pillar collapses to its neutral 5.0).
  * the GAP between them is the forecast's footprint on the rating. abs(gap)/full = forecast_share.
Computed through the real (non-linear, standout-lifted) rating function, so it captures the true effect,
not a linear approximation.

CONTEXT-AWARE by archetype — the whole point. A high forecast-share means OPPOSITE things by name:
  * a convex spear (option_convexity) or a passive vehicle (pure_macro_delta) is a regime bet BY DESIGN —
    a high share is EXPECTED and fine (info). The silver spear IS a silver-cycle bet; that's the thesis.
  * a BALLAST royalty/holdco is supposed to be business- and floor-driven. A high share is the ALARM:
    your "ballast" is quietly riding the forecast, not the business — it has stopped behaving as ballast
    (warn). That hidden case — diversification that is really three more ways to bet the same macro — is
    exactly what this catches, and what an eyeball misses.

Pure + dependency-free (stdlib only); a thin consumer (build_conviction_state) does the shadow re-rate
and hands the two scores here. Never raises into the rating path.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_FORECAST_SHARE_CONFIG", "forecast_share_read"]

DEFAULT_FORECAST_SHARE_CONFIG: dict[str, Any] = {
    # forecast footprint above this fraction of the rating gets flagged (a ballast warn / a spear info)
    "flag_threshold": 0.30,
    # archetypes for which a macro bet IS the thesis — a high share is by-design, not an alarm
    "forecast_native_archetypes": ["option_convexity", "pure_macro_delta"],
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_FORECAST_SHARE_CONFIG)
    block = (config or {}).get("forecast_share", {}) if config else {}
    if isinstance(block, dict):
        cfg.update(block)
    return cfg


def forecast_share_read(full_score: Any, macro_off_score: Any, *, archetype: Any = None,
                        posture_factor: Any = None, config: Optional[dict] = None) -> dict:
    """Partition a rating into FORECAST vs BUSINESS+PROTECTION, from the full rating and its macro-off
    shadow (see module docstring). Returns the forecast_share (0–1), the direction the forecast is
    pushing (``tailwind`` = inflating · ``drag`` = suppressing · ``neutral``), the ``business_rating``
    (what the name rates on its own merits with the regime neutral), a context-aware ``flag``, and a
    plain-language ``read``. ``posture_factor`` (the book-level size cap, e.g. 0.94) is a SEPARATE
    forecast dial on *sizing* — surfaced alongside, never folded into the rating share. Pure; on bad
    inputs returns ``available: False`` (the consumer simply omits the meter)."""
    cfg = _cfg(config)
    full = _num(full_score)
    off = _num(macro_off_score)
    if full is None or off is None or full <= 0:
        return {"available": False, "read": "forecast-share n/a (need both the rating and its macro-off shadow)"}

    swing = full - off                                    # +ve: forecast LIFTS the rating; −ve: forecast DRAGS it
    share = abs(swing) / full
    if swing > 0.01:
        direction = "tailwind"
    elif swing < -0.01:
        direction = "drag"
    else:
        direction = "neutral"

    arch = str(archetype or "")
    native = arch in (cfg.get("forecast_native_archetypes") or [])
    threshold = _num(cfg.get("flag_threshold")) or 0.30
    flagged = share >= threshold
    pct = round(share * 100)

    if native:
        # a regime bet is the thesis here — name the bet, don't alarm.
        level = "info"
        read = (f"{pct}% of this rating is the regime — BY DESIGN for a {arch} ({'the silver/commodity cycle' if arch=='option_convexity' else 'the commodity'} IS the thesis). "
                f"Size it as a macro bet, not a business one.")
    elif flagged and direction == "drag":
        level = "warn"
        read = (f"{pct}% of this BALLAST rating is a macro FORECAST suppressing it — not the business. "
                f"The floor/quality may disagree with the regime call; check the name, not the knobs.")
    elif flagged and direction == "tailwind":
        level = "warn"
        read = (f"{pct}% of this BALLAST rating is a macro FORECAST lifting it — you're being paid by the "
                f"regime, not the business. Hold that part loosely; it isn't ballast behaviour.")
    else:
        level = "ok"
        read = f"{pct}% forecast footprint — the rating stands on the business + the floor, not a regime call."

    out: dict = {
        "available": True,
        "forecast_share": round(share, 3),
        "direction": direction,
        "swing": round(swing, 3),
        "full_rating": round(full, 2),
        "business_rating": round(off, 2),          # the rating with the regime neutralized
        "forecast_native": native,
        "flag": {"level": level, "flagged": bool(flagged and not native)},
        "read": read,
    }
    pf = _num(posture_factor)
    if pf is not None and abs(pf - 1.0) > 1e-6:
        out["posture_size_cap"] = round(pf, 3)      # a SEPARATE forecast dial — on sizing, not the rating
    return out
