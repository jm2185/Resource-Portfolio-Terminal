"""
Matrix renderer config — palette, colour-state thresholds, device profile, intervals (Forge-Matrix M3+).

Thresholds-from-engine, not code (spec §0): the colour-state cutoffs and the MRI stress threshold are
DEFAULTS here, intended to be overlaid from the engine's proposal-gated config (v5_config.json via
dynamic_config) by the orchestrator — never re-decided in the draw code. The renderer reads these; it
does not invent them. Kept as a tiny stdlib module so screens import it without pulling PIL/requests.
"""
from __future__ import annotations

# RGB palette (the glass is RGB; the encoder packs to rgb565 at the boundary).
PALETTE = {
    "bg": (6, 8, 12),
    "text": (235, 235, 245),
    "dim": (120, 125, 140),
    # colour states (calm/elevated/stress -> green/amber/red) — engine-bucketed, renderer colours.
    "calm": (0, 230, 118),
    "elevated": (255, 183, 77),
    "stress": (255, 82, 82),
    # regime tilt
    "risk_on": (0, 230, 118),
    "risk_off": (255, 82, 82),
    "balanced": (255, 183, 77),
    # barbell sleeves + catalyst accent
    "spear": (124, 77, 255),
    "ballast": (0, 150, 200),
    "accent": (255, 213, 79),
}

# MRI stress overlay cutoff for the regime band. Default mirrors the engine's posture MRI_RISK_OFF
# (regime_posture.MRI_RISK_OFF = 60). Overlay from engine config when wired.
MRI_STRESS_THRESHOLD = 60.0

# Margin-of-safety / asymmetry colour cutoffs (DEFAULTS; tunable, intended to be engine/config-owned).
# ρ payoff ratio: >= good is green; >= 1.0 amber; < 1.0 red (downside > upside). φ REP-floor coverage:
# >= good is green (well above the stressed floor); >= 1.0 amber; < 1.0 red (price below floor).
RHO_GOOD = 2.0
PHI_GOOD = 1.3

# Device profile / orchestrator (used from M5; here so it lives in one place).
DEVICE_HOST = "esp32s3-cb15f8.home.local"   # prefer mDNS hostname (IP may change)
POLL_INTERVAL_S = 5.0                        # /state poll cadence (ambient)
MIN_SAVE_INTERVAL_S = 30.0                   # flash-wear guard for Route A /api/save (M8)
CYCLE_INTERVAL_S = 8.0                        # screen rotation cadence (M5)


def state_color(state: str):
    """calm|elevated|stress -> RGB (default to amber/elevated for anything unknown)."""
    return PALETTE.get(state, PALETTE["elevated"])


def tilt_color(net_tilt: str):
    """RISK-ON|RISK-OFF|BALANCED -> RGB."""
    key = str(net_tilt or "BALANCED").strip().lower().replace("-", "_")
    return PALETTE.get(key, PALETTE["balanced"])
