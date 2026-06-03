#!/usr/bin/env python3
"""
commodityex_tui.py — the professional terminal cockpit (Pillar 3).

A high-end-feel Textual dashboard that is a *pure consumer* of the engine: it never computes
valuation/what-if/state itself — it reads `/state`, posts `/action/whatif`, and reads/writes
`/config/scenarios`. Layout: macro header · watchlist (health bars) · tabbed centre
(Book · What-If · Regime · Dossier) · signals rail (live agent ui_commands) · footer.

Run (engine on :8000):  pip install textual && python commodityex_tui.py
Keys: q quit · r refresh
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from conviction_health import health_color
except Exception:  # pragma: no cover
    def health_color(_):
        return "white"
try:
    from valuation_actions import parse_overrides   # shared input parsing (not business logic)
except Exception:  # pragma: no cover
    def parse_overrides(s):
        return {}

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Button, DataTable, Footer, Header, Input, Static,
                             TabbedContent, TabPane)

ENGINE = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000")
REFRESH_SECONDS = 3.0


def _get(path: str, timeout: float = 1.5):
    try:
        with urllib.request.urlopen(f"{ENGINE}{path}", timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _post(path: str, payload: dict, timeout: float = 6.0):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{ENGINE}{path}", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"engine unreachable ({exc})"}


def _pillar(b: dict, k: str):
    v = b.get(k)
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


def _bar(score, width=10):
    """A health-coloured unicode meter for a 0-10 score."""
    try:
        f = max(0.0, min(1.0, float(score) / 10.0))
    except (TypeError, ValueError):
        return Text("░" * width, style="grey37")
    filled = round(f * width)
    return Text("█" * filled + "░" * (width - filled), style=health_color(score))


class Cockpit(App):
    TITLE = "CommodityEx · Cockpit"
    CSS = """
    Screen { background: #08080A; color: #D0D0D5; }
    Header { background: #0E0E10; color: #E6C200; text-style: bold; }
    #macroband { height: 1; content-align: center middle; background: #0E0E10; color: #C0C0C8; }
    #body { height: 1fr; }
    #watch { width: 30; border-right: solid #222226; padding: 0 1; }
    #signals { width: 32; border-left: solid #222226; padding: 0 1; }
    .railtitle { color: #FFB000; text-style: bold; border-bottom: solid #222226; }
    #tabs { width: 1fr; }
    DataTable { height: 1fr; background: #08080A; }
    Input { border: tall #222226; background: #0E0E10; }
    Input:focus { border: tall #FFB000; }
    Button { background: #121214; color: #E6C200; border: tall #222226; }
    Button:hover { border: tall #FFB000; }
    #wf_result { height: 1fr; border: round #222226; padding: 1; }
    #wf_hint, #regime, #dossier, #signalbody { color: #A0A0A5; }
    .glow { border: round #FF9800; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("connecting to engine…", id="macroband")
        with Horizontal(id="body"):
            with VerticalScroll(id="watch"):
                yield Static("WATCHLIST", classes="railtitle")
                yield Static("…", id="watchbody")
            with TabbedContent(id="tabs", initial="book"):
                with TabPane("Book", id="book"):
                    yield DataTable(id="booktbl", zebra_stripes=True, cursor_type="row")
                with TabPane("Live What-If", id="whatif"):
                    yield Input(placeholder="ticker (blank = GUI-focused)", id="wf_ticker")
                    yield Input(placeholder="silver=+5 ry=-0.5 peer=+20%   (or a saved scenario name)", id="wf_overrides")
                    with Horizontal(classes="row"):
                        yield Button("Run What-If", id="wf_run", variant="warning")
                        yield Input(placeholder="save as… (name)", id="wf_name")
                        yield Button("Save scenario", id="wf_save")
                    yield Static("Enter a ticker + overrides, then Run.", id="wf_result")
                    yield Static("", id="wf_hint")
                with TabPane("Regime", id="regime_tab"):
                    yield Static("…", id="regime")
                with TabPane("Dossier", id="dossier_tab"):
                    yield Static("Run /dossier <TICKER> in the Claude pane — it grounds in the "
                                 "focused ticker and writes data/decisions/. (View lands here next.)",
                                 id="dossier")
            with VerticalScroll(id="signals"):
                yield Static("SIGNALS", classes="railtitle")
                yield Static("no agent commands yet", id="signalbody")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#booktbl", DataTable)
        for c in ("TICKER", "ARCHETYPE", "RATING", "BAND", "T", "Q", "V", "DIRECTIVE"):
            t.add_column(c, key=c)
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.refresh_data()

    # ---- actions ----------------------------------------------------------
    def action_refresh(self) -> None:
        self.refresh_data()

    @work(thread=True, exclusive=True, group="poll")
    def refresh_data(self) -> None:
        state = _get("/state")
        scenarios = _get("/config/scenarios")
        self.call_from_thread(self._apply, state, scenarios)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wf_run":
            self.query_one("#wf_result", Static).update("running what-if…")
            self._run_whatif(self.query_one("#wf_ticker", Input).value.strip(),
                             self.query_one("#wf_overrides", Input).value.strip())
        elif event.button.id == "wf_save":
            self._save_scenario(self.query_one("#wf_name", Input).value.strip(),
                                self.query_one("#wf_overrides", Input).value.strip())

    @work(thread=True, group="whatif")
    def _run_whatif(self, ticker: str, overrides: str) -> None:
        res = _post("/action/whatif", {"ticker": ticker, "overrides": overrides})
        self.call_from_thread(self._show_whatif, res)

    @work(thread=True, group="scen")
    def _save_scenario(self, name: str, overrides: str) -> None:
        ov = parse_overrides(overrides)
        if not name or not ov:
            self.call_from_thread(self.query_one("#wf_hint", Static).update,
                                  Text("need a name and overrides to save", style="#FF9800"))
            return
        res = _post("/config/scenario", {"name": name, "overrides": ov})
        msg = (f"saved scenario '{name}'" if res.get("ok") else f"save failed: {res.get('error')}")
        self.call_from_thread(self.query_one("#wf_hint", Static).update, Text(msg, style="#69F0AE"))
        self.refresh_data()

    # ---- rendering (all driven by engine data) ----------------------------
    def _apply(self, state, scenarios) -> None:
        band = self.query_one("#macroband", Static)
        if not state:
            band.update(Text("⚠ engine offline — start it (ops window · run_engine)", style="bold #FF9800"))
            return
        conv = state.get("conviction_mode", {}) or {}
        ctx = conv.get("context", {}) or {}
        baskets = conv.get("baskets", []) or []
        band.update(Text(
            f"REGIME {ctx.get('regime','—')}   ·   MRI {_fmt(state.get('mri'), '{:.0f}')}"
            f"   ·   TOP {conv.get('top_pick','—')}   ·   {state.get('status','')}",
            style="bold #E6C200"))

        # watchlist with health bars
        rows = []
        focus = (state.get("ui_command", {}) or {}).get("args", {}).get("ticker")
        for b in baskets:
            tk = str(b.get("ticker", "?"))
            r = b.get("rating")
            line = Text()
            line.append(("▸ " if tk == focus else "  "), style="#FFB000")
            line.append(f"{tk:<7}", style="bold white")
            line.append(f"{_fmt(r):>4}  ", style=health_color(r))
            line.append_text(_bar(r))
            rows.append(line)
        wb = self.query_one("#watchbody", Static)
        wb.update(Text("\n").join(rows) if rows else Text("waiting for baskets…", style="grey50"))

        # book table
        tbl = self.query_one("#booktbl", DataTable)
        tbl.clear()
        for b in baskets:
            r = b.get("rating")
            tbl.add_row(
                Text(str(b.get("ticker", "?")), style="bold white"),
                Text(str(b.get("archetype", "")).replace("_", " "), style="grey62"),
                Text(_fmt(r), style=health_color(r)),
                Text(str(b.get("band", "—")), style=health_color(r) if r is not None else "grey50"),
                Text(_fmt(_pillar(b, "T")), style=health_color(_pillar(b, "T"))),
                Text(_fmt(_pillar(b, "Q")), style=health_color(_pillar(b, "Q"))),
                Text(_fmt(_pillar(b, "V")), style=health_color(_pillar(b, "V"))),
                Text(str(b.get("directive", "—"))[:36], style="grey70"),
            )

        # regime tab
        dec = state.get("mri_decomposition") or {}
        reg = Text()
        reg.append(f"Regime: {ctx.get('regime','—')}\nMRI: {_fmt(state.get('mri'),'{:.1f}')}\n\n", style="#C0C0C8")
        if isinstance(dec, dict) and dec:
            reg.append("MRI components:\n", style="#FFB000")
            for k, v in list(dec.items())[:12]:
                reg.append(f"  {k}: {v}\n", style="grey70")
        self.query_one("#regime", Static).update(reg)

        # signals rail (last agent ui_command)
        cmd = state.get("ui_command")
        sig = self.query_one("#signalbody", Static)
        if cmd:
            sig.update(Text(f"#{cmd.get('seq')} {cmd.get('action')} "
                            f"{cmd.get('args')}", style="#69F0AE"))
        # scenario hint
        names = [s.get("name") for s in (scenarios or {}).get("scenarios", [])] if scenarios else []
        if names:
            self.query_one("#wf_hint", Static).update(Text("saved scenarios: " + ", ".join(names), style="grey62"))

    def _show_whatif(self, res: dict) -> None:
        out = self.query_one("#wf_result", Static)
        if not res or res.get("error"):
            out.update(Text(f"⚠ {res.get('error','no result') if res else 'no result'}", style="#FF9800"))
            return
        base, scen, delta = res.get("base", {}), res.get("scenario", {}), res.get("delta", {})
        t = Text()
        t.append(f"{res.get('ticker','?')}  ({res.get('archetype','—')})\n\n", style="bold #E6C200")
        t.append("applied: ", style="grey62"); t.append(f"{res.get('overrides_applied', {})}\n\n", style="grey70")
        t.append(f"{'':10}{'BASE':>12}{'SCENARIO':>12}\n", style="#FFB000")
        bi, si = base.get("intrinsic"), scen.get("intrinsic")
        t.append(f"{'intrinsic':10}{_fmt(bi):>12}{_fmt(si):>12}\n", style="#D0D0D5")
        t.append(f"{'upside %':10}{_fmt(base.get('upside_pct')):>12}{_fmt(scen.get('upside_pct')):>12}\n\n", style="#D0D0D5")
        dp = delta.get("intrinsic_pct")
        t.append("Δ intrinsic: ", style="grey62")
        t.append(f"{_fmt(dp)}%   ", style=("#69F0AE" if (dp or 0) >= 0 else "#FF5252"))
        t.append("Δ upside: ", style="grey62")
        t.append(f"{_fmt(delta.get('upside_pp'))} pp", style="#C0C0C8")
        out.update(t)


if __name__ == "__main__":
    Cockpit().run()
