"""Pure, streamlit-free projection + presentation helpers for the legacy Streamlit dashboard.

Invariant 1 — ENGINE is the single source of math truth: the dashboard must **project** the
engine's published verdicts, never re-derive them. These helpers map an engine directive *string*
to a display colour and read book identity from config; they decide no rating, directive, or price.
Kept out of ``dashboard.py`` (which imports streamlit at module load) so the logic is unit-testable
on its own.
"""
from __future__ import annotations

from typing import Any, Optional

# Display colours — presentation only, keyed off the ENGINE directive text (never recomputed here).
_DIR_GREEN, _DIR_ORANGE, _DIR_RED, _DIR_GREY = "#00E676", "#FF9800", "#FF5252", "#888888"


def directive_color(directive: Optional[str]) -> str:
    """Map an ENGINE directive string to a display colour by its text. NO directive is decided here
    (invariant 1): the engine owns ACCUMULATE / TRIM / HOLD; the dashboard only paints what it is
    told. ``TRIM`` is checked before ``ACCUMULATE`` so a mixed "HOLD / TRIM" reads cautionary."""
    d = (directive or "").upper()
    if not d:
        return _DIR_GREY
    if "AVOID" in d or "DE-RISK" in d or "STAND ASIDE" in d:
        return _DIR_RED
    if "TRIM" in d:
        return _DIR_ORANGE
    if "ACCUMULATE" in d:
        return _DIR_GREEN
    return _DIR_GREY                          # HOLD / MONITOR / WATCH / CORE / unknown — neutral


def directive_bg(directive: Optional[str]) -> str:
    """The faint row tint that matches :func:`directive_color` (transparent for the neutral case)."""
    return {_DIR_GREEN: "rgba(0,230,118,0.06)", _DIR_ORANGE: "rgba(255,152,0,0.06)",
            _DIR_RED: "rgba(255,82,82,0.06)"}.get(directive_color(directive), "transparent")


def directive_by_ticker(conviction_mode: Optional[dict]) -> dict:
    """The engine's per-name directive map projected from a published ``conviction_mode`` block.
    Empty when the block is absent — grounded-or-silent, never a fabricated default."""
    out: dict[str, Any] = {}
    for b in (conviction_mode or {}).get("baskets") or []:
        if isinstance(b, dict) and b.get("ticker"):
            out[b["ticker"]] = b.get("directive")
    return out


def spear_ticker(config: Optional[dict]) -> Optional[str]:
    """The single silver-spear name, read from config (``portfolio_metadata[t].thesis_slot``) rather
    than a hardcoded ``"AGA.V"`` literal — so the book can be re-slotted in config alone."""
    meta = (config or {}).get("portfolio_metadata", {}) or {}
    for tkr, m in meta.items():
        if isinstance(m, dict) and m.get("thesis_slot") == "silver-spear":
            return tkr
    return None


def node_price(state: Optional[dict], ticker: str) -> Optional[float]:
    """The live per-name price from the engine ``state['nodes']``, or ``None`` when the feed is
    missing/partial. Never a stale literal — a missing price must read as unknown, not as a number."""
    if not state:
        return None
    node = (state.get("nodes") or {}).get(ticker)
    px = node.get("price") if isinstance(node, dict) else None
    return float(px) if isinstance(px, (int, float)) and not isinstance(px, bool) else None


def node_shares(state: Optional[dict], ticker: str) -> Optional[float]:
    """The live per-name share count from the engine ``state['nodes']``, or ``None`` when absent."""
    if not state:
        return None
    node = (state.get("nodes") or {}).get(ticker)
    sh = node.get("shares") if isinstance(node, dict) else None
    return float(sh) if isinstance(sh, (int, float)) and not isinstance(sh, bool) else None


def fmt_or_dash(x: Any, spec: str = "") -> str:
    """Format a number, or render an em-dash for a missing value — grounded-or-silent. Never coerces
    ``None``/strings to ``0`` (that would fabricate data the engine did not supply)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return "—"
    try:
        return format(x, spec) if spec else str(x)
    except (ValueError, TypeError):
        return "—"
