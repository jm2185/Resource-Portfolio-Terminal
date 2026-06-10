"""
Task supervision — surfacing background-worker death (audit A1.9, second half).

The engine fires its workers (prices / macro / CFTC / comps, plus the eval loop and the websocket
broadcaster) as bare ``asyncio.create_task`` calls. A worker that crashes — or simply *returns*
from its supposed-to-be-infinite loop — dies silently: the loop keeps serving stale data with no
health signal, which violates grounded-or-silent at the process level.

``create_supervised`` wraps a worker coroutine so that:
  * a liveness record is kept in a caller-supplied ``health`` dict ({name: {alive, started_at,
    error?, died_at?}}) — the engine parks this at ``terminal_state["worker_health"]`` so every
    /state reader sees it;
  * an unexpected exit (exception OR return — worker loops must never return) marks the record
    dead and fires ``on_death(name, error)`` so the engine can flip its status to degraded;
  * a *cancellation* (clean shutdown) is recorded as stopped, never as a death.

Surfacing only, deliberately: no auto-restart — a crash-looping worker silently restarting is
exactly the failure mode this exists to make visible. The operator restarts the engine.

Pure stdlib/asyncio; unit-testable without the engine.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def create_supervised(name: str, coro: Awaitable, *, health: dict,
                      on_death: Optional[Callable[[str, str], None]] = None) -> "asyncio.Task":
    """Schedule ``coro`` as a named task whose death is RECORDED, never silent.

    ``health[name]`` is written in place (the caller owns the dict — the engine parks it in
    terminal_state so it rides /state and the websocket). ``on_death`` is best-effort: it must
    never be able to mask the health record (exceptions in it are swallowed after recording)."""
    health[name] = {"alive": True, "started_at": _now_iso()}

    async def _runner():
        try:
            await coro
            err = "exited (worker loops must never return)"
        except asyncio.CancelledError:
            health[name] = {**(health.get(name) or {}), "alive": False,
                            "stopped": "cancelled", "stopped_at": _now_iso()}
            raise                                       # clean shutdown propagates
        except Exception as e:                          # noqa: BLE001 — the whole point
            err = f"{type(e).__name__}: {e}"
        health[name] = {**(health.get(name) or {}), "alive": False,
                        "error": err, "died_at": _now_iso()}
        if on_death is not None:
            try:
                on_death(name, err)
            except Exception:
                pass                                    # the health record already tells the story

    return asyncio.create_task(_runner(), name=name)


def dead_workers(health: Optional[dict]) -> list:
    """Names of workers that DIED (crashed/exited) — cancelled/stopped workers excluded.
    The engine folds this into its status line each eval."""
    return sorted(n for n, h in (health or {}).items()
                  if isinstance(h, dict) and h.get("alive") is False and not h.get("stopped"))
