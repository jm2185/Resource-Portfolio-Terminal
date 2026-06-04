"""
Headless cockpit tests — prove commodityex_tui.py is a correct, crash-free *consumer* of the
engine contract. A tiny stub HTTP server returns realistic /state-shaped payloads; the Textual
app is booted with App.run_test() and driven through real interactions (focus a name, run a
what-if, switch tabs, slash commands, confirm a proposal). Pure formatting helpers are unit-tested
directly. Skips cleanly where Textual isn't installed (the TUI is an optional cockpit pane).
"""
from __future__ import annotations

import io
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def text_of(widget) -> str:
    """Plain text of a Static's content (Textual 8.x has no public `renderable`)."""
    from rich.console import Console
    content = getattr(widget, "_Static__content", "")
    con = Console(width=200, file=io.StringIO(), color_system=None)
    con.print(content)
    return con.file.getvalue()

try:
    import textual  # noqa: F401
    HAVE_TEXTUAL = True
except Exception:                                  # pragma: no cover
    HAVE_TEXTUAL = False

# ---- a representative engine /state payload (mirrors the real contract shapes) ----------
STATE = {
    "status": "LIVE",
    "mri": 47.0,
    "macro_regime": "risk_on",
    "directive": "Deploy under REP floor",
    "mri_decomposition": {"liquidity": -0.12, "yields": 0.20, "volatility": 0.05,
                          "commodities": 0.15, "sentiment": -0.08, "top_driver": "yields"},
    "metrics": {"Spot_Ag": {"value": 74.82, "status": "LIVE"}, "GSR": {"value": 81.3, "status": "LIVE"},
                "DXY_MOMENTUM": {"value": -0.4, "status": "LIVE"}, "VIX": {"value": 15.7, "status": "LIVE"},
                "DXY": {"value": 104.2, "status": "LIVE"}, "10Y": {"value": 4.25, "status": "LIVE"},
                "30Y": {"value": 4.46, "status": "LIVE"}},
    "macro_tape": {"signals": [
        {"key": "gsr", "label": "Gold/Silver", "value": 81.3, "display": "81", "bias": "neutral", "read": "Balanced"},
        {"key": "real_yield", "label": "Real Yield", "value": 1.8, "display": "1.80%", "bias": "neutral", "read": "Neutral"},
        {"key": "vix", "label": "VIX", "value": 15.7, "display": "16", "bias": "risk_on", "read": "Complacent"},
    ], "risk_off_count": 1, "risk_on_count": 4, "net_tilt": "RISK-ON", "top_mri_driver": "yields",
        "vix_term_structure": 1.04},
    "forensics": {"jsf_score": 3.5, "penalty_factor": 0.9, "runway": 18.4, "sloan_cfo": 0.02, "sloan_bs": 0.02},
    "portfolio_stats": {"expected_shortfall_95": 6.2, "avg_correlation": 0.41},
    "health_radar": {"health_rating": 8.2, "rating_desc": "High integrity", "rating_color": "green",
                     "tactical_ceiling": 4200.0, "priorities": [{"title": "Watch AGA.V assays", "desc": "drill"}]},
    "integrity": {"status": "LIVE", "any_stale": False, "stale_feeds": [], "forensic_override_count": 0},
    "nodes": {"AGA.V": {"price": 0.71, "role": "The Spear", "shares": 1000},
              "GROY": {"price": 3.22, "role": "Ballast", "shares": 100}},
    "ui_command": {"seq": 2, "action": "focus", "args": {"ticker": "AGA.V"}, "issued_at": 0},
    "agent_activity": [
        {"seq": 1, "ts": 0, "agent": "claude", "kind": "prompt", "summary": "why is AGA.V rated this?", "ticker": "AGA.V"},
        {"seq": 2, "ts": 0, "agent": "claude", "kind": "tool", "summary": "run_valuation_whatif AGA.V", "ticker": None},
    ],
    "agent_annotations": {
        "AGA.V": [{"ticker": "AGA.V", "badge": "✦", "reason": "REP-floor arb live", "level": "good",
                   "agent": "claude", "ts": 0, "ttl": None, "seq": 5}],
        "GROY": [{"ticker": "GROY", "badge": "◆", "reason": "regime tailwind", "level": "info",
                  "agent": "antigravity", "ts": 0, "ttl": None, "seq": 6}],
    },
    "agent_reply": {"text": "AGA.V screens cheap vs its REP floor — asymmetric.", "agent": "claude", "ts": 0},
    "treasury_curve": {"date": "2026-06-03", "source": "FMP", "cached": True,
                       "tenors": {"month1": 3.71, "month3": 3.78, "year2": 4.08, "year5": 4.21,
                                  "year10": 4.49, "year30": 4.99}},
    "pipeline": {"status": "running", "theme": "silver juniors", "stage": "verifier",
                 "started": 0, "updated": 0, "result": None, "verdicts": {"AGA.V": "APPROVE"},
                 "events": [{"ts": 0, "stage": "verifier", "status": "running", "message": "red-teaming GROY"}]},
    "conviction_mode": {
        "status": "live", "view": "conviction", "primary": True, "top_pick": "AGA.V",
        "context": {"mri": 47.0, "regime": "RISK-ON", "catalyst_feed": "live"},
        "baskets": [
            {"ticker": "AGA.V", "archetype": "junior_explorer", "archetype_code": "EXPL",
             "rating": 8.2, "band": "STRONG ASYMMETRY", "directive": "STRONG ASYMMETRY — WATCH CLOSELY",
             "pillars": {"T": {"score": 7.1}, "Q": {"score": 6.4},
                         "V": {"score": 8.6, "mode": "asymmetry", "upside_pct": 99.0,
                               "downside_to_floor_pct": 12.7, "floor_coverage": 0.87, "rho": 2.3, "support": 0.4}},
             "gate": {"applied": False, "cap": 10.0, "floor_support": 0.4, "reason": "clean"},
             "confidence_ribbon": {"plus_minus": 0.18, "quality": "full", "scenario_spread": 0.9},
             "ladder": {"bull": 1.42, "base": 0.95, "price": 0.71, "bear": 0.55, "floor": 0.62},
             "catalysts": [{"headline": "Drill assays pending", "type": "drill"}], "catalyst_signal": 0.3},
            {"ticker": "GROY", "archetype": "asset_light_yield", "archetype_code": "ROY",
             "rating": 6.9, "band": "HIGH QUALITY", "directive": "QUALITY — CORE HOLD",
             "pillars": {"T": {"score": 5.5}, "Q": {"score": 7.8},
                         "V": {"score": 6.2, "mode": "value", "upside_pct": 8.0,
                               "downside_to_floor_pct": None, "floor_coverage": 0.6}},
             "gate": {"applied": True, "cap": 7.0, "floor_support": 0.1, "reason": "JSF 3.0<3.5 (floor-relaxed 10%)"},
             "confidence_ribbon": {"plus_minus": 0.4, "quality": "degraded", "scenario_spread": 0.0},
             "ladder": {"bull": None, "base": 3.5, "price": 3.22, "bear": None, "floor": 1.9},
             "catalysts": [], "catalyst_signal": 0.0},
        ],
    },
}
SCENARIOS = {"scenarios": [{"name": "debasement", "overrides": {"spot_ag": "+5", "real_yield": "-0.5"}}]}
PENDING = {"pending": [{"id": 3, "key": "rov_default", "value": 1.25, "reason": "negative real yields deepening",
                        "proposed_by": "conviction-analyst", "status": "pending"}]}
DECISIONS = {"dir": "data/decisions", "count": 1, "decisions": [
    {"name": "AGA.V_thesis.md", "ticker": "AGA.V", "title": "AGA.V — asymmetric spear",
     "mtime": 0, "age_minutes": 12.0, "size": 400, "preview": "AGA.V thesis…"}]}
WHATIF = {"ticker": "AGA.V", "archetype": "junior_explorer", "price": 0.71,
          "overrides_applied": {"spot_ag": {"from": 74.8, "to": 79.8}},
          "base": {"intrinsic": 0.95, "upside_pct": 33.8, "legs": {"cost": 0.62}},
          "scenario": {"intrinsic": 1.18, "upside_pct": 66.2, "legs": {"cost": 0.62}},
          "delta": {"intrinsic_pct": 24.2, "upside_pp": 32.4}}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                     # keep test output quiet
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/state"):
            return self._send(STATE)
        if self.path.startswith("/config/scenarios"):
            return self._send(SCENARIOS)
        if self.path.startswith("/config/pending"):
            return self._send(PENDING)
        if self.path.startswith("/decisions/item"):
            return self._send({"name": "AGA.V_thesis.md", "markdown": "# AGA.V\nAsymmetric spear thesis."})
        if self.path.startswith("/decisions"):
            return self._send(DECISIONS)
        return self._send({"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        if self.path.startswith("/action/whatif"):
            return self._send(WHATIF)
        if self.path.startswith("/config/confirm"):
            return self._send({"ok": True, "applied": 3})
        if self.path.startswith("/config/scenario"):
            return self._send({"ok": True, "name": "tmp", "overrides": {}})
        return self._send({"ok": True})


class HelperTests(unittest.TestCase):
    """Pure formatting helpers — no Textual app required (rich only)."""

    @unittest.skipUnless(HAVE_TEXTUAL, "textual not installed")
    def test_helpers(self):
        import commodityex_tui as t
        self.assertEqual(t._score({"score": 7.1}), 7.1)
        self.assertEqual(t._score(6.0), 6.0)
        self.assertIsNone(t._score({"x": 1}))
        # asymmetric upside indicator
        self.assertIn("+99%", t._upside_text(STATE["conviction_mode"]["baskets"][0]).plain)
        # REP-floor edge: below liquidation reads BELOW; otherwise a distance
        below = {"pillars": {"V": {"floor_coverage": 1.2}}}
        self.assertIn("BELOW", t._floor_edge(below).plain)
        self.assertIn("-13%", t._floor_edge(STATE["conviction_mode"]["baskets"][0]).plain)
        # gate text: clean vs capped
        self.assertEqual(t._gate_text(STATE["conviction_mode"]["baskets"][0]).plain, "clean")
        self.assertTrue(t._gate_text(STATE["conviction_mode"]["baskets"][1]).plain.startswith("⚠"))
        # delta bar is symmetric and centred
        self.assertEqual(len(t._delta_bar(10).plain), 21)
        # ladder places points between extremes
        bar, legend = t._ladder([("F", 0.62, "x"), ("●", 0.71, "y"), ("▲", 1.42, "z")])
        self.assertIn("F", bar.plain)
        self.assertIn("▲", bar.plain)
        # compact macro-tape labels + sparkline helpers (the live ticker building blocks)
        self.assertEqual(t._tape_short("VIX"), "VIX")
        self.assertEqual(t._tape_short("Gold/Silver"), "GSR")
        self.assertEqual(len(t._spark([1, 2, 3, 4, 5])), 5)
        self.assertEqual(t._spark([1]), "")
        self.assertEqual(t._arch_short("asset_light_yield"), "ROYALTY")


@unittest.skipUnless(HAVE_TEXTUAL, "textual not installed")
class CockpitBootTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        os.environ["CEX_ENGINE_URL"] = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    async def test_boots_and_drives(self):
        import importlib
        import commodityex_tui as t
        importlib.reload(t)                        # pick up CEX_ENGINE_URL pointed at the stub
        app = t.Cockpit()
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause(0.4)                 # let the first poll land
            # header reflects engine state
            self.assertIn("RISK-ON", text_of(app.query_one("#statusband")))
            self.assertIn("HEALTH", text_of(app.query_one("#statusband")))
            # book populated + top pick focused -> agent grounding
            self.assertEqual(app._row_index.get("AGA.V"), 0)
            self.assertEqual(app._focus, "AGA.V")
            # signals rail surfaces the pending agent proposal + grounded ask-agents copy
            self.assertIn("#3", text_of(app.query_one("#signalbody")))
            self.assertIn("conviction-analyst", text_of(app.query_one("#signalbody")))
            # AGENT STREAM renders the ambient agent activity (hooks -> /agent/activity)
            rail = text_of(app.query_one("#signalbody"))
            self.assertIn("why is AGA.V rated this?", rail)
            self.assertIn("run_valuation_whatif", rail)
            self.assertIn("bear case", rail)
            # agents leave visual traces: badge in the watch rail + AGENT NOTES in the signals rail
            self.assertIn("REP-floor arb live", text_of(app.query_one("#watchbody")))
            self.assertIn("AGENT NOTES", rail)
            self.assertIn("regime tailwind", rail)
            # background pipeline status surfaces in the PIPELINE panel (chat stays free)
            self.assertIn("PIPELINE", rail)
            self.assertIn("silver juniors", rail)
            self.assertIn("APPROVE", rail)
            # structured UI commands drive the cockpit: switch_tab + apply_scenario (run a what-if)
            from textual.widgets import TabbedContent, Input as _In
            app._handle_agent_command({"ui_command": {"seq": 90, "action": "switch_tab", "args": {"view": "regime"}}})
            await pilot.pause(0.1)
            self.assertEqual(app.query_one("#tabs", TabbedContent).active, "regime_tab")
            self.assertIn("UST curve", text_of(app.query_one("#regime")))    # FMP treasury curve wired in
            app._handle_agent_command({"ui_command": {"seq": 91, "action": "apply_scenario",
                                                      "args": {"ticker": "AGA.V", "overrides": "silver=+8"}}})
            await pilot.pause(0.3)
            self.assertEqual(app.query_one("#tabs", TabbedContent).active, "whatif")
            self.assertIn("silver=+8", app.query_one("#wf_overrides", _In).value)
            # the dashboard is promptable: latest agent reply renders in the AGENT REPLY panel
            self.assertIn("screens cheap vs its REP floor", text_of(app.query_one("#agent_reply")))
            # plain text in the command bar routes to a background agent (not parsed as a /command,
            # not the interactive pane). Stub the headless command so the test stays fast + offline.
            os.environ["CEX_ASK_CMD"] = "true"
            app._ask_agent("why is AGA.V cheap?")
            await pilot.pause(0.2)
            self.assertEqual(app._asked, "why is AGA.V cheap?")
            self.assertIn("you asked: why is AGA.V cheap?", text_of(app.query_one("#agent_reply")))
            # one-key dispatch: needs a focused name; reports clearly without one
            app._focus = None
            app.action_ask("analyst")
            await pilot.pause(0.2)
            self.assertIn("focus a name first", text_of(app.query_one("#wf_status")))
            app._focus = "AGA.V"
            app.action_ask("analyst")             # no CLAUDE pane in the test env -> clear status, no crash
            await pilot.pause(0.3)
            self.assertIn("claude", text_of(app.query_one("#wf_status")).lower())
            # slash command: focus a different name
            app._run_command("/focus GROY")
            await pilot.pause(0.2)
            self.assertEqual(app._focus, "GROY")
            # run a what-if via the command bar
            app._run_command("/whatif AGA.V silver=+5")
            await pilot.pause(0.8)
            self.assertIn("Δ intrinsic", text_of(app.query_one("#wf_result")))
            self.assertIn("24.2%", text_of(app.query_one("#wf_result")))
            self.assertTrue(app._wf_hist)          # iteration trail recorded
            # load a saved scenario into the override line
            app._run_command("/scenario debasement")
            await pilot.pause(0.2)
            self.assertEqual(app._active_scenario, "debasement")
            self.assertIn("spot_ag", app.query_one("#wf_overrides").value)
            self.assertIn("loaded scenario 'debasement'", text_of(app.query_one("#wf_status")))
            # confirm the pending agent proposal (transient status must survive the next poll)
            app._run_command("/confirm 3")
            await pilot.pause(0.4)
            self.assertIn("confirmed #3", text_of(app.query_one("#wf_status")))
            await pilot.pause(0.3)                 # a poll lands; status must NOT be clobbered
            self.assertIn("confirmed #3", text_of(app.query_one("#wf_status")))
            # cycle all tabs (regime + dossier render without error)
            for tab in ("regime_tab", "dossier_tab", "whatif", "book"):
                app.action_tab(tab)
                await pilot.pause(0.1)
            # regime tab built its research view
            self.assertIn("REGIME", text_of(app.query_one("#regime")))
            self.assertIn("MRI components", text_of(app.query_one("#regime")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
