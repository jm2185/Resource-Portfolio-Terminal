"""
UI-context state for the cockpit <-> Flutter merge — owned and orchestrated by engine.py.

The engine holds a single ``UIStateManager``. A frontend (Flutter) POSTs what it is showing
to ``/ui/state``; agents read it via ``GET /ui/state`` (the ``get_ui_context`` MCP tool) and
steer the display via ``POST /ui/command`` (broadcast on ``/ws`` under
``terminal_state['ui_command']``; the frontend acts when ``seq`` increases).

Kept as a tiny stdlib module so it is unit-testable on its own and so engine.py stays the
authoritative hub (it owns the instance, the routes and terminal_state). Versioned so the
Flutter contract can evolve without silent breakage.
"""

from __future__ import annotations

import time

SCHEMA_VERSION = 1
VALID_ACTIONS = ("focus", "view", "scenario", "highlight", "alert")

# Fields a frontend may report. (``ticker`` is accepted as an alias for focused_ticker.)
_REPORTABLE = (
    "focused_ticker", "active_view", "current_scenario",
    "visible_tickers", "selected_whatif", "source",
)


class UIStateManager:
    """Bidirectional UI-context broker. Read side = the on-screen context; write side = a
    monotonic command stream the frontend consumes over /ws."""

    def __init__(self) -> None:
        self._state: dict = {
            "schema_version": SCHEMA_VERSION,
            "focused_ticker": None,     # the name the user is looking at
            "active_view": None,        # "conviction" | "detailed" | ...
            "current_scenario": None,   # scenario/regime the GUI is displaying
            "visible_tickers": [],      # what's on screen (watchlist / cards)
            "selected_whatif": None,    # the active/named what-if overrides
            "source": None,             # which frontend last reported (e.g. "flutter")
            "last_updated": None,
        }
        self._seq = 0
        self._last_command: dict | None = None

    # ---- read side ---------------------------------------------------------
    def get(self) -> dict:
        return dict(self._state)

    @property
    def focused_ticker(self):
        return self._state.get("focused_ticker")

    # ---- frontend reports its on-screen context ---------------------------
    def update(self, patch: dict | None) -> dict:
        p = dict(patch or {})
        if "ticker" in p and "focused_ticker" not in p:
            p["focused_ticker"] = p["ticker"]
        for k in _REPORTABLE:
            if k in p:
                self._state[k] = p[k]
        self._state["schema_version"] = SCHEMA_VERSION
        self._state["last_updated"] = time.time()
        return self.get()

    # ---- agents steer the frontend ----------------------------------------
    def command(self, action: str, args: dict | None = None) -> dict:
        if not action:
            raise ValueError("action required (%s)" % " | ".join(VALID_ACTIONS))
        self._seq += 1
        self._last_command = {
            "seq": self._seq,
            "action": action,
            "args": dict(args or {}),
            "issued_at": time.time(),
        }
        return dict(self._last_command)

    @property
    def last_command(self) -> dict | None:
        return dict(self._last_command) if self._last_command else None
