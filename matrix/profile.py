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


def ensure_owned(host: str, *, reader: Optional[Callable[[str], dict]] = None,
                 writer: Optional[Callable[..., str]] = None) -> dict:
    """Re-assert the claim, but ONLY if the device has drifted back to its own content.

    ``claim_device`` is a one-shot manual step (``python -m matrix --claim``). Nothing ever asked
    again. A panel that reverts — a config import, a firmware update, a factory reset, or a native
    screen re-enabled in the device's web UI — goes back to playing the stock "name + null values"
    screens while every ``/upload`` still returns 200. The export looks healthy from the host and
    the glass shows factory content: silent and total.

    This is the sentinel for that. Read the config, ``verify`` it, and re-apply the patch only when
    we no longer own the panel. Flash-wear safe BY CONSTRUCTION: a healthy device is a pure read and
    never a write, so this is safe to call on a loop.

    Returns ``{owned, reclaimed, verify, lost?, patch?, note?}``. I/O is injectable (tests pass
    stubs; defaults lazy-import ``device`` so this module imports without ``requests``).
    """
    if reader is None or writer is None:
        from . import device
        reader = reader or device.get_data
        writer = writer or device.save_config
    config = reader(host) or {}
    before = verify(config)
    if before["owns_panel"]:
        return {"owned": True, "reclaimed": False, "verify": before}

    # what we lost the panel TO — named, so the log line says which screen took the glass back
    lost = list(before["natives_on"])
    if not before["gif_on"]:
        lost.append(GIF_TOGGLE)

    patch = commodityex_patch(config)
    if not patch:
        # version-safety cuts both ways: if the firmware reports none of the keys we know, there is
        # nothing safe to write. Say so rather than inventing keys the device doesn't understand.
        return {"owned": False, "reclaimed": False, "verify": before, "lost": lost, "patch": {},
                "note": "device reports no known CommodityEx profile keys — cannot re-claim"}
    writer(host, patch)
    after = verify(reader(host) or {})
    return {"owned": after["owns_panel"], "reclaimed": True, "patch": patch,
            "verify": after, "lost": lost}
