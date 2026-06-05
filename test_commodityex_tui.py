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
        {"seq": 3, "ts": 0, "agent": "claude", "kind": "ran", "summary": "python -m unittest test_council", "ticker": None},
        {"seq": 4, "ts": 0, "agent": "claude", "kind": "git", "summary": "git commit -m fix", "ticker": None},
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
    "data_freshness": {"feeds": {
        "macro": {"age_minutes": 43.0, "stale": False}, "prices": {"age_minutes": 1.0, "stale": False},
        "mri_history": {"age_minutes": 1230.0, "stale": True}, "forensic": {"age_minutes": 1230.0, "stale": False},
        "peers": {"age_minutes": 240.0, "stale": False}}, "any_stale": True},
    "posture": {"code": "spear_exploit", "label": "SPEAR EXPLOIT", "cap": 0.75, "headwind": True,
                "rationale": "spear exploit · real_yield headwind (cap 0.75x)"},
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
        # design-system glyph primitives (PillarBar / Badge / ConvictionRating in glyph form)
        self.assertEqual(t._pillar("X", 10, width=20).plain.count("█"), 20)   # full fill
        self.assertEqual(t._pillar("X", 0, width=20).plain.count("█"), 0)     # empty fill
        self.assertIn("7.1", t._pillar("T · TAILWIND", 7.1).plain)            # value rides the bar
        self.assertIn("—", t._pillar("V", None).plain)                       # missing degrades
        self.assertEqual(t._badge("CLEAN", "good").plain, " CLEAN ")          # chip pads the label
        self.assertEqual(t._badge("X", "risk").style.color.name, "#d87a7a")   # level → colour
        self.assertIn("◆ 8.6", t._rating(8.6, "PRIME").plain)                 # hero read + band
        self.assertIn("PRIME", t._rating(8.6, "PRIME").plain)
        self.assertEqual(t._rating(None).plain, "◆ —")                        # missing rating


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
            # regime posture (the master temperature dial) composes onto the header
            self.assertIn("SPEAR EXPLOIT", text_of(app.query_one("#statusband")))
            self.assertIn("0.75x", text_of(app.query_one("#statusband")))
            # book populated + top pick focused -> agent grounding
            self.assertEqual(app._row_index.get("AGA.V"), 0)
            self.assertEqual(app._focus, "AGA.V")
            # company-detail tearsheet: engine price surfaced (works even without FMP coverage)
            detail = text_of(app.query_one("#book_detail"))
            self.assertIn("price", detail)
            self.assertIn("$0.71", detail)
            # the focused name renders as the conviction card: hero ◆ rating + T/Q/V PillarBars
            self.assertIn("◆", detail)                          # hero ConvictionRating glyph
            self.assertIn("TAILWIND", detail)                   # T/Q/V rendered as labelled bars
            self.assertIn("VALUE", detail)
            self.assertTrue("█" in detail or "─" in detail)     # pillar fill / track glyphs
            self.assertIn("convictioncard", app.query_one("#book_detail").classes)
            # dossier index renders clickable entries when decisions exist
            app._decisions = [{"name": "AGA.V_x.md", "ticker": "AGA.V", "title": "spear", "age_minutes": 5}]
            app._render_dossier_index()
            self.assertIn("AGA.V", text_of(app.query_one("#dossier_index")))
            # delete is two-click armed (no accidental loss)
            app.action_delete_dossier("AGA.V_x.md")
            self.assertEqual(app._del_arm, "AGA.V_x.md")
            # company profile page: click-to-open renders the deep-dive. Inject FMP's (stale) mcap
            # as production would have it, to exercise the sourced-vs-feed integrity cross-check.
            app._fund["AGA.V"] = {"marketCap": 112_644_909, "beta": 1.24}
            app.action_open_profile("AGA.V")
            await pilot.pause(0.1)
            prof = text_of(app.query_one("#profile_body"))
            self.assertIn("CONVICTION", prof)
            self.assertIn("CATALYSTS", prof)
            self.assertIn("$0.71", prof)
            # market cap is computed from SOURCED filing shares × live price, not FMP's stale field
            # (208.6M sh × $0.71 ≈ $148M); the stale FMP feed (112.6M) is surfaced as a flag
            self.assertIn("sh×px", prof)
            self.assertIn("FMP feed", prof)
            # provenance: every input tagged; filings-derived inputs read from the research cache,
            # AISC honestly 'pending' (pre-PEA, no value faked)
            self.assertIn("DATA & TRUST", prof)
            self.assertIn("in-ground oz", prof)
            self.assertIn("pending", prof)
            # dashboard surfaces feed ages with stale flags
            rail = text_of(app.query_one("#signalbody"))
            self.assertIn("regime", rail)
            # signals rail surfaces the pending agent proposal (human-gated, no command-speak)
            self.assertIn("#3", text_of(app.query_one("#signalbody")))
            self.assertIn("conviction-analyst", text_of(app.query_one("#signalbody")))
            # DESK TAPE merges the operator's terminal actions (ran/edited/git, shown as "you") with
            # agent work + state changes — the nervous system made visible (Forge #2/#6)
            rail = text_of(app.query_one("#signalbody"))
            self.assertIn("DESK TAPE", rail)
            self.assertIn("why is AGA.V rated this?", rail)
            self.assertIn("run_valuation_whatif", rail)
            self.assertIn("you", rail)                          # operator actions framed as "you"
            self.assertIn("git commit", rail)
            # the repurposed rail surfaces the Living Memory research stream (not hotkey ask-agents)
            self.assertIn("LIVING MEMORY", rail)
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
            # the dashboard is promptable: empty CONVERSATION shows the branching affordance
            conv = text_of(app.query_one("#agent_reply"))
            self.assertIn("CONVERSATION", conv)
            self.assertIn("✦ new", conv)
            self.assertIn("own thread", conv)
            # the Council reconciliation now rides on the Book page (focused name = AGA.V)
            self.assertIn("COUNCIL", conv)
            self.assertIn("full debate", conv)
            # click-to-inspect: clicking a metric pops a live breakdown OVER any view (works
            # everywhere via the modal), with the formula + glossary + an 'ask the analyst' deep-dive
            app._set_focus("AGA.V")
            app.action_explain("phi")
            await pilot.pause(0.1)
            self.assertIn("Floor coverage", text_of(app.screen.query_one("#inspect_title")))
            self.assertIn("φ = floor", text_of(app.screen.query_one("#inspect_body")))
            self.assertIn("ask the analyst", text_of(app.screen.query_one("#inspect_actions")))
            app.pop_screen()                                   # dismiss the pop-over
            await pilot.pause(0.1)
            # the desk tape is interactive: clicking an entry pops its detail (not just a log)
            app.action_tape(4)                                 # the 'git' event in the fixture
            await pilot.pause(0.1)
            self.assertIn("GIT", text_of(app.screen.query_one("#inspect_title")))
            app.pop_screen()
            await pilot.pause(0.1)
            # plain text in the command bar routes to a background agent (not parsed as a /command,
            # not the interactive pane). Stub the headless command so the test stays fast + offline.
            os.environ["CEX_ASK_CMD"] = "true"
            app._ask_agent("why is AGA.V cheap?")
            await pilot.pause(0.2)
            self.assertEqual(app._asked, "why is AGA.V cheap?")
            conv = text_of(app.query_one("#agent_reply"))
            self.assertIn("you ›", conv)                       # the active thread's transcript
            self.assertIn("why is AGA.V cheap?", conv)
            # follow-up 1 — the thread is bound to the name you were on (AGA.V from boot focus)
            self.assertEqual(app._thread_meta(app._active)[0], "AGA.V")
            # follow-up 2 — saving the thread writes a Dossier memo (data/decisions); clean up after
            import glob as _glob
            app.action_save_thread()
            saved = _glob.glob(os.path.join(os.path.dirname(os.path.abspath(t.__file__)),
                                            "data", "decisions", "*_thread_*.md"))
            self.assertTrue(saved)
            for _p in saved:
                os.remove(_p)
            # branching: a new thread isolates context from the AGA.V thread
            app.action_new_thread()
            self.assertIsNone(app._active)
            app._ask_agent("unrelated: uranium royalty outlook?")
            roots = [n for n in app._conv.values() if not n.get("parent")]
            self.assertEqual(len(roots), 2)                    # two separate research threads
            lineage_text = " ".join(m["text"] for m in app._lineage(app._active))
            self.assertIn("uranium", lineage_text)
            self.assertNotIn("why is AGA.V cheap?", lineage_text)   # context scoped to this branch only
            # follow-up A — clicking a thread restores its bound name + scenario (research⇄valuation)
            bound = app._new_node("you", "URC.TO dilution risk?", None)
            app._conv[bound]["ticker"] = "URC.TO"
            app._conv[bound]["scenario"] = "silver=+3 dxy=-1"
            app.action_sel_branch(bound)
            self.assertEqual(app._focus, "URC.TO")
            self.assertEqual(app.query_one("#wf_overrides", _In).value, "silver=+3 dxy=-1")
            # follow-up B — a finished pipeline seeds a context-bound thread per surviving name
            before = len(app._conv)
            app._maybe_seed_pipeline({"pipeline": {"status": "done", "started": 123, "theme": "royalties",
                "result": "Scout 4 → Synthesis ranked → Verifier approved GROY.",
                "verdicts": {"GROY": {"verdict": "APPROVE", "note": "cheap NAV, clean JSF"},
                             "XYZ": {"verdict": "REJECT", "note": "dilution"}}}})
            seeded = [n for n in app._conv.values() if n.get("agent") == "pipeline"]
            self.assertEqual(len(seeded), 1)                    # GROY seeded, XYZ (reject) skipped
            self.assertEqual(seeded[0]["ticker"], "GROY")
            self.assertGreater(len(app._conv), before)
            for _p in _glob.glob(os.path.join(os.path.dirname(os.path.abspath(t.__file__)),
                                              "data", "decisions", "pipeline_*.md")):
                os.remove(_p)
            await pilot.pause(0.4)                 # let the stubbed ask workers settle (status line)
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
            # interactive what-if knobs: overrides <-> knobs round-trip + render + stepping
            app._knobs_from_overrides("silver=+5 ry=-0.5 peer=+20%")
            self.assertEqual((app._wf_knobs["silver"], app._wf_knobs["ry"], app._wf_knobs["peer"]),
                             (5.0, -0.5, 20.0))
            self.assertEqual(app._wf_overrides_from_knobs(), "silver=+5 ry=-0.5 peer=+20%")
            app._render_wf_knobs()
            await pilot.pause(0.05)
            knob_panel = text_of(app.query_one("#wf_knobs"))
            self.assertIn("Ag", knob_panel)
            self.assertIn("RealY", knob_panel)
            app.action_tab("whatif")
            await pilot.pause(0.05)
            app._wf_sel = 0                          # silver
            app.action_wf_step(1, False)             # coarse +1 -> 6.0, builds the override line
            self.assertEqual(app._wf_knobs["silver"], 6.0)
            self.assertIn("silver=+6", app.query_one("#wf_overrides", _In).value)
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
            # cycle all tabs (regime + dossier + profile render without error; council is merged into Book)
            for tab in ("regime_tab", "dossier_tab", "profile_tab", "whatif", "book"):
                app.action_tab(tab)
                await pilot.pause(0.1)
            # regime tab built its research view
            self.assertIn("REGIME", text_of(app.query_one("#regime")))
            self.assertIn("MRI components", text_of(app.query_one("#regime")))
            # Council is MERGED into the Book page (no separate tab): convening EXPANDS the debate
            # inline above the SHARED conversation — grounded in the engine asymmetry, not a tab switch.
            app._set_focus("AGA.V")
            app.action_go_council()
            await pilot.pause(0.1)
            self.assertEqual(app.query_one("#tabs", TabbedContent).active, "book")   # stayed on Book
            self.assertTrue(app._council_open)
            council = text_of(app.query_one("#agent_reply"))   # the council rides on the Book conversation
            self.assertIn("COUNCIL", council)
            self.assertIn("BULL", council)
            self.assertIn("ARBITER", council)
            self.assertIn("SPEAR EXPLOIT", council)            # posture composes onto the pre-debate
            self.assertIn("RESEARCH THREAD", council)          # the name's living memory thread
            self.assertIn("Re-run with memory", council)       # council action buttons post into the chat
            # collapsing leaves the shared chat intact, with the compact council strip atop it
            app.action_toggle_council()
            await pilot.pause(0.05)
            self.assertFalse(app._council_open)
            collapsed = text_of(app.query_one("#agent_reply"))
            self.assertIn("full debate", collapsed)            # the expand affordance
            self.assertIn("CONVERSATION", collapsed)           # the shared chat is still there
            # plain-text note -> Living Memory (everything-talks loop), then visible in the thread.
            # Point the cockpit's memory at a temp store so the versioned one isn't polluted.
            import tempfile
            import living_memory
            tmp = tempfile.mktemp(suffix=".jsonl")
            app._mem = living_memory.LivingMemory(path=tmp)
            try:
                app._write_note("Nevada permitting looks faster than Canadian peers", "AGA.V")
                await pilot.pause(0.1)
                self.assertIn("note saved", text_of(app.query_one("#wf_status")))
                self.assertEqual(app._mem.latest(ticker="AGA.V", type="note")["text"],
                                 "Nevada permitting looks faster than Canadian peers")
                app.action_go_council()                        # re-expand the inline council on Book
                await pilot.pause(0.1)
                self.assertIn("permitting looks faster", text_of(app.query_one("#agent_reply")))
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    async def test_palette_history_and_help(self):
        import importlib
        import commodityex_tui as t
        importlib.reload(t)
        os.environ["CEX_ASK_CMD"] = "true"             # stub the headless ask so plain text is offline
        app = t.Cockpit()
        async with app.run_test(size=(150, 50)) as pilot:
            await pilot.pause(0.4)

            # --- command palette: Ctrl-K reaches it even while the chat input is focused (priority) ---
            app.query_one("#cmdbar", t.ChatInput).focus()
            await pilot.pause(0.05)
            await pilot.press("ctrl+k")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, t.PaletteScreen)
            pal = app.screen
            results = text_of(pal.query_one("#palette_results"))
            self.assertIn("AGA.V", results)            # book names are candidates
            self.assertIn("Convene council", results)  # actions are candidates
            pal._rebuild("help")                        # help is reachable from the palette
            self.assertIn("Keys & help", text_of(pal.query_one("#palette_results")))
            # filter to GROY and run the top hit → it focuses that name and writes a recap
            pal.query_one("#palette_input", t.Input).value = "GROY"
            pal._rebuild("GROY")
            self.assertTrue(pal._results and pal._results[0][1] == "GROY")
            pal.dismiss((pal._results[0][3], "GROY"))
            await pilot.pause(0.1)
            self.assertEqual(app._focus, "GROY")
            self.assertIn("focus GROY", app._palette_recap)
            # an unmatched query falls through to the agents (no dead-ends)
            app.action_palette(); await pilot.pause(0.05)
            app.screen.dismiss((None, "why is silver bid?"))
            await pilot.pause(0.1)
            self.assertEqual(app._asked, "why is silver bid?")

            # --- ask-history: prior chat asks recall with ↑/↓ (Bloomberg History key) ---
            ci = app.query_one("#cmdbar", t.ChatInput)

            class _Sub:                                # duck-typed Input.Submitted
                def __init__(self, inp, val): self.input, self.value = inp, val
            for q in ("why is AGA.V cheap?", "what is the floor?"):
                ci.value = q
                app.on_input_submitted(_Sub(ci, q))
                await pilot.pause(0.05)
            self.assertEqual(app._ask_history[-2:], ["why is AGA.V cheap?", "what is the floor?"])
            ci._hist_idx = None
            ci.action_hist(-1); self.assertEqual(ci.value, "what is the floor?")
            ci.action_hist(-1); self.assertEqual(ci.value, "why is AGA.V cheap?")
            ci.action_hist(1);  self.assertEqual(ci.value, "what is the floor?")

            # --- ? help overlay: the keymap + click grammar, as a pop-over ---
            app.action_help()
            await pilot.pause(0.1)
            hb = text_of(app.screen.query_one("#inspect_body"))
            self.assertIn("KEYS", hb)
            self.assertIn("CLICK GRAMMAR", hb)
            self.assertIn("Palette", hb)               # the Ctrl-K palette binding is documented
            app.pop_screen()

    async def test_agent_oversight(self):
        import importlib
        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(150, 50)) as pilot:
            await pilot.pause(0.4)

            # --- AGENTS control strip: in-flight runs are visible (label · elapsed · cancel) ---
            strip = text_of(app.query_one("#agents_strip"))
            self.assertIn("AGENTS", strip)
            self.assertIn("pipeline", strip)           # the running fixture pipeline is surfaced here
            jid = app._inflight_add("ask", "why is AGA.V cheap?", "AGA.V")
            await pilot.pause(0.05)
            strip = text_of(app.query_one("#agents_strip"))
            self.assertIn("why is AGA.V cheap?", strip)
            self.assertIn("cancel", strip)
            # cancelling stops waiting on the run — it leaves the strip
            app.action_cancel_job(jid)
            await pilot.pause(0.05)
            self.assertTrue(app._inflight[jid]["cancelled"])
            self.assertNotIn("why is AGA.V cheap?", text_of(app.query_one("#agents_strip")))

            # --- action receipts + undo: a note emits a receipt; undo supersedes it (immutably) ---
            import tempfile
            import living_memory
            tmp = tempfile.mktemp(suffix=".jsonl")
            app._mem = living_memory.LivingMemory(path=tmp)
            try:
                app._set_focus("AGA.V")
                app._write_note("Nevada permitting fast", "AGA.V")
                await pilot.pause(0.05)
                ag = text_of(app.query_one("#agents_strip"))
                self.assertIn("RECEIPTS", ag)
                self.assertIn("note", ag)
                self.assertIn("undo", ag)              # the note is reversible
                self.assertEqual(app._mem.latest(ticker="AGA.V", type="note")["text"], "Nevada permitting fast")
                rid = app._receipts[-1]["id"]
                # undo → the note is superseded, so it's hidden from the live thread (audit trail kept)
                app.action_undo_receipt(rid)
                await pilot.pause(0.05)
                notes = [e["text"] for e in app._mem.query(ticker="AGA.V", type="note")]
                self.assertNotIn("Nevada permitting fast", notes)
                self.assertFalse(any(r["id"] == rid for r in app._receipts))
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    async def test_memory_management(self):
        import importlib
        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(150, 55)) as pilot:
            await pilot.pause(0.4)
            import tempfile
            import living_memory
            tmp = tempfile.mktemp(suffix=".jsonl")
            app._mem = living_memory.LivingMemory(path=tmp)
            try:
                app._set_focus("AGA.V")
                a = app._mem.write("note", text="silver leadership intact", ticker="AGA.V", source="you")
                app._mem.write("note", text="ancient note", ticker="AGA.V", source="arbiter",
                               ts="2000-01-01T00:00:00Z")              # ancient → stale
                app._render_signals(app._state or {})
                await pilot.pause(0.05)
                rail = text_of(app.query_one("#signalbody"))
                # provenance + management affordances + decay all render
                self.assertIn("LIVING MEMORY", rail)
                self.assertIn("silver leadership", rail)
                self.assertIn("by you", rail)                          # provenance: captured-by source
                self.assertIn("pin", rail)
                self.assertIn("edit", rail)
                self.assertIn("stale", rail)                           # the ancient note decays → re-confirm
                # pin → it floats to the top, marked 📌
                app.action_mem_pin(a["id"])
                await pilot.pause(0.05)
                self.assertEqual(app._mem.pinned_ids(), {a["id"]})
                self.assertIn("📌", text_of(app.query_one("#signalbody")))
                # edit → loads into the chat bar; saving supersedes the original (immutable edit)
                app.action_mem_edit(a["id"])
                await pilot.pause(0.05)
                self.assertEqual(app._editing_mem, a["id"])
                ci = app.query_one("#cmdbar", t.ChatInput)
                self.assertTrue(ci.value.startswith("note: silver leadership"))

                class _Sub:
                    def __init__(s, inp, val): s.input, s.value = inp, val
                ci.value = "note: silver leadership CONFIRMED"
                app.on_input_submitted(_Sub(ci, "note: silver leadership CONFIRMED"))
                await pilot.pause(0.05)
                self.assertIsNone(app._editing_mem)
                texts = [e["text"] for e in app._mem.query(ticker="AGA.V", type="note")]
                self.assertIn("silver leadership CONFIRMED", texts)
                self.assertNotIn("silver leadership intact", texts)    # original superseded
                # retract the edited note → it leaves the live rail (audit trail kept)
                cur = app._mem.latest(ticker="AGA.V", type="note")
                app.action_mem_del(cur["id"])
                await pilot.pause(0.05)
                self.assertNotIn("CONFIRMED", text_of(app.query_one("#signalbody")))
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
