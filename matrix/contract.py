"""
MatrixState — the frozen boundary between the live engine and the InfoMatrix renderer (Forge-Matrix M0).

This is the *only* thing the renderer consumes. It is import-light and free of engine internals: the
adapter (``adapter.build_matrix_state``) maps the engine's published ``/state`` onto these dataclasses,
and every screen renderer reads MatrixState — never the engine, never the raw pillars. Same discipline
as the Sentinel's ``STATE_FIELDS.md`` contract: *if a number can come from the engine, it comes from the
engine; a missing field degrades to None, it is never fabricated in the renderer.*

Regime representation (operator decision): we carry the engine's RAW regime values rather than forcing a
single literal. ``net_tilt`` is the engine's own three-valued macro tilt (RISK-ON / RISK-OFF / BALANCED)
and ``mri`` is the raw Macro Regime Index. The band renderer colours from ``net_tilt`` and applies a
"stress" overlay when ``mri`` crosses an engine/config-owned threshold (NOT hardcoded in the renderer —
the cutoff lives in the matrix config block, the same way colour cutoffs are proposal-gated config). This
keeps the engine's BALANCED distinction, which a 3-value risk_on/risk_off/stress enum would have lost.

Pure stdlib, fully testable. Frozen so a built MatrixState can be hashed, compared (change-detection for
the flash-wear guard, M8) and safely shared across the orchestrator's layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

# Per-signal colour state. Mapped by the adapter from the engine's own per-signal ``bias`` — the
# renderer never decides what counts as stress. (risk_on -> calm/green tailwind, neutral -> elevated/
# amber, risk_off -> stress/red headwind.) See adapter._bias_to_state.
StressState = Literal["calm", "elevated", "stress"]


@dataclass(frozen=True)
class WatchItem:
    """One row of the watchlist crawl. Ordered by the engine (conviction/weight); the renderer only
    colours and draws ▲▼ from the sign of ``change_pct``."""
    symbol: str                          # display symbol, abbreviated for 64px (e.g. "AGA", "GROY")
    last: Optional[float] = None         # nodes.<TK>.price (CAD); None if the engine has no price
    change_pct: Optional[float] = None   # GAP: not surfaced per-name in /state — stubbed None at M0


@dataclass(frozen=True)
class StressIndex:
    """One macro/stress reading from the engine's ``macro_tape.signals[]``. ``state`` is engine-bucketed
    (see StressState); the renderer maps state -> colour and never re-thresholds the value."""
    label: str                           # macro_tape.signals[].label ("VIX", "HY Spread", ...)
    value: Optional[float] = None        # macro_tape.signals[].value
    state: StressState = "elevated"      # mapped from macro_tape.signals[].bias
    read: Optional[str] = None           # engine's human read ("Elevated fear") — for a detail screen


@dataclass(frozen=True)
class CatalystRef:
    """The soonest upcoming catalyst. Engine-owned label + whole days until the window opens."""
    label: str                           # "AGA DRILL"
    days: int                            # whole days until


@dataclass(frozen=True)
class MatrixState:
    """The frozen render contract. All fields default so a safe empty/degraded frame is ``MatrixState()``
    (used by the orchestrator when the engine feed drops — rendered with the stale marker)."""
    # --- regime band (raw engine values; operator chose: carry net_tilt + MRI) ---
    net_tilt: str = "BALANCED"           # macro_tape.net_tilt: "RISK-ON" | "RISK-OFF" | "BALANCED"
    mri: Optional[float] = None          # root .mri — raw Macro Regime Index (pivot 50; >60 stress)
    regime_label: str = ""               # posture.label: "SPEAR EXPLOIT" | "BALANCED" | "DEFENSIVE"
    posture_cap: Optional[float] = None  # posture.cap — book-level size dial (header tint, M3)
    # --- complexes (engine-ordered) ---
    stress: Tuple[StressIndex, ...] = ()      # ordered by importance, engine-decided
    watchlist: Tuple[WatchItem, ...] = ()     # ordered by conviction/weight, engine-decided
    # --- barbell split (derived from live node market value: price*shares by role) ---
    spear_pct: Optional[float] = None
    ballast_pct: Optional[float] = None
    # --- next catalyst (injected: GAP in /state) ---
    next_catalyst: Optional[CatalystRef] = None
    # --- provenance ---
    stale: bool = False                  # set by the adapter/orchestrator if the engine feed is late
    generated_at: float = 0.0            # epoch seconds the frame was built
