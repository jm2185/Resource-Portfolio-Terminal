#!/usr/bin/env python3
"""
commodityex_tui.py — terminal-native Conviction dashboard (Tier 0).

A calm companion to the browser Streamlit dashboard: it polls the engine's /state
and renders the four baskets live, right in a tmux pane. Numbers are health-coloured
via ``conviction_health`` (the same ramp the dashboard uses), so green = good,
amber = mid, red = weak at a glance.

Run (engine on :8000):  pip install textual && python commodityex_tui.py
Keys:  q quit · r refresh now
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from conviction_health import health_color
except Exception:  # pragma: no cover - degrade to plain text if the module moves
    def health_color(_):
        return "white"

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

ENGINE = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000/state")
REFRESH_SECONDS = 3.0


def _fetch_state():
    try:
        with urllib.request.urlopen(ENGINE, timeout=1.0) as r:  # noqa: S310 (localhost)
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _pillar(basket: dict, key: str):
    """T/Q/V scores arrive as {'score': x} dicts in the raw state."""
    v = basket.get(key)
    if isinstance(v, dict):
        v = v.get("score")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(x, spec="{:.1f}"):
    try:
        return spec.format(float(x))
    except (TypeError, ValueError):
        return "—"


def _scored(score):
    """A health-coloured number cell."""
    if score is None:
        return Text("—", style="grey50")
    return Text(_fmt(score), style=health_color(score))


class Cockpit(App):
    CSS = """
    Screen { background: #08080A; }
    #banner { height: 1; content-align: center middle; }
    #hint { height: 1; color: #5C5C62; content-align: center middle; }
    DataTable { height: 1fr; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh_now", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("connecting to engine…", id="banner")
        yield DataTable(id="book", zebra_stripes=True, cursor_type="row")
        yield Static("scores colour-coded by health · green good · amber mid · red weak", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#book", DataTable)
        for col in ("TICKER", "ARCHETYPE", "RATING", "BAND", "T", "Q", "V", "DIRECTIVE"):
            table.add_column(col, key=col)
        self.title = "CommodityEx · Conviction"
        self.set_interval(REFRESH_SECONDS, self.update_book)
        self.update_book()

    def action_refresh_now(self) -> None:
        self.update_book()

    def update_book(self) -> None:
        state = _fetch_state()
        banner = self.query_one("#banner", Static)
        table = self.query_one("#book", DataTable)

        if not state:
            banner.update(Text("⚠  engine offline — start it (ops window · or MCP run_engine)",
                               style="bold #FF9800"))
            return

        conv = state.get("conviction_mode", {}) or {}
        ctx = conv.get("context", {}) or {}
        baskets = conv.get("baskets", []) or []

        if not baskets:
            banner.update(Text("engine up · Conviction Mode empty — run ingestion, then restart the engine",
                               style="#FFB74D"))
            table.clear()
            return

        banner.update(Text(
            f"REGIME {ctx.get('regime','—')}   ·   MRI {_fmt(state.get('mri'), '{:.0f}')}"
            f"   ·   TOP {conv.get('top_pick','—')}   ·   {state.get('status','')}",
            style="bold #4FC3F7"))

        table.clear()
        for b in baskets:
            rating = b.get("rating")
            band_style = health_color(rating) if rating is not None else "grey50"
            table.add_row(
                Text(str(b.get("ticker", "?")), style="bold white"),
                Text(str(b.get("archetype", "")).replace("_", " "), style="grey62"),
                _scored(rating),
                Text(str(b.get("band", "—")), style=band_style),
                _scored(_pillar(b, "T")),
                _scored(_pillar(b, "Q")),
                _scored(_pillar(b, "V")),
                Text(str(b.get("directive", "—"))[:40], style="grey70"),
            )


if __name__ == "__main__":
    Cockpit().run()
