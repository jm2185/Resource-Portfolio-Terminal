#!/usr/bin/env python3
"""
commodityex_tui.py — the CommodityEx research cockpit (Pillar 3).

A keyboard-first Textual terminal you can live in for hours doing deep, high-conviction work on
silver/junior names (AGA.V, GMX.TO, GROY, URC.TO). It is a **pure consumer** of the engine: it
never computes valuation / what-if / regime / config itself. It reads ``/state``,
``/config/scenarios``, ``/config/pending`` and ``/decisions``; it POSTs ``/action/whatif``,
``/config/scenario``, ``/config/confirm`` and — so agents always know what you're looking at —
``/ui/state``. Agents steer it back via the ``ui_command`` stream on ``/state``.

Layout (a serious trading desk, not a dev tool)::

    ┌ Header (title · clock) ───────────────────────────────────────────────────────────┐
    │ STATUS  REGIME · MRI gauge · Ag/GSR · book HEALTH · ◆FOCUS · SCEN · LIVE           │
    │ TAPE    dense cross-asset macro strip, coloured by risk-on / risk-off bias         │
    ├──────────────┬─────────────────────────────────────────────┬──────────────────────┤
    │ WATCHLIST    │  Book · Live What-If · Regime · Dossier      │  SIGNALS             │
    │ health bars  │  (the work surface)                          │  agent stream /      │
    │ BOOK HEALTH  │                                              │  proposals / actions │
    ├──────────────┴─────────────────────────────────────────────┴──────────────────────┤
    │ › command bar  (/focus · /whatif · /scenario · /confirm · /dossier)                │
    │ Footer (keys)                                                                      │
    └───────────────────────────────────────────────────────────────────────────────────┘

Run (engine on :8000):  pip install textual && python commodityex_tui.py
Keys: q quit · r refresh · 1-4 tabs · w what-if · c confirm pending · / command bar

Module layout: this file keeps the ``Cockpit`` App (so ``CSS_PATH`` keeps resolving
``cockpit.tcss`` next to it) and re-exports, for backward compatibility, everything that
moved out — the palette/transport/format helpers + modal screens (``cockpit_widgets``)
and the Blend/Concierge surface family (``cockpit_surfaces``).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                                  # health/score -> colour (shared visual language)
    from conviction_health import health_color, quality_color
except Exception:                                     # pragma: no cover - graceful if module moves
    def health_color(_): return "#C0C0C8"
    def quality_color(_): return "#C0C0C8"
try:                                                  # shared input parsing only (NOT business logic)
    from valuation_actions import parse_overrides
except Exception:                                     # pragma: no cover
    def parse_overrides(s): return {}

from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Button, Collapsible, DataTable, Header, Input,
                             Markdown, Static)

import obs  # CEX_DEBUG-gated logging for swallowed exceptions (shared with the engine)
from hub_gist import (ask_failure_message, ask_timeout_seconds, condense_reply,   # pure hub helpers
                      conv_prune, pick_mcap, reduce_stream_json,                   # (testable sans
                      reply_gist)                                                  #  textual)


# ======================================================================================
#  Split modules — backward-compatible re-exports.
#  The visual vocabulary + modal screens live in cockpit_widgets; the Blend/Concierge
#  surface family lives in cockpit_surfaces. EVERY moved top-level name is re-imported
#  here so `import commodityex_tui as t` keeps resolving t.<name> (tests + agents rely
#  on it), and the Cockpit App below keeps its original module-global vocabulary.
#  Cockpit itself stays in THIS module so Textual resolves CSS_PATH -> cockpit.tcss
#  relative to this file.
# ======================================================================================
from cockpit_widgets import (  # noqa: F401
    ENGINE, SESSION, REFRESH_SECONDS, SCHED_TICK_SECONDS, AMBER, AMBER_BRIGHT, GOLD, SILVER,
    DIM, FAINT, GREEN, RED, ORANGE, TEAL, BORDER, _ROLE_GLYPH, _ARCH_SHORT, _get, _post, _num,
    _fmt, _score, _bar, _pillar, _badge, _rating, _mri_gauge, bias_color, _arch_short,
    _role_glyph, _SUB_ABBR, _sub_abbr, _native_ladder, _disp_price, _upside_text, _floor_edge,
    _directive_action, _clean_convo_title, METRIC_HELP, _EXPLAIN_META_RE, metric_hover_help,
    _gate_text, _delta_bar, _ladder, _money, _provenance_tell, _compact, STALE_DAYS, _age_days, _mem_age,
    _range_bar, _rel_age, _SPARK, _spark, _TAPE_SHORT, _tape_short, _LEVEL_COLOR, _level_color,
    _clip, _stream_lines, _readline_iter, _parse_workflow_signals, _eval_workflow_gate,
    HUB_RUNTIMES, HUB_GROUPS, HUB_AGENT_META, HUB_VERBS, HUB_LEDGER_VERBS, HUB_AGENT_MODEL,
    _MODEL_COLORS, _agent_model, _model_chip, _run_model_label, HUB_INTENT_RULES, HUB_AGENT_DOC,
    _hub_meta, _lane_chip, _status_dot, _routine_read, CONCIERGE_C, BLEND_FILTERS, BLEND_NAV,
    _blend_nav_markup, JOBNAV_JOBS, JOBNAV_DRAWERS, _jobnav_markup, BLEND_SEED_WORKFLOWS,
    _BLEND_KIND_GROUP, _BLEND_GROUP_STYLE, _blend_kind_style, _BLEND_OPEN_HINT, _MATCHUP_LENSES,
    _council_convergence, _blend_feed_row, _blend_feed_parts, _BLEND_LANES, _blend_feed_lanes,
    _prop_label, BLEND_NODE_W, BLEND_NODE_H, _provider_color, paint_fan, _blend_node_card,
    _vpad_center, _hcat, _blend_chain_canvas, _lane_rows, _WF_KNOBS, _ALIAS_TO_KNOB,
    InspectScreen, _esc_change, _change_title, _change_body, _screen_funnel_markup,
    _correlation_screen_markup, ChangeReviewScreen, ChatInput, PaletteScreen, HubScreen,
)
from cockpit_surfaces import (  # noqa: F401
    ConciergeDock, BlendSurface, PipelineSurface, MatchupSurface, ThreadSurface, CompareSurface,
    RosterSurface, QuestLogSurface, BlendHubScreen, _bar_markup,
)

# Tests (and operators) repoint CEX_ENGINE_URL / CEX_SESSION and then importlib.reload(THIS
# module) to pick the change up. The engine transport (`_get`/`_post`) now lives in
# cockpit_widgets, whose module body does NOT re-execute on that reload — so recompute the
# env-derived endpoints here on every (re)load and push them into the transport module
# (`_get`/`_post` read the module global at call time, keeping every consumer in sync).
import cockpit_widgets as _cockpit_widgets

ENGINE = _cockpit_widgets.ENGINE = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000")
SESSION = _cockpit_widgets.SESSION = os.environ.get("CEX_SESSION", "commodityex")


class Cockpit(App):
    TITLE = "CommodityEx"
    SUB_TITLE = "research cockpit"

    # Refined "desk at night" theme — the design system's tmux/Textual projection
    # (docs/archive/tmux-textual-theme.md). Same one-source-of-truth palette, tightened to the
    # web kit's hierarchy: round borders stand in for radii, a bright amber border + the 2 Hz
    # pulse for the web glow, percent-alpha fills for rgba tints. No web-only properties.
    # Stylesheet lives in cockpit.tcss (extracted from the inline CSS literal in the 2026-07
    # token-optimization pass) so style edits never touch this module.
    CSS_PATH = "cockpit.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        # the five tabs are gone — lenses summon onto the spine; the palette covers the rest
        ("w", "whatif_focus", "What-If"),
        ("e", "go_council", "Council"),
        ("d", "open_profile", "Detail"),
        ("g", "grid", "Book grid"),
        ("h", "open_hub", "Hub"),
        ("v", "open_hub", "Hub"),
        Binding("p", "open_profile", "Profile", show=False),
        # what-if knob stepping (live only while the What-If lens is open; hints live in the lens)
        Binding("left_square_bracket", "wf_knob(-1)", "Prev knob", show=False),
        Binding("right_square_bracket", "wf_knob(1)", "Next knob", show=False),
        Binding("minus", "wf_step(-1, False)", "Knob −", show=False),
        Binding("equals_sign", "wf_step(1, False)", "Knob +", show=False),
        Binding("comma", "wf_step(-1, True)", "Knob − fine", show=False),
        Binding("full_stop", "wf_step(1, True)", "Knob + fine", show=False),
        Binding("backslash", "wf_reset", "Reset knobs", show=False),
        ("c", "confirm", "Confirm"),
        ("a", "ask('analyst')", "Ask analyst"),
        ("b", "ask('bear')", "Bear case"),
        ("x", "ask('dossier')", "Dossier"),
        ("slash", "cmd", "Command"),
        # the command palette — Ctrl-K reaches it from ANYWHERE (even mid-type in the chat, via
        # priority); ':' opens it when focus is on a tab/grid. '?' is the keymap/help overlay.
        Binding("ctrl+k", "palette", "Palette", priority=True),
        Binding("colon", "palette", "Palette", show=False),   # ':' alias (^K already in the footer)
        ("question_mark", "help", "Help"),
        Binding("alt+o", "ops_shell", "Shell", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._state: dict = {}
        self._scenarios: list = []
        self._pending: list = []
        self._decisions: list = []
        self._open_doss: str | None = None    # currently-open dossier (for index highlight)
        self._del_arm: str | None = None       # dossier armed for delete (two-click safety)
        self._baskets_by_ticker: dict = {}
        self._fund: dict = {}                 # FMP fundamentals per ticker (cached; {} = fetched/none)
        self._watch_cands: dict = {}          # {ticker: {ticker,note,source,status,added_ts}} — persisted bench
        self._watch_proposals: list = []      # pending watchlist additions in "propose" mode (awaiting ✓/✗)
        self._uni_ident = None                 # cached {ticker: "Name · commodity"} from the discovery universe
        self._uni_ident_ts = 0.0
        self._dismissed_cands: set = set()    # pipeline/engine suggestions the user has skipped this session
        self._load_watchlist()
        self._inspect: tuple | None = None    # (metric_key, ticker) when the detail panel is inspecting a metric
        self._row_index: dict = {}
        self._book_sig = None
        self._focus: str | None = None
        self._last_reported: tuple | None = None
        self._active_scenario: str | None = None
        self._wf_source = "you"
        self._wf_scenario_brief = ""    # agent-proposed scenario narrative (effects beyond the 7 knobs)
        self._wf_scenario_ov = None     # the overrides that narrative belongs to (so it shows only for that run)
        self._wf_hist: list = []
        self._wf_knobs: dict = {k[0]: 0.0 for k in _WF_KNOBS}   # interactive what-if knob deltas
        self._wf_sel = 0                                         # selected knob index
        self._wf_timer = None                                   # debounce for live revalue
        self._wf_pinned: dict | None = None                     # pinned A/B baseline (scenario A)
        self._wf_last: dict | None = None                       # last what-if result (pinnable)
        self._wf_last_res: tuple | None = None                  # (res, overrides) — for A/B re-render
        self._last_seq = 0
        self._act_seq = 0
        self._tick = 0
        self._suppress_report = False
        # --- "alive" state: rolling history for sparklines, heartbeat + ticker animation ---
        self._hist: dict = {}                 # metric -> deque of recent values (for sparklines/trend)
        self._beat = 0                        # pulse frame, advanced ~2x/sec
        self._ticker_body: Text | None = None  # cached colored macro line; _pulse adds the heartbeat
        self._asked: str | None = None        # last plain-text prompt sent to the agents from the bar
        # branching conversation tree: nodes keyed by id, each {id,parent,role,text,agent,ts}.
        # _active = the node your next message hangs off (None → a fresh thread). Context for an
        # ask is ONLY the active node's lineage (root→here), so threads stay isolated.
        self._conv: dict = {}
        self._active: str | None = None
        self._pending_user: str | None = None     # the just-asked node awaiting its reply
        self._stream_buf: dict = {}                # uid -> partial reply text, streamed live (H1 tape)
        self._node_seq = 0
        self._expanded: set = set()                # reply node ids the user expanded in the tree
        self._pipe_seen = None                     # started-ts of the last pipeline run seeded to threads
        self._council_open = False                 # inline Council debate expanded on the Book page?
        self._ask_history: list = []               # prior chat asks, for ↑/↓ recall in the cmdbar
        self._palette_recap = "—"                  # last command-palette action, echoed as a recap
        self._inflight: dict = {}                  # in-flight agent runs (AGENTS control strip): jid -> job
        self._job_seq = 0                          # in-flight job id sequence
        self._receipts: list = []                  # recent action receipts (what changed + optional undo)
        self._receipt_seq = 0                      # receipt id sequence
        self._done_runs: list = []                 # finished agent runs/research → the Hub's Done board (readable)
        self._done_seq = 0                         # done-run id sequence
        self._workflow: list = []                  # the chain being composed: [{agents:[...], note:str}, …]
        self._workflows = None                     # saved named workflows (lazy-loaded)
        self._wf_running = False                   # a workflow chain is executing
        self._hub_compose_ctx: dict | None = None  # {root, tail, summary, ticker} — follow-up context for Hub compose
        self._hub_expanded: set = set()            # thread root IDs expanded in the Hub feed
        self._editing_mem: str | None = None       # memory entry id being edited via the chat bar
        self._autonomy = "propose"                  # agent trust dial: manual · propose · auto (≤ posture cap)
        # ── THE BLEND (Agent Hub v2) ──
        self._wf_subject = None                     # the subject a running chain was LAUNCHED on (stable)
        self._matchup_results: dict = {}            # {subject: {scores:{tk:{...}}, verdict, ref}} — agent-scored grids
        self._pipe_dismissed = None                 # an engine-pipeline 'started' ts cleared from the lane
        self._blend_notes = True                    # show the Blend's amber design-intent note (NOTES toggle)
        # Quest Log layout (g toggles): 3 vertical lanes (RUN·FLAG·NOTE) vs one stream. The
        # full-width QUEST LOG tab defaults to lanes (room for 3 columns); the narrow Blend-home
        # center defaults to the single stream (3 columns would clip there). Independent per surface.
        self._blend_lanes = False                   # Blend home center
        self._blend_lanes_quest = True              # focused QUEST LOG surface (full width)
        self._concierge_hist: list = []             # ephemeral Concierge Q&A — NEVER persisted
        self._concierge_busy = False
        self._wf_ctl: dict = {"pause": False, "stop": False}   # chain controls (⏸ / ⏹, stage-boundary)
        self._wf_stage_idx = 0                      # the running chain's current stage (Pipeline view)
        self._last_wf_steps: list | None = None     # last-launched chain shape (done-Pipeline fallback)
        self._watch_query = ""                      # active watchlist search / scout theme
        self._active_view = "book"                  # last-summoned detail card (for /ui/state reporting)
        self._jobs: list | None = None              # recurring scheduler jobs (lazy-loaded)
        self._job_proposals: list = []              # due jobs awaiting a human ✓ (propose mode)

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("connecting to engine…", id="statusband")
        with Horizontal(id="body"):
            # ── LEFT RAIL — holdings + an open, agent-fed watchlist ─────────────────────
            with VerticalScroll(id="rail"):
                yield Static("HOLDINGS", classes="railtitle")
                yield Static("…", id="holdingsbody")               # the book's rated names
                yield Static("WATCHLIST", classes="railtitle railsub")
                yield Input(placeholder="+ search a name or scout a theme…", id="watchsearch")
                yield Static("…", id="watchbody")                  # agent-fed candidates / scout hits
                with Vertical(id="healthmini"):
                    yield Static("BOOK HEALTH", classes="railtitle")
                    yield Static("…", id="healthbody")
            # ── CENTER — the reasoning surface: always-on macro frame, then a two-column workspace
            #     (the reasoning spine on the left; Regime / Name / What-If detail cards on the right) ──
            with Vertical(id="surface"):
                yield Static("…", id="regime_panel")               # always-on regime decomposition
                with Horizontal(id="workspace"):
                    with VerticalScroll(id="spine"):               # LEFT — the name + council + chat
                        yield Static("Select a name to ground the desk.", id="conviction",
                                     classes="convictioncard")
                        # Council renders INLINE here (verdict strip → full debate ⌄) atop the shared
                        # conversation — it is NOT a card. Both live in #agent_reply.
                        yield Static("", id="agent_reply")
                    with VerticalScroll(id="cards"):               # RIGHT — always-on detail cards
                        with Collapsible(title="◑ REGIME DETAIL", collapsed=False, id="lens_regime"):
                            yield Static("…", id="regime")         # curve + integrity + full components
                        with Collapsible(title="▤ NAME DETAIL", collapsed=False, id="lens_dossier"):
                            yield Static("Click a name (or press d) for its deep-dive profile.", id="profile_body")
                            yield Static("DOSSIERS", classes="railsub")
                            yield Static("…", id="dossier_index")
                            yield Input(placeholder="open #  or  ticker", id="dossier_open")
                            yield Markdown("", id="dossier_body")
                        with Collapsible(title="△ WHAT-IF", collapsed=False, id="lens_whatif"):
                            with Horizontal(classes="row"):
                                yield Input(placeholder="ticker — blank uses the focused name", id="wf_ticker")
                                yield Input(placeholder="load a saved scenario by name…", id="wf_scenario")
                            yield Input(placeholder="knobs (silver=+5 ry=-0.5)  ·  or a free-form scenario: \"uranium spot doubles on a supply shock\"  ·  Enter",
                                        id="wf_overrides")
                            yield Static("", id="wf_knobs")
                            with Horizontal(classes="row"):
                                yield Button("− step", id="k_down", classes="knob")
                                yield Button("+ step", id="k_up", classes="knob")
                                yield Button("Reset", id="k_clear", classes="knob")
                                yield Button("▶ Run", id="wf_run", classes="-run")
                                yield Button("Decompose", id="wf_decomp", classes="knob")
                                yield Input(placeholder="save as…", id="wf_name")
                                yield Button("Save", id="wf_save")
                            yield Static("[#74747C]Knobs: [ ] select · − = step · , . fine · \\\\ reset.  "
                                         "Type an idea (e.g. “silver +8, real yield −0.5”) then Enter.[/]", id="wf_result")
                            yield Static("", id="wf_history")
                            yield Static("", id="wf_status")
                            yield Static("", id="wf_hint")
                # the BOOK GRID is invisible until you press `g` (a dense table when you want it)
                with Collapsible(title="▦ BOOK GRID", collapsed=False, id="lens_grid"):
                    yield DataTable(id="booktbl", zebra_stripes=True, cursor_type="row")
                # the omnibox — a ChatInput (↑↓ recall) docked under the spine. Everything agentic
                # (agents working · proposals · memory · results · research) lives in the Hub (press h).
                yield ChatInput(placeholder="Ask anything — type & Enter · ↑↓ recall · ^K palette · h Hub · g grid · ? help",
                                id="cmdbar")
        yield Static("", id="ticker")          # live macro ticker (always on) — see _pulse

    def on_mount(self) -> None:
        self._load_conv()                       # rehydrate past chats so they survive a restart
        t = self.query_one("#booktbl", DataTable)
        for c, w in (("", 3), ("TICKER", 7), ("PRICE", 8), ("ARCH", 8), ("R", 4), ("BAND", 14),
                     ("T", 3), ("Q", 3), ("V", 3), ("UP%", 5), ("FLOOR", 6),
                     ("GATE", 13), ("DIRECTIVE", 22)):
            t.add_column(c, key=c or "role", width=w)
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.set_interval(0.5, self._pulse)     # ~2 Hz heartbeat (no network) — keeps the desk live
        self.set_interval(SCHED_TICK_SECONDS, self._scheduler_tick)   # recurring agent work (dial-gated)
        self.refresh_data()
        self.call_after_refresh(lambda: self.query_one("#cmdbar", Input).focus())   # chat-first: ready to type

    # ------------------------------------------------------------------ polling
    def action_refresh(self) -> None:
        self.refresh_data()

    def _push_hist(self, key: str, val) -> None:
        if isinstance(val, (int, float)):
            self._hist.setdefault(key, deque(maxlen=40)).append(float(val))

    def _pulse(self) -> None:
        """Animate the LIVE heartbeat + breathe the bottom ticker, with no network calls
        (data lands on the 3 s poll; this just makes the desk feel awake)."""
        self._beat = (self._beat + 1) % 10000
        on = (self._beat % 2 == 0)
        # the Hub owns its own 1 Hz tick for live elapsed; nothing to animate on the desk but the ticker.
        body = self._ticker_body
        if body is None:
            return
        line = Text("◉ " if on else "◯ ", style=(GREEN if on else DIM))
        line.append("".join("▏▎▍▌▋▊▉"[(self._beat + i) % 7] for i in range(3)) + " ", style=GREEN)
        line.append_text(body)
        try:
            self.query_one("#ticker", Static).update(line)
        except Exception:
            pass

    @work(thread=True, exclusive=True, group="poll")
    def refresh_data(self) -> None:
        state = _get("/state")
        scenarios = _get("/config/scenarios")
        pending = _get("/config/pending")
        decisions = _get("/decisions") if (self._tick % 4 == 0 or not self._decisions) else None
        self._tick += 1
        self.call_from_thread(self._apply, state, scenarios, pending, decisions)

    def _status(self, text) -> None:
        """Transient feedback line in the What-If sandbox (never clobbered by the poll)."""
        self.query_one("#wf_status", Static).update(text)

    def _apply(self, state, scenarios, pending, decisions) -> None:
        # The refresh worker can finish as the app tears down; the widget tree is then gone and
        # query_one would raise. Bail if we're not running (also avoids any post-exit render churn).
        if not self.is_running:
            return
        if not state:
            self.query_one("#statusband", Static).update(
                Text("⚠ engine offline — start it (ops window · run_engine)  ", style=f"bold {ORANGE}"))
            return
        self._state = state
        if scenarios is not None:
            self._scenarios = (scenarios or {}).get("scenarios", []) or []
        if pending is not None:
            self._pending = (pending or {}).get("pending", []) or []
        if decisions is not None:
            self._decisions = (decisions or {}).get("decisions", []) or []

        conv = state.get("conviction_mode", {}) or {}
        baskets = conv.get("baskets", []) or []
        self._baskets_by_ticker = {b.get("ticker"): b for b in baskets}

        self._render_status(state, conv)
        self._render_tape(state)
        self._render_regime_panel(state)
        self._render_holdings(state, baskets)
        self._render_watchlist(state)
        self._render_health(state)
        self._render_book(state, baskets)
        self._maybe_seed_pipeline(state)
        self._render_agent_reply(state)
        self._render_wf_knobs()
        self._render_regime(state)
        if self._focus:                              # the Name card is always on — keep it live
            self._render_profile(self._focus)
        self._render_dossier_index()
        self._refresh_hub()                     # keep the Hub's live cards fresh while it's open
        self._handle_agent_command(state)

        names = [s.get("name") for s in self._scenarios]
        if names:
            self.query_one("#wf_hint", Static).update(
                Text("saved scenarios: ", style=DIM) + Text(" · ".join(names), style=SILVER))

    # ------------------------------------------------------------------ header
    def _render_status(self, state, conv) -> None:
        ctx = conv.get("context", {}) or {}
        metrics = state.get("metrics", {}) or {}
        hr = state.get("health_radar", {}) or {}
        tape = state.get("macro_tape", {}) or {}
        tape_by_key = {s.get("key"): s for s in (tape.get("signals") or [])}
        regime = ctx.get("regime") or tape.get("net_tilt", "—")
        mri = state.get("mri")
        spot = (metrics.get("Spot_Ag", {}) or {}).get("value")
        gsr = (metrics.get("GSR", {}) or {}).get("value")
        dxy_mom = (metrics.get("DXY_MOMENTUM", {}) or {}).get("value")
        dxy = (metrics.get("DXY", {}) or {}).get("value")
        y10 = (metrics.get("10Y", {}) or {}).get("value")
        y30 = (metrics.get("30Y", {}) or {}).get("value")
        health = hr.get("health_rating")
        status = state.get("status", "—")
        focus = self._focus or "—"
        gold = (gsr * spot) if (_num(gsr) is not None and _num(spot) is not None) else None

        for k, v in (("mri", mri), ("ag", spot), ("au", gold)):   # feed the sparkline memory
            self._push_hist(k, v)

        sep = Text("   ", style=BORDER)
        line = Text()
        line.append("REGIME ", style=DIM)
        line.append(str(regime), style=f"bold {bias_color('risk_off' if 'OFF' in str(regime).upper() else ('risk_on' if 'ON' in str(regime).upper() else 'neutral'))}")
        line.append_text(sep)
        line.append("MRI ", style=DIM)
        line.append(_fmt(mri, "{:.0f}"), style=Style.parse(GOLD) + Style(meta={"@click": "app.explain('mri')"}))
        line.append(" "); line.append_text(_mri_gauge(mri))
        sp = _spark(self._hist.get("mri", []))
        if sp:
            line.append(" "); line.append(sp, style=TEAL)
        # what MOVED the MRI: session delta + the dominant driver (low MRI = risk-on, so ▼ is GREEN)
        hist = [h for h in self._hist.get("mri", []) if _num(h) is not None]
        if len(hist) >= 2:
            d = _num(hist[-1]) - _num(hist[0])
            if abs(d) >= 0.1:
                line.append(f" {'▲' if d > 0 else '▼'}{abs(d):.1f}", style=(ORANGE if d > 0 else GREEN))
        drv = tape.get("top_mri_driver")
        if drv:
            line.append(f" {drv}", style=DIM)
        line.append_text(sep)
        # POSTURE — the master temperature dial (book-level size cap that composes everywhere)
        posture = state.get("posture") or {}
        if posture.get("label"):
            pcode = posture.get("code")
            pc = GREEN if pcode == "spear_exploit" else (ORANGE if pcode == "defensive" else SILVER)
            line.append("POSTURE ", style=DIM)
            line.append(str(posture["label"]), style=Style.parse(f"bold {pc}") + Style(meta={"@click": "app.explain('posture')"}))
            if _num(posture.get("cap")) is not None:
                capc = ORANGE if posture.get("headwind") else GREEN
                line.append(f" {posture['cap']:g}x", style=capc)
                if posture.get("headwind"):
                    line.append(" headwind", style=DIM)
            line.append_text(sep)
        if gold is not None:
            line.append("Au ", style=DIM); line.append(f"${_fmt(gold, '{:.0f}')}", style=SILVER)
            line.append_text(sep)
        line.append("Ag ", style=DIM); line.append(f"${_fmt(spot, '{:.2f}')}", style=SILVER)
        sp = _spark(self._hist.get("ag", []))
        if sp:
            line.append(" "); line.append(sp, style=TEAL)
        line.append("  GSR ", style=DIM); line.append(_fmt(gsr, "{:.0f}"), style=SILVER)
        line.append_text(sep)
        ry = tape_by_key.get("real_yield")
        if ry:
            line.append("RealY ", style=DIM)
            line.append(str(ry.get("display", "—")), style=bias_color(ry.get("bias")))
            line.append_text(sep)
        # rates cluster: dollar level + the long end (levels, not the spread)
        if _num(dxy) is not None:
            arrow = "▲" if (_num(dxy_mom) or 0) > 0 else "▼"
            line.append("DXY ", style=DIM)
            line.append(f"{_fmt(dxy, '{:.1f}')}{arrow}", style=(ORANGE if (_num(dxy_mom) or 0) > 0 else GREEN))
            line.append_text(sep)
        if _num(y10) is not None:
            line.append("10Y ", style=DIM); line.append(f"{_fmt(y10, '{:.2f}')}", style=SILVER)
            line.append(" 30Y ", style=DIM); line.append(f"{_fmt(y30, '{:.2f}')}", style=SILVER)
            line.append_text(sep)
        line.append("HEALTH ", style=DIM); line.append(f"{_fmt(health)}/10", style=health_color(health))
        line.append_text(sep)
        line.append("◆ ", style=AMBER); line.append(str(focus), style=f"bold {AMBER}")
        line.append_text(sep)
        line.append("● " if status == "LIVE" else "○ ", style=(GREEN if status == "LIVE" else ORANGE))
        line.append(str(status), style=(GREEN if status == "LIVE" else ORANGE))
        self.query_one("#statusband", Static).update(line)

    def _render_tape(self, state) -> None:
        """Build the bottom live-ticker body: every cross-asset signal, bias-coloured and compact.
        _pulse() prepends the animated heartbeat and pushes it to #ticker ~2x/sec."""
        tape = state.get("macro_tape", {}) or {}
        sig = tape.get("signals", []) or []
        tilt = str(tape.get("net_tilt", "—"))
        on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
        body = Text()
        body.append("NET ", style=DIM)
        body.append(f"{tilt}", style=f"bold {bias_color('risk_on' if 'ON' in tilt else ('risk_off' if 'OFF' in tilt else 'neutral'))}")
        body.append(f" {on}↑/{off}↓", style=DIM)
        for s in sig:
            body.append("   ")
            body.append(f"{_tape_short(s.get('label', ''))} ", style=DIM)
            body.append(str(s.get("display", "—")), style=bias_color(s.get("bias")))
        self._ticker_body = body
        self._pulse()                          # paint immediately, don't wait for the next beat

    # ------------------------------------------------------------------ always-on regime panel
    def _render_regime_panel(self, state) -> None:
        """The compact, always-visible macro frame above the spine (the heavy decomposition lives in
        the Regime lens). Ends the old status-band / regime-tab / signals triplication."""
        try:
            panel = self.query_one("#regime_panel", Static)
        except Exception:
            return
        ctx = (state or {}).get("conviction_mode", {}).get("context", {}) or {}
        tape = (state or {}).get("macro_tape", {}) or {}
        label = ctx.get("regime") or tape.get("net_tilt", "—")
        mri = (state or {}).get("mri")
        head = Text("REGIME ", style=f"bold {DIM}")
        head.append(str(label),
                    style=f"bold {bias_color('risk_off' if 'OFF' in str(label).upper() else 'risk_on')}")
        head.append("   top driver ", style=DIM)
        head.append(str(tape.get("top_mri_driver", "—")), style=AMBER)
        head.append("    MRI ", style=DIM)
        head.append(_fmt(mri, "{:.0f}"), style=f"bold {GOLD}")
        head.append(" "); head.append_text(_mri_gauge(mri, 12))
        head.append("   ", style=DIM)
        head.append("‹ detail ›", style=Style.parse(TEAL) + Style(meta={"@click": "app.lens('lens_regime')"}))
        # Regime Engine v2 (G1): the two-lens split — Broad-Market Risk (context) vs Metals Regime
        # (drives conviction), side by side, so a single blended "RISK-ON" can't mask a metals headwind.
        rlz = (state or {}).get("regime_lens", {}) or {}
        lens_line = None
        if rlz.get("metals") or rlz.get("broad"):
            b = rlz.get("broad", {}) or {}
            m = rlz.get("metals", {}) or {}
            mlab = str(m.get("label", "—"))
            mcolor = bias_color("risk_off") if mlab == "HEADWIND" else (bias_color("risk_on") if mlab == "SUPPORTIVE" else AMBER)
            lens_line = Text("  Broad ", style=DIM)
            lens_line.append(str(b.get("label", "—")),
                             style=bias_color("risk_off" if "OFF" in str(b.get("label", "")).upper() else "risk_on"))
            lens_line.append("  │  Metals ", style=DIM)
            lens_line.append(mlab, style=Style.parse(f"bold {mcolor}")
                             + Style(meta={"@click": "app.metals_lens()"}))   # click → the lens
            lens_line.append(" ‹drives conviction›", style=DIM)
            if rlz.get("divergence"):
                lens_line.append("   ⚠ divergence — read the metals lens",
                                 style=Style.parse(AMBER) + Style(meta={"@click": "app.metals_lens()"}))
        dec = (state or {}).get("mri_decomposition", {}) or {}
        comps = sorted(((k, _num(v)) for k, v in dec.items() if k != "top_driver" and _num(v) is not None),
                       key=lambda kv: -abs(kv[1]))[:5]
        bias = Text()
        for i, (k, v) in enumerate(comps):
            if i:
                bias.append("   ", style=DIM)
            bias.append(f"{str(k)[:10]} ", style=DIM)
            bias.append(f"{v:+.2f}", style=(GREEN if v >= 0 else ORANGE))
        # Book-factor lens: is this a PORTFOLIO or one bet wearing different tickers? avg pairwise ρ
        # (single-factor tell) + the % of the book's OWN scenario weight that has no answer.
        bfac = (state or {}).get("book_factor", {}) or {}
        conc, cov = (bfac.get("concentration") or {}), (bfac.get("coverage") or {})
        bf_line = None
        if conc.get("available") or cov.get("available"):
            bf_line = Text("  BOOK ", style=f"bold {DIM}")
            avg, sf = _num(conc.get("avg_pairwise")), conc.get("single_factor")
            if conc.get("available") and avg is not None:
                bf_line.append(f"avg ρ {avg:.2f}", style=Style.parse(f"bold {ORANGE if sf else GREEN}"))
                bf_line.append(" single-factor" if sf else " multi-factor", style=(ORANGE if sf else GREEN))
            if cov.get("available"):
                unc = _num(cov.get("uncovered_weight")) or 0.0
                holes = ",".join(str(h.get("scenario", "")) for h in (cov.get("holes") or []))
                bf_line.append("  │  ", style=DIM)
                bf_line.append(f"{unc:.0%} scenario weight uncovered",
                               style=(ORANGE if unc >= 0.20 else (AMBER if unc > 0 else GREEN)))
                if holes:
                    bf_line.append(f" ({holes})", style=DIM)
            # the ballast role-check SENTINEL: a ballast whose ρ→spear has drifted to ~1 has quietly
            # STOPPED being ballast — name it inline so the failure is visible, not buried in a number.
            cflags = [f for f in (conc.get("flags") or []) if _num(f.get("corr")) is not None]
            if cflags:
                bf_line.append("   ⚠ ", style=ORANGE)
                bf_line.append(" ".join(f"{f.get('ticker')} ρ{_num(f.get('corr')):.2f}→spear" for f in cflags[:3]),
                               style=ORANGE)
            bf_line.append("  ‹detail›", style=Style.parse(TEAL) + Style(meta={"@click": "app.lens('lens_regime')"}))
        parts = ([head] + ([lens_line] if lens_line is not None else [])
                 + ([bf_line] if bf_line is not None else []) + ([bias] if comps else []))
        panel.update(Group(*parts) if len(parts) > 1 else head)

    # ------------------------------------------------------------------ holdings rail
    def _render_holdings(self, state, baskets) -> None:
        nodes = state.get("nodes", {}) or {}
        annos = state.get("agent_annotations", {}) or {}
        try:
            body = self.query_one("#holdingsbody", Static)
        except Exception:
            return
        # HOLDINGS is the BOOK — barbell members only. ◇EVAL names are RATED-but-NOT-held; they live on
        # the bench (the watchlist ◇RATED tier), never intermixed here with an inline badge. Keep a count
        # for the one-line pointer to the bench so they're still discoverable from the book.
        all_baskets = baskets or []
        n_eval = sum(1 for b in all_baskets if isinstance(b, dict) and b.get("eval_only"))
        baskets = [b for b in all_baskets if not (isinstance(b, dict) and b.get("eval_only"))]
        if not baskets:
            body.update(Text("waiting for baskets…" if not n_eval else
                             f"no holdings — {n_eval} rated on the bench (◇EVAL) →", style=DIM))
            return
        out = Text()
        for i, b in enumerate(baskets):
            tk = str(b.get("ticker", "?"))
            r = b.get("rating")
            if i:
                out.append("\n")
            mark = "▸" if tk == self._focus else " "
            # clicking a holding FOCUSES it on the spine (the name becomes the subject); the rating
            # click pops its grounded breakdown. Holdings is the primary nav now (grid → a lens).
            click = Style(meta={"@click": f"app.focus_tk('{tk}')"})
            hc = Style.parse(health_color(r))
            out.append(f"{mark}", style=AMBER)
            out.append(f"{_role_glyph(tk, nodes)} ", style=hc + click)
            out.append(f"{tk:<7}", style=Style.parse("bold white") + click)
            out.append(f"{_fmt(r):>4} ", style=hc + Style(meta={"@click": f"app.explain('rating', '{tk}')"}))
            _act, _acol = _directive_action(b.get("directive"))   # the STANCE next to the rating (orthogonal)
            out.append(f"{_act:<5} ", style=Style.parse(f"bold {_acol}")
                       + Style(meta={"@click": f"app.explain('directive', '{tk}')"}))
            out.append_text(_bar(r, 7))
            # L2 — the three pillars, so the rail shows WHY the rating is what it is (not just the number)
            P = b.get("pillars", {}) or {}
            T_, Q_, V = P.get("T", {}) or {}, P.get("Q", {}) or {}, P.get("V", {}) or {}
            out.append("\n     ", style=DIM)
            for lbl, pv in (("T", T_), ("Q", Q_), ("V", V)):
                sc = _num(pv.get("score"))
                out.append(f"{lbl} ", style=DIM)
                out.append(f"{(_fmt(sc) if sc is not None else '—'):>3} ",
                           style=Style.parse(health_color(sc) if sc is not None else DIM))
            _prov = _provenance_tell(b)
            if _prov["q_marker"]:
                out.append(_prov["q_marker"], style=ORANGE)    # Q is a market-confidence proxy, not earned
            if (b.get("gate", {}) or {}).get("applied"):
                out.append(" ⚠gate", style=ORANGE)             # forensic cap is biting the rating
            # --- the VALUE LADDER, spelled out: ENGINE valuation (grounded) then BLUE-SKY (researched upside) ---
            lad, _sfx = _native_ladder(b)
            px = _num(lad.get("price"))
            base = _num(lad.get("base"))       # engine's grounded central fair value / risked NAV
            bull = _num(lad.get("bull"))       # the blue-sky / optionality leg (research-fed, grounded in the engine)
            fl = _num(lad.get("floor")); phi = _num(V.get("floor_coverage"))
            _up = lambda t: ((t / px - 1.0) * 100.0) if (px and px > 0 and t is not None) else None
            # ENGINE valuation — floor (downside) · fair value (+ gap) · where price sits now
            out.append("\n     ", style=DIM)
            if fl is not None:
                _fd = _prov["floor_degraded"]
                out.append(f"floor {_money(fl)}", style=(ORANGE if _fd else DIM))
                if _fd:
                    out.append(_prov["floor_marker"], style=ORANGE)   # unsourced/degraded floor, not a verified MoS
                if phi is not None:
                    # a φ on a proxy floor is not the confident "above floor" green — dim it when degraded
                    out.append(f" φ{phi:.2f}", style=(GREEN if (phi >= 1.0 and not _fd) else DIM))
            if base is not None:
                ub = _up(base)
                out.append("  fair " if fl is not None else "fair ", style=DIM)
                out.append(f"{_money(base)}", style=SILVER)
                if ub is not None:
                    out.append(f" {ub:+.0f}%", style=(GREEN if ub >= 0 else RED))
            out.append(f"  now {_money(px) if px is not None else '—'}", style=Style.parse("bold white"))
            # BLUE-SKY — the researched upside potential (the bull leg). Always shown: a real number when
            # the optionality is sourced+wired (the spear's scenario bull), else "not sourced" so the gap
            # is visible (a royalty/holdco bull is None until its optionality is independently sourced —
            # engine.py:5300-5309), never a hidden/missing line.
            out.append("\n     ", style=DIM)
            out.append("blue-sky ", style=DIM)
            if bull is not None and (base is None or bull > base * 1.02):
                usky = _up(bull)
                out.append(f"{_money(bull)}", style=TEAL)
                if usky is not None:
                    out.append(f"  {usky:+.0f}%", style=(GREEN if usky >= 0 else RED))
            else:
                out.append("— not sourced", style=ORANGE)       # optionality not yet wired to the bull leg
            # L4 — band · floor margin of safety
            out.append("\n     ", style=DIM)
            out.append(f"{str(b.get('band','—'))[:20]:<20} ", style=health_color(r))
            out.append_text(_floor_edge(b))
            # L5 — flags (sub-archetype · catalysts · floor-breach · re-rate), only when present
            flags = Text()
            sub = b.get("subarchetype")
            if sub:                                           # finer-sort hint (differentiates royalties)
                flags.append(f"{_sub_abbr(sub)} ", style=TEAL)
            cat = b.get("catalysts") or []
            if cat:                                           # catalyst-countdown badge (Phase 4)
                sig = _num(b.get("catalyst_signal")) or 0.0
                flags.append(f"↯{len(cat)} ", style=(GREEN if sig >= 0 else ORANGE))
            if _num(V.get("floor_coverage")) is not None and _num(V.get("floor_coverage")) >= 1.0:
                flags.append("⚑ ", style=GREEN)               # floor-breach: trading under liquidation
            rr = b.get("rerate") or {}                         # royalty carried at COST book → may under-mark
            if rr.get("applied"):
                flags.append("↻rerated", style=TEAL)           # anchor lifted to a VERIFIED metal re-rate
            elif rr.get("pending"):
                flags.append("↻pending", style=ORANGE)         # sourced re-rate held back, awaiting verification
            elif rr.get("candidate"):
                flags.append("↻cost", style=AMBER)             # re-rate candidate: source (and verify) one
            if flags.plain.strip():
                out.append("\n     ", style=DIM)
                out.append_text(flags)
            for a in (annos.get(tk) or [])[-1:]:          # agent's visual trace (pin_insight/highlight)
                col = _level_color(a.get("level"))
                out.append("\n     ", style=DIM)
                out.append(f"{a.get('badge', '✦')} ", style=f"bold {col}")
                out.append(str(a.get("reason", ""))[:38], style=col)
        if n_eval:                                         # the bench lives in the watchlist — point to it
            out.append("\n")
            out.append(f"  ◇ {n_eval} rated · not held → bench",
                       style=Style.parse(TEAL) + Style(meta={"@click": "app.watchlist_expand()"}))
        body.update(out)

    # ------------------------------------------------------------------ open watchlist (agent-fed)
    def _render_watchlist(self, state) -> None:
        """The watchlist is a depth-tiered BENCH, not a flat list: ◇RATED (◇EVAL names with the FULL
        dataset, rated-not-held) → ·MONITORED (scout/screen candidates). A name shows at its furthest
        funnel stage; click any to focus; ⤢ opens the whole bench."""
        try:
            body = self.query_one("#watchbody", Static)
        except Exception:
            return
        import bench
        parts: list = []
        if self._watch_query:
            parts.append(Text(f"⟳ scanning: {self._watch_query[:22]}", style=TEAL))
        eval_baskets = [b for b in (self._baskets_by_ticker or {}).values()
                        if isinstance(b, dict) and b.get("eval_only")]
        monitored = self._watch_candidates(state)      # monitored bench (already excludes held + eval)
        tiers = bench.bench_tiers(eval_baskets, monitored)
        vcol = {"APPROVE": GREEN, "CONDITIONAL": AMBER, "REJECT": RED}
        _CAP = 14                                      # rail budget across tiers; ⤢ expand for ALL
        shown = 0
        for tier in tiers:
            if shown >= _CAP:
                break
            hdr = Text(f"{tier['glyph']} {tier['label']} ",
                       style=Style.parse(f"bold {TEAL if tier['key'] == 'rated' else DIM}"))
            hdr.append(f"({len(tier['items'])})", style=DIM)
            parts.append(hdr)
            for c in tier["items"]:
                if shown >= _CAP:
                    break
                shown += 1
                tk = str(c.get("ticker", "?"))
                click = Style(meta={"@click": f"app.focus_tk('{tk}')"})
                line = Text("  ")
                line.append(f"{tk:<8}", style=Style.parse(f"bold {SILVER}") + click)
                if tier["key"] == "rated":             # ◇RATED — the full-data eval names, with their rating + floor
                    r = c.get("rating")
                    if r is not None:
                        line.append(f" {_fmt(r)}", style=Style.parse(f"bold {health_color(r)}"))
                    line.append(f"  fl {bench.floor_display(c)}  ", style=DIM)
                    line.append("◇EVAL", style=Style.parse(f"bold {TEAL}"))
                else:                                  # ·MONITORED — candidates, with the bench add/skip/dismiss
                    src = str(c.get("source") or c.get("note") or "")[:20]
                    if src:
                        line.append(f"  {src}", style=DIM)
                    if tk in self._watch_cands:
                        line.append("  ")
                        line.append("✕", style=Style(meta={"@click": f"app.watch_dismiss('{tk}')"}))
                    else:
                        st = str(c.get("status", "") or "")
                        if st:
                            line.append(f" {st[:8]}", style=vcol.get(st.upper(), DIM))
                        line.append("  ")
                        line.append("✓", style=Style.parse(f"bold {GREEN}") + Style(meta={"@click": f"app.watch_add_cand('{tk}')"}))
                        line.append(" ✗", style=Style.parse(RED) + Style(meta={"@click": f"app.watch_skip_cand('{tk}')"}))
                parts.append(line)
        total = bench.bench_counts(tiers)["total"]
        if total:                                      # always offer the full, scrollable bench view
            foot = Text("", style=DIM)
            if total > shown:
                foot.append(f"+{total - shown} more   ", style=AMBER)
            foot.append("⤢ expand", style=Style.parse(TEAL) + Style(meta={"@click": "app.watchlist_expand()"}))
            parts.append(foot)
        if not total and not self._watch_query:
            parts.append(Text("type a name above — or a theme to scout —", style=DIM))
            parts.append(Text("agents auto-add tickers from research.", style=DIM))
        body.update(Group(*parts) if parts else Text("…", style=DIM))

    def _watch_candidates(self, state) -> list:
        """The full bench, deduped: engine watchlist + pipeline verdicts + persisted bench, minus held
        names and dismissed ones. Shared by the rail render and the ⤢ expanded view (so they can't
        drift)."""
        held = set(self._baskets_by_ticker or {})
        cands = [c for c in ((state or {}).get("watchlist") or []) if isinstance(c, dict)]
        pipe = (state or {}).get("pipeline") or {}
        for tk, v in (pipe.get("verdicts") or {}).items():
            if tk in held:
                continue
            verdict = (v.get("verdict") if isinstance(v, dict) else str(v)) or ""
            note = (v.get("note") if isinstance(v, dict) else "") or f"pipeline · {pipe.get('theme', '')}"
            cands.append({"ticker": tk, "note": note, "source": "pipeline", "status": verdict})
        held_tks = {c.get("ticker") for c in cands}
        for tk, wc in (self._watch_cands or {}).items():
            if tk not in held and tk not in held_tks:
                cands.append(wc); held_tks.add(tk)
        return [c for c in cands if str(c.get("ticker", "?")) not in self._dismissed_cands]

    def action_watchlist_expand(self) -> None:
        """⤢ — the WHOLE bench in a scrollable modal, sectioned by funnel stage (◇RATED → ·MONITORED).
        Each name clickable to focus; ◇RATED names carry their live rating + floor (full data, not held)."""
        import bench
        eval_baskets = [b for b in (self._baskets_by_ticker or {}).values()
                        if isinstance(b, dict) and b.get("eval_only")]
        monitored = self._watch_candidates(self._state or {})
        tiers = bench.bench_tiers(eval_baskets, monitored)
        if not tiers:
            self._status(Text("the bench is empty — search a name or scout a theme to fill it", style=DIM))
            return
        vcol = {"APPROVE": GREEN, "CONDITIONAL": AMBER, "REJECT": RED}
        blocks = []
        for tier in tiers:
            head_col = TEAL if tier["key"] == "rated" else AMBER
            rows = [f"[bold {head_col}]{tier['glyph']} {tier['label']}[/] [{DIM}]· {len(tier['items'])}[/]"]
            for c in tier["items"]:
                tk = str(c.get("ticker", "?"))
                if tier["key"] == "rated":
                    r = c.get("rating")
                    rtxt = f"  [bold {health_color(r)}]{self._esc(_fmt(r))}[/]" if r is not None else ""
                    rows.append(f"  [@click=app.focus_tk('{tk}')][bold {GOLD}]{tk:<10}[/][/]{rtxt}"
                                f"  [{DIM}]floor {self._esc(bench.floor_display(c))} · ◇EVAL rated, not held[/]")
                else:
                    src = self._esc(str(c.get("source") or c.get("note") or "")[:54])
                    st = str(c.get("status", "") or "")
                    stx = f"  [{vcol.get(st.upper(), DIM)}]{self._esc(st[:14])}[/]" if st else ""
                    # ·MONITORED candidates get a one-click ⚖ vet (the gauntlet) straight from the funnel
                    vet = (f"   [@click=app.bench_vet('{tk}')][{TEAL}]⚖ vet[/][/]"
                           if tier["key"] == "monitored" else "")
                    rows.append(f"  [@click=app.focus_tk('{tk}')][bold {GOLD}]{tk:<10}[/][/] [{DIM}]{src}[/]{stx}{vet}")
            blocks.append("\n".join(rows))
        n = bench.bench_counts(tiers)["total"]
        body = (f"[{SILVER}]The full bench — {n} name{'s' if n != 1 else ''}, by funnel stage. Click a name "
                f"to focus, or ⚖ vet a ·MONITORED candidate to run the gauntlet (verifier → anti-scout → "
                f"forensic → graduate) → promote_to_eval → ◇RATED.[/]\n\n" + "\n\n".join(blocks))
        self.push_screen(InspectScreen(f"[bold {AMBER}]≣ BENCH[/]  [{DIM}]· the full funnel[/]",
                                       body, f"[{DIM}]‹ Esc to close[/]"))

    def action_bench_vet(self, tk: str = "") -> None:
        """⚖ vet a ·MONITORED bench candidate straight from the expanded funnel: close the modal so the
        gauntlet's progress is visible, then run the one-action disconfirmation gate on it."""
        tk = (tk or "").strip().upper()
        try:
            self.pop_screen()                 # close the bench modal before the gauntlet launches
        except Exception:
            obs.swallow("bench.vet.pop")
        if tk:
            self._set_focus(tk, move_cursor=True)
            self._run_gauntlet(tk)

    # ------------------------------------------------------------------ watchlist management
    # US + Canada only — the book trades North-American listings. Canadian suffixes
    # (.V/.TO/.TSXV/.TSX TSX-V & TSX, .CN CSE, .NE Cboe Canada/NEO) + US (.OTC); plain
    # US NYSE/Nasdaq tickers carry no suffix and are added by name elsewhere. Foreign
    # lines (.L/AIM, .AX/ASX, .HK, .PA, .F, .MI) are deliberately NOT captured.
    _WATCH_TICKER_RE = re.compile(
        r'\b([A-Z]{1,6}\.(?:V|TO|TSXV|TSX|CN|NE|OTC))\b'
    )

    def _load_watchlist(self) -> None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "watchlist.json")
        try:
            if os.path.exists(path):
                import json as _j
                with open(path) as f:
                    items = _j.load(f)
                self._watch_cands = {i["ticker"]: i for i in items if "ticker" in i}
        except Exception:
            pass

    def _save_watchlist(self) -> None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "watchlist.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            import json as _j
            with open(path, "w") as f:
                _j.dump(list(self._watch_cands.values()), f, indent=2)
        except Exception:
            pass

    def _add_to_watchlist(self, ticker: str, note: str = "", source: str = "agent",
                          status: str = "candidate", _force: bool = False) -> bool:
        """Add ticker to the bench, gated by the autonomy dial.
        auto → add immediately; propose → queue for human ✓/✗; manual → silently skip.
        _force bypasses the gate (used when the user explicitly approves a proposal)."""
        ticker = (ticker or "").strip().upper()
        if not ticker or ticker in (self._baskets_by_ticker or {}):
            return False
        if ticker in self._watch_cands:
            return False
        # autonomy gate: in propose mode, queue for human approval instead of adding directly
        if not _force and self._autonomy == "propose":
            if not any(p["ticker"] == ticker for p in self._watch_proposals):
                self._watch_proposals.append(
                    {"ticker": ticker, "note": note[:80], "source": source, "status": status}
                )
                try:
                    self._render_proposals(self._state or {})
                except Exception:
                    pass
            return False
        if not _force and self._autonomy == "manual":
            return False  # manual: agent auto-add silently blocked
        import datetime as _dt
        self._watch_cands[ticker] = {
            "ticker": ticker, "note": note[:80], "source": source,
            "status": status, "added_ts": _dt.datetime.now().isoformat(),
        }
        self._save_watchlist()
        self._fetch_fundamentals(ticker)
        try:
            self._render_watchlist(self._state or {})
        except Exception:
            pass
        return True

    def _extract_watch_tickers(self, text: str) -> list:
        """US+Canada exchange-suffixed tickers (.V, .TO, .CN, …) from agent reply text, excluding book names."""
        held = set(self._baskets_by_ticker or {})
        seen: set = set()
        result = []
        for tk in self._WATCH_TICKER_RE.findall(text):
            if tk not in held and tk not in seen:
                seen.add(tk); result.append(tk)
        return result

    def action_watch_dismiss(self, ticker: str) -> None:
        self._watch_cands.pop(ticker, None)
        self._save_watchlist()
        self._render_watchlist(self._state or {})

    def action_watch_approve(self, ticker: str) -> None:
        """Approve a pending watchlist proposal — add the ticker, clear the proposal."""
        prop = next((p for p in self._watch_proposals if p["ticker"] == ticker), None)
        self._watch_proposals = [p for p in self._watch_proposals if p["ticker"] != ticker]
        if prop:
            self._add_to_watchlist(prop["ticker"], note=prop.get("note", ""),
                                   source=prop.get("source", "agent"),
                                   status=prop.get("status", "candidate"), _force=True)
            self._toast(f"✓ {ticker} added to watchlist bench", GREEN)
        self._render_proposals(self._state or {})

    def action_watch_deny(self, ticker: str) -> None:
        """Deny a pending watchlist proposal — discard it."""
        self._watch_proposals = [p for p in self._watch_proposals if p["ticker"] != ticker]
        self._toast(f"✗ {ticker} proposal dismissed", DIM)
        self._render_proposals(self._state or {})

    def action_watch_add_cand(self, ticker: str) -> None:
        """Add a pipeline/engine-suggested ticker directly to the bench."""
        self._dismissed_cands.discard(ticker)
        if self._add_to_watchlist(ticker, source="pipeline", _force=True):
            self._toast(f"✓ {ticker} added to bench", GREEN)
        else:
            self._toast(f"✓ {ticker} already on the bench", DIM)
        self._render_watchlist(self._state or {})

    def action_watch_skip_cand(self, ticker: str) -> None:
        """Skip a pipeline/engine suggestion — hide it from the watchlist this session."""
        self._dismissed_cands.add(ticker)
        self._toast(f"✗ {ticker} skipped", DIM)
        self._render_watchlist(self._state or {})

    def _render_health(self, state) -> None:
        """The expanded BOOK HEALTH card (freed space, the Hub holds the agentic clutter): the book
        rating + integrity bar, forensics (JSF · runway · Sloan), risk (ES95 · avg corr), the posture
        dial, the data-integrity line, and the live priorities (click a named holding to focus it)."""
        hr = state.get("health_radar", {}) or {}
        fr = state.get("forensics", {}) or {}
        ps = state.get("portfolio_stats", {}) or {}
        integ = state.get("integrity", {}) or {}
        posture = state.get("posture") or {}
        health = hr.get("health_rating")
        out = Text()
        out.append("Rating ", style=DIM)
        out.append(f"{_fmt(health)}/10  ", style=Style.parse(health_color(health)) + Style(meta={"@click": "app.explain_book('rating')"}))
        out.append_text(_bar(health, 10)); out.append("\n")
        if hr.get("rating_desc"):
            out.append(str(hr.get("rating_desc"))[:30], style=health_color(health)); out.append("\n")
        # forensics — the JSF gate's book aggregate + runway + the Sloan accrual flag
        jsf = _num(fr.get("jsf_score"))
        out.append("JSF ", style=DIM); out.append(f"{_fmt(jsf)}/4", style=health_color((jsf or 0) * 2.5))
        rw = _num(fr.get("runway"))
        if rw is not None:
            out.append("  runway ", style=DIM)
            out.append(f"{rw:.0f}mo", style=(RED if rw < 6 else (AMBER if rw < 12 else SILVER)))
        sloan = _num(fr.get("sloan_cfo"))
        if sloan is not None:
            out.append("  sloan ", style=DIM)
            out.append(f"{sloan:+.2f}", style=(ORANGE if abs(sloan) > 0.10 else SILVER))
        out.append("\n")
        # risk — tail loss + how correlated the book is (concentration tell)
        es = _num(ps.get("expected_shortfall_95")); corr = _num(ps.get("avg_correlation"))
        out.append("ES95 ", style=DIM)
        out.append(f"{_fmt(es)}%", style=(GREEN if (es or 0) < 5 else (AMBER if (es or 0) < 10 else RED)))
        if corr is not None:
            out.append("  avg ρ ", style=DIM)
            out.append(f"{corr:.2f}", style=(ORANGE if corr > 0.6 else SILVER))
        out.append("\n")
        # posture — the master temperature dial (size cap that composes onto every name)
        if posture.get("label"):
            pc = GREEN if posture.get("code") == "spear_exploit" else (ORANGE if posture.get("code") == "defensive" else SILVER)
            out.append("Posture ", style=DIM)
            out.append(str(posture["label"]), style=Style.parse(f"bold {pc}") + Style(meta={"@click": "app.explain('posture')"}))
            if _num(posture.get("cap")) is not None:
                out.append(f" {posture['cap']:g}x", style=(ORANGE if posture.get("headwind") else GREEN))
            out.append("\n")
        # integrity — stale feeds / forensic waivers, or a clean tick
        out.append("Integrity ", style=DIM)
        if integ.get("any_stale") or integ.get("forensic_override_count"):
            bits = []
            if integ.get("any_stale"):
                bits.append(f"{len(integ.get('stale_feeds', []) or []) or 'feed'} stale")
            if integ.get("forensic_override_count"):
                bits.append(f"{integ['forensic_override_count']} waiver")
            out.append("⚠ " + " · ".join(bits), style=ORANGE)
        else:
            out.append("clean ✓", style=GREEN)
        # priorities — the health radar's to-watch list; link any named holding to focus it
        for p in (hr.get("priorities") or [])[:2]:
            title = str(p.get("title", ""))[:30]
            out.append("\n▸ ", style=AMBER)
            hit = next((tk for tk in (self._baskets_by_ticker or {}) if tk and tk in title), None)
            if hit:
                out.append(title, style=Style.parse(SILVER) + Style(meta={"@click": f"app.focus_tk('{hit}')"}))
            else:
                out.append(title, style=SILVER)
        self.query_one("#healthbody", Static).update(out)

    # ------------------------------------------------------------------ book
    def _book_signature(self, baskets):
        return tuple((b.get("ticker"), b.get("rating"), b.get("band"),
                      _score(b.get("pillars", {}).get("V")), (b.get("gate") or {}).get("cap"),
                      str(b.get("directive"))) for b in baskets)

    def _render_book(self, state, baskets) -> None:
        annos = state.get("agent_annotations", {}) or {}
        anno_sig = tuple(sorted((tk, (v[-1].get("seq") if v else None)) for tk, v in annos.items()))
        sig = (self._book_signature(baskets), anno_sig)
        if sig == self._book_sig:
            return                                          # nothing material changed — keep cursor steady
        self._book_sig = sig
        tbl = self.query_one("#booktbl", DataTable)
        prev = self._focus
        self._suppress_report = True
        tbl.clear()
        self._row_index = {}
        nodes = state.get("nodes", {}) or {}
        for i, b in enumerate(baskets):
            tk = str(b.get("ticker", "?"))
            r = b.get("rating")
            pillars = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
            t, q, v = _score(pillars.get("T")), _score(pillars.get("Q")), _score(pillars.get("V"))
            focus_mark = "▸" if tk == prev else " "
            tick = Text(tk, style="bold white")             # agent badge rides next to the ticker
            if b.get("eval_only"):                          # rated, NOT held — badge it so an eval
                tick.append(" ◇EVAL", style=f"bold {TEAL}")  # row can never read as a holding
            for a in (annos.get(tk) or [])[-1:]:
                tick.append(f" {a.get('badge', '✦')}", style=f"bold {_level_color(a.get('level'))}")
            px = _disp_price(b, nodes.get(tk))             # native-currency price (consistent with floor/upside)
            tbl.add_row(
                Text(f"{focus_mark}{_role_glyph(tk, nodes)}", style=AMBER if tk == prev else health_color(r)),
                tick,
                Text(_money(px), style="white", justify="right"),
                Text(_arch_short(b.get("archetype"), b.get("archetype_code"), b.get("subarchetype")), style=DIM),
                Text(_fmt(r), style=f"bold {health_color(r)}"),
                Text(str(b.get("band", "—"))[:14], style=health_color(r)),
                Text(_fmt(t), style=health_color(t)),
                Text(_fmt(q), style=health_color(q)),
                Text(_fmt(v), style=health_color(v)),
                _upside_text(b),
                _floor_edge(b),
                _gate_text(b),
                Text(str(b.get("directive", "—"))[:22], style=SILVER),
                key=tk,
            )
            self._row_index[tk] = i
        if prev in self._row_index:
            try:
                tbl.move_cursor(row=self._row_index[prev], animate=False)
            except Exception:
                pass
        elif baskets:                                       # first load -> focus the top pick
            top = state.get("conviction_mode", {}).get("top_pick") or baskets[0].get("ticker")
            self._set_focus(top, move_cursor=True, report=True)
        self._suppress_report = False
        if self._focus:
            self._render_book_detail(self._focus)

    # display metric -> (glossary key, label, live-value extractor) for click-to-inspect breakdowns
    _METRICS = {
        "T": ("T", "T · Macro Tailwind", lambda b, V, L: _score((b.get("pillars") or {}).get("T"))),
        "Q": ("Q", "Q · Quality", lambda b, V, L: _score((b.get("pillars") or {}).get("Q"))),
        "V": ("V", "V · Valuation Asymmetry", lambda b, V, L: _score((b.get("pillars") or {}).get("V"))),
        "rating": ("rating", "Conviction rating", lambda b, V, L: _num(b.get("rating"))),
        "rho": ("payoff", "ρ · Payoff ratio", lambda b, V, L: _num(V.get("rho"))),
        "phi": ("floor_coverage", "φ · Floor coverage", lambda b, V, L: _num(V.get("floor_coverage"))),
        "upside": ("upside", "Upside to bull leg", lambda b, V, L: _num(V.get("upside_pct"))),
        "floor": ("floor_coverage", "Floor (margin of safety)", lambda b, V, L: _num(L.get("floor"))),
        "gate": ("gate", "JSF forensic gate", lambda b, V, L: (b.get("gate") or {}).get("cap")),
        "band": ("band", "Conviction band", lambda b, V, L: b.get("band")),
        "directive": ("directive", "Directive", lambda b, V, L: b.get("directive")),
        "mri": ("mri", "MRI · Macro Regime Index", lambda b, V, L: (self._state or {}).get("mri")
                if False else None),  # filled live below
        "posture": (None, "Regime posture", lambda b, V, L: None),
    }

    def action_metals_lens(self) -> None:
        """Pop the METALS LENS — the divergence explainer the regime strip points at ('read the metals
        lens'). It was a dangling pointer: the text existed, the lens didn't. Built live from
        state['regime_lens'] (broad vs metals, each metals driver's read, what a divergence means)."""
        import regime_lens
        lens = (self._state or {}).get("regime_lens") or {}
        title, body = regime_lens.metals_lens_view(lens)
        try:
            self.push_screen(InspectScreen(title, body, ""))
        except Exception:
            pass

    def action_explain(self, key: str, ticker: str = "") -> None:
        """Click ANY metric, anywhere -> pop a live, grounded breakdown over the current view
        (glossary + value + how it's derived + an 'ask the analyst' deep-dive). The universal
        everything-is-clickable core; works from every tab via the modal."""
        tk = (ticker or self._focus or "").strip()
        if ticker:
            self._set_focus(ticker, move_cursor=True)
        title, body, actions = self._metric_breakdown(key, tk)
        try:
            self.push_screen(InspectScreen(title, body, actions))
        except Exception:
            pass

    def on_mouse_move(self, event) -> None:
        """Hover help: surface a one-line explanation for the clickable METRIC under the cursor — reusing
        its existing ``@click=app.explain('…')`` target — as Textual's native tooltip, so every metric is
        self-describing on HOVER, not only on click. Defensive: a hover must NEVER disturb the desk; the
        tooltip clears when the cursor isn't over a metric (non-metric clickables don't tip)."""
        try:
            style = getattr(event, "style", None)
            meta = (getattr(style, "meta", None) or getattr(event, "meta", None) or {})
            help_txt = metric_hover_help(meta.get("@click")) if isinstance(meta, dict) else None
            w, _region = self.get_widget_at(event.screen_x, event.screen_y)
            if w is not None and getattr(w, "tooltip", None) != help_txt:
                w.tooltip = help_txt                       # a string shows on hover; None clears it
        except Exception:
            pass

    def action_ask_metric(self, key: str) -> None:
        """Deep-dive from inside the pop-over: close it, route the metric to the analyst."""
        try:
            self.pop_screen()
        except Exception:
            pass
        spec = self._METRICS.get(key)
        label = spec[1] if spec else key
        tk = self._focus or ""
        self.action_tab("book")
        self._ask_agent(f"Explain {label} for {tk} in depth — what it measures, how the engine "
                        f"computes it here, its live value, and what would change it.", ticker=tk or None)

    def _metric_breakdown(self, key, ticker):
        """Return (title, body, actions) markup for a metric's live, grounded breakdown."""
        b = self._baskets_by_ticker.get(ticker) or {}
        V = (b.get("pillars") or {}).get("V", {}) or {}
        L, _ccy_sfx = _native_ladder(b)                    # native ladder so floor÷price reconciles with φ
        node = ((self._state or {}).get("nodes") or {}).get(ticker, {}) or {}
        price = _disp_price(b, node)
        spec = self._METRICS.get(key)
        gloss = ((self._state or {}).get("conviction_mode") or {}).get("glossary") or {}
        glos_key, label = (spec[0], spec[1]) if spec else (key, key)
        val = spec[2](b, V, L) if spec else None
        if key == "mri":
            val = (self._state or {}).get("mri")

        title = f"[bold {GOLD}]{self._esc(label)}[/]  [bold white]{self._esc(ticker or 'book')}[/]"
        lines = []
        if key == "phi" and _num(L.get("floor")) is not None and price:
            lines.append(f"[{DIM}]live[/]  φ = floor ÷ price = {_money(L.get('floor'))} ÷ {_money(price)} "
                         f"= [bold {GREEN if (val or 0) >= 1 else SILVER}]{_fmt(val, '{:.2f}')}[/]")
            lines.append(f"[{DIM}](φ ≥ 1 = trading below the liquidation floor — margin of safety)[/]")
        elif key == "rho":
            lines.append(f"[{DIM}]live[/]  ρ = upside ÷ downside-to-floor = "
                         f"[bold {SILVER}]{_fmt(val, '{:.2f}')}[/]   [{DIM}](the asymmetry payoff ratio)[/]")
        elif key == "upside":
            lines.append(f"[{DIM}]live[/]  [bold {GREEN if (val or 0) >= 0 else RED}]{_fmt(val, '{:+.0f}')}%[/]"
                         f"  [{DIM}]to the bull leg[/] {_money(L.get('bull'))} [{DIM}]from[/] {_money(price)}")
        elif key == "V":
            mode = V.get("mode", "asymmetry")
            lines.append(f"[{DIM}]live[/]  V = [bold {health_color(val)}]{_fmt(val)}/10[/]"
                         f"   [{DIM}]{self._esc(str(b.get('band', '')))} · {mode} mode[/]")
            if mode == "asymmetry":
                phi = V.get("floor_coverage")
                lines.append(f"[{SILVER}] ├ payoff ρ {_fmt(V.get('rho'), '{:.1f}')} → term "
                             f"{_fmt(V.get('payoff'), '{:.2f}')}[/]  [{DIM}](×0.65) · upside "
                             f"{_fmt(V.get('upside_pct'), '{:+.0f}')}% to the bull leg[/]")
                cov_txt = (f" — buying {(_num(phi) - 1) * 100:.0f}% below the REP floor (asset-backed downside)"
                           if _num(phi) is not None and _num(phi) >= 1 else "")
                lines.append(f"[{SILVER}] └ support φ {_fmt(phi, '{:.2f}')} → term "
                             f"{_fmt(V.get('support'), '{:.2f}')}[/]  [{DIM}](×0.35){cov_txt}[/]")
                lines.append(f"[bold {GOLD}]⚠ V grades the ENTRY, not the destination[/] [{SILVER}]— high V = "
                             f"best entry; V compressing as price rallies UP through the floor is the thesis "
                             f"WORKING (the asymmetry spent as designed), not deteriorating.[/]")
            else:
                lines.append(f"[{SILVER}] ├ value {_fmt(V.get('value_term'), '{:.2f}')}[/]  [{DIM}](×0.45) · gap "
                             f"{_fmt(V.get('upside_pct'), '{:+.0f}')}% to fair value[/]")
                lines.append(f"[{SILVER}] ├ stability {_fmt(V.get('stability'), '{:.2f}')}[/]  [{DIM}](×0.45) · cash-flow durability[/]")
                lines.append(f"[{SILVER}] └ support φ {_fmt(V.get('floor_coverage'), '{:.2f}')} → "
                             f"{_fmt(V.get('support'), '{:.2f}')}[/]  [{DIM}](×0.10)[/]")
                lines.append(f"[{DIM}](value mode: ~5 at fair value — a quality name isn't marked down for lacking a 5×)[/]")
        elif key == "Q":
            Q = (b.get("pillars") or {}).get("Q", {}) or {}
            lines.append(f"[{DIM}]live[/]  Q = [bold {health_color(val)}]{_fmt(val)}/10[/]"
                         f"   [{DIM}]quality in a vacuum, archetype-tagged[/]")
            lines.append(f"[{SILVER}] ├ JSF {_fmt(Q.get('forensic_score'), '{:.1f}')}/4[/]  "
                         f"[{DIM}](×0.35 · survival; JSF<1.5 hard-gates the whole rating)[/]")
            lens = Q.get("lenses") or {}
            lens_lbl = {"grade": "grade", "scale": "scale", "jurisdiction": "juris",
                        "metallurgy": "metal", "permitting": "permit"}
            lens_str = " · ".join(f"{lens_lbl.get(k, k)} {lens[k]:.2f}" for k in
                                  ("grade", "scale", "jurisdiction", "metallurgy", "permitting") if k in lens)
            lines.append(f"[{SILVER}] ├ resource {_fmt(Q.get('resource_quality'), '{:.2f}')}[/]  [{DIM}](×0.40)"
                         f"{(' · ' + lens_str) if lens_str else ''}[/]")
            lines.append(f"[{SILVER}] └ mgmt {_fmt(Q.get('management'), '{:.2f}')}[/]  [{DIM}](×0.25)[/]")
            lines.append(f"[{DIM}]For the spear Q is LIGHT (0.22) — the edge is V's entry asymmetry (click V).[/]")
        elif key in ("T", "rating", "mri"):
            unit = "" if key == "mri" else "/10"
            lines.append(f"[{DIM}]live[/]  [bold {health_color(val if key != 'mri' else None)}]{_fmt(val)}{unit}[/]")
            if key == "T":
                T = (b.get("pillars") or {}).get("T", {}) or {}
                mom = T.get("commodity_momentum")
                if mom is not None:
                    lines.append(f"[{DIM}](forward-structural · near-term momentum "
                                 f"{_fmt(mom, '{:+.2f}')} is a SEPARATE factor, not summed into T)[/]")
        elif key in ("band", "directive"):
            lines.append(f"[{DIM}]live[/]  [bold {SILVER}]{self._esc(str(val) if val is not None else '—')}[/]")
        elif key == "posture":
            p = (self._state or {}).get("posture") or {}
            lines.append(f"[{DIM}]live[/]  [bold {SILVER}]{self._esc(str(p.get('label', '—')))}[/] "
                         f"{p.get('cap', '')}x   [{DIM}]{self._esc(str(p.get('rationale', '')))}[/]")
        else:
            lines.append(f"[{DIM}]live[/]  [bold {SILVER}]{_fmt(val) if val is not None else '—'}[/]")
        g = gloss.get(glos_key) if glos_key else None
        if g:
            lines.append("")
            for ln in str(g).split("\n")[:8]:
                if ln.strip():
                    lines.append(f"[{SILVER}]{self._esc(ln.strip())}[/]")
        actions = (f"[@click=app.ask_metric('{key}')][{TEAL}]› ask the analyst for the full story[/][/]"
                   f"   [{DIM}]· Esc to close[/]")
        return title, "\n".join(lines), actions

    def action_explain_book(self, key: str = "rating") -> None:
        """BOOK-level explainer — clicking the BOOK HEALTH rating pops a summary of the BOOK's health
        (quality · forensics · risk · posture), NOT a single name's T/Q/V conviction. Distinct from
        ``action_explain``, which is name-scoped to the focused holding."""
        try:
            self.push_screen(InspectScreen(*self._book_health_breakdown(self._state or {})))
        except Exception:
            pass

    def action_ask_book(self) -> None:
        """Deep-dive the BOOK health with the analyst — the subject is the BOOK, never the focused
        stock (the lingering focus is exactly what made this ask go to the wrong name before)."""
        try:
            self.pop_screen()
        except Exception:
            pass
        self.action_tab("book")
        self._ask_agent("Explain the BOOK's health rating in depth — what's driving it across quality, "
                        "the JSF forensic gate, runway, ES95 tail risk and average correlation, and the "
                        "regime posture; and what would move it. Book-level, not a single holding.",
                        ticker=None)

    def _book_health_breakdown(self, state):
        """(title, body, actions) for the BOOK HEALTH rating — the aggregate, explained, with a
        book-scoped 'ask the analyst'."""
        hr = state.get("health_radar", {}) or {}
        fr = state.get("forensics", {}) or {}
        ps = state.get("portfolio_stats", {}) or {}
        posture = state.get("posture") or {}
        integ = state.get("integrity", {}) or {}
        gloss = (state.get("conviction_mode") or {}).get("glossary") or {}
        health = hr.get("health_rating")
        L = [f"[{DIM}]rating[/]  [bold {health_color(health)}]{_fmt(health)}/10[/]"
             + (f"   [{health_color(health)}]{self._esc(str(hr.get('rating_desc')))}[/]" if hr.get("rating_desc") else ""),
             f"[{SILVER}]The BOOK's health — the aggregate of quality, forensics, tail risk and posture. "
             f"It is NOT a single name's T/Q/V conviction; click a holding's rating for that.[/]", ""]
        jsf, rw, sloan = _num(fr.get("jsf_score")), _num(fr.get("runway")), _num(fr.get("sloan_cfo"))
        L.append(f"[{DIM}]forensics[/]  JSF [bold {health_color((jsf or 0)*2.5)}]{_fmt(jsf)}/4[/]"
                 + (f"  ·  runway [bold {SILVER}]{rw:.0f}mo[/]" if rw is not None else "")
                 + (f"  ·  sloan [bold {SILVER}]{sloan:+.2f}[/]" if sloan is not None else ""))
        es, corr = _num(ps.get("expected_shortfall_95")), _num(ps.get("avg_correlation"))
        L.append(f"[{DIM}]risk[/]  ES95 [bold {SILVER}]{_fmt(es)}%[/] [{DIM}](tail loss)[/]"
                 + (f"  ·  avg ρ [bold {SILVER}]{corr:.2f}[/] [{DIM}](concentration)[/]" if corr is not None else ""))
        if posture.get("label"):
            L.append(f"[{DIM}]posture[/]  [bold {SILVER}]{self._esc(str(posture['label']))}[/] "
                     f"{posture.get('cap', '')}x   [{DIM}]{self._esc(str(posture.get('rationale', '')))}[/]")
        clean = not (integ.get("any_stale") or integ.get("forensic_override_count"))
        L.append(f"[{DIM}]integrity[/]  " + (f"[{GREEN}]clean ✓[/]" if clean else f"[{ORANGE}]⚠ stale feeds / waivers[/]"))
        prios = [str(p.get("title", ""))[:60] for p in (hr.get("priorities") or [])[:3]]
        if prios:
            L.append("")
            L.append(f"[{DIM}]priorities[/]")
            L += [f"[{AMBER}]▸[/] [{SILVER}]{self._esc(p)}[/]" for p in prios]
        g = gloss.get("health_rating") or gloss.get("book_health")
        if g:
            L.append("")
            L += [f"[{SILVER}]{self._esc(ln.strip())}[/]" for ln in str(g).split("\n")[:6] if ln.strip()]
        title = f"[bold {GOLD}]BOOK HEALTH[/]  [bold white]book[/]"
        actions = (f"[@click=app.ask_book][{TEAL}]› ask the analyst about the book[/][/]"
                   f"   [{DIM}]· Esc to close[/]")
        return title, "\n".join(L), actions

    def action_tape(self, seq: int) -> None:
        """Click a DESK TAPE entry -> pop its full detail + actions (focus the name, dig in). Makes
        the tape interactive, not just a log."""
        acts = (self._state or {}).get("agent_activity", []) or []
        ev = next((a for a in acts if a.get("seq") == int(seq)), None)
        if not ev:
            return
        tk = ev.get("ticker")
        title = f"[bold {GOLD}]{self._esc(str(ev.get('kind', 'event')).upper())}[/]  " \
                f"[{SILVER}]{self._esc(str(ev.get('agent', '')))}[/]"
        body = [f"[white]{self._esc(str(ev.get('summary', '')))}[/]",
                f"\n[{DIM}]{_rel_age(ev.get('ts'))}" + (f" · {self._esc(tk)}" if tk else "") + "[/]"]
        rep = (self._state or {}).get("agent_reply") or {}
        if ev.get("kind") in ("reply", "response") and rep.get("text"):
            body.append(f"\n[{SILVER}]{self._esc(str(rep.get('text'))[:1200])}[/]")
        acts_md = "[#74747C]Esc to close[/]"
        if tk:
            acts_md = (f"[@click=app.focus_tk('{tk}')][{TEAL}]› focus {self._esc(tk)}[/][/]   "
                       f"[@click=app.go_council_tk('{tk}')][{TEAL}]› council[/][/]   [#74747C]· Esc to close[/]")
        try:
            self.push_screen(InspectScreen(title, "\n".join(body), acts_md))
        except Exception:
            pass

    def action_go_council_tk(self, tk: str) -> None:
        try:
            self.pop_screen()
        except Exception:
            pass
        self._set_focus(str(tk), move_cursor=True)
        self.action_go_council()

    def _render_book_detail(self, ticker) -> None:
        b = self._baskets_by_ticker.get(ticker)
        det = self.query_one("#conviction", Static)
        if not b:
            det.update(Text("no live data for this name", style=DIM))
            return
        node = ((self._state or {}).get("nodes") or {}).get(ticker, {}) or {}
        fund = self._fund.get(ticker) or {}
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) if isinstance(pil.get("V"), dict) else {}
        rib = b.get("confidence_ribbon", {}) or {}
        L, ccy_sfx = _native_ladder(b)                      # native: price/floor/ladder reconcile with φ/upside
        rating = b.get("rating")
        price = _disp_price(b, node)

        # ── header: ticker · hero conviction read (◆ rating + band), then role · archetype ──
        head = Text()
        head.append(f"{ticker}   ", style=f"bold {GOLD}")
        rt = _rating(rating, b.get("band", "—"))                 # ◆ 8.6  PRIME CONVICTION
        rt.stylize(Style(meta={"@click": f"app.explain('rating', '{ticker}')"}))
        head.append_text(rt)
        ctx = Text()
        if node.get("role"):
            ctx.append(f"{node.get('role')}  ·  ", style=DIM)
        ctx.append(_arch_short(b.get('archetype'), b.get('archetype_code'), b.get('subarchetype')), style=DIM)

        # ── price line: bright last + day change · upside · floor (margin of safety) ──
        pl = Text("price ", style=DIM)
        pl.append(f"{_money(price)}{ccy_sfx}", style="bold white")
        chg = _num(fund.get("changePercentage"))
        if chg is not None:
            pl.append(f"  {'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%", style=(GREEN if chg >= 0 else RED))
        up = _num(V.get("upside_pct"))
        if up is not None:
            pl.append("    upside ", style=DIM)
            pl.append(f"{up:+.0f}%", style=Style.parse(GREEN if up >= 0 else RED) + Style(meta={"@click": "app.explain('upside')"}))
        fl = _num(L.get("floor")); cov = _num(V.get("floor_coverage")); dtf = _num(V.get("downside_to_floor_pct"))
        if fl is not None:
            pl.append("    floor ", style=DIM)
            pl.append(f"{_money(fl)}", style=Style.parse(ORANGE) + Style(meta={"@click": "app.explain('floor')"}))
            if cov is not None:
                pl.append(f" φ{cov:.2f}", style=Style.parse(GREEN if cov >= 1 else DIM) + Style(meta={"@click": "app.explain('phi')"}))
            if dtf is not None:
                pl.append(f" −{abs(dtf):.0f}%", style=ORANGE)

        # ── fundamentals (FMP where covered; many juniors aren't — degrade gracefully) ──
        _mc, _, _ = self._mcap_display(ticker, price, fund)   # sourced shares × px, not FMP's stale cap
        fl2 = Text("mcap ", style=DIM)
        fl2.append(f"{_compact(_mc)}".rjust(0), style=SILVER)
        fl2.append("   β ", style=DIM); fl2.append(f"{_fmt(fund.get('beta'), '{:.2f}')}", style=SILVER)
        if _num(fund.get("volume")) is not None:
            fl2.append("   vol ", style=DIM)
            fl2.append(f"{_compact(fund.get('volume'))}/{_compact(fund.get('averageVolume'))} avg", style=SILVER)
        if not fund:
            fl2.append("   (no FMP coverage — engine price)", style=DIM)
        rbar = _range_bar(fund.get("range"), price)

        # ── conviction: T/Q/V as the kit's PillarBars (labelled fill bars, each click-to-inspect) ──
        _PLAB = {"T": "T · TAILWIND", "Q": "Q · QUALITY", "V": "V · VALUE"}
        pillars = []
        for k in ("T", "Q", "V"):
            row = _pillar(_PLAB[k], _score(pil.get(k)))
            row.stylize(Style(meta={"@click": f"app.explain('{k}')"}))   # whole bar inspects the pillar
            pillars.append(row)

        # ── asymmetry summary under the bars: ρ · ribbon · the JSF gate as a chip (kit Badge) ──
        summ = Text()
        if _num(V.get("rho")) is not None:
            summ.append("ρ ", style=DIM)
            summ.append(f"{_fmt(V.get('rho'), '{:.2f}')}   ",
                        style=Style.parse(SILVER) + Style(meta={"@click": "app.explain('rho')"}))
        summ.append(f"±{_fmt(rib.get('plus_minus'), '{:.2f}')} ({rib.get('quality', '?')})   ",
                    style=quality_color(rib.get("quality")))
        g = b.get("gate") or {}
        if not g.get("applied"):
            summ.append_text(_badge("GATE CLEAN", "good"))
        else:
            cap = _num(g.get("cap"))
            lvl = "risk" if (cap is not None and cap <= 5.0) else "warn"
            summ.append_text(_badge("⚠ " + str(g.get("reason", "capped")).split(";")[0][:22], lvl))

        # forecast-share — the Lynch guardrail (measure-only): how much of THIS rating is a macro FORECAST
        # vs the business + floor. Context-aware: a spear is a regime bet BY DESIGN (info); a BALLAST with a
        # high share is the alarm (warn); a low share reads as healthy/business-driven (good).
        fcs = b.get("forecast_share") or {}
        if fcs.get("available") and _num(fcs.get("forecast_share")) is not None:
            _fpct = round(_num(fcs.get("forecast_share")) * 100)
            summ.append(" ")
            if fcs.get("forecast_native"):
                summ.append_text(_badge(f"REGIME BET {_fpct}%", "info"))
            elif (fcs.get("flag") or {}).get("flagged"):
                summ.append_text(_badge(f"⚠ FORECAST {_fpct}%", "warn"))
            else:
                summ.append_text(_badge(f"FORECAST {_fpct}%", "good"))

        bar, legend = _ladder([("F", L.get("floor"), ORANGE), ("b", L.get("bear"), RED),
                               ("●", price, "white"), ("◆", L.get("base"), GOLD),
                               ("▲", L.get("bull"), GREEN)])

        cat = b.get("catalysts") or []
        cat_line = Text()
        if cat:
            sig = _num(b.get("catalyst_signal"))
            cat_line.append(f"↯{len(cat)} ", style=(GREEN if (sig or 0) >= 0 else ORANGE))
            if sig is not None:
                cat_line.append(f"signal {sig:+.1f}  ", style=DIM)
            cat_line.append(" · ".join(str(c.get("headline", c.get("type", "event")))[:30] for c in cat[:3]),
                            style=SILVER)

        # V2 — probability-weighted E[NAV] (shown only when a live signal GROUNDS it; the ± band on
        # `summ` already carries the intrinsic-input distribution). Native currency, like the ladder.
        ev_line = None
        sn = b.get("scenario_nav") or {}
        ev = _num(sn.get("expected_value"))
        if sn.get("grounded") and ev is not None:
            fx = _num(b.get("fx_to_cad")) or 1.0
            p = sn.get("p") or {}
            ev_line = Text("E[NAV] ", style=DIM)
            ev_line.append(f"{_money(ev / fx)}{ccy_sfx}",
                           style=Style.parse(f"bold {GOLD}") + Style(meta={"@click": "app.explain('upside')"}))
            if _num(p.get("bull")) is not None:
                ev_line.append(f"  P(bull) {p['bull'] * 100:.0f}%", style=DIM)
            edge = _num(sn.get("edge_pct"))
            if edge is not None:
                ev_line.append(f"  edge {edge:+.0f}%", style=(GREEN if edge >= 0 else RED))
            drv = sn.get("drivers") or []
            if drv:
                ev_line.append("   " + " · ".join(str(d) for d in drv[:2]), style=FAINT)

        # H5 — the live conviction reading on this thesis (the latest forecast in its trail), if any.
        conv_line = None
        mem = self._memory()
        if mem is not None:
            try:
                cv = mem.query(ticker=ticker, type="conviction", limit=1)   # newest first
                c = _num((cv[0].get("meta") or {}).get("confidence")) if cv else None
                if c is not None:
                    n_trail = len(mem.query(ticker=ticker, type="conviction", limit=0))
                    conv_line = Text("conviction ", style=DIM)
                    conv_line.append(f"{c * 100:.0f}%", style=f"bold {GOLD}")
                    if n_trail > 1:
                        conv_line.append(f"  ({n_trail} readings)", style=FAINT)
                    basis = str((cv[0].get("meta") or {}).get("basis") or "")
                    if basis:
                        conv_line.append(f"  {_clip(basis, 38)}", style=FAINT)
            except Exception:
                conv_line = None

        parts = [head, ctx, pl, fl2]
        if rbar:
            parts.append(rbar)
        parts += [Text(""), *pillars, summ, bar, legend]
        if ev_line is not None:
            parts.append(ev_line)
        if conv_line is not None:
            parts.append(conv_line)
        if cat:
            parts.append(cat_line)
        parts.append(Text(""))
        parts.append(self._name_action_bar(ticker))
        det.update(Group(*parts))

    def _name_action_bar(self, ticker: str) -> Text:
        """Per-name action bar (UX): the key features as VISIBLE, clickable verbs — with the existing
        hotkey shown where one exists (·e/·w/·b) — so they need no command recall. Click any chip, or
        press the shown key while the name is focused; the dispatcher (action_name_verb) routes to the
        SAME handler the keymap / NL bar already uses, so the bar is a thin, discoverable surface."""
        t = str(ticker or "")

        def chip(verb, label, key=""):
            kh = f" [{FAINT}]·{key}[/]" if key else ""
            return f"[@click=app.name_verb('{verb}','{t}')][{TEAL}]{label}[/]{kh}[/]"

        chips = "   ".join([
            chip("council", "Council", "e"), chip("whatif", "What-If", "w"),
            chip("entry", "Entry"), chip("rotate", "Rotate"), chip("replace", "Replace"),
            chip("change", "Change"), chip("story", "Story"), chip("antiscout", "Anti-scout"),
            chip("vet", "Vet"), chip("explain", "Explain"), chip("bear", "Bear", "b"),
        ])
        try:
            return Text.from_markup(f"[{DIM}]▸[/] " + chips)
        except Exception:
            return Text("")

    def _ctx_tag(self, tk: str) -> str:
        """A short context tag for a name — archetype · subarchetype · commodity — to PREPEND to an agent
        prompt so the seat starts WITH the profile (the context-aware-by-default principle), not uphill.
        '' when the name isn't a rated basket."""
        b = (self._baskets_by_ticker or {}).get(tk, {}) if isinstance(self._baskets_by_ticker, dict) else {}
        b = b if isinstance(b, dict) else {}
        bits = [str(b[k]) for k in ("archetype", "subarchetype") if b.get(k)]
        st = b.get("sector_tags") or []
        if st:
            bits.append(str(st[0]))
        return f" ({' · '.join(bits)})" if bits else ""

    def action_name_verb(self, verb: str = "", tk: str = "") -> None:
        """Run a key feature on a name straight from the action bar — no command needed. Focuses the
        name, then routes to the handler the keymap / NL router already uses (a thin surface over what
        already worked), so 'I never use the commands' stops costing you the features."""
        if tk:
            self._set_focus(tk, move_cursor=True)
        name = (self._focus or tk or "").strip()
        ctx = self._ctx_tag(name)                         # context-aware: hand the seat the name's profile
        if verb == "council":
            self.action_go_council()
        elif verb == "whatif":
            self.action_whatif_focus()
        elif verb == "entry":
            self._ask_agent(f"entry timing on {name}{ctx} — am I top-blasting? LOAD / SCALE-IN / WAIT / "
                            f"AVOID-EXTENDED with entry zones (read the entry for THIS archetype, not a generic chart)")
        elif verb == "rotate":
            self._ask_agent(f"should I rotate {name}{ctx}? slot-fit a challenger to its SAME thesis slot "
                            f"first, then run the friction-adjusted rotation gate")
        elif verb == "story":
            self._ask_agent(f"story card on {name}{ctx} — intrinsic decomposed into named legs + drivers "
                            f"+ the breakpoint")
        elif verb == "antiscout":
            self._ask_agent(f"anti-scout {name}{ctx} — what would make me sell it, and is there a better "
                            f"vehicle for the same exposure?")
        elif verb == "change":
            self._change_chooser(name)           # deliberate chooser (cut / rotate) — never auto-stage
        elif verb == "replace":
            self._run_replace(name)
        elif verb == "vet":
            self._run_gauntlet(name)             # the disconfirmation gauntlet: verifier → anti-scout → forensic → graduate
        elif verb == "explain":
            self._run_explain_move(name)         # triage a decoupled/unexplained move → ranked cause + SENTINEL log
        elif verb == "bear":
            self._ask_agent(f"bear case on {name}{ctx}")
        else:
            return
        self._palette_recap = f"{verb} {name}".strip()

    # ------------------------------------------------------------------ company profile
    def action_open_profile(self, ticker: str = "") -> None:
        tk = (ticker or self._focus or "").strip()
        if not tk:
            return
        self._set_focus(tk, move_cursor=True)
        self.action_tab("profile_tab")
        self._render_profile(tk)

    # ------------------------------------------------------------------ Dialectic Council
    def _memory(self):
        """Lazy Living Memory handle (read-only here). None if the substrate is unavailable."""
        m = getattr(self, "_mem", None)
        if m is None:
            try:
                import living_memory
                self._mem = living_memory.LivingMemory()
                m = self._mem
            except Exception:
                self._mem = False
                return None
        return m or None

    def _research(self):
        """Lazy research-cache handle (sourced filings data). None if unavailable."""
        rc = getattr(self, "_rc", None)
        if rc is None:
            try:
                import research_cache
                self._rc = research_cache.ResearchCache()
                rc = self._rc
            except Exception:
                self._rc = False
                return None
        return rc or None

    def _calendar(self):
        """Lazy catalyst-calendar handle (Forge M1). None if the module is unavailable."""
        c = getattr(self, "_cal", None)
        if c is None:
            try:
                import catalyst_calendar
                self._cal = catalyst_calendar.CatalystCalendar()
                c = self._cal
            except Exception:
                self._cal = False
                return None
        return c or None

    def _mcap_display(self, ticker, price, fund):
        """The market cap to SHOW for a name — the single source of truth across every view. Prefers
        the SOURCED filing share count × live price (the post-merger truth) over FMP's marketCap field,
        which goes stale for post-merger TSXV micro-caps (FMP missed AGA.V's merger issuance: ~173M
        implied shares vs the filed 208.6M → a wrong ~97M cap). Returns (mcap, shares_or_None, fmp_mcap):
        shares is None when it fell back to FMP, and fmp_mcap is the raw feed so a caller can flag a
        material disagreement."""
        rc = self._research()
        sh = rc.value(ticker, "shares_out") if rc is not None else None
        fmp_mc = _num((fund or {}).get("marketCap"))
        mc, shares = pick_mcap(sh, price, fmp_mc)
        return mc, shares, fmp_mc

    def _regime_ctx(self) -> dict:
        """The live regime context to stamp on a memory entry (so it's regime-recallable later)."""
        st = self._state or {}
        return {"mri": st.get("mri"),
                "net_tilt": (st.get("macro_tape") or {}).get("net_tilt"),
                "posture": (st.get("posture") or {}).get("code")}

    def _write_note(self, text: str, ticker: str = "") -> None:
        """Persist a plain-text research note to Living Memory, tagged to the focused name and
        stamped with the live regime — so the next Council run / What-If inherits it. This is the
        'type a thought, it becomes structured, connected memory' loop."""
        text = (text or "").strip()
        if not text:
            return
        mem = self._memory()
        tk = (ticker or self._focus or "").strip() or None
        if mem is None:
            self._toast("memory unavailable — note not saved", ORANGE)
            return
        try:
            entry = mem.write("note", text=text, ticker=tk, regime=self._regime_ctx(), source="user")
            where = f" → {tk}" if tk else " (book-level)"
            self._toast(f"✎ note saved to memory{where} — Council & What-If will see it", TEAL)
            eid = (entry or {}).get("id")
            self._receipt(f"note → {tk or 'book'}", "✎", TEAL,
                          undo=(lambda i=eid: mem.retract(i, source="user")) if eid else None)
            self.query_one("#agent_reply", Static).update(self._conversation_markup())   # live in the thread
        except Exception as e:
            self._toast(f"note not saved: {e}", ORANGE)

    # ------------------------------------------------------------------ Forge M1/M2 NL entry points
    def _write_catalyst(self, spec: str) -> None:
        """`catalyst: <kind> | <title> | <YYYY-MM-DD>[..<YYYY-MM-DD>]` — add a WINDOW to the calendar.
        A catalyst is a window, not a point. kind omitted ⇒ inferred (macro if no focus, else drill).
        Grounded-or-silent: an undated catalyst is refused, not guessed."""
        cal = self._calendar()
        if cal is None:
            self._toast("calendar unavailable — catalyst not saved", ORANGE)
            return
        import catalyst_calendar as cc
        parts = [p.strip() for p in spec.split("|")]
        kind = title = dates = None
        if len(parts) >= 3:
            kind, title, dates = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            if parts[0].lower() in cc.KINDS:
                kind, title = parts[0].lower(), parts[1]
            else:
                title, dates = parts[0], parts[1]
        else:
            title = parts[0]
        kind = (kind or ("macro" if not self._focus else "drill_result")).lower()
        ws = we = None
        if dates:
            ws, we = ([d.strip() for d in dates.split("..", 1)] + [None])[:2] if ".." in dates \
                else (dates.strip(), None)
        if not ws:
            self._toast("need a date — catalyst: <kind> | <title> | YYYY-MM-DD[..YYYY-MM-DD]", ORANGE)
            return
        tk = None if kind == "macro" else (self._focus or None)
        try:
            e = cal.write(kind=kind, title=(title or kind), window_start=ws, window_end=we,
                          ticker=tk, confidence="guided", source="manual", regime=self._regime_ctx())
            where = f" → {tk}" if tk else " (macro)"
            self._toast(f"📅 catalyst saved{where}: {e['window_start'][:10]}…{e['window_end'][:10]}", TEAL)
            self._receipt(f"catalyst → {tk or 'macro'}", "📅", TEAL)
        except Exception as ex:
            self._toast(f"catalyst not saved: {ex}", ORANGE)

    def _amend_thesis(self, *, claim=None, rule=None):
        """Append a claim/rule to the focused name's thesis (creating a CONDITIONAL one if none yet),
        VALIDATE it, and persist via supersede (append-only). Returns the new body or None on error."""
        mem = self._memory()
        if mem is None:
            self._toast("memory unavailable", ORANGE)
            return None
        tk = (self._focus or "").strip()
        if not tk:
            self._toast("focus a name first (claims/rules attach to a name's thesis)", ORANGE)
            return None
        import thesis_ledger as tl
        cur = mem.latest_thesis(tk)
        body = dict((cur or {}).get("meta") or {})
        claims = list(body.get("claims") or [])
        rules = list(body.get("rules") or [])
        if claim:
            claims.append(claim)
        if rule:
            rules.append(rule)
        _std = {"ticker", "stance", "archetype", "claims", "rules", "expected", "linked_calendar",
                "source_urls", "entered_at", "regime_at_entry"}
        new_body = tl.build_thesis(
            tk, stance=body.get("stance", "CONDITIONAL"), archetype=body.get("archetype", ""),
            claims=claims, rules=rules, expected=body.get("expected"),
            linked_calendar=body.get("linked_calendar"), source_urls=body.get("source_urls"),
            regime_at_entry=body.get("regime_at_entry") or self._regime_ctx(),
            intangibles={k: v for k, v in body.items() if k not in _std})
        ok, errors = tl.validate_thesis(new_body)
        if not ok:
            self._toast("rejected: " + "; ".join(errors)[:120], ORANGE)
            return None
        try:
            txt = tl.thesis_summary_line(new_body)
            if cur:
                mem.supersede(cur["id"], "thesis", text=txt, ticker=tk, regime=self._regime_ctx(),
                              meta=new_body, source="user")
            else:
                mem.write("thesis", text=txt, ticker=tk, tags=["thesis", new_body["stance"].lower()],
                          regime=self._regime_ctx(), meta=new_body, source="user")
            try:
                self.query_one("#agent_reply", Static).update(self._conversation_markup())
            except Exception:
                pass
            return new_body
        except Exception as ex:
            self._toast(f"thesis not saved: {ex}", ORANGE)
            return None

    def _amend_thesis_claim(self, spec: str) -> None:
        """`claim: <text> [| <metric> <op> <threshold>]` — a manual claim, or one bound to an engine
        metric (Sentinel re-checks it every sweep)."""
        import thesis_ledger as tl
        if "|" in spec:
            text, expr = [p.strip() for p in spec.split("|", 1)]
            toks = expr.split()
            if len(toks) >= 3:
                thr = toks[2]
                try:
                    thr = float(thr)
                except ValueError:
                    pass
                c = tl.new_claim(text, metric=toks[0], op=toks[1], threshold=thr)
            else:
                c = tl.new_claim(text)
        else:
            c = tl.new_claim(spec.strip())
        body = self._amend_thesis(claim=c)
        if body is not None:
            self._toast(f"✓ claim bound to {self._focus} thesis ({len(body['claims'])} claim(s))", TEAL)

    def _amend_thesis_rule(self, spec: str) -> None:
        """`rule: <trigger> -> <action> [arg]` — arm a pre-commitment. The trigger is parsed through
        the safe grammar; a malformed one is rejected here, never armed."""
        if "->" not in spec:
            self._toast("form: rule: <trigger> -> <action> [arg]   e.g. phi < 1.0 -> trim_to 0.4", ORANGE)
            return
        import thesis_ledger as tl
        trig, act = [p.strip() for p in spec.split("->", 1)]
        toks = act.split()
        action = toks[0] if toks else ""
        arg = None
        if len(toks) > 1:
            try:
                arg = float(toks[1])
            except ValueError:
                arg = toks[1]
        body = self._amend_thesis(rule=tl.new_rule(trig, action, arg=arg))
        if body is not None:
            self._toast(f"🛰 rule armed on {self._focus} ({len(body['rules'])} rule(s))", TEAL)

    def _toast(self, msg, color=None) -> None:
        """Lightweight status line (reuses the what-if status slot; harmless if absent)."""
        try:
            self.query_one("#wf_status", Static).update(Text(str(msg), style=(color or SILVER)))
        except Exception:
            pass

    def _pop_if_modal(self) -> None:
        """Close a detail pop-over if one is open, so acting from inside it dismisses it (a no-op when
        clicked from a rail). Keeps the click-grammar consistent: act in a pop-over → it closes."""
        try:
            if isinstance(self.screen, InspectScreen):
                self.pop_screen()
        except Exception:
            pass

    def action_anno(self, seq) -> None:
        """Open an AGENT NOTE in full — the agent's whole pinned reason + level + the name it's on,
        with focus / council actions (the rail only shows a teaser)."""
        annos = (self._state or {}).get("agent_annotations", {}) or {}
        found, tk = None, None
        for t, lst in annos.items():
            for a in (lst or []):
                if str(a.get("seq")) == str(seq):
                    found, tk = a, t
        if not found:
            return
        lvl = str(found.get("level", "info"))
        col = _level_color(lvl)
        name = "book-level" if tk == "_book" else (tk or "—")
        title = f"[bold {col}]{self._esc(str(found.get('badge', '✦')))} AGENT NOTE[/]  [bold white]{self._esc(name)}[/]"
        body = [f"[#C8C8CE]{self._esc(str(found.get('reason', '')))}[/]", "",
                f"[{DIM}]level[/] [{col}]{self._esc(lvl)}[/]   "
                f"[{DIM}]by[/] [{SILVER}]{self._esc(str(found.get('agent', 'agent')))}[/]   "
                f"[{DIM}]{_rel_age(found.get('ts'))}[/]"]
        acts = "[#74747C]‹ Esc to close[/]"
        if tk and tk != "_book":
            acts = (f"[@click=app.focus_tk('{tk}')][{TEAL}]› focus {self._esc(tk)}[/][/]   "
                    f"[@click=app.go_council_tk('{tk}')][{TEAL}]› council[/][/]   [#74747C]· Esc[/]")
        try:
            self.push_screen(InspectScreen(title, "\n".join(body), acts))
        except Exception:
            pass

    def action_mem_open(self, eid) -> None:
        """Open a saved memory entry IN FULL — the whole note / verdict / thesis, its provenance, and
        the regime it was captured under — and manage it (focus · pin · re-confirm · retract) right
        there. This is the 'access my saved notes' path."""
        mem = self._memory()
        e = mem.get(eid) if mem is not None else None
        if not e:
            self._toast("memory entry not found", ORANGE)
            return
        typ = str(e.get("type", "note"))
        tk = e.get("ticker")
        pinned = e.get("id") in (mem.pinned_ids() if mem is not None else set())
        title = (f"[bold {GOLD}]{self._esc(typ.replace('_', ' ').upper())}[/]  "
                 f"[bold white]{self._esc(tk) if tk else 'book-level'}[/]")
        body = [f"[#C8C8CE]{self._esc(str(e.get('text', '')))}[/]", ""]
        prov = (f"[{DIM}]by[/] [{SILVER}]{self._esc(str(e.get('source', '—')))}[/]   "
                f"[{DIM}]{_mem_age(e.get('ts'))} ago[/]")
        if e.get("confidence"):
            prov += f"   [{DIM}]conf[/] [{SILVER}]{self._esc(str(e['confidence']))}[/]"
        body.append(prov)
        reg = e.get("regime") or {}
        if reg.get("mri") is not None or reg.get("posture") or reg.get("net_tilt"):
            body.append(f"[{DIM}]captured under[/] [{SILVER}]MRI {_fmt(reg.get('mri'), '{:.0f}')} · "
                        f"{self._esc(str(reg.get('posture') or reg.get('net_tilt') or '—'))}[/]")
        if e.get("tags"):
            body.append("  ".join(f"[{DIM}]#{self._esc(str(t))}[/]" for t in (e.get('tags') or [])[:8]))
        stale = (not pinned) and _age_days(e.get("ts")) >= STALE_DAYS
        acts = []
        if tk:
            acts.append(f"[@click=app.focus_tk('{tk}')][{TEAL}]› focus[/][/]")
        acts.append(f"[@click=app.mem_pin('{eid}')][{AMBER if pinned else DIM}]{'unpin' if pinned else '📌 pin'}[/][/]")
        if stale:
            acts.append(f"[@click=app.mem_reaffirm('{eid}')][{ORANGE}]↻ re-confirm[/][/]")
        acts.append(f"[@click=app.mem_del('{eid}')][{DIM}]✕ retract[/][/]")
        acts.append("[#74747C]· Esc[/]")
        try:
            self.push_screen(InspectScreen(title, "\n".join(body), "   ".join(acts)))
        except Exception:
            pass

    # ---- agent oversight (Tier 2): in-flight control strip + action receipts/undo -----------
    def _inflight_add(self, kind: str, label: str, ticker: str = "", agent: str = None,
                      provider: str = None, node: str = None) -> int:
        """Register an in-flight agent run so it's visible (and cancellable) in the AGENTS strip.
        agent/provider record WHO is really doing it and on WHICH model, so the lane/monitor label it
        truthfully (a Gemini-routed scout reads 'scout · gemini-flash', not 'claude'). ``node`` links
        the run to its conversation node so the Quest Log can dedup the live WORKING row against the
        thread row it belongs to (no double-listing of an in-flight ask)."""
        self._job_seq += 1
        self._inflight[self._job_seq] = {"kind": kind, "label": str(label), "ticker": ticker,
                                         "started": time.time(), "proc": None, "cancelled": False,
                                         "agent": agent, "provider": provider, "node": node}
        self._render_agents()
        return self._job_seq

    def _inflight_done(self, jid: int) -> None:
        if self._inflight.pop(jid, None) is not None:
            self._render_agents()

    @staticmethod
    def _task_label(j: dict):
        """Turn an in-flight run into a clear (who, what): the agent that's doing it + the task itself.
        Prefers the recorded agent; else parses '@agent <brief>' or a job's kind + topic."""
        label = str(j.get("label", "")).strip()
        if j.get("agent"):                                  # the run recorded who's really doing it
            if label.startswith("@"):
                parts = label[1:].split(None, 1)
                label = parts[1].strip() if len(parts) > 1 else ""
            return j["agent"], label
        kind = str(j.get("kind", "run"))
        if label.startswith("@"):
            parts = label[1:].split(None, 1)
            return parts[0], (parts[1].strip() if len(parts) > 1 else "")
        if kind not in ("ask", "run", "job", ""):
            return kind, label
        return "claude", label

    def action_cancel_job(self, jid) -> None:
        """Stop an in-flight agent run — terminate the child process and drop its (now-ignored)
        reply. In-flight interruptibility is the agent-trust unlock."""
        job = self._inflight.get(int(jid))
        if not job:
            return
        job["cancelled"] = True                       # the worker reads this and drops its reply
        proc = job.get("proc")
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._pending_user = None                     # stop the conversation waiting on the reply
        self._toast(f"✗ cancelled — {str(job.get('label', 'run'))[:24]}", ORANGE)
        self._render_agents()
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass

    def _render_agents(self) -> None:
        """AGENTS WORKING — the concise, no-noise live view (Hub card #agents_strip): in-flight runs
        with elapsed + cancel, the running pipeline, recent agent flags (annotations), and the last
        receipts with undo. Summaries only — the full feed is the board's Tape; full output is Results."""
        try:
            strip = self.screen.query_one("#agents_strip", Static)
        except Exception:
            return                                         # only present while the Hub is open
        parts = []
        pipe = (self._state or {}).get("pipeline") or {}
        pipe_running = pipe.get("status") == "running"
        live = [(jid, j) for jid, j in self._inflight.items() if not j.get("cancelled")]
        head = Text("⟳ ", style=GREEN)
        head.append("WORKING", style="bold #8C8C92")
        head.append(f"  {len(live) + (1 if pipe_running else 0)}", style=f"bold {GOLD}")
        head.append("   live now" if (live or pipe_running) else "   no agents working — delegate above", style=DIM)
        parts.append(head)
        now = time.time()
        monitoring = self.screen._insp_task if isinstance(self.screen, HubScreen) else None
        for jid, j in live:
            el = max(0, int(now - j.get("started", now)))
            click = Style(meta={"@click": f"app.hub_inspect_task('{jid}')"})
            on = (monitoring == jid)
            who, task = self._task_label(j)              # "who's doing it" + "what the task is" (clear)
            # a prominent, clickable card — the whole row opens a live monitor in FOCUS
            prov = j.get("provider") or self._agent_provider(who)
            model = _run_model_label(who, prov)
            line = Text("▸ " if on else "  ", style=(AMBER if on else TEAL))
            line.append("⟳ ", style=TEAL)
            line.append(f"{who} ", style=Style.parse(f"bold {GOLD if on else AMBER}") + click)
            line.append(f"◇{model} ", style=_MODEL_COLORS.get(model, DIM))
            line.append(_clip(task, 44), style=Style.parse(SILVER) + click)
            if j.get("ticker") and j["ticker"].lower() not in task.lower():
                line.append(f"  {j['ticker']}", style=Style.parse(AMBER) + click)
            line.append(f"   {el}s", style=DIM)
            line.append("  ▸ monitor", style=Style.parse(TEAL) + click)
            line.append("   ✗", style=Style.parse(ORANGE) + Style(meta={"@click": f"app.cancel_job('{jid}')"}))
            parts.append(line)
        if pipe_running:
            line = Text("  ⟳ ", style=TEAL)
            line.append("pipeline ", style=f"bold {SILVER}")
            line.append(_clip(pipe.get("theme", ""), 18), style=SILVER)
            if pipe.get("stage"):
                line.append(f" ·{pipe.get('stage')}", style=DIM)
            parts.append(line)
        if not live and not pipe_running:
            parts.append(Text("  no agents working — delegate a task above", style=DIM))
        # (agent FLAGS now live on the right-hand board — see _render_flags / #hub_flags)
        if self._receipts:
            parts.append(Text("RECEIPTS", style="bold #8C8C92"))
            for r in self._receipts[-2:]:
                line = Text("  ", style=DIM)
                line.append(f"{r['glyph']} ", style=r["color"])
                line.append(_clip(r["text"], 28), style=SILVER)
                if r.get("undo"):
                    line.append("  ", style=DIM)
                    line.append("↶", style=Style.parse(GOLD) + Style(meta={"@click": f"app.undo_receipt('{r['id']}')"}))
                parts.append(line)
        strip.update(Group(*parts))

    def _render_flags(self) -> None:
        """⚑ FLAGS — agent signals pinned on names (pins / highlights), shown on the right-hand board
        (not crammed into the live WORKING lane). Click one to open the full note."""
        try:
            box = self.screen.query_one("#hub_flags", Static)
        except Exception:
            return                                         # only present while the Hub is open
        annos = (self._state or {}).get("agent_annotations", {}) or {}
        flagged = []
        for tk in sorted(annos.keys(), key=lambda t: (t != self._focus, t)):
            for a in (annos[tk] or [])[-2:]:
                flagged.append((tk, a))
        head = Text("⚑ ", style=AMBER)
        head.append("FLAGS", style="bold #8C8C92")
        head.append(f"  {len(flagged)}", style=f"bold {GOLD}")
        head.append("   agent signals on names · click to open", style=DIM)
        parts = [head]
        if not flagged:
            parts.append(Text("  none — agents pin signals here as they surface them", style=DIM))
        for tk, a in flagged[:6]:
            col = _level_color(a.get("level"))
            meta = Style(meta={"@click": f"app.anno('{a.get('seq', 0)}')"})
            ln = Text("  ")
            ln.append(f"{a.get('badge', '✦')} ", style=Style.parse(f"bold {col}") + meta)
            ln.append(f"{'BOOK' if tk == '_book' else tk} ", style=Style.parse(f"bold {col}") + meta)
            ln.append(_clip(a.get("reason", ""), 38), style=SILVER)
            parts.append(ln)
        box.update(Group(*parts))

    def _receipt(self, text: str, glyph: str = "✓", color: str = None, undo=None) -> None:
        """Record an action receipt (what changed) + an optional undo closure, shown in the AGENTS
        strip. Receipts add reversibility on top of the Desk Tape's append-only log."""
        self._receipt_seq += 1
        self._receipts.append({"id": self._receipt_seq, "text": str(text), "glyph": glyph,
                               "color": (color or GREEN), "undo": undo, "ts": time.time()})
        del self._receipts[:-3]                        # keep the last few
        self._render_agents()

    def _record_done_run(self, agent, subject, summary, cat="thread", ref=None) -> None:
        """Log a FINISHED agent run / piece of research onto the Hub's Done board — a readable card.
        Clicking it opens the full result in the FOCUS reader (a Book thread, or a saved Result draft).
        When the Hub is open, auto-opens the result in the review panel so it's immediately readable."""
        self._done_seq += 1
        self._done_runs.insert(0, {"id": self._done_seq, "agent": str(agent or "agent"),
                                   "subject": str(subject or ""), "summary": _clip(str(summary or ""), 56),
                                   "cat": cat, "ref": ref, "ts": time.time()})
        del self._done_runs[12:]                        # keep the last dozen
        if isinstance(self.screen, HubScreen):
            try:
                self._render_hub_feed()                 # refresh the unified feed
                self.screen.open_ref(cat, ref)          # auto-open result in the review panel
            except Exception:
                pass
        elif isinstance(self.screen, (BlendHubScreen, BlendSurface)):
            self._refresh_hub()                         # the new event fade-rises into the Quest Log

    def action_undo_receipt(self, rid) -> None:
        """Reverse the most recent reversible action (memory note → supersede; saved file → delete)."""
        r = next((x for x in self._receipts if str(x["id"]) == str(rid)), None)
        if not r or not r.get("undo"):
            return
        try:
            r["undo"]()
        except Exception as exc:
            self._toast(f"undo failed: {exc}", ORANGE)
            return
        self._receipts.remove(r)
        self._toast(f"↺ undone — {str(r['text'])[:30]}", DIM)
        self._render_agents()
        try:                                           # reflect any thread / memory change live
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass

    def _undo_file(self, path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass
        self._refresh_decisions()

    # ---- memory management (Tier 2): pin / edit / retract / re-confirm + provenance ----------
    def _after_mem_change(self) -> None:
        """Reflect a memory mutation everywhere it shows (the agent column + the inline research thread)."""
        try:
            self._refresh_hub()
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass

    def action_mem_pin(self, eid: str) -> None:
        """Pin / unpin a memory entry — pinned floats to the top and is exempt from decay."""
        self._pop_if_modal()                          # if invoked from the detail pop-over, close it
        mem = self._memory()
        if mem is None:
            return
        try:
            if eid in mem.pinned_ids():
                mem.unpin(eid); self._toast("memory unpinned", DIM)
            else:
                mem.pin(eid, source="user"); self._toast("📌 pinned — kept & exempt from decay", AMBER)
        except Exception as exc:
            self._toast(f"pin failed: {exc}", ORANGE); return
        self._after_mem_change()

    def action_mem_del(self, eid: str) -> None:
        """Retract a memory entry — superseded so it leaves the live stream (the record survives)."""
        self._pop_if_modal()
        mem = self._memory()
        if mem is None:
            return
        try:
            e = mem.get(eid) or {}
            mem.retract(eid, source="user")
        except Exception as exc:
            self._toast(f"retract failed: {exc}", ORANGE); return
        self._receipt(f"retracted {str(e.get('text', ''))[:20]}", "✕", ORANGE)
        self._after_mem_change()

    def action_mem_reaffirm(self, eid: str) -> None:
        """Re-confirm a stale entry — supersede with a fresh-dated copy (resets decay)."""
        self._pop_if_modal()
        mem = self._memory()
        if mem is None:
            return
        try:
            mem.reaffirm(eid, regime=self._regime_ctx(), source="user")
        except Exception as exc:
            self._toast(f"re-confirm failed: {exc}", ORANGE); return
        self._toast("↻ re-confirmed — memory freshened", GREEN)
        self._after_mem_change()

    def action_mem_edit(self, eid: str) -> None:
        """Edit an entry — load it into the chat bar; saving supersedes it (an immutable edit)."""
        self._pop_if_modal()
        mem = self._memory()
        e = mem.get(eid) if mem is not None else None
        if not e:
            return
        self._editing_mem = eid
        self.action_tab("book")
        try:
            box = self.query_one("#cmdbar", Input)
            box.value = f"note: {e.get('text', '')}"
            box.cursor_position = len(box.value)
            self.call_after_refresh(box.focus)
        except Exception:
            pass
        self._toast("editing memory — Enter to save (supersedes the original)", TEAL)

    def _edit_note(self, eid: str, text: str) -> None:
        mem = self._memory()
        text = (text or "").strip()
        if mem is None or not text:
            return
        try:
            e = mem.get(eid) or {}
            mem.supersede(eid, e.get("type", "note"), text=text, ticker=e.get("ticker"),
                          regime=self._regime_ctx(), source="user", meta={"edited": True})
        except Exception as exc:
            self._toast(f"edit failed: {exc}", ORANGE); return
        self._receipt(f"edited {text[:20]}", "✎", TEAL)
        self._after_mem_change()

    def _render_bench_profile(self, ticker: str, body) -> None:
        """Profile page for a watchlist/bench ticker — not yet in the book's conviction baskets.
        Shows watchlist context, FMP fundamentals (if fetched), saved research, and action buttons."""
        wc = self._watch_cands.get(ticker, {})
        fund = self._fund.get(ticker) or {}
        rule = f"[{BORDER}]{'─' * 58}[/]"
        e = self._esc

        hdr = f"[bold {GOLD}]{e(ticker)}[/]"
        if fund.get("companyName"):
            hdr += f"  [{SILVER}]{e(fund['companyName'])}[/]"
        meta = " · ".join(e(x) for x in (fund.get("exchange"), fund.get("sector")) if x)
        if meta:
            hdr += f"   [{DIM}]{meta}[/]"
        hdr += f"  [{AMBER}]BENCH[/]"
        out = [hdr, rule]

        # watchlist entry context (how it got here)
        if wc:
            src = e(str(wc.get("source") or "agent"))
            note = e(str(wc.get("note") or ""))
            ts = str(wc.get("added_ts") or "")[:10]
            st = str(wc.get("status") or "candidate")
            out.append(f"[{DIM}]source[/] [{TEAL}]{src}[/]  [{DIM}]added[/] [{SILVER}]{ts}[/]"
                       f"  [{DIM}]status[/] [{AMBER}]{e(st)}[/]")
            if note:
                out.append(f"[{DIM}]{note}[/]")
            out.append(rule)

        # FMP fundamentals — same block as the book profile
        if fund:
            price = _num(fund.get("price"))
            chg = _num(fund.get("changePercentage"))
            pr = f"[{DIM}]PRICE[/] [bold white]{_money(price)}[/]"
            if chg is not None:
                pr += f" [{GREEN if chg >= 0 else RED}]{'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%[/]"
            mc2, _, _ = self._mcap_display(ticker, price, fund)   # sourced shares × px, not FMP's stale cap
            pr += f"    [{DIM}]MCAP[/] [{SILVER}]{_compact(mc2)}[/]"
            pr += f"    [{DIM}]β[/] [{SILVER}]{_fmt(fund.get('beta'), '{:.2f}')}[/]"
            if _num(fund.get("volume")) is not None:
                pr += f"    [{DIM}]VOL[/] [{SILVER}]{_compact(fund.get('volume'))}/{_compact(fund.get('averageVolume'))}[/]"
            out.append(pr)
            rng = fund.get("range")
            if rng:
                try:
                    lo, hi = [float(x) for x in str(rng).replace("$", "").split("-")[:2]]
                    frac = max(0.0, min(1.0, (float(price) - lo) / (hi - lo))) if (price and hi > lo) else 0.0
                    rc = GREEN if frac >= 0.66 else (RED if frac <= 0.33 else AMBER)
                    out.append(f"[{DIM}]52wk[/] [{SILVER}]{_money(lo)}–{_money(hi)}[/]  [{rc}]{frac * 100:.0f}%[/]")
                except (ValueError, IndexError, TypeError):
                    pass
            desc = str(fund.get("description") or "")
            if desc:
                out.append(f"[{DIM}]{e(desc[:220])}[/]")
        elif ticker not in self._fund:
            out.append(f"[{DIM}]fetching fundamentals…[/]")
        else:
            out.append(f"[{DIM}]no FMP/yfinance coverage for {e(ticker)}[/]")

        # saved research files for this ticker
        out.append(rule)
        res_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        safe = ticker.replace(".", "_").upper()
        research_files = []
        try:
            if os.path.isdir(res_dir):
                research_files = sorted(
                    [f for f in os.listdir(res_dir) if f.upper().startswith(safe + "_") and f.endswith(".md")],
                    reverse=True
                )[:5]
        except Exception:
            pass
        if research_files:
            out.append(f"[bold {AMBER}]RESEARCH[/]  [{DIM}]{len(research_files)} file(s)[/]")
            for fname in research_files:
                safe_name = e(fname[:42])
                out.append(f"  [@click=app.open_dossier('{safe_name}')][{TEAL}]▸ {safe_name}[/][/]")
        # conversation threads bound to this ticker
        thr = [n for n in self._conv.values() if not n.get("parent") and (n.get("ticker") or "") == ticker]
        if thr:
            if not research_files:
                out.append(f"[bold {AMBER}]RESEARCH[/]")
            for n in thr[:4]:
                out.append(f"  [{TEAL}]▸ thread[/] [{SILVER}]{e(str(n.get('text', ''))[:40])}[/]")

        # action buttons
        out.append(rule)
        tk_ = e(ticker)
        out.append(
            f"[@click=app.bench_act('{tk_}','synthesis')][{TEAL}]→ synthesize[/][/]   "
            f"[@click=app.bench_act('{tk_}','bear')][{AMBER}]→ bear case[/][/]   "
            f"[@click=app.bench_act('{tk_}','verifier')][{AMBER}]→ verify[/][/]   "
            f"[@click=app.bench_act('{tk_}','scout')][{DIM}]↺ scout[/][/]   "
            f"[@click=app.watch_dismiss('{tk_}')][{DIM}]✕ dismiss[/][/]"
        )
        body.update("\n".join(out))

    def action_bench_act(self, ticker: str, action: str) -> None:
        """Dispatch a research action on a bench/watchlist ticker from the profile action buttons."""
        verb = {"synthesis": "deep-dive and value", "bear": "build the strongest bear case for",
                "verifier": "verify and red-team", "scout": "scout alternatives to"}.get(action, "review")
        self._delegate(action if action != "scout" else "scout",
                       f"{verb} {ticker}.", subject=ticker)
        self._toast(f"→ {action} on {ticker} dispatched", TEAL)

    def _render_profile(self, ticker) -> None:
        body = self.query_one("#profile_body", Static)
        b = self._baskets_by_ticker.get(ticker)
        if not b:
            self._render_bench_profile(ticker, body)
            return
        node = ((self._state or {}).get("nodes") or {}).get(ticker, {}) or {}
        fund = self._fund.get(ticker) or {}
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) if isinstance(pil.get("V"), dict) else {}
        rib = b.get("confidence_ribbon", {}) or {}
        L, ccy_sfx = _native_ladder(b)                      # native currency, consistent with the fundamentals
        gate = b.get("gate", {}) or {}
        rating = b.get("rating")
        hc = health_color(rating)
        price = _disp_price(b, node)
        rule = f"[{BORDER}]{'─' * 58}[/]"

        # header
        hdr = f"[bold {GOLD}]{self._esc(ticker)}[/]"
        if fund.get("companyName"):
            hdr += f"  [{SILVER}]{self._esc(fund.get('companyName'))}[/]"
        meta = " · ".join(self._esc(x) for x in (fund.get("exchange"), fund.get("sector"), node.get("role")) if x)
        if meta:
            hdr += f"   [{DIM}]{meta}[/]"
        out = [hdr, rule]

        # taxonomy: archetype (how it's valued) · sub-archetype (finer sort) · sector tags
        arch = b.get("archetype")
        sub_label = b.get("subarchetype_label") or b.get("subarchetype")
        tax = []
        if arch:
            tax.append(f"[{DIM}]archetype[/] [{TEAL}]{self._esc(str(arch).replace('_', ' '))}[/]")
        if sub_label:
            tax.append(f"[{DIM}]›[/] [{SILVER}]{self._esc(str(sub_label))}[/]")
        if tax:
            out.append("  ".join(tax))
        tags = b.get("sector_tags") or []
        if tags:
            out.append("  ".join(f"[{BORDER}]\\[[/][{AMBER}]{self._esc(str(t))}[/][{BORDER}]][/]"
                                 for t in tags[:8]))

        # price + fundamentals
        chg = _num(fund.get("changePercentage"))
        pr = f"[{DIM}]PRICE[/] [bold white]{_money(price)}{ccy_sfx}[/]"
        if chg is not None:
            pr += f" [{GREEN if chg >= 0 else RED}]{'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%[/]"
        # MCAP from SOURCED filing shares × live price (not FMP's stale marketCap field); when the
        # FMP feed disagrees materially, surface it as a flag so stale feeds are caught, not trusted.
        mc, sh, fmp_mc = self._mcap_display(ticker, price, fund)
        if sh:
            pr += f"    [{DIM}]MCAP[/] [{SILVER}]{_compact(mc)}[/] [{DIM}]({_compact(sh)}sh×px)[/]"
            if fmp_mc and mc and (fmp_mc / mc < 0.87 or fmp_mc / mc > 1.15):
                pr += f"  [{ORANGE}]⚠ FMP feed {_compact(fmp_mc)}[/]"
        else:
            pr += f"    [{DIM}]MCAP[/] [{SILVER}]{_compact(mc)}[/]"
        pr += f"    [{DIM}]β[/] [{SILVER}]{_fmt(fund.get('beta'), '{:.2f}')}[/]"
        if _num(fund.get("volume")) is not None:
            pr += f"    [{DIM}]VOL[/] [{SILVER}]{_compact(fund.get('volume'))}/{_compact(fund.get('averageVolume'))}[/]"
        out.append(pr)
        rng = fund.get("range")
        if rng:
            try:
                lo, hi = [float(x) for x in str(rng).replace("$", "").split("-")[:2]]
                frac = max(0.0, min(1.0, (float(price) - lo) / (hi - lo))) if (price and hi > lo) else 0.0
                rc = GREEN if frac >= 0.66 else (RED if frac <= 0.33 else AMBER)
                out.append(f"[{DIM}]52wk[/] [{SILVER}]{_money(lo)}–{_money(hi)}[/]  [{rc}]{frac * 100:.0f}%[/]")
            except (ValueError, IndexError, TypeError):
                pass
        if not fund:
            out.append(f"[{DIM}](no FMP coverage — engine price; mcap/β/range unavailable)[/]")

        # conviction
        out.append(rule)
        out.append(f"[bold {AMBER}]CONVICTION[/]  [bold {hc}]{_fmt(rating)}/10[/]  [{hc}]{self._esc(b.get('band', '—'))}[/]")
        out.append(f"  [{DIM}]directive[/]  [{SILVER}]{self._esc(b.get('directive', '—'))}[/]")
        tk_ = self._esc(ticker)
        tline = "  "
        for k in ("T", "Q", "V"):
            s = _score(pil.get(k))
            tline += f"[@click=app.explain('{k}','{tk_}')][{DIM}]{k}[/] [{health_color(s)}]{_fmt(s)}[/][/]   "
        if _num(V.get("rho")) is not None:
            tline += f"[@click=app.explain('rho','{tk_}')][{DIM}]ρ[/] [{SILVER}]{_fmt(V.get('rho'), '{:.2f}')}[/][/]   "
        tline += f"[{quality_color(rib.get('quality'))}]±{_fmt(rib.get('plus_minus'), '{:.2f}')} ({self._esc(rib.get('quality', '?'))})[/]"
        out.append(tline)
        up = _num(V.get("upside_pct")); fl = _num(L.get("floor")); cov = _num(V.get("floor_coverage"))
        dtf = _num(V.get("downside_to_floor_pct")); sup = _num(V.get("support"))
        vd = "  "
        if up is not None:
            vd += f"[@click=app.explain('upside','{tk_}')][{DIM}]upside[/] [{GREEN if up >= 0 else RED}]{up:+.0f}%[/][/]   "
        if fl is not None:
            vd += f"[@click=app.explain('floor','{tk_}')][{DIM}]floor[/] [{ORANGE}]{_money(fl)}[/]"
            vd += f"[{DIM}] φ{cov:.2f}[/]" if cov is not None else ""
            vd += "[/]   "
        if dtf is not None:
            vd += f"[{ORANGE}]−{abs(dtf):.0f}% to floor[/]   "
        if sup is not None:
            vd += f"[{DIM}]support {sup:.2f}[/]"
        out.append(vd)
        gr = self._esc(gate.get("reason", "clean"))
        gl = f"  [{DIM}]gate[/]  [{RED if gate.get('applied') else GREEN}]{gr}[/]"
        if _num(gate.get("cap")) is not None and gate.get("applied"):
            gl += f" [{DIM}]· cap {_num(gate.get('cap')):.0f}[/]"
        out.append(gl)

        # valuation ladder points
        out.append(rule)
        pts = [("floor", L.get("floor"), ORANGE), ("bear", L.get("bear"), RED), ("price", price, "white"),
               ("base", L.get("base"), GOLD), ("bull", L.get("bull"), GREEN)]
        out.append(f"[bold {AMBER}]VALUATION[/]   " +
                   "   ".join(f"[{DIM}]{lab}[/] [{c}]{_money(_num(v))}[/]" for lab, v, c in pts if _num(v) is not None))

        # catalysts (full)
        cat = b.get("catalysts") or []
        sig = _num(b.get("catalyst_signal"))
        out.append(rule)
        out.append(f"[bold {AMBER}]CATALYSTS[/] [{DIM}]({len(cat)}{f' · signal {sig:+.1f}' if sig is not None else ''})[/]")
        for c in cat[:8]:
            out.append(f"  [{SILVER}]· {self._esc(str(c.get('headline', c.get('type', 'event')))[:52])}[/]"
                       f"  [{DIM}]{self._esc(c.get('type', ''))}[/]")
        if not cat:
            out.append(f"  [{DIM}]none in window[/]")

        # notes (agent annotations on this name)
        annos = ((self._state or {}).get("agent_annotations") or {}).get(ticker, []) or []
        out.append(rule)
        out.append(f"[bold {AMBER}]NOTES[/]")
        if annos:
            import textwrap
            for a in annos[-6:]:
                col = _level_color(a.get("level"))
                reason = str(a.get("reason", "")).strip()
                src = self._esc(str(a.get("agent", "")))
                # wrap the FULL note (was a silent 52-char slice that dropped the tail) — a pin is
                # meant to be read; badge on the first line, continuation indented, source dim on the last.
                chunks = textwrap.wrap(reason, 58) or [""]
                for i, ch in enumerate(chunks):
                    # the badge opens the full note (level · source · focus/council actions); text is inline too
                    prefix = (f"  [@click=app.anno('{a.get('seq', 0)}')][{col}]{a.get('badge', '✦')}[/][/] "
                              if i == 0 else "    ")
                    suffix = f"  [{DIM}]·{src}[/]" if (i == len(chunks) - 1 and src) else ""
                    out.append(f"{prefix}[{SILVER}]{self._esc(ch)}[/]{suffix}")
        else:
            out.append(f"  [{DIM}]none yet — analysis (explain-move / vet / council) pins a one-line note here[/]")

        # related research (clickable dossiers + threads bound to this name)
        doss = [d for d in self._decisions if str(d.get("ticker", "")).upper() == ticker.upper()]
        thr = [n for n in self._conv.values() if not n.get("parent") and (n.get("ticker") or "") == ticker]
        if doss or thr:
            out.append(rule)
            out.append(f"[bold {AMBER}]RELATED RESEARCH[/]")
            for d in doss[:5]:
                nm = self._esc(str(d.get("name", "")))
                out.append(f"  [@click=app.open_dossier('{nm}')][{TEAL}]▸ {self._esc(str(d.get('title', ''))[:38])}[/][/]"
                           f"  [{DIM}]dossier[/]")
            for n in thr[:5]:
                out.append(f"  [{TEAL}]▸ thread[/] [{SILVER}]{self._esc(str(n.get('text', ''))[:40])}[/]")

        # data & trust — every key input tagged by provenance so nothing is a black box
        out.append(rule)
        out.append(f"[bold {AMBER}]DATA & TRUST[/]  [{DIM}](● live · ◐ cached · ◆ sourced · … pending · ✕ placeholder)[/]")
        gl = {"live": (GREEN, "●"), "cached": (SILVER, "◐"), "stale": (ORANGE, "◐"),
              "config": (ORANGE, "▲"), "placeholder": (RED, "✕"), "na": (DIM, "·"),
              "web": (TEAL, "◆"), "pending": (ORANGE, "…")}
        for label, cls, note in self._provenance_rows(ticker, b):
            col, glyph = gl.get(cls, (SILVER, "·"))
            out.append(f"  [{col}]{glyph}[/] [{SILVER}]{self._esc(label)}[/]"
                       + (" " * max(1, 18 - len(label))) + f"[{DIM}]{self._esc(note)}[/]")
        body.update("\n".join(out))

    def _provenance_rows(self, ticker, b):
        """Per-input provenance for the focused name (audit knowledge × live freshness)."""
        feeds = (self._state or {}).get("data_freshness", {}).get("feeds", {}) or {}

        def age(feed):
            a = _num((feeds.get(feed) or {}).get("age_minutes"))
            return "" if a is None else (f"{a / 60:.0f}h" if a >= 90 else f"{a:.0f}m")

        def st(feed):
            return bool((feeds.get(feed) or {}).get("stale"))

        def price_prov():
            # the focused name's OWN price freshness — the engine stamps per-holding stale + as-of,
            # so a frozen mark shows "STALE · as of <date>" in orange instead of reading as live.
            pf = feeds.get("prices") or {}
            if ticker in (pf.get("stale_holdings") or []):
                ao = (pf.get("holdings_asof") or {}).get(ticker)
                return ("stale", f"STALE · as of {ao}" if ao else "STALE · last close")
            if st("prices"):
                return ("cached", "feed degraded (other names)")
            return ("live", "yfinance")

        covered = bool(self._fund.get(ticker))
        rows = [
            ("price", *price_prov()),
            ("fundamentals", "live" if covered else "na", f"FMP {age('macro')}" if covered else "no FMP coverage"),
            ("macro / regime", "stale" if st("macro") else "live", age("macro") or "—"),
            ("regime history / vol", "stale" if st("mri_history") else "cached", age("mri_history") or "—"),
            ("forensics", "cached", f"last quarter · {age('forensic') or '—'}"),
        ]
        # filings-derived inputs now come from the provenance-stamped research cache (web fallback)
        if getattr(self, "_rc", None) is None:
            try:
                from research_cache import ResearchCache
                self._rc = ResearchCache()
            except Exception:
                self._rc = False

        def rc_row(label, field):
            e = self._rc.get(ticker, field) if self._rc else None
            if not e:
                return (label, "config", "not sourced yet")
            if e.get("value") is None:
                return (label, "pending", f"pending — {str(e.get('note', ''))[:42]}")
            return (label, "web", f"web · {e.get('as_of', '')} · {e.get('confidence', '?')}")

        arch = str(b.get("archetype") or "")
        is_expl = ("convex" in arch or "explor" in arch
                   or (b.get("pillars", {}) or {}).get("V", {}).get("mode") == "asymmetry")
        if is_expl:
            rows += [
                rc_row("in-ground oz I", "in_ground_ageq_oz_indicated"),
                rc_row("in-ground oz Inf", "in_ground_ageq_oz_inferred"),
                rc_row("AISC", "aisc_per_oz"),
                rc_row("NAV / share", "nav_per_share"),
                rc_row("shares out", "shares_out"),
            ]
        else:
            rows += [
                rc_row("floor (book/sh)", "book_value_per_share"),
                rc_row("cash", "cash"),
                rc_row("shares out", "shares_out"),
            ]
        return rows

    # ------------------------------------------------------------------ regime
    def _render_regime(self, state) -> None:
        tape = state.get("macro_tape", {}) or {}
        ctx = (state.get("conviction_mode", {}) or {}).get("context", {}) or {}
        mri = state.get("mri")
        regime = ctx.get("regime") or tape.get("net_tilt", "—")
        head = Text()
        head.append("REGIME  ", style=f"bold {AMBER}")
        head.append(f"{regime}", style=f"bold {bias_color('risk_off' if 'OFF' in str(regime).upper() else 'risk_on')}")
        head.append("    MRI ", style=DIM); head.append(_fmt(mri, "{:.1f}"), style=GOLD)
        head.append(" "); head.append_text(_mri_gauge(mri, 16))
        head.append("    ·  top driver: ", style=DIM)
        head.append(str(tape.get("top_mri_driver", "—")), style=SILVER)

        on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
        total = max(1, on + off)
        tug = Text("\nrisk  ")
        tug.append("▰" * round(on / total * 18), style=GREEN)
        tug.append("▱" * round(off / total * 18), style=ORANGE)
        tug.append(f"  on {on} / off {off}\n", style=DIM)

        # rates & dollar — raw levels (not the spread): DXY, the long end, plus the slope
        metrics = state.get("metrics", {}) or {}
        def _mv(k):
            return (metrics.get(k, {}) or {}).get("value")
        dxy_, y10_, y30_, dmom = _mv("DXY"), _mv("10Y"), _mv("30Y"), _mv("DXY_MOMENTUM")
        rates = Text("\nrates  ", style=f"bold {AMBER}")
        if _num(dxy_) is not None:
            arrow = "▲" if (_num(dmom) or 0) > 0 else "▼"
            rates.append("DXY ", style=DIM)
            rates.append(f"{_fmt(dxy_, '{:.1f}')}{arrow}", style=(ORANGE if (_num(dmom) or 0) > 0 else GREEN))
        rates.append("    10Y ", style=DIM); rates.append(f"{_fmt(y10_, '{:.2f}')}%", style=SILVER)
        rates.append("    30Y ", style=DIM); rates.append(f"{_fmt(y30_, '{:.2f}')}%", style=SILVER)
        if _num(y10_) is not None and _num(y30_) is not None:
            sp = y30_ - y10_
            rates.append("    30Y–10Y ", style=DIM); rates.append(f"{sp:+.2f}%", style=(RED if sp < 0 else SILVER))
        # full UST curve from FMP (1mo…30yr), if available. G4 data-hygiene: the header 10Y/30Y above
        # are the LIVE yfinance marks; this full curve is a separate (often cached) FMP vintage, so
        # label its as-of explicitly — the two tenor values are different vintages, not a contradiction.
        tc = state.get("treasury_curve") or {}
        ten = tc.get("tenors") or {}
        if any(_num(v) is not None for v in ten.values()):
            rates.append("\nUST curve ", style=DIM)
            for lbl, key in (("1M", "month1"), ("3M", "month3"), ("6M", "month6"), ("1Y", "year1"),
                             ("2Y", "year2"), ("5Y", "year5"), ("10Y", "year10"), ("30Y", "year30")):
                if _num(ten.get(key)) is not None:
                    rates.append(f" {lbl} ", style=DIM)
                    rates.append(f"{_fmt(ten.get(key), '{:.2f}')}", style=SILVER)
            _src = tc.get("source", "FMP"); _asof = tc.get("date")
            _tag = f"   ({_src}" + (f" as-of {_asof}" if _asof else "") + (" · cached" if tc.get("cached") else "") + ")"
            rates.append(_tag, style=DIM)
        rates.append("\n")

        # cross-asset macro tape table
        tt = Table(expand=True, show_edge=False, pad_edge=False, box=None)
        for col in ("SIGNAL", "VALUE", "BIAS", "READ"):
            tt.add_column(col, style=DIM, no_wrap=(col != "READ"))
        for s in tape.get("signals", []) or []:
            tt.add_row(
                Text(str(s.get("label", "?")), style=SILVER),
                Text(str(s.get("display", "—")), style=bias_color(s.get("bias"))),
                Text(str(s.get("bias", "")).replace("_", "-"), style=bias_color(s.get("bias"))),
                Text(str(s.get("read", "")), style=DIM),
            )

        # MRI decomposition bars
        dec = state.get("mri_decomposition", {}) or {}
        comps = [(k, _num(v)) for k, v in dec.items() if _num(v) is not None and k != "top_driver"]
        decg = Text("\nMRI components\n", style=f"bold {AMBER}")
        if comps:
            mx = max(abs(v) for _, v in comps) or 1.0
            for k, v in comps[:10]:
                w = round(abs(v) / mx * 14)
                decg.append(f"  {str(k)[:18]:<18} ", style=DIM)
                decg.append("▰" * w + " " * (14 - w), style=(GREEN if v >= 0 else ORANGE))
                decg.append(f"  {v:+.2f}\n", style=SILVER)
        else:
            decg.append("  (no numeric decomposition)\n", style=DIM)

        # integrity / model-risk strip
        integ = state.get("integrity", {}) or {}
        ig = Text("\nintegrity  ", style=f"bold {AMBER}")
        if integ.get("any_stale"):
            ig.append(f"STALE: {', '.join(integ.get('stale_feeds', [])) or 'feed'}  ", style=ORANGE)
        if integ.get("forensic_override_count"):
            ig.append(f"{integ.get('forensic_override_count')} forensic waiver(s) active  ", style=ORANGE)
        if not integ.get("any_stale") and not integ.get("forensic_override_count"):
            ig.append("all feeds fresh · no waivers", style=GREEN)

        self.query_one("#regime", Static).update(Group(head, tug, rates, tt, decg, ig))

    # ------------------------------------------------------------------ desk tape (→ the Hub board)
    def _tape_items(self, state) -> list:
        """The nervous-system feed as Review items (the Hub's Tape category): operator actions + agent
        work + state, newest-first, routine read-only calls (get_/list_…) folded out as noise."""
        out = []
        now = time.time()
        for a in reversed((state or {}).get("agent_activity", []) or []):
            if _routine_read(a):
                continue
            ag = str(a.get("agent", "")).lower()
            actor = "you" if (a.get("kind") in ("ran", "edited", "git", "prompt")
                              and any(k in ag for k in ("operator", "claude", "cockpit"))) else (a.get("agent") or "agent")
            glyph = {"prompt": "›", "tool": "⚙", "response": "✓", "reply": "✓", "note": "•", "proposal": "↯",
                     "alert": "⚠", "focus": "◎", "scenario": "↯", "ran": "⌘", "edited": "✎", "git": "⎇"}.get(a.get("kind"), "•")
            out.append({"cat": "activity", "glyph": glyph, "title": f"{actor}: {a.get('summary', '')}",
                        "ticker": a.get("ticker"), "age": now - float(a.get("ts", now) or now), "ref": a.get("seq", 0)})
        return out

    def _render_autonomy(self, state) -> None:
        """The agent-trust dial — manual · propose · auto (≤ posture cap). The visible boundary on
        how far agents may act on their own; clicking a segment posts a receipt. Composes with the
        book-level POSTURE cap (auto never exceeds it)."""
        try:
            box = self.screen.query_one("#autonomy", Static)
        except Exception:
            return
        posture = (state or {}).get("posture") or {}
        cap = _num(posture.get("cap"))
        # one compact line for the chrome band: Autonomy  manual · propose · auto≤Xx   <hint>
        line = Text("Autonomy ", style="bold #8C8C92")
        labels = [("manual", "manual"), ("propose", "propose"),
                  ("auto", f"auto{f'≤{cap:g}x' if cap is not None else ''}")]
        for i, (mode, label) in enumerate(labels):
            on = (self._autonomy == mode)
            line.append("  " if i else " ", style=DIM)
            if i:
                line.append("· ", style=BORDER)
            style = Style.parse(f"bold {GOLD}" if on else DIM) + Style(meta={"@click": f"app.autonomy('{mode}')"})
            line.append(("▸" if on else "") + label, style=style)
        hint = {"manual": "you drive every run",
                "propose": "agents propose, you approve",
                "auto": "alerts fire · trims & exits proposed"}.get(self._autonomy, "")
        line.append(f"    {hint}", style=DIM)
        box.update(line)

    def _cand_identity(self, ticker: str) -> str:
        """A short 'Name · commodity' for a candidate ticker, from the discovery universe — so a
        bench-add prompt shows WHAT a bare symbol is (e.g. COP-UN.TO → Sprott Physical Copper Trust ·
        copper) instead of a mysterious ticker that reads like a typo. Cached ~60s; '' if unknown."""
        tk = (ticker or "").strip().upper()
        if not tk:
            return ""
        if self._uni_ident is None or (time.time() - self._uni_ident_ts) > 60:
            ident = {}
            try:
                import json as _j
                p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                 "candidate_universe.json")
                with open(p) as f:
                    for c in (_j.load(f).get("candidates") or []):
                        t = str(c.get("ticker", "")).upper()
                        if t:
                            bits = [b for b in (str(c.get("name", "") or ""),
                                                str(c.get("commodity", "") or "")) if b]
                            ident[t] = " · ".join(bits)
            except Exception:
                pass
            self._uni_ident = ident
            self._uni_ident_ts = time.time()
        return self._uni_ident.get(tk, "")

    def _render_proposals(self, state) -> None:
        """Human-gated AGENT PROPOSALS with inline ✓ approve / ✗ reject / ? why — one-click clearing
        that posts a receipt (reuses _do_confirm / _do_reject). The dial sets the default posture."""
        try:
            box = self.screen.query_one("#proposals", Static)
        except Exception:
            return
        n_prop = len(self._pending or []) + len(self._job_proposals or []) + len(self._watch_proposals or [])
        ph = Text("⚑ ", style=AMBER)
        ph.append("PROPOSALS", style="bold #8C8C92")
        ph.append(f"  {n_prop}", style=f"bold {GOLD}")
        ph.append("   awaiting your approval — the autonomy boundary", style=DIM)
        parts = [ph]
        for p in (self._pending or [])[:4]:                # engine param-change proposals
            pid = p.get("id")
            pl = Text(f"#{pid} ", style=AMBER)
            pl.append(f"{p.get('key')}=", style=SILVER)
            pl.append(f"{p.get('value')}", style=GOLD)
            pl.append(f"  by {p.get('proposed_by','agent')}", style=DIM)
            parts.append(pl)
            parts.append(Text(f"   {str(p.get('reason',''))[:54]}", style=DIM))
            row = Text("   ")
            row.append(" ✓ approve ",
                       style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.confirm_prop('{pid}')"}))
            row.append(" ")
            row.append(" ✗ reject ",
                       style=Style.parse(f"{RED} on #141418") + Style(meta={"@click": f"app.reject_prop('{pid}')"}))
            row.append(" ")
            row.append(" ? why ",
                       style=Style.parse(f"{TEAL} on #141418") + Style(meta={"@click": f"app.prop_why('{pid}')"}))
            parts.append(row)
        for p in (self._job_proposals or [])[:4]:          # due recurring jobs awaiting a human ✓
            jid = p.get("job_id")
            jl = Text("⏱ ", style=AMBER)
            jl.append(f"{str(p.get('kind','job'))} ", style=TEAL)
            jl.append(str(p.get("label", ""))[:28], style=SILVER)
            parts.append(jl)
            row = Text("   ")
            row.append(" ✓ run ",
                       style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.job_run('{jid}')"}))
            row.append(" ")
            row.append(" ✕ skip ",
                       style=Style.parse(f"{DIM} on #141418") + Style(meta={"@click": f"app.job_skip('{jid}')"}))
            parts.append(row)
        for p in (self._watch_proposals or [])[:6]:             # watchlist additions awaiting ✓
            tk = p.get("ticker", "?")
            wl = Text("◇ ", style=TEAL)
            wl.append(f"{tk}", style=f"bold {SILVER}")
            _idw = self._cand_identity(tk)             # WHAT the ticker is (name · commodity)
            if _idw:
                wl.append(f"  {_idw}", style=SILVER)
            wl.append(f"  → bench", style=DIM)
            src = p.get("source") or p.get("note") or ""
            if src and not _idw:
                wl.append(f"  {str(src)[:28]}", style=DIM)
            parts.append(wl)
            row = Text("   ")
            row.append(" ✓ add ",
                       style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.watch_approve('{tk}')"}))
            row.append(" ")
            row.append(" ✗ skip ",
                       style=Style.parse(f"{RED} on #141418") + Style(meta={"@click": f"app.watch_deny('{tk}')"}))
            parts.append(row)
        if not self._pending and not self._job_proposals and not self._watch_proposals:
            parts.append(Text("   none pending — alerts fire on their own; trims & exits land here", style=DIM))
        box.update(Group(*parts))

    # ---- recurring agent work (the scheduler): dial-gated jobs that improve the terminal ----------
    def _jobs_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cockpit_jobs.json")

    def _drafts_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agent_drafts")

    def _load_jobs(self) -> list:
        if self._jobs is None:
            try:
                import cockpit_scheduler as sched
                self._jobs = sched.load_jobs(self._jobs_path())
            except Exception:
                self._jobs = []
        return self._jobs

    def _save_jobs(self, jobs=None) -> None:
        try:
            import cockpit_scheduler as sched
            sched.save_jobs(self._jobs_path(), jobs if jobs is not None else (self._jobs or []))
        except Exception:
            pass

    def _scheduler_tick(self) -> None:
        """Fire due recurring jobs, gated by the autonomy dial: manual skips (paused); propose queues
        a one-click ✓-able job-run proposal; auto runs headless + posts a receipt. Cheap (60 s)."""
        try:
            import cockpit_scheduler as sched
        except Exception:
            return
        jobs = self._load_jobs()
        due = sched.due_jobs(jobs)
        if not due:
            return
        mode = sched.decide(self._autonomy)
        if mode == "skip":
            return                                  # manual — paused; jobs stay due until the dial moves
        changed = False
        for job in due:
            if mode == "propose":
                if not any(p.get("job_id") == job["id"] for p in self._job_proposals):
                    self._job_proposals.append({"job_id": job["id"], "label": job.get("label", ""),
                                                "kind": job.get("kind", "job")})
                    self._receipt(f"job due: {job.get('label','')[:22]}", "⏱", AMBER)
                sched.snooze(job, job.get("every_min", 1440))   # one proposal at a time; re-due next cadence
                changed = True
            elif mode == "run":
                self._launch_job(job)
                sched.mark_ran(job)
                changed = True
        if changed:
            self._save_jobs(jobs)
            try:
                self._render_proposals(self._state or {})
            except Exception:
                pass

    def _job_argv(self, prompt: str):
        """Headless launch for a scheduled job. Configurable: CEX_JOB_CMD (else CEX_PIPELINE_CMD,
        else 'claude -p {prompt}'). The CLI's own permission flags govern how much the agent may do —
        the cockpit itself never commits/pushes; jobs emit review artifacts."""
        import shlex
        tmpl = os.environ.get("CEX_JOB_CMD") or os.environ.get("CEX_PIPELINE_CMD", "claude -p {prompt}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            parts = [prompt if p == "{prompt}" else p for p in parts]
        else:
            parts = parts + [prompt]
        # background recurring work defaults CHEAP (sonnet @ medium) — override per env
        return self._inject_model_flags(parts, tmpl,
                                        os.environ.get("CEX_JOB_MODEL", "sonnet"),
                                        os.environ.get("CEX_JOB_EFFORT", "medium"))

    def _launch_job(self, job: dict) -> None:
        import cockpit_scheduler as sched
        prompt = sched.prompt_for(job)
        agent = job.get("agent")
        if agent and agent != "antigravity":               # a Claude subagent does the task
            prompt = f"@{agent} {prompt}"
        jid = self._inflight_add(agent or job.get("kind", "job"), job.get("label", ""), "")  # visible + cancellable
        self._launch_job_bg(job, prompt, jid)

    @work(thread=True, group="job")
    def _launch_job_bg(self, job: dict, prompt: str, jid: int) -> None:
        agent = job.get("agent")
        _post("/agent/activity", {"agent": agent or "scheduler", "kind": "prompt", "summary": f"⏱ {job.get('label','job')}"})
        self.call_from_thread(self._status, Text(f"⏱ scheduled job: {job.get('label','')}", style=TEAL))
        # build/implement jobs are review-only — the safety line is enforced in BOTH the prompt and the runner
        guard = ("\n\nIMPORTANT: produce a REVIEW ARTIFACT only (markdown). Do NOT edit tracked files, "
                 "commit, or push." if job.get("kind") == "build" else "")
        # an antigravity-assigned task runs through the agy CLI; everything else through CEX_JOB_CMD
        argv = self._agy_argv(prompt) if agent == "antigravity" else self._job_argv(prompt + guard)
        try:
            out = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_JOB_TIMEOUT", "900")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            result = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text("job: CLI not found — set CEX_JOB_CMD", style=ORANGE)); return
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text(f"job timed out: {job.get('label','')}", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text(f"job failed: {exc}", style=ORANGE)); return
        self.call_from_thread(self._inflight_done, jid)
        result = result or "(no output — check CEX_JOB_CMD permission flags)"
        path = self._save_job_artifact(job, prompt, result)
        _post("/agent/activity", {"agent": "scheduler", "kind": "note",
            "summary": f"{job.get('label','job')} → {os.path.basename(path) if path else 'done'} ({len(result)}c)"})
        mem = self._memory()                            # a short, recallable outcome (full text = the artifact)
        if mem is not None:
            try:
                mem.write("note", text=f"[scheduled {job.get('kind')}] {job.get('label','')}: {result[:180]}",
                          ticker=None, regime=self._regime_ctx(), source="scheduler")
            except Exception:
                pass
        self.call_from_thread(self._receipt, f"ran {job.get('label','')[:20]}", "⏱", GREEN,
                              (lambda p=path: self._undo_file(p)) if path else None)
        # surface the finished job on the Hub's Done board (readable — opens the saved review draft)
        self.call_from_thread(self._record_done_run, (agent or job.get("kind", "job")),
                              job.get("label", ""), (result[:80] if result else "review draft"), "result", path)
        self.call_from_thread(self._status, Text(f"✓ job done: {job.get('label','')} → review draft", style=GREEN))

    def _save_job_artifact(self, job: dict, prompt: str, result: str):
        """Persist a job's output as a REVIEW DRAFT under data/agent_drafts/ (never applied/committed)."""
        import datetime
        try:
            d = self._drafts_dir()
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(job.get("label", "job")))[:24] or "job"
            path = os.path.join(d, f"{job.get('kind','job')}_{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Scheduled {job.get('kind')} — {job.get('label','')}\n\n"
                        f"_{datetime.datetime.now():%Y-%m-%d %H:%M} · review draft (not applied / not committed)_\n\n"
                        f"**Prompt:** {prompt}\n\n---\n\n{result}\n")
            return path
        except Exception:
            return None

    def action_job_run(self, job_id: str) -> None:
        """Approve a due job proposal → run it now (the propose-mode human ✓)."""
        self._job_proposals = [p for p in self._job_proposals if p.get("job_id") != job_id]
        jobs = self._load_jobs()
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job:
            import cockpit_scheduler as sched
            self._launch_job(job); sched.mark_ran(job); self._save_jobs(jobs)
        self._render_proposals(self._state or {})

    def action_job_skip(self, job_id: str) -> None:
        self._job_proposals = [p for p in self._job_proposals if p.get("job_id") != job_id]
        self._toast("job run skipped (re-proposes next cadence)", DIM)
        self._render_proposals(self._state or {})

    def action_job_run_now(self, job_id: str) -> None:
        jobs = self._load_jobs()
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job:
            import cockpit_scheduler as sched
            self._launch_job(job); sched.mark_ran(job); self._save_jobs(jobs)
            self._toast(f"running {job.get('label','')}", TEAL)
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def action_job_toggle(self, job_id: str) -> None:
        for j in self._load_jobs():
            if j.get("id") == job_id:
                j["enabled"] = not j.get("enabled")
        self._save_jobs()
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def action_job_del(self, job_id: str) -> None:
        self._jobs = [j for j in self._load_jobs() if j.get("id") != job_id]
        self._job_proposals = [p for p in self._job_proposals if p.get("job_id") != job_id]
        self._save_jobs(self._jobs)
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def _add_job(self, kind: str, topic: str, every_min=None, agent=None):
        import cockpit_scheduler as sched
        jobs = self._load_jobs()
        job = sched.new_job(kind, topic, every_min=every_min, agent=agent)
        jobs.append(job)
        self._jobs = jobs
        self._save_jobs(jobs)
        who = f" · {agent}" if agent else ""
        self._toast(f"scheduled {job['label']}{who} · every {job['every_min']}m (dial: {self._autonomy})", GREEN)
        return job

    def _agent_names(self) -> set:
        return {n for n, _ in self._agent_roster()} | {"antigravity"}

    def _hub_add_job(self, spec: str) -> None:
        """Parse a job spec from the Hub input. Forms (all optional bits):
          job <kind> <topic…> [by <agent>] [@minutes]     — a templated job, optionally assigned
          job <agent> <topic…> [@minutes]                 — assign a specific agent a task
        e.g. `job scout silver juniors @1440`, `job bear AGA.V dilution`, `job audit thresholds by data-integrity-auditor`."""
        import cockpit_scheduler as sched
        spec = (spec or "").strip().lstrip(":").strip()
        if not spec:
            self._toast("format: job <kind|agent> <topic> [by <agent>] [@min]  · kinds: " + " ".join(sched.JOB_KINDS), ORANGE)
            return
        parts = spec.split()
        every = agent = None
        if parts and parts[-1].startswith("@"):
            try:
                every = int(parts[-1][1:]); parts = parts[:-1]
            except ValueError:
                pass
        agents = self._agent_names()
        if len(parts) >= 2 and parts[-2].lower() == "by" and parts[-1].lower() in agents:
            agent = parts[-1].lower(); parts = parts[:-2]
        # first token: a kind (templated) wins; else if it's an agent name, assign it a generic task
        if parts and parts[0].lower() in sched.JOB_KINDS:
            kind = parts[0].lower(); topic = " ".join(parts[1:])
        elif parts and parts[0].lower() in agents:
            agent = agent or parts[0].lower(); kind = "ask"; topic = " ".join(parts[1:])
        else:
            kind = sched.DEFAULT_KIND; topic = " ".join(parts)
        self._add_job(kind, topic, every_min=every, agent=agent)

    def action_hub_assign(self, agent: str) -> None:
        """Pre-fill the Hub input to schedule a task for a specific agent — pick the agent, edit the
        task, Enter to schedule it (the autonomy dial then governs run vs propose)."""
        tk = self._focus or "<topic>"
        try:
            box = self.screen.query_one("#hub_input", Input)   # the input lives in the open Hub
            box.value = f"job ask {tk} by {agent} @1440"
            box.cursor_position = len(box.value)
            self.screen.set_focus(box)
        except Exception:
            pass
        self._toast(f"assign {agent}: edit the task, then Enter to schedule it", TEAL)

    # ---- the Review room: one reader for memory · results · research · threads -----------------
    _MEM_GLYPH = {"note": "✎", "council_verdict": "⚖", "thesis": "◆", "scenario_prior": "⊹",
                  "outcome": "✓", "regime_snapshot": "◷", "decision": "▸", "catalyst": "⛏", "thread": "↯"}

    def action_open_hub(self, tk: str = "", cat: str = "") -> None:
        """Open the Agent Hub. Bare `h`/`v`/palette → THE BLEND (Quest Log home). Calls that carry
        an explicit ticker or board category (the reader flows — 'review ›' on memory, a done-run
        open) land on the classic mission-control reader, so nothing is uprooted."""
        if tk or cat:
            self.action_open_hub_classic(tk, cat or "archive")
            return
        try:
            self.push_screen(BlendHubScreen())
        except Exception:
            pass

    def action_open_hub_classic(self, tk: str = "", cat: str = "archive") -> None:
        """The previous-generation mission-control Hub (TEAM · WORK · FOCUS reader) — still one
        click away from the Blend's footer, so every classic feature stays reachable."""
        try:
            self.push_screen(HubScreen(tk or None, cat=cat))
        except Exception:
            pass

    def action_open_hub_ctx(self) -> None:
        """Open Hub — called from the compact spine strip's 'open Hub' link."""
        self.action_open_hub()

    # back-compat aliases — every old caller (palette, memory rail, agent-hub) lands on the one Hub
    def action_open_review(self, tk: str = "") -> None:
        self.action_open_hub(tk)

    def action_agent_hub(self) -> None:
        self.action_open_hub()

    def _refresh_hub(self) -> None:
        """Keep the open hub fresh while it's up (called on the 3 s poll + on actions) — the classic
        Hub's live cards, or the Blend home / focus surfaces. The reader board only re-pulls on user
        navigation, so a poll never disrupts your reading."""
        scr = self.screen
        try:
            if isinstance(scr, HubScreen):
                scr.refresh_cards()
            elif isinstance(scr, BlendHubScreen):
                scr.paint_all()
            elif isinstance(scr, BlendSurface):
                scr.paint()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════════════
    #  THE BLEND — app-side data + actions. Every hotkey here mirrors a clickable
    #  affordance painted by the screens above (the interaction-matrix contract).
    # ══════════════════════════════════════════════════════════════════════════════════
    def _blend_subject(self) -> str:
        """The DEFAULT launch subject — the desk's focused name. There is no separate sticky
        'target': subject-at-fire means every launch confirms/edits this default in its setup
        before it runs, so the hub and the desk never disagree on 'the current name'."""
        return self._focus or next(iter(self._baskets_by_ticker or {}), "AGA.V")

    def _pipe_is_live(self, pipe=None) -> bool:
        """Is the engine pipeline running AND not dismissed from the Working lane? (A genuinely new
        run carries a fresh 'started' ts, so dismissing a stale one never hides a real one.)"""
        pipe = pipe if pipe is not None else (self._state or {}).get("pipeline") or {}
        return pipe.get("status") == "running" and pipe.get("started") != self._pipe_dismissed

    def _pipe_is_echo(self, pipe=None) -> bool:
        """Is the engine 'pipeline' row just the LOCAL chain's own event-bus echo? The workflow
        runner posts its stage events with theme=subject, and the engine reports them back as a
        running pipeline — without this guard the SAME run shows twice (a chain row + a pipeline
        row). A genuinely independent engine pipeline carries a different theme and still shows."""
        pipe = pipe if pipe is not None else (self._state or {}).get("pipeline") or {}
        return bool(self._wf_running and self._wf_subject
                    and str(pipe.get("theme", "")) == str(self._wf_subject))

    def _blend_workflows(self) -> dict:
        """Launch buttons: the operator's saved chains, with the canonical seeds filling any gap
        (seeds are views, not writes — saving your own chain under the same name shadows the seed)."""
        out = dict(BLEND_SEED_WORKFLOWS)
        out.update(self._load_workflows() or {})
        return out

    def _blend_log_items(self, flt: str = "all") -> list:
        """The QUEST LOG feed — working runs, proposals (flagged), threads, done runs, and recent
        Living-Memory events as ONE stream, newest first. Each item knows which surface it opens."""
        e = self._esc
        items: list = []
        now = time.time()
        # Every item carries: uid (stable — drives ▸/▾ expansion), full (the UN-truncated text
        # shown wrapped when expanded), detail ([(label, value)] meta lines for the expansion).
        # ── working (pinned at top; the 'working' filter shows only these) ──
        if self._wf_running:
            total = max(1, len(self._workflow or []))
            idx = int(getattr(self, "_wf_stage_idx", 0))
            items.append({"kind": "dossier", "status": "running", "opens": "pipeline", "uid": "run:chain",
                          "title": f"chain · {self._wf_subject or self._blend_subject()}",
                          "summary": f"stage {min(idx + 1, total)}/{total} · "
                                     + " → ".join(self._wf_stage_label(s) for s in (self._workflow or [])[:4]),
                          "full": "\n".join(f"{si + 1}. {self._wf_stage_label(s)} — {s.get('note', '')}"
                                            for si, s in enumerate(self._workflow or [])),
                          "detail": [("stage", f"{min(idx + 1, total)}/{total}"),
                                     ("paused", "yes" if self._wf_ctl.get("pause") else "no")],
                          "ticker": "", "party": [], "ts": now})
        pipe = (self._state or {}).get("pipeline") or {}
        if self._pipe_is_live(pipe) and not self._pipe_is_echo(pipe):
            items.append({"kind": "dossier", "status": "running", "opens": "pipeline", "uid": "run:pipe",
                          "title": f"pipeline · {pipe.get('theme', '')}",
                          "summary": str(pipe.get("stage", "")),
                          "full": "\n".join(f"{ev.get('stage', '')}: {ev.get('message', '')}"
                                            for ev in (pipe.get("events") or [])[-6:]),
                          "detail": [("theme", str(pipe.get("theme", ""))), ("stage", str(pipe.get("stage", "")))],
                          "ticker": "", "party": [], "ts": now})
        for jid, j in self._inflight.items():
            if j.get("cancelled"):
                continue
            who, task = self._task_label(j)
            prov = j.get("provider") or self._agent_provider(who)
            # H1 heartbeat: a streaming run carries a live line-count + the latest line, so the row
            # reads as ALIVE (and shows the reasoning tail) instead of a static elapsed spinner.
            lines_n = int(j.get("lines") or 0)
            detail = [("agent", who), ("model", _run_model_label(who, prov)),
                      ("elapsed", f"{max(0, int(now - j.get('started', now)))}s")]
            if lines_n:
                detail.append(("streamed", f"{lines_n} lines"))
            # while live, the auto-expanded row shows the agent feed itself (the streamed tail),
            # not just the static task line — falls back to the task if nothing has streamed yet.
            node = j.get("node")
            live = (self._stream_buf.get(node) or "").strip() if node else ""
            live_tail = "\n".join(live.splitlines()[-18:]) if live else ""
            items.append({"kind": "ask", "status": "running", "opens": "working", "jid": jid,
                          "uid": f"run:{jid}", "title": _clip(task or f"{who} working", 60),
                          "summary": _clip(str(j.get("tail") or ""), 96),
                          "full": (live_tail or str(task or "")),
                          "detail": detail,
                          "ticker": j.get("ticker") or "", "party": [who],
                          "ts": j.get("started", now)})
        # ── proposals — the flagged lane (inline ✓ / ✗, exactly like the classic feed) ──
        for p in (self._pending or [])[:6]:
            pid = p.get("id", "")
            items.append({"kind": "flag", "status": "flagged", "opens": "detail", "level": "risk",
                          "uid": f"prop:{pid}",
                          "title": _clip(_prop_label(p), 60),
                          "summary": "awaiting your approval",
                          "full": str(p.get("reason") or p.get("text") or p.get("label") or ""),
                          "detail": [("source", str(p.get("source") or "engine")),
                                     ("param", str(p.get("param") or "—"))],
                          "ticker": p.get("ticker") or "",
                          "party": [str(p.get("source") or "engine")], "ts": now,
                          "actions": (f"[@click=app.do_confirm('{pid}')][bold {GREEN} on #141418] ✓ approve [/][/] "
                                      f"[@click=app.do_reject('{pid}')][{DIM} on #141418] ✕ dismiss [/][/]")})
        for p in (self._watch_proposals or [])[:6]:
            tk2 = p.get("ticker", "?")
            _id2 = self._cand_identity(tk2)            # show WHAT the ticker is, not a bare symbol
            items.append({"kind": "flag", "status": "flagged", "opens": "detail", "level": "warn",
                          "uid": f"watch:{tk2}", "title": f"add {tk2}{(' — ' + _id2) if _id2 else ''} to the bench?",
                          "summary": _clip(_id2 or str(p.get("source") or p.get("note") or ""), 60),
                          "full": str(p.get("note") or p.get("source") or ""),
                          "ticker": tk2, "party": ["scout"], "ts": now,
                          "actions": (f"[@click=app.watch_approve('{tk2}')][bold {GREEN} on #141418] ✓ add [/][/] "
                                      f"[@click=app.watch_deny('{tk2}')][{RED} on #141418] ✗ skip [/][/]")})
        # ── threads — each research conversation is a log entry that opens as a Thread ──
        # An in-flight ask is already shown above as its live WORKING row; suppress the matching
        # thread row while its run is live so a brand-new question isn't double-listed (the row
        # reappears, with its reply, the moment the run finishes).
        running_roots = {self._branch_root(j["node"]) for j in self._inflight.values()
                         if j.get("node") and not j.get("cancelled")}
        for root in self._roots():
            rid = root["id"]
            if rid in running_roots:
                continue
            nodes = [n for n in self._conv.values() if self._branch_root(n["id"]) == rid]
            party = list(dict.fromkeys(n.get("agent") for n in nodes
                                       if n.get("role") == "agent" and n.get("agent")))[:4]
            ts = max((n.get("ts", 0) for n in nodes), default=root.get("ts", 0))
            reply = next((n for n in sorted(nodes, key=lambda x: x.get("ts", 0), reverse=True)
                          if n.get("role") == "agent"), None)
            items.append({"kind": "ask", "status": "done", "opens": "thread", "ref": rid,
                          "uid": f"thread:{rid}", "title": _clip(str(root.get("text", "")), 60),
                          # collapsed line = the RESULT (conclusion), not the "I will…" preamble
                          "summary": reply_gist(str(reply.get("text", "")), 110) if reply else "awaiting reply…",
                          "full": str(reply.get("text", "")) if reply else "",
                          "detail": [("turns", str(len(nodes))),
                                     ("last", (reply.get("agent") or "claude") if reply else "—")],
                          "ticker": root.get("ticker") or "", "party": party or ["claude"], "ts": ts})
        # ── done runs — dossiers / matchups land here when a chain finishes ──
        for r in (self._done_runs or []):
            subj = str(r.get("subject", ""))
            matchup = " vs " in subj.lower() or r.get("cat") == "matchup"
            workflow = r.get("agent") in ("workflow", "pipeline") or r.get("cat") in ("result", "research")
            if r.get("cat") == "thread":
                continue                                   # already surfaced as its thread
            items.append({"kind": "matchup" if matchup else "dossier", "status": "done",
                          "opens": "matchup" if matchup else ("pipeline" if workflow else "detail"),
                          "ref": r.get("ref"), "uid": f"done:{r.get('id')}",
                          "title": _clip(subj or str(r.get("agent", "")), 60),
                          "subject": subj,                 # UN-clipped — keys the matchup re-hydrate
                          "summary": str(r.get("summary", "")), "full": str(r.get("summary", "")),
                          "detail": ([("saved", os.path.basename(str(r.get("ref"))))] if r.get("ref") else []),
                          "ticker": "", "party": [str(r.get("agent", "agent"))], "ts": r.get("ts", now)})
        # ── recent Living-Memory events (notes · verdicts · catalysts · sentinel flags) ──
        mem = self._memory()
        if mem is not None:
            try:
                # cap low-signal memory notes so runs/dossiers/flags aren't buried under a wall of
                # them; verdicts/decisions/sentinel flags are higher-signal and shown more freely
                notes_shown = 0
                for ent in mem.query(limit=20):
                    typ = str(ent.get("type", "note"))
                    if typ in ("pin", "thread") or (ent.get("meta") or {}).get("retracted"):
                        continue
                    kind = "flag" if typ.startswith("sentinel") else (
                        "dossier" if typ in ("council_verdict", "decision", "outcome") else "note")
                    if kind == "note":
                        notes_shown += 1
                        if notes_shown > 6:
                            continue
                    reg = ent.get("regime") or {}
                    detail = [("type", typ.replace("_", " ")), ("by", str(ent.get("source") or "—"))]
                    if reg.get("mri") is not None or reg.get("posture"):
                        detail.append(("regime", f"MRI {reg.get('mri', '—')} · {reg.get('posture') or reg.get('net_tilt') or ''}"))
                    if ent.get("tags"):
                        detail.append(("tags", " ".join(f"#{t_}" for t_ in (ent.get("tags") or [])[:5])))
                    # a memory entry's TITLE already carries its text — a "note"/type summary line is
                    # pure repetition, so collapse it to a single line (the full text + type live in
                    # the ▾ expansion). Keep a one-word type only for the higher-signal dossier kinds.
                    summ = (typ.replace("_", " ") if kind == "dossier" else "")
                    items.append({"kind": kind, "status": "flagged" if kind == "flag" else "note",
                                  "opens": "detail", "ref": ent.get("id"), "uid": f"mem:{ent.get('id')}",
                                  "title": _clip(str(ent.get("text", "")), 60),
                                  "summary": summ, "full": str(ent.get("text", "")),
                                  "detail": detail, "ticker": ent.get("ticker") or "",
                                  "party": [str(ent.get("source") or "memory")],
                                  "ts": now - _age_days(ent.get("ts")) * 86400.0})
            except Exception:
                pass
        # ── filter + sort: working pinned first, then newest first ──
        if flt == "working":
            items = [i for i in items if i.get("status") == "running"]
        elif flt == "flagged":
            items = [i for i in items if i.get("kind") == "flag"]
        elif flt == "matchups":
            items = [i for i in items if i.get("kind") == "matchup"]
        items.sort(key=lambda i: (0 if i.get("status") == "running" else 1, -(i.get("ts") or 0)))
        return items

    # ---- Blend actions (all are click targets painted by the screens) ----
    def action_blend_notes_toggle(self) -> None:
        """The header NOTES toggle — show/hide the Blend's amber design-intent note (wireframe)."""
        self._blend_notes = not self._blend_notes
        if isinstance(self.screen, BlendHubScreen):
            self.screen.paint_head()
            self.screen.paint_nav()

    def action_blend_lanes_toggle(self) -> None:
        """The ⫴ lanes toggle (g) — Quest Log as three vertical lanes (RUN · FLAG · NOTE) vs one
        single stream. Per-surface (each keeps its own default): the full-width QUEST LOG tab
        toggles independently of the narrow Blend-home center."""
        scr = self.screen
        if isinstance(scr, BlendHubScreen):
            self._blend_lanes = not self._blend_lanes
            scr.paint_log()
        elif isinstance(scr, QuestLogSurface):
            self._blend_lanes_quest = not self._blend_lanes_quest
            scr.paint()

    def action_blend_filter(self, f: str) -> None:
        # the feed lives on BOTH the Blend home and the focused QUEST LOG surface
        if isinstance(self.screen, (BlendHubScreen, QuestLogSurface)):
            self.screen.set_filter(str(f))

    def action_blend_expand(self, ref) -> None:
        """▸/▾ on a Quest-Log row — unfold the full, untruncated event in place (space mirrors). ``ref``
        is the row's stable uid (a keyboard _sel index also resolves)."""
        if isinstance(self.screen, (BlendHubScreen, QuestLogSurface)):
            self.screen.toggle_expand(ref)

    def action_blend_complete(self, text: str) -> None:
        """A clicked (or tab'd) command-bar suggestion — fill the bar, keep typing."""
        scr = self.screen
        if not isinstance(scr, BlendHubScreen):
            return
        try:
            bar = scr.query_one("#blend_cmd", Input)
            bar.set_class(True, "open")
            bar.value = str(text)
            bar.cursor_position = len(bar.value)
            bar.focus()
        except Exception:
            pass

    def action_blend_clear_lane(self) -> None:
        """Clear the WHOLE Working lane — cancel every in-flight run (terminating its child process),
        stop & reset a running chain, and dismiss a stale engine-pipeline row. Force-clears even an
        orphaned/stuck row that has no live worker to cancel (the lane's '⏹ clear all' button)."""
        n = 0
        for jid in list(self._inflight):
            j = self._inflight.get(jid)
            if j and not j.get("cancelled"):
                self.action_cancel_job(jid)
                n += 1
        if self._wf_running:
            self._wf_ctl = {"pause": False, "stop": True}   # any live worker exits at the next boundary
            self._wf_running = False                        # …and the view clears now, orphan or not
            n += 1
        pipe = (self._state or {}).get("pipeline") or {}
        if self._pipe_is_live(pipe):
            self._pipe_dismissed = pipe.get("started")
            n += 1
        self._toast(f"⏹ cleared the working lane ({n})" if n else "working lane already clear",
                    TEAL if n else DIM)
        self._refresh_hub()

    def action_blend_clear_chain(self) -> None:
        """Clear just the running/stuck chain from the lane (force — orphan-safe)."""
        self._wf_ctl = {"pause": False, "stop": True}
        self._wf_running = False
        self._toast("⏹ chain cleared", ORANGE)
        self._refresh_hub()

    def action_blend_dismiss_pipeline(self) -> None:
        """Dismiss the engine pipeline row from the lane (a genuinely new run re-appears)."""
        pipe = (self._state or {}).get("pipeline") or {}
        self._pipe_dismissed = pipe.get("started")
        self._toast("pipeline dismissed from the lane", DIM)
        self._refresh_hub()

    def action_pipe_subject(self, tk: str) -> None:
        """Set the launch subject on the open Pipeline setup (subject-at-fire — local to the
        surface, confirmed at ▶ LAUNCH; never a sticky global target)."""
        scr = self.screen
        if isinstance(scr, PipelineSurface):
            scr._subject = str(tk)
            scr.paint()

    def action_blend_cmd(self) -> None:
        if isinstance(self.screen, BlendHubScreen):
            self.screen.action_cmd()

    def action_blend_launch(self, name: str) -> None:
        """A Launch-rail chain click — subject-at-fire: open the Pipeline SETUP with this chain
        staged and the subject defaulted to the focused name, editable. Nothing runs until the
        explicit ▶ LAUNCH inside the setup (so a chain never fires on a name you didn't confirm)."""
        if self._wf_running:
            self._toast("a chain is already running — watch it in the Working lane", ORANGE)
            return
        self.action_blend_configure(str(name))

    # ---- the top navigation bar — THE BLEND (all rails) vs a focused feature (1-6) ----
    def action_jobnav(self, verb: str = "") -> None:
        """Three-JOB nav routing (the reframe): jobs up front, mechanisms as drawers — each a
        clickable affordance (the Build Plan's click-floor). Watch returns to the cockpit; Screen
        opens the disconfirmation funnel; Change opens the book-diff review; log / fleet / concierge
        are the demoted mechanism drawers (still also on keys 1-6)."""
        verb = str(verb)
        if verb == "watch":
            try:
                self.pop_screen()                      # close the hub → back to the WATCH cockpit
            except Exception:
                pass
        elif verb == "screen":
            self._screen_chooser()                  # deliberate: pick the sleeve, don't auto-screen focus
        elif verb == "change":
            self._change_chooser((self._focus or "").strip())   # deliberate chooser, never auto-stage
        elif verb == "log":
            self.action_blend_nav("quest")             # the demoted log, now a drawer
        elif verb == "fleet":
            self.action_blend_nav("roster")
        elif verb == "concierge":
            try:
                self.action_concierge_toggle()
            except Exception:
                pass

    def action_blend_nav(self, tab: str) -> None:
        """Switch from the persistent top bar (keys 1-6). 'blend' is the unified hub (all rails);
        the others open ONE focused feature full-screen. The bar switches surfaces, never stacks —
        it pops whatever's open and lands on the chosen tab."""
        tab = str(tab)
        if not isinstance(self.screen, (BlendHubScreen, BlendSurface)):
            return
        while isinstance(self.screen, BlendSurface):        # the bar switches, it never stacks
            self.pop_screen()
        if tab == "blend" or not isinstance(self.screen, BlendHubScreen):
            return                                          # 'blend' = the home itself (already here)
        if tab == "quest":
            self.push_screen(QuestLogSurface())
        elif tab == "pipeline":
            live = self._wf_running or self._pipe_is_live()
            self.push_screen(PipelineSurface(mode="live" if live else "setup",
                                             sub="live" if live else "set up, then ▶ launch"))
        elif tab == "matchup":
            self.action_blend_matchup()
        elif tab == "thread":
            roots = sorted(self._roots(), key=lambda r: r.get("ts", 0), reverse=True)
            if roots:
                self.push_screen(ThreadSurface(roots[0]["id"],
                                               sub=_clip(str(roots[0].get("text", "")), 50)))
            else:
                self._toast("no research threads yet — ask anything from the / command bar", DIM)
        elif tab == "roster":
            self.action_blend_roster()

    def action_blend_configure(self, name: str = "") -> None:
        """⚙ on a Launch row (or the idle Pipeline's 'set up a chain') — open the chain in the
        Pipeline SETUP view to stage parameters first. Nothing runs until ▶ LAUNCH."""
        try:
            self.push_screen(PipelineSurface(mode="setup", chain_name=str(name or ""),
                                             sub="set up, then ▶ launch"))
        except Exception:
            pass

    def action_pipe_setup(self) -> None:
        scr = self.screen
        if isinstance(scr, PipelineSurface):
            scr._mode = "setup"
            if not scr._chain_name and not self._workflow:
                scr._chain_name = "deep dossier"
                self._workflow = [dict(s) for s in BLEND_SEED_WORKFLOWS["deep dossier"]]
            scr.paint()

    def action_pipe_chain_pick(self, name: str) -> None:
        """Pick a chain recipe in the setup view — loads an editable copy, replacing the stage."""
        steps = self._blend_workflows().get(str(name))
        if not steps:
            return
        self._workflow = [dict(s) for s in steps]
        scr = self.screen
        if isinstance(scr, PipelineSurface):
            scr._chain_name = str(name)
            scr._sel = -1
            scr.paint()

    def action_pipe_stage_del(self, idx) -> None:
        """✕ on a staged stage — re-wire before launch."""
        try:
            self._workflow.pop(int(idx))
        except Exception:
            return
        scr = self.screen
        if isinstance(scr, PipelineSurface):
            scr._sel = -1
            scr.paint()

    def action_blend_launch_current(self) -> None:
        """▶ LAUNCH from the Pipeline setup — fire the STAGED chain on the surface's CONFIRMED
        subject (the explicit moment of execution; everything before this was just setup)."""
        if self._wf_running:
            self._toast("a chain is already running — watch it in the Working lane", ORANGE)
            return
        steps = [dict(s) for s in (self._workflow or [])]
        if not steps:
            self._toast("stage a chain first — pick a recipe or + add stage", ORANGE)
            return
        scr = self.screen
        subject = (getattr(scr, "_subject", "") if isinstance(scr, PipelineSurface) else "") or self._blend_subject()
        self._wf_subject = subject                          # stable for the lane/log while it runs
        self._last_wf_steps = [dict(s) for s in steps]
        self._wf_ctl = {"pause": False, "stop": False}
        self._wf_stage_idx = 0
        self._wf_running = True
        self._toast(f"▶ chain launched on {subject} — {len(steps)} stages", GREEN)
        self._run_workflow_bg(steps, subject)
        if isinstance(scr, PipelineSurface):                # the setup view flips to live in place
            scr._mode = "live"
            scr._sel = -1
            scr.paint()
        self._refresh_hub()

    def action_blend_matchup(self, chal: str = "") -> None:
        try:
            self.push_screen(MatchupSurface(hold=self._blend_subject(), chal=str(chal or "")))
        except Exception:
            pass

    def action_blend_roster(self) -> None:
        try:
            self.push_screen(RosterSurface())
        except Exception:
            pass

    def _blend_item_by_ref(self, scr, ref):
        """Resolve a clicked/selected Quest-Log row to its item by STABLE uid — NOT by positional index.
        The feed is rebuilt and re-sorted on a 1s timer, so an index bound at render time can resolve to
        the wrong (newest) row by dispatch; the uid is stable across rebuilds. Accepts a uid string
        (clicks) or a bare int index (keyboard nav, read in-tick so it can't race). None if unresolved."""
        items = getattr(scr, "_items", None) or []
        s = str(ref)
        for it in items:
            if str(it.get("uid")) == s:
                return it
        try:                                               # back-compat: a bare int index (keyboard _sel)
            i = int(ref)
        except (TypeError, ValueError):
            return None
        return items[i] if 0 <= i < len(items) else None

    def action_blend_open(self, ref) -> None:
        """A Quest-Log row's click → open its matching surface (works from the Blend home AND the
        focused QUEST LOG surface; the new surface stacks, esc returns to the feed). ``ref`` is the
        row's stable uid (a keyboard _sel index also resolves)."""
        scr = self.screen
        if not isinstance(scr, (BlendHubScreen, QuestLogSurface)):
            return
        it = self._blend_item_by_ref(scr, ref)
        if it is None:
            return
        opens = it.get("opens", "detail")
        if opens == "thread" and it.get("ref"):
            self.push_screen(ThreadSurface(it["ref"], sub=_clip(str(it.get("title", "")), 60)))
        elif opens == "pipeline":
            mode = "done" if (it.get("status") == "done" and it.get("ref")) else "live"
            self.push_screen(PipelineSurface(mode=mode, ref=it.get("ref"),
                                             sub=_clip(str(it.get("title", "")), 60)))
        elif opens == "matchup":
            pair = str(it.get("subject") or it.get("title", ""))   # un-clipped subject keys the grid
            hold, _, chal = pair.partition(" vs ")
            self._rehydrate_matchup(pair, it.get("ref"))           # scores survive a TUI restart
            self.push_screen(MatchupSurface(hold=hold.strip() or self._blend_subject(),
                                            chal=chal.strip(), verdict=str(it.get("summary", "")),
                                            sub=pair))
        elif opens == "working" and it.get("jid") is not None:
            self.action_blend_monitor(it["jid"])
        else:
            self._blend_read_detail(it)

    def _blend_read_detail(self, it: dict) -> None:
        """Open a note / memory / file entry full-screen in the universal inspector."""
        ref = it.get("ref")
        md, _acts = self._review_detail({"cat": "archive", "ref": ref}) if ref else (
            f"[{SILVER}]{self._esc(str(it.get('title', '')))}[/]", "")
        self.push_screen(InspectScreen(str(it.get("title", ""))[:60], md))

    def action_blend_read(self, ref: str) -> None:
        """'❖ read the dossier' from a done Pipeline — the saved package, readable in place."""
        md, _acts = self._review_detail({"cat": "archive", "ref": ref})
        self.push_screen(InspectScreen("DOSSIER", md))

    def action_blend_open_pipeline(self) -> None:
        try:
            self.push_screen(PipelineSurface(mode="live", sub=f"{self._blend_subject()} · live"))
        except Exception:
            pass

    def action_blend_monitor(self, jid) -> None:
        """Watch one in-flight run: its thread (asks land in a thread) or the live task detail."""
        j = self._inflight.get(int(jid))
        if not j:
            return
        if self._wf_running:
            self.action_blend_open_pipeline()
            return
        # resolve THIS job's OWN thread from its conversation node — never the global _pending_user,
        # which always points at the most-recent ask, so clicking any lane row opened the newest log.
        node = j.get("node")
        root = self._branch_root(node) if node else None
        if root:
            self.push_screen(ThreadSurface(root, sub="live — the reply lands here"))
        else:
            md, _ = self._task_inspector_markup(int(jid))
            self.push_screen(InspectScreen("WORKING", md))

    def action_surface_close(self) -> None:
        if isinstance(self.screen, (BlendSurface,)):
            self.pop_screen()

    # ---- Pipeline controls (⏸ / + / ⏹ — buttons with key mirrors) ----
    def action_wf_pause(self) -> None:
        """Pause/resume the running chain at the next stage boundary (the runner can't stop a
        seat mid-thought — honest pause, not a fake freeze)."""
        if not self._wf_running:
            self._toast("no chain running", ORANGE)
            return
        self._wf_ctl["pause"] = not self._wf_ctl.get("pause")
        self._toast("⏸ pausing at the stage boundary" if self._wf_ctl["pause"] else "▶ resumed",
                    AMBER if self._wf_ctl["pause"] else GREEN)
        self._refresh_hub()

    def action_wf_stop(self) -> None:
        """Stop the chain: no further stages launch; the stages already run are still packaged."""
        if not self._wf_running:
            self._toast("no chain running", ORANGE)
            return
        self._wf_ctl["stop"] = True
        self._wf_ctl["pause"] = False
        self._toast("⏹ stopping — finishing the current stage, then packaging what exists", ORANGE)
        self._refresh_hub()

    def action_wf_addstage(self) -> None:
        """+ add stage — re-wire mid-flight: pick the agent from the Roster drawer."""
        try:
            self.push_screen(RosterSurface(mode="chain"))
        except Exception:
            pass

    def action_pipe_sel(self, idx) -> None:
        scr = self.screen
        if isinstance(scr, PipelineSurface):
            scr._sel = int(idx)
            scr.paint()

    def _load_workflow_chain(self, path) -> list:
        """Recover a finished package's chain shape from its saved markdown (## Stage n · a ∥ b),
        so a done Pipeline re-renders its true topology. Falls back to the last-run steps."""
        try:
            stages = []
            with open(str(path), encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"^## Stage \d+ · (.+)$", line.strip())
                    if m:
                        stages.append({"agents": [a.strip() for a in m.group(1).split("∥")], "note": ""})
            if stages:
                return stages
        except Exception:
            pass
        return [dict(s) for s in (self._last_wf_steps or [])]

    # ---- Matchup (the 1v1 verb) ----
    def action_matchup_lens(self, lens: str) -> None:
        scr = self.screen
        if isinstance(scr, MatchupSurface):
            scr._lenses.symmetric_difference_update({str(lens)})
            scr.paint()

    def action_matchup_change(self) -> None:
        scr = self.screen
        if isinstance(scr, MatchupSurface):
            try:
                scr.query_one("#mu_chal", Input).focus()
            except Exception:
                pass

    def action_matchup_open_verdict(self, ref: str = "") -> None:
        """Open the full matchup verdict — the saved package, or the in-memory text."""
        if ref and os.path.exists(str(ref)):
            md, _ = self._review_detail({"cat": "archive", "ref": ref})
            self.push_screen(InspectScreen("MATCHUP VERDICT", md))
            return
        scr = self.screen
        if isinstance(scr, MatchupSurface):
            res = self._matchup_results.get(f"{scr._hold or self._blend_subject()} vs {', '.join(scr._chals)}") or {}
            txt = res.get("verdict") or scr._verdict or "(no verdict captured)"
            self.push_screen(InspectScreen("MATCHUP VERDICT", f"[{SILVER}]{self._esc(str(txt))}[/]"))

    def action_matchup_hold(self, tk: str) -> None:
        """Pick the HOLDING side (subject-at-fire — defaults to focus, changeable before ▶ run)."""
        scr = self.screen
        if isinstance(scr, MatchupSurface):
            scr._hold = str(tk)
            scr._chals = [c for c in scr._chals if c != str(tk)]   # can't bench the holding
            scr.paint()

    def action_matchup_remove(self, idx) -> None:
        """✕ a challenger off the bench."""
        scr = self.screen
        if isinstance(scr, MatchupSurface):
            try:
                scr._chals.pop(int(idx))
            except Exception:
                return
            scr.paint()

    def action_matchup_run(self) -> None:
        """Fire the bench: the same agents score the holding against EVERY outsider, the arbiter
        ranks them, and the verdict (winner + caveat) drops into the Quest Log as a MATCHUP entry.
        A single challenger is just the 1v1 special case."""
        scr = self.screen
        if not isinstance(scr, MatchupSurface) or not scr._chals:
            self._toast("add at least one outsider to the bench first", ORANGE)
            return
        if self._wf_running:
            self._toast("a chain is already running — let it land first", ORANGE)
            return
        hold = scr._hold or self._blend_subject()
        chals = list(scr._chals)
        bench = ", ".join(chals)
        lenses = ", ".join(sorted(scr._lenses)) or "Value, Balance sheet"
        if len(chals) == 1:
            head = f"1v1 MATCHUP — {hold} (the holding) vs {chals[0]} (the outsider)."
            reconcile = (f"Reconcile into ONE matchup verdict for {hold} vs {chals[0]}: the winner "
                         f"per metric and overall — HOLD or SWAP — with the invalidation caveat.")
        else:
            head = (f"N-WAY MATCHUP BENCH — {hold} (the holding) vs the bench [{bench}]. Score EVERY "
                    f"contender on the same metrics.")
            reconcile = (f"Rank the whole bench for {hold} vs [{bench}]: the winner per metric and "
                         f"the overall ranking — HOLD {hold}, or SWAP to which challenger and why — "
                         f"with the invalidation caveat. Slot-fit gates any SWAP first.")
        all_tickers = " ".join([hold] + chals)
        scores_fmt = (
            f"\n\nAFTER your analysis, emit a machine-readable SCORES block — ONE line per contender "
            f"({all_tickers}), in EXACTLY this format so the comparison grid can parse it:\n"
            f"SCORE <TICKER> | conviction=<0-10> | upside=<±N%> | rho=<N.N> | phi=<N.N> | price=<$N.NN>\n"
            f"Use your best grounded estimate for each outsider (the holding's engine numbers are "
            f"already shown); write '—' for any field genuinely unknowable. Emit the block for ALL "
            f"contenders, the holding included, so the grid is complete.")
        steps = [
            {"agents": ["value-analyst", "balance-sheet-analyst"],
             "note": (f"{head} Score ALL of them on the {lenses} lens(es): conviction, fair-value "
                      f"range, runway, ρ/φ asymmetry, EV per resource unit. Slot-fit first; numbers "
                      f"grounded.{scores_fmt}")},
            {"agents": ["arbiter"], "note": reconcile + scores_fmt},
        ]
        self._workflow = [dict(s) for s in steps]
        self._last_wf_steps = [dict(s) for s in steps]
        self._wf_ctl = {"pause": False, "stop": False}
        self._wf_stage_idx = 0
        self._wf_subject = f"{hold} vs {bench}"             # the lane/log/canvas show THIS run's subject
        self._matchup_results.pop(self._wf_subject, None)   # clear any stale grid for this exact bench
        self._wf_running = True
        self._run_workflow_bg([dict(s) for s in steps], f"{hold} vs {bench}")
        self._fetch_fundamentals_bg(chals)                  # ground each outsider's price (off the UI thread)
        self._toast(f"⇄ {'matchup' if len(chals) == 1 else 'bench'} running — {hold} vs {bench} "
                    f"· scores fill the grid when it lands", GREEN)
        scr.paint()

    @work(thread=True, group="fund", exclusive=False)
    def _fetch_fundamentals_bg(self, tickers: list) -> None:
        """Fetch FMP fundamentals for a set of outsiders OFF the UI thread (the per-name _get is
        blocking), then repaint the matchup so prices populate as they arrive."""
        for tk in list(tickers or []):
            self._fetch_fundamentals(tk)
            try:
                self.call_from_thread(self._refresh_hub)
            except Exception:
                pass

    @staticmethod
    def _parse_matchup_scores(text: str) -> dict:
        """Pull the agents' structured SCORE lines out of the run output into {ticker: {metric: val}}
        — the bridge that turns the prose verdict into the filled comparison grid. Tolerant of
        spacing, optional pipes, $/% signs, and '—' for unknowable fields."""
        out: dict = {}
        for m in re.finditer(r"SCORE\s+([A-Za-z0-9.\-]{1,12})\b(.*)", str(text or "")):
            tk = m.group(1).upper()
            rest = m.group(2)
            row = {}
            for key, pat in (("rating", r"conviction\s*[=:]\s*([\d.]+)"),
                             ("upside", r"upside\s*[=:]\s*([+\-]?[\d.]+)"),
                             ("rho", r"(?:rho|ρ)\s*[=:]\s*([\d.]+)"),
                             ("phi", r"(?:phi|φ)\s*[=:]\s*([\d.]+)"),
                             ("price", r"price\s*[=:]\s*\$?\s*([\d.]+)")):
                mm = re.search(pat, rest, re.I)
                if mm:
                    try:
                        row[key] = float(mm.group(1))
                    except ValueError:
                        pass
            if row:
                out[tk] = row
        return out

    def _rehydrate_matchup(self, subject: str, ref) -> None:
        """Re-load a finished bench's scores + verdict from its saved package — _matchup_results
        is in-memory, so without this a TUI restart would blank a grid the agents already filled."""
        subject = str(subject or "")
        if not subject or subject in self._matchup_results:
            return                                          # live results win; nothing to do
        if not ref or not os.path.exists(str(ref)):
            return
        try:
            txt = open(str(ref), encoding="utf-8").read()
        except Exception:
            return
        scores = self._parse_matchup_scores(txt)
        if not scores:
            return                                          # a pre-SCORE-block package — nothing parseable
        m = re.search(r"### arbiter\s*\n+(.+)", txt, re.S)  # the verdict = the arbiter's stage output
        self._matchup_results[subject] = {"scores": scores,
                                          "verdict": (m.group(1).strip() if m else ""), "ref": str(ref)}

    # ---- Thread (linear narrative + switchable branches) ----
    def _thread_trunk_branches(self, root_id: str):
        """(trunk, branches) for a conversation root. The trunk is the shared spine down to the
        first fork; each branch is one continuation walked linearly (newest child at its own forks),
        labelled by its first ask and led by its first agent. No fork → everything is trunk."""
        rid = str(root_id)
        nodes = {n["id"]: n for n in self._conv.values() if self._branch_root(n["id"]) == rid}
        kids: dict = {}
        for n in nodes.values():
            if n.get("parent") in nodes or (n.get("parent") is None and n["id"] == rid):
                kids.setdefault(n.get("parent"), []).append(n["id"])
        for v in kids.values():
            v.sort(key=lambda i: nodes[i].get("ts", 0))
        trunk, cur = [], rid
        while cur in nodes:
            trunk.append(nodes[cur])
            ch = kids.get(cur, [])
            if len(ch) != 1:
                break
            cur = ch[0]
        fork_children = kids.get(cur, []) if cur in nodes else []
        branches = []
        tones = [ORANGE, RED, GOLD, TEAL, GREEN]
        if len(fork_children) > 1:
            for bi, cid in enumerate(fork_children):
                chain, c = [], cid
                while c in nodes:
                    chain.append(nodes[c])
                    ch = kids.get(c, [])
                    c = ch[-1] if ch else None              # newest continuation at inner forks
                first_ask = next((n for n in chain if n.get("role") == "you"), chain[0] if chain else {})
                lead = next((n.get("agent") for n in chain
                             if n.get("role") == "agent" and n.get("agent")), "claude")
                branches.append({"id": cid, "label": _clip(str(first_ask.get("text", "branch")), 22),
                                 "lead": lead, "tone": tones[bi % len(tones)],
                                 "nodes": chain, "tail": chain[-1]["id"] if chain else cid})
        return trunk, branches

    def action_thread_branch(self, i) -> None:
        scr = self.screen
        if isinstance(scr, ThreadSurface):
            scr._active = int(i)
            scr.paint()

    def action_thread_compare(self) -> None:
        scr = self.screen
        if isinstance(scr, ThreadSurface):
            try:
                self.push_screen(CompareSurface(scr._root))
            except Exception:
                pass

    def action_compare_open(self, i) -> None:
        scr = self.screen
        if isinstance(scr, CompareSurface):
            root = scr._root
            self.pop_screen()
            if isinstance(self.screen, ThreadSurface):
                self.screen._active = int(i)
                self.screen.paint()
            else:
                self.push_screen(ThreadSurface(root, active=int(i)))

    def action_thread_deck(self, agent: str) -> None:
        """The CONTINUE deck — each verb adds a new continuation from the live branch's tail
        (never a tangle). 'Compare vs…' borrows the Matchup desk instead."""
        scr = self.screen
        if not isinstance(scr, ThreadSurface):
            return
        trunk, branches = self._thread_trunk_branches(scr._root)
        tail = (branches[scr._active]["tail"] if branches and 0 <= scr._active < len(branches)
                else (trunk[-1]["id"] if trunk else scr._root))
        tk, _ = self._thread_meta(scr._root)
        if agent == "value-analyst":                        # Compare vs… → the Matchup desk
            self.push_screen(MatchupSurface(hold=tk or self._blend_subject()))
            return
        briefs = {"bull": "Counter the case above — the strongest asymmetric long rebuttal.",
                  "balance-sheet-analyst": "Stress it harder — runway, dilution, the financing window.",
                  "arbiter": "Convene the council on this thread and reconcile ONE verdict."}
        self._active = tail
        self._delegate(agent, briefs.get(agent, "continue this thread"), subject=tk or self._blend_subject(),
                       continue_thread=True)                 # explicit follow-up → continue this thread
        scr.paint()

    def action_thread_newbranch(self) -> None:
        """+ new branch — your next ask forks from the branch point; type it in the command bar."""
        scr = self.screen
        if not isinstance(scr, ThreadSurface):
            return
        trunk, _branches = self._thread_trunk_branches(scr._root)
        fork = trunk[-1]["id"] if trunk else scr._root
        self._active = fork
        self.pop_screen()
        if isinstance(self.screen, BlendHubScreen):
            self.screen.action_cmd()
        self._toast("type the new branch's ask — it forks from the branch point", TEAL)

    # ---- Roster verbs ----
    def action_roster_run(self, agent: str) -> None:
        """▶ run on a fleet card → load the agent into the launch line, ready to brief."""
        self.pop_screen()
        if isinstance(self.screen, BlendHubScreen):
            self.screen.action_cmd()
            try:
                bar = self.screen.query_one("#blend_cmd", Input)
                bar.value = f"@{agent} "
                bar.cursor_position = len(bar.value)
            except Exception:
                pass
        self._toast(f"@{agent} loaded — describe the task, ⏎ to delegate", TEAL)

    def action_roster_chain(self, agent: str) -> None:
        """⛓ chain on a fleet card → append the agent as the next workflow stage."""
        self._workflow.append({"agents": [str(agent)], "note": ""})
        scr = self.screen
        if isinstance(scr, RosterSurface) and scr._mode == "chain":
            self.pop_screen()
        self._toast(f"⛓ stage {len(self._workflow)}: {agent} appended to the chain", TEAL)
        self._refresh_hub()

    # ---- the Concierge — a plain read-only LLM, NOT an agent ----
    def action_concierge_toggle(self) -> None:
        scr = self.screen
        if isinstance(scr, (BlendHubScreen, BlendSurface)):
            scr.action_concierge()

    def action_concierge_chip(self, i) -> None:
        scr = self.screen
        if isinstance(scr, (BlendHubScreen, BlendSurface)):
            chips = scr.concierge_chips()
            try:
                self._concierge_send(chips[int(i)], scr.concierge_context())
            except Exception:
                pass

    def _concierge_send(self, q: str, ctx: str) -> None:
        if self._concierge_busy:
            self._toast("the concierge is mid-answer — one at a time", ORANGE)
            return
        self._concierge_hist.append(("you", str(q)))
        self._concierge_busy = True
        self._concierge_repaint()
        self._concierge_bg(str(q), str(ctx))

    @work(thread=True, group="concierge", exclusive=True)
    def _concierge_bg(self, q: str, ctx: str) -> None:
        """The Concierge's lane: a one-shot `claude -p` with the on-screen frame as context and a
        hard read-only contract. It never touches the conversation tree, the run bus, or Memory."""
        frame = []
        try:
            st = self._state or {}
            frame.append(f"Operator is looking at: {ctx}.")
            if self._focus:
                frame.append(f"Desk focus: {self._focus}.")
            reg = st.get("regime") or {}
            if reg:
                frame.append(f"Regime: MRI {reg.get('mri', '—')} · {reg.get('label', reg.get('bias', ''))}.")
            titles = [str(i.get("title", "")) for i in self._blend_log_items("all")[:8]]
            if titles:
                frame.append("Recent Quest-Log events: " + "; ".join(titles) + ".")
        except Exception:
            pass
        prompt = ("You are the CommodityEx cockpit CONCIERGE — a plain, read-only assistant docked "
                  "under the Agent Hub. You explain, define, recap and help find things on screen. "
                  "You are NOT a research agent: you cannot trade, fire pipelines, run agents, or "
                  "write Living Memory — if asked to act, point at the on-screen affordance to click "
                  "instead. Be terse and signal-first; no emoji.\n\n"
                  + "\n".join(frame) + f"\n\nOperator asks: {q}")
        try:
            # the Concierge explains/recaps — a haiku job, NOT an opus@xhigh one. No effort
            # flag by default: haiku 4.5 doesn't take --effort (set CEX_CONCIERGE_EFFORT only
            # if you also move CEX_CONCIERGE_MODEL to sonnet/opus).
            argv = self._ask_argv(prompt, model=os.environ.get("CEX_CONCIERGE_MODEL", "haiku"),
                                  effort=os.environ.get("CEX_CONCIERGE_EFFORT", ""))
            out = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_ASK_TIMEOUT", "300")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            reply = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            reply = "(concierge offline — set CEX_ASK_CMD to a working CLI)"
        except Exception as exc:
            reply = f"(concierge error: {exc})"
        self.call_from_thread(self._concierge_deliver, reply or "(no answer)")

    def _concierge_deliver(self, text: str) -> None:
        self._concierge_busy = False
        self._concierge_hist.append(("concierge", str(text)))
        del self._concierge_hist[:-12]                      # ephemeral — never persisted
        self._concierge_repaint()

    def _concierge_repaint(self) -> None:
        scr = self.screen
        if isinstance(scr, (BlendHubScreen, BlendSurface)):
            try:
                scr.paint_concierge()
            except Exception:
                pass

    def _clip_copy(self, text: str) -> None:
        """Put text on the OS clipboard (pbcopy / clip / xclip / xsel). The dashboard owns the mouse,
        so this is the reliable way to lift agent output & memory off the screen (the ⧉ copy action)."""
        text = str(text or "")
        for argv in (["pbcopy"], ["clip"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                p = subprocess.Popen(argv, stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"), timeout=3)
                self._toast(f"⧉ copied {len(text)} chars to the clipboard", GREEN)
                return
            except Exception:
                continue
        self._toast("clipboard tool not found (pbcopy/xclip)", ORANGE)

    @staticmethod
    def _file_title(path: str) -> str:
        import re
        base = os.path.basename(path)
        base = base[:-3] if base.endswith(".md") else base
        base = re.sub(r"_\d{8}-\d{6}$", "", base)              # drop the trailing timestamp
        return (base.replace("_", " ").strip() or base)[:52]

    @staticmethod
    def _file_ticker(path: str):
        head = os.path.basename(path).split("_")[0]
        return head if (("." in head or head.isupper()) and 1 < len(head) <= 8) else None

    def _review_items(self, cat: str = "all", tk: str | None = None) -> list:
        """Aggregate sources into newest-first list. Tabs: archive · threads · activity · all."""
        import glob as _glob
        items: list = []
        now = time.time()
        repo = os.path.dirname(os.path.abspath(__file__))

        # ── Archive: living memory (non-pin/thread/sentinel) + saved markdown files ──
        if cat in ("all", "archive"):
            mem = self._memory()
            if mem is not None:
                try:
                    pinned = mem.pinned_ids()
                    _skip = {"pin", "thread", "sentinel", "sentinel_ack"}
                    for e in mem.query(limit=120):
                        if e.get("type") in _skip or (e.get("meta") or {}).get("retracted"):
                            continue
                        items.append({"cat": "archive", "glyph": self._MEM_GLYPH.get(e.get("type"), "·"),
                                      "title": str(e.get("text", "")), "ticker": e.get("ticker"),
                                      "age": _age_days(e.get("ts")) * 86400.0, "ref": e.get("id"),
                                      "pinned": e.get("id") in pinned})
                except Exception:
                    pass
            for p in _glob.glob(os.path.join(self._drafts_dir(), "*.md")):
                items.append({"cat": "archive", "glyph": "⏱", "title": self._file_title(p),
                              "ticker": self._file_ticker(p), "age": now - os.path.getmtime(p), "ref": p})
            for p in _glob.glob(os.path.join(repo, "research", "*.md")):
                items.append({"cat": "archive", "glyph": "🔬", "title": self._file_title(p),
                              "ticker": self._file_ticker(p), "age": now - os.path.getmtime(p), "ref": p})
            for p in _glob.glob(os.path.join(repo, "data", "decisions", "*.md")):
                items.append({"cat": "archive", "glyph": "▤", "title": self._file_title(p),
                              "ticker": self._file_ticker(p), "age": now - os.path.getmtime(p), "ref": p})

        # ── Threads: saved thread entries in living memory + active session threads ──
        if cat in ("all", "threads"):
            mem = self._memory()
            saved_roots: set = set()
            if mem is not None:
                try:
                    for e in mem.query(type="thread", limit=60):
                        if (e.get("meta") or {}).get("retracted"):
                            continue
                        root_id = (e.get("meta") or {}).get("thread_root_id", e.get("id"))
                        saved_roots.add(root_id)
                        items.append({"cat": "threads", "glyph": "↯",
                                      "title": str(e.get("text", "")), "ticker": e.get("ticker"),
                                      "age": _age_days(e.get("ts")) * 86400.0, "ref": e.get("id"),
                                      "mem_entry": True})
                except Exception:
                    pass
            for r in self._roots():
                if r["id"] in saved_roots:
                    continue   # already represented by the memory entry
                nodes = [n for n in self._conv.values() if self._branch_root(n["id"]) == r["id"]]
                if not any(n.get("role") == "agent" for n in nodes):
                    continue   # only show threads that have at least one agent reply
                tip = max(nodes, key=lambda n: n["ts"], default=r)
                items.append({"cat": "threads", "glyph": "↯",
                              "title": (f"{r.get('ticker')} · " if r.get('ticker') else "") + str(r.get("text", "")),
                              "ticker": r.get("ticker"), "age": now - float(tip.get("ts", now)), "ref": r["id"]})

        # ── Activity: agent activity log (renamed from Tape) ──
        if cat in ("all", "activity"):
            items += self._tape_items(self._state or {})

        if tk:
            items = [i for i in items if (i.get("ticker") or "").upper() == tk.upper()]
        items.sort(key=lambda i: i.get("age", 1e12))           # newest first
        return items

    def _flywheel_explainer(self, typ: str, ent: dict) -> str:
        """Plain-English decode for the validation FLYWHEEL's terse entries — so the desk isn't reading
        'OUTCOME LOSS -21% @90d (leg broke_floor) · stance-change' cold. Returns '' for non-flywheel
        entries (it only annotates what the flywheel itself wrote)."""
        if str(ent.get("source", "")) != "engine-flywheel" and "flywheel" not in (ent.get("tags") or []):
            return ""
        e_ = self._esc
        head = (f"[{TEAL}]▸ the flywheel[/]  [{SILVER}]the desk grading its OWN calls — it freezes each "
                f"decision, then re-checks at a horizon how it actually turned out. A real track record, "
                f"not marking its own homework.[/]")
        if typ == "outcome":
            legmap = {
                "bull": "reached the BULL leg — full upside hit",
                "base": "reached the base-case leg",
                "above_entry": "held above your entry (a modest gain)",
                "held_floor": "slipped below entry but HELD the REP floor (a contained loss)",
                "broke_floor": "fell THROUGH the REP (liquidation) floor — the real downside leg",
            }
            meta = ent.get("meta") or {}
            leg = legmap.get(str(meta.get("leg_hit", "")),
                             "where the price landed on the floor→bull ladder")
            reason = ("the bet closed because your STANCE on the name CHANGED — the old call is graded "
                      "here before the new one opens"
                      if "stance-change" in str(ent.get("text", ""))
                      else "the bet simply reached its measurement horizon")
            # THE RECEIPT — recover the frozen mark + the REAL holding period from the linked decision,
            # so the grade is auditable (the % is realized return vs the FROZEN price; '@Nd' is the
            # horizon SETTING, not how long the bet actually ran). A grade is only as honest as p0.
            rr = _num(meta.get("realized_return"))
            p0 = freeze_ts = None
            try:
                _mem = self._memory()
                for _rid in (ent.get("refs") or []):
                    _dec = _mem.get(_rid) if _mem is not None else None
                    if _dec and _dec.get("type") == "decision":
                        p0 = _num((_dec.get("meta") or {}).get("price")); freeze_ts = _dec.get("ts"); break
            except Exception:
                p0 = freeze_ts = None
            held = None
            if freeze_ts:
                import datetime as _dt
                try:
                    _f = _dt.datetime.fromisoformat(str(freeze_ts).replace("Z", "").split("+")[0])
                    _c = _dt.datetime.fromisoformat(str(ent.get("ts")).replace("Z", "").split("+")[0])
                    held = max(0, (_c - _f).days)
                except Exception:
                    held = None
            receipt = ""
            if rr is not None:
                rp = (p0 * (1.0 + rr)) if p0 else None
                bits = []
                if p0 and rp:
                    bits.append(f"frozen at [bold]{p0:.3f}[/] → closed at [bold]{rp:.3f}[/]")
                bits.append(f"realized [bold]{rr * 100:+.0f}%[/]")
                if held is not None:
                    bits.append(f"actually held [bold]{held}d[/]")
                receipt = (f"\n[{AMBER}]▸ the receipt[/]  [{SILVER}]" + " · ".join(bits) +
                           f" — the [bold]@Nd[/] is the horizon SETTING, not how long it ran.[/]")
                # a large 'result' over a near-instant hold is the signature of a BAD FREEZE PRICE
                # (a stale/wrong mark), not a real move — make it announce itself for retraction.
                if held is not None and held <= 3 and abs(rr) >= 0.15:
                    receipt += (f"\n[{ORANGE}]⚠ suspect grade[/]  [{SILVER}]a {rr * 100:+.0f}% result over "
                                f"just {held}d almost always means the FROZEN PRICE was bad — verify "
                                f"[bold]{(p0 if p0 else 0):.3f}[/] against the tape on the freeze date and "
                                f"[bold]✕ retract[/] if wrong, so it doesn't skew the learned base rate.[/]")
            return (head + "\n"
                    f"[{TEAL}]▸ this line[/]  [{SILVER}]a CLOSED, graded bet — [bold]WIN / LOSS / "
                    f"SCRATCH[/] vs the call (scratch = too small to count) · the % is the realized "
                    f"return since it was frozen · [bold](leg …)[/] = the price {e_(leg)} · the trailing "
                    f"reason = {e_(reason)}.[/]" + receipt + "\n"
                    f"[{SILVER}]It feeds the per-archetype LEARNED base rates + the Brier calibration that "
                    f"tune every future underwrite — and a grade is only as honest as its frozen mark.[/]")
        if typ == "decision":
            return (head + "\n"
                    f"[{TEAL}]▸ this line[/]  [{SILVER}]a FROZEN bet — the engine recorded this call "
                    f"(verdict @ price, with its floor and bull legs) so the flywheel can grade it later "
                    f"at the horizon. The immutable entry point of the track record.[/]")
        if typ == "calibration_snapshot":
            return (head + "\n"
                    f"[{TEAL}]▸ this line[/]  [{SILVER}]the per-archetype LEARNED base rates rolled up from "
                    f"your OWN closed outcomes — regime-stamped, used to anchor future underwrites and "
                    f"discovery against the desk's real track record, not just the textbook outside view.[/]")
        return head

    def _review_detail(self, item: dict):
        """(content-markup, actions-markup) for the selected Review item — the FULL content rendered
        as Rich markup for the detail Static (consistent with the rest of the desk), + verify/act."""
        e_ = self._esc
        cat, ref = item.get("cat"), item.get("ref")

        # ── Archive: living memory entry (no path sep) or saved file ──
        if cat == "archive":
            if ref and os.sep not in str(ref) and not str(ref).endswith(".md"):
                mem = self._memory()
                ent = mem.get(ref) if mem is not None else None
                if not ent:
                    return ("[#74747C]entry not found[/]", "[#74747C]‹ Esc[/]")
                typ = str(ent.get("type", "note")); etk = ent.get("ticker"); reg = ent.get("regime") or {}
                pinned = ent.get("id") in (mem.pinned_ids() if mem is not None else set())
                stale = (not pinned) and _age_days(ent.get("ts")) >= STALE_DAYS
                md = [f"[bold {GOLD}]{self._MEM_GLYPH.get(typ, '·')} {e_(typ.replace('_', ' ').upper())}[/]"
                      f"  [bold white]{e_(etk) if etk else 'book-level'}[/]", "",
                      f"[#C8C8CE]{e_(str(ent.get('text', '')))}[/]", ""]
                _fly = self._flywheel_explainer(typ, ent)   # decode terse flywheel entries in-place
                if _fly:
                    md += [_fly, ""]
                md += [f"[{BORDER}]{'─' * 40}[/]",
                       f"[{DIM}]by[/] [{SILVER}]{e_(str(ent.get('source', '—')))}[/]   "
                       f"[{DIM}]{_mem_age(ent.get('ts'))} ago[/]" + ("   [bold #CF9A5C]stale[/]" if stale else "")]
                if reg.get("mri") is not None or reg.get("posture") or reg.get("net_tilt"):
                    md.append(f"[{DIM}]captured under[/] [{SILVER}]MRI {_fmt(reg.get('mri'), '{:.0f}')} · "
                              f"{e_(str(reg.get('posture') or reg.get('net_tilt') or '—'))}[/]")
                if ent.get("tags"):
                    md.append("  ".join(f"[{DIM}]#{e_(str(t))}[/]" for t in (ent.get("tags") or [])[:8]))
                acts = []
                if etk:
                    acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(etk)}[/][/]")
                acts.append(f"[@click=app.review_do('pin')][{AMBER if pinned else DIM}]{'unpin' if pinned else '📌 pin'}[/][/]")
                if stale:
                    acts.append(f"[@click=app.review_do('reaffirm')][{ORANGE}]↻ re-confirm[/][/]")
                acts.append(f"[@click=app.review_do('edit')][{DIM}]✎ edit[/][/]")
                acts.append(f"[@click=app.review_do('retract')][{DIM}]✕ retract[/][/]")
                acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]")
                return ("\n".join(md), "   ".join(acts))
            else:
                try:
                    with open(ref, encoding="utf-8") as fh:
                        body = fh.read()
                except Exception:
                    body = "could not read this file"
                head = f"[bold {GOLD}]{e_(self._file_title(ref))}[/]   [{DIM}]{e_(os.path.basename(ref))}[/]\n\n"
                acts = []
                if item.get("ticker"):
                    acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(item['ticker'])}[/][/]")
                acts.append(f"[@click=app.review_do('ask')][{TEAL}]› send to chat[/][/]")
                acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]")
                acts.append(f"[@click=app.review_do('discard')][{DIM}]✕ discard[/][/]")
                acts.append("[#74747C]· Esc[/]")
                return (head + f"[#C8C8CE]{e_(body)}[/]", "   ".join(acts))

        # ── Threads: saved memory thread entry or live session thread ──
        if cat == "threads":
            if item.get("mem_entry"):
                mem = self._memory()
                ent = mem.get(ref) if mem is not None else None
                if not ent:
                    return ("[#74747C]thread not found[/]", "[#74747C]‹ Esc[/]")
                full_text = (ent.get("meta") or {}).get("full_text") or str(ent.get("text", ""))
                etk = ent.get("ticker")
                md = [f"[bold {GOLD}]↯ THREAD[/]  [bold white]{e_(etk) if etk else 'book-level'}[/]",
                      f"[{DIM}]{_mem_age(ent.get('ts'))} ago[/]", "",
                      f"[#C8C8CE]{e_(full_text)}[/]"]
                acts = []
                if etk:
                    acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(etk)}[/][/]")
                acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]")
                acts.append(f"[@click=app.review_do('retract')][{DIM}]✕ retract[/][/]")
                acts.append("[#74747C]· Esc[/]")
                return ("\n".join(md), "   ".join(acts))
            else:
                nodes = sorted((n for n in self._conv.values() if self._branch_root(n["id"]) == ref),
                               key=lambda n: n["ts"])
                root = self._conv.get(ref) or {}
                md = [f"[bold {GOLD}]↯ THREAD[/]  [bold white]{e_(root.get('ticker') or '—')}[/]", ""]
                for n in nodes:
                    if n.get("role") == "you":
                        md.append(f"[b {TEAL}]you ›[/] [{SILVER}]{e_(str(n.get('text', '')))}[/]\n")
                    else:
                        md.append(f"[b {GREEN}]{e_(str(n.get('agent', 'claude')))} ‹[/] [#C8C8CE]{e_(str(n.get('text', '')))}[/]\n")
                acts = (f"[@click=app.review_do('jump')][{TEAL}]› open in chat[/][/]   "
                        f"[@click=app.review_do('handoff_verifier')][{AMBER}]→ verify[/][/]   "
                        f"[@click=app.review_do('handoff_synthesis')][{AMBER}]→ synthesis[/][/]   "
                        f"[@click=app.review_do('handoff_bear')][{AMBER}]→ bear[/][/]   "
                        f"[@click=app.review_do('save')][{GOLD}]⇪ save[/][/]   "
                        f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]   [#74747C]· Esc[/]")
                return ("\n".join(md), acts)

        # ── Activity (renamed from Tape) ──
        if cat == "activity":
            acts_list = (self._state or {}).get("agent_activity", []) or []
            ev = next((a for a in acts_list if str(a.get("seq")) == str(ref)), None) or {}
            rep = (self._state or {}).get("agent_reply") or {}
            md = [f"[bold {GOLD}]{e_(str(ev.get('kind', 'event')).upper())}[/]  "
                  f"[{SILVER}]{e_(str(ev.get('agent', '')))}[/]" + (f"  [{AMBER}]{e_(ev.get('ticker'))}[/]" if ev.get('ticker') else ""),
                  "", f"[#C8C8CE]{e_(str(ev.get('summary', '')))}[/]", "", f"[{DIM}]{_rel_age(ev.get('ts'))}[/]"]
            if ev.get("kind") in ("reply", "response") and rep.get("text"):
                md += ["", f"[#C8C8CE]{e_(str(rep.get('text'))[:2000])}[/]"]
            acts = []
            if ev.get("ticker"):
                acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(ev['ticker'])}[/][/]")
            acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]   [#74747C]· Esc[/]")
            return ("\n".join(md), "   ".join(acts))

        return ("[#74747C]nothing selected[/]", "[#74747C]‹ Esc[/]")

    def _review_copy_text(self, item: dict) -> str:
        """Plain text to put on the clipboard for a Review item (the desk owns the mouse in Textual,
        so ⧉ copy is the reliable way to lift agent output / memory off the screen)."""
        cat, ref = item.get("cat"), item.get("ref")
        try:
            if cat == "archive":
                if ref and os.sep not in str(ref) and not str(ref).endswith(".md"):
                    ent = (self._memory().get(ref) if self._memory() else None) or {}
                    return str(ent.get("text", ""))
                with open(ref, encoding="utf-8") as fh:
                    return fh.read()
            if cat == "threads":
                if item.get("mem_entry"):
                    ent = (self._memory().get(ref) if self._memory() else None) or {}
                    return (ent.get("meta") or {}).get("full_text") or str(ent.get("text", ""))
                nodes = sorted((n for n in self._conv.values() if self._branch_root(n["id"]) == ref),
                               key=lambda n: n["ts"])
                return "\n\n".join(("You: " if n.get("role") == "you" else
                                    f"{n.get('agent', 'claude')}: ") + str(n.get("text", "")) for n in nodes)
            if cat == "activity":
                ev = next((a for a in ((self._state or {}).get("agent_activity") or [])
                           if str(a.get("seq")) == str(ref)), {})
                rep = (self._state or {}).get("agent_reply") or {}
                txt = str(ev.get("summary", ""))
                if ev.get("kind") in ("reply", "response") and rep.get("text"):
                    txt += "\n\n" + str(rep.get("text"))
                return txt
        except Exception:
            pass
        return str(item.get("title", ""))

    def action_review_sel(self, idx) -> None:
        if isinstance(self.screen, HubScreen):
            self.screen.select(int(idx))

    def action_review_cat(self, cat) -> None:
        if isinstance(self.screen, HubScreen):
            self.screen._tk = None                              # clicking a category also clears the filter
            self.screen.set_cat(str(cat))

    def action_review_do(self, op: str = "primary") -> None:
        """Dispatch a verify/act on the selected Review item; reload the room (or close it for nav)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        item = scr.current()
        if not item:
            return
        cat, ref, tk = item.get("cat"), item.get("ref"), item.get("ticker")
        if op == "primary":
            op = "jump" if cat == "threads" else ("focus" if tk else "open")
        if op == "copy":
            self._clip_copy(self._review_copy_text(item)); return
        if op == "focus" and tk:
            scr.dismiss(None); self._set_focus(tk, move_cursor=True); self.action_tab("book"); return
        if cat == "archive" and ref and os.sep not in str(ref) and not str(ref).endswith(".md"):
            # living memory entry in Archive tab
            if op == "pin":
                self.action_mem_pin(ref)
            elif op == "reaffirm":
                self.action_mem_reaffirm(ref)
            elif op == "retract":
                self.action_mem_del(ref)
            elif op == "edit":
                scr.dismiss(None); self.action_mem_edit(ref); return
            scr.reload()
        elif cat == "archive":
            # saved file in Archive tab
            if op == "discard":
                try:
                    os.remove(ref)
                except OSError:
                    pass
                self._toast("discarded", DIM); scr.reload()
            elif op == "ask":
                scr.dismiss(None)
                try:
                    with open(ref, encoding="utf-8") as fh:
                        content = fh.read()[:4000]
                except Exception:
                    content = ""
                self._ask_agent(f"Review this research and tell me whether it's worth acting on, and "
                                f"the single best next step:\n\n{content}")
        elif cat == "threads":
            if item.get("mem_entry"):
                if op == "retract":
                    self.action_mem_del(ref); scr.reload()
            else:
                if op == "jump":
                    scr.dismiss(None); self.action_sel_branch(ref)
                elif op == "save":
                    self.action_sel_branch(ref); self.action_save_thread(); scr.reload()
                elif op.startswith("handoff_"):
                    agent = op[len("handoff_"):]
                    hnodes = sorted((n for n in self._conv.values()
                                     if self._branch_root(n["id"]) == ref), key=lambda n: n["ts"])
                    report = "\n\n".join(
                        ("You: " if n.get("role") == "you" else f"{n.get('agent','agent')}: ")
                        + str(n.get("text", "")) for n in hnodes)
                    subj = item.get("ticker") or ""
                    verb = {"verifier": "verify and red-team", "synthesis": "deep-dive and value",
                            "bear": "build the strongest bear case for"}.get(agent, "review")
                    brief = (f"Prior research context:\n\n{report[:3500]}\n\n---\n"
                             f"Task: {verb} {subj} using the above as your starting point.")
                    self._delegate(agent, brief, subject=subj)
                    self._toast(f"handed off to @{agent} — watch Working lane", GREEN)

    # ---- autonomy dial + one-click proposal clearing (the agent-trust model) ----------------
    def action_autonomy(self, mode: str) -> None:
        if mode not in ("manual", "propose", "auto"):
            return
        self._autonomy = mode
        self._receipt(f"autonomy → {mode}", "⚙", AMBER)
        self._render_autonomy(self._state or {})
        self._toast(f"autonomy set to {mode}", AMBER)

    def action_confirm_prop(self, pid) -> None:
        try:
            self._do_confirm(int(pid))
        except (TypeError, ValueError):
            pass

    def action_reject_prop(self, pid) -> None:
        try:
            self._do_reject(int(pid))
        except (TypeError, ValueError):
            pass

    def action_prop_why(self, pid) -> None:
        p = next((x for x in (self._pending or []) if str(x.get("id")) == str(pid)), None)
        if p:
            self._ask_agent(f"explain agent proposal #{pid}: {p.get('key')}={p.get('value')} "
                            f"(by {p.get('proposed_by', 'agent')}) — is it justified in this regime?")

    # ------------------------------------------------------------------ dossier
    def _render_dossier_index(self) -> None:
        idx = self.query_one("#dossier_index", Static)
        if not self._decisions:
            idx.update(f"[{DIM}]No dossiers yet.\n\nSave one from the CONVERSATION (⇪ save on a thread),\n"
                       f"or just ask the desk to “run the pipeline on silver” /\n“write a dossier on GMX”.[/]")
            return
        lines = []
        for i, d in enumerate(self._decisions[:20]):
            name = self._esc(str(d.get("name", "")))
            sel = (d.get("name") == self._open_doss)
            mark = "▸" if sel else " "
            col = AMBER if sel else SILVER
            tk = self._esc(str(d.get("ticker") or "?"))
            title = self._esc(str(d.get("title", ""))[:20])
            age = d.get("age_minutes", "?")
            arm = (name == self._del_arm)
            lines.append(f"[{col}]{mark}[/][@click=app.open_dossier('{name}')] "
                         f"[bold {col}]{tk:<7}[/] [{col}]{title}[/]  [{DIM}]{age}m[/][/]"
                         f"  [@click=app.delete_dossier('{name}')]"
                         f"[{RED if arm else DIM}]{'✕ sure?' if arm else '✕'}[/][/]")
        idx.update("\n".join(lines))

    def action_open_dossier(self, name: str) -> None:
        self.action_tab("dossier_tab")
        self._open_doss = name
        self._del_arm = None
        self._render_dossier_index()
        self._open_dossier(name)
        try:
            self.query_one("#dossier_open", Input).value = ""
        except Exception:
            pass

    def action_delete_dossier(self, name: str) -> None:
        if self._del_arm != name:                          # first click arms, second deletes
            self._del_arm = name
            self._render_dossier_index()
            self._status(Text("click ✕ again to delete this dossier", style=ORANGE))
            return
        self._del_arm = None
        self._delete_dossier(name)

    @work(thread=True, group="dossier_del")
    def _delete_dossier(self, name: str) -> None:
        res = _post("/decisions/delete", {"name": name})
        ok = isinstance(res, dict) and res.get("ok")

        def after():
            if self._open_doss == name:
                self._open_doss = None
                try:
                    self.query_one("#dossier_body", Markdown).update("")
                except Exception:
                    pass
            self._status(Text("🗑 dossier deleted" if ok else f"delete failed: {(res or {}).get('error', '?')}",
                              style=(GREEN if ok else RED)))
            self._refresh_decisions()
        self.call_from_thread(after)

    @work(thread=True, group="dossier")
    def _open_dossier(self, name: str) -> None:
        res = _get(f"/decisions/item?name={quote(name)}")
        md = (res or {}).get("markdown") or (res or {}).get("body") or f"*could not load {name}*"
        self.call_from_thread(self.query_one("#dossier_body", Markdown).update, md)

    @work(thread=True, group="dossier_refresh", exclusive=True)
    def _refresh_decisions(self) -> None:
        """Pull the dossier index immediately (don't wait for the ~12s poll) after a save."""
        res = _get("/decisions")
        self._decisions = (res or {}).get("decisions", []) or []
        self.call_from_thread(self._render_dossier_index)

    # ------------------------------------------------------------------ agent pickup
    def _handle_agent_command(self, state) -> None:
        cmd = state.get("ui_command") or {}
        seq = cmd.get("seq", 0)
        if not seq or seq <= self._last_seq:
            return
        self._last_seq = seq
        args = cmd.get("args", {}) or {}
        action = cmd.get("action")
        if action in ("focus", "focus_element") and args.get("ticker"):
            self._set_focus(args["ticker"], move_cursor=True, report=False)
        elif action == "scenario":
            ov = args.get("scenario") or args.get("overrides") or ""
            self.query_one("#wf_overrides", Input).value = str(ov)
            self._wf_source = "agent"
            self._status(Text(f"↯ scenario proposed by agent: {ov}", style=GREEN))
        elif action == "switch_tab":
            self.action_tab(self._tab_for(args.get("view") or args.get("tab")))
        elif action == "apply_scenario":
            if args.get("ticker"):
                self._set_focus(args["ticker"], move_cursor=True, report=False)
            ov = args.get("overrides") or args.get("scenario") or ""
            self.query_one("#wf_overrides", Input).value = str(ov)
            self._wf_source = "agent"
            self.action_tab("whatif")
            self._do_whatif()
            self._status(Text(f"↯ agent ran what-if: {ov}", style=GREEN))
        elif action in ("highlight", "pin_insight") and args.get("ticker"):
            r = str(args.get("reason") or args.get("note") or "")[:48]
            self._status(Text(f"✦ {args.get('agent','agent')} flagged {args['ticker']}: {r}",
                              style=_level_color(args.get("level"))))
        self._refresh_hub()                       # surface fresh agent activity in the Hub if it's open

    # ------------------------------------------------------------------ focus plumbing
    def _set_focus(self, ticker, move_cursor=False, report=True) -> None:
        ticker = (ticker or "").strip()
        if not ticker:
            return
        self._focus = ticker
        if move_cursor and ticker in self._row_index:
            self._suppress_report = True
            try:
                self.query_one("#booktbl", DataTable).move_cursor(row=self._row_index[ticker], animate=False)
            except Exception:
                pass
            self._suppress_report = False
        if ticker in self._baskets_by_ticker:
            self._render_book_detail(ticker)
            self._fetch_fundamentals(ticker)
        else:
            # watchlist / bench ticker — fetch fundamentals and render what we have
            self._fetch_fundamentals(ticker)
            self._render_profile(ticker)
        if report:
            self._report_ui(ticker)

    @work(thread=True, group="fund")
    def _fetch_fundamentals(self, ticker: str) -> None:
        """FMP fundamentals for the focused name (engine-cached + budget-capped). Many TSXV juniors
        aren't covered on the free tier — we store {} so the panel degrades to engine data, no spam."""
        if ticker in self._fund:
            return
        res = _get(f"/fmp/fundamentals?ticker={quote(ticker)}")
        data = (res or {}).get("data") if isinstance(res, dict) else None
        self._fund[ticker] = data if isinstance(data, dict) else {}
        if self._focus == ticker:
            if ticker in self._baskets_by_ticker:
                self.call_from_thread(self._render_book_detail, ticker)
            else:
                self.call_from_thread(self._render_profile, ticker)   # watchlist name

    @work(thread=True, group="ui")
    def _report_ui(self, ticker: str) -> None:
        view = self._current_view()
        sig = (ticker, view)
        if sig == self._last_reported:
            return
        self._last_reported = sig
        _post("/ui/state", {"focused_ticker": ticker, "active_view": view, "source": "tui",
                            "current_scenario": self._active_scenario,
                            "visible_tickers": list(self._baskets_by_ticker)})

    # ------------------------------------------------------------------ events
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        tk = getattr(event.row_key, "value", event.row_key)
        if not tk:
            return
        self._focus = str(tk)
        self._render_book_detail(str(tk))
        if not self._suppress_report:
            self._report_ui(str(tk))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tk = getattr(event.row_key, "value", event.row_key)      # click / Enter on a row → full profile
        if tk:
            self.action_open_profile(str(tk))

    def on_collapsible_toggled(self, event: Collapsible.Toggled) -> None:
        """Summoning a lens (incl. via its title toggle) renders its body immediately and reports the
        new view to the agents — the Collapsible replacement for tab activation."""
        c = getattr(event, "collapsible", None)
        if c is not None and not c.collapsed:
            self._on_lens_opened(c.id)
        if self._focus:
            self._report_ui(self._focus)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id
        val = event.value.strip()
        if wid == "cmdbar":
            low = val.lower()
            editing = self._editing_mem              # consumed by this submit (always cleared)
            self._editing_mem = None
            if val and (not self._ask_history or self._ask_history[-1] != val):
                self._ask_history.append(val)         # remember for ↑/↓ recall (dedupe consecutive)
                del self._ask_history[:-50]
            if isinstance(event.input, ChatInput):
                event.input._hist_idx = None          # reset the recall cursor on send
            if val.startswith("/") or val.startswith(":"):
                self._run_command(val)
            elif low.startswith("note:") or low.startswith("note "):
                note_text = val.split(":", 1)[-1].strip() if ":" in val else val[5:].strip()
                if editing:                           # an in-place edit supersedes the original
                    self._edit_note(editing, note_text)
                else:
                    self._write_note(note_text)
            elif low.startswith("catalyst:"):         # Forge M1 — add a catalyst WINDOW to the calendar
                self._write_catalyst(val.split(":", 1)[1].strip())
            elif low.startswith("claim:"):            # Forge M2 — bind a load-bearing claim to the thesis
                self._amend_thesis_claim(val.split(":", 1)[1].strip())
            elif low.startswith("rule:"):             # Forge M2 — arm a pre-commitment (Ulysses) rule
                self._amend_thesis_rule(val.split(":", 1)[1].strip())
            elif val:
                self._ask_agent(val, ticker=self._focus)  # book-view query: bind to what the user is viewing
            event.input.value = ""
            self.call_after_refresh(event.input.focus)   # stay in chat — no / to send the next one
        elif wid in ("wf_ticker", "wf_overrides"):
            self._do_whatif()
        elif wid == "wf_scenario":
            self._load_scenario(val)
        elif wid == "wf_name":
            self._do_save(val)
        elif wid == "dossier_open":
            self._dossier_pick(val)
        elif wid == "watchsearch":
            self._watch_search(val)
            event.input.value = ""

    def _watch_search(self, q: str) -> None:
        """The watchlist search box is a door: a known holding focuses it; anything else scouts the
        theme/name onto the bench (headless) and shows a scanning row."""
        q = (q or "").strip()
        if not q:
            return
        up = q.upper()
        if up in (self._baskets_by_ticker or {}):     # a holding → just focus it on the spine
            self._set_focus(up, move_cursor=True)
            return
        self._watch_query = q
        self._render_watchlist(self._state or {})
        self._run_pipeline_bg(q, mode="scout")        # headless scout; results stream to PIPELINE + bench
        self._status(Text(f"⟳ scouting “{q[:32]}” onto the watchlist (headless)", style=TEAL))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "k_down":
            self.action_wf_step(-1, False)
        elif bid == "k_up":
            self.action_wf_step(1, False)
        elif bid == "k_clear":
            self.action_wf_reset()
        elif bid == "wf_run":
            self._do_whatif()
        elif bid == "wf_decomp":
            self._wf_decompose()
        elif bid == "wf_save":
            self._do_save(self.query_one("#wf_name", Input).value.strip())

    # ------------------------------------------------------------------ actions
    # old tab ids → always-on detail cards. council is inline; grid is hotkey-toggled; book = the spine.
    _LENS_FOR = {"book": None, "whatif": "lens_whatif", "regime_tab": "lens_regime",
                 "dossier_tab": "lens_dossier", "profile_tab": "lens_dossier"}
    _VIEW_FOR = {"whatif": "whatif", "regime_tab": "regime", "dossier_tab": "dossier",
                 "profile_tab": "dossier", "grid": "book", "book": "book"}

    def action_tab(self, tab_id: str) -> None:
        """Compat shim: the detail cards (Regime · Name · What-If) are always on the right column now,
        so 'switch a tab' means 'scroll that card into view'. Every old caller keeps working. The Book
        Grid is hotkey-toggled (`g`); council stays inline."""
        tid = str(tab_id)
        if tid in ("council_tab", "council"):
            self.action_go_council()                      # council stays inline — not a card
            return
        if tid in ("grid", "lens_grid"):
            self.action_grid(show=True)
            return
        lens_id = self._LENS_FOR.get(tid)
        if lens_id:
            self.open_lens(lens_id)
        self._active_view = self._VIEW_FOR.get(tid, "book")

    def open_lens(self, lens_id: str, *, solo: bool = False) -> None:
        """Scroll a detail card into view (the cards are always expanded) and render it fresh."""
        for c in self.query(Collapsible):
            if c.id == lens_id:
                c.collapsed = False
                try:
                    c.scroll_visible(animate=False)
                except Exception:
                    pass
        self._on_lens_opened(lens_id)

    def action_lens(self, lens_id: str) -> None:
        """Toggle a detail card collapsed/expanded (muscle-memory key + click bindings)."""
        try:
            c = self.query_one(f"#{lens_id}", Collapsible)
        except Exception:
            return
        c.collapsed = not c.collapsed
        if not c.collapsed:
            self._on_lens_opened(lens_id)
            try:
                c.scroll_visible(animate=False)
            except Exception:
                pass

    def action_grid(self, show=None) -> None:
        """Toggle the Book Grid — invisible until summoned with `g` (a dense table when you want it)."""
        try:
            grid = self.query_one("#lens_grid", Collapsible)
        except Exception:
            return
        grid.display = (not grid.display) if show is None else bool(show)
        if grid.display:
            grid.collapsed = False
            try:
                grid.scroll_visible(animate=False)
            except Exception:
                pass

    def _on_lens_opened(self, lens_id: str) -> None:
        """Render a card body the moment it's summoned (don't wait for the 3 s poll)."""
        if lens_id == "lens_dossier" and self._focus:
            self._render_profile(self._focus)
            self._render_dossier_index()
        elif lens_id == "lens_regime":
            self._render_regime(self._state or {})

    def _lens_open(self, lens_id: str) -> bool:
        try:
            return not self.query_one(f"#{lens_id}", Collapsible).collapsed
        except Exception:
            return False

    def _current_view(self) -> str:
        """The view the operator last summoned (for /ui/state reporting). The detail cards are always
        on, so this is an explicit pointer rather than derived from collapse state."""
        return getattr(self, "_active_view", "book")

    @staticmethod
    def _tab_for(view) -> str:
        return {"book": "book", "whatif": "whatif", "what-if": "whatif", "live what-if": "whatif",
                "council": "book", "council_tab": "book",   # council is merged into the Book page
                "regime": "regime_tab", "regime_tab": "regime_tab", "profile": "profile_tab",
                "profile_tab": "profile_tab",
                "dossier": "dossier_tab", "dossier_tab": "dossier_tab"}.get(str(view or "").lower(), "book")

    def action_whatif_focus(self) -> None:
        self.action_tab("whatif")
        if self._focus:
            self.query_one("#wf_ticker", Input).value = self._focus
        self._render_wf_knobs()
        self.query_one("#wf_overrides", Input).focus()

    # ---- interactive what-if knobs -----------------------------------------
    def _wf_active(self) -> bool:
        try:
            return not self.query_one("#lens_whatif", Collapsible).collapsed
        except Exception:
            return False

    def action_wf_knob(self, direction: int) -> None:
        if not self._wf_active():
            return
        self._wf_sel = (self._wf_sel + int(direction)) % len(_WF_KNOBS)
        self._render_wf_knobs()

    def action_wf_step(self, direction: float, fine: bool = False) -> None:
        if not self._wf_active():
            return
        name, key, kind, coarse, finestep, label = _WF_KNOBS[self._wf_sel]
        step = (finestep if fine else coarse) * (1 if direction >= 0 else -1)
        self._wf_knobs[name] = round(self._wf_knobs.get(name, 0.0) + step, 4)
        self._sync_knobs(); self._render_wf_knobs(); self._wf_live()

    def action_wf_reset(self) -> None:
        for n in self._wf_knobs:
            self._wf_knobs[n] = 0.0
        self._sync_knobs(); self._render_wf_knobs()
        try:
            self.query_one("#wf_result", Static).update(Text("knobs reset", style=DIM))
        except Exception:
            pass

    def _sync_knobs(self) -> None:
        try:
            self.query_one("#wf_overrides", Input).value = self._wf_overrides_from_knobs()
        except Exception:
            pass

    def _wf_overrides_from_knobs(self) -> str:
        parts = []
        for name, key, kind, coarse, fine, label in _WF_KNOBS:
            v = self._wf_knobs.get(name, 0.0)
            if abs(v) < 1e-9:
                continue
            parts.append(f"{key}={v:+g}%" if kind == "pct" else f"{key}={v:+g}")
        return " ".join(parts)

    def _knobs_from_overrides(self, ov: str) -> None:
        for n in self._wf_knobs:
            self._wf_knobs[n] = 0.0
        for tok in str(ov or "").replace(",", " ").split():
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            name = _ALIAS_TO_KNOB.get(k.strip().lower())
            if not name:
                continue
            try:
                self._wf_knobs[name] = float(v.strip().rstrip("%"))
            except ValueError:
                pass

    def _wf_live(self) -> None:
        if self._wf_timer is not None:
            try:
                self._wf_timer.stop()
            except Exception:
                pass
        self._wf_timer = self.set_timer(0.5, self._do_whatif)   # debounce live revalue while stepping

    def _render_wf_knobs(self) -> None:
        t = Text()
        for i, (name, key, kind, coarse, fine, label) in enumerate(_WF_KNOBS):
            v = self._wf_knobs.get(name, 0.0)
            sel = i == self._wf_sel
            nm_col = AMBER if sel else (SILVER if abs(v) > 1e-9 else DIM)
            disp = (f"{v:+g}{'%' if kind == 'pct' else ''}") if abs(v) > 1e-9 else "·"
            click = Style(meta={"@click": f"app.wf_sel({i})"})       # click a knob to select it
            t.append(f"{'▸' if sel else ' '}{label:<8}", style=Style.parse(f"bold {nm_col}") + click)
            t.append(f"{disp:>7}", style=Style.parse(GREEN if v > 0 else (RED if v < 0 else DIM)) + click)
            t.append("    " if i % 2 == 0 else "\n")
        try:
            self.query_one("#wf_knobs", Static).update(t)
        except Exception:
            pass

    def action_wf_sel(self, i: int) -> None:
        """Click-select a what-if knob (replaces the [ ] keys); then the ± buttons nudge it."""
        try:
            self._wf_sel = int(i) % len(_WF_KNOBS)
            self._render_wf_knobs()
        except Exception:
            pass

    @work(thread=True, group="wfproto", exclusive=True)
    def _wf_prototype_bg(self, idea: str, ticker: str) -> None:
        """Free-form SCENARIO: an agent turns a plain-language scenario into (a) runnable knob overrides
        AND (b) a narrative of the second-order effects BEYOND the 7 knobs (dilution/financing-window,
        catalyst timing, liquidity/ADV, regime shift, peer re-rating, thesis-integrity). The knobs run
        live; the narrative shows alongside the numbers — so the what-if isn't boxed into hard knobs."""
        tkname = ticker or self._focus or "the focused name"
        self.call_from_thread(lambda: self.query_one("#wf_result", Static).update(
            Text(f"⟳ an agent is building the scenario for {tkname}…  “{idea[:42]}”", style=TEAL)))
        prompt = (
            f"You are a resource-sector analyst building a what-if SCENARIO for {tkname} in the CommodityEx engine.\n"
            "Only these knobs are numerically runnable: silver (+/- $), gold (+/- $), ry (+/- pp real yield), "
            "dxy (+/- index pts), peer (+/-% EV/oz multiple), vol (+/-% silver vol), mri (+/- regime score).\n"
            "Return EXACTLY two lines, no fences, no extra prose:\n"
            "KNOBS: <space-separated key=value deltas using ONLY those knobs, e.g. silver=+8 ry=-0.5 peer=+20%>\n"
            f"BRIEF: <2-4 sentences on the SECOND-ORDER effects this scenario has on {tkname} that the knobs "
            "can't capture — dilution / financing-window risk, catalyst timing, liquidity / ADV, regime shift, "
            "peer re-rating, thesis-integrity.>\n"
            f"Scenario: {idea}")
        try:
            out = subprocess.run(self._ask_argv(prompt), capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_ASK_TIMEOUT", "180")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            raw = (out.stdout or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._status, Text("scenario: CLI not found — set CEX_ASK_CMD", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"scenario failed: {exc}", style=ORANGE)); return
        # parse KNOBS: / BRIEF: (tolerant — fall back to any line of knob tokens)
        knobs_line, brief, in_brief = "", "", False
        for line in raw.splitlines():
            s = line.strip()
            if s.upper().startswith("KNOBS:"):
                knobs_line = s.split(":", 1)[1]; in_brief = False
            elif s.upper().startswith("BRIEF:"):
                brief = s.split(":", 1)[1].strip(); in_brief = True
            elif in_brief and s:
                brief += " " + s
        if not knobs_line:
            for line in raw.splitlines():
                toks = line.replace(",", " ").split()
                if any("=" in t and t.split("=", 1)[0].strip().lower() in _ALIAS_TO_KNOB for t in toks):
                    knobs_line = line; break
        ov = " ".join(tok for tok in knobs_line.replace(",", " ").split()
                      if "=" in tok and tok.split("=", 1)[0].strip().lower() in _ALIAS_TO_KNOB)
        if not ov and not brief:
            self.call_from_thread(self._status, Text("couldn't build the scenario — try explicit overrides", style=ORANGE)); return

        def apply():
            self._wf_scenario_brief = brief
            self._wf_scenario_ov = ov
            self._wf_source = "agent"
            if ov:
                self._knobs_from_overrides(ov); self._render_wf_knobs()
                self.query_one("#wf_overrides", Input).value = ov
                self.query_one("#wf_result", Static).update(Text(f"scenario → {ov}  · running…", style=GREEN))
                self._run_whatif(ticker, ov)
            else:                       # purely qualitative scenario — show the narrative on its own
                t = Text(f"{tkname}  ", style=f"bold {GOLD}")
                t.append("agent scenario · no runnable knob move\n\n", style=DIM)
                t.append(brief, style=SILVER)
                self.query_one("#wf_result", Static).update(t)
        self.call_from_thread(apply)

    @work(thread=True, group="wfdecomp", exclusive=True)
    def _wf_decompose(self) -> None:
        """Granularity: attribute the move to each lever by revaluing one knob at a time."""
        ticker = self.query_one("#wf_ticker", Input).value.strip()
        active = [(n, k, kind) for (n, k, kind, c, f, l) in _WF_KNOBS if abs(self._wf_knobs.get(n, 0.0)) > 1e-9]
        if not active:
            self.call_from_thread(self._status, Text("set some knobs first, then Decompose", style=ORANGE)); return
        self.call_from_thread(lambda: self.query_one("#wf_result", Static).update(
            Text("⟳ decomposing the move per driver…", style=TEAL)))
        rows = []
        for n, k, kind in active:
            v = self._wf_knobs[n]
            ov = f"{k}={v:+g}%" if kind == "pct" else f"{k}={v:+g}"
            res = _post("/action/whatif", {"ticker": ticker, "overrides": ov})
            dp = (res.get("delta") or {}).get("intrinsic_pct") if isinstance(res, dict) else None
            rows.append((n, ov, _num(dp)))
        comb = _post("/action/whatif", {"ticker": ticker, "overrides": self._wf_overrides_from_knobs()})
        cdp = _num((comb.get("delta") or {}).get("intrinsic_pct")) if isinstance(comb, dict) else None
        self.call_from_thread(self._show_decomp, ticker, rows, cdp)

    def _show_decomp(self, ticker, rows, cdp) -> None:
        t = Text(f"{ticker} — per-driver attribution of Δ intrinsic\n", style=f"bold {GOLD}")
        mx = max((abs(d) for _, _, d in rows if d is not None), default=1.0) or 1.0
        for name, ov, d in sorted(rows, key=lambda r: -(abs(r[2]) if r[2] is not None else 0)):
            w = round(abs(d) / mx * 16) if d is not None else 0
            t.append(f"{ov:<14}", style=SILVER)
            t.append("▰" * w + " " * (16 - w), style=(GREEN if (d or 0) >= 0 else RED))
            t.append(f" {_fmt(d)}%\n", style=(GREEN if (d or 0) >= 0 else RED))
        if cdp is not None:
            t.append(f"{'COMBINED':<14}", style=f"bold {AMBER}")
            t.append(f"{'':16} {_fmt(cdp)}%", style=f"bold {(GREEN if cdp >= 0 else RED)}")
            interact = sum(d for _, _, d in rows if d is not None)
            t.append(f"   (interaction {cdp - interact:+.1f}pp)", style=DIM)
        self.query_one("#wf_result", Static).update(t)

    def action_cmd(self) -> None:
        """Focus the chat input (which now lives in the Book conversation panel). Plain text is a
        query to the desk agents; you never need a command or a hotkey."""
        self.action_tab("book")
        try:
            self.query_one("#cmdbar", Input).focus()
        except Exception:
            pass

    def action_focus_chat(self) -> None:
        """Click-to-type: clicking the conversation routes here and focuses the chat input."""
        self.action_cmd()

    # ---- command palette + help (discoverability: the Bloomberg command line + HELP) -------
    def action_palette(self) -> None:
        """Open the discoverable command palette (Ctrl-K from anywhere, or ':')."""
        try:
            self.push_screen(PaletteScreen(self._palette_recap), self._palette_done)
        except Exception:
            pass

    def _palette_done(self, result) -> None:
        if not result:
            return
        run, q = result
        if run is None:                                  # no match → send the typed text to the agents
            if q:
                self._ask_agent(q)
                self._palette_recap = f"ask · {q[:22]}"
            return
        verb, arg = run
        if verb == "focus":
            self._set_focus(arg, move_cursor=True); self.action_tab("book"); self._palette_recap = f"focus {arg}"
        elif verb == "tab":
            self.action_tab(arg); self._palette_recap = f"open {arg}"
        elif verb == "council":
            self.action_go_council(); self._palette_recap = f"council {self._focus or ''}".strip()
        elif verb == "bear":
            self._ask_agent(f"bear case on {arg}"); self._palette_recap = f"bear · {arg}"
        elif verb == "scenario":
            self.action_tab("whatif"); self._load_scenario(arg); self._palette_recap = f"scenario {arg}"
        elif verb == "dossier":
            self.action_tab("dossier_tab")
            if arg:
                self._set_focus(arg, move_cursor=True); self._dossier_pick(arg)
            self._palette_recap = f"dossier {arg}"
        elif verb in ("review", "hub"):
            self.action_open_hub(); self._palette_recap = "hub"
        elif verb == "hubclassic":
            self.action_open_hub_classic(); self._palette_recap = "mission control"
        elif verb == "help":
            self.action_help()

    def action_help(self) -> None:
        """The keymap + click-grammar cheat-sheet (Bloomberg HELP), as a pop-over."""
        def keylabel(k):
            return {"left_square_bracket": "[", "right_square_bracket": "]", "equals_sign": "=",
                    "full_stop": ".", "question_mark": "?", "colon": ":", "slash": "/",
                    "backslash": "\\", "minus": "−", "comma": ",", "ctrl+k": "^K"}.get(k, k)
        rows = []
        for b in self.BINDINGS:
            k = b.key if isinstance(b, Binding) else b[0]
            desc = (b.description if isinstance(b, Binding) else b[2]) or ""
            if desc:
                rows.append((keylabel(k), desc))
        half = (len(rows) + 1) // 2
        # '[' is the only markup-opener (neutralize it); the trailing space before [/] keeps a
        # literal '\' from abutting a bracket and breaking the parse.
        def cell(kv):
            key = str(kv[0]).replace("[", r"\[")
            return f"[{GOLD}]{key:>3} [/] [{SILVER}]{kv[1]:<13}[/]"
        body = [f"[bold {AMBER}]KEYS[/]"]
        for i in range(half):
            left = rows[i]
            right = rows[i + half] if i + half < len(rows) else None
            body.append(f"  {cell(left)}   {cell(right) if right else ''}")
        body.append("")
        body.append(f"[bold {AMBER}]CLICK GRAMMAR[/]  [{DIM}](the desk is clickable)[/]")
        for glyph, what in (("a name", "focus it on the Book page"),
                            ("a metric φ/ρ/T/Q/V", "pop its grounded breakdown"),
                            ("‹full debate ⌄›", "expand the inline Council"),
                            ("a desk-tape / memory row", "open its detail"),
                            ("v  ·  Review room", "read & verify memory · results · research · threads"),
                            ("‹✦ new›", "start a fresh research thread")):
            body.append(f"  [{TEAL}]›[/] [{SILVER}]{glyph:<22}[/] [{DIM}]{what}[/]")
        body.append("")
        body.append(f"[{DIM}]Plain text is a question to the agents — no command needed. "
                    f"Ctrl-K opens the command palette; v opens the Review room.[/]")
        try:
            self.push_screen(InspectScreen("KEYS & CLICK GRAMMAR", "\n".join(body),
                                           "[#74747C]‹ Esc or click outside to close[/]"))
        except Exception:
            pass

    # ---- agent hub (mission control: set up agent work — a lens over existing data) ----------
    _AGENT_PROMPT = {
        "conviction-analyst": "@conviction-analyst why is {tk} rated this? Ground in the live engine state.",
        "catalyst-verifier": "@catalyst-verifier are {tk}'s catalysts real and correctly attributed (straight-to-source)?",
        "data-integrity-auditor": "@data-integrity-auditor sweep the book for ticker / company / archetype / alias mis-IDs.",
        "bull": "@bull build the strongest asymmetric bull case for {tk}, grounded in engine ρ / φ / upside.",
        "bear": "@bear build the strongest invalidation case for {tk}; set the hard stop, attack φ/ρ at the base leg.",
        "arbiter": "@arbiter reconcile the bull and bear on {tk} into one verdict.",
        "scout": "scout for overlooked names adjacent to {tk}.",
        "synthesis": "deep dive on {tk} — full structured analysis, valuation what-ifs, regime fit.",
        "verifier": "verify / red-team {tk} — accounting integrity (JSF), catalysts, dilution, regime vulnerability.",
        "calibration": "how are my calls doing? show the expectancy scorecard (Druckenmiller objective).",
    }
    _AGENT_BOOK_LEVEL = {"data-integrity-auditor", "calibration"}
    _HUB_DEFAULT_COMMANDS = {
        "bear": "Red-team {ticker}: valuation, dilution / financing risk, jurisdiction, and the signals that invalidate the bull.",
        "catalysts": "Verify {ticker}'s catalysts straight-to-source (issuer PR / SEDAR+ / EDGAR) — flag stale or misattributed.",
        "floor": "What is {ticker}'s REP floor, and how much margin of safety does the current price give?",
        "peers": "Compare {ticker} to its closest book peer on ρ / φ / upside and regime fit.",
    }

    def action_ops_shell(self) -> None:
        """⌥O — open the ops shell popup (tmux display-popup if inside a tmux session)."""
        import subprocess, os
        repo = os.path.dirname(os.path.abspath(__file__))
        tmux_env = os.environ.get("TMUX")
        if tmux_env:
            subprocess.Popen(
                ["tmux", "display-popup", "-w", "82%", "-h", "70%", "-E", "-d", repo, os.environ.get("SHELL", "/bin/bash")],
                close_fds=True,
            )
        else:
            self._toast("⌥O shell: not inside a tmux session — run via ./cockpit.sh", ORANGE)

    def action_agent_hub(self) -> None:
        """Open the Agent Hub (Ctrl-K → 'agent hub', or 'manage ›' on the agent column header)."""
        try:
            self.push_screen(HubScreen())
        except Exception:
            pass

    def _agent_roster(self):
        """The cockpit's agents (.claude/agents/*.md → name + one-line role). Cached."""
        if getattr(self, "_roster_cache", None) is not None:
            return self._roster_cache
        roster = []
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude", "agents")
        try:
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".md"):
                    continue
                name, desc = fn[:-3], ""
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as fh:
                        head = fh.read(1400)
                    for line in head.splitlines():
                        if line.strip().startswith("description:"):
                            desc = line.split(":", 1)[1].strip()
                            break
                except Exception:
                    pass
                roster.append((name, desc.split(". ")[0][:52]))
        except Exception:
            roster = []
        self._roster_cache = roster
        return roster

    def action_hub_run_agent(self, name: str) -> None:
        if name == "antigravity":                          # the independent red-team — headless via agy
            if not self._focus:
                self._toast("focus a name first", ORANGE); return
            try:
                self.pop_screen()
            except Exception:
                pass
            self.action_ask("bear"); return
        tmpl = self._AGENT_PROMPT.get(name)
        if not tmpl:
            return
        tk = self._focus or ""
        if "{tk}" in tmpl and not tk and name not in self._AGENT_BOOK_LEVEL:
            self._toast("focus a name first", ORANGE); return
        try:
            self.pop_screen()
        except Exception:
            pass
        self._ask_agent(tmpl.replace("{tk}", tk))

    def _hub_commands_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cockpit_commands.json")

    def _user_commands(self) -> dict:
        try:
            with open(self._hub_commands_path(), encoding="utf-8") as fh:
                return {str(k): str(v) for k, v in ((json.load(fh) or {}).get("commands") or {}).items()}
        except Exception:
            return {}

    def _load_commands(self) -> dict:
        cmds = dict(self._HUB_DEFAULT_COMMANDS)
        cmds.update(self._user_commands())                 # user templates override / extend the defaults
        return cmds

    def _hub_save_command(self, line: str) -> None:
        line = (line or "").strip()
        low = line.lower()
        if low.startswith("job ") or low.startswith("job:"):     # 'job <kind> <topic> [@min]' → schedule
            self._hub_add_job(line[4:] if low.startswith("job ") else line[3:])
            return
        if "=" not in line:
            if line:
                self._toast("format: name = prompt with {ticker}  ·  or  job <kind> <topic> [@min]", ORANGE)
            return
        name, tmpl = line.split("=", 1)
        name = "".join(c for c in name.strip() if c.isalnum() or c in "-_")[:24]   # markup-safe id
        tmpl = tmpl.strip()
        if not name or not tmpl:
            return
        user = self._user_commands(); user[name] = tmpl
        try:
            os.makedirs(os.path.dirname(self._hub_commands_path()), exist_ok=True)
            with open(self._hub_commands_path(), "w", encoding="utf-8") as fh:
                json.dump({"commands": user}, fh, indent=2)
            self._toast(f"saved command '{name}'", GREEN)
        except Exception as exc:
            self._toast(f"save failed: {exc}", ORANGE)

    def action_hub_del_command(self, name: str) -> None:
        user = self._user_commands()
        if name in user:
            del user[name]
            try:
                with open(self._hub_commands_path(), "w", encoding="utf-8") as fh:
                    json.dump({"commands": user}, fh, indent=2)
            except Exception:
                pass
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def action_hub_run_command(self, name: str) -> None:
        tmpl = self._load_commands().get(name)
        if not tmpl:
            return
        tk = self._focus or ""
        try:
            self.pop_screen()
        except Exception:
            pass
        self._ask_agent(tmpl.replace("{ticker}", tk).replace("{tk}", tk))

    # ---- the Hub's left control cards (built from app state; rendered by HubScreen.refresh_cards) ----
    _ANTIGRAVITY_DESC = "Independent red-team / bear case — runs headless via the Gemini-backed agy CLI."

    def _hub_roster_status(self, agent_id: str) -> str:
        """Live status for a roster agent: working if it has an in-flight run, scheduled if it owns an
        enabled job, the Sentinel watches, else its default (idle)."""
        if any(j.get("kind") == agent_id and not j.get("cancelled") for j in self._inflight.values()):
            return "working"
        if any((j.get("agent") == agent_id and j.get("enabled")) for j in (self._jobs or [])):
            return "scheduled"
        return _hub_meta(agent_id)[2]

    def _convo_title(self, root: dict) -> str:
        """A short, scannable title for a conversation — the agent-set title if present, else a
        heuristic from the opening message (prefixed with the bound ticker). Chat-app style auto-title
        so the sidebar reads cleanly."""
        if not isinstance(root, dict):
            return "conversation"
        t = str(root.get("title") or "").strip()
        if not t:
            t = _clean_convo_title(str(root.get("text") or "")) or "conversation"
        tk = root.get("ticker")
        if tk and str(tk).lower() not in t.lower():
            t = f"{tk} · {t}"
        return t

    def _hub_convos_markup(self) -> str:
        """The conversations SIDEBAR (chat-app style): '+ New chat', then each conversation newest-
        first, auto-titled, the active one marked. Click a row to open it — a clean linear-chat picker
        in place of the branching-thread list."""
        active_root = self._branch_root(self._active) if self._active else None
        lines = [f"[@click=app.hub_new_chat][bold {TEAL}]+ New chat[/][/]",
                 f"[{BORDER}]{'─' * 24}[/]"]
        roots = sorted(self._roots(),
                       key=lambda r: max((n.get("ts", 0) for n in self._conv.values()
                                          if self._branch_root(n["id"]) == r["id"]),
                                         default=r.get("ts", 0)), reverse=True)
        if not roots:
            lines.append(f"[{DIM}]no conversations yet —[/]")
            lines.append(f"[{DIM}]ask anything below to start[/]")
            return "\n".join(lines)
        for root in roots[:30]:
            rid = root["id"]
            on = (rid == active_root)
            ts = max((n.get("ts", 0) for n in self._conv.values()
                      if self._branch_root(n["id"]) == rid), default=root.get("ts", 0))
            title = self._esc(_clip(self._convo_title(root), 36))
            sty = f"bold {AMBER}" if on else "#C8C8CE"
            lines.append(f"[@click=app.hub_open_convo('{rid}')]{'▸ ' if on else '  '}[{sty}]{title}[/]"
                         f"  [{DIM}]{_rel_age(ts)}[/][/]")
        return "\n".join(lines)

    def action_hub_new_chat(self) -> None:
        """Start a fresh conversation (the sidebar's '+ New chat')."""
        self._active = None
        self._repaint_hub()
        self._toast("✦ new chat — your next message starts fresh", TEAL)

    def action_hub_open_convo(self, rid: str) -> None:
        """Open a conversation from the sidebar — make its latest turn active, restore its research
        frame, and scroll the chat to the newest message."""
        tip = max((n for n in self._conv.values() if self._branch_root(n["id"]) == rid),
                  key=lambda n: n.get("ts", 0), default=None)
        self._active = tip["id"] if tip else None
        try:
            self._restore_thread_frame(rid)
        except Exception:
            pass
        self._repaint_hub()

    def _repaint_hub(self) -> None:
        """Repaint whichever hub is open after a chat nav change, scrolling to the newest turn —
        the Blend chat-home (paint_launch + paint_log) or the classic Hub (refresh_cards + feed)."""
        scr = self.screen
        try:
            if isinstance(scr, BlendHubScreen):
                scr.paint_launch(); scr.paint_log()
                scr.query_one("#blend_logwrap", VerticalScroll).scroll_end(animate=False)
            elif isinstance(scr, HubScreen):
                scr.refresh_cards(); self._render_hub_feed()
                scr.query_one("#hub_feed_scroll", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _retract_flywheel_artifacts(self) -> int:
        """Retract the flywheel's polluted history — every engine-flywheel decision + outcome — so the
        Quest Log clears and the ledger rebuilds clean (the last-good feed + stale-mark guards are in;
        only fresh, verified grades accrue now). Non-destructive: retract leaves an audit tombstone,
        and it's idempotent (already-retracted entries are hidden from the query)."""
        mem = self._memory()
        if mem is None:
            return 0
        n = 0
        for e in (mem.query(type="outcome", limit=0) or []) + (mem.query(type="decision", limit=0) or []):
            if e.get("source") == "engine-flywheel":
                try:
                    mem.retract(e["id"], source="flywheel-cleanup"); n += 1
                except Exception:
                    pass
        return n

    def action_retract_flywheel(self) -> None:
        """One-click cleanup of the flywheel artifacts (the phantom +N%/−N% grades from the bad feed)."""
        n = self._retract_flywheel_artifacts()
        self._toast(f"⌫ retracted {n} flywheel artifact(s) — the ledger rebuilds clean" if n
                    else "no flywheel artifacts to retract", TEAL if n else DIM)
        try:
            self._refresh_hub()
        except Exception:
            pass

    def _chat_markup(self) -> str:
        """The active conversation as a LINEAR chat (Rich markup): you ›/agent ‹ turns, newest at the
        bottom, with a clean empty state. Shared by the Blend chat-home and the classic Hub."""
        e = self._esc
        active_root = self._branch_root(self._active) if self._active else None
        if not (active_root and active_root in self._conv):
            if self._pending_user:
                return "\n".join(self._thinking_lines(self._pending_user))
            return (f"[bold {GOLD}]Start a conversation[/]\n\n"
                    f"[{DIM}]Type below — plain English, @agent, or a command. "
                    f"Pick a past chat on the left, or just start typing.[/]")
        root = self._conv[active_root]
        lines = [f"[{AMBER}]▣[/] [bold white]{e(_clip(self._convo_title(root), 60))}[/]", ""]
        nodes = sorted((n for n in self._conv.values()
                        if self._branch_root(n["id"]) == active_root), key=lambda n: n.get("ts", 0))
        for m in nodes:
            if m.get("role") == "you":
                lines.append(f"[bold {TEAL}]you ›[/]  [{SILVER}]{e(str(m.get('text', '')))}[/]")
            else:
                lines.append(f"[bold {GREEN}]{e(m.get('agent') or 'claude')} ‹[/]  "
                             f"[#C8C8CE]{e(str(m.get('text', '')))}[/]")
            lines.append("")
        if self._pending_user and self._branch_root(self._pending_user) == active_root:
            lines.extend(self._thinking_lines(self._pending_user))
        return "\n".join(lines)

    def _card_roster_markup(self) -> str:
        """TEAM — the roster, grouped by FUNCTION in a COLLAPSIBLE sidebar (click a group header to
        fold/unfold it — keeps the column uncluttered). Each agent is a compact one-line row: status
        dot · name · runtime-lane chip · ▶ run · ⏱ assign; click the name to inspect it (role + detail
        live in the FOCUS inspector). Each row shows the agent's model (◇) + runtime lane (▪)."""
        if isinstance(self.screen, HubScreen) and getattr(self.screen, "_left", "chats") == "chats":
            return self._hub_convos_markup()            # colA is the conversations sidebar by default
        e = self._esc
        self._load_jobs()                                   # ensure self._jobs is populated for status
        extras = [nm for nm, _ in self._agent_roster() if nm not in HUB_AGENT_META]   # forward-compat
        n = len(HUB_AGENT_META) + len(extras)
        collapsed = self.screen._collapsed_groups if isinstance(self.screen, HubScreen) else set()
        lines = [f"[{AMBER}]Roster[/]  [{DIM}]{n} agents · claude + gemini[/]"]
        # agents grouped by function (sentinel · council · research · audit · independent)
        for gid, gtitle, gnote in HUB_GROUPS:
            members = [a for a in HUB_AGENT_META if _hub_meta(a)[0] == gid]
            if gid == "audit":
                members += extras                           # any new .claude/agents land in Audit
            if not members:
                continue
            folded = gid in collapsed
            caret = "▸" if folded else "▾"
            lines.append(f"[@click=app.hub_toggle_group('{gid}')][{DIM}]{caret}[/] [bold #8C8C92]{gtitle}[/] "
                         f"[{DIM}]· {len(members)}[/][/]")
            if folded:
                continue
            for name in members:
                _g, lane, _st, _can = _hub_meta(name)
                status = self._hub_roster_status(name)
                sel = (self.screen._insp_agent == name and self.screen._insp_task is None) if isinstance(self.screen, HubScreen) else False
                nm_style = f"bold {AMBER}" if sel else "bold #FFFFFF"
                bl = f" [{DIM}]·bk[/]" if name in self._AGENT_BOOK_LEVEL else ""
                tag = HUB_AGENT_DOC.get(name, {}).get("tag", "")
                tag_frag = f"  [{FAINT}]{self._esc(tag[:30])}[/]" if tag else ""
                lines.append(
                    f"  {_status_dot(status)} [@click=app.hub_inspect_agent('{name}')][{nm_style}]{e(name)}[/][/] "
                    f"{_model_chip(name)} {_lane_chip(lane)}{bl}"
                    f"  [@click=app.hub_run_agent('{name}')][{GREEN}]▶[/][/]"
                    f" [@click=app.hub_assign('{name}')][{AMBER}]⏱[/][/]{tag_frag}")
        pane_chips = []
        for label, kw in (("claude", "CLAUDE"), ("agy", "ANTIGRAVITY"), ("ops", "OPERATOR")):
            live = bool(self._find_pane(kw))
            pane_chips.append(f"[{GREEN if live else DIM}]{'●' if live else '○'} {label}[/]")
        lines.append(f"[{DIM}]panes:[/] " + "  ".join(pane_chips))
        return "\n".join(lines)

    def _card_recurring_markup(self) -> str:
        if isinstance(self.screen, HubScreen) and getattr(self.screen, "_left", "chats") == "chats":
            return ""                                    # hidden while colA is the chat sidebar (press t)
        e = self._esc
        try:
            import cockpit_scheduler as sched
            jobs = self._load_jobs()
        except Exception:
            sched, jobs = None, []
        enabled = sum(1 for j in jobs if j.get("enabled"))
        lines = [f"[{AMBER}]⏲[/] [bold #8C8C92]SCHEDULED[/]  [bold {GOLD}]{enabled}[/]  [{DIM}]recurring · dial: {self._autonomy}[/]"]
        for j in jobs:
            jid = e(str(j.get("id", ""))); en = j.get("enabled"); nd = j.get("next_due"); when = ""
            if nd:
                mins = max(0, int((nd - time.time()) / 60))
                when = f"· in {mins}m" if mins < 90 else (f"· in {mins // 60}h" if mins < 2880 else f"· in {mins // 1440}d")
            dot = f"[{GREEN if en else DIM}]{'●' if en else '○'}[/]"
            who = f" [{TEAL}]by {e(j['agent'])}[/]" if j.get("agent") else ""
            lines.append(f"  {dot} [@click=app.job_run_now('{jid}')][{TEAL}]▶[/][/] "
                         f"[{SILVER if en else DIM}]{e(_clip(j.get('label', ''), 22))}[/]{who} [{DIM}]{j.get('every_min')}m {when}[/]"
                         f"  [@click=app.job_toggle('{jid}')][{DIM}]{'pause' if en else 'on'}[/][/]"
                         f" [@click=app.job_del('{jid}')][{DIM}]✕[/][/]")
        if not jobs:
            lines.append(f"  [{DIM}]none — e.g.[/] [{TEAL}]job scout silver @1440[/] [{DIM}]or[/] [{TEAL}]job bear AGA.V[/]")
            lines.append(f"  [{DIM}]assign an agent: ⏱ on the roster, or add[/] [{SILVER}]by <agent>[/]")
        return "\n".join(lines)

    def _card_commands_markup(self) -> str:
        e = self._esc
        user = self._user_commands()
        lines = [f"[bold #8C8C92]COMMANDS[/]  [{DIM}]{{ticker}} → focus[/]"]
        for name, tmpl in self._load_commands().items():
            row = (f"  [@click=app.hub_run_command('{e(name)}')][{TEAL}]›[/] [{SILVER}]{e(name)[:12].ljust(12)}[/][/] "
                   f"[{DIM}]{e(_clip(str(tmpl), 40))}[/]")
            if name in user:
                row += f"  [@click=app.hub_del_command('{e(name)}')][{DIM}]✕[/][/]"
            lines.append(row)
        return "\n".join(lines)

    def _card_audit_markup(self) -> str:
        """ENGINE AUDIT — the fetch · verify · review council over the engine itself (the numbers that
        feed it, the thresholds, the valuation formulas). Run on demand or schedule `job audit …`."""
        if isinstance(self.screen, HubScreen) and getattr(self.screen, "_left", "chats") == "chats":
            return ""                                    # hidden while colA is the chat sidebar (press t)
        import glob as _glob
        e = self._esc
        lines = [f"[bold #8C8C92]ENGINE AUDIT[/]  [{DIM}]fetch · verify · review[/]",
                 f"  [@click=app.run_audit][{GOLD}]▶ run audit[/][/] [{DIM}]inputs · thresholds · formulas[/]"]
        files = sorted(_glob.glob(os.path.join(self._drafts_dir(), "audit_*.md")), reverse=True)
        if files:
            lines.append(f"  [{DIM}]last:[/] [@click=app.review_cat('result')][{TEAL}]{e(_clip(self._file_title(files[0]), 28))}[/][/]")
        else:
            lines.append(f"  [{DIM}]evaluates the data, thresholds & valuation formulas → a methodology report[/]")
        return "\n".join(lines)

    def action_run_audit(self) -> None:
        """Launch the engine-audit council now (fetch the inputs/thresholds/formulas, verify, review)."""
        try:
            import cockpit_scheduler as sched
            self._launch_job(sched.new_job("audit", "inputs · thresholds · valuation formulas"))
            self._toast("⏱ engine audit running — fetch · verify · review", TEAL)
        except Exception as exc:
            self._toast(f"audit failed to launch: {exc}", ORANGE)
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    # ======================================================================================
    # The Agent Hub — WORK column (delegate composer + board) & FOCUS column (inspector)
    # handoff: docs/archive/design_handoff_agent_hub. The fleet is uniformly Opus 4.8 — the chip
    # carries the runtime LANE, not the model; the autonomy boundary is concrete (alerts fire,
    # trims/exits/swaps are proposed). Every surface binds to live state / the Forge modules.
    # ======================================================================================
    def _hub_compose_lab_markup(self) -> str:
        return (f"[{AMBER}]Delegate a task[/]  [{DIM}]say it in plain words — it routes to the right agent and "
                f"hands over your whole request · ⏎ to send · a bare ticker sets the subject[/]")

    def _hub_composer_markup(self) -> str:
        """The composer line — agent · do-what · subject · when — then the Go button, whose label
        follows the verb/when (Delegate ⏎ / Schedule ⏲ / Arm rule ⏎ / File claim ⏎). Click a field's
        ▾ to cycle it. claim/rule hide 'when' (they file to the Ledger, not the scheduler)."""
        e = self._esc
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return ""
        a = scr._c_agent; verb = scr._c_verb; subj = (scr._c_subject or "").strip(); when = scr._c_when
        _g, lane, _st, _can = _hub_meta(a)
        ledger = verb in HUB_LEDGER_VERBS
        ready = bool(a and subj and subj != "—")
        fields = [f"[{DIM}]agent[/] [@click=app.hub_cycle('agent')][bold {SILVER}]{e(a)}[/] {_lane_chip(lane)} [{DIM}]▾[/][/]",
                  f"[{DIM}]do[/] [@click=app.hub_cycle('verb')][{GOLD}]{e(verb)}[/] [{DIM}]▾[/][/]",
                  f"[{DIM}]subject[/] [@click=app.hub_cycle('subject')][{AMBER}]{e(subj or '—')}[/] [{DIM}]▾[/][/]"]
        if not ledger:
            fields.append(f"[{DIM}]when[/] [@click=app.hub_cycle('when')][{SILVER}]{when}[/] [{DIM}]▾[/][/]")
        line = f"  [{FAINT}]·[/]  ".join(fields)
        if ledger:
            label = "Arm rule ⏎" if verb == "rule" else "File claim ⏎"; note = "files to the Thesis Ledger · validated at save"
        elif when == "schedule":
            label = "Schedule ⏲"; note = f"runs respect autonomy: {self._autonomy}"
        else:
            label = "Delegate ⏎"; note = f"runs on {_agent_model(a)[1]} · you'll be notified"
        go = (f"[@click=app.hub_go][bold {AMBER_BRIGHT} on #141418] {label} [/][/]" if ready
              else f"[{DIM}] {label} [/]")
        # ＋ step — add this (agent + instruction) to the Workflow chain instead of firing it now
        step = (f"[@click=app.hub_wf_add][{TEAL}]＋ step[/][/]" if (a and not ledger)
                else f"[{DIM}]＋ step[/]")
        # disconfirm-by-default — composing an advocate auto-offers a one-click red-team foil leg, so a
        # long case never ships without its pre-mortem (@antigravity if available, else @bear).
        disc = ""
        if a in self._ADVOCATE_AGENTS and not ledger:
            foil = "antigravity" if self._has_gemini() else "bear"
            disc = f"    [@click=app.hub_wf_disconfirm][{ORANGE}]↳ disconfirm (@{foil})[/][/]"
        return f"{line}\n  [{DIM}]{note}[/]   {go}    [{DIM}]or chain it →[/] {step}{disc}"

    def _hub_calendar_windows(self, n: int = 3) -> list:
        """Up to n upcoming catalyst windows for the header strip → (ticker, event, 'in Nd', is_macro).
        Grounded-or-silent: empty when the calendar module/data is unavailable (never invented)."""
        cal = self._calendar()
        if cal is None:
            return []
        try:
            import catalyst_calendar as cc
            from datetime import datetime, timezone
            rows = [r for r in (cal.query(within_days=120) or []) if r.get("window_start")]
            rows.sort(key=lambda r: str(r.get("window_start")))
            now = datetime.now(timezone.utc)
            out = []
            for r in rows[:n]:
                tk = r.get("ticker") or "macro"
                ev = r.get("title") or r.get("kind") or "event"
                macro = (str(r.get("kind")) == "macro") or not r.get("ticker")
                din = "soon"
                d = cc._parse(r.get("window_start"))
                if d is not None:
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    din = f"in {max(0, (d - now).days)}d"
                out.append((str(tk), _clip(str(ev), 14), din, macro))
            return out
        except Exception:
            return []

    def _hub_status_counts(self):
        """(awaiting, working, scheduled) for the header pips — all from live state."""
        awaiting = len(self._pending or []) + len(self._job_proposals or []) + len(self._watch_proposals or [])
        pipe = (self._state or {}).get("pipeline") or {}
        working = (sum(1 for j in self._inflight.values() if not j.get("cancelled"))
                   + (1 if (self._pipe_is_live(pipe) and not self._pipe_is_echo(pipe)) else 0)
                   + (1 if self._wf_running else 0))
        scheduled = sum(1 for j in (self._load_jobs() or []) if j.get("enabled"))
        return awaiting, working, scheduled

    def _hub_done_markup(self) -> str:
        """✓ Done today — finished agent runs & research as READABLE cards: agent → subject + a one-line
        result, click to open the full output in the FOCUS reader (a Book thread or a saved draft)."""
        e = self._esc
        runs = list(self._done_runs or [])[:6]
        lines = [f"[{GREEN}]✓[/] [bold #8C8C92]DONE TODAY[/]  [bold {GOLD}]{len(self._done_runs or [])}[/]  "
                 f"[{DIM}]finished work · click to read[/]"]
        if not runs:
            lines.append(f"  [{DIM}]nothing yet — delegated & scheduled runs land here when they finish[/]")
        for r in runs:
            rid = r.get("id")
            click = f"@click=app.hub_open_done('{rid}')"
            glyph = "↯" if r.get("cat") == "thread" else "✎"
            lines.append(f"  [{GREEN}]{glyph}[/] [{click}][bold {SILVER}]{e(r.get('agent', ''))}[/] "
                         f"[{DIM}]→[/] [{AMBER}]{e(_clip(r.get('subject', '—'), 12))}[/][/] "
                         f"[{DIM}]· {_rel_age(r.get('ts'))}[/]")
            if r.get("summary"):
                lines.append(f"     [{click}][{DIM}]{e(_clip(r.get('summary', ''), 52))}[/][/]")
        return "\n".join(lines)

    def action_hub_open_done(self, run_id) -> None:
        """Open a finished run's full output in the FOCUS reader (the board → read flow)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        run = next((r for r in (self._done_runs or []) if str(r.get("id")) == str(run_id)), None)
        if not run:
            return
        scr.open_ref(run.get("cat", "thread"), run.get("ref"))

    # ======================================================================================
    # Hub research feed — unified chronological thread / proposal / working view
    # ======================================================================================

    def _thread_tail(self, root_id: str) -> str:
        """Latest node in a thread (deepest by timestamp) — correct parent for a follow-up."""
        nodes = [n for n in self._conv.values() if self._branch_root(n["id"]) == root_id]
        if not nodes:
            return root_id
        return max(nodes, key=lambda n: n.get("ts", 0))["id"]

    def _render_hub_compose_ctx(self) -> None:
        """Render (or clear) the context bar above the Hub input."""
        try:
            box = self.screen.query_one("#hub_compose_ctx", Static)
        except Exception:
            return
        ctx = self._hub_compose_ctx
        if not ctx:
            box.update("")
            return
        tk = ctx.get("ticker", "")
        summary = _clip(ctx.get("summary", ""), 42)
        line = Text("↩ re: ", style=TEAL)
        if tk:
            line.append(f"{tk} · ", style=f"bold {AMBER}")
        line.append(summary, style=DIM)
        line.append("   ✕ clear", style=Style.parse(DIM) + Style(meta={"@click": "app.hub_ctx_clear()"}))
        box.update(line)

    def action_hub_ctx(self, uid: str) -> None:
        """Load a thread root as follow-up context — opens Hub, shows context bar, focuses input."""
        root_node = self._conv.get(uid) or {}
        self._hub_compose_ctx = {
            "root": uid,
            "tail": self._thread_tail(uid),
            "summary": _clip(str(root_node.get("text", "")), 42),
            "ticker": root_node.get("ticker", ""),
        }
        if not isinstance(self.screen, HubScreen):
            self.action_open_hub()
        else:
            self._render_hub_compose_ctx()
            try:
                self.screen.query_one("#hub_input", Input).focus()
            except Exception:
                pass

    def action_hub_ctx_clear(self) -> None:
        """Clear the Hub compose context."""
        self._hub_compose_ctx = None
        self._render_hub_compose_ctx()

    def action_hub_expand(self, uid: str) -> None:
        """Toggle expand/collapse of a thread card in the Hub feed."""
        if uid in self._hub_expanded:
            self._hub_expanded.discard(uid)
        else:
            self._hub_expanded.add(uid)
        self._render_hub_feed()

    def action_hub_save_thread(self, uid: str) -> None:
        """Save a thread from the Hub feed to a dossier."""
        self._active = self._thread_tail(uid)
        self.action_save_thread()

    def _render_hub_feed(self) -> None:
        """Unified chronological research feed: working → proposals → threads + done runs."""
        try:
            box = self.screen.query_one("#hub_feed", Static)
        except Exception:
            return
        e = self._esc
        parts: list = []
        now = time.time()

        # ── 1. WORKING — pinned at top ────────────────────────────────────
        live = [(jid, j) for jid, j in self._inflight.items() if not j.get("cancelled")]
        pipe = (self._state or {}).get("pipeline") or {}
        pipe_running = pipe.get("status") == "running"
        if live or pipe_running:
            hd = Text("⟳ ", style=GREEN); hd.append("WORKING", style="bold #8C8C92")
            hd.append(f"  {len(live) + (1 if pipe_running else 0)}", style=f"bold {GOLD}")
            parts.append(hd)
        for jid, j in live:
            el = max(0, int(now - j.get("started", now)))
            who, task = self._task_label(j)
            line = Text("  ⟳ ", style=TEAL)
            line.append(f"{who} ", style=f"bold {AMBER}")
            line.append(_clip(task, 36), style=SILVER)
            if j.get("ticker") and j["ticker"].lower() not in task.lower():
                line.append(f"  {j['ticker']}", style=AMBER)
            line.append(f"   {el}s  ", style=DIM)
            line.append("▸ monitor", style=Style.parse(TEAL) + Style(meta={"@click": f"app.hub_inspect_task('{jid}')"}))
            line.append("  ✗", style=Style.parse(ORANGE) + Style(meta={"@click": f"app.cancel_job('{jid}')"}))
            parts.append(line)
        if pipe_running:
            line = Text("  ⟳ pipeline ", style=TEAL)
            line.append(_clip(pipe.get("theme", ""), 18), style=SILVER)
            if pipe.get("stage"):
                line.append(f" · {pipe.get('stage')}", style=DIM)
            parts.append(line)

        # ── 2. PROPOSALS — urgent, near top ──────────────────────────────
        all_props = (list(self._pending or [])[:4] + list(self._watch_proposals or [])[:4]
                     + list(self._job_proposals or [])[:4])
        if all_props:
            ph = Text("⚑ ", style=AMBER); ph.append("PROPOSALS", style="bold #8C8C92")
            ph.append(f"  {len(list(self._pending or [])) + len(list(self._watch_proposals or [])) + len(list(self._job_proposals or []))}", style=f"bold {GOLD}")
            parts.append(ph)
        for p in (self._pending or [])[:4]:
            pid = p.get("id", "")
            line = Text("  ⚑ ", style=AMBER)
            line.append(_clip(_prop_label(p), 38), style=SILVER)
            line.append("  ")
            line.append(" ✓ ", style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.do_confirm('{pid}')"}))
            line.append(" ✕ skip ", style=Style.parse(f"{DIM} on #141418") + Style(meta={"@click": f"app.do_reject('{pid}')"}))
            line.append(" ? why ", style=Style.parse(f"{TEAL} on #141418") + Style(meta={"@click": f"app.explain('{p.get('param', '')}')"}))
            parts.append(line)
        for p in (self._job_proposals or [])[:4]:      # due scheduled jobs awaiting the human ✓
            jid2 = p.get("job_id", "")
            line = Text("  ⚑ ", style=AMBER)
            line.append("due: ", style=DIM)
            line.append(_clip(str(p.get("label") or "scheduled job"), 34), style=SILVER)
            line.append("  ")
            line.append(" ▶ run ", style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.job_run('{jid2}')"}))
            line.append(" ✕ skip ", style=Style.parse(f"{DIM} on #141418") + Style(meta={"@click": f"app.job_skip('{jid2}')"}))
            parts.append(line)
        for p in (self._watch_proposals or [])[:4]:
            tk2 = p.get("ticker", "?")
            src = str(p.get("source") or p.get("note") or "")[:20]
            line = Text("  ⚑ ", style=AMBER)
            line.append(f"add {tk2} to bench?", style=SILVER)
            if src:
                line.append(f"  {src}", style=DIM)
            line.append("  ")
            line.append(" ✓ add ", style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.watch_approve('{tk2}')"}))
            line.append(" ✗ skip ", style=Style.parse(f"{RED} on #141418") + Style(meta={"@click": f"app.watch_deny('{tk2}')"}))
            parts.append(line)

        # ── 2b. RECEIPTS — what just changed, with one-click undo (reversibility) ──
        for r_ in (self._receipts or [])[-3:]:
            line = Text("  ", style=DIM)
            line.append("RECEIPTS " if r_ is (self._receipts or [])[-3:][0] else "         ", style="bold #8C8C92")
            line.append(f"{r_['glyph']} ", style=r_["color"])
            line.append(_clip(str(r_["text"]), 44), style=SILVER)
            if r_.get("undo"):
                line.append("  ")
                line.append("↶ undo", style=Style.parse(GOLD) + Style(meta={"@click": f"app.undo_receipt('{r_['id']}')"}))
            parts.append(line)

        # ── 3. THE ACTIVE CONVERSATION — one linear chat; the sidebar switches which one ──
        if parts:
            parts.append(Text(""))                       # spacer below the attention strip
        active_root = self._branch_root(self._active) if self._active else None
        if active_root and active_root in self._conv:
            root = self._conv[active_root]
            th = Text("▣ ", style=AMBER)
            th.append(_clip(self._convo_title(root), 56), style="bold white")
            parts.append(th)
            nodes = sorted((n for n in self._conv.values()
                            if self._branch_root(n["id"]) == active_root),
                           key=lambda n: n.get("ts", 0))
            for m in nodes:
                parts.append(Text(""))
                if m.get("role") == "you":
                    line = Text("you ", style=f"bold {TEAL}"); line.append("›  ", style=DIM)
                    line.append(e(str(m.get("text", ""))), style=SILVER)
                else:
                    line = Text(f"{m.get('agent') or 'claude'} ", style=f"bold {GREEN}")
                    line.append("‹  ", style=DIM)
                    line.append(e(str(m.get("text", ""))), style="#C8C8CE")
                parts.append(line)
            if self._pending_user and self._branch_root(self._pending_user) == active_root:
                for tl in self._thinking_lines(self._pending_user):
                    parts.append(Text.from_markup(tl) if isinstance(tl, str) else tl)
        elif self._pending_user:
            for tl in self._thinking_lines(self._pending_user):
                parts.append(Text.from_markup(tl) if isinstance(tl, str) else tl)
        else:
            empty = Text("Start a conversation\n\n", style=f"bold {GOLD}")
            empty.append("Ask anything below — plain English, @agent, or a command. "
                         "Pick a past chat on the left, or just start typing.", style=DIM)
            parts.append(empty)

        box.update(Group(*parts))

    # ======================================================================================
    # Workflows — composable agent CHAINS. A workflow is a list of stages; each stage is one or
    # more agents (>1 = a parallel fan-out) + an instruction. Each stage's OUTPUT is handed to the
    # next as context, so the team works as a line — scout → [value ∥ balance-sheet] → verifier →
    # package — and you get one assembled dossier on the Results board. (No bubbles.)
    # ======================================================================================
    def _workflows_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cockpit_workflows.json")

    def _load_workflows(self) -> dict:
        if self._workflows is None:
            try:
                with open(self._workflows_path(), encoding="utf-8") as fh:
                    self._workflows = {str(k): v for k, v in ((json.load(fh) or {}).get("workflows") or {}).items()}
            except Exception:
                self._workflows = {}
        return self._workflows

    def _save_workflows(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._workflows_path()), exist_ok=True)
            with open(self._workflows_path(), "w", encoding="utf-8") as fh:
                json.dump({"workflows": self._workflows or {}}, fh, indent=2)
        except Exception as exc:
            self._toast(f"save failed: {exc}", ORANGE)

    @staticmethod
    def _wf_stage_label(step: dict) -> str:
        label = " ∥ ".join(step.get("agents", []) or ["?"])
        return f"⟜ {label}" if step.get("gate") else label   # ⟜ marks a gated (conditional) stage

    def _hub_workflow_markup(self) -> str:
        """⛓ WORKFLOW — the chain being composed (or running): each stage = agent(s) + instruction;
        outputs flow stage→stage; the last stage is packaged to the Results board."""
        e = self._esc
        steps = self._workflow or []
        running = self._wf_running
        n = len(steps)
        head = (f"[{TEAL}]⛓[/] [bold #8C8C92]WORKFLOW[/]  [bold {GOLD}]{n}[/]  "
                f"[{DIM}]{'running…' if running else 'chain · outputs flow stage→stage → packaged'}[/]")
        lines = [head]
        if not steps:
            lines.append(f"  [{DIM}]Build a chain: set agent + a plain-language instruction below, then[/] "
                         f"[{TEAL}]＋ step[/][{DIM}].  e.g. scout (fit) → value ∥ balance-sheet → verifier.[/]")
        for i, st in enumerate(steps):
            par = len(st.get("agents", [])) > 1
            agents = "  ∥  ".join(f"[{AMBER}]{e(x)}[/]" for x in st.get("agents", []))
            arrow = f"  [{DIM}]↓ passes output to[/]" if i < n - 1 else f"  [{DIM}]↓ packaged → Results board[/]"
            ctl = "" if running else (f"   [@click=app.hub_wf_merge('{i}')][{TEAL}]∥+agent[/][/] "
                                      f"[@click=app.hub_wf_del('{i}')][{DIM}]✕[/][/]")
            lines.append(f"  [{GOLD}]{i + 1}.[/] {agents}{'  [{}]∥ parallel[/]'.format(TEAL) if par else ''}{ctl}")
            if st.get("note"):
                lines.append(f"      [{SILVER}]{e(_clip(st['note'], 60))}[/]")
            lines.append(arrow)
        # action row + saved workflows
        if steps and not running:
            run = f"[@click=app.hub_wf_run][bold {AMBER_BRIGHT} on #141418] ▶ Run workflow [/][/]"
            lines.append(f"  {run}   [@click=app.hub_wf_save][{TEAL}]⊹ save…[/][/]   "
                         f"[@click=app.hub_wf_clear][{DIM}]✕ clear[/][/]")
        saved = self._load_workflows()
        if saved and not running:
            row = f"  [{DIM}]load:[/] " + "  ".join(
                f"[@click=app.hub_wf_load('{e(nm)}')][{TEAL}]▸ {e(nm)}[/][/]" for nm in list(saved)[:5])
            lines.append(row)
        return "\n".join(lines)

    def _paint_workflow(self) -> None:
        if isinstance(self.screen, HubScreen):
            try:
                self.screen.query_one("#hub_workflow", Static).update(self._hub_workflow_markup())
            except Exception:
                pass

    def action_hub_wf_add(self) -> None:
        """Append the current composer (agent + instruction) as a new workflow stage."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        note = ""
        try:
            note = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        note = note or f"{scr._c_verb} {scr._c_subject}".strip()
        self._workflow.append({"agents": [scr._c_agent], "note": note})
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        self._paint_workflow()
        self._toast(f"added step {len(self._workflow)}: {scr._c_agent} — set the next one, or ▶ Run", TEAL)

    def action_hub_wf_disconfirm(self) -> None:
        """Disconfirm-by-default: chain a red-team foil (@bear, or @antigravity when available) after the
        composed advocate ask — the one-keystroke pre-mortem. Builds the 2-stage chain <advocate> →
        <foil: 'what would have to be true for this to be WRONG?'> and leaves it ready to Run, so a long
        case never ships without its disconfirmation (the dissent lands on the same thread as a caveat)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        a = scr._c_agent
        if a not in self._ADVOCATE_AGENTS:
            self._toast("disconfirm chains after an advocate (bull · synthesis · value · balance-sheet)", ORANGE)
            return
        note = ""
        try:
            note = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        note = note or f"{scr._c_verb} {scr._c_subject}".strip()
        foil = "antigravity" if self._has_gemini() else "bear"
        # don't double-stage the advocate if the operator already added it via ＋ step
        if not self._workflow or self._workflow[-1].get("agents") != [a]:
            self._workflow.append({"agents": [a], "note": note})
        self._workflow.append({"agents": [foil],
                               "note": ("DISCONFIRM the case above — what would have to be true for this "
                                        "thesis to be WRONG? Attack the base leg (φ/ρ), name the hard "
                                        "invalidation level, and flag dilution / liquidity / exit friction.")})
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        self._paint_workflow()
        self._toast(f"chained {a} → {foil} (disconfirm) — ▶ Run for the case + its pre-mortem", TEAL)

    def action_hub_wf_merge(self, idx) -> None:
        """Add the current composer agent to stage idx — making it a PARALLEL fan-out (same input,
        several agents at once)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        try:
            st = self._workflow[int(idx)]
        except Exception:
            return
        if scr._c_agent not in st["agents"]:
            st["agents"].append(scr._c_agent)
        self._paint_workflow()
        self._toast(f"stage {int(idx) + 1} now runs {' ∥ '.join(st['agents'])} in parallel", TEAL)

    def action_hub_wf_del(self, idx) -> None:
        try:
            self._workflow.pop(int(idx))
        except Exception:
            return
        self._paint_workflow()

    def action_hub_wf_clear(self) -> None:
        self._workflow = []
        self._paint_workflow()

    def action_hub_wf_save(self) -> None:
        """Save the current chain as a named workflow (name comes from the NL line, else auto)."""
        scr = self.screen
        if not isinstance(scr, HubScreen) or not self._workflow:
            return
        name = ""
        try:
            name = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        name = "".join(c for c in name if c.isalnum() or c in " -_").strip()[:32] or f"workflow-{len(self._load_workflows()) + 1}"
        self._load_workflows()[name] = [dict(s) for s in self._workflow]
        self._save_workflows()
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        self._paint_workflow()
        self._toast(f"saved workflow '{name}'", GREEN)

    def action_hub_wf_load(self, name: str) -> None:
        wf = self._load_workflows().get(name)
        if not wf:
            return
        self._workflow = [dict(s) for s in wf]
        self._paint_workflow()
        self._toast(f"loaded '{name}' — edit it, or ▶ Run workflow", TEAL)

    def action_hub_wf_run(self) -> None:
        """Run the composed chain headless (stages in order; parallel agents within a stage; outputs
        flow forward; the result is packaged to the Results board)."""
        if self._wf_running:
            self._toast("a workflow is already running", ORANGE); return
        if not self._workflow:
            self._toast("build a chain first (＋ step)", ORANGE); return
        scr = self.screen
        subject = (scr._c_subject if isinstance(scr, HubScreen) else None) or "book"
        steps = [dict(s) for s in self._workflow]
        self._last_wf_steps = [dict(s) for s in steps]
        self._wf_ctl = {"pause": False, "stop": False}
        self._wf_stage_idx = 0
        self._wf_subject = subject
        self._wf_running = True
        self._paint_workflow()
        self._toast(f"▶ workflow running ({len(steps)} stages) — watch Working; the package lands on the board", GREEN)
        self._run_workflow_bg(steps, subject)

    @work(thread=True, group="workflow", exclusive=True)
    def _run_workflow_bg(self, steps: list, subject: str) -> None:
        """Execute the chain. Each stage's agents run via the configured CLI; their output is appended
        to a running context handed to the next stage. A final package (every stage's output) is saved
        as a Result draft and surfaced on the board."""
        import concurrent.futures as _cf
        _post("/pipeline/event", {"status": "running", "stage": self._wf_stage_label(steps[0]),
                                  "theme": subject, "message": f"workflow · {len(steps)} stages"})
        context = ""                                        # accumulated prior-stage output (the flow)
        transcript = []
        for si, st in enumerate(steps):
            # ── chain controls (the Pipeline surface's ⏸ / ⏹) — honored at stage boundaries,
            #    because a seat mid-thought can't be frozen honestly ──
            while self._wf_ctl.get("pause") and not self._wf_ctl.get("stop"):
                time.sleep(1.0)
            if self._wf_ctl.get("stop"):
                _post("/pipeline/event", {"status": "running", "stage": self._wf_stage_label(st),
                                          "message": f"stopped before stage {si + 1}"})
                break
            # ── conditional choreography (H2): a stage can carry a GATE that's checked against the
            #    prior stages' output. A failed gate ABORTS the chain early (cheap) and writes WHY to
            #    Living Memory — the pipeline becomes a decision tree, not a fixed escalator. ──
            gate = st.get("gate")
            if gate:
                passed, why = _eval_workflow_gate(gate, context)
                if not passed:
                    label = self._wf_stage_label(st)
                    _post("/pipeline/event", {"status": "done", "stage": "halted",
                                              "message": f"gate failed before {label}: {why}",
                                              "result": (context[-3500:] if context else "")})
                    self._workflow_halt_note(subject, si + 1, label, why, gate)
                    transcript.append((si + 1, label, f"GATE HALT — {why}", []))
                    break
            self._wf_stage_idx = si                         # the Pipeline view reads this live
            agents = st.get("agents", []) or ["scout"]
            note = st.get("note", "") or "proceed"
            _post("/pipeline/event", {"status": "running", "stage": self._wf_stage_label(st),
                                      "message": f"stage {si + 1}/{len(steps)}"})

            def _run_one(agent):
                prov = self._agent_provider(agent)           # route each stage to its provider's CLI
                jid = None
                try:
                    jid = self.call_from_thread(self._inflight_add, agent, note, subject, agent, prov)
                except Exception:
                    pass
                prior = (f"\n\n--- Prior stage output to build on (do not repeat it; advance it) ---\n{context}"
                         if context.strip() else "")
                if prov == "gemini":
                    argv = self._agy_argv(self._gemini_prompt(agent, note + prior, subject))
                else:
                    argv = self._pipeline_argv(f"@{agent} {note}\n\nSubject / book context: {subject}.{prior}",
                                               agent=agent)
                try:
                    out = subprocess.run(argv, capture_output=True, text=True,
                                         timeout=int(os.environ.get("CEX_PIPELINE_TIMEOUT", "900")),
                                         cwd=os.path.dirname(os.path.abspath(__file__)))
                    res = (out.stdout or "").strip() or (out.stderr or "").strip()
                except Exception as exc:
                    res = f"(stage error: {exc})"
                if jid is not None:
                    try:
                        self.call_from_thread(self._inflight_done, jid)
                    except Exception:
                        pass
                return agent, (res or "(no output — check the agent CLI permission flags)")

            results = []
            if len(agents) > 1:                             # parallel fan-out
                with _cf.ThreadPoolExecutor(max_workers=min(4, len(agents))) as ex:
                    results = list(ex.map(_run_one, agents))
            else:
                results = [_run_one(agents[0])]

            stage_block = "\n\n".join(f"### {ag} — {note}\n{txt}" for ag, txt in results)
            transcript.append((si + 1, self._wf_stage_label(st), note, results))
            context = (context + "\n\n" + stage_block).strip()   # flows into the next stage

        path = self._save_workflow_package(subject, steps, transcript)
        _post("/pipeline/event", {"status": "done", "stage": "package", "message": "workflow complete",
                                  "result": (context[-3500:] if context else "")})
        # a matchup/bench run carries per-contender SCORE lines — parse them back into the grid
        if " vs " in str(subject).lower():
            self._matchup_results[str(subject)] = {
                "scores": self._parse_matchup_scores(context),
                "verdict": (context or "").strip(), "ref": path}
        self.call_from_thread(self._record_done_run, "workflow", subject,
                              f"{len(steps)}-stage chain → packaged", "result", path)
        self.call_from_thread(self._wf_finish)

    def _wf_finish(self) -> None:
        stopped = self._wf_ctl.get("stop")
        self._wf_running = False
        self._wf_ctl = {"pause": False, "stop": False}
        self._wf_stage_idx = 0
        self._wf_subject = None                         # the launched-subject lock is released
        self._receipt("workflow stopped — partial package saved" if stopped
                      else "workflow complete → Quest Log", "⛓", ORANGE if stopped else GREEN)
        self._paint_workflow()
        self._refresh_hub()
        self._toast("⏹ chain stopped — what ran is packaged on the log" if stopped
                    else "✓ chain complete — the dossier is in the Quest Log", ORANGE if stopped else GREEN)

    def _workflow_halt_note(self, subject: str, stage_n: int, label: str, why: str, gate: dict) -> None:
        """Persist a conditional-workflow HALT to Living Memory (H2) — the chain aborted at a gate and
        WHY, so the early-abort is auditable and the Quest Log NOTE lane surfaces it. Best-effort;
        runs on the worker thread (Living-Memory appends are process-safe)."""
        mem = self._memory()
        if mem is None:
            return
        subj = str(subject or "")
        tkr = subj if (subj and " " not in subj and len(subj) <= 10) else None
        try:
            mem.write("note",
                      text=f"WORKFLOW HALT — {subj}: gate before stage {stage_n} ({label}) failed — {why}",
                      ticker=tkr, tags=["workflow", "halt"],
                      meta={"subject": subj, "stage": stage_n, "label": label,
                            "gate": gate, "reason": why}, source="workflow-gate")
        except Exception:
            pass

    def _save_workflow_package(self, subject: str, steps: list, transcript: list):
        """Assemble the chain's output into ONE dossier (the 'nice package at the end') under
        data/agent_drafts/, where the Results board reads it."""
        import datetime
        try:
            d = self._drafts_dir()
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(subject))[:24] or "book"
            path = os.path.join(d, f"workflow_{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
            chain = "  →  ".join(self._wf_stage_label(s) for s in steps)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"# Workflow package — {subject}\n\n_{datetime.datetime.now():%Y-%m-%d %H:%M} · "
                         f"chain: {chain} · review draft (not applied / not committed)_\n\n")
                for num, label, note, results in transcript:
                    fh.write(f"\n## Stage {num} · {label}\n_{note}_\n\n")
                    for ag, txt in results:
                        fh.write(f"### {ag}\n\n{txt}\n\n")
            return path
        except Exception:
            return None

    # ---- the FOCUS column: the agent / task inspectors -----------------------------------------
    def _agent_role(self, agent_id: str) -> str:
        """A clear, full 'what it does' line — the curated copy first (HUB_AGENT_DOC), falling back to
        the .claude/agents blurb only for agents we haven't documented yet (never the 52-char stub)."""
        doc = HUB_AGENT_DOC.get(agent_id, {})
        if doc.get("what"):
            return doc["what"]
        return dict(self._agent_roster()).get(agent_id, "")

    def _agent_recent(self, agent_id: str, n: int = 3) -> list:
        """Recent outputs/alerts for an agent → (level, text, meta), from Living Memory entries whose
        source names the agent. Grounded; empty if none."""
        mem = self._memory()
        if mem is None:
            return []
        out = []
        try:
            for ent in mem.query(limit=60):
                if agent_id.lower() not in str(ent.get("source", "")).lower():
                    continue
                low = str(ent.get("text", "")).lower()
                typ = str(ent.get("type", "note"))
                level = ("warn" if any(w in low for w in ("flag", "stale", "risk", "below", "dilut"))
                         else ("good" if typ in ("council_verdict", "outcome") else "info"))
                out.append((level, _clip(str(ent.get("text", "")), 44), f"{_mem_age(ent.get('ts'))} ago"))
                if len(out) >= n:
                    break
        except Exception:
            return []
        return out

    def _sentinel_watch_rows(self) -> list:
        """The Sentinel's four checks → (name, status, note, value). If a recent sweep wrote to memory
        we surface its read (warn); otherwise we describe what each check watches — never an invented
        per-name number (grounded-or-silent, per the Forge spec)."""
        rows = [("liquidity-runway", "days of ADV to exit the position", "≥ 5d floor"),
                ("financing-window", "price vs last placement · death-spiral", "dilution ≤ 2% QoQ"),
                ("thesis-integrity", "load-bearing claims vs the tape", "claims tracked"),
                ("Ulysses rules", "armed pre-commitments · parsed at save", "fail-closed")]
        latest = None
        mem = self._memory()
        if mem is not None:
            try:
                for ent in mem.query(limit=40):
                    if "sentinel" in str(ent.get("source", "")).lower() or str(ent.get("type")) == "sentinel":
                        latest = ent; break
            except Exception:
                latest = None
        out = []
        for k, note, v in rows:
            status, n = "ok", note
            if latest is not None and k.split("-")[0].split()[0] in str(latest.get("text", "")).lower():
                status, n = "warn", _clip(str(latest.get("text", "")), 40)
            out.append((k, status, n, v))
        return out

    def _agent_inspector_markup(self, agent_id: str):
        """The selected agent's detail — what it does · WHEN to reach for it · its Can-do verbs · example
        briefs you can click to pre-fill (then edit for specifics) · the Sentinel's Watching panel ·
        standing jobs · recent outputs. The whole request you type is handed through, verbatim."""
        e = self._esc
        _g, lane, _st, can = _hub_meta(agent_id)
        r = HUB_RUNTIMES.get(lane, {})
        doc = HUB_AGENT_DOC.get(agent_id, {})
        status = self._hub_roster_status(agent_id)
        prov = self._agent_provider(agent_id)
        provnote = "gemini · agy CLI" if prov == "gemini" else f"claude · {r.get('sub', '')}"
        md = [f"[bold #FFFFFF]{e(agent_id)}[/]   {_status_dot(status)} [{DIM}]{status}[/]",
              f"{_model_chip(agent_id)} {_lane_chip(lane)} [{DIM}]{provnote}[/]",
              f"[{SILVER}]{e(_clip(self._agent_role(agent_id), 200))}[/]", ""]
        if doc.get("when"):
            md.append(f"[bold #8C8C92]USE WHEN[/]")
            md.append(f"  [{DIM}]{e(doc['when'])}[/]")
            md.append("")
        if agent_id == "sentinel":
            md.append(f"[bold #8C8C92]WATCHING[/] [{DIM}]· every 6h sweep[/]")
            for k, st, note, v in self._sentinel_watch_rows():
                dot = f"[{GREEN}]●[/]" if st == "ok" else f"[{ORANGE}]◔[/]"
                md.append(f"  {dot} [{SILVER}]{e(k)}[/]  [{DIM}]{e(note)}[/]  [{DIM}]{e(v)}[/]")
            md.append("")
        md.append(f"[bold #8C8C92]CAN DO[/] [{DIM}]· click to set the verb[/]")
        md.append("  " + "  ".join(f"[@click=app.hub_pick('verb','{e(k)}')][{TEAL}]{e(k)}[/][/]" for k in can))
        md.append("")
        if doc.get("eg"):
            md.append(f"[bold #8C8C92]TRY[/] [{DIM}]· click to load, then edit for specifics[/]")
            for i, ex in enumerate(doc["eg"]):
                md.append(f"  [{AMBER}]›[/] [@click=app.hub_example('{agent_id}', {i})][{SILVER}]{e(ex)}[/][/]")
            md.append("")
        myjobs = [j for j in (self._load_jobs() or []) if j.get("agent") == agent_id]
        md.append(f"[bold #8C8C92]RECURRING[/] [{DIM}]· {len(myjobs) or 'none'}[/]")
        for j in myjobs[:4]:
            md.append(f"  [{AMBER}]⏲[/] [{SILVER}]{e(_clip(j.get('label', ''), 28))}[/] [{DIM}]{j.get('every_min')}m[/]")
        md.append("")
        md.append(f"[bold #8C8C92]{'RECENT ALERTS' if agent_id == 'sentinel' else 'RECENT OUTPUTS'}[/]")
        recent = self._agent_recent(agent_id, 3)
        if recent:
            for level, txt, meta in recent:
                md.append(f"  [{_level_color(level)}]●[/] [{SILVER}]{e(txt)}[/] [{DIM}]{e(meta)}[/]")
        else:
            md.append(f"  [{DIM}]no runs yet — delegate one below[/]")
        acts = (f"[@click=app.hub_delegate_agent('{e(agent_id)}')][bold {AMBER}]▶ Delegate to {e(agent_id)}[/][/]   "
                f"[@click=app.hub_schedule('{e(agent_id)}')][{DIM}]⏲ Schedule…[/][/]   [{DIM}]· Esc[/]")
        return ("\n".join(md), acts)

    def _task_inspector_markup(self, jid):
        """A running task's detail — who's doing it, the task itself, elapsed, and a live note."""
        e = self._esc
        j = self._inflight.get(int(jid))
        if not j:
            return (f"[bold {GOLD}]task ended[/]\n\n[{DIM}]it finished — see Done today.[/]", f"[{DIM}]· Esc[/]")
        el = max(0, int(time.time() - j.get("started", time.time())))
        who, task = self._task_label(j)
        prov = j.get("provider") or self._agent_provider(who)
        model = _run_model_label(who, prov)
        md = [f"[bold #FFFFFF]{e(who)}[/] [{DIM}]is running[/]" + (f" [{DIM}]·[/] [{AMBER}]{e(j['ticker'])}[/]" if j.get("ticker") else ""),
              f"{_model_chip(who) if who in HUB_AGENT_MODEL else ''} [{DIM}]working · {el}s · {model}[/]",
              f"[{SILVER}]{e(_clip(task or j.get('label', ''), 160))}[/]", "",
              f"[bold #8C8C92]LIVE[/]",
              f"  [{TEAL}]$[/] [{DIM}]{e(who)} · grounding context…[/]",
              f"  [{GREEN}]⟳[/] [{SILVER}]running — the result will land on the Results board[/]"]
        acts = (f"[@click=app.cancel_job('{jid}')][{ORANGE}]✕ Cancel run[/][/]   "
                f"[@click=app.hub_clear_inspect][{DIM}]Close detail[/][/]   [{DIM}]· Esc[/]")
        return ("\n".join(md), acts)

    # ---- composer / inspector actions (clicked from the Hub markup) ----------------------------
    def action_hub_inspect_agent(self, agent_id: str) -> None:
        """Select an agent → focus it in the inspector AND load it into the composer (the verb resets
        to its first capability if the current verb isn't one of its own)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._insp_agent = agent_id
        scr._insp_task = None
        scr._sel = -1                                  # leave the reader → show the inspector
        scr._c_agent = agent_id
        can = _hub_meta(agent_id)[3]
        if scr._c_verb not in can:
            scr._c_verb = can[0] if can else "ask"
        scr.refresh_cards()
        scr._paint()

    def action_hub_inspect_task(self, jid) -> None:
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._insp_task = int(jid)
        scr._sel = -1
        scr.refresh_cards()
        scr._paint()

    def action_hub_clear_inspect(self) -> None:
        scr = self.screen
        if isinstance(scr, HubScreen):
            scr._insp_task = None
            scr.refresh_cards()
            scr._paint()

    def action_hub_toggle_group(self, gid: str) -> None:
        """Fold / unfold a roster group (the collapsible TEAM sidebar)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._collapsed_groups ^= {gid}                  # toggle membership
        try:
            scr.query_one("#hub_roster", Static).update(self._card_roster_markup())
        except Exception:
            pass

    def action_hub_cycle(self, field: str) -> None:
        """Cycle a composer field forward (agent · verb · subject · when)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        if field == "agent":
            ids = list(HUB_AGENT_META.keys())
            i = ids.index(scr._c_agent) if scr._c_agent in ids else -1
            scr._c_agent = ids[(i + 1) % len(ids)]
            can = _hub_meta(scr._c_agent)[3]
            if scr._c_verb not in can:
                scr._c_verb = can[0] if can else "ask"
        elif field == "verb":
            can = _hub_meta(scr._c_agent)[3] or HUB_VERBS
            i = can.index(scr._c_verb) if scr._c_verb in can else -1
            scr._c_verb = can[(i + 1) % len(can)]
        elif field == "when":
            scr._c_when = "schedule" if scr._c_when == "now" else "now"
        elif field == "subject":
            opts = ["book"] + sorted(self._baskets_by_ticker or {}) + ["silver universe"]
            i = opts.index(scr._c_subject) if scr._c_subject in opts else -1
            scr._c_subject = opts[(i + 1) % len(opts)]
        scr.refresh_cards()

    def action_hub_pick(self, field: str, value: str) -> None:
        """Set a composer field directly (e.g. from the inspector's Can-do chips)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        if field == "agent":
            self.action_hub_inspect_agent(value)
            return
        if field == "verb":
            scr._c_verb = value
        elif field == "subject":
            scr._c_subject = value
        scr.refresh_cards()

    def action_hub_example(self, agent_id: str, idx) -> None:
        """Load an example brief into the NL line (then the operator edits it for specifics and sends).
        This is the granular path — the example is a starting point, not a fixed template."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        try:
            ex = HUB_AGENT_DOC.get(agent_id, {}).get("eg", [])[int(idx)]
        except Exception:
            return
        scr._c_agent = agent_id
        tk = self._detect_ticker(ex)
        if tk:
            scr._c_subject = tk
        try:
            box = scr.query_one("#hub_input", Input)
            box.value = ex
            box.cursor_position = len(ex)
            scr.set_focus(box)
        except Exception:
            pass
        scr.refresh_cards()
        self._toast("loaded — edit for specifics, then ⏎ to send it through to the agent", TEAL)

    def action_hub_delegate_agent(self, agent_id: str) -> None:
        """Delegate to this agent using whatever is typed in the NL line as the FULL brief (pass-through).
        Empty line → prefill it so you can write a specific request rather than fire a template."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._c_agent = agent_id
        scr._c_when = "now"
        brief = ""
        try:
            brief = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        if not brief:
            try:
                box = scr.query_one("#hub_input", Input)
                box.value = ""
                scr.set_focus(box)
            except Exception:
                pass
            self._toast(f"type what you want {agent_id} to do, then ⏎ — your words go through verbatim", TEAL)
            return
        tk = self._detect_ticker(brief) or (scr._c_subject if scr._c_subject not in ("book", "—") else None)
        self._delegate(agent_id, brief, subject=tk, verb=scr._c_verb)
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        scr.refresh_cards()

    def action_hub_schedule(self, agent_id: str) -> None:
        scr = self.screen
        if isinstance(scr, HubScreen):
            scr._c_agent = agent_id
            scr._c_when = "schedule"
            scr.refresh_cards()
        self._toast(f"composer set to schedule {agent_id} — pick a verb/subject, then Schedule ⏲", TEAL)

    def action_hub_go(self, nl: str = None) -> None:
        """Send the composer. claim/rule → file to the Thesis Ledger (parsed/validated at save);
        schedule → add a recurring job (dial-gated); now → delegate to the agent as a background run
        (visible in the Working lane). The route follows verb + when."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        a = scr._c_agent; verb = scr._c_verb; subj = (scr._c_subject or "").strip(); when = scr._c_when
        if nl is None:
            try:
                nl = scr.query_one("#hub_input", Input).value.strip()
            except Exception:
                nl = ""
        if not subj or subj == "—":
            self._toast("set a subject first (click subject ▾, or type a ticker)", ORANGE)
            return
        is_name = subj not in ("book", "silver universe")
        if verb in HUB_LEDGER_VERBS:
            if is_name:
                self._focus = subj                     # claims/rules attach to the named thesis
            if verb == "rule":
                if "->" in (nl or ""):
                    self._amend_thesis_rule(nl)
                else:
                    self._toast("rule: type the trigger in the line — e.g. phi < 1.0 -> trim_to 0.4", ORANGE)
                    return
            else:
                self._amend_thesis_claim(nl or f"{subj}: thesis claim")
        elif when == "schedule":
            import cockpit_scheduler as sched
            kind = verb if verb in getattr(sched, "JOB_KINDS", ()) else "ask"
            agent = a if a in self._agent_names() else None
            self._add_job(kind, (f"{subj} — {nl}" if nl else subj), agent=agent)
        else:
            self._delegate(a, nl or f"{verb} {subj}", subject=subj, verb=verb)
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        scr.refresh_cards()

    # ---- the intent router + pass-through delegation (the NL bar reads your words, the agent gets
    #      your WHOLE request — no template flattening) ------------------------------------------
    def _detect_ticker(self, text: str):
        """Pull a ticker out of free text — a known holding first, else an EXCHANGE-suffixed symbol
        (URC.TO, AGA.V). Conservative: a bare uppercase word is NOT treated as a ticker."""
        import re
        up = (text or "").upper()
        for tk in sorted(self._baskets_by_ticker or {}, key=len, reverse=True):
            if re.search(rf"\b{re.escape(tk)}\b", up):
                return tk
        m = re.search(r"\b[A-Z]{1,5}\.[A-Z]{1,2}\b", up)
        return m.group(0) if m else None

    def _route_intent(self, text: str):
        """Map a natural-language request → (agent, verb, ticker). agent/verb are None when no keyword
        matches (→ hand to the general orchestrator). The ticker is best-effort."""
        low = f" {(text or '').lower()} "
        tk = self._detect_ticker(text)
        for keywords, agent, verb in HUB_INTENT_RULES:
            if any(kw in low for kw in keywords):
                return agent, verb, tk
        return None, None, tk

    def _has_gemini(self) -> bool:
        """Is the Gemini (agy) CLI actually available? Cached. If not, gemini-routed agents fall back
        to Claude so nothing breaks when agy isn't configured.
        Trusts CEX_AGY_CMD if set explicitly (covers shell aliases shutil.which can't see)."""
        if getattr(self, "_agy_ok", None) is None:
            import shutil
            explicit = os.environ.get("CEX_AGY_CMD", "")
            self._agy_ok = (bool(explicit) or bool(shutil.which("agy"))
                            or bool(os.environ.get("CEX_AGY_HEADLESS")))
        return self._agy_ok

    def _agent_provider(self, agent: str) -> str:
        """Effective provider for an agent — the registry's choice, but falling back to Claude when the
        Gemini (agy) CLI isn't installed/configured."""
        prov = _agent_model(agent)[0]
        if prov == "gemini" and not self._has_gemini():
            return "claude"
        return prov

    _RESEARCH_AGENTS = frozenset({"scout", "synthesis", "verifier", "bear", "bull", "value-analyst",
                                    "balance-sheet-analyst", "catalyst-verifier"})
    # advocate seats — composing one of these auto-offers a one-click disconfirmation leg (a @bear /
    # @antigravity pre-mortem) so a long case never ships without its red-team foil (disconfirm-by-default).
    _ADVOCATE_AGENTS = frozenset({"bull", "synthesis", "value-analyst", "balance-sheet-analyst"})

    def _thesis_slot_hint(self, ticker: str) -> str:
        """Return a thesis-slot constraint block for *ticker*, or '' if not applicable.
        Reads directly from v5_config.json so it works even when the engine is down."""
        if not ticker or ticker in ("book", "—", "silver universe"):
            return ""
        try:
            import json as _json
            _cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v5_config.json")
            with open(_cfg_path) as _f:
                _pm = _json.load(_f).get("portfolio_metadata", {}).get(ticker, {})
            slot = _pm.get("thesis_slot", "")
            desc = _pm.get("thesis_slot_desc", "")
            if slot:
                return (f"\n\n--- THESIS-SLOT CONSTRAINT (mandatory first screen) ---\n"
                        f"{ticker} fills the '{slot}' slot in the barbell.\n"
                        f"Any replacement or rotation candidate MUST fit this slot first, "
                        f"ahead of valuation or catalysts. Flag slot-mismatches explicitly.\n"
                        f"Slot definition: {desc}")
        except Exception:
            pass
        return ""

    def _gemini_prompt(self, agent: str, brief: str, subject: str = None) -> str:
        """Wrap a brief for a Gemini seat — the agent's role + a Google Finance grounding nudge (its
        edge for accurate prices/data), since Gemini doesn't carry the .claude subagent definition."""
        role = self._agent_role(agent) or f"the {agent}"
        slot_hint = (self._thesis_slot_hint(subject)
                     if subject and agent in self._RESEARCH_AGENTS else "")
        subj = (f"  Subject / book context: {subject}.{slot_hint}"
                if subject and subject not in ("book", "—") else "")
        return (f"You are {agent} — {role}\n\nUse Google Finance / Google Search grounding for accurate, "
                f"current prices and figures; cite sources; never invent a number.{subj}\n\nTask: {brief}")

    def _delegate(self, agent: str, brief: str, subject: str = None, verb: str = None,
                  continue_thread: bool = False) -> None:
        """Hand a FULL natural-language brief to an agent — the whole request, verbatim. Routes to the
        agent's provider: Claude (claude -p @agent) or Gemini (the agy CLI), per HUB_AGENT_MODEL.
        ``continue_thread`` is forwarded to ``_ask_agent`` (the chat compose continues; a button starts
        a new chat)."""
        brief = (brief or "").strip()
        subj = (subject or "").strip()
        prov = self._agent_provider(agent)
        label = brief or f"{verb or ''} {subj}".strip()
        # bind_ticker: use the composer subject so the thread lands on URC.TO, not the global AGA.V focus
        bind_ticker = subj if subj and subj not in ("book", "silver universe", "—") else None
        # inject thesis-slot constraint inline for research agents when the subject has a defined slot
        # (Gemini agents don't read CLAUDE.md; Claude agents benefit from the inline reminder too)
        if agent in self._RESEARCH_AGENTS and bind_ticker:
            slot_hint = self._thesis_slot_hint(bind_ticker)
            if slot_hint:
                brief = brief + slot_hint
        if prov == "gemini":
            self._ask_agent(self._gemini_prompt(agent, brief, subj), provider="gemini", agent=agent,
                            label=label, ticker=bind_ticker, continue_thread=continue_thread)
            self._toast(f"delegated → {agent} (gemini-flash) — watch the Working lane, result lands on the board", GREEN)
            return
        ctx = (f"  (subject: {subj})" if bind_ticker
               and subj.lower() not in brief.lower() and agent not in self._AGENT_BOOK_LEVEL else "")
        model = _agent_model(agent)[1]
        if agent == "sentinel":
            body = brief or ("Run a Sentinel sweep on the book — liquidity-runway, financing-window / "
                             "death-spiral, thesis-integrity, and armed Ulysses rules.")
            self._ask_agent(f"As the Sentinel (the book's risk watcher), {body}{ctx}", agent=agent,
                            label=label, ticker=bind_ticker, continue_thread=continue_thread)
        elif agent in self._agent_names():
            self._ask_agent(f"@{agent} {brief}{ctx}", agent=agent, label=label, ticker=bind_ticker,
                            continue_thread=continue_thread)
        else:
            self._ask_agent(brief, ticker=bind_ticker, continue_thread=continue_thread)  # orchestrator routes
            model = "claude"
        self._toast(f"delegated → {agent} ({model}) — watch the Working lane, result lands on the board", GREEN)

    def _hub_scenario(self, idea: str) -> None:
        """Run a free-form what-if SCENARIO from the Hub — close to the desk, focus the what-if, and let
        an agent build the knob move + a narrative of the effects beyond the knobs."""
        idea = (idea or "").strip()
        if not idea:
            self._toast("scenario: describe it — e.g. 'uranium spot doubles on a supply shock'", ORANGE)
            return
        try:
            self.pop_screen()                               # leave the Hub so the desk what-if is visible
        except Exception:
            pass
        try:
            self.action_whatif_focus()
            tk = self._detect_ticker(idea) or self._focus or ""
            if tk:
                self.query_one("#wf_ticker", Input).value = tk
            self.query_one("#wf_overrides", Input).value = idea
        except Exception:
            pass
        self._do_whatif()
        self._toast("scenario → an agent is building the knobs + a brief beyond them", TEAL)

    def action_focus_tk(self, tk: str) -> None:
        """Click a ticker anywhere (desk tape, notes, memory) -> focus it on the spine."""
        self._pop_if_modal()                          # if invoked from a detail pop-over, close it
        if tk and tk != "_book":
            self.action_tab("book")
            self._set_focus(str(tk), move_cursor=True)

    def _ask_agent(self, text: str, provider: str = "claude", agent: str = None,
                   label: str = None, ticker: str = None, continue_thread: bool = False) -> None:
        """Plain-text query → a *background* headless agent. A distinct ask starts its OWN chat by
        default; only the chat COMPOSE or an explicit follow-up passes ``continue_thread=True`` to
        append to the active conversation — so unrelated actions ('ask the analyst' on quality, then on
        valuation) never fold into whichever chat was last touched. Context sent to the agent is ONLY
        the (new or continued) branch's lineage, so threads stay isolated. Both query and reply land in
        the CONVERSATION tree. `ticker` binds a fresh thread to a specific name."""
        text = text.strip()
        if not text:
            return
        self._asked = text
        low = text.lower()
        if "convene" in low or "council" in low:     # convening expands the inline council (merged view)
            self._council_open = True
        parent = self._active if continue_thread else None   # a new ask = a new chat; the compose continues
        fresh = parent is None
        uid = self._new_node("you", text, parent)
        bind_ticker = ticker                         # explicit subject only — never inherit global focus
        if fresh:                                    # a fresh thread binds to its subject, not the global focus
            self._conv[uid]["ticker"] = bind_ticker
            try:
                self._conv[uid]["scenario"] = self.query_one("#wf_overrides", Input).value.strip()
            except Exception:
                self._conv[uid]["scenario"] = ""
        self._pending_user = uid
        self._active = uid
        self.action_tab("book")
        self._render_agent_reply(self._state)        # show the pending state immediately
        jid = self._inflight_add("ask", label or text, bind_ticker or "", agent=agent,
                                 provider=provider, node=uid)
        self._ask_agent_bg(text, uid, jid, provider, agent or provider)

    # ---- conversation tree -------------------------------------------------
    def _new_node(self, role: str, text: str, parent, agent=None) -> str:
        self._node_seq += 1
        nid = str(self._node_seq)
        self._conv[nid] = {"id": nid, "parent": parent, "role": role,
                            "text": str(text), "agent": agent, "ts": time.time()}
        self._save_conv()                              # chats survive a restart (was in-memory only)
        return nid

    def _conv_path(self) -> str:
        return os.environ.get("CEX_CONV_PATH") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "conversations.json")

    def _save_conv(self) -> None:
        """Persist the conversation tree so chats survive a restart — the Hub used to rebuild from an
        EMPTY _conv every launch, so past threads vanished. Bounded to the most recent threads
        (conv_prune); atomic write; fenced so a disk hiccup never disturbs the chat."""
        try:
            path = self._conv_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {"node_seq": self._node_seq, "nodes": conv_prune(self._conv)}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
        except Exception:
            obs.swallow("conv.save")

    def _load_conv(self) -> None:
        """Rehydrate the conversation tree on startup so past chats reappear — CONTINUABLE threads in
        the Hub, not just the read-only Living-Memory snapshots. Restores the monotonic node counter so
        new nodes never collide. Fenced — a missing/corrupt file just yields an empty desk."""
        try:
            path = self._conv_path()
            if not os.path.exists(path):
                return
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            nodes = payload.get("nodes")
            if not isinstance(nodes, dict) or not nodes:
                return
            self._conv = nodes
            ids = [int(k) for k in nodes if str(k).isdigit()]
            self._node_seq = max([int(payload.get("node_seq") or 0)] + ids + [0])
        except Exception:
            obs.swallow("conv.load")

    def _lineage(self, nid):
        chain, seen = [], set()
        while nid and nid in self._conv and nid not in seen:
            seen.add(nid); chain.append(self._conv[nid]); nid = self._conv[nid]["parent"]
        return list(reversed(chain))

    def _branch_root(self, nid):
        cur = nid
        while cur and self._conv.get(cur, {}).get("parent"):
            cur = self._conv[cur]["parent"]
        return cur

    def _roots(self):
        return [n for n in self._conv.values() if not n.get("parent")]

    def _thread_meta(self, nid):
        """The name + scenario a thread is bound to (captured on its root)."""
        root = self._conv.get(self._branch_root(nid)) or {}
        return root.get("ticker"), root.get("scenario")

    def _maybe_seed_pipeline(self, state) -> None:
        """When a background pipeline finishes, turn each surviving name into a context-bound research
        thread (seeded with the finding) so the run flows INTO your research instead of just being a
        readout. Also persists the full report as a Dossier memo. Runs once per completed run."""
        pipe = (state or {}).get("pipeline") or {}
        if pipe.get("status") != "done" or pipe.get("started") is None or pipe.get("started") == self._pipe_seen:
            return
        self._pipe_seen = pipe.get("started")
        theme = pipe.get("theme") or "pipeline"
        seeded = 0
        for tk, v in (pipe.get("verdicts") or {}).items():
            verdict = (v.get("verdict") if isinstance(v, dict) else str(v)) or "—"
            note = (v.get("note") if isinstance(v, dict) else "") or ""
            # auto-add ALL verdicts to watchlist bench (survivors + rejects, clearly labelled)
            self._add_to_watchlist(
                tk,
                note=(note[:60] or f"pipeline · {theme}"),
                source="pipeline",
                status=verdict,
            )
            if str(verdict).upper() == "REJECT":          # survivors become threads; rejects stay in the panel
                continue
            seed = f"[{verdict}] {note}".strip()
            aid = self._new_node("agent", f"Pipeline finding ({theme}): {seed}", None, agent="pipeline")
            self._conv[aid]["ticker"] = tk
            self._conv[aid]["scenario"] = ""
            seeded += 1
        self._save_pipeline_dossier(pipe)
        if seeded:
            self._status(Text(f"⑂ pipeline seeded {seeded} research thread(s) — open CONVERSATION to dig in",
                              style=GREEN))

    def _save_pipeline_dossier(self, pipe) -> None:
        body = (pipe.get("result") or "").strip()
        if not body:
            return
        import datetime
        theme = pipe.get("theme") or "pipeline"
        verds = ", ".join(f"{tk} {(v.get('verdict') if isinstance(v, dict) else v)}"
                          for tk, v in (pipe.get("verdicts") or {}).items())
        out = [f"# Pipeline — {theme}", "",
               f"_run {datetime.datetime.now():%Y-%m-%d %H:%M}_" + (f" · {verds}" if verds else ""),
               "", body]
        try:
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "decisions")
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(theme))[:20] or "pipeline"
            with open(os.path.join(d, f"pipeline_{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md"),
                      "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            self._refresh_decisions()
        except Exception:
            pass

    @staticmethod
    def _esc(s) -> str:
        return str(s).replace("\\", "\\\\").replace("[", "\\[")   # neutralise markup in user/agent text

    def action_new_thread(self) -> None:
        self._active = None
        self._render_agent_reply(self._state)
        self._status(Text("✦ new thread — your next message starts fresh (no prior context)", style=TEAL))

    def action_sel_node(self, nid: str) -> None:
        if nid in self._conv:
            self._active = nid
            self._render_agent_reply(self._state)
            self._status(Text("⤷ following up on this reply — next message forks here", style=GREEN))

    def action_sel_branch(self, root_nid: str) -> None:
        # jump to a thread: make its most-recent node active AND restore its research frame
        tip = max((n for n in self._conv.values() if self._branch_root(n["id"]) == root_nid),
                  key=lambda n: n["ts"], default=None)
        if tip:
            self._active = tip["id"]
            self._restore_thread_frame(root_nid)
            self._render_agent_reply(self._state)

    def _restore_thread_frame(self, root_nid: str) -> None:
        """Re-load the name + what-if scenario a thread was opened on, so revisiting it restores the
        exact frame you were exploring — research and valuation stay in lockstep."""
        n = self._conv.get(root_nid) or {}
        tk, scen = n.get("ticker"), n.get("scenario")
        restored = []
        if tk:
            self._set_focus(tk, move_cursor=True)
            restored.append(tk)
        if scen:
            try:
                self.query_one("#wf_overrides", Input).value = scen
                self._knobs_from_overrides(scen)
                self._render_wf_knobs()
                restored.append(scen)
            except Exception:
                pass
        if restored:
            self._status(Text(f"↻ restored frame: {' · '.join(restored)}", style=TEAL))

    def action_toggle_node(self, nid: str) -> None:
        self._expanded.discard(nid) if nid in self._expanded else self._expanded.add(nid)
        self._render_agent_reply(self._state)

    def action_save_thread(self) -> None:
        """Turn the active thread into a saved research memo (data/decisions → the Dossier tab)."""
        chain = self._lineage(self._active)
        if not chain:
            self._status(Text("no active thread to save", style=ORANGE)); return
        import datetime
        root = self._conv.get(self._branch_root(self._active)) or {}
        tk = root.get("ticker") or "thread"
        out = [f"# {tk} — {(root.get('text') or 'research thread')[:70]}", "",
               f"_cockpit research thread · {datetime.datetime.now():%Y-%m-%d %H:%M}_"]
        if root.get("scenario"):
            out.append(f"_scenario: {root['scenario']}_")
        out.append("")
        for m in chain:
            who = "**You**" if m["role"] == "you" else f"**{m.get('agent', 'claude')}**"
            out.append(f"{who}: {m['text']}\n")
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "decisions")
        try:
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(tk))[:16] or "thread"
            path = os.path.join(d, f"{safe}_thread_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
        except Exception as exc:
            self._status(Text(f"save failed: {exc}", style=ORANGE)); return
        self._status(Text(f"✓ thread saved → Dossier ({os.path.basename(path)})", style=GREEN))
        self._receipt(f"dossier {os.path.basename(path)}", "⇪", GOLD, undo=lambda p=path: self._undo_file(p))
        self._refresh_decisions()

    @staticmethod
    def _inject_model_flags(parts: list, tmpl: str, model: str = None, effort: str = None) -> list:
        """Append --model/--effort to a claude-CLI argv — the cost governor. Without these, EVERY
        headless spawn runs the session default (opus @ xhigh effort), even for seats the registry
        pins to sonnet — the #1 token burn. Respect the operator: only inject when the command IS
        the claude CLI and the template doesn't already set the flag."""
        if not parts or not os.path.basename(parts[0]).startswith("claude"):
            return parts                                   # custom CLI (agy, true, …) — hands off
        out = list(parts)
        if model and "--model" not in tmpl:
            out += ["--model", str(model)]
        if effort and "--effort" not in tmpl:
            out += ["--effort", str(effort)]
        return out

    def _ask_argv(self, prompt: str, model: str = None, effort: str = None, stream: bool = False):
        """Headless one-shot for the prompt bar. Configurable (CEX_ASK_CMD, default 'claude -p
        {prompt}') so it fits the user's CLI; shares the cockpit's permission allowlist.
        model/effort ride as CLI flags so an ask runs on the seat's registry model, not the
        session default (effort default: CEX_ASK_EFFORT, else high — xhigh is for deep seats).
        ``stream`` adds Claude Code's stream-json output so the tape updates live (parsed by
        ``reduce_stream_json``) — only for a real ``claude`` command, never a custom CLI."""
        import shlex
        tmpl = os.environ.get("CEX_ASK_CMD", "claude -p {prompt}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            parts = [prompt if p == "{prompt}" else p for p in parts]
        else:
            parts = parts + [prompt]
        if effort is None:                              # None → the default; "" → explicitly none
            effort = os.environ.get("CEX_ASK_EFFORT", "high")
        argv = self._inject_model_flags(parts, tmpl, model, effort or None)
        if stream and argv and os.path.basename(argv[0]).startswith("claude") \
                and "--output-format" not in tmpl:      # claude -p needs --verbose with stream-json
            argv = argv + ["--output-format", "stream-json", "--verbose"]
        return argv

    @work(thread=True, group="ask", exclusive=True)
    def _ask_agent_bg(self, text: str, uid: str, jid: int = 0, provider: str = "claude",
                      agent_label: str = "claude") -> None:
        _post("/agent/activity", {"agent": "cockpit", "kind": "prompt", "summary": text,
                                  "ticker": (self._conv.get(uid) or {}).get("ticker") or ""})
        self.call_from_thread(self._status, Text("⟳ asking… (chat stays free; reply lands in Book)", style=TEAL))
        # context = ONLY this thread's lineage (prior turns above the new question), not other branches
        chain = self._lineage(self._conv.get(uid, {}).get("parent"))
        ctx = ""
        if chain:
            lines = "\n".join(("You: " if m["role"] == "you" else "Assistant: ") + str(m["text"])[:400]
                              for m in chain)
            ctx = f"Earlier in THIS research thread:\n{lines}\n\nContinue this thread.\n\n"
        # the thread is self-aware: it carries the name + scenario it was opened on
        tk, scen = self._thread_meta(uid)
        bind = ""
        if tk:
            bind += f"This research thread is about {tk}. "
        if scen:
            bind += f"Its working what-if scenario is: {scen}. "
        if bind:
            bind += "Ground your answer in that name/scenario unless told otherwise.\n"
        # prepend the shared situational frame (Forge #3) so the agent never starts blind — regime,
        # posture, what you're looking at + doing, the book's verdicts, recent memory.
        frame = ""
        try:
            import world_state
            import living_memory as _lm_mod
            _mem_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "living_memory.jsonl")
            _lm_inst = _lm_mod.LivingMemory(path=_mem_path)
            recent_mem = _lm_inst.query(ticker=tk, limit=8) if tk else _lm_inst.query(limit=5)
            # calibration flywheel (read side): the per-archetype prior the agent must clear, anchored
            # to the book's live archetypes so a base rate shows even before any decision has closed.
            cal_prior = None
            try:
                import calibration as _cal
                _scored = [e.get("meta", {}) for e in _lm_inst.query(type="outcome", limit=0)
                           if (e.get("meta") or {}).get("status") == "scored"]
                _arch = sorted({(b.get("archetype") or "") for b in (self._baskets_by_ticker or {}).values()
                                if b.get("archetype")}) or None
                cal_prior = _cal.brief_prior(_cal.priored_scorecard(_scored, archetypes=_arch), _arch)
            except Exception:
                cal_prior = None
            frame = world_state.render_brief(
                world_state.build(self._state or {}, focus=tk or None, recent_memory=recent_mem,
                                  calibration=cal_prior)) + "\n\n"
            if tk and recent_mem:
                mem_lines = [f"## PRIOR RESEARCH — {tk} ({len(recent_mem)} entries, newest first)"]
                for e in recent_mem[:8]:
                    entry_text = str(e.get("text", ""))[:120]
                    mem_lines.append(f"- [{e.get('type', '')}] {entry_text}")
                frame += "\n".join(mem_lines) + "\n\n"
        except Exception:
            frame = ""
        prompt = f"{frame}{ctx}{bind}{text}"
        # opt-in streaming (CEX_ASK_STREAM): claude emits stream-json so the tape updates live AND a
        # timeout keeps partial work. Off by default — the plain text path is unchanged. Gemini (agy)
        # has its own format, so it's never streamed here.
        streaming = bool(os.environ.get("CEX_ASK_STREAM")) and provider != "gemini"
        # Popen (not run) so a cancel from the AGENTS strip can terminate the child mid-flight.
        if provider == "gemini":
            argv = self._agy_argv(prompt)
        else:                                         # the seat's registry model governs the spawn
            mdl = _run_model_label(agent_label, "claude") if agent_label in HUB_AGENT_META else None
            argv = self._ask_argv(prompt, model=mdl, stream=streaming)
        proc = None
        try:
            # bufsize=1 (line-buffered) + a readline loop = the child's reasoning lands LINE BY LINE,
            # not all at once on exit — the H1 live tape. stdout/stderr are drained on separate reader
            # threads (so a full stderr pipe can't deadlock us), and we enforce the timeout ourselves
            # since communicate() is gone. A cancel from the AGENTS strip kills the child → poll() trips.
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, bufsize=1,
                                    cwd=os.path.dirname(os.path.abspath(__file__)))
            if jid in self._inflight:
                self._inflight[jid]["proc"] = proc
            err_buf: list = []
            out_holder: dict = {}

            def _on_update(txt, n):
                self.call_from_thread(self._stream_partial, uid, jid, txt, n)

            def _read_out():
                # streaming: parse stream-json into the live tape (assistant turns) + the final reply.
                # plain: accumulate raw stdout (the unchanged default).
                if streaming:
                    out_holder["text"] = reduce_stream_json(_readline_iter(proc.stdout), _on_update)
                else:
                    out_holder["text"] = _stream_lines(proc.stdout, _on_update)

            def _read_err():
                try:
                    for ln in proc.stderr:
                        err_buf.append(ln)
                except (ValueError, OSError):
                    pass

            t_out = threading.Thread(target=_read_out, daemon=True)
            t_err = threading.Thread(target=_read_err, daemon=True)
            t_out.start(); t_err.start()
            # every main-chat ask (orchestrator or a named seat) does real web work and `claude -p` only
            # prints on completion — so the ceiling must clear minutes, not 300s, or a deep ask is killed
            # before it emits ("no output produced"). A quick question still returns fast; HEAVY multi-agent
            # commands (/gauntlet, /council, /pipeline) get a larger ceiling (detected from the prompt).
            # CEX_ASK_TIMEOUT overrides. (The quick Concierge dock is a separate, shorter lane.)
            timeout_s = ask_timeout_seconds(os.environ.get("CEX_ASK_TIMEOUT"), prompt=text)
            deadline = time.monotonic() + timeout_s
            timed_out = False
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    timed_out = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                time.sleep(0.1)
            t_out.join(timeout=2); t_err.join(timeout=2)
            if timed_out:
                # surface the timeout (preserving any partial output) AND clear the pending wait, so the
                # chat doesn't sit on 'thinking…' after the Working lane empties.
                self.call_from_thread(self._deliver_error, uid, jid,
                                      ask_failure_message("timeout", timeout_s=timeout_s,
                                                          partial=out_holder.get("text", "")), agent_label)
                return
            out = out_holder.get("text", "")
            reply = (out or "").strip() or ("".join(err_buf)).strip()
        except FileNotFoundError:
            self.call_from_thread(self._deliver_error, uid, jid,
                                  ask_failure_message("cli_missing"), agent_label); return
        except Exception as exc:
            try:
                if proc:
                    proc.kill()
            except Exception:
                pass
            self.call_from_thread(self._deliver_error, uid, jid,
                                  ask_failure_message("error", exc=exc), agent_label); return
        cancelled = self._inflight.get(jid, {}).get("cancelled", False)
        self.call_from_thread(self._stream_clear, uid)
        self.call_from_thread(self._inflight_done, jid)
        if cancelled:                                  # the operator stopped this run — drop the reply
            return
        reply = reply or "(no output — check CEX_ASK_CMD permission flags)"
        _post("/agent/activity", {"agent": agent_label, "kind": "reply", "summary": reply[:180], "text": reply[:6000]})
        # Gemini reports live in the agy brain — save a copy to research/ so Claude agents can read them
        if provider == "gemini":
            try:
                tk_save, _ = self._thread_meta(uid)
                if tk_save and tk_save not in ("—", "book"):
                    self._save_research(tk_save, agent_label, text[:120], reply)
            except Exception:
                pass
        # Deliver the answer straight to the conversation tree under the EXACT question that asked it
        # (uid). The old path posted to /agent/activity and waited for the reply to round-trip back via
        # a /state poll, folding it under the GLOBAL _pending_user — which raced: answers surfaced only
        # on the next keystroke and landed in the wrong thread. (The post above stays for the AGENT
        # STREAM / activity log.)
        self.call_from_thread(self._deliver_reply, uid, reply, agent_label)
        self.call_from_thread(self._status, Text("✓ reply in the Book tab", style=GREEN))

    def _deliver_error(self, uid: str, jid: int, msg: str, agent: str = "claude") -> None:
        """A background ask ended WITHOUT a usable reply — timeout, missing CLI, or an exception. Clear
        the live preview + the Working-lane entry AND surface the reason as a reply in the thread, so
        the chat never hangs on 'thinking…' after the lane empties. (The failure paths used to drop the
        job but leave _pending_user set — the lane went to 0 while the thread stayed 'thinking'.) Lighter
        than _deliver_reply: no memory autosave / done-board / watch-ticker scan — an error isn't research.
        Every UI touch is best-effort so this is safe to unit-test on an unmounted app."""
        self._stream_buf.pop(uid, None)
        self._inflight.pop(jid, None)
        aid = self._new_node("agent", msg, uid, agent=agent)
        if self._pending_user == uid:                  # clear the wait only for THIS ask, not a newer one
            self._pending_user = None
        if self._active == uid:
            self._active = aid
        for _paint in (self._render_agents,
                       lambda: self.query_one("#agent_reply", Static).update(self._conversation_markup()),
                       lambda: self.query_one("#spine", VerticalScroll).scroll_end(animate=False),
                       lambda: self._status(Text(_clip(msg, 80), style=ORANGE))):
            try:
                _paint()
            except Exception:
                pass

    def _render_agent_reply(self, state) -> None:
        # Just a live re-render of the conversation. Cockpit asks now fold their reply into the tree
        # from the worker that produced it (``_deliver_reply``), bound to the exact question node — so
        # there is nothing to reconcile from ``state.agent_reply`` here. (The old path folded
        # state.agent_reply under the GLOBAL _pending_user on a /state poll, which raced: answers
        # surfaced only on the next keystroke and landed in the wrong thread.)
        self.query_one("#agent_reply", Static).update(self._conversation_markup())

    def _autosave_thread_to_memory(self, root_id: str) -> None:
        """Write (or supersede) a 'thread' entry in living memory for the completed conversation
        rooted at root_id. Uses meta.thread_root_id for deduplication so re-runs update in place."""
        mem = self._memory()
        if mem is None:
            return
        root = self._conv.get(root_id) or {}
        nodes = sorted((n for n in self._conv.values() if self._branch_root(n["id"]) == root_id),
                       key=lambda n: n["ts"])
        if not nodes:
            return
        ticker = root.get("ticker")
        title = str(root.get("text", ""))[:80]
        full_text = "\n\n".join(
            ("You: " if n.get("role") == "you" else f"{n.get('agent', 'claude')}: ")
            + str(n.get("text", "")) for n in nodes)
        try:
            # supersede any prior entry for this root so we don't accumulate duplicates
            existing = mem.query(type="thread", limit=60)
            for e in existing:
                if (e.get("meta") or {}).get("thread_root_id") == root_id:
                    mem.supersede(e["id"], type="thread", text=title, ticker=ticker,
                                  meta={"thread_root_id": root_id, "full_text": full_text})
                    return
            mem.write(type="thread", text=title, ticker=ticker,
                      meta={"thread_root_id": root_id, "full_text": full_text})
        except Exception:
            pass

    def _stream_partial(self, uid: str, jid: int, text: str, n_lines: int) -> None:
        """H1 — a chunk of the agent's reply landed mid-run (called from the worker via
        call_from_thread). Stash the partial for the live preview, beat the Working-lane heartbeat
        (line count + the latest line + a fresh timestamp), and repaint the spine + agents strip so
        the desk reads the analyst think instead of watching a dead spinner."""
        self._stream_buf[uid] = text
        j = self._inflight.get(jid)
        if j is not None:
            j["lines"] = int(n_lines)
            j["heartbeat"] = time.time()
            j["tail"] = (text.strip().splitlines() or [""])[-1][:80]
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass
        try:
            self._render_agents()
        except Exception:
            pass

    def _stream_clear(self, uid: str) -> None:
        """Drop the live-preview buffer for a thread once its run finishes, is cancelled, or errors —
        the finished reply (or nothing) takes over from here."""
        self._stream_buf.pop(uid, None)

    def _deliver_reply(self, uid: str, text: str, agent: str = "claude") -> None:
        """Fold a finished agent reply into the conversation tree under the EXACT question node that
        asked it (``uid``) — never a global pending flag. Deterministic + thread-correct: the worker
        already knows which question this answers, so a reply can't land in another thread, and it
        appears the instant the run finishes (no /state poll round-trip)."""
        if not self.is_running:
            return
        self._stream_buf.pop(uid, None)                # the streamed preview is now the real node
        # the live tape already showed the 'I will…' process log; the STORED message is the actionable
        # result so the thread doesn't read as a wall of narration. Raw kept on the node for audit.
        shown = condense_reply(text)
        aid = self._new_node("agent", shown, uid, agent=agent)
        if shown != text:
            self._conv[aid]["raw"] = text
        if self._pending_user == uid:                 # clear the wait only for THIS ask, not a newer one
            self._pending_user = None
        if self._active == uid:                       # keep the operator on the thread only if they
            self._active = aid                        # haven't already navigated away
        root = self._branch_root(aid)
        tk = (self._conv.get(root) or {}).get("ticker") or "—"
        summary = reply_gist(text, 90) or (str(text).strip().splitlines() or [""])[0]
        self._record_done_run(agent, tk, summary, cat="thread", ref=root)   # Hub Done board + auto-open
        self._autosave_thread_to_memory(root)
        # auto-add exchange-suffixed tickers mentioned in the reply to the watchlist bench
        for wtk in self._extract_watch_tickers(text):
            self._add_to_watchlist(wtk, note=f"via {agent}", source=agent)
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass
        try:
            self.query_one("#spine", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass
        try:
            if isinstance(self.screen, HubScreen):
                self._render_hub_feed()
                self.screen.query_one("#hub_feed_scroll", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _council_strip(self, tk) -> list:
        """The Dialectic Council reconciliation for the focused name — inline on the Book page,
        sharing THIS conversation (no separate tab). Collapsed: the verdict + φ/ρ/invalidation +
        a click to expand. Expanded (``self._council_open``): the full Bull / Bear / Arbiter
        debate, action buttons that post into this same chat, and the living research thread.
        Empty when no name is focused."""
        tk = (tk or "").strip()
        b = self._baskets_by_ticker.get(tk) if tk else None
        if not b:
            return []
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) or {}
        T = pil.get("T", {}) or {}
        gate = b.get("gate", {}) or {}
        L, _ccy_sfx = _native_ladder(b)        # native ladder: the invalidation/floor leg shows in the
        rating = b.get("rating")               # name's OWN currency, reconciling with the USD main card
        # (the CAD rating ladder rendered a USD floor as C$4.45 next to its $3.13 native twin — a phantom level)
        hc = health_color(rating)
        rule = f"[{BORDER}]{'─' * 52}[/]"

        def g(x, s="{:.2f}"):
            v = _num(x)
            return s.format(v) if v is not None else "—"

        # reconciled verdict from Living Memory (None until a /council run lands) → else engine directive
        verdict_txt, vcol, verdict = str(b.get("directive", "—")), SILVER, None
        contested = False
        mem = self._memory()
        if mem is not None:
            try:
                verdict = mem.latest(ticker=tk, type="council_verdict")
                if verdict:
                    meta = verdict.get("meta", {}) or {}
                    conv_str, contested = _council_convergence(meta)
                    verdict_txt = f"{meta.get('stance', '')}" + (f" · {conv_str}" if conv_str else "")
                    vcol = ORANGE if contested else GREEN
            except Exception:
                verdict = None                              # a malformed verdict must never crash the card

        caret = "hide debate ⌃" if self._council_open else "full debate ⌄"
        badge = f"  [{ORANGE}]⚖ contested[/]" if contested else ""
        out = [
            f"[b {GOLD}]⚖ COUNCIL[/] [b white]{self._esc(tk)}[/] [{hc}]{_fmt(rating)}/10[/]"
            f"  [{vcol}]{self._esc(verdict_txt)}[/]{badge}"
            f"   [@click=app.toggle_council][{TEAL}]{caret}[/][/]",
            f"[@click=app.explain('phi')][{DIM}]φ[/] {g(V.get('floor_coverage'))}[/]  "
            f"[@click=app.explain('rho')][{DIM}]ρ[/] {g(V.get('rho'))}[/]  "
            f"[@click=app.explain('upside')][{DIM}]upside[/] {g(V.get('upside_pct'),'{:.0f}%')}[/]  "
            f"[{DIM}]invalidation[/] [{RED}]{_money(L.get('floor'))}[/]   [{DIM}]regime composes posture[/]",
        ]
        if not self._council_open:
            out.append(rule)
            return out

        # ── expanded: the full debate (formerly the Council tab), inline above the chat ──
        out.append(rule)
        out.append(f"[bold {GREEN}]BULL — asymmetry (engine-grounded)[/]")
        out.append(f"  φ floor-coverage [{GREEN if (_num(V.get('floor_coverage')) or 0) >= 1 else SILVER}]"
                   f"{g(V.get('floor_coverage'))}[/]   ρ payoff [{SILVER}]{g(V.get('rho'))}[/]"
                   f"   upside [{SILVER}]{g(V.get('upside_pct'),'{:.0f}%')}[/]")
        out.append(f"  tailwind [{SILVER}]{g(T.get('score'),'{:.1f}')}[/] [{DIM}]({self._esc(str(T.get('commodity','—')))})[/]"
                   f"   ladder [{DIM}]floor[/] {_money(L.get('floor'))} [{DIM}]· base[/] "
                   f"{_money(L.get('base'))} [{DIM}]· bull[/] {_money(L.get('bull'))}")
        out.append("")
        out.append(f"[bold {RED}]BEAR + LIQUIDITY SENTINEL — invalidation[/]")
        out.append(f"  hard invalidation [{RED}]{_money(L.get('floor'))}[/] [{DIM}](floor leg)[/]")
        gcap = gate.get("cap")
        cap_str = "" if gcap is None else f" — cap {g(gcap, '{:.1f}')}"
        if gate.get("applied"):
            out.append(f"  [{ORANGE}]⚠ forensic gate active{cap_str}: {self._esc(str(gate.get('reason',''))[:40])}[/]")
        else:
            out.append(f"  [{DIM}]forensic gate clear (JSF){cap_str} · dilution / liquidity / exit-friction "
                       f"surface on a live /council run[/]")
        out.append(rule)
        out.append(f"[bold {AMBER}]ARBITER — single reconciled verdict[/]")
        if verdict:
            meta = verdict.get("meta", {}) or {}
            out.append(f"  [bold {hc}]{self._esc(verdict.get('text','') or meta.get('stance',''))}[/]")
            if meta.get("tension"):
                out.append(f"  [{DIM}]tension:[/] [{ORANGE}]{self._esc(str(meta['tension'])[:72])}[/]")
            for cav in (meta.get("caveats") or [])[:3]:
                out.append(f"  [{DIM}]⚑[/] [{SILVER}]{self._esc(str(cav)[:72])}[/]")
        else:
            out.append(f"  [{SILVER}]{self._esc(str(b.get('directive','—')))}[/]  [{DIM}](engine directive)[/]")
            posture = (self._state or {}).get("posture") or {}
            if _num(posture.get("cap")) is not None and posture.get("cap") != 1.0:
                pc = GREEN if not posture.get("headwind") else ORANGE
                out.append(f"  [{DIM}]posture composes:[/] [{pc}]{self._esc(str(posture.get('label','')))} "
                           f"{posture['cap']:g}x[/]")
            out.append(f"  [{DIM}]No Council verdict yet — run[/] [{TEAL}]/council {self._esc(tk)}[/] "
                       f"[{DIM}]to convene the full debate.[/]")
        # action buttons — they post into THIS shared conversation (the merge: book + council = one chat)
        out.append(f"  [@click=app.council_ask('rerun')][{GOLD} on #141418] ↻ Re-run with memory [/]   "
                   f"[@click=app.council_ask('save')][{SILVER} on #141418] ⇪ Save as prior [/]   "
                   f"[@click=app.council_ask('outcomes')][{TEAL} on #141418] ⊹ Pull outcomes [/]")
        # the name's LIVING research thread (notes / verdicts / outcomes) — type "note: …" to add one
        if mem is not None:
            try:
                thread = [e for e in mem.query(ticker=tk, limit=8)
                          if e.get("type") != "pin" and not (e.get("meta") or {}).get("retracted")][:6]
            except Exception:
                thread = []
            out.append(rule)
            out.append(f"[bold {TEAL}]RESEARCH THREAD[/]  [{DIM}]living memory[/]")
            if thread:
                glyphs = {"note": "✎", "council_verdict": "⚖", "thesis": "◆", "scenario_prior": "⊹",
                          "outcome": "✓", "regime_snapshot": "◷", "decision": "▸", "catalyst": "⛏",
                          "thread": "↯", "pin": "📌"}
                for e in thread:
                    gl = glyphs.get(e.get("type"), "·")
                    when = str(e.get("ts", ""))[:10]
                    out.append(f"  [{DIM}]{when}[/] {gl} [{SILVER}]{self._esc(str(e.get('text',''))[:54])}[/]"
                               f"  [{DIM}]{self._esc(str(e.get('source','')))}[/]")
            else:
                out.append(f"  [{DIM}]empty — type[/] [{TEAL}]note: <your observation>[/] "
                           f"[{DIM}]to start this name's thread.[/]")
        out.append(rule)
        return out

    def action_toggle_council(self) -> None:
        """Expand / collapse the inline Council debate on the Book page — no tab switch."""
        self._council_open = not self._council_open
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
            if self._council_open and not self._active:
                self.query_one("#spine", VerticalScroll).scroll_home(animate=False)
        except Exception:
            pass

    def action_council_ask(self, kind: str) -> None:
        """The Council action buttons route into the shared conversation (one chat for book+council)."""
        tk = self._focus or ""
        text = {"rerun": f"re-run the council on {tk} with latest memory",
                "save": f"save the council verdict on {tk} as a scenario prior",
                "outcomes": f"pull related outcomes for {tk}"}.get(kind)
        if text:
            self._ask_agent(text)

    def action_go_council(self) -> None:
        """Convene the Council — expands the debate INLINE on the Book page (the shared chat),
        rather than opening a separate tab."""
        self._council_open = True
        self.action_tab("book")
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
            if not self._active:
                self.query_one("#spine", VerticalScroll).scroll_home(animate=False)
        except Exception:
            pass

    def _thinking_lines(self, uid: str) -> list:
        """The live 'thinking' indicator for a pending thread (H1). When the agent's reply is
        streaming in, show its trailing lines — you read the analyst think — instead of a dead
        spinner; before any text lands, a plain ⟳ thinking…."""
        e = self._esc
        partial = (self._stream_buf.get(uid) or "").strip()
        if not partial:
            return [f"  [{TEAL}]⟳ thinking…[/]"]
        out = [f"  [{TEAL}]⟳ streaming…[/]"]
        for ln in partial.splitlines()[-3:]:
            out.append(f"  [{DIM}]{e(_clip(ln, 78))}[/]")
        return out

    def _conversation_markup(self) -> str:
        """Compact research strip for the Book spine — council verdict + latest threads for this name.
        Full conversation lives in the Hub (press h). "↩ hub" on any card loads context and opens it."""
        lines = list(self._council_strip(self._focus))   # Council reconciliation strip (always shown)
        e = self._esc

        # Latest threads for the focused name (or the 3 most recent if no name focused)
        focus_tk = self._focus or ""
        name_threads = sorted(
            [r for r in self._roots() if (r.get("ticker") or "") == focus_tk or not focus_tk],
            key=lambda r: r.get("ts", 0), reverse=True)[:3]

        if name_threads or self._pending_user:
            suffix = (' - ' + e(focus_tk)) if focus_tk else ''
            lines.append(f"[{DIM}]-- latest research{suffix} --[/]")

        for root in name_threads:
            rid = root["id"]
            all_nodes = sorted([n for n in self._conv.values()
                                if self._branch_root(n["id"]) == rid], key=lambda n: n.get("ts", 0))
            latest = all_nodes[-1] if all_nodes else root
            is_agent = latest.get("role") != "you"
            age = _rel_age(latest.get("ts", root.get("ts", 0)))
            summary = e(_clip(str(root.get("text", "")), 30))
            # show the last agent reply (collapsed)
            if is_agent:
                body = e(_clip(str(latest.get("text", "")), 80))
                agent_nm = latest.get("agent") or "claude"
                lines.append(f"[b {GREEN}]{agent_nm} ‹[/] [{DIM}]{age}[/]  [{SILVER}]{body}[/]")
            else:
                lines.append(f"[b {TEAL}]you ›[/] [{DIM}]{age}[/]  [{SILVER}]{summary}[/]")
            if self._pending_user and self._branch_root(self._pending_user) == rid:
                lines.extend(self._thinking_lines(self._pending_user))
            lines.append(f"  [@click=app.hub_ctx('{rid}')][{TEAL}]↩ continue in Hub[/][/]")

        if self._pending_user and not any(self._branch_root(self._pending_user) == r["id"] for r in name_threads):
            lines.extend(self._thinking_lines(self._pending_user))

        if not self._conv:
            lines.append(f"[{DIM}]Ask anything below — replies and research live in the Hub (h).[/]")

        # quick entry hint at the bottom
        n_total = len(self._roots())
        if n_total > len(name_threads):
            lines.append(f"[{DIM}]  +{n_total - len(name_threads)} more threads · all in Hub[/]")
        lines.append(f"\n[@click=app.open_hub()][{DIM}]⇒ open Hub for full research feed[/][/]")
        return "\n".join(lines)

    def _hide_cmd(self) -> None:
        """Drop from chat to keyboard-nav mode (the bar stays visible; single-key binds work again)."""
        try:
            self.query_one("#cmdbar", Input).value = ""
            self.set_focus(None)            # blur → app-level single-key binds (q/w/e/d/g) fire again
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            try:
                if self.focused is self.query_one("#cmdbar", Input):
                    self._hide_cmd()                       # Esc → keyboard-nav (1-4 tabs, q, etc.)
                    event.stop()
            except Exception:
                pass

    def action_confirm(self) -> None:
        if self._pending:
            self._do_confirm(self._pending[0].get("id"))

    # ---- one-key dispatch: Claude -> its pane; Antigravity -> headless research ----
    def action_ask(self, which: str) -> None:
        """`a`/`x` fire a grounded prompt into the Claude pane; `b` runs Antigravity headless."""
        tk = self._focus
        if not tk:
            self._status(Text("focus a name first", style=ORANGE)); return
        if which == "analyst":
            self._dispatch("CLAUDE", "claude",
                           f"@conviction-analyst why is {tk} rated this? Ground in the live engine state.")
        elif which == "dossier":
            self._dispatch("CLAUDE", "claude", f"/dossier {tk}")
        elif which == "bear":
            self._agy_research(
                f"Red-team the investment thesis for {tk}, a precious-metals name. Give the strongest, "
                f"most specific bear case: valuation, dilution / financing risk, jurisdiction, execution, "
                f"and the concrete signals that would invalidate the bull case.", "bear-case")

    def _find_pane(self, keyword: str):
        """Resolve a tmux pane id by its border title (set by cockpit.sh). Cockpit-only."""
        if not os.environ.get("TMUX"):
            return None
        for scope in (["-s", "-t", SESSION], ["-a"]):
            try:
                r = subprocess.run(["tmux", "list-panes", *scope, "-F", "#{pane_id}\t#{pane_title}"],
                                   capture_output=True, text=True, timeout=1.0)
                for ln in r.stdout.splitlines():
                    pid, _, title = ln.partition("\t")
                    if keyword.lower() in title.lower():
                        return pid
            except Exception:
                pass
        return None

    # ---- Antigravity as a headless research backend (web-auth'd CLI, no API key) ----
    def _agy_argv(self, prompt: str):
        """One-shot Antigravity/Gemini invocation. Flags vary by CLI, so it's configurable:
        CEX_AGY_HEADLESS (default 'agy -p {prompt}'); {prompt} is substituted, else appended."""
        import shlex
        binary = os.environ.get("CEX_AGY_CMD", "agy")
        tmpl = os.environ.get("CEX_AGY_HEADLESS", f"{binary} -p {{prompt}}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            return [prompt if p == "{prompt}" else p for p in parts]
        return parts + [prompt]

    def _save_research(self, tk: str, tag: str, prompt: str, result: str) -> str:
        import datetime
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{tk}_{tag}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
        with open(path, "w") as f:
            f.write(f"# Antigravity {tag} — {tk}\n\n_{datetime.datetime.now():%Y-%m-%d %H:%M}_\n\n"
                    f"**Prompt:** {prompt}\n\n---\n\n{result}\n")
        return path

    @work(thread=True, group="research")
    def _agy_research(self, prompt: str, tag: str) -> None:
        tk = self._focus or "?"
        self.call_from_thread(self._status, Text(f"⟳ Antigravity {tag} on {tk}… (headless, up to ~2 min)", style=TEAL))
        _post("/agent/activity", {"agent": "antigravity", "kind": "prompt", "summary": f"{tag}: {tk}", "ticker": tk})
        try:
            out = subprocess.run(self._agy_argv(prompt), capture_output=True, text=True, timeout=180)
            result = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._status, Text("agy CLI not found — set CEX_AGY_CMD / CEX_AGY_HEADLESS", style=ORANGE))
            _post("/agent/activity", {"agent": "antigravity", "kind": "alert", "summary": "CLI not found", "ticker": tk}); return
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._status, Text("Antigravity timed out (180s)", style=ORANGE))
            _post("/agent/activity", {"agent": "antigravity", "kind": "alert", "summary": f"{tag} timed out", "ticker": tk}); return
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"research failed: {exc}", style=ORANGE)); return
        if not result:
            self.call_from_thread(self._status, Text("Antigravity returned nothing — check CEX_AGY_HEADLESS flag", style=ORANGE)); return
        path = self._save_research(tk, tag, prompt, result)
        _post("/agent/activity", {"agent": "antigravity", "kind": "note",
                                  "summary": f"{tag} ready → {os.path.basename(path)} ({len(result)}c)", "ticker": tk})
        self.call_from_thread(self._status, Text(f"✓ Antigravity {tag} saved → {path}", style=GREEN))

    # ---- background research pipeline (headless agent; the interactive panes stay free) ----
    def _pipeline_argv(self, prompt: str, agent: str = None):
        """Headless launch for the pipeline / workflow stages. Configurable: CEX_PIPELINE_CMD
        (default 'claude -p {prompt}'). When the stage names an agent, the OUTER session runs on
        that agent's registry model too (sonnet seats run sonnet end-to-end — the subagent pin
        alone doesn't govern the wrapper). Effort: CEX_PIPELINE_EFFORT, default high."""
        import shlex
        tmpl = os.environ.get("CEX_PIPELINE_CMD", "claude -p {prompt}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            parts = [prompt if p == "{prompt}" else p for p in parts]
        else:
            parts = parts + [prompt]
        # the seat's honest model — a gemini seat falling back to Claude runs sonnet, not opus
        model = _run_model_label(agent, "claude") if agent and agent in HUB_AGENT_META else None
        return self._inject_model_flags(parts, tmpl, model,
                                        os.environ.get("CEX_PIPELINE_EFFORT", "high"))

    @work(thread=True, group="pipeline", exclusive=True)
    def _run_pipeline_bg(self, theme: str, mode: str = "pipeline") -> None:
        prompt = f"/pipeline {theme}" if mode == "pipeline" else f"scout for {theme}"
        _post("/pipeline/event", {"status": "running", "stage": "scout", "theme": theme,
                                  "message": f"launching headless {mode}…"})
        self.call_from_thread(self._status, Text(
            f"⟳ {mode} running in background: {theme} — your chat stays free (watch PIPELINE)", style=TEAL))
        try:
            out = subprocess.run(self._pipeline_argv(prompt), capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_PIPELINE_TIMEOUT", "900")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            result = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            _post("/pipeline/event", {"status": "error", "message": "CLI not found — set CEX_PIPELINE_CMD"})
            self.call_from_thread(self._status, Text("pipeline: CLI not found — set CEX_PIPELINE_CMD", style=ORANGE)); return
        except subprocess.TimeoutExpired:
            _post("/pipeline/event", {"status": "error", "message": "timed out"})
            self.call_from_thread(self._status, Text("pipeline timed out — raise CEX_PIPELINE_TIMEOUT / check permissions", style=ORANGE)); return
        except Exception as exc:
            _post("/pipeline/event", {"status": "error", "message": str(exc)[:80]})
            self.call_from_thread(self._status, Text(f"pipeline failed: {exc}", style=ORANGE)); return
        tail = (result[-3500:] if result else "(no output — check CEX_PIPELINE_CMD permission flags)")
        _post("/pipeline/event", {"status": "done", "stage": "done", "result": tail, "message": "complete"})
        self.call_from_thread(self._status, Text(f"✓ {mode} complete: {theme}", style=GREEN))

    @work(thread=True, group="dispatch")
    def _dispatch(self, keyword: str, agent_label: str, prompt: str) -> None:
        pane = self._find_pane(keyword)
        if not pane:
            self.call_from_thread(self._status,
                                  Text(f"no '{keyword}' pane — run inside the cockpit (./cockpit.sh)", style=ORANGE))
            return
        try:
            subprocess.run(["tmux", "send-keys", "-t", pane, prompt, "Enter"], timeout=1.0)
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"dispatch failed: {exc}", style=ORANGE)); return
        # Log the dispatch onto the bus so it shows in the stream even for agents without hooks.
        _post("/agent/activity", {"agent": agent_label, "kind": "prompt", "summary": prompt, "ticker": self._focus})
        self.call_from_thread(self._status, Text(f"→ sent to {agent_label}: {prompt[:44]}", style=GREEN))

    # ------------------------------------------------------------------ what-if
    def _do_whatif(self) -> None:
        ticker = self.query_one("#wf_ticker", Input).value.strip()
        overrides = self.query_one("#wf_overrides", Input).value.strip()
        if ticker:
            self._set_focus(ticker, move_cursor=True)
        # a plain-text idea (a phrase with no '=') → translate to overrides via a background agent
        if overrides and "=" not in overrides and len(overrides.split()) > 1:
            self._wf_prototype_bg(overrides, ticker)
            return
        self.query_one("#wf_result", Static).update(Text("running what-if…", style=AMBER))
        self._run_whatif(ticker, overrides)

    @work(thread=True, group="whatif")
    def _run_whatif(self, ticker: str, overrides: str) -> None:
        res = _post("/action/whatif", {"ticker": ticker, "overrides": overrides})
        self.call_from_thread(self._show_whatif, res, overrides)

    def _show_whatif(self, res: dict, overrides: str, record: bool = True) -> None:
        out = self.query_one("#wf_result", Static)
        if not res or res.get("error"):
            out.update(Text(f"⚠ {res.get('error','no result') if res else 'no result'}", style=ORANGE))
            return
        base, scen, delta = res.get("base", {}), res.get("scenario", {}), res.get("delta", {})
        tk = res.get("ticker", "?")
        bi, si = _num(base.get("intrinsic")), _num(scen.get("intrinsic"))
        price = _num(res.get("price"))
        dp = _num(delta.get("intrinsic_pct"))
        # remember this run so it can be pinned as the A/B baseline (and re-rendered on pin/unpin)
        self._wf_last = {"overrides": overrides, "intrinsic": si,
                         "upside_pct": _num(scen.get("upside_pct")), "ticker": tk}
        self._wf_last_res = (res, overrides)

        head = Text()
        head.append(f"{tk}  ", style=f"bold {GOLD}")
        head.append(f"({res.get('archetype','—')})   ", style=DIM)
        head.append("source: ", style=DIM)
        head.append("agent ↯" if self._wf_source == "agent" else "you", style=(GREEN if self._wf_source == "agent" else SILVER))

        applied = Text("applied: ", style=DIM)
        ap = res.get("overrides_applied", {}) or {}
        applied.append(", ".join(f"{k} {v.get('from')}→{v.get('to')}" if isinstance(v, dict) else f"{k}={v}"
                                 for k, v in ap.items()) or "—", style=SILVER)

        cols = Text()
        cols.append(f"\n{'':10}{'BASE':>12}{'SCENARIO':>12}\n", style=AMBER)
        cols.append(f"{'intrinsic':10}{_fmt(bi):>12}{_fmt(si):>12}\n", style=SILVER)
        cols.append(f"{'upside %':10}{_fmt(base.get('upside_pct')):>12}{_fmt(scen.get('upside_pct')):>12}\n",
                    style=SILVER)

        dl = Text("\nΔ intrinsic ", style=DIM)
        dl.append(f"{_fmt(dp)}%  ", style=(GREEN if (dp or 0) >= 0 else RED))
        dl.append_text(_delta_bar(dp))
        dl.append(f"   Δ upside {_fmt(delta.get('upside_pp'))}pp", style=SILVER)

        # granularity: per-leg base→scenario breakdown so the user sees *which* components moved
        blegs = base.get("legs") or {}; slegs = scen.get("legs") or {}
        legkeys = [k for k in list(blegs) + [x for x in slegs if x not in blegs]
                   if _num(blegs.get(k)) is not None or _num(slegs.get(k)) is not None]
        legs_txt = None
        if legkeys:
            legs_txt = Text(f"\n{'valuation legs':<14}{'BASE':>11}{'SCENARIO':>11}{'Δ':>9}\n", style=AMBER)
            for k in legkeys[:8]:
                b_, s_ = _num(blegs.get(k)), _num(slegs.get(k))
                d_ = (s_ - b_) if (b_ is not None and s_ is not None) else None
                legs_txt.append(f"{str(k)[:14]:<14}{_fmt(b_):>11}{_fmt(s_):>11}", style=SILVER)
                legs_txt.append(f"{(f'{d_:+.2f}' if d_ is not None else '—'):>9}\n",
                                style=(GREEN if (d_ or 0) >= 0 else RED))

        # A/B: pin a scenario as baseline A, step knobs to B, see B vs A (not just vs base)
        ab = Text()
        pin = self._wf_pinned
        if pin and _num(pin.get("intrinsic")):
            pa = _num(pin["intrinsic"])
            dA = ((si - pa) / pa * 100.0) if (si is not None and pa) else None
            su, pu = _num(scen.get("upside_pct")), _num(pin.get("upside_pct"))
            ab.append("\nA/B  ", style=f"bold {AMBER}")
            ab.append(f"vs A [{pin.get('overrides') or '(base)'}]  ", style=DIM)
            ab.append(f"Δ {_fmt(dA)}%", style=(GREEN if (dA or 0) >= 0 else RED))
            ab.append_text(_delta_bar(dA, 15))
            if su is not None and pu is not None:
                ab.append(f"   Δ upside {su - pu:+.1f}pp", style=SILVER)
            ab.append("   ")
            ab.append("✕ unpin", style=Style.parse(DIM) + Style(meta={"@click": "app.wf_unpin"}))
        else:
            ab.append("\n")
            ab.append("⊹ pin this as A/B baseline", style=Style.parse(TEAL) + Style(meta={"@click": "app.wf_pin"}))

        bar, legend = _ladder([("F", (base.get("legs") or {}).get("cost"), ORANGE),
                               ("●", price, "white"),
                               ("◆", bi, GOLD),
                               ("✦", si, GREEN)])
        ladder = Group(Text("\nvalue ladder  (F floor · ● price · ◆ base intrinsic · ✦ scenario)", style=DIM),
                       bar, legend)

        groups = [head, applied, cols, dl] + ([legs_txt] if legs_txt else []) + [ab, ladder]
        # the agent-proposed scenario narrative — effects beyond the 7 knobs (shown only for its own run)
        if self._wf_scenario_brief and overrides == self._wf_scenario_ov:
            sc = Text("\n\nSCENARIO  ", style=f"bold {TEAL}")
            sc.append("agent-proposed · effects beyond the knobs\n", style=DIM)
            sc.append(self._wf_scenario_brief, style=SILVER)
            groups.append(sc)
        out.update(Group(*groups))
        if record:
            self._push_history(tk, overrides, dp)
            self._wf_source = "you"

    def _push_history(self, tk, overrides, dp) -> None:
        line = Text("↳ ", style=AMBER)
        line.append(f"{tk} ", style="bold white")
        line.append(f"{overrides or '(none)'}  ", style=DIM)
        line.append(f"Δ{_fmt(dp)}%", style=(GREEN if (dp or 0) >= 0 else RED))
        self._wf_hist.insert(0, line)
        del self._wf_hist[5:]                          # keep a short, scannable iteration trail
        self.query_one("#wf_history", Static).update(Text("\n").join(self._wf_hist))

    def action_wf_pin(self) -> None:
        """Pin the current what-if result as the A/B baseline (scenario A) — runs then show Δ vs A,
        so you can pin a thesis, step the knobs to a variant, and read the difference directly."""
        if not self._wf_last or self._wf_last.get("intrinsic") is None:
            self._toast("run a what-if first, then pin it as A", ORANGE); return
        self._wf_pinned = dict(self._wf_last)
        self._toast(f"⊹ pinned A: {self._wf_pinned.get('overrides') or '(base)'} — runs now show Δ vs A", TEAL)
        if self._wf_last_res:
            self._show_whatif(self._wf_last_res[0], self._wf_last_res[1], record=False)

    def action_wf_unpin(self) -> None:
        self._wf_pinned = None
        self._toast("unpinned A/B baseline", DIM)
        if self._wf_last_res:
            self._show_whatif(self._wf_last_res[0], self._wf_last_res[1], record=False)

    def _load_scenario(self, name: str) -> None:
        name = (name or "").strip()
        match = next((s for s in self._scenarios if s.get("name") == name), None)
        box = self.query_one("#wf_overrides", Input)
        if not match:
            self._status(Text(f"no saved scenario '{name}'", style=ORANGE))
            return
        ov = match.get("overrides", {})
        box.value = " ".join(f"{k}={v}" for k, v in ov.items()) if isinstance(ov, dict) else str(ov)
        self._active_scenario = name
        self._status(Text(f"loaded scenario '{name}'", style=GREEN))

    @work(thread=True, group="scen")
    def _do_save(self, name: str) -> None:
        overrides = self.query_one("#wf_overrides", Input).value.strip()
        ov = parse_overrides(overrides)
        if not name or not ov:
            self.call_from_thread(self._status, Text("need a name and overrides to save", style=ORANGE))
            return
        res = _post("/config/scenario", {"name": name, "overrides": ov})
        ok = res.get("ok")
        self._active_scenario = name if ok else self._active_scenario
        msg = (f"saved scenario '{name}'" if ok else f"save failed: {res.get('error')}")
        self.call_from_thread(self._status, Text(msg, style=(GREEN if ok else ORANGE)))
        if ok:
            self.call_from_thread(self._receipt, f"scenario '{name}'", "⇪", AMBER)
        self.refresh_data()

    @work(thread=True, group="confirm")
    def _do_confirm(self, pid) -> None:
        res = _post("/config/confirm", {"id": pid, "source": "cockpit"})
        ok = res.get("ok")
        self.call_from_thread(self._status,
                              Text((f"confirmed #{pid}" if ok else f"confirm failed: {res.get('error')}"),
                                   style=(GREEN if ok else ORANGE)))
        if ok:                                         # engine-applied — receipt records it (no undo)
            self.call_from_thread(self._receipt, f"applied proposal #{pid}", "✓", GREEN)
        self.refresh_data()

    @work(thread=True, group="reject")
    def _do_reject(self, pid) -> None:
        _post("/config/reject", {"id": pid})
        self.call_from_thread(self._receipt, f"rejected proposal #{pid}", "✗", ORANGE)
        self.refresh_data()

    def _dossier_pick(self, val: str) -> None:
        val = (val or "").strip()
        if not self._decisions:
            return
        target = None
        if val.isdigit():
            i = int(val)
            target = self._decisions[i] if 0 <= i < len(self._decisions) else None
        else:
            target = next((d for d in self._decisions
                           if val.upper() in str(d.get("ticker", "")).upper()), None)
        if target:
            self.action_open_dossier(target.get("name"))

    # ------------------------------------------------------------------ slash commands
    def _run_command(self, text: str) -> None:
        text = text.strip()
        if text.startswith("/"):
            text = text[1:]
        if not text:
            return
        parts = text.split()
        verb, rest = parts[0].lower(), parts[1:]
        if verb in ("focus", "f") and rest:
            self.action_tab("book")
            self._set_focus(rest[0].upper(), move_cursor=True)
        elif verb in ("whatif", "wi") and rest:
            self.action_tab("whatif")
            self.query_one("#wf_ticker", Input).value = rest[0].upper()
            if len(rest) > 1:
                self.query_one("#wf_overrides", Input).value = " ".join(rest[1:])
            self._do_whatif()
        elif verb in ("scenario", "scen") and rest:
            self.action_tab("whatif")
            self._load_scenario(rest[0])
        elif verb == "save" and rest:
            self._do_save(rest[0])
        elif verb == "confirm" and rest and rest[0].isdigit():
            self._do_confirm(int(rest[0]))
        elif verb == "reject" and rest and rest[0].isdigit():
            self._do_reject(int(rest[0]))
        elif verb in ("dossier", "doss") and rest:
            self.action_tab("dossier_tab")
            self._set_focus(rest[0].upper())
            self._dossier_pick(rest[0].upper())
        elif verb in ("profile", "prof"):
            self.action_open_profile(rest[0].upper() if rest else (self._focus or ""))
        elif verb in ("council", "debate") and (rest or self._focus):
            if rest:
                self._set_focus(rest[0].upper(), move_cursor=True)
            self.action_go_council()                      # expand the debate inline on the Book page
            self._ask_agent(f"/council {rest[0].upper() if rest else self._focus}")
        elif verb == "note":                              # persist a research note to Living Memory
            self._write_note(" ".join(rest))
        elif verb == "tab" and rest:
            self.action_tab(rest[0])
        elif verb in ("pipeline", "pipe", "scout") and rest:
            self._run_pipeline_bg(" ".join(rest), mode=("scout" if verb == "scout" else "pipeline"))
        elif verb in ("rotate", "swap") and rest:
            inc = rest[0].upper()
            chl = rest[1].upper() if len(rest) > 1 else ""
            if not chl:
                self._status(Text("usage: /rotate <incumbent> <challenger>  (e.g. /rotate URC.TO NXE.TO)", style=DIM))
                return
            self._set_focus(inc, move_cursor=True)
            self._ask_agent(f"/rotate {inc} {chl}")
        elif verb in ("screen", "scr") and rest:
            self._run_screen(rest[0])
        elif verb in ("replace", "repl") and rest:
            self._run_replace(rest[0].upper())
        elif verb in ("change", "chg") and rest:
            self._run_change(rest)
        elif verb in ("gauntlet", "vet", "graduate") and rest:
            self._run_gauntlet(rest[0].upper())
        elif verb in ("explain-move", "explainmove", "explain", "decouple") and rest:
            self._run_explain_move(rest[0].upper())
        elif verb in ("refresh", "r"):
            self.refresh_data()
        else:
            self.action_tab("whatif")
            self._status(Text("commands: /focus TK · /screen slot · /change cut|rotate|reweight · /replace TK · "
                              "/gauntlet TK · /council TK · /rotate INC CHL · /note … · /whatif TK ov… · "
                              "/scenario name · /save name · /confirm id · /reject id · /pipeline theme · "
                              "/tab id · /refresh", style=DIM))

    def _run_screen(self, slot: str) -> None:
        """Run the quantitative discovery screen (slot-fit FIRST, then stage / jurisdiction / mcap /
        survival / REP-floor) over data/candidate_universe.json and land the survivors on the
        WATCHLIST bench — so screening is a one-keystroke, VISIBLE action instead of an invisible MCP
        call, and the bench is fed by the funnel. Accepts loose slot names (silver, uranium, gold,
        holdco); @scout then enriches the survivors (the screen is the funnel, web search the colour)."""
        alias = {
            "silver": "silver-spear", "spear": "silver-spear", "ag": "silver-spear",
            "gold": "gold-royalty-ballast", "royalty": "gold-royalty-ballast",
            "gold-royalty": "gold-royalty-ballast",
            "holdco": "project-generator-holdco", "generator": "project-generator-holdco",
            "project-generator": "project-generator-holdco",
            "electrification": "electrification-royalty", "uranium": "electrification-royalty",
            "u": "electrification-royalty",
            # off-slot / satellite: asymmetric bets OUTSIDE the barbell slots (new sleeves · satellites)
            "satellite": "satellite", "satellites": "satellite", "off-slot": "satellite",
            "offslot": "satellite", "off": "satellite", "freeform": "satellite", "any": "satellite",
            # the macro-correlation / diversifier SECTION — assess the book's single-factor concentration
            # and rank the universe by INDEPENDENCE from it (a section, not a thesis slot)
            "uncorrelated": "uncorrelated", "uncorr": "uncorrelated", "correlation": "uncorrelated",
            "diversifier": "uncorrelated", "diversifiers": "uncorrelated", "macro": "uncorrelated",
            "independence": "uncorrelated",
        }
        slot = alias.get((slot or "").strip().lower(), (slot or "").strip().lower())
        if slot == "uncorrelated":                          # the macro-correlation section, not a slot screen
            self._run_correlation_screen()
            return
        import discovery_screen as ds
        ds.reload_slots()                              # pick up any runtime-created slots
        valid = set(ds.SLOT_RULES) | {"satellite"}     # data-driven: seed four + user-created slots
        if slot not in valid:
            named = " · ".join(sorted(ds.SLOT_RULES)) + " · satellite"
            self._status(Text(f"usage: /screen <slot>  ({named})", style=DIM))
            return
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                "candidate_universe.json")
            uni = ds.load_universe(path)
            cfg_gates = dict(uni.get("screen_config") or {})
            res = ds.screen(uni.get("candidates") or [], slot=slot, gates=(cfg_gates or None))
        except Exception as e:
            self._status(Text(f"screen failed: {e}", style=DIM))
            return
        survivors = res.get("survivors") or []
        # stash survivors so the ◆ 'new slot from this' chip can recover the candidate's screened fields
        self._last_screen_survivors = {str(s.get("ticker") or "").upper(): s for s in survivors}
        added = 0
        for s in survivors:
            tk = str(s.get("ticker") or "").strip().upper()
            if not tk:
                continue
            gaps = s.get("data_gaps") or []
            note = f"screen:{slot}" + (f" · gaps {','.join(gaps)}" if gaps else " · clean")
            if self._add_to_watchlist(tk, note=note, source="screen", status="screened"):
                added += 1
        n_surv = res.get("n_survivors", 0)
        killed = res.get("killed") or []
        substantive = [k for k in killed if k.get("gate") != "slot_fit"]   # slot-relevant kills only
        n_cand = n_surv + len(substantive)
        if n_cand == 0:                                    # no names tagged for this slot — not a "kill"
            msg = f"⛏ screen {slot}: no candidates tagged for this slot · /scout {slot} to populate"
        else:
            msg = f"⛏ screen {slot}: {n_cand} candidate(s) → {n_surv} survived, {len(substantive)} killed"
            if n_surv:
                msg += " → WATCHLIST" + (f" (+{added} new)" if added else "")
        self._status(Text(msg, style=(GREEN if n_surv else DIM)))
        # SCREEN as a JOB SURFACE (the reframe): open the disconfirmation funnel over the result —
        # kill-rate header, survived/gaps/killed lanes with cause-of-death, each pinned to its slot
        # incumbent + best-effort disproof pips. Read-only InspectScreen modal; additive, never blocks
        # the bench-feed above.
        try:
            incumbent = self._slot_incumbent(slot)
            pips = self._disproof_pips([s.get("ticker") for s in survivors if s.get("ticker")])
            title = (f"[bold {AMBER}]▲ SCREEN[/]  [{DIM}]·[/]  [bold {GOLD}]{slot}[/]  "
                     f"[{DIM}]· the disconfirmation funnel[/]")
            acts = (f"[{DIM}]‹ Esc to close[/]    [@click=app.funnel('scout','{slot}')][{TEAL}]/scout {slot}[/][/]"
                    f"    [{FAINT}]click a name to open · ⚑ to disconfirm[/]")
            self.push_screen(InspectScreen(title, _screen_funnel_markup(slot, res, incumbent, pips), acts))
        except Exception:
            pass

    def _run_correlation_screen(self) -> None:
        """SCREEN ⟂ — the macro-correlation SECTION. Assess the book's single-factor concentration (avg
        pairwise ρ + each ballast's ρ to the spear + drift, read from the engine's cached matrix) and
        rank the candidate universe by INDEPENDENCE from the book — measured ρ where price history is
        cached, factor-class proxy otherwise. Read-only InspectScreen; the engine owns the correlation
        math, this only marshals it. Never raises (degrades to a status line)."""
        try:
            import correlation_monitor as cm
            import discovery_screen as ds
            import price_history
            from datetime import date
            state = _get("/state") or {}
            conc = ((state.get("book_factor") or {}).get("concentration")) or {}
            ind = state.get("correlation_independence") or {}
            macro = cm.book_macro_summary(conc, ind)
            spear = conc.get("spear") or "AGA.V"
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            uni = ds.load_universe(os.path.join(data_dir, "candidate_universe.json"))
            cands = uni.get("candidates") or []
            book_tks = [str(t).upper() for t in (self._baskets_by_ticker or {})] or \
                [spear, "GROY", "GMX.TO", "URC.TO"]
            ph = price_history.PriceHistory(path=os.path.join(data_dir, "price_history.json"))
            need = list(dict.fromkeys(book_tks + [str(c.get("ticker") or "").upper()
                                                  for c in cands if c.get("ticker")]))
            raw = {}
            for tk in need:
                r = cm.returns_from_closes(ph.window(tk, date(2000, 1, 1), date.today()))
                if r:
                    raw[tk] = r
            aligned, _ = cm.align_returns(raw)
            book_rets = {tk: aligned[tk] for tk in book_tks if tk in aligned}
            cand_rets = {tk: v for tk, v in aligned.items() if tk not in book_tks}
            uncorr = cm.screen_uncorrelated(cands, candidate_returns=cand_rets,
                                            book_returns_by_ticker=book_rets, spear=spear)
            title = (f"[bold {AMBER}]⟂ SCREEN · MACRO-CORRELATION[/]  "
                     f"[{DIM}]· portfolio factor read + the diversifier search[/]")
            acts = (f"[{DIM}]‹ Esc to close[/]    [{FAINT}]click a name to open · measured ρ where prices are "
                    f"cached, factor-proxy otherwise[/]")
            self.push_screen(InspectScreen(title, _correlation_screen_markup(macro, uncorr), acts))
            nd = uncorr.get("n_diversifiers", 0)
            self._status(Text(f"⟂ {macro.get('read') or 'macro-correlation n/a'} · {nd} diversifier candidate(s)",
                              style=(GREEN if nd else ORANGE)))
        except Exception as e:
            self._status(Text(f"correlation screen failed: {e}", style=DIM))

    def _screen_chooser(self) -> None:
        """The DELIBERATE entry to SCREEN — pick the sleeve you're screening to fill, rather than
        auto-screening the focused name's slot (which dumped a wall of wrong-slot kills when that slot
        had no candidates). SCREEN finds a name that could DISPLACE a holding; you choose which slot."""
        focus_slot = self._slot_for((self._focus or "").strip())
        # data-driven: the seed four + any runtime-created slots (descs from each slot's stage_note),
        # then the off-slot satellite screen.
        try:
            import discovery_screen as ds
            ds.reload_slots()
            seed = list(ds._SEED_SLOT_RULES)
            slots = [(s, ds.SLOT_RULES.get(s, {}).get("stage_note") or s) for s in seed]
            user = [(s, (ds.SLOT_RULES[s].get("stage_note") or "user-created slot") + "  ✦ created")
                    for s in ds.SLOT_RULES if s not in seed]
            slots += sorted(user)
        except Exception:
            slots = [("silver-spear", "the convex Ag spear"),
                     ("gold-royalty-ballast", "Au royalty / streamer ballast"),
                     ("project-generator-holdco", "diversified holdco / generator"),
                     ("electrification-royalty", "U / Cu / grid electrification ballast")]
        slots.append(("satellite", "off-slot asymmetric bets — outside the barbell  ◆ found here"))
        slots.append(("uncorrelated", "macro-correlation read + the search for uncorrelated diversifiers  ⟂"))
        opts = []
        for s, desc in slots:
            mark = (f"   [{GREEN}]← {self._focus} fills this[/]"
                    if (s == focus_slot and self._focus) else "")
            glyph = "◆" if s == "satellite" else ("⟂" if s == "uncorrelated" else "›")  # mark the special screens apart
            opts.append(f"[@click=app.screen_slot('{s}')][{AMBER}]{glyph} {s}[/]  [{DIM}]{desc}[/]{mark}[/]")
        body = (f"[{SILVER}]SCREEN is the disconfirmation funnel — slot-fit first, it finds a name that "
                f"could displace a holding. Or screen [/][{AMBER}]satellite[/][{SILVER}] for calculated "
                f"asymmetric bets that DON'T fit a slot — then [/][{AMBER}]◆ new slot from this[/]"
                f"[{SILVER}] turns a satellite find into a new slot. Pick what you're screening for:[/]\n\n"
                + "\n".join(opts))
        self.push_screen(InspectScreen(f"[bold {AMBER}]▲ SCREEN[/]  [{DIM}]· pick a slot[/]",
                                       body, f"[{DIM}]‹ Esc to close · or /screen <slot>[/]"))

    def action_screen_slot(self, slot: str = "") -> None:
        """From the SCREEN chooser: run the disconfirmation funnel for the chosen slot."""
        try:
            self.pop_screen()
        except Exception:
            pass
        if slot:
            self._run_screen(slot)

    def action_new_slot_from(self, ticker: str = "") -> None:
        """◆ 'new slot from this' on a satellite survivor — draft a slot from the candidate's screened
        fields (the cockpit fills the rules, you just approve), then show a confirm card. No typing, no
        command: one click → review → create. The draft is stashed for action_create_slot."""
        tk = (ticker or "").strip().upper()
        cand = (getattr(self, "_last_screen_survivors", {}) or {}).get(tk)
        if not cand:
            self._status(Text(f"no screened candidate for {tk} — run /screen satellite first", style=ORANGE))
            return
        try:
            import discovery_screen as ds
            draft = ds.draft_slot_from_candidate(cand)
        except Exception as e:
            self._status(Text(f"slot draft failed: {e}", style=ORANGE))
            return
        self._pending_slot_draft = draft
        coms = ", ".join(draft.get("commodities") or []) or "any"
        body = (f"[{SILVER}]A new thesis slot, drafted from [bold {GOLD}]{tk}[/] — review and create. "
                f"It joins the SCREEN chooser and the engine rates its names by the archetype below "
                f"(same T/Q/V machinery as a holding):[/]\n\n"
                f"  [{DIM}]name[/]       [bold {AMBER}]{draft['name']}[/]\n"
                f"  [{DIM}]vehicle[/]    [{SILVER}]{', '.join(draft.get('vehicles') or [])}[/]\n"
                f"  [{DIM}]commodity[/]  [{SILVER}]{coms}[/]\n"
                f"  [{DIM}]archetype[/]  [{SILVER}]{draft.get('archetype')}[/]  [{FAINT}](how it's rated)[/]\n"
                f"  [{DIM}]thesis[/]     [{SILVER}]{draft.get('stage_note')}[/]")
        acts = (f"[@click=app.create_slot()][bold {GREEN} on #141418] ✓ create slot [/][/]    "
                f"[@click=app.app.pop_screen()][{DIM} on #141418] ✕ cancel [/][/]    "
                f"[{FAINT}]a slot reshapes screening + rating — created on your confirm, never silently[/]")
        self.push_screen(InspectScreen(f"[bold {AMBER}]◆ NEW SLOT[/]  [{DIM}]· from {tk}[/]", body, acts))

    def action_create_slot(self) -> None:
        """Confirm the drafted slot — persist it (add_slot), reload the live taxonomy so SCREEN/rotation
        see it at once, and re-tag the seeding candidate into its new slot on the bench."""
        draft = getattr(self, "_pending_slot_draft", None)
        if not draft:
            return
        try:
            import discovery_screen as ds
            saved = ds.add_slot(**draft, source="chip")
        except Exception as e:
            self._status(Text(f"create slot failed: {e}", style=ORANGE))
            return
        self._pending_slot_draft = None
        try:
            self.pop_screen()
        except Exception:
            pass
        self._status(Text(f"◆ slot created: {saved['name']} (archetype {saved['archetype']}) — "
                          f"now in SCREEN + rotation", style=GREEN))
        self._receipt(f"new slot {saved['name']}", "◆", AMBER, undo=None)

    def _slot_incumbent(self, slot: str):
        """The held name filling `slot` — what a candidate must displace (weakest by conviction if
        several). Read from config thesis_slot + live basket conviction. None if the slot is empty."""
        try:
            import json as _j
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v5_config.json")
            with open(p) as f:
                pm = (_j.load(f).get("portfolio_metadata") or {})
        except Exception:
            pm = {}
        held = list(self._baskets_by_ticker or {})
        cands = [tk for tk in held if (pm.get(tk, {}) or {}).get("thesis_slot") == slot]
        if not cands:
            return None
        weakest = min(cands, key=lambda tk: (self._baskets_by_ticker.get(tk, {}) or {}).get("rating") or 99)
        return f"{'◆' if weakest == 'AGA.V' else '●'} {weakest}"

    def _disproof_pips(self, tickers: list) -> dict:
        """{ticker: {roles}} — which of verifier/anti_scout/forensic receipts are on record in Living
        Memory for each candidate (the disproof it has withstood). Best-effort; {} if Memory is down."""
        mem = self._memory()
        out: dict = {}
        if not mem:
            return out
        for tk in tickers:
            got = set()
            for role in ("verifier", "anti_scout", "forensic"):
                try:
                    if mem.query(ticker=tk, tag=role, limit=1):
                        got.add(role)
                except Exception:
                    pass
            out[tk] = got
        return out

    def action_funnel(self, verb: str = "", tk: str = "") -> None:
        """Clickable routing from the SCREEN funnel (the Build Plan's click-floor): open a name,
        disconfirm it (the gauntlet), or scout the slot to feed the funnel."""
        if verb == "open" and tk:
            self.action_open_profile(tk)
        elif verb == "disconfirm" and tk:
            try:
                self.pop_screen()                 # close the funnel before the gauntlet launches
            except Exception:
                pass
            self._run_gauntlet(tk)
        elif verb == "scout" and tk:
            try:
                self.pop_screen()
            except Exception:
                pass
            self._run_pipeline_bg(tk, mode="scout")

    def _slot_for(self, ticker: str) -> str:
        """The thesis_slot a held name fills, read from config (works even when the engine is down)."""
        try:
            import json as _json
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v5_config.json")
            with open(p) as f:
                pm = (_json.load(f).get("portfolio_metadata", {}) or {}).get(ticker, {}) or {}
            return str(pm.get("thesis_slot", "") or "")
        except Exception:
            return ""

    def _run_replace(self, tk: str) -> None:
        """Replace-this-slot in one action: look up the held name's thesis_slot, screen that slot
        (survivors land on the bench), then hand the ranked rotation to the gate. Chains what used to
        be three separate steps — find the slot, screen it, rotate — behind a single verb."""
        tk = (tk or "").strip().upper()
        if not tk:
            self._status(Text("usage: /replace <held-ticker>", style=DIM))
            return
        slot = self._slot_for(tk)
        if slot:
            self._run_screen(slot)                       # deterministic screen → survivors on the bench
        else:
            self._status(Text(f"replace {tk}: no thesis_slot on record — the agent will resolve it",
                              style=DIM))
        self._ask_agent(
            f"Replace {tk}" + (f" (slot '{slot}')" if slot else "") + ": from the screened WATCHLIST "
            f"survivors (or /scout the slot if the bench is thin), rank the slot-fit challengers by "
            f"friction-adjusted ρ-edge — slot-fit FIRST, then valuation — and run the rotation gate "
            f"(/rotate {tk} <best>). Flag any slot-mismatch."
        )
        self._palette_recap = f"replace {tk}".strip()

    def _run_gauntlet(self, tk: str) -> None:
        """The one-action disconfirmation gauntlet: fire @verifier → @anti-scout → forensic (each
        tagged to Memory) and graduate in a single pass — graduate_candidate auto-collects the three
        tagged receipts, so there are no entry ids to hand-copy."""
        tk = (tk or "").strip().upper()
        if not tk:
            self._status(Text("usage: /gauntlet <candidate-ticker>", style=DIM))
            return
        self._status(Text(f"⚖ gauntlet {tk}: verifier → anti-scout → forensic → graduate", style=GREEN))
        self._ask_agent(
            f"Run the disconfirmation GAUNTLET on {tk} (the Phase-7 graduation gate) in one pass:\n"
            f"1) @verifier — verify claims / catalysts / accounting (JSF); record the verdict with "
            f"memory_write(type='note', ticker='{tk}', tags=['verifier'], text=…).\n"
            f"2) @anti-scout — the kill case / better-vehicle hunt (CLEAN is a valid result); record "
            f"with tags=['anti_scout'].\n"
            f"3) the forensic / JSF gate result; record with tags=['forensic'].\n"
            f"Then call graduate_candidate('{tk}') — it auto-collects the three tagged receipts — and "
            f"pin_insight('{tk}', '<≤14-word verdict — PASS, or which leg failed>', level='good' for PASS "
            f"else 'warn') so the result shows as a readable note on its card. Report PASS (then "
            f"promote_to_eval) or which leg failed and why."
        )
        self._palette_recap = f"gauntlet {tk}".strip()

    def _run_explain_move(self, tk: str) -> None:
        """Triage an unexplained / decoupled price move — TAILORED to the name's type (its dominant factor,
        the right ETF basket, the right insider-filing system, an archetype-appropriate corporate event,
        and drill-leak ONLY for explorers). Ranks the stock-specific causes, then logs a date-stamped
        SENTINEL event + sets the watches. A SENTINEL event, NOT a trade trigger (the info is in what
        happens next)."""
        tk = (tk or "").strip().upper()
        if not tk:
            self._status(Text("usage: /explain-move <ticker>", style=DIM))
            return
        import divergence_monitor
        b = (self._baskets_by_ticker or {}).get(tk, {}) if isinstance(self._baskets_by_ticker, dict) else {}
        b = b if isinstance(b, dict) else {}
        st = b.get("sector_tags") or []
        ctx = divergence_monitor.explain_context(
            ticker=tk, archetype=str(b.get("archetype") or ""),
            commodity=str(st[0]) if st else "", subarchetype=str(b.get("subarchetype") or ""))
        self._status(Text(f"⚡ explain-move {tk} ({ctx['kind']}): ranking the cause vs {ctx['factor']}", style=GREEN))
        drill_line = (
            "6) DRILL-RESULT leak — downweight HARD against the spud→assay calendar (first hole to an "
            "assay-bearing PR is ~6–12 weeks).\n" if ctx["drill_relevant"] else
            f"6) (DRILL-RESULT leak is N/A for a {ctx['kind']} — weigh an operational / portfolio event under #3 instead.)\n")
        self._ask_agent(
            f"EXPLAIN-MOVE on {tk} (a {ctx['kind']}): it DECOUPLED from {ctx['factor']} on volume — a "
            f"stock-specific force overrode the macro (beta can't decouple a name from its factor and push it "
            f"the other way on size). State the residual + relative volume up front, then rank the cause "
            f"most→least likely, each grounded STRAIGHT-TO-SOURCE with the URL:\n"
            f"1) discrete ACCUMULATOR (fund / large buyer building) — the most common signature for exactly "
            f"this (no news, decoupled, on volume); confirm later by whether the bid stays supported.\n"
            f"2) MECHANICAL / INDEX flow — check the quarterly rebalance window + the relevant ETF holdings "
            f"({ctx['etfs']}) for a recent add; metal-agnostic clustered buying.\n"
            f"3) leaked CORPORATE EVENT — {ctx['corporate']} (SEDAR+ / Newsfile / EDGAR; a UMA-forced halt "
            f"usually lands within a few sessions if real).\n"
            f"4) PROMOTION / newsletter / social surge (ceo.ca, X) — volume + price with zero filing; round-trips.\n"
            f"5) INSIDER open-market buying — {ctx['insider']}.\n"
            + drill_line +
            f"Then leave BOTH traces: pin_insight('{tk}', '<≤14-word takeaway — SENTINEL: decoupled vs "
            f"{ctx['factor']}, top cause + the watch>', level='warn') so it shows as a READABLE note on {tk}'s "
            f"card (the NOTES section + a badge on its row), AND memory_write(type='alert', ticker='{tk}', "
            f"tags=['sentinel','divergence'], text=…) to LOG the date-stamped SENTINEL event (residual + rvol + "
            f"the {ctx['factor']}-divergence flag). State the watches (insider filings · SEDAR+/EDGAR PR · UMA/halt "
            f"· ETF holdings). This is a SENTINEL event, NOT a trade trigger — a spike that round-trips tomorrow "
            f"was a fill/promo (noise); one that holds and builds over 2–3 sessions is accumulation or a pending "
            f"catalyst (signal)."
        )
        self._palette_recap = f"explain-move {tk}".strip()

    def _book_snapshot(self) -> list:
        """Current book as [{ticker, weight, role, conviction, runway}] for the CHANGE review.
        Weights come from the engine's EFFECTIVE (overlay-merged) barbell in /state — so a confirmed
        cut / reweight is reflected; the base config file is only a fallback and can be stale.
        Conviction is the live basket rating. Read-only; never mutates the book."""
        bw = (self._state or {}).get("barbell_weights")
        if not isinstance(bw, dict) or not any(not str(k).startswith("_") for k in bw):
            try:                                          # fallback only: the base file (may be stale)
                import json as _j
                p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v5_config.json")
                with open(p) as f:
                    bw = (_j.load(f).get("barbell_weights") or {})
            except Exception:
                bw = {}
        out = []
        for tk, w in (bw or {}).items():
            if str(tk).startswith("_"):
                continue
            try:
                wf = float(w)
            except (TypeError, ValueError):
                continue
            b = (self._baskets_by_ticker or {}).get(tk, {}) or {}
            out.append({"ticker": tk, "weight": wf,
                        "role": "spear" if str(tk).upper() == "AGA.V" else "ballast",
                        "conviction": b.get("rating"), "runway": None})
        return out

    def _run_change(self, args: list) -> None:
        """Open the CHANGE review for a staged book change (the reframe's job 2). Routes NOTHING
        until you commit — and the commit only FILES a gated proposal you then /confirm.
        usage: /change cut TK · /change rotate OUT IN · /change reweight TK=.6 TK=.4"""
        usage = "usage: /change cut TK · /change rotate OUT IN · /change reweight TK=.6 TK=.4"
        if not args:
            self._status(Text(usage, style=DIM)); return
        kind = args[0].lower()
        if kind in ("cut", "remove") and len(args) >= 2:
            spec = {"kind": "cut", "ticker": args[1].upper()}
        elif kind in ("rotate", "swap", "replace") and len(args) >= 3:
            spec = {"kind": "rotate", "out": args[1].upper(), "in": args[2].upper()}
        elif kind == "reweight" and len(args) >= 2:
            weights = {}
            for tok in args[1:]:
                if "=" in tok:
                    t, _, v = tok.partition("=")
                    try:
                        weights[t.upper()] = float(v)
                    except ValueError:
                        pass
            spec = {"kind": "reweight", "weights": weights}
        else:
            self._status(Text(usage, style=DIM)); return
        book = self._book_snapshot()
        if not book:
            self._status(Text("change: no book weights found (config barbell_weights)", style=DIM)); return
        try:
            import book_change as _bc
            p = _bc.propose_change(spec, book, mem=None)
        except Exception as e:
            self._status(Text(f"change error: {e}", style=ORANGE)); return
        if not p.get("ok"):
            self._status(Text(f"change refused — {p.get('error')}", style=ORANGE)); return
        self.push_screen(ChangeReviewScreen(p, spec))

    def _change_apply(self, spec: dict, proposal: dict, premortem: str) -> None:
        """Commit a reviewed change — record the decision + pre-mortem to Memory and FILE the change
        through the EXISTING gated path (cut_holding / barbell propose / the rotation gate). Never
        mutates the book directly; the operator still /confirms the filed proposal."""
        kind = spec.get("kind")
        subj = proposal.get("subject") or ""
        try:
            self._write_note(f"CHANGE {proposal.get('kind')} {subj} — pre-mortem: {premortem}",
                             ticker=("" if subj == "book" else subj))
        except Exception:
            pass
        if kind in ("cut", "remove"):
            _post("/config/cut_holding", {"ticker": spec["ticker"], "proposed_by": "change-review",
                                          "reason": f"CHANGE review cut — pre-mortem: {premortem[:120]}"})
            self._status(Text(f"⇄ filed CUT {spec['ticker']} — pending; /confirm to apply", style=GREEN))
        elif kind == "reweight":
            after = {r["ticker"]: r["weight"] for r in proposal.get("after", [])}
            _post("/config/propose", {"key": "barbell_weights", "value": after,
                                      "reason": f"CHANGE review reweight — pre-mortem: {premortem[:120]}"})
            self._status(Text("⇄ filed REWEIGHT (barbell_weights) — pending; /confirm to apply", style=GREEN))
        else:  # rotate → the slot-fit rotation gate (evaluates + proposes)
            self._ask_agent(f"/rotate {spec.get('out')} {spec.get('in')}")
            self._status(Text(f"⇄ rotation gate invoked {spec.get('out')}→{spec.get('in')} — "
                              f"pre-mortem recorded", style=GREEN))

    def _change_chooser(self, name: str) -> None:
        """The DELIBERATE entry point to CHANGE. CHANGE reviews a change YOU stage — it does not
        suggest one — so the operator picks the operation explicitly (cut / rotate) instead of the
        chip auto-staging a cut. Book-level reweight stays the /change reweight command."""
        name = (name or "").strip().upper()
        if not name or name in ("BOOK", "—", "SILVER UNIVERSE"):
            self._status(Text("CHANGE — focus a holding first, then ⇄ Change · or type "
                              "/change cut TK · rotate OUT IN · reweight TK=.6 TK=.4", style=DIM))
            return
        is_spear = (name == "AGA.V")
        opts = []
        if not is_spear:
            opts.append(f"[@click=app.change_stage('cut','{name}')][{AMBER}]› Cut {name}[/] "
                        f"[{DIM}]from the book — then review the before→after diff[/][/]")
        opts.append(f"[@click=app.change_stage('rotate','{name}')][{AMBER}]› Rotate {name}[/] "
                    f"[{DIM}]— screen a slot-fit replacement, then the rotation gate[/][/]")
        body = (f"[{SILVER}]CHANGE reviews a before→after book diff for a change YOU stage — it does "
                f"not suggest changes, it lets you check yours (and see the downside) before anything "
                f"commits. Pick one:[/]\n\n" + "\n".join(opts))
        if is_spear:
            body += f"\n\n[{DIM}]AGA.V is the structural spear — it can't be cut, only swapped in-slot.[/]"
        body += (f"\n\n[{DIM}]book-level reweight (no auto-percentages — your numbers): type[/] "
                 f"[{AMBER}]/change reweight {name}=.5 GROY=.3 …[/]")
        self.push_screen(InspectScreen(f"[bold {AMBER}]⇄ CHANGE[/]  [{DIM}]·[/]  [bold {GOLD}]{name}[/]",
                                       body, f"[{DIM}]‹ Esc to close · nothing is staged until you pick[/]"))

    def action_change_stage(self, op: str = "", tk: str = "") -> None:
        """From the CHANGE chooser: stage the operation the operator explicitly chose (deliberate)."""
        try:
            self.pop_screen()                     # close the chooser
        except Exception:
            pass
        tk = (tk or "").strip().upper()
        if op == "cut" and tk:
            self._run_change(["cut", tk])         # → the diff review (shows consequences, incl. negatives)
        elif op == "rotate" and tk:
            self._run_replace(tk)                 # → screen the slot for a challenger, then the rotation gate


if __name__ == "__main__":
    Cockpit().run()
