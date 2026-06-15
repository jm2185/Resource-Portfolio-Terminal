"""
M2 — claim the device for CommodityEx.

Make OUR uploaded animation own the panel and stop the native "name + null values" screens (those came
from the device's TwelveData feed). The profile is a SAFE read-modify-write that only touches keys the
device actually reports in /api/data, so it's version-tolerant across firmware 2.0.x / 2.1.x.

Order of operations (do the on-glass backup FIRST):
  1. Export a config backup  — GET /api/config/export  (your restore point; the operator already has it).
  2. Set Matrix Size = 128x64 in the web UI (done). Our anim.bin header is [128][64] regardless, so it's
     authoritative — there's no separate size key to set here.
  3. claim_device(host, confirm=True) — dGif ON, native screens OFF, stocks cleared.

``claim_device`` refuses without ``confirm=True``. No API key is needed once our anim owns the panel.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

GIF_TOGGLE = "dGif"                           # show the uploaded animation (our content)
# native content screens to disable so OUR anim owns the panel (msg/text left off too; enable later if
# you want native scrolling one-liners via /api/save).
NATIVE_SCREEN_TOGGLES = ("dStock", "dWeath", "dCom", "dCrkt", "dMsg",
                         "dMlb", "dNba", "dNfl", "dNhl")
TRUE, FALSE = "true", "false"                 # firmware checkbox serialization (el.checked -> "true"/"false")


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "on", "yes")


def commodityex_patch(config: dict) -> Dict[str, str]:
    """The CommodityEx profile patch: dGif on, native screens off, stocks cleared. ONLY includes keys
    already present in ``config`` — never invents keys the firmware doesn't know (version-safe)."""
    patch: Dict[str, str] = {}
    if GIF_TOGGLE in config:
        patch[GIF_TOGGLE] = TRUE
    for k in NATIVE_SCREEN_TOGGLES:
        if k in config:
            patch[k] = FALSE
    if "stocks" in config:
        patch["stocks"] = ""                  # stop the TwelveData fetch entirely
    return patch


def verify(config: dict) -> dict:
    """Post-claim sanity report: is the device set up for CommodityEx to own the panel?"""
    natives_on = [k for k in NATIVE_SCREEN_TOGGLES if k in config and _truthy(config[k])]
    return {
        "gif_on": _truthy(config.get(GIF_TOGGLE)),
        "natives_on": natives_on,
        "stocks_cleared": not config.get("stocks"),
        "owns_panel": _truthy(config.get(GIF_TOGGLE)) and not natives_on,
    }


def claim_device(host: str, *, confirm: bool = False,
                 reader: Optional[Callable[[str], dict]] = None,
                 writer: Optional[Callable[..., str]] = None) -> dict:
    """Read config -> apply the CommodityEx profile (read-modify-write, preserving every other key) ->
    verify. Refuses without ``confirm=True``. EXPORT A BACKUP FIRST (GET /api/config/export).

    I/O is injectable for tests; defaults use ``device.get_data`` / ``device.save_config`` (lazy-imported
    so this module stays importable without ``requests``)."""
    if reader is None or writer is None:
        from . import device
        reader = reader or device.get_data
        writer = writer or device.save_config
    config = reader(host)
    patch = commodityex_patch(config)
    if not confirm:
        return {"applied": False, "patch": patch,
                "note": "dry run — back up config (GET /api/config/export) then pass confirm=True"}
    writer(host, patch)
    return {"applied": True, "patch": patch, "verify": verify(reader(host))}
