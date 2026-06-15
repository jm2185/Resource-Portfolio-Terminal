"""
InfoMatrix device I/O (Forge-Matrix M1) — the network side of the renderer.

This is the *only* module that talks to the panel over HTTP. It is kept apart from the pure ``encoder``
so the byte-exact fixtures (and ``import matrix``) never require ``requests`` or a reachable device.
Endpoints are the CONFIRMED firmware v2.0.8 API (Appendix A).

FOOTGUNS, fenced here (spec §7):
  * ``GET /api/reboot`` hard-reboots — ``reboot()`` refuses without ``confirm=True``.
  * ``POST /api/config/import`` overwrites config AND reboots — ``import_config()`` refuses without
    ``confirm=True``.
  * ``/api/save`` takes the FULL config; whether omitted fields merge or reset is UNKNOWN, so
    ``push_lines()`` does a mandatory read-modify-write (GET /api/data -> mutate -> POST the whole object).
  * Flash wear: never loop ``/api/save`` — the orchestrator (M5/M8) enforces a min-save interval +
    change-detection. This module is the transport; the cadence guard lives upstream.
"""
from __future__ import annotations

from typing import Dict, Optional

import requests

from .encoder import encode_anim, rgb565  # noqa: F401  (re-exported for callers' convenience)

DEFAULT_TIMEOUT = 10
# Prefer the mDNS hostname (the IP may change); the orchestrator config supplies the real host.
DEFAULT_HOST = "esp32s3-cb15f8.home.local"


def _base(host: str) -> str:
    host = (host or DEFAULT_HOST).strip().rstrip("/")
    return host if host.startswith("http") else f"http://{host}"


# ---- Route B: framebuffer / GIF pipeline ---------------------------------------------------------
def upload_anim(host: str, payload: bytes, timeout: int = DEFAULT_TIMEOUT) -> str:
    """POST an encoded anim.bin to ``/upload`` (multipart, field ``file``, filename ``anim.bin``)."""
    files = {"file": ("anim.bin", payload, "application/octet-stream")}
    r = requests.post(f"{_base(host)}/upload", files=files, timeout=timeout)
    r.raise_for_status()
    return r.text


def delete_gif(host: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Clear the uploaded animation (``POST /api/delete_gif``)."""
    r = requests.post(f"{_base(host)}/api/delete_gif", timeout=timeout)
    r.raise_for_status()
    return r.text


# ---- Route A: scrolling strings (read-modify-write, mandatory) -----------------------------------
def get_data(host: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Full device config/state (``GET /api/data``)."""
    r = requests.get(f"{_base(host)}/api/data", timeout=timeout)
    r.raise_for_status()
    return r.json()


def push_lines(host: str, lines: Dict[int, str], colors: Optional[Dict[int, str]] = None,
               timeout: int = DEFAULT_TIMEOUT) -> str:
    """Read-modify-write the device config, changing ONLY msgL{1,2,3} / colL{1,2,3} / rssUrl{1,2,3}.

    Always GET the whole config, mutate the intended fields, POST the whole object back — because
    ``/api/save`` takes the full config and partial saves have undefined merge behaviour (spec §5).
    Each save writes flash; the caller must debounce + change-detect (M8).
    """
    colors = colors or {}
    cur = get_data(host, timeout=timeout)
    form = {k: ("" if v is None else v) for k, v in cur.items()}  # preserve everything
    for i in (1, 2, 3):
        form[f"msgL{i}"] = lines.get(i, "")
        form[f"rssUrl{i}"] = ""                      # text mode, not RSS
        form[f"colL{i}"] = colors.get(i, "#ffffff")
    r = requests.post(f"{_base(host)}/api/save", data=form, timeout=timeout)
    r.raise_for_status()
    return r.text


def save_config(host: str, patch: dict, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Generic read-modify-write of arbitrary config keys (e.g. clearing ``stocks``, setting ``bright``,
    neutralising native cycle durations for the CommodityEx device profile, M2). Never sends a partial."""
    cur = get_data(host, timeout=timeout)
    form = {k: ("" if v is None else v) for k, v in cur.items()}
    for k, v in (patch or {}).items():
        form[k] = "" if v is None else v
    r = requests.post(f"{_base(host)}/api/save", data=form, timeout=timeout)
    r.raise_for_status()
    return r.text


# ---- Config backup / restore ---------------------------------------------------------------------
def export_config(host: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """Download the safe backup snapshot (``GET /api/config/export``). Save this as the factory restore
    point before claiming the device (M2)."""
    r = requests.get(f"{_base(host)}/api/config/export", timeout=timeout)
    r.raise_for_status()
    return r.content


def import_config(host: str, config_bytes: bytes, *, confirm: bool = False,
                  timeout: int = DEFAULT_TIMEOUT) -> str:
    """Restore a config (``POST /api/config/import``). OVERWRITES config and REBOOTS — refuses without
    ``confirm=True``."""
    if not confirm:
        raise RuntimeError("import_config refused: /api/config/import overwrites config AND reboots — "
                           "pass confirm=True to proceed")
    files = {"config": ("config.json", config_bytes, "application/json")}
    r = requests.post(f"{_base(host)}/api/config/import", files=files, timeout=timeout)
    r.raise_for_status()
    return r.text


def reboot(host: str, *, confirm: bool = False, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Hard reboot (``GET /api/reboot``). The endpoint is a GET footgun — a stray fetch reboots the
    device — so this refuses without ``confirm=True``."""
    if not confirm:
        raise RuntimeError("reboot refused: /api/reboot is a GET footgun — pass confirm=True to reboot")
    r = requests.get(f"{_base(host)}/api/reboot", timeout=timeout)
    r.raise_for_status()
    return r.text
