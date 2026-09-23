"""
Bond artificial-prop monitor — the TLT tactical trigger.

The TLT put setup is "fade the artificial bid": intervention episodes (Fed/Treasury
buybacks, YCC chatter, BoJ operations, coordinated central-bank bond support) push TLT
up and re-cheapen puts. This monitor NAMES the episodes so the trigger is an observed
event, not a feeling. Manual/news-driven input (like CFTC): set
``config['bond_intervention'] = {'active': True, 'note': '...'}`` when an episode is
underway; clear it when the bid fades.

COHERENCE NOTE (stated on the board card): intervention episodes SUPPRESS real yields —
the opposite of the PM book's shared kill (TIPS real yields breaking higher). An active
prop episode is TLT-tactical-bullish and PM-thesis-neutral/supportive, never a kill
signal. Do not wire this monitor to any PM invalidation line.

Pure + dependency-free. No eval().
"""
from __future__ import annotations

__all__ = ["assess"]


def assess(*, active: bool = False, note: str = "") -> dict:
    """Assess the bond-prop episode state. ``active``: an artificial bid is currently
    in bonds. ``note``: what the episode is — human-read context, never scored."""
    act = bool(active)
    read = ("INTERVENTION EPISODE — artificial bid in bonds; TLT put setup sharpening"
            if act else "dormant — no artificial bid")
    flag = ({"id": "bond_prop", "active": True,
             "note": note or "intervention episode active"} if act else None)
    return {"active": act, "read": read, "note": note,
            "flags": [flag] if flag else [],
            "coherence": ("prop suppresses real yields — PM-kill opposite; "
                          "tactical TLT fade only, never a PM invalidation")}
