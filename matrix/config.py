"""
Matrix renderer config — palette, colour-state thresholds, device profile, intervals (Forge-Matrix M3+).

Thresholds-from-engine, not code (spec §0): the colour-state cutoffs and the MRI stress threshold are
DEFAULTS here, intended to be overlaid from the engine's proposal-gated config (v5_config.json via
dynamic_config) by the orchestrator — never re-decided in the draw code. The renderer reads these; it
does not invent them. Kept as a tiny stdlib module so screens import it without pulling PIL/requests.
"""
from __future__ import annotations

import os

# RGB palette (the glass is RGB; the encoder packs to rgb565 at the boundary).
PALETTE = {
    "bg": (0, 0, 0),            # pure black: max LED contrast, true-off pixels
    "text": (255, 255, 255),    # bright white for legibility
    "dim": (140, 146, 162),
    # colour states (calm/elevated/stress -> green/amber/red), saturated for an RGB LED panel.
    "calm": (0, 240, 90),
    "elevated": (255, 176, 0),
    "stress": (255, 45, 45),
    # regime tilt (mirrors the states)
    "risk_on": (0, 240, 90),
    "risk_off": (255, 45, 45),
    "balanced": (255, 176, 0),
    # accents (barbell screens were cut; kept for any future use)
    "spear": (150, 90, 255),
    "ballast": (0, 170, 220),
    "accent": (255, 210, 60),
}

# MRI stress overlay cutoff for the regime band. Default mirrors the engine's posture MRI_RISK_OFF
# (regime_posture.MRI_RISK_OFF = 60). Overlay from engine config when wired.
MRI_STRESS_THRESHOLD = 60.0

# Margin-of-safety / asymmetry colour cutoffs (DEFAULTS; tunable, intended to be engine/config-owned).
# ρ payoff ratio: >= good is green; >= 1.0 amber; < 1.0 red (downside > upside). φ REP-floor coverage:
# >= good is green (well above the stressed floor); >= 1.0 amber; < 1.0 red (price below floor).
RHO_GOOD = 2.0
PHI_GOOD = 1.3

# Stress screen: which engine macro-tape signals to show, in order (operator-chosen "Balanced" set).
# The engine owns the values + colour states; this only selects/orders which appear on the 64px panel.
# Labels match macro_tape.signals[].label exactly (note the en-dash in the curve label).
STRESS_SHOW = ["Real Yield", "VIX", "HY Spread", "Gold/Silver", "30Y–10Y"]

# Device profile / orchestrator (used from M5; here so it lives in one place).
DEVICE_HOST = os.environ.get("CEX_MATRIX_HOST", "esp32s3-cb15f8.home.local")   # prefer mDNS hostname (IP may change)
POLL_INTERVAL_S = 5.0                        # /state poll cadence (ambient)
MIN_SAVE_INTERVAL_S = 30.0                   # flash-wear guard for Route A /api/save (M8)
CYCLE_INTERVAL_S = float(os.environ.get("CEX_MATRIX_CYCLE", "15"))          # dwell per board / detail screen
AMBIENT_DWELL_S = float(os.environ.get("CEX_MATRIX_AMBIENT_DWELL", "45"))   # the home/ambient page dwells longer                        # screen rotation cadence (M5)

# Crawl (M4) tuning — speed is the per-frame dwell (the scroll step is capped by the payload budget,
# so delay is the readable-speed lever); scale is the tape glyph magnification (2x = a bold ticker).
CRAWL_DELAY_MS = float(os.environ.get("CEX_MATRIX_CRAWL_MS", "550"))   # per-step scroll delay (env-tunable; slower)
CRAWL_SCALE = 2

# Ambient cockpit (build_ambient): the static macro dashboard cells (top), as macro_tape labels — MRI is
# already in the band. Plus the bottom-crawl glyph scale. USD = the engine's dollar signal (DXY/Gold).
AMBIENT_MACRO = ["VIX", "DXY", "Real Yield", "HY Spread", "Gold/Silver", "30Y–10Y"]  # 2x3 grid (6 cells)
AMBIENT_CRAWL_SCALE = 2

# Orchestrator (M5) — matches the engine's own env (CEX_ENGINE_HOST/PORT, default 127.0.0.1:8000).
ENGINE_URL = os.environ.get("CEX_ENGINE_URL") or \
    f"http://{os.environ.get('CEX_ENGINE_HOST', '127.0.0.1')}:{os.environ.get('CEX_ENGINE_PORT', '8000')}"
# ambient cockpit + the boards, then 'detail' = the per-name mode (one full card per holding+bench).
# Set ROTATION = ["detail"] for a pure detail mode (just walk each company); the button can toggle.
ROTATION = ["ambient", "conviction_board", "asymmetry", "stress", "detail"]
STATIC_FRAME_MS = 1000          # single-frame display delay for static screens
MIN_UPLOAD_INTERVAL_S = 6.0     # flash-wear guard for /upload (anim.bin)
LOOP_MAX_FRAMES = 24            # self-loop mode: max screens packed into one anim.bin (upload-size guard)


def state_color(state: str):
    """calm|elevated|stress -> RGB (default to amber/elevated for anything unknown)."""
    return PALETTE.get(state, PALETTE["elevated"])


def tilt_color(net_tilt: str):
    """RISK-ON|RISK-OFF|BALANCED -> RGB."""
    key = str(net_tilt or "BALANCED").strip().lower().replace("-", "_")
    return PALETTE.get(key, PALETTE["balanced"])
