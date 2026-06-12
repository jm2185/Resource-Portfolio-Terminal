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


async def open_hub(app, pilot, cat=None):
    """Open the full-screen Hub (where everything agentic now lives) and return it; optionally set the
    board category. Helper for the post-reorg tests."""
    app.action_open_hub(cat=cat or "result")
    await pilot.pause(0.2)
    if cat:
        app.screen.set_cat(cat)
        await pilot.pause(0.1)
    return app.screen


def hub_text(app, sel) -> str:
    """Plain text of a widget inside the currently-open Hub (modal screen)."""
    return text_of(app.screen.query_one(sel))

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


class CostGovernorTests(unittest.TestCase):
    """The model/effort flags on every headless claude spawn — the token-burn governor. A seat's
    registry model must govern the OUTER session too (the subagent pin alone doesn't), background
    jobs default cheap, the Concierge never runs opus, and operator overrides are respected."""

    def setUp(self):
        for k in ("CEX_ASK_CMD", "CEX_PIPELINE_CMD", "CEX_JOB_CMD",
                  "CEX_ASK_EFFORT", "CEX_PIPELINE_EFFORT", "CEX_JOB_EFFORT"):
            os.environ.pop(k, None)

    tearDown = setUp

    @unittest.skipUnless(HAVE_TEXTUAL, "textual not installed")
    def test_spawn_flags(self):
        import commodityex_tui as t
        app = t.Cockpit()
        # plain asks: session-default model, but effort capped at high (not the xhigh default)
        self.assertEqual(app._ask_argv("hi"), ["claude", "-p", "hi", "--effort", "high"])
        # an agent-bound ask runs the seat's registry model
        self.assertIn("--model", app._ask_argv("hi", model="sonnet"))
        # effort="" suppresses the flag entirely (haiku doesn't take --effort)
        self.assertEqual(app._ask_argv("hi", model="haiku", effort=""),
                         ["claude", "-p", "hi", "--model", "haiku"])
        # workflow stages: opus seats run opus, sonnet seats run sonnet END-TO-END…
        self.assertIn("opus", app._pipeline_argv("@verifier x", agent="verifier"))
        self.assertIn("sonnet", app._pipeline_argv("@calibration x", agent="calibration"))
        # …and a gemini seat falling back to Claude runs its honest sonnet fallback
        self.assertIn("sonnet", app._pipeline_argv("@scout x", agent="scout"))
        # scheduled background jobs default CHEAP: sonnet @ medium
        jv = app._job_argv("sweep the book")
        self.assertIn("sonnet", jv)
        self.assertIn("medium", jv)
        # operator overrides win: an explicit --model in the template is never duplicated
        os.environ["CEX_ASK_CMD"] = "claude -p --model opus {prompt}"
        self.assertEqual(app._ask_argv("hi", model="sonnet").count("--model"), 1)
        # a non-claude command (agy, test stubs) is never touched
        os.environ["CEX_ASK_CMD"] = "true"
        self.assertEqual(app._ask_argv("hi", model="sonnet"), ["true", "hi"])


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
            # the always-on conviction card on the spine: engine price surfaced (no FMP needed)
            detail = text_of(app.query_one("#conviction"))
            self.assertIn("price", detail)
            self.assertIn("$0.71", detail)
            # the focused name renders as the conviction card: hero ◆ rating + T/Q/V PillarBars
            self.assertIn("◆", detail)                          # hero ConvictionRating glyph
            self.assertIn("TAILWIND", detail)                   # T/Q/V rendered as labelled bars
            self.assertIn("VALUE", detail)
            self.assertTrue("█" in detail or "─" in detail)     # pillar fill / track glyphs
            self.assertIn("convictioncard", app.query_one("#conviction").classes)
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
            # agents leave a visual trace on the desk: the badge in the HOLDINGS rail
            self.assertIn("REP-floor arb live", text_of(app.query_one("#holdingsbody")))
            # everything agentic now lives in the full-screen Hub (the desk has no side column)
            await open_hub(app, pilot)
            # the autonomy dial is the visible agent-trust boundary (manual · propose · auto ≤ cap)
            auton = hub_text(app, "#autonomy")
            self.assertIn("Autonomy", auton)
            self.assertIn("propose", auton)
            # the unified feed surfaces the pending agent proposal with inline ✓ / ✕
            props = hub_text(app, "#hub_feed")
            self.assertIn("#3", props)
            self.assertIn("rov_default", props)                 # the structured change is readable
            self.assertIn("✓", props)                           # one-click human-gated clearing
            # the roster shows the Claude subagents AND Antigravity, plus a live/idle panes read
            roster = hub_text(app, "#hub_roster")
            self.assertIn("conviction-analyst", roster)
            self.assertIn("antigravity", roster)
            self.assertIn("panes:", roster)
            # the board's Tape category is the nervous-system feed: operator actions (shown as "you")
            # + agent work + the running pipeline
            app.screen.set_cat("activity")
            await pilot.pause(0.1)
            tape = hub_text(app, "#review_list")
            self.assertIn("why is AGA.V rated", tape)           # list clips long titles; detail has the rest
            self.assertIn("you", tape)                          # operator actions framed as "you"
            self.assertIn("git commit", tape)
            # the board's Archive category carries the Living Memory research stream
            app.screen.set_cat("archive")
            await pilot.pause(0.1)
            self.assertTrue(app.screen._items or "Archive" in hub_text(app, "#review_head"))
            await pilot.press("escape")                         # back to the desk
            await pilot.pause(0.1)
            # structured UI commands drive the cockpit: switch_tab + apply_scenario summon lenses
            from textual.widgets import Collapsible, Input as _In
            app._handle_agent_command({"ui_command": {"seq": 90, "action": "switch_tab", "args": {"view": "regime"}}})
            await pilot.pause(0.1)
            self.assertFalse(app.query_one("#lens_regime", Collapsible).collapsed)   # the lens is summoned
            self.assertIn("UST curve", text_of(app.query_one("#regime")))    # FMP treasury curve wired in
            app._handle_agent_command({"ui_command": {"seq": 91, "action": "apply_scenario",
                                                      "args": {"ticker": "AGA.V", "overrides": "silver=+8"}}})
            await pilot.pause(0.3)
            self.assertFalse(app.query_one("#lens_whatif", Collapsible).collapsed)
            self.assertIn("silver=+8", app.query_one("#wf_overrides", _In).value)
            # the dashboard is promptable: the spine points at the chat + the Hub door
            conv = text_of(app.query_one("#agent_reply"))
            self.assertIn("Ask anything below", conv)
            self.assertIn("open Hub", conv)
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
            # threads bind to an EXPLICIT subject (never the global focus implicitly)
            app._ask_agent("why is AGA.V cheap?", ticker="AGA.V")
            await pilot.pause(0.2)
            self.assertEqual(app._asked, "why is AGA.V cheap?")
            # the spine shows the thread's LATEST turn + the door; the full transcript is the Hub's
            conv = text_of(app.query_one("#agent_reply"))
            self.assertIn("latest research - AGA.V", conv)     # the ask landed on the focused name
            self.assertIn("‹", conv)                           # the reply turn is visible
            self.assertIn("continue in Hub", conv)
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
            # regression (wrong-thread bug): a LATE-finishing reply must land under the exact question
            # that asked it, even if a newer question is now pending/active. The old poll-fold bound the
            # answer to the global _pending_user, so it surfaced only on the next keystroke and dropped
            # into the wrong thread. _deliver_reply binds to the question's uid instead.
            q_old = app._new_node("you", "slow Q about GROY", None)
            app._pending_user = q_old; app._active = q_old
            q_new = app._new_node("you", "fast Q about GMX", None)
            app._pending_user = q_new; app._active = q_new      # a newer ask is now the pending one
            app._deliver_reply(q_old, "the slow GROY answer", "claude")
            old_kids = [n for n in app._conv.values() if n.get("parent") == q_old and n["role"] == "agent"]
            new_kids = [n for n in app._conv.values() if n.get("parent") == q_new and n["role"] == "agent"]
            self.assertEqual([n["text"] for n in old_kids], ["the slow GROY answer"])  # under Q_old ✓
            self.assertEqual(new_kids, [])                       # NOT mis-filed under the newer Q_new
            self.assertEqual(app._pending_user, q_new)           # newer ask still waiting (not clobbered)
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
            # summon every lens onto the spine (regime + detail + grid + what-if render without error)
            for tab in ("regime_tab", "dossier_tab", "profile_tab", "whatif", "grid", "book"):
                app.action_tab(tab)
                await pilot.pause(0.1)
            # the regime lens built its research view
            self.assertIn("REGIME", text_of(app.query_one("#regime")))
            self.assertIn("MRI components", text_of(app.query_one("#regime")))
            # Council convenes INLINE on the spine (not a lens): convening EXPANDS the debate above the
            # SHARED conversation — grounded in the engine asymmetry, not a navigation.
            app._set_focus("AGA.V")
            app.action_go_council()
            await pilot.pause(0.1)
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
            self.assertIn("latest research", collapsed)        # the research strip is still there
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
            # the AGENTS WORKING card lives in the Hub now
            await open_hub(app, pilot)

            # --- WORKING lane: in-flight runs are visible in the unified feed (label · ✗) ---
            app._render_hub_feed()
            strip = hub_text(app, "#hub_feed")
            self.assertIn("WORKING", strip)
            self.assertIn("pipeline", strip)           # the running fixture pipeline is surfaced here
            jid = app._inflight_add("ask", "why is AGA.V cheap?", "AGA.V")
            app._render_hub_feed()
            await pilot.pause(0.05)
            strip = hub_text(app, "#hub_feed")
            self.assertIn("why is AGA.V cheap?", strip)
            self.assertIn("✗", strip)                  # the cancel affordance
            # cancelling stops waiting on the run — it leaves the feed
            app.action_cancel_job(jid)
            app._render_hub_feed()
            await pilot.pause(0.05)
            self.assertTrue(app._inflight[jid]["cancelled"])
            self.assertNotIn("why is AGA.V cheap?", hub_text(app, "#hub_feed"))

            # --- action receipts + undo: a note emits a receipt; undo supersedes it (immutably) ---
            import tempfile
            import living_memory
            tmp = tempfile.mktemp(suffix=".jsonl")
            app._mem = living_memory.LivingMemory(path=tmp)
            try:
                app._set_focus("AGA.V")
                app._write_note("Nevada permitting fast", "AGA.V")
                app._render_hub_feed()
                await pilot.pause(0.05)
                ag = hub_text(app, "#hub_feed")
                self.assertIn("RECEIPTS", ag)
                self.assertIn("note", ag)
                self.assertIn("↶", ag)                 # the note is reversible (undo glyph)
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
                # memory now lives in the Hub board (Memory category) — read in full + manage there
                await open_hub(app, pilot, cat="memory")
                lst = hub_text(app, "#review_list")
                self.assertIn("silver leadership", lst)
                self.assertIn("ancient", lst)
                # select the fresh note → full text + provenance (by you) in the detail
                app.screen.select(0)
                await pilot.pause(0.05)
                det = hub_text(app, "#review_md")
                self.assertIn("silver leadership intact", det)
                self.assertIn("by", det)
                # the ancient note decays → 'stale' + a re-confirm affordance in its detail
                si = next(i for i, it in enumerate(app.screen._items) if "ancient" in it.get("title", ""))
                app.screen.select(si)
                await pilot.pause(0.05)
                self.assertIn("stale", hub_text(app, "#review_md"))
                self.assertIn("re-confirm", hub_text(app, "#review_actions"))
                # pin the fresh note → marked 📌 in the list
                app.action_mem_pin(a["id"])
                app.screen.reload()
                await pilot.pause(0.05)
                self.assertEqual(app._mem.pinned_ids(), {a["id"]})
                self.assertIn("📌", hub_text(app, "#review_list"))
                # edit from the board → loads the chat bar; saving supersedes the original (immutable edit)
                si = next(i for i, it in enumerate(app.screen._items) if it.get("ref") == a["id"])
                app.screen.select(si)
                app.action_review_do("edit")
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
                # retract the edited note → it leaves the live stream (audit trail kept)
                cur = app._mem.latest(ticker="AGA.V", type="note")
                app.action_mem_del(cur["id"])
                await pilot.pause(0.05)
                self.assertNotIn("CONFIRMED", [e["text"] for e in app._mem.query(ticker="AGA.V", type="note")])
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    async def test_reorg_spine_lenses_and_agent_column(self):
        """The two-up reorg: the five tabs collapse to a spine + inline lenses, macro is always on,
        the rail splits into Holdings + an open Watchlist, and the agent column gains the autonomy
        dial + one-click proposals. Everything shipped survives; the container changed."""
        import importlib
        import commodityex_tui as t
        importlib.reload(t)
        os.environ["CEX_ASK_CMD"] = "true"
        os.environ["CEX_PIPELINE_CMD"] = "true"
        from textual.widgets import Collapsible
        app = t.Cockpit()
        async with app.run_test(size=(180, 55)) as pilot:
            await pilot.pause(0.4)
            # the detail cards (Regime · Name · What-If) are always-on in the right column (expanded);
            # the Book Grid is hotkey-toggled and hidden by default
            for lid in ("lens_whatif", "lens_regime", "lens_dossier"):
                self.assertFalse(app.query_one(f"#{lid}", Collapsible).collapsed)
            self.assertFalse(app.query_one("#lens_grid", Collapsible).display)   # invisible until `g`
            self.assertEqual(app._current_view(), "book")
            # `g` toggles the Book Grid into view
            app.action_grid()
            await pilot.pause(0.05)
            self.assertTrue(app.query_one("#lens_grid", Collapsible).display)
            app.action_grid()
            await pilot.pause(0.05)
            self.assertFalse(app.query_one("#lens_grid", Collapsible).display)
            # the action_tab SHIM keeps every old caller working — it scrolls the card + reports the view
            app.action_tab("whatif")
            await pilot.pause(0.05)
            self.assertFalse(app.query_one("#lens_whatif", Collapsible).collapsed)
            self.assertEqual(app._current_view(), "whatif")
            # always-on regime frame above the spine (ends the status/regime/signals triplication)
            self.assertIn("REGIME", text_of(app.query_one("#regime_panel")))
            self.assertIn("MRI", text_of(app.query_one("#regime_panel")))
            # left rail is split: Holdings = the rated book; Watchlist = a door (search → scout)
            self.assertIn("AGA.V", text_of(app.query_one("#holdingsbody")))
            self.assertIn("scout", text_of(app.query_one("#watchbody")))   # empty-state invites scouting
            # the watchlist search box is a door: a holding focuses, a theme scouts (headless 'true')
            app._watch_search("GROY")
            self.assertEqual(app._focus, "GROY")
            app._watch_search("silver developers")
            await pilot.pause(0.1)
            self.assertEqual(app._watch_query, "silver developers")
            self.assertIn("scanning", text_of(app.query_one("#watchbody")))
            # --- the Hub holds everything agentic now (the side column was removed) ---
            from textual.css.query import NoMatches
            with self.assertRaises(NoMatches):
                app.query_one("#agents")                # no side column on the desk
            await open_hub(app, pilot)
            # the autonomy dial is the visible trust boundary
            self.assertEqual(app._autonomy, "propose")
            app.action_autonomy("manual")
            await pilot.pause(0.05)
            self.assertEqual(app._autonomy, "manual")
            self.assertIn("manual", hub_text(app, "#autonomy"))
            self.assertTrue(any("autonomy" in str(r["text"]) for r in app._receipts))  # dial posts a receipt
            # one-click proposal clearing (reuses the human-gated confirm path)
            props = hub_text(app, "#hub_feed")
            self.assertIn("#3", props)
            self.assertIn("✓", props)
            self.assertIn("skip", props)
            app.action_confirm_prop(3)
            await pilot.pause(0.3)
            self.assertIn("confirmed #3", text_of(app.query_one("#wf_status")))
            # 'why' on a proposal routes a grounded question to the agents
            app.action_prop_why(3)
            await pilot.pause(0.1)
            self.assertIn("proposal #3", app._asked)

    async def test_agent_hub(self):
        """The Hub's control cards: ROSTER (Claude subagents + Antigravity + PANES), COMMANDS (saved
        templates), RECURRING, ENGINE AUDIT. Dispatch runs on the focus and closes the Hub; the saved-
        command store round-trips."""
        import importlib
        import tempfile
        import commodityex_tui as t
        importlib.reload(t)
        os.environ["CEX_ASK_CMD"] = "true"
        app = t.Cockpit()
        async with app.run_test(size=(180, 55)) as pilot:
            await pilot.pause(0.4)
            tmp = tempfile.mktemp(suffix=".json")
            app._hub_commands_path = lambda: tmp        # isolate the saved-command store from the repo
            try:
                await open_hub(app, pilot)
                self.assertIsInstance(app.screen, t.HubScreen)
                self.assertIn("conviction-analyst", hub_text(app, "#hub_roster"))   # from .claude/agents
                self.assertIn("antigravity", hub_text(app, "#hub_roster"))          # the Gemini red-team
                self.assertIn("panes:", hub_text(app, "#hub_roster"))               # live/idle read
                self.assertIn("bear", hub_text(app, "#hub_commands"))               # a default command
                self.assertIn("ENGINE AUDIT", hub_text(app, "#hub_audit"))          # the fetch·verify·review card
                # dispatch an agent on the focus (AGA.V at boot) → headless ask; the hub closes
                app.action_hub_run_agent("bear")
                await pilot.pause(0.2)
                self.assertNotIsInstance(app.screen, t.HubScreen)
                self.assertIn("AGA.V", app._asked)
                # save a command, run it ({ticker} → focus), then delete it (defaults are not deletable)
                app._hub_save_command("dilution = check {ticker} share count vs last filing")
                self.assertIn("dilution", app._user_commands())
                app._set_focus("GROY")
                app.action_hub_run_command("dilution")
                await pilot.pause(0.2)
                self.assertIn("GROY", app._asked)
                self.assertIn("share count", app._asked)
                app.action_hub_del_command("dilution")
                self.assertNotIn("dilution", app._user_commands())
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    async def test_whatif_ab_pinning(self):
        """A/B pinning in the What-If lens: pin a scenario as baseline A, then later runs show Δ vs A
        (not just vs base) — pin a thesis, step the knobs to a variant, read the difference."""
        import importlib
        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.4)
            app.action_tab("whatif")
            await pilot.pause(0.05)
            app._run_command("/whatif AGA.V silver=+5")
            await pilot.pause(0.8)
            res = text_of(app.query_one("#wf_result"))
            self.assertIn("Δ intrinsic", res)
            self.assertIn("pin this as A/B baseline", res)        # affordance shown before pinning
            # pin the current scenario as A → the result re-renders with the A/B comparison row
            app.action_wf_pin()
            await pilot.pause(0.1)
            self.assertIsNotNone(app._wf_pinned)
            self.assertEqual(app._wf_pinned["intrinsic"], 1.18)   # captured from the stub scenario
            ab = text_of(app.query_one("#wf_result"))
            self.assertIn("A/B", ab)
            self.assertIn("vs A", ab)
            self.assertIn("unpin", ab)
            # unpin restores the single-focus view
            app.action_wf_unpin()
            await pilot.pause(0.1)
            self.assertIsNone(app._wf_pinned)
            self.assertIn("pin this as A/B baseline", text_of(app.query_one("#wf_result")))

    async def test_scheduler_recurring_jobs(self):
        """Recurring agent work governed by the autonomy dial: manual pauses, propose queues a
        one-click ✓ job-run, auto runs headless. Jobs emit a REVIEW DRAFT + a Living-Memory note —
        they improve the terminal (scout/backtest/verify/brainstorm/build) but never auto-commit."""
        import glob
        import importlib
        import shutil
        import tempfile
        import commodityex_tui as t
        importlib.reload(t)
        os.environ["CEX_JOB_CMD"] = "true"             # stub the headless job runner (offline, fast)
        import living_memory
        app = t.Cockpit()
        async with app.run_test(size=(170, 55)) as pilot:
            await pilot.pause(0.4)
            jtmp = tempfile.mktemp(suffix=".json"); dtmp = tempfile.mkdtemp()
            mtmp = tempfile.mktemp(suffix=".jsonl")
            app._jobs_path = lambda: jtmp              # isolate the job store + drafts + memory
            app._drafts_dir = lambda: dtmp
            app._jobs = None
            app._mem = living_memory.LivingMemory(path=mtmp)
            try:
                # add a scouting job (and prove the Hub 'job …' add syntax works)
                j = app._add_job("scout", "silver juniors", every_min=60)
                app._hub_add_job("build a uranium royalty agent @4320")
                self.assertEqual(len(app._load_jobs()), 2)

                # propose (default): a due job queues a ✓-able proposal — it does NOT run
                app._autonomy = "propose"
                j["next_due"] = 0; app._save_jobs(app._jobs)
                app._scheduler_tick()
                await pilot.pause(0.05)
                self.assertTrue(any(p["job_id"] == j["id"] for p in app._job_proposals))
                await open_hub(app, pilot)             # due-job proposals live in the Hub feed
                app._render_hub_feed()
                props = hub_text(app, "#hub_feed")
                self.assertIn("due:", props)
                self.assertIn("run", props); self.assertIn("skip", props)
                self.assertEqual(glob.glob(os.path.join(dtmp, "*.md")), [])     # nothing ran yet

                # approve → runs headless, writes a review draft + a recallable memory note
                app.action_job_run(j["id"])
                drafts = []
                for _ in range(40):                         # poll: the draft is written by a bg worker
                    drafts = glob.glob(os.path.join(dtmp, "*.md"))
                    if drafts:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(drafts)
                self.assertIn("review draft", open(drafts[0]).read())
                self.assertTrue(any("scheduled scout" in e["text"] for e in app._mem.query(type="note")))
                self.assertFalse(any(p["job_id"] == j["id"] for p in app._job_proposals))

                # auto: a due job runs with no proposal
                j2 = app._add_job("backtest", "AGA.V", every_min=60)
                j2["next_due"] = 0; app._save_jobs(app._jobs)
                app._autonomy = "auto"; app._scheduler_tick()
                await pilot.pause(0.4)
                self.assertFalse(any(p["job_id"] == j2["id"] for p in app._job_proposals))
                self.assertTrue(glob.glob(os.path.join(dtmp, "backtest_*.md")))

                # manual: a due job is paused — no proposal, no run
                j3 = app._add_job("verify", "catalysts", every_min=60)
                j3["next_due"] = 0; app._save_jobs(app._jobs)
                app._autonomy = "manual"; app._scheduler_tick()
                await pilot.pause(0.05)
                self.assertFalse(any(p["job_id"] == j3["id"] for p in app._job_proposals))
                self.assertEqual(glob.glob(os.path.join(dtmp, "verify_*.md")), [])

                # the Hub SCHEDULED lane lists the recurring jobs
                if not isinstance(app.screen, t.HubScreen):
                    await open_hub(app, pilot)
                app.screen.refresh_cards()
                await pilot.pause(0.1)
                rec = hub_text(app, "#hub_recurring")
                self.assertIn("SCHEDULED", rec)
                self.assertIn("silver juniors", rec)
            finally:
                for p in (jtmp, mtmp):
                    if os.path.exists(p):
                        os.remove(p)
                shutil.rmtree(dtmp, ignore_errors=True)

    async def test_notes_and_memory_open_in_full(self):
        """Agent notes and saved memory are no longer read-only dead-ends: opening one shows the FULL
        entry (read + provenance + act); the board's Tape category drops routine get_ reads as noise."""
        import importlib
        import tempfile
        import commodityex_tui as t
        importlib.reload(t)
        import living_memory
        app = t.Cockpit()
        async with app.run_test(size=(190, 55)) as pilot:
            await pilot.pause(0.4)
            # AGENT NOTE opens in full (fixture has AGA.V annotation seq 5) — works from anywhere
            app.action_anno("5")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, t.InspectScreen)
            self.assertIn("REP-floor arb live", text_of(app.screen.query_one("#inspect_body")))
            app.action_focus_tk("AGA.V")               # acting from the pop-over closes it
            await pilot.pause(0.1)
            self.assertNotIsInstance(app.screen, t.InspectScreen)

            # saved memory opens in FULL (text + provenance); pin from the pop-over closes it
            tmp = tempfile.mktemp(suffix=".jsonl")
            app._mem = living_memory.LivingMemory(path=tmp)
            try:
                long_note = ("Nevada permitting is materially faster than Canadian peers; this is the "
                             "swing factor for the spear's optionality and why the floor holds.")
                e = app._mem.write("note", text=long_note, ticker="AGA.V",
                                   regime={"mri": 47, "posture": "spear_exploit"}, source="you")
                app.action_mem_open(e["id"])
                await pilot.pause(0.1)
                self.assertIsInstance(app.screen, t.InspectScreen)
                full = text_of(app.screen.query_one("#inspect_body"))
                self.assertIn("materially faster", full)        # the WHOLE text, not a teaser
                self.assertIn("captured under", full)           # provenance + regime surfaced
                app.action_mem_pin(e["id"])             # manage from inside the pop-over → closes + pins
                await pilot.pause(0.1)
                self.assertNotIsInstance(app.screen, t.InspectScreen)
                self.assertIn(e["id"], app._mem.pinned_ids())
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

            # the board's Tape category is signal-only — routine read-only agent calls are dropped
            app._state["agent_activity"] = [
                {"seq": 1, "ts": 0, "agent": "claude", "kind": "prompt", "summary": "why is AGA.V cheap?", "ticker": "AGA.V"},
                {"seq": 2, "ts": 0, "agent": "claude", "kind": "tool", "summary": "get_config_values", "ticker": None},
                {"seq": 3, "ts": 0, "agent": "claude", "kind": "tool", "summary": "get_conviction_ratings", "ticker": None},
                {"seq": 4, "ts": 0, "agent": "operator", "kind": "git", "summary": "git commit -m fix", "ticker": None},
            ]
            await open_hub(app, pilot, cat="activity")
            tape = hub_text(app, "#review_list")
            self.assertNotIn("get_config_values", tape)         # routine reads don't clutter the feed
            self.assertIn("why is AGA.V cheap?", tape)          # the signal stays
            self.assertIn("git commit", tape)                   # operator action kept

    async def test_review_room(self):
        """The Review room (key `v`): a full-screen master-detail reader unifying Living Memory,
        scheduled-job results, research/dossiers and threads — read the FULL entry and act
        (focus · pin · discard) without the cramped chat. The reading surface."""
        import glob
        import importlib
        import shutil
        import tempfile
        import commodityex_tui as t
        importlib.reload(t)
        os.environ["CEX_ASK_CMD"] = "true"
        import living_memory
        app = t.Cockpit()
        async with app.run_test(size=(190, 55)) as pilot:
            await pilot.pause(0.4)
            repo = os.path.dirname(os.path.abspath(t.__file__))
            dtmp = tempfile.mkdtemp(); mtmp = tempfile.mktemp(suffix=".jsonl")
            app._drafts_dir = lambda: dtmp
            app._mem = living_memory.LivingMemory(path=mtmp)
            try:
                open(os.path.join(dtmp, "build_uranium_agent_20260606-101010.md"), "w").write(
                    "# Draft: uranium agent\n\nproposed spec + patch")
                note = app._mem.write(
                    "note", text="Nevada permitting materially faster than peers — swing factor",
                    ticker="AGA.V", regime={"mri": 47, "posture": "spear_exploit"}, source="you")
                app._ask_agent("why is AGA.V cheap?")          # creates a thread item
                await pilot.pause(0.2)
                # `v` opens the Blend home; the classic reader stays one click away in its footer
                app.set_focus(None)
                await pilot.press("v")
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, t.BlendHubScreen)
                self.assertIn("mission control", text_of(app.screen.query_one("#blend_foot")))
                await pilot.press("escape")
                await pilot.pause(0.1)
                app.action_open_hub_classic()
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, t.HubScreen)
                self.assertIn("Archive", text_of(app.screen.query_one("#review_head")))
                # Archive: the WHOLE note + provenance (not a 24-char teaser)
                app.screen.open_ref("archive", note["id"])
                await pilot.pause(0.1)
                md = text_of(app.screen.query_one("#review_md"))
                self.assertIn("materially faster", md)
                self.assertIn("captured under", md)
                # the job draft's full content + verify actions (drafts live on the Archive board)
                draft = os.path.join(dtmp, "build_uranium_agent_20260606-101010.md")
                app.screen.open_ref("archive", draft)
                await pilot.pause(0.1)
                self.assertIn("proposed spec", text_of(app.screen.query_one("#review_md")))
                self.assertIn("discard", text_of(app.screen.query_one("#review_actions")))
                # Threads: the conversation as a readable transcript
                app.screen.set_cat("threads")
                await pilot.pause(0.1)
                self.assertIn("why is AGA.V cheap?", text_of(app.screen.query_one("#review_md")))
                # act from the room: pin a memory entry (reloads in place)
                app.screen.open_ref("archive", note["id"])
                await pilot.pause(0.05)
                app.action_review_do("pin")
                await pilot.pause(0.1)
                self.assertTrue(app._mem.pinned_ids())
                # discard a result file from the room
                app.screen.open_ref("archive", draft)
                await pilot.pause(0.05)
                app.action_review_do("discard")
                await pilot.pause(0.1)
                self.assertEqual(glob.glob(os.path.join(dtmp, "*.md")), [])
                # focus-from-review closes the room and lands on the name
                app.screen.open_ref("archive", note["id"])
                await pilot.pause(0.05)
                app.action_review_do("focus")
                await pilot.pause(0.1)
                self.assertNotIsInstance(app.screen, t.HubScreen)
                self.assertEqual(app._focus, "AGA.V")
            finally:
                shutil.rmtree(dtmp, ignore_errors=True)
                if os.path.exists(mtmp):
                    os.remove(mtmp)

    async def test_agent_assignment(self):
        """You can assign a specific agent to a task: `job <agent> <topic>` or `… by <agent>`, or the
        roster's ⏱ affordance. The job carries the agent; launching it dispatches to that agent
        (a Claude subagent via @name, or Antigravity via the agy CLI)."""
        import importlib
        import tempfile
        import commodityex_tui as t
        importlib.reload(t)
        os.environ["CEX_JOB_CMD"] = "true"
        from textual.widgets import Input as _In
        app = t.Cockpit()
        async with app.run_test(size=(180, 55)) as pilot:
            await pilot.pause(0.4)
            jtmp = tempfile.mktemp(suffix=".json")
            app._jobs_path = lambda: jtmp
            app._jobs = None
            try:
                # `job <agent> <topic>` assigns that agent a generic task
                app._hub_add_job("bear AGA.V dilution risk")
                bj = next(j for j in app._load_jobs() if j.get("agent") == "bear")
                self.assertEqual(bj["kind"], "ask")
                self.assertIn("AGA.V", bj["topic"])
                # `… by <agent>` assigns an agent to a templated kind
                app._hub_add_job("audit thresholds by data-integrity-auditor")
                aj = next(j for j in app._load_jobs() if j.get("kind") == "audit")
                self.assertEqual(aj["agent"], "data-integrity-auditor")
                # launching an agent-assigned job dispatches to that subagent (@name prefix)
                cap = {}

                def fake_job_argv(prompt):
                    cap["p"] = prompt
                    return ["true"]
                app._job_argv = fake_job_argv
                app._launch_job(bj)
                await pilot.pause(0.3)
                self.assertTrue(cap["p"].startswith("@bear"))
                self.assertIn("AGA.V", cap["p"])
                # the roster's ⏱ assign affordance pre-fills the input for a chosen agent
                app._set_focus("GROY")
                await open_hub(app, pilot)
                app.action_hub_assign("scout")
                self.assertIn("by scout", app.screen.query_one("#hub_input", _In).value)
                # an Antigravity-assigned task routes through the agy CLI, not CEX_JOB_CMD
                cap2 = {}

                def fake_agy_argv(prompt):
                    cap2["p"] = prompt
                    return ["true"]
                app._agy_argv = fake_agy_argv
                ag = app._add_job("ask", "red-team URC.TO", agent="antigravity")
                app._launch_job(ag)
                await pilot.pause(0.3)
                self.assertIn("red-team URC.TO", cap2["p"])
                self.assertFalse(cap2["p"].startswith("@"))   # antigravity isn't an @-subagent
            finally:
                if os.path.exists(jtmp):
                    os.remove(jtmp)


@unittest.skipUnless(HAVE_TEXTUAL, "textual not installed")
class DisconfirmByDefaultTests(unittest.IsolatedAsyncioTestCase):
    """H4 — composing an advocate auto-offers a one-click red-team foil, and accepting chains it."""

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

    async def test_advocate_offers_disconfirm_and_chains_foil(self):
        import importlib
        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause(0.3)
            await open_hub(app, pilot)
            scr = app.screen
            # composing an ADVOCATE (bull) surfaces the one-click disconfirm chip in the composer
            scr._c_agent, scr._c_verb, scr._c_subject = "bull", "ask", "AGA.V"
            markup = app._hub_composer_markup()
            self.assertIn("hub_wf_disconfirm", markup)
            self.assertIn("disconfirm", markup)
            # accepting it builds a 2-stage chain: advocate -> independent red-team foil
            app._workflow = []
            app.action_hub_wf_disconfirm()
            self.assertEqual(len(app._workflow), 2)
            self.assertEqual(app._workflow[0]["agents"], ["bull"])
            self.assertIn(app._workflow[1]["agents"][0], ("bear", "antigravity"))
            self.assertIn("WRONG", app._workflow[1]["note"])          # framed as a pre-mortem
            # a NON-advocate (bear) gets no disconfirm chip (don't disconfirm the disconfirmer)
            scr._c_agent = "bear"
            self.assertNotIn("hub_wf_disconfirm", app._hub_composer_markup())


@unittest.skipUnless(HAVE_TEXTUAL, "textual not installed")
class BlendPainterTests(unittest.TestCase):
    """The Blend's hand-painted connectors (Textual routes no edges) — pure + deterministic."""

    def test_fan_out_junction_and_corners(self):
        import commodityex_tui as t
        grid = t.paint_fan([2, 8], 5, "out")
        self.assertEqual(grid[5], "──┤  ")                  # incoming trunk splits with ┤
        self.assertEqual(grid[2], "  ╭─→")                  # upper lane turns with ╭
        self.assertEqual(grid[8], "  ╰─→")                  # lower lane turns with ╰
        for r in (3, 4, 6, 7):
            self.assertEqual(grid[r], "  │  ")              # the vertical trunk between lanes

    def test_fan_in_mirrors(self):
        import commodityex_tui as t
        grid = t.paint_fan([2, 8], 5, "in")
        self.assertEqual(grid[5], "  ├─→")                  # lanes merge with ├, exit right
        self.assertEqual(grid[2], "──╮  ")                  # upper lane turns in with ╮
        self.assertEqual(grid[8], "──╯  ")                  # lower lane turns in with ╯

    def test_fan_is_deterministic(self):
        import commodityex_tui as t
        self.assertEqual(t.paint_fan([1, 7], 4, "out"), t.paint_fan([7, 1], 4, "out"))

    def test_chain_canvas_paints_topology_and_state(self):
        """target → scout → (value ∥ balance) → verifier → synthesis → DOSSIER, with the running
        node carrying a live bar and the done node a ✓ — the §05 visual target."""
        import io as _io

        import commodityex_tui as t
        from rich.console import Console
        stages = [{"agents": ["scout"]}, {"agents": ["value-analyst", "balance-sheet-analyst"]},
                  {"agents": ["verifier"]}, {"agents": ["synthesis"]}]
        states = {(0, "scout"): "done", (1, "value-analyst"): "running",
                  (1, "value-analyst", "pct"): 0.5, (1, "balance-sheet-analyst"): "running",
                  (2, "verifier"): "queued", (3, "synthesis"): "queued"}
        con = Console(width=220, file=_io.StringIO(), color_system=None)
        con.print(t._blend_chain_canvas(stages, states, target="AGA.V", target_role="spear"))
        out = con.file.getvalue()
        for token in ("AGA.V", "target", "SCOUT", "✓ done", "VALUE-ANALYST", "BALANCE-SHEET",
                      "⚙", "█", "VERIFIER", "queued", "DOSSIER", "┤", "├", "╭", "╰", "──→"):
            self.assertIn(token, out)
        # rounded card corners survive (border style, not CSS radius)
        self.assertIn("╭─", out)
        self.assertIn("╰─", out)


@unittest.skipUnless(HAVE_TEXTUAL, "textual not installed")
class BlendHubTests(unittest.IsolatedAsyncioTestCase):
    """Agent Hub v2 — THE BLEND. Quest Log home, surfaces opening out of it, the Roster drawer,
    the read-only Concierge, and the mouse+key interaction contract."""

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

    @staticmethod
    def _seed_thread(app):
        """A research thread with one fork (two switchable continuations)."""
        r = app._new_node("you", "Open AGA.V — is the spear still convex?", None)
        app._conv[r]["ticker"] = "AGA.V"
        a1 = app._new_node("agent", "Conviction 8.2 · BELOW FLOOR — accumulate.", r,
                           agent="conviction-analyst")
        b1 = app._new_node("you", "Stress it — silver down 20%.", a1)
        app._new_node("agent", "Floor holds to $0.61; 18mo runway absorbs it.", b1,
                      agent="balance-sheet-analyst")
        b2 = app._new_node("you", "Steelman the bear.", a1)
        app._new_node("agent", "Dilution risk + a binary 7d catalyst.", b2, agent="bear")
        return r

    async def test_quest_log_home_three_rails(self):
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            self._seed_thread(app)
            app._done_runs.insert(0, {"id": 90, "agent": "arbiter", "subject": "AGA.V vs SILV",
                                      "summary": "AGA.V wins asymmetry — HOLD", "cat": "result",
                                      "ref": None, "ts": 9e9})
            app.set_focus(None)
            await pilot.press("h")                         # h → the Blend is the hub home
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.BlendHubScreen)
            # LAUNCH rail: target chips + chain verbs + 1v1 + fleet browse, all click targets
            launch = text_of(app.screen.query_one("#blend_launch_body"))
            self.assertIn("LAUNCH", launch)
            self.assertIn("AGA.V", launch)
            self.assertIn("MATCHUP BENCH", launch)
            self.assertIn("DEEP DOSSIER", launch)
            self.assertIn("BROWSE FLEET", launch)
            # QUEST LOG: the engine's running pipeline + the thread + the matchup, one stream
            log = text_of(app.screen.query_one("#blend_log"))
            self.assertIn("silver juniors", log)           # stub /state pipeline, running
            self.assertIn("matchup", log)                  # the old kind survives as the sub-tag
            self.assertIn("open thread", log)
            self.assertIn("party", log)                    # who worked it, model on each
            # the feed reads as THREE calm groups (RUN · FLAG · NOTE); a live run is bright with
            # the 'live' sub-tag, a finished run earns ✓, the old kind rides as a dim sub-tag
            self.assertIn("⚙ RUN", log)
            self.assertIn("✓ RUN", log)
            self.assertIn("ask", log)                      # ask survives as a sub-tag
            # the kind-style helper is the single source of that identity (color·glyph·label·sub)
            self.assertEqual(t._blend_kind_style("matchup")[2:], ("RUN", "matchup"))
            self.assertEqual(t._blend_kind_style("dossier", "done")[1:], ("✓", "RUN", "dossier"))
            self.assertEqual(t._blend_kind_style("note")[1:], ("✎", "NOTE", ""))
            self.assertEqual(t._blend_kind_style("ask", "running")[2:], ("RUN", "live"))
            self.assertEqual(t._blend_kind_style("ask", "running")[0], t.AMBER_BRIGHT)
            self.assertEqual(t._blend_kind_style("flag", level="warn")[0], t.ORANGE)
            self.assertEqual(t._blend_kind_style("flag", level="warn")[3], "warn")
            # WORKING lane: the live pipeline row
            lane = text_of(app.screen.query_one("#blend_lane_body"))
            self.assertIn("WORKING LANE", lane)
            self.assertIn("pipeline", lane)
            # filters: key cycles · click sets (both ship — the interaction-matrix gate)
            await pilot.press("f")
            self.assertEqual(app.screen._filter, "working")
            app.action_blend_filter("matchups")
            self.assertEqual(app.screen._filter, "matchups")
            self.assertTrue(all(i["kind"] == "matchup" for i in app.screen._items))
            # the demoted command bar — hidden until `/`
            self.assertFalse(app.screen.query_one("#blend_cmd").has_class("open"))
            await pilot.press("slash")
            self.assertTrue(app.screen.query_one("#blend_cmd").has_class("open"))
            # footer keeps the classic mission control one click away (nothing uprooted)
            self.assertIn("mission control", text_of(app.screen.query_one("#blend_foot")))

    async def test_surfaces_open_out_of_the_log(self):
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            root = self._seed_thread(app)
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            scr = app.screen
            # a log row opens its THREAD — linear narrative + the track-switch at the fork
            idx = next(i for i, it in enumerate(scr._items) if it.get("opens") == "thread")
            app.action_blend_open(idx)
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.ThreadSurface)
            body = text_of(app.screen.query_one("#th_body"))
            self.assertIn("YOU · ASK", body)
            self.assertIn("BRANCH POINT", body)
            self.assertIn("compare all", body)
            before = app.screen._active
            await pilot.press("b")                         # key mirror of the pill click
            self.assertNotEqual(app.screen._active, before)
            app.action_thread_branch(0)                    # the click affordance
            self.assertEqual(app.screen._active, 0)
            # ⊞ compare borrows the Matchup idiom on the branch ENDPOINTS
            app.action_thread_compare()
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.CompareSurface)
            cmp_body = text_of(app.screen.query_one("#cmp_body"))
            self.assertIn("ENDS AT", cmp_body)
            self.assertIn("open branch", cmp_body)
            app.action_compare_open(1)                     # promote a branch → back to the thread
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.ThreadSurface)
            self.assertEqual(app.screen._active, 1)
            await pilot.press("escape")
            await pilot.pause(0.1)
            # PIPELINE: nodes + hand-painted fan-out + the action row with key mirrors
            app.action_blend_open_pipeline()
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.PipelineSurface)
            # the stub engine reports a RUNNING pipeline (stage: verifier) — the surface binds to
            # it live: scout/synthesis done, verifier pulsing, theme as the target
            canvas = text_of(app.screen.query_one("#pipe_canvas"))
            self.assertIn("silver juniors", canvas)
            self.assertIn("SCOUT", canvas)
            self.assertIn("✓ done", canvas)
            self.assertIn("⚙", canvas)                     # the live node's bar
            self.assertIn("DOSSIER", canvas)
            await pilot.press("right")                     # ◂ ▸ inspect a stage
            self.assertEqual(app.screen._sel, 0)
            self.assertIn("stage 1", text_of(app.screen.query_one("#pipe_detail")))
            await pilot.press("escape")
            await pilot.pause(0.1)
            # ROSTER drawer: model + purpose on every card; ⛓ chain appends a stage
            await pilot.press("r")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.RosterSurface)
            roster = text_of(app.screen.query_one("#roster_body"))
            self.assertIn("DIALECTIC COUNCIL", roster)
            self.assertIn("◇opus", roster)
            self.assertIn("▶ run", roster)
            app._workflow = []
            app.action_roster_chain("verifier")
            self.assertEqual(app._workflow[-1]["agents"], ["verifier"])
            await pilot.press("escape")
            await pilot.pause(0.1)
            # MATCHUP: holding side carries live engine numbers (ρ, upside) before any run
            app.action_blend_matchup("SILV")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.MatchupSurface)
            tbl = text_of(app.screen.query_one("#mu_table"))
            self.assertIn("Conviction", tbl)
            self.assertIn("8.2", tbl)                      # AGA.V engine rating, holding column
            self.assertIn("2.30×", tbl)                    # ρ from the live basket
            self.assertIn("not grounded yet", tbl)         # honest about the outsider

    def test_matchup_score_parsing(self):
        """The agents' SCORE block is parsed back into per-ticker metrics — the bridge that fills
        outsider columns the engine can't rate. Tolerant of pipes, signs, and '—'."""
        import commodityex_tui as t
        sc = t.Cockpit._parse_matchup_scores(
            "prose…\n"
            "SCORE URC.TO | conviction=6.4 | upside=-34% | rho=— | phi=0.63 | price=$4.12\n"
            "SCORE LUNR.TO conviction=5.1 upside=+22% rho=1.8 phi=0.40 price=$23.08\n"
            "VERDICT: HOLD.")
        self.assertEqual(sc["URC.TO"]["rating"], 6.4)
        self.assertEqual(sc["URC.TO"]["upside"], -34.0)
        self.assertNotIn("rho", sc["URC.TO"])          # '—' is left unset, not zero
        self.assertEqual(sc["LUNR.TO"]["rho"], 1.8)
        self.assertEqual(sc["LUNR.TO"]["price"], 23.08)

    async def test_matchup_run_collects_scores(self):
        """Running the bench fills the grid: the run prompt asks for a SCORE block, and once the
        run lands those scores populate the outsider columns (marked ~ as agent estimates), while
        a book holding keeps its grounded engine numbers."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(160, 46)) as pilot:
            await pilot.pause(0.4)
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.2)
            app.action_blend_matchup("")
            await pilot.pause(0.2)
            ms = app.screen
            ms._hold = "AGA.V"                          # a book name (engine-rated in the stub)
            ms._chals = ["LUNR.TO", "FCXS.TO"]
            # the run prompt instructs a machine-readable SCORE block for every contender
            app._run_workflow_bg = lambda steps, subject: None
            app._fetch_fundamentals_bg = lambda tks: None
            app.action_matchup_run()
            self.assertIn("SCORE <TICKER>", app._workflow[0]["note"])
            self.assertIn("conviction=", app._workflow[0]["note"])
            # simulate the run landing with parsed scores under the exact subject key
            app._wf_running = False
            app._matchup_results["AGA.V vs LUNR.TO, FCXS.TO"] = {"scores": {
                "LUNR.TO": {"rating": 5.1, "upside": 22.0, "rho": 1.8, "phi": 0.4, "price": 23.08},
                "FCXS.TO": {"rating": 4.2, "upside": 5.0, "price": 1.9},
            }, "verdict": "HOLD AGA.V — the spear wins asymmetry.", "ref": ""}
            ms.paint()
            grid = text_of(ms.query_one("#mu_table"))
            # outsider columns now carry the agents' numbers, flagged ~ as estimates
            self.assertIn("5.1~", grid)
            self.assertIn("1.80×~", grid)
            self.assertIn("estimate", grid)            # the ~ legend
            # the holding keeps its GROUNDED engine conviction (8.2 from the stub), no ~
            self.assertIn("8.2", grid)
            self.assertNotIn("8.2~", grid)
            # the verdict is surfaced right in the matchup, not just the Quest Log
            self.assertIn("HOLD AGA.V", grid)

    async def test_matchup_scores_survive_restart(self):
        """_matchup_results is in-memory — opening a finished bench from the Quest Log after a
        restart re-hydrates the grid (scores + the arbiter's verdict) from the saved package."""
        import importlib
        import tempfile
        import time as _time

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(160, 46)) as pilot:
            await pilot.pause(0.4)
            pkg = tempfile.mktemp(suffix=".md")
            with open(pkg, "w") as fh:
                fh.write("## Stage 1 · value-analyst\n\n### value-analyst\n\n"
                         "SCORE URC.TO | conviction=6.4 | phi=0.63 | price=$4.12\n"
                         "SCORE LUNR.TO | conviction=5.1 | rho=1.8 | price=$23.08\n\n"
                         "## Stage 2 · arbiter\n\n### arbiter\n\n"
                         "STANCE: HOLD slot (no swap).\n")
            try:
                # a restarted session: the done-run exists on disk, nothing in memory
                app._done_runs.insert(0, {"id": 7, "agent": "workflow",
                                          "subject": "URC.TO vs LUNR.TO",
                                          "summary": "2-stage chain → packaged",
                                          "cat": "result", "ref": pkg, "ts": _time.time()})
                self.assertEqual(app._matchup_results, {})
                app.set_focus(None)
                await pilot.press("h")
                await pilot.pause(0.3)
                mi = next(i for i, it in enumerate(app.screen._items)
                          if it.get("opens") == "matchup")
                app.action_blend_open(mi)
                await pilot.pause(0.3)
                self.assertIsInstance(app.screen, t.MatchupSurface)
                grid = text_of(app.screen.query_one("#mu_table"))
                self.assertIn("5.1~", grid)                # scores back from disk
                self.assertIn("1.80×~", grid)
                self.assertIn("HOLD slot", grid)           # the arbiter verdict, not the stub summary
            finally:
                os.remove(pkg)

    async def test_matchup_bench_is_n_way(self):
        """The Matchup is an N-way bench: one holding vs several outsiders, a column per contender,
        best-in-row highlighted, capped at MAX_CHAL — and the run prompt ranks the whole bench."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            app.action_blend_matchup("SILV")               # seed one challenger
            await pilot.pause(0.2)
            scr = app.screen
            self.assertEqual(scr._chals, ["SILV"])

            class _Sub:                                    # duck-typed Input.Submitted
                def __init__(s, v):
                    s.value = v
                    s.input = type("I", (), {"id": "mu_chal", "value": v})()

                def stop(s):
                    pass

            scr.on_input_submitted(_Sub("MAG, AYA.V"))      # comma/space split adds both
            self.assertEqual(scr._chals, ["SILV", "MAG", "AYA.V"])
            # a column per contender (holding + 3 challengers) in the grid header
            grid = text_of(scr.query_one("#mu_table"))
            for tk in ("AGA.V", "SILV", "MAG", "AYA.V"):
                self.assertIn(tk, grid)
            self.assertIn("8.2", grid)                      # holding's live conviction still shown
            # ✕ removes one off the bench
            app.action_matchup_remove(1)
            self.assertEqual(scr._chals, ["SILV", "AYA.V"])
            # the bench is capped at MAX_CHAL
            scr._chals = ["A", "B", "C", "D"]
            scr.on_input_submitted(_Sub("EEE"))
            self.assertEqual(len(scr._chals), scr.MAX_CHAL)
            # run ranks the WHOLE bench (not a 1v1) and lands as a Quest-Log matchup
            app._run_workflow_bg = lambda steps, subject: None
            app._fetch_fundamentals = lambda tk: None
            scr._chals = ["SILV", "MAG", "AYA.V"]
            app.action_matchup_run()
            self.assertTrue(app._wf_running)
            self.assertIn("N-WAY MATCHUP BENCH", app._workflow[0]["note"])
            self.assertIn("rank", app._workflow[1]["note"].lower())
            # a lone challenger degrades cleanly to the 1v1 wording
            app._wf_running = False
            scr._chals = ["SILV"]
            app.action_matchup_run()
            self.assertIn("1v1 MATCHUP", app._workflow[0]["note"])

    async def test_log_expansion_and_command_completion(self):
        """Quest-Log rows unfold in place (▸/▾ · space) to the FULL untruncated text + a detail
        meta line; the command bar completes as you type ('@s' → every agent on s)."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            r = app._new_node("you", "Is the spear still convex?", None)
            app._conv[r]["ticker"] = "AGA.V"
            long_reply = ("Convexity intact: rho/phi 2.3x, floor $0.62 vs $0.71 print. The 7d drill "
                          "is binary and crowded — a miss re-rates hard, so the bear's $0.58 "
                          "invalidation stays a permanent caveat. Runway 18mo; JSF clean.")
            app._new_node("agent", long_reply, r, agent="conviction-analyst")
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            scr = app.screen
            ti = next(i for i, it in enumerate(scr._items) if it.get("opens") == "thread")
            # collapsed: the long reply is clipped, the tail isn't visible
            self.assertNotIn("permanent caveat", text_of(scr.query_one("#blend_log")))
            # expand via the caret's action → the FULL text (wrapped, never clipped) + meta
            app.action_blend_expand(ti)
            log = text_of(scr.query_one("#blend_log"))
            self.assertIn("permanent caveat", log)
            self.assertIn("turns", log)                    # the detail meta line
            # space mirrors the caret on the selected row (collapse again)
            scr._sel = ti
            await pilot.press("space")
            self.assertNotIn("permanent caveat", text_of(scr.query_one("#blend_log")))
            # completion: '@s' → every agent starting with s, with its purpose as the hint
            names = [lbl for _i, lbl, _h in scr._build_suggests("@s")]
            self.assertIn("@scout", names)
            self.assertIn("@sentinel", names)
            self.assertIn("@synthesis", names)
            # prefixes and tickers complete from a bare first token; chosen agents stop suggesting
            self.assertEqual([lbl for _i, lbl, _h in scr._build_suggests("no")], ["note:"])
            self.assertIn("AGA.V", [lbl for _i, lbl, _h in scr._build_suggests("ag")])
            self.assertEqual(scr._build_suggests("@scout brief"), [])
            # a clicked suggestion fills the bar, ready to keep typing
            app.action_blend_complete("@scout ")
            bar = scr.query_one("#blend_cmd")
            self.assertEqual(bar.value, "@scout ")
            self.assertTrue(bar.has_class("open"))

    async def test_blend_vs_focused_quest_log(self):
        """The wireframe model: THE BLEND (1) is the all-rails hub; QUEST LOG (2) is the SAME feed
        focused full-width via the top nav. The NOTES toggle shows/hides the design-intent note."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(190, 52)) as pilot:
            await pilot.pause(0.4)
            r = app._new_node("you", "convex?", None)
            app._conv[r]["ticker"] = "AGA.V"
            app._new_node("agent", "Below floor — accumulate; the bear's $0.58 stays a caveat.",
                          r, agent="conviction-analyst")
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            scr = app.screen
            # the hero + the lettered tabs both render, two-line (name over tagline)
            nav = text_of(scr.query_one("#blend_nav"))
            self.assertIn("THE BLEND", nav)
            self.assertIn("ROSTER TRIAGE", nav)
            self.assertIn("fleet teaches itself", nav)
            # the NOTES toggle drives the amber intro note
            self.assertTrue(scr.query_one("#blend_intro").has_class("open"))
            self.assertIn("one hub", text_of(scr.query_one("#blend_intro")))
            app.action_blend_notes_toggle()
            self.assertFalse(scr.query_one("#blend_intro").has_class("open"))
            # key 2 → the focused full-width QUEST LOG (same events, wider); expand works there too
            await pilot.press("2")
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.QuestLogSurface)
            self.assertIn("QUEST LOG", text_of(app.screen.query_one("#quest_filters")))
            qi = next(i for i, it in enumerate(app.screen._items) if it.get("opens") == "thread")
            app.action_blend_expand(qi)
            self.assertIn("stays a caveat", text_of(app.screen.query_one("#quest_log")))
            # opening an entry stacks its surface; the top bar pops back to the chosen tab
            app.action_blend_open(qi)
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.ThreadSurface)
            await pilot.press("1")                          # 1 = THE BLEND, pops everything
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.BlendHubScreen)

    async def test_inspect_modal_scrolls_long_dossier(self):
        """A long dossier/verdict opened in the universal inspector renders in FULL and the body
        scrolls — it no longer clips at ~22 rows (the cause of 'dossiers getting cut off')."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        from textual.containers import VerticalScroll
        app = t.Cockpit()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            body = "\n".join(f"line {i}: long arbiter verdict reasoning." for i in range(1, 41))
            app.push_screen(t.InspectScreen("ARBITER VERDICT", body))
            await pilot.pause(0.2)
            rendered = text_of(app.screen.query_one("#inspect_body"))
            self.assertIn("line 1:", rendered)
            self.assertIn("line 40:", rendered)            # the tail is NOT clipped
            self.assertTrue(app.screen.query_one(VerticalScroll).max_scroll_y > 0)   # genuinely scrollable

    async def test_run_subject_truth_and_echo_dedup(self):
        """A run shows ITS OWN subject everywhere (never the unrelated desk focus), and shows
        exactly once — the engine's event-bus echo of the local chain (theme == subject) is not
        a second 'pipeline' row. An independent engine pipeline (different theme) still shows."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(200, 52)) as pilot:
            await pilot.pause(0.4)
            app.set_focus(None)
            app._set_focus("AGA.V")                        # desk focus ≠ the run's subject
            await pilot.press("h")
            await pilot.pause(0.3)
            app.action_blend_matchup("")
            await pilot.pause(0.2)
            ms = app.screen
            app.action_matchup_hold("URC.TO")
            ms._chals = ["U-UN.TO", "IVN.TO", "NXE.TO", "FCXS.TO"]
            app._run_workflow_bg = lambda steps, subject: None
            app._fetch_fundamentals = lambda tk: None
            app.action_matchup_run()
            subject = "URC.TO vs U-UN.TO, IVN.TO, NXE.TO, FCXS.TO"
            self.assertEqual(app._wf_subject, subject)     # the matchup records its true subject
            # the engine echoes our own run back as a running 'pipeline' with theme == subject
            app._state["pipeline"] = {"status": "running", "theme": subject,
                                      "stage": "value-analyst", "started": 123}
            await pilot.press("escape")
            await pilot.pause(0.2)
            scr = app.screen
            scr.paint_all()
            lane = text_of(scr.query_one("#blend_lane_body"))
            self.assertIn("URC.TO vs", lane)               # the run's true subject…
            self.assertNotIn("chain AGA.V", lane)          # …never the unrelated focus
            self.assertNotIn("pipeline", lane)             # the echo row is suppressed
            running = [ln for ln in text_of(scr.query_one("#blend_log")).splitlines() if "⚙ RUN" in ln]
            self.assertTrue(any("URC.TO vs" in ln for ln in running))
            self.assertFalse(any("chain · AGA.V" in ln for ln in running))
            self.assertFalse(any("pipeline ·" in ln for ln in running))
            # a genuinely independent engine pipeline (different theme) still shows
            app._state["pipeline"] = {"status": "running", "theme": "silver juniors",
                                      "stage": "verifier", "started": 124}
            scr.paint_all()
            self.assertIn("pipeline · silver juniors", text_of(scr.query_one("#blend_log")))
            # the live canvas targets the run's subject too
            app.action_blend_open_pipeline()
            await pilot.pause(0.3)
            canvas = text_of(app.screen.query_one("#pipe_canvas"))
            self.assertIn("URC.TO vs", canvas)
            app._wf_finish()                               # cleanup releases the subject lock
            self.assertIsNone(app._wf_subject)

    async def test_subject_at_fire_no_sticky_target(self):
        """Subject-at-fire: there's no sticky _blend_target. The launch subject defaults to the
        desk focus and is confirmed/edited per launch (Pipeline setup · Matchup holding); a bare
        ticker in the / bar just sets focus."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            self.assertIsNone(app._blend_target if hasattr(app, "_blend_target") else None)
            app.set_focus(None)
            app._set_focus("GROY")                              # one notion of "current name": focus
            await pilot.press("h")
            await pilot.pause(0.3)
            self.assertEqual(app._blend_subject(), "GROY")
            # the matchup holding defaults to focus and is changeable before the run
            app.action_blend_matchup("")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.MatchupSurface)
            self.assertEqual(app.screen._hold or app._blend_subject(), "GROY")
            app.action_matchup_hold("AGA.V")
            self.assertEqual(app.screen._hold, "AGA.V")
            # the holding can't also sit on its own bench
            app.screen._chals = ["AGA.V", "SILV"]
            app.action_matchup_hold("AGA.V")
            self.assertEqual(app.screen._chals, ["SILV"])
            await pilot.press("escape")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.BlendHubScreen)
            # a bare ticker in the / bar sets the desk focus (the default subject), not a hub target
            from textual.widgets import Input as _In
            bar = app.screen.query_one("#blend_cmd", _In)
            bar.value = "URC.TO"
            app.screen.on_input_submitted(_In.Submitted(bar, "URC.TO"))
            await pilot.pause(0.1)
            self.assertEqual(app._focus, "URC.TO")
            self.assertEqual(app._blend_subject(), "URC.TO")

    async def test_concierge_is_read_only_and_everywhere(self):
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            # the dock states its boundary on the collapsed bar itself
            bar = text_of(app.screen.query_one("#con_bar"))
            self.assertIn("CONCIERGE", bar)
            self.assertIn("not", bar)
            self.assertIn("write Memory", bar)
            # opens by key on the home…
            await pilot.press("c")
            self.assertTrue(app.screen._con_open)
            self.assertTrue(app.screen.query_one("#con_dock").has_class("open"))
            await pilot.press("escape")                    # leave the input
            await pilot.pause(0.1)
            # …and rides the focus surfaces too, context-aware
            app.action_blend_roster()
            await pilot.pause(0.2)
            self.assertIn("fleet roster", text_of(app.screen.query_one("#con_bar")))
            # a question goes to the Concierge lane, never the conversation tree or memory
            conv_before = dict(app._conv)
            app._concierge_hist = [("you", "what is rho?"), ("concierge", "the payoff ratio")]
            app.screen._con_open = True
            app.screen.paint_concierge()
            self.assertEqual(app._conv, conv_before)
            self.assertIn("payoff ratio", text_of(app.screen.query_one("#con_log")))

    async def test_working_lane_clear(self):
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            # a running chain + a live inflight run + the stub's running engine pipeline
            app._wf_running = True
            app._workflow = [{"agents": ["scout"], "note": "x"}, {"agents": ["verifier"], "note": "y"}]
            app._inflight_add("ask", "@scout screening", "URC.TO", agent="scout", provider="gemini")
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            lane = text_of(app.screen.query_one("#blend_lane_body"))
            self.assertIn("clear all", lane)               # the one-button clear is present
            self.assertIn("✗", lane)                       # per-row cancels too
            # clear-all empties the lane — even orphaned/stuck rows (force)
            app.action_blend_clear_lane()
            await pilot.pause(0.2)
            self.assertFalse(app._wf_running)
            self.assertTrue(all(j.get("cancelled") for j in app._inflight.values()))
            self.assertEqual(app._pipe_dismissed, ((app._state or {}).get("pipeline") or {}).get("started"))
            lane2 = text_of(app.screen.query_one("#blend_lane_body"))
            self.assertIn("WORKING LANE  0", lane2)
            self.assertNotIn("clear all", lane2)           # nothing left to clear → button gone
            # a genuinely NEW pipeline (fresh 'started') is not hidden by the dismissal
            app._pipe_dismissed = 0
            (app._state or {})["pipeline"] = {"status": "running", "theme": "new", "started": 999}
            self.assertTrue(app._pipe_is_live())

    async def test_top_nav_and_pipeline_setup(self):
        """The top bar explores; nothing fires until ▶ LAUNCH. The Launch rail stays quick-fire
        (▶) with a ⚙ that opens the same setup view instead of running."""
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            app.set_focus(None)
            await pilot.press("h")
            await pilot.pause(0.3)
            # the wireframe top bar: THE BLEND hero + A–E focused features, each with a tagline
            nav = text_of(app.screen.query_one("#blend_nav"))
            for lbl in ("THE BLEND", "QUEST LOG", "PIPELINE CANVAS", "MATCHUP DESK",
                        "ROSTER TRIAGE", "THREAD MAP"):
                self.assertIn(lbl, nav)
            self.assertIn("chains, not black boxes", nav)   # a tagline survives
            # key 2 focuses the QUEST LOG full-screen (distinct from THE BLEND home)
            await pilot.press("2")
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.QuestLogSurface)
            await pilot.press("1")                          # 1 = THE BLEND home
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.BlendHubScreen)
            # subject-at-fire: the rail has NO sticky target row — it shows the focused-name
            # default, and each chain opens its setup (nothing fires from the rail directly)
            launch = text_of(app.screen.query_one("#blend_launch_body"))
            self.assertNotIn("TARGET", launch)
            self.assertIn("on the focused name", launch)
            self.assertIn("DEEP DOSSIER", launch)
            # PIPELINE is now tab 3; with the stub's engine pipeline LIVE it opens the live view…
            await pilot.press("3")
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.PipelineSurface)
            self.assertEqual(app.screen._mode, "live")
            await pilot.press("escape")
            await pilot.pause(0.2)
            # …and once that run is dismissed from the lane, the tab opens SETUP mode
            app.action_blend_dismiss_pipeline()
            await pilot.press("3")
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.PipelineSurface)
            self.assertEqual(app.screen._mode, "setup")
            self.assertFalse(app._wf_running)
            setup = text_of(app.screen.query_one("#pipe_setup"))
            self.assertIn("CHAIN", setup)
            self.assertIn("SUBJECT", setup)
            self.assertIn("✕", setup)                      # stages are editable before launch
            self.assertIn("▶ LAUNCH", text_of(app.screen.query_one("#pipe_actions")))
            # the subject defaults to the desk focus and is editable per-launch (subject-at-fire)
            self.assertEqual(app.screen._subject, app._blend_subject())
            app.action_pipe_subject("URC.TO")
            self.assertEqual(app.screen._subject, "URC.TO")
            # stage the parameters: pick a recipe, drop a stage — still nothing running
            app.action_pipe_chain_pick("convene council")
            self.assertEqual([s["agents"] for s in app._workflow], [["bull", "bear"], ["arbiter"]])
            app.action_pipe_stage_del(0)
            self.assertEqual([s["agents"] for s in app._workflow], [["arbiter"]])
            self.assertFalse(app._wf_running)
            # ▶ LAUNCH is the explicit execution moment; the surface flips to live in place
            captured = {}
            app._run_workflow_bg = lambda steps, subject: captured.update(subject=subject)
            app.action_blend_launch_current()
            self.assertTrue(app._wf_running)
            self.assertEqual(app.screen._mode, "live")
            self.assertEqual(captured["subject"], "URC.TO")    # fired on the confirmed subject
            self.assertEqual(app._wf_subject, "URC.TO")        # locked stable for the lane/log
            app._wf_finish()                                   # releases the lock
            self.assertIsNone(app._wf_subject)
            app._wf_running = False
            app._workflow = []
            # the bar rides surfaces too: 5 switches straight to the Roster, 1 goes home
            await pilot.press("5")
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.RosterSurface)
            self.assertIn("PIPELINE", text_of(app.screen.query_one("#srf_nav")))
            await pilot.press("1")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.BlendHubScreen)
            # ⚙ on a Launch row opens setup for that chain (instead of auto-running it)
            app.action_blend_configure("quick red-team")
            await pilot.pause(0.3)
            self.assertIsInstance(app.screen, t.PipelineSurface)
            self.assertEqual(app.screen._mode, "setup")
            self.assertEqual(app.screen._chain_name, "quick red-team")
            self.assertFalse(app._wf_running)

    async def test_chain_controls_and_classic_reachability(self):
        import importlib

        import commodityex_tui as t
        importlib.reload(t)
        app = t.Cockpit()
        async with app.run_test(size=(180, 52)) as pilot:
            await pilot.pause(0.4)
            # pause / stop are honest stage-boundary controls on the runner's shared flags
            app._wf_running = True
            app._workflow = [{"agents": ["scout"], "note": "x"}]
            app.action_wf_pause()
            self.assertTrue(app._wf_ctl["pause"])
            app.action_wf_stop()
            self.assertTrue(app._wf_ctl["stop"])
            self.assertFalse(app._wf_ctl["pause"])         # stop clears pause so the loop exits
            app._wf_running = False
            # explicit reader flows still land on the classic mission control (nothing uprooted)
            app.action_open_hub(cat="archive")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, t.HubScreen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
