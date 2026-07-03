#!/usr/bin/env python3
"""
cockpit_surfaces.py — THE BLEND: the Concierge dock + the hub focus surfaces.

Split out of ``commodityex_tui.py`` (which keeps the ``Cockpit`` App orchestrator).
``BlendHubScreen`` is HOME (Launch · Quest Log · Working lane); the focus surfaces
(Pipeline · Matchup · Thread · Compare · Roster) open OUT of it as modals and close back
into it; the ``ConciergeDock`` mixin rides every one of them.

Depends only on ``cockpit_widgets`` (palette, transport, blend render helpers) — never on
``commodityex_tui``; every surface reaches the running App via ``self.app`` at runtime.
"""
from __future__ import annotations

import time

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from cockpit_widgets import (
    AMBER, AMBER_BRIGHT, BORDER, CONCIERGE_C, DIM, FAINT, GOLD, GREEN, ORANGE, RED, SILVER, TEAL,
    BLEND_FILTERS, BLEND_SEED_WORKFLOWS, HUB_AGENT_DOC, HUB_AGENT_META, HUB_AGENT_MODEL, HUB_GROUPS,
    _MATCHUP_LENSES, _MODEL_COLORS, _ROLE_GLYPH,
    _agent_model, _blend_chain_canvas, _blend_feed_lanes, _blend_feed_parts, _blend_nav_markup,
    _clip, _disp_price, _jobnav_markup, _num, _provider_color, _run_model_label,
)

# ══════════════════════════════════════════════════════════════════════════════════════
#  THE BLEND — screens. BlendHubScreen is HOME (Launch · Quest Log · Working lane); the
#  focus surfaces (Pipeline · Matchup · Thread · Compare · Roster) open OUT of it as
#  modals and close back into it; the Concierge dock rides every one of them.
# ══════════════════════════════════════════════════════════════════════════════════════
class ConciergeDock:
    """Mixin: the ambient Concierge — a plain READ-ONLY LLM docked at the bottom of every hub
    screen. It reads what's on the operator's screen ("recap this", "what does this mean",
    "find me…") and visibly cannot fire runs or write Living Memory — a separate, quiet lane
    (periwinkle-slate) so it never reads as agent chrome. Collapsed bar ⇄ expanded panel."""

    _con_open = False

    def compose_concierge(self) -> ComposeResult:
        with Vertical(id="con_dock", classes="con_dock"):
            with VerticalScroll(id="con_logwrap", classes="con_logwrap"):
                yield Static("", id="con_log", classes="con_log")
            yield Input(placeholder="Concierge — ask for help, a definition, a recap, or just think out loud…",
                        id="con_input", classes="con_input")
            yield Static("", id="con_bar", classes="con_bar")

    def concierge_context(self) -> str:                    # override per screen
        return "Quest Log"

    def action_concierge(self) -> None:
        """Toggle the dock open/closed — bound to `c` AND to the clickable bar."""
        self._con_open = not self._con_open
        try:
            self.query_one("#con_dock").set_class(self._con_open, "open")
            if self._con_open:
                self.query_one("#con_input", Input).focus()
        except Exception:
            pass
        self.paint_concierge()

    def paint_concierge(self) -> None:
        app = self.app
        e = app._esc
        ctx = e(self.concierge_context())
        C = CONCIERGE_C
        bar = (f"[@click=app.concierge_toggle][bold {C}]❯ CONCIERGE[/][/]  "
               f"[{DIM}]◈ context:[/] [{SILVER}]{ctx}[/]  "
               f"[{FAINT}]read-only · [bold {C}]not[/] an agent · can't run agents or write Memory[/]   "
               f"[@click=app.concierge_toggle][bold {C} on #141418] {'✕ close' if self._con_open else '❯ ask'} [/][/]"
               f"  [{FAINT}]c[/]")
        try:
            self.query_one("#con_bar", Static).update(bar)
        except Exception:
            return
        if not self._con_open:
            return
        lines = []
        hist = list(getattr(app, "_concierge_hist", []) or [])
        if not hist:
            lines.append(f"[{FAINT}]ephemeral Q&A — nothing here persists to Living Memory[/]")
        for role, txt in hist[-8:]:
            if role == "you":
                lines.append(f"[bold {SILVER}]you ›[/] [{SILVER}]{e(_clip(txt, 160))}[/]")
            else:
                lines.append(f"[bold {C}]❯[/] [{SILVER}]{e(txt)}[/]")
        if getattr(app, "_concierge_busy", False):
            lines.append(f"[{C}]❯ thinking…[/]")
        chips = ["Explain ρ/φ asymmetry", f"Recap {ctx}", "How do I run a council?",
                 "Find every below-floor name"]
        lines.append("  ".join(f"[@click=app.concierge_chip({i})][{C} on #141418] {e(p)} [/][/]"
                               for i, p in enumerate(chips)))
        try:
            self.query_one("#con_log", Static).update("\n".join(lines))
        except Exception:
            pass

    def concierge_chips(self) -> list:
        return ["Explain ρ/φ asymmetry", f"Recap {self.concierge_context()}",
                "How do I run a council?", "Find every below-floor name"]


class BlendSurface(ModalScreen, ConciergeDock):
    """A focus surface — opens OUT of the Quest Log over a dimmed backdrop, closes back into it.
    Ships the full close contract: ✕ button, esc, AND a click on the backdrop (never esc-only).
    The top bar rides every surface, so you can hop straight to another one (1–5)."""

    SURFACE_TITLE = "SURFACE"
    SURFACE_GLYPH = "◈"
    NAV_ID = ""                                            # which top-bar tab this surface is
    ACCENT = AMBER
    BINDINGS = [Binding("escape", "close", "Close"), Binding("c", "concierge", "Concierge"),
                Binding("1", "app.blend_nav('blend')", "Blend", show=False),
                Binding("2", "app.blend_nav('quest')", "Quest Log", show=False),
                Binding("3", "app.blend_nav('pipeline')", "Pipeline", show=False),
                Binding("4", "app.blend_nav('matchup')", "Matchup", show=False),
                Binding("5", "app.blend_nav('roster')", "Roster", show=False),
                Binding("6", "app.blend_nav('thread')", "Thread", show=False)]

    def __init__(self, sub: str = "") -> None:
        super().__init__()
        self._sub = sub

    def compose(self) -> ComposeResult:
        with Vertical(id="srf_box", classes=f"srf_box {self.__class__.__name__.lower()}"):
            yield Static("", id="srf_nav")
            yield Static("", id="srf_head")
            with VerticalScroll(id="srf_body", classes="srf_body"):
                yield from self.body()
            yield from self.compose_concierge()

    def body(self) -> ComposeResult:                       # override
        yield Static("")

    def on_mount(self) -> None:
        self.paint_head()
        self.paint()
        self.paint_concierge()

    def paint_head(self) -> None:
        e = self.app._esc
        try:
            self.query_one("#srf_nav", Static).update(_blend_nav_markup(self.NAV_ID))
        except Exception:
            pass
        self.query_one("#srf_head", Static).update(
            f"[bold {self.ACCENT}]{self.SURFACE_GLYPH} {e(self.SURFACE_TITLE)}[/]"
            + (f"  [{FAINT}]{e(self._sub)}[/]" if self._sub else "")
            + f"   [@click=app.surface_close][{DIM} on #141418] ✕ esc [/][/]")

    def paint(self) -> None:                               # override
        pass

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event) -> None:
        try:                                               # click the dimmed backdrop → close
            box = self.query_one("#srf_box")
            w, _ = self.get_widget_at(event.screen_x, event.screen_y)
            if w is not box and box not in w.ancestors:
                self.dismiss(None)
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "con_input":
            event.stop()
            q = (event.value or "").strip()
            event.input.value = ""
            if q:
                self.app._concierge_send(q, self.concierge_context())


class PipelineSurface(BlendSurface):
    """The Pipeline — a chain you can SET UP and a chain mid-flight, never a black box. In
    **setup** mode (the top bar's PIPELINE tab, or ⚙ on a Launch row) you stage the parameters
    first — pick the chain recipe, the target, edit stages — and nothing fires until ▶ LAUNCH.
    Live: bordered node cards on a horizontally-scrollable strip, junctions hand-painted in box
    glyphs (fan-out ┤ · fan-in ├ · corners ╭╰╮╯), the running node pulsing at ~2 Hz. ◂ ▸ move
    focus · ⏎ expands a stage · ⏸ pause / + add stage / ⏹ stop mirror space / a / x."""

    SURFACE_TITLE = "PIPELINE"
    SURFACE_GLYPH = "⛓"
    NAV_ID = "pipeline"
    ACCENT = AMBER
    BINDINGS = BlendSurface.BINDINGS + [
        Binding("left", "node(-1)", "◂ node"), Binding("right", "node(1)", "node ▸"),
        Binding("enter", "node(0)", "Inspect"),
        Binding("space", "app.wf_pause", "Pause"), Binding("a", "app.wf_addstage", "Add stage"),
        Binding("x", "app.wf_stop", "Stop"),
    ]

    def __init__(self, mode: str = "live", ref=None, sub: str = "", chain_name: str = "",
                 subject: str = "") -> None:
        super().__init__(sub=sub)
        self._mode = mode                                  # setup | live | done
        self._ref = ref                                    # done → the saved package path
        self._chain_name = chain_name                      # setup → the staged recipe's name
        self._subject = subject                            # subject-at-fire (defaults to focus on mount)
        self._sel = -1
        self._pulse = False
        self._timer = None

    def body(self) -> ComposeResult:
        from textual.containers import HorizontalScroll
        yield Static("", id="pipe_setup")
        yield Input(placeholder="subject — the focused name by default; type a ticker to override…",
                    id="pipe_subject", classes="pipe_subject")
        with HorizontalScroll(id="pipe_strip"):
            yield Static("", id="pipe_canvas")
        yield Static("", id="pipe_detail")
        yield Static("", id="pipe_actions")

    def on_mount(self) -> None:
        app = self.app
        if not self._subject:                              # subject-at-fire: default to the desk focus
            self._subject = app._blend_subject()
        if self._mode == "setup" and not app._wf_running:   # stage the recipe (editable copy)
            if self._chain_name:
                app._workflow = [dict(s) for s in app._blend_workflows().get(self._chain_name, [])]
            elif not app._workflow:
                self._chain_name = "deep dossier"
                app._workflow = [dict(s) for s in BLEND_SEED_WORKFLOWS["deep dossier"]]
        super().on_mount()
        self._timer = self.set_interval(0.5, self._tick)   # the ~2 Hz live pulse

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pipe_subject":
            event.stop()
            v = (event.value or "").strip().upper()
            if v:
                self._subject = v
            self.paint()
        else:
            super().on_input_submitted(event)

    def _tick(self) -> None:
        self._pulse = not self._pulse
        if any(st == "running" for st in self._chain()[1].values() if isinstance(st, str)):
            self.paint()

    def _chain(self):
        """(stages, states, subject) — the live workflow, the staged setup chain, the engine
        pipeline, a saved package, or the canonical preview. states[(si, agent)] ∈ done|running|queued.
        Every node is annotated with the EFFECTIVE seat (states[(si, a, "model"/"provider")]) so the
        canvas chips match the working lane: a live run reports its own provider; everything else
        resolves through app._agent_provider (registry choice, honest about the agy→Claude fallback) —
        a queued scout on a box without the Gemini CLI reads ◇sonnet, not the registry's aspiration."""
        stages, states, subject = self._chain_states()
        app = self.app
        try:
            live_prov = {j.get("agent"): j.get("provider") for j in app._inflight.values()
                         if j.get("agent") and j.get("provider") and not j.get("cancelled")}
            for si, st in enumerate(stages):
                for a in st.get("agents", []) or []:
                    prov = (live_prov.get(a) if states.get((si, a)) == "running" else None) \
                        or app._agent_provider(a)
                    states[(si, a, "provider")] = prov
                    states[(si, a, "model")] = _run_model_label(a, prov)
        except Exception:
            pass                                            # annotation is display-only — never block paint
        return stages, states, subject

    def _chain_states(self):
        app = self.app
        states: dict = {}
        if self._mode == "done" and self._ref:
            stages = app._load_workflow_chain(self._ref) or BLEND_SEED_WORKFLOWS["deep dossier"]
            for si, st in enumerate(stages):
                for a in st.get("agents", []):
                    states[(si, a)] = "done"
            return stages, states, self._sub
        if self._mode == "setup" and not app._wf_running:   # the staged chain — all queued
            stages = app._workflow or [dict(s) for s in BLEND_SEED_WORKFLOWS["deep dossier"]]
            for si, st in enumerate(stages):
                for a in st.get("agents", []):
                    states[(si, a)] = "queued"
            return stages, states, (self._subject or app._blend_subject())
        if app._wf_running and app._workflow:
            stages = app._workflow
            idx = int(getattr(app, "_wf_stage_idx", 0))
            live_agents = {j.get("agent") for j in app._inflight.values() if not j.get("cancelled")}
            now = time.time()
            for si, st in enumerate(stages):
                for a in st.get("agents", []):
                    if si < idx:
                        states[(si, a)] = "done"
                    elif si == idx:
                        live = next((j for j in app._inflight.values()
                                     if j.get("agent") == a and not j.get("cancelled")), None)
                        states[(si, a)] = "running" if (a in live_agents) else "done"
                        if live:
                            el = now - live.get("started", now)
                            states[(si, a, "pct")] = min(0.95, el / 180.0)
                    else:
                        states[(si, a)] = "queued"
            return stages, states, (app._wf_subject or self._subject or app._blend_subject())
        pipe = (app._state or {}).get("pipeline") or {}
        if app._pipe_is_live(pipe):                         # the engine's scout→synthesis→verifier run
            stages = [{"agents": ["scout"], "note": "find the names"},
                      {"agents": ["synthesis"], "note": "rank & build the case"},
                      {"agents": ["verifier"], "note": "gate the survivors"}]
            cur = str(pipe.get("stage", "scout")).lower()
            order = ["scout", "synthesis", "verifier"]
            ci = next((i for i, a in enumerate(order) if a in cur), 0)
            for si, a in enumerate(order):
                states[(si, a)] = "done" if si < ci else ("running" if si == ci else "queued")
                if si == ci:
                    states[(si, a, "pct")] = 0.5
            return stages, states, str(pipe.get("theme", ""))
        stages = BLEND_SEED_WORKFLOWS["deep dossier"]      # idle → the canonical preview, all queued
        for si, st in enumerate(stages):
            for a in st.get("agents", []):
                states[(si, a)] = "queued"
        return stages, states, app._blend_subject()

    def paint(self) -> None:
        app = self.app
        e = app._esc
        if self._mode == "setup" and app._wf_running:       # it launched — flip to the live view
            self._mode = "live"
        stages, states, subject = self._chain()
        role = ((app._state or {}).get("nodes", {}).get(subject, {}) or {}).get("role", "")
        try:
            self.query_one("#pipe_canvas", Static).update(
                _blend_chain_canvas(stages, states, pulse=self._pulse, sel=self._sel,
                                    target=subject or "book", target_role=role))
        except Exception:
            return
        # ── SETUP — stage the parameters first; nothing fires until ▶ LAUNCH ──
        setup = []
        if self._mode == "setup":
            names = list(app._blend_workflows())
            setup.append(f"[{FAINT}]CHAIN[/]   " + "  ".join(
                f"[@click=app.pipe_chain_pick('{e(nm)}')]"
                f"[bold {'#08080A on ' + TEAL if nm == self._chain_name else TEAL + ' on #141418'} ] {e(nm)} [/][/]"
                for nm in names[:6]))
            nodes = (app._state or {}).get("nodes", {}) or {}
            tchips = []
            for tk in (app._baskets_by_ticker or {}):
                g = _ROLE_GLYPH.get((nodes.get(tk, {}) or {}).get("role", ""), "")
                on = (tk == subject)
                tchips.append(f"[@click=app.pipe_subject('{e(tk)}')]"
                              f"[bold {'#08080A on ' + AMBER if on else GOLD + ' on #141418'} ] {g}{e(tk)} [/][/]")
            # subject-at-fire: the subject is chosen HERE (defaults to focus), not a sticky target
            setup.append(f"[{FAINT}]SUBJECT[/] [bold {GOLD}]{e(subject)}[/]  " + " ".join(tchips)
                         + f"  [{FAINT}](or type one below)[/]")
            for si, st in enumerate(stages):
                agents = "  ∥  ".join(f"[{AMBER}]{e(a)}[/]" for a in st.get("agents", []))
                note = f"  [{DIM}]{e(_clip(st.get('note', ''), 54))}[/]" if st.get("note") else ""
                setup.append(f"  [{GOLD}]{si + 1}.[/] {agents}{note}"
                             f"  [@click=app.pipe_stage_del({si})][{ORANGE}]✕[/][/]")
            setup.append(f"[{FAINT}]✕ remove · + add from Roster[/]")
        try:
            self.query_one("#pipe_setup", Static).update("\n".join(setup))
            self.query_one("#pipe_subject", Input).set_class(self._mode == "setup", "open")
        except Exception:
            pass
        # ── stage detail (the focused node, expanded in place) ──
        det = []
        if 0 <= self._sel < len(stages):
            st = stages[self._sel]
            agents = st.get("agents", [])
            par = len(agents) > 1
            det.append(f"[bold {GOLD}]stage {self._sel + 1}[/]"
                       + (f"  [{TEAL}]∥ parallel[/]" if par else "")
                       + "  " + "  ".join(f"[bold {AMBER}]{e(a)}[/] [{_MODEL_COLORS.get(_agent_model(a)[1], SILVER)}]◇{_agent_model(a)[1]}[/]"
                                          for a in agents))
            if st.get("note"):
                det.append(f"[{SILVER}]{e(st['note'])}[/]")
            for a in agents:
                stt = states.get((self._sel, a), "queued")
                if stt == "running":
                    j = next((jj for jj in app._inflight.values()
                              if jj.get("agent") == a and not jj.get("cancelled")), None)
                    el = int(time.time() - j.get("started", time.time())) if j else 0
                    det.append(f"  [{AMBER}]⚙ {e(a)} running · {el}s[/]")
                else:
                    det.append(f"  [{GREEN if stt == 'done' else FAINT}]{'✓' if stt == 'done' else '·'} {e(a)} {stt}[/]")
        else:
            det.append(f"[{FAINT}]◂ ▸ / click a node to inspect[/]")
        if self._mode == "done" and self._ref:
            det.append(f"[@click=app.blend_read('{e(str(self._ref))}')][bold {GREEN} on #141418] ❖ read the dossier [/][/]")
        # node click targets (one chip per stage — the canvas itself is painted text)
        chips = "  ".join(f"[@click=app.pipe_sel({si})][{GOLD if si == self._sel else DIM} on #141418]"
                          f" {si + 1}·{e(_clip(' ∥ '.join(st.get('agents', [])), 30))} [/][/]"
                          for si, st in enumerate(stages))
        det.append(f"[{FAINT}]inspect:[/] {chips}")
        self.query_one("#pipe_detail", Static).update("\n".join(det))
        # ── the action row — buttons with key mirrors (never key-only) ──
        paused = bool(app._wf_ctl.get("pause"))
        running = app._wf_running
        acts = []
        if running:
            acts.append(f"[@click=app.wf_pause][bold {AMBER} on #141418] {'▶ resume' if paused else '⏸ pause chain'} [/][/] [{FAINT}]space[/]")
            acts.append(f"[@click=app.wf_addstage][bold {TEAL} on #141418] + add stage [/][/] [{FAINT}]a[/]")
            acts.append(f"[@click=app.wf_stop][bold {RED} on #141418] ⏹ stop [/][/] [{FAINT}]x[/]")
            if paused:
                acts.append(f"[{ORANGE}]paused — resumes at the next stage boundary[/]")
        elif self._mode == "setup":
            acts.append(f"[@click=app.blend_launch_current][bold {AMBER_BRIGHT} on #141418] ▶ LAUNCH "
                        f"on {e(subject)} [/][/]")
            acts.append(f"[@click=app.wf_addstage][bold {TEAL} on #141418] + add stage [/][/] [{FAINT}]a[/]")
            acts.append(f"[@click=app.pipe_chain_pick('{e(self._chain_name or 'deep dossier')}')]"
                        f"[{DIM} on #141418] ↺ reset to recipe [/][/]")
        elif self._mode != "done":
            acts.append(f"[@click=app.pipe_setup][bold {AMBER_BRIGHT} on #141418] ⚙ set up a chain [/][/]")
        self.query_one("#pipe_actions", Static).update("   ".join(acts))

    def action_node(self, d: int) -> None:
        stages = self._chain()[0]
        if not stages:
            return
        self._sel = (self._sel + int(d)) % len(stages) if self._sel >= 0 else 0
        self.paint()

    def concierge_context(self) -> str:
        return f"{self.app._blend_subject()} chain"


class MatchupSurface(BlendSurface):
    """The 1v1 — "is this outsider better than what I hold?" as a first-class verb. Holding vs
    outsider slots, lens chips, the metric table (engine numbers on the holding side; the run
    grounds the outsider), and ▶ run fires the same agents on both sides. The result drops back
    into the Quest Log as a MATCHUP entry."""

    SURFACE_TITLE = "MATCHUP"
    SURFACE_GLYPH = "⇄"
    NAV_ID = "matchup"
    ACCENT = GOLD
    BINDINGS = BlendSurface.BINDINGS + [Binding("enter", "app.matchup_run", "Run", show=False)]

    MAX_CHAL = 4                                           # the bench width that still fits the grid

    def __init__(self, hold: str = "", chal: str = "", chals=None, verdict: str = "", sub: str = "") -> None:
        super().__init__(sub=sub or "holding vs the bench")
        self._hold = hold
        # the bench — one holding vs SEVERAL outsiders (N-way). `chal`/`chals` seed it (comma-split).
        seed = list(chals) if chals else ([c.strip().upper() for c in str(chal).replace(",", " ").split()] if chal else [])
        self._chals: list = []
        for c in seed:
            if c and c not in self._chals:
                self._chals.append(c)
        self._verdict = verdict
        self._lenses = {"Value", "Balance sheet"}

    def body(self) -> ComposeResult:
        yield Static("", id="mu_slots")
        yield Input(placeholder="add an outsider to the bench — e.g. SILV, MAG, AYA.V (comma-separated ok)…",
                    id="mu_chal")
        yield Static("", id="mu_table")
        yield Static("", id="mu_actions")

    def paint(self) -> None:
        app = self.app
        e = app._esc
        hold = self._hold or app._blend_subject()
        b = (app._baskets_by_ticker or {}).get(hold, {}) or {}
        role = ((app._state or {}).get("nodes", {}).get(hold, {}) or {}).get("role", "")
        g = _ROLE_GLYPH.get(role, "")
        # ── slots: the HOLDING (subject-at-fire — pick from the book, defaults to focus) vs an
        #    editable BENCH of challenger chips (each removable) ──
        nodes = (app._state or {}).get("nodes", {}) or {}
        hold_chips = "  ".join(
            f"[@click=app.matchup_hold('{e(tk)}')]"
            f"[bold {'#08080A on ' + GOLD if tk == hold else GOLD + ' on #141418'} ]"
            f" {_ROLE_GLYPH.get((nodes.get(tk, {}) or {}).get('role', ''), '')}{e(tk)} [/][/]"
            for tk in (app._baskets_by_ticker or {}))
        bench = "  ".join(
            f"[@click=app.matchup_remove({i})][bold {TEAL} on #141418] {e(c)} ✕ [/][/]"
            for i, c in enumerate(self._chals)) or f"[{FAINT}](bench empty — add an outsider below)[/]"
        slots = (f"[{FAINT}]HOLDING[/]  {hold_chips}   [bold {AMBER}]VS[/]   "
                 f"[{FAINT}]BENCH {len(self._chals)}/{self.MAX_CHAL}[/]  {bench}")
        lens = f"[{FAINT}]LENS[/]  " + "  ".join(
            f"[@click=app.matchup_lens('{ln}')][bold {AMBER if ln in self._lenses else DIM} on #141418] {ln} [/][/]"
            for ln in _MATCHUP_LENSES)
        both = (f"[{FAINT}]all sides:[/] [bold {SILVER}]value-analyst[/] "
                f"[{AMBER_BRIGHT}]◇opus[/] [bold {SILVER}]balance-sheet-analyst[/] [{AMBER_BRIGHT}]◇opus[/]")
        self.query_one("#mu_slots", Static).update(slots + "\n" + lens + "   " + both)
        # ── the metric grid: a column per contender (holding + bench); best-in-row in mint ──
        contenders = [hold] + self._chals
        baskets = {hold: b}
        for c in self._chals:
            baskets[c] = (app._baskets_by_ticker or {}).get(c, {}) or {}
        # the agents score outsiders the ENGINE can't rate — pull this run's parsed SCORE block
        result = app._matchup_results.get(f"{hold} vs {', '.join(self._chals)}") or {}
        ascore = result.get("scores") or {}

        def cell(tk, key, spec="{:.1f}", higher=True):
            """(text, numeric, source). Engine basket first (grounded); then FMP price; then the
            agents' estimate from the run (marked ~ so it never reads as a hard engine number)."""
            bb = baskets.get(tk, {})
            V = bb.get("pillars", {}).get("V", {}) if isinstance(bb.get("pillars"), dict) else {}
            src = {"rating": bb.get("rating"), "upside": V.get("upside_pct"), "rho": V.get("rho"),
                   "phi": V.get("floor_coverage"),
                   "price": _disp_price(bb) or (app._fund or {}).get(tk, {}).get("price")}
            v = _num(src.get(key))
            if v is not None:
                return spec.format(v), v, "engine"
            av = _num((ascore.get(tk) or {}).get(key))     # agent-estimated fallback
            if av is not None:
                return spec.format(av) + "~", av, "agent"
            return "—", None, "none"

        metrics = [("Conviction", "rating", "{:.1f}", True), ("Upside", "upside", "{:+.0f}%", True),
                   ("ρ payoff", "rho", "{:.2f}×", True), ("φ floor cover", "phi", "{:.2f}", True),
                   ("Price", "price", "${:.2f}", None)]
        LBL, COL = 15, 13

        def colorize(tk):                                  # holding gold, bench teal
            return GOLD if tk == hold else TEAL
        header = " " * LBL + "".join(
            (f"[bold {colorize(tk)}]" + (f"{_ROLE_GLYPH.get(role, '') if tk == hold else ''}{tk}").ljust(COL)[:COL] + "[/]")
            for tk in contenders)
        tbl = [header]
        for label, key, spec, higher in metrics:
            vals = [cell(tk, key, spec, higher) for tk in contenders]
            best = None
            if higher is not None:
                nums = [(i, v) for i, (_t, v, _s) in enumerate(vals) if v is not None]
                if len(nums) > 1:
                    best = max(nums, key=lambda iv: iv[1])[0]
            line = f"[{DIM}]{label.ljust(LBL)}[/]"
            for i, (txt, _v, srcd) in enumerate(vals):
                if i == best:
                    sty = f"bold {GREEN}"
                elif srcd == "agent":                      # an estimate — dimmed + italic, never bold
                    sty = f"italic {DIM}"
                else:
                    sty = GOLD if contenders[i] == hold else SILVER
                line += f"[{sty}]{txt.ljust(COL)[:COL]}[/]"
            tbl.append(line)
        if ascore:
            tbl.append(f"[{FAINT}]~ = the agents' estimate from this run (the engine rates book names only)[/]")
        ungrounded = [c for c in self._chals
                      if not baskets.get(c) and not (app._fund or {}).get(c) and c not in ascore]
        if ungrounded:
            tbl.append(f"[{FAINT}]not grounded yet: {', '.join(ungrounded)} — ▶ run the bench to fetch + score them[/]")
        verdict = result.get("verdict") or self._verdict
        if verdict:
            tbl.append(f"\n[bold {GOLD}]⚖ VERDICT[/]  [{SILVER}]{e(_clip(str(verdict), 280))}[/]")
            if result.get("ref") or (len(str(verdict)) > 280):
                ref = result.get("ref", "")
                tbl.append(f"[@click=app.matchup_open_verdict('{e(str(ref))}')][{AMBER} on #141418] ↗ read the full verdict [/][/]")
        self.query_one("#mu_table", Static).update("\n".join(tbl))
        n = len(self._chals)
        run_lbl = "▶ run 1v1" if n == 1 else f"▶ run bench ({n})"
        self.query_one("#mu_actions", Static).update(
            (f"[@click=app.matchup_run][bold {GREEN} on #141418] {run_lbl} [/][/] [{FAINT}]⏎[/]   "
             if n else f"[{FAINT}]add an outsider above, then[/] [bold {DIM}]▶ run[/]   ")
            + f"[{FAINT}]same agents, every contender → verdict lands in the log[/]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mu_chal":
            event.stop()
            for raw in str(event.value or "").replace(",", " ").split():
                c = raw.strip().upper()
                if c and c not in self._chals and c != (self._hold or self.app._blend_subject()):
                    if len(self._chals) >= self.MAX_CHAL:
                        self.app._toast(f"bench is full ({self.MAX_CHAL}) — remove one first", ORANGE)
                        break
                    self._chals.append(c)
            event.input.value = ""
            self.paint()
        else:
            super().on_input_submitted(event)

    def concierge_context(self) -> str:
        bench = ", ".join(self._chals) if self._chals else "?"
        return f"{self._hold or self.app._blend_subject()} vs {bench}"


class ThreadSurface(BlendSurface):
    """A research thread that always reads as ONE clean linear narrative. A branch is not a tree
    you parse — it's an alternate continuation you SWITCH to: at the fork a track-switch of pills
    (each showing who answers) flips which continuation is live and the narrative below re-flows.
    Comparing branches is an explicit ⊞ action that borrows the Matchup idiom."""

    SURFACE_TITLE = "THREAD"
    SURFACE_GLYPH = "⑂"
    NAV_ID = "thread"
    ACCENT = GOLD
    BINDINGS = BlendSurface.BINDINGS + [
        Binding("b", "branch_next", "Switch branch"), Binding("o", "app.thread_compare", "Compare"),
    ]

    def __init__(self, root_id: str, active: int = -1, sub: str = "") -> None:
        super().__init__(sub=sub)
        self._root = str(root_id)
        self._active = active                              # branch index; -1 → latest

    def body(self) -> ComposeResult:
        yield Static("", id="th_path")
        yield Static("", id="th_body")
        yield Static("", id="th_deck")

    def _node_line(self, n, e) -> list:
        out = []
        if n.get("role") == "you":
            out.append(f"[bold {GOLD}]◇ YOU · ASK[/]")
            out.append(f"[bold white]{e(_clip(n.get('text', ''), 4000))}[/]")
        else:
            a = n.get("agent") or "claude"
            col = TEAL if _agent_model(a)[0] == "gemini" else SILVER
            out.append(f"[bold {col}]● {e(a)}[/] [{_MODEL_COLORS.get(_agent_model(a)[1], DIM)}]◇{_agent_model(a)[1]}[/]")
            out.append(f"[{SILVER}]{e(_clip(n.get('text', ''), 4000))}[/]")
        out.append(f"[{BORDER}]│[/]")
        return out

    def paint(self) -> None:
        app = self.app
        e = app._esc
        trunk, branches = app._thread_trunk_branches(self._root)
        if self._active < 0:
            self._active = max(0, len(branches) - 1)
        # ── breadcrumb path bar (rewindable) ──
        tk, _scen = app._thread_meta(self._root)
        crumb = [f"[{DIM}]open[/]"]
        if tk:
            crumb.append(f"[bold {AMBER}]{e(tk)}[/]")
        if trunk:
            crumb.append(f"[{DIM}]{e(_clip(trunk[0].get('text', ''), 30))}[/]")
        if branches and 0 <= self._active < len(branches):
            b = branches[self._active]
            crumb.append(f"[bold {b['tone']}]⇄ {e(b['label'])}[/]")
        crumb.append(f"[{FAINT}]{len(branches)} branch{'es' if len(branches) != 1 else ''} · 1 live[/]")
        self.query_one("#th_path", Static).update(f" [{FAINT}]→[/] ".join(crumb))
        # ── the linear narrative: trunk → track-switch → the ACTIVE branch re-flowed ──
        lines: list = []
        for n in trunk:
            lines += self._node_line(n, e)
        if branches:
            pills = []
            for i, b in enumerate(branches):
                on = (i == self._active)
                lead = b.get("lead") or "claude"
                pills.append(f"[@click=app.thread_branch({i})][bold {'#08080A on ' + b['tone'] if on else b['tone'] + ' on #141418'}]"
                             f" {'▶' if on else '⑂'} {e(b['label'])} ◇{_agent_model(lead)[1]} [/][/]")
            pills.append(f"[@click=app.thread_newbranch][{FAINT} on #141418] + new branch [/][/]")
            sw = (f"[bold {AMBER}]⇄ BRANCH POINT[/] [{FAINT}]— pick the continuation; the thread re-flows below ·[/] "
                  f"[@click=app.thread_compare][bold {TEAL} on #141418] ⊞ compare all [/][/] [{FAINT}]o[/]\n"
                  + "  ".join(pills))
            lines.append(sw)
            for n in branches[self._active]["nodes"]:
                lines += self._node_line(n, e)
        self.query_one("#th_body", Static).update("\n".join(lines))
        # ── the action deck — continuing adds a branch pill, never a tangle ──
        deck = [(f"Counter it", "bull", GREEN), ("Stress harder", "balance-sheet-analyst", ORANGE),
                ("Compare vs…", "value-analyst", GOLD), ("Convene council", "arbiter", TEAL)]
        chips = "  ".join(f"[@click=app.thread_deck('{a}')][bold {c} on #141418] {lbl} ◇{_agent_model(a)[1]} [/][/]"
                          for lbl, a, c in deck)
        self.query_one("#th_deck", Static).update(
            f"[{FAINT}]CONTINUE — adds a new continuation from here, never a tangle[/]\n{chips}")

    def action_branch_next(self) -> None:
        _t, branches = self.app._thread_trunk_branches(self._root)
        if branches:
            self._active = (self._active + 1) % len(branches)
            self.paint()

    def concierge_context(self) -> str:
        tk, _ = self.app._thread_meta(self._root)
        return f"{tk or 'thread'} thread"


class CompareSurface(BlendSurface):
    """⊞ Compare branches — the branch ENDPOINTS side-by-side (the Matchup desk pointed inward
    at your own thread). Open any branch to make it live again."""

    SURFACE_TITLE = "COMPARE BRANCHES"
    SURFACE_GLYPH = "⊞"
    NAV_ID = "thread"
    ACCENT = TEAL

    def __init__(self, root_id: str, sub: str = "") -> None:
        super().__init__(sub=sub or "continuations weighed at a glance")
        self._root = str(root_id)

    def body(self) -> ComposeResult:
        yield Static("", id="cmp_body")

    def paint(self) -> None:
        app = self.app
        e = app._esc
        _trunk, branches = app._thread_trunk_branches(self._root)
        if not branches:
            self.query_one("#cmp_body", Static).update(
                f"[{FAINT}]no fork yet — use the thread's CONTINUE deck to add a second continuation first[/]")
            return
        lines = []
        for i, b in enumerate(branches):
            lead = b.get("lead") or "claude"
            tail = b["nodes"][-1] if b.get("nodes") else {}
            lines.append(f"[bold {b['tone']}]⑂ {e(b['label'])}[/] "
                         f"[{_MODEL_COLORS.get(_agent_model(lead)[1], DIM)}]◇{_agent_model(lead)[1]}[/]")
            lines.append(f"  [{FAINT}]ENDS AT[/]  [{SILVER}]{e(_clip(str(tail.get('text', '—')), 140))}[/]")
            lines.append(f"  [@click=app.compare_open({i})][{AMBER} on #141418] ↗ open branch [/][/]")
            lines.append("")
        self.query_one("#cmp_body", Static).update("\n".join(lines))

    def concierge_context(self) -> str:
        tk, _ = self.app._thread_meta(self._root)
        return f"{tk or 'thread'} branches"


class RosterSurface(BlendSurface):
    """The fleet, pulled open as a drawer — discovery by browsing, not by memorizing commands.
    Every card states what the agent is for and which model runs it; ▶ run loads it into the
    launch line, ⛓ chain appends it as a workflow stage."""

    SURFACE_TITLE = "FLEET ROSTER"
    SURFACE_GLYPH = "❖"
    NAV_ID = "roster"
    ACCENT = AMBER

    def __init__(self, mode: str = "browse", sub: str = "") -> None:
        n = len(HUB_AGENT_META)
        super().__init__(sub=sub or f"{n} agents · model + purpose on every card")
        self._mode = mode                                  # browse | chain (picking a stage)

    def body(self) -> ComposeResult:
        yield Static("", id="roster_body")

    def paint(self) -> None:
        app = self.app
        e = app._esc
        lines = []
        if self._mode == "chain":
            lines.append(f"[bold {TEAL}]⛓ pick an agent to append as the next chain stage[/]")
        for gid, gtitle, gnote in HUB_GROUPS:
            members = [a for a, m in HUB_AGENT_META.items() if m[0] == gid]
            if not members:
                continue
            lines.append(f"[bold {AMBER}]{gtitle.upper()}[/]  [{FAINT}]{e(gnote)}[/]")
            for a in members:
                prov, model = _agent_model(a)
                doc = HUB_AGENT_DOC.get(a, {})
                nm = f"[bold {TEAL if prov == 'gemini' else GOLD}]{e(a)}[/]"
                lines.append(f"  {nm} [{_MODEL_COLORS.get(model, SILVER)}]◇{model}[/]"
                             f"  [@click=app.roster_run('{e(a)}')][bold {GREEN} on #141418] ▶ run [/][/]"
                             f" [@click=app.roster_chain('{e(a)}')][{TEAL} on #141418] ⛓ chain [/][/]")
                lines.append(f"    [{SILVER}]{e(_clip(str(doc.get('what', doc.get('tag', ''))), 110))}[/]")
            lines.append("")
        self.query_one("#roster_body", Static).update("\n".join(lines))

    def concierge_context(self) -> str:
        return "fleet roster"


class QuestLogSurface(BlendSurface):
    """QUEST LOG, focused — the unified feed full-width (the wireframe's 'A' tab). Same events,
    same filled badges, same ▸/▾ depth as the Blend home's center column, but with the rails out
    of the way so the feed gets the whole screen. Filter chips · ↑↓ select · ⏎ open · space expand."""

    SURFACE_TITLE = "QUEST LOG"
    SURFACE_GLYPH = "⑂"
    NAV_ID = "quest"
    ACCENT = AMBER
    BINDINGS = BlendSurface.BINDINGS + [
        Binding("f", "filter_next", "Filter"),
        Binding("g", "app.blend_lanes_toggle", "Lanes/stream"),
        Binding("up", "move(-1)", "Up", show=False), Binding("down", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False), Binding("j", "move(1)", "Down", show=False),
        Binding("enter", "open_sel", "Open", show=False), Binding("space", "expand_sel", "Expand", show=False),
    ]

    def __init__(self, flt: str = "all", sub: str = "") -> None:
        super().__init__(sub=sub or "the unified feed, full-width")
        self._filter = flt
        self._sel = -1
        self._items: list = []
        self._expanded: set = set()

    def body(self) -> ComposeResult:
        yield Static("", id="quest_filters")
        yield Static("", id="quest_log")

    def paint(self) -> None:
        app = self.app
        self._items = app._blend_log_items(self._filter)
        chips = []
        for fid, lbl in BLEND_FILTERS:
            on = (fid == self._filter)
            chips.append(f"[@click=app.blend_filter('{fid}')]"
                         f"[bold {'#08080A on ' + AMBER if on else DIM + ' on #141418'} ] {lbl} [/][/]")
        lanes_on = getattr(app, "_blend_lanes_quest", True)
        layout = (f"[@click=app.blend_lanes_toggle]"
                  f"[bold {'#08080A on ' + AMBER if lanes_on else DIM + ' on #141418'} ] ⫴ lanes [/][/]")
        try:
            self.query_one("#quest_filters", Static).update(
                f"[bold {AMBER}]QUEST LOG[/]  [{FAINT}]{len(self._items)}[/]   " + " ".join(chips)
                + f"  [{FAINT}]f[/]   " + layout + f"  [{FAINT}]g[/]")
        except Exception:
            pass
        if lanes_on:
            body = _blend_feed_lanes(self._items, self._sel, self._expanded, lane_w=48)
            if not self._items:
                body = Text("nothing yet — open THE BLEND (1) and launch, or ask (/)", style=DIM)
        else:
            parts = _blend_feed_parts(self._items, self._sel, self._expanded, title_w=68, wrap_w=120)
            if not self._items:
                parts.append(Text("nothing yet — open THE BLEND (1) and launch, or ask (/)", style=DIM))
            body = Group(*parts)
        try:
            self.query_one("#quest_log", Static).update(body)
        except Exception:
            pass

    # the feed-action contract shared with the Blend home (resolved by _feed_screen)
    def toggle_expand(self, ref) -> None:
        it = self.app._blend_item_by_ref(self, ref)        # by stable uid (click) or _sel index (keyboard)
        uid = it.get("uid") if it else None
        if uid:
            self._expanded.symmetric_difference_update({uid})
            self.paint()

    def set_filter(self, f: str) -> None:
        if f in dict(BLEND_FILTERS):
            self._filter = f
            self._sel = -1
            self.paint()

    def action_filter_next(self) -> None:
        keys = [f for f, _ in BLEND_FILTERS]
        self._filter = keys[(keys.index(self._filter) + 1) % len(keys)]
        self._sel = -1
        self.paint()

    def action_move(self, d: int) -> None:
        if self._items:
            self._sel = (self._sel + int(d)) % min(len(self._items), 40)
            self.paint()

    def action_open_sel(self) -> None:
        if 0 <= self._sel < len(self._items):
            self.app.action_blend_open(self._sel)

    def action_expand_sel(self) -> None:
        if 0 <= self._sel < len(self._items):
            self.toggle_expand(self._sel)

    def concierge_context(self) -> str:
        return "Quest Log"


class BlendHubScreen(ModalScreen, ConciergeDock):
    """THE BLEND — the unified Agent Hub (press h). The QUEST LOG is home: a live feed of past
    and current research events; each row opens its matching surface on click (or ⏎). LAUNCH
    (left) fires a chain or a 1v1 on a target; the WORKING LANE (right) carries every in-flight
    run, AUTO/MANUAL tagged, model on each. The Roster is a drawer; the Concierge rides the
    bottom; the `/` command bar stays demoted — a power path, never the only way in."""

    NAV_ID = "blend"
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("f", "filter_next", "Filter"),
        Binding("g", "app.blend_lanes_toggle", "Lanes/stream"),
        Binding("m", "matchup", "1v1 matchup"),
        Binding("r", "roster", "Roster"),
        Binding("c", "concierge", "Concierge"),
        Binding("slash", "cmd", "Command", show=False),
        Binding("up", "move(-1)", "Up", show=False), Binding("down", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False), Binding("j", "move(1)", "Down", show=False),
        Binding("enter", "open_sel", "Open", show=False),
        Binding("space", "expand_sel", "Expand", show=False),
        Binding("1", "app.blend_nav('blend')", "Blend", show=False),
        Binding("2", "app.blend_nav('quest')", "Quest Log", show=False),
        Binding("3", "app.blend_nav('pipeline')", "Pipeline", show=False),
        Binding("4", "app.blend_nav('matchup')", "Matchup", show=False),
        Binding("5", "app.blend_nav('roster')", "Roster", show=False),
        Binding("6", "app.blend_nav('thread')", "Thread", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._filter = "all"
        self._sel = -1
        self._items: list = []
        self._expanded: set = set()                        # uids unfolded in place (▸/▾ · space)
        self._suggests: list = []                          # live command-bar completions
        self._timer = None
        self._home = "chat"                                # blend home: 'chat' (conversation) | 'log' (quest log)

    def compose(self) -> ComposeResult:
        with Vertical(id="blend_box"):
            yield Static("", id="blend_head")
            yield Static("", id="blend_nav")
            yield Static("", id="blend_intro")              # the toggleable design-intent note
            with Horizontal(id="blend_main"):
                with VerticalScroll(id="blend_launch"):
                    yield Static("", id="blend_launch_body")
                with Vertical(id="blend_center"):
                    yield Static("", id="blend_filters")
                    with VerticalScroll(id="blend_logwrap"):
                        yield Static("", id="blend_log")
                    yield Static("", id="blend_suggest")
                    yield Input(placeholder='command — "@bear stress AGA.V" · "scout silver" · a bare ticker sets the target',
                                id="blend_cmd")
                with VerticalScroll(id="blend_lane"):
                    yield Static("", id="blend_lane_body")
            yield from self.compose_concierge()
            yield Static("", id="blend_foot")

    def on_mount(self) -> None:
        self.paint_all()
        if self._home == "chat":                            # the compose is always-on in chat-home mode
            try:
                bar = self.query_one("#blend_cmd", Input)
                bar.add_class("open")
                bar.placeholder = "Ask anything — plain English, @agent, or a command…"
            except Exception:
                pass
        self._timer = self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        try:
            self.paint_lane()
            self.paint_log()
            self.paint_head()
        except Exception:
            pass

    def paint_all(self) -> None:
        self.paint_head()
        self.paint_nav()
        self.paint_launch()
        self.paint_log()
        self.paint_lane()
        self.paint_concierge()
        self.paint_foot()

    def paint_nav(self) -> None:
        try:
            self.query_one("#blend_nav", Static).update(_jobnav_markup())
            intro = self.query_one("#blend_intro", Static)
            intro.set_class(bool(self.app._blend_notes), "open")
            intro.update(
                f"[{AMBER}]✱ Organized around your three jobs, by rising consequence.[/] "
                f"[bold {GREEN}]◆ Watch[/] [{DIM}]the book ·[/] [bold {AMBER}]▲ Screen[/] "
                f"[{DIM}]the kill-funnel ·[/] [bold {RED}]⇄ Change[/] [{DIM}]the book diff. The "
                f"mechanisms are drawers now —[/] [bold {GOLD}]log[/] [{DIM}](this feed — the "
                f"provenance),[/] [bold {GOLD}]fleet[/][{DIM}], and a[/] [{CONCIERGE_C}]Concierge[/] "
                f"[{DIM}](plain LLM) on the bottom. Keys 1-6 still reach every surface.[/]")
        except Exception:
            pass

    # ---- chrome ----
    def paint_head(self) -> None:
        a = self.app
        head = Text()
        head.append("◆ ", style=f"bold {AMBER}")
        head.append("CommodityEx", style=f"bold {GOLD}")
        head.append("  ⛓ AGENT HUB", style=f"bold {AMBER}")
        head.append("  the blend", style=FAINT)
        tiers = [m for m in ("opus", "sonnet") if any(v == ("claude", m) for v in HUB_AGENT_MODEL.values())]
        head.append("   ● FLEET ", style=DIM)
        head.append("·".join(tiers), style=f"bold {AMBER_BRIGHT}")
        head.append(" + ", style=DIM)
        head.append("gemini", style=f"bold {TEAL}")
        for tk, ev, din, macro in a._hub_calendar_windows(2):
            head.append("   ⛏ ", style=DIM)
            head.append(f"{tk} ", style=(DIM if macro else f"bold {GOLD}"))
            head.append(f"{ev} ", style=DIM)
            head.append(din, style=AMBER)
        aw, wk, sc = a._hub_status_counts()
        head.append("    ⚑ ", style=AMBER); head.append(f"{aw} ", style=f"bold {GOLD}"); head.append("awaiting", style=DIM)
        head.append("  ⟳ ", style=GREEN);  head.append(f"{wk} ", style=f"bold {GOLD}"); head.append("working", style=DIM)
        head.append("  ◔ ", style=ORANGE); head.append(f"{sc} ", style=f"bold {GOLD}"); head.append("scheduled", style=DIM)
        on = bool(a._blend_notes)                           # the wireframe's NOTES toggle (intro note)
        head.append("    ")
        head.append(" NOTES ", style=Style.parse(f"bold {'#08080A on ' + AMBER if on else DIM + ' on #141418'}")
                    + Style(meta={"@click": "app.blend_notes_toggle"}))
        try:
            self.query_one("#blend_head", Static).update(head)
        except Exception:
            pass

    def paint_foot(self) -> None:
        try:
            self.query_one("#blend_foot", Static).update(
                f"[{DIM}]1-6 focus a tab · ⏎ open · ↑↓ select · f filter · c concierge · / command · esc[/]"
                f"    [@click=app.open_hub_classic][{FAINT}]⌘ mission control (classic)[/][/]")
        except Exception:
            pass

    # ---- LAUNCH (left rail): run verbs → each opens its setup (subject-at-fire) ----
    def paint_launch(self) -> None:
        a = self.app
        e = a._esc
        if self._home == "chat":                            # left rail = the CONVERSATIONS sidebar
            launch = (f"[@click=app.blend_matchup][{FAINT}]⇄ matchup[/][/]    "
                      f"[@click=app.blend_roster][{FAINT}]❖ fleet[/][/]    "
                      f"[@click=app.blend_nav('quest')][{FAINT}]☰ quest log[/][/]    "
                      f"[@click=app.retract_flywheel][{FAINT}]⌫ clean log[/][/]")
            try:
                self.query_one("#blend_launch_body", Static).update(
                    a._hub_convos_markup() + f"\n\n[{BORDER}]{'─' * 22}[/]\n{launch}")
            except Exception:
                pass
            return
        nodes = (a._state or {}).get("nodes", {}) or {}
        focus = a._blend_subject()
        g = _ROLE_GLYPH.get((nodes.get(focus, {}) or {}).get("role", ""), "")
        lines = [f"[bold {GOLD}]LAUNCH[/]  [@click=app.blend_cmd][{FAINT}]or / command[/][/]"]
        # subject-at-fire: there's no sticky target — each launch confirms the name in its setup,
        # defaulted to the focused one. The rail just shows that default + where you pick it.
        lines.append(f"[{FAINT}]on the focused name[/] [bold {GOLD}]{g}{e(focus)}[/]"
                     f"  [{FAINT}]· edit per-launch in setup[/]")
        lines.append("")
        lines.append(f"[{FAINT}]RUN[/]")
        lines.append(f"[@click=app.blend_matchup][bold {AMBER_BRIGHT} on #141418] ⇄ MATCHUP BENCH [/][/]"
                     f" [{FAINT}]hold vs 1–{MatchupSurface.MAX_CHAL} · m[/]")
        for name, steps in a._blend_workflows().items():
            ids = [x for s in steps for x in s.get("agents", [])]
            models = "·".join(dict.fromkeys(_agent_model(x)[1] for x in ids[:3]))
            lines.append(f"[@click=app.blend_configure('{e(name)}')][bold {TEAL} on #141418] ⛓ {e(name.upper())} [/][/]"
                         f" [{FAINT}]{len(ids)} seats · {e(models)}[/]")
        lines.append(f"[@click=app.blend_roster][{DIM} on #141418] ❖ BROWSE FLEET [/][/]"
                     f" [{FAINT}]{len(HUB_AGENT_META)} agents · r[/]")
        ctx = a._hub_compose_ctx
        if ctx:
            lines.append("")
            lines.append(f"[{TEAL}]↩ follow-up context:[/] [{SILVER}]{e(_clip(str(ctx.get('summary', '')), 26))}[/] "
                         f"[@click=app.hub_ctx_clear][{FAINT}](×)[/][/]")
        try:
            self.query_one("#blend_launch_body", Static).update("\n".join(lines))
        except Exception:
            pass

    # ---- QUEST LOG (center): filters + the feed ----
    def paint_filters(self) -> None:
        e = self.app._esc
        chips = []
        for fid, lbl in BLEND_FILTERS:
            on = (fid == self._filter)
            chips.append(f"[@click=app.blend_filter('{fid}')]"
                         f"[bold {'#08080A on ' + AMBER if on else DIM + ' on #141418'} ] {lbl} [/][/]")
        lanes_on = getattr(self.app, "_blend_lanes", True)
        layout = (f"[@click=app.blend_lanes_toggle]"
                  f"[bold {'#08080A on ' + AMBER if lanes_on else DIM + ' on #141418'} ] ⫴ lanes [/][/]")
        try:
            self.query_one("#blend_filters", Static).update(
                f"[bold {AMBER}]QUEST LOG[/]  [{FAINT}]{len(self._items)}[/]   " + " ".join(chips)
                + f"  [{FAINT}]f[/]   " + layout + f"  [{FAINT}]g[/]")
        except Exception:
            pass

    def paint_log(self) -> None:
        a = self.app
        if self._home == "chat":                            # center = the linear active conversation
            try:
                self.query_one("#blend_filters", Static).update(
                    f"[bold {AMBER}]CONVERSATION[/]   [{FAINT}]2 quest log · 6 threads · / command[/]")
                self.query_one("#blend_log", Static).update(a._chat_markup())
            except Exception:
                pass
            return
        self._items = a._blend_log_items(self._filter)
        self.paint_filters()
        if getattr(a, "_blend_lanes", True):
            body = _blend_feed_lanes(self._items, self._sel, self._expanded, lane_w=30)
            if not self._items:
                body = Text("nothing yet — launch left, or ask (/)", style=DIM)
        else:
            parts = _blend_feed_parts(self._items, self._sel, self._expanded, title_w=50, wrap_w=92)
            if not self._items:
                parts.append(Text("nothing yet — launch left, or ask (/)", style=DIM))
            else:
                parts.append(Text(""))
                parts.append(Text("· earlier → ⌘ mission control ·", style=FAINT))
            body = Group(*parts)
        try:
            self.query_one("#blend_log", Static).update(body)
        except Exception:
            pass

    # ---- WORKING LANE (right rail): every in-flight run ----
    def paint_lane(self) -> None:
        a = self.app
        e = a._esc
        now = time.time()
        live = [(jid, j) for jid, j in a._inflight.items() if not j.get("cancelled")]
        pipe = (a._state or {}).get("pipeline") or {}
        pipe_running = a._pipe_is_live(pipe) and not a._pipe_is_echo(pipe)
        n = len(live) + (1 if pipe_running else 0) + (1 if a._wf_running else 0)
        head = f"[bold {TEAL}]WORKING LANE[/]  [bold {GOLD}]{n}[/]"
        if n:                                              # one button clears the whole lane
            head += f"   [@click=app.blend_clear_lane][{ORANGE} on #141418] ⏹ clear all [/][/]"
        lines = [head]
        if a._wf_running:
            idx = int(getattr(a, "_wf_stage_idx", 0))
            total = len(a._workflow or []) or 1
            paused = bool(a._wf_ctl.get("pause"))
            lines.append(f"[@click=app.blend_open_pipeline][bold {AMBER}]⛓ chain[/] "
                         f"[{SILVER}]{e(a._wf_subject or a._blend_subject())}[/] [{DIM}]· stage {min(idx + 1, total)}/{total}"
                         f"{' · ⏸ paused' if paused else ''}[/] [{AMBER}]↗ watch[/][/]"
                         f"  [@click=app.blend_clear_chain][{ORANGE}]✗[/][/]")
            lines.append("  " + _bar_markup((idx) / total, AMBER))
        for jid, j in live:
            el = max(0, int(now - j.get("started", now)))
            who, task = a._task_label(j)
            prov = j.get("provider") or a._agent_provider(who)
            model = _run_model_label(who, prov)
            auto = str(j.get("kind", "")) in ("job", "sweep", "sentinel")
            mode = f"[{TEAL}]↺ AUTO[/]" if auto else f"[{DIM}]MANUAL[/]"
            lines.append(f"[@click=app.blend_monitor('{jid}')][bold {SILVER}]{e(who)}[/] "
                         f"[{_MODEL_COLORS.get(model, DIM)}]◇{model}[/] {mode}[/]"
                         f" [@click=app.cancel_job('{jid}')][{ORANGE}]✗[/][/]")
            lines.append(f"  [{DIM}]{e(_clip(task or 'working…', 34))}[/]")
            lines.append("  " + _bar_markup(min(0.95, el / 180.0), _provider_color(who)) + f" [{FAINT}]{el}s[/]")
        if pipe_running:
            lines.append(f"[@click=app.blend_open_pipeline][bold {SILVER}]pipeline[/] "
                         f"[{DIM}]{e(_clip(pipe.get('theme', ''), 20))} · {e(str(pipe.get('stage', '')))}[/] "
                         f"[{AMBER}]↗ watch[/][/]"
                         f"  [@click=app.blend_dismiss_pipeline][{ORANGE}]✗[/][/]")
        if n == 0:
            lines.append(f"[{FAINT}]no runs — launch from the left rail[/]")
        for r_ in (a._receipts or [])[-2:]:                # reversibility stays visible
            undo = (f" [@click=app.undo_receipt('{r_['id']}')][{GOLD}]↶[/][/]" if r_.get("undo") else "")
            lines.append(f"[{r_['color']}]{r_['glyph']}[/] [{DIM}]{e(_clip(r_['text'], 30))}[/]{undo}")
        try:
            self.query_one("#blend_lane_body", Static).update("\n".join(lines))
        except Exception:
            pass

    # ---- actions (every one of these also has a clickable affordance) ----
    def action_close(self) -> None:
        try:                                               # esc steps back: open command bar first
            bar = self.query_one("#blend_cmd", Input)
            if bar.has_class("open"):
                bar.set_class(False, "open")
                bar.value = ""
                self._hide_suggest()
                self.set_focus(None)
                return
        except Exception:
            pass
        self.dismiss(None)

    # ---- ▸/▾ in-place expansion (click the caret · space on the selected row) ----
    def toggle_expand(self, ref) -> None:
        it = self.app._blend_item_by_ref(self, ref)        # by stable uid (click) or _sel index (keyboard)
        uid = it.get("uid") if it else None
        if uid:
            self._expanded.symmetric_difference_update({uid})
            self.paint_log()

    def action_expand_sel(self) -> None:
        if 0 <= self._sel < len(self._items):
            self.toggle_expand(self._sel)

    # ---- chat-aware completion: "@s" → every agent starting with s · prefixes · tickers ----
    def _build_suggests(self, val: str) -> list:
        """[(insert, label, hint)] for the command bar's current text. '@' completes agents;
        a bare first token completes command prefixes, saved chains, and book tickers."""
        val = str(val or "")
        if not val or " " in val.rstrip() and not val.startswith("@"):
            return []
        if val.startswith("@"):
            if " " in val:                                 # agent already chosen — stop suggesting
                return []
            pre = val[1:].lower()
            return [(f"@{a} ", f"@{a}", str(HUB_AGENT_DOC.get(a, {}).get("tag", "")))
                    for a in HUB_AGENT_META if a.startswith(pre)][:6]
        if " " in val:
            return []
        low = val.lower()
        out = []
        for p, hint in (("note:", "→ Living Memory"), ("catalyst:", "log a catalyst"),
                        ("claim:", "→ Thesis Ledger"), ("rule:", "arm a Ulysses rule"),
                        ("scenario:", "→ what-if forge"), ("what if ", "→ what-if forge")):
            if p.startswith(low) and p != low:
                out.append((p, p.strip(), hint))
        for tk in (self.app._baskets_by_ticker or {}):
            if str(tk).lower().startswith(low):
                out.append((str(tk), str(tk), "set the target"))
        return out[:6]

    def _hide_suggest(self) -> None:
        self._suggests = []
        try:
            self.query_one("#blend_suggest", Static).set_class(False, "open")
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "blend_cmd":
            return
        self._suggests = self._build_suggests(event.value)
        try:
            box = self.query_one("#blend_suggest", Static)
        except Exception:
            return
        if not self._suggests:
            box.set_class(False, "open")
            return
        e = self.app._esc
        lines = []
        for ins, lbl, hint in self._suggests:
            lines.append(f"[@click=app.blend_complete('{e(ins)}')][bold {AMBER} on #141418] {e(lbl)} [/][/]"
                         + (f"  [{FAINT}]{e(_clip(hint, 56))}[/]" if hint else ""))
        lines.append(f"[{FAINT}]tab completes the first · click any[/]")
        box.update("\n".join(lines))
        box.set_class(True, "open")

    def on_key(self, event) -> None:
        """Tab completes the first suggestion while the command bar is live (click is the floor)."""
        if (getattr(event, "key", "") == "tab" and self._suggests
                and getattr(self.focused, "id", "") == "blend_cmd"):
            event.prevent_default()
            event.stop()
            self.app.action_blend_complete(self._suggests[0][0])

    def action_filter_next(self) -> None:
        keys = [f for f, _ in BLEND_FILTERS]
        self._filter = keys[(keys.index(self._filter) + 1) % len(keys)]
        self._sel = -1
        self.paint_log()

    def set_filter(self, f: str) -> None:
        if f in dict(BLEND_FILTERS):
            self._filter = f
            self._sel = -1
            self.paint_log()

    def action_move(self, d: int) -> None:
        if self._items:
            self._sel = (self._sel + int(d)) % min(len(self._items), 40)
            self.paint_log()

    def action_open_sel(self) -> None:
        if 0 <= self._sel < len(self._items):
            self.app.action_blend_open(self._sel)

    def action_matchup(self) -> None:
        self.app.action_blend_matchup()

    def action_roster(self) -> None:
        self.app.action_blend_roster()

    def action_cmd(self) -> None:
        """`/` — summon the demoted command bar (the power path, hidden until called)."""
        try:
            bar = self.query_one("#blend_cmd", Input)
            bar.set_class(True, "open")
            bar.focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "con_input":
            event.stop()
            q = (event.value or "").strip()
            event.input.value = ""
            if q:
                self.app._concierge_send(q, self.concierge_context())
            return
        if event.input.id != "blend_cmd":
            return
        event.stop()
        app = self.app
        val = (event.value or "").strip()
        event.input.value = ""
        event.input.set_class(False, "open")
        self._hide_suggest()
        if not val:
            return
        low = val.lower()
        ctx = app._hub_compose_ctx                          # ↩ follow-up resumes that thread
        if ctx and not any(low.startswith(p) for p in ("note:", "catalyst:", "claim:", "rule:", "scenario:")):
            app._active = ctx.get("tail") or ctx.get("root")
            app._hub_compose_ctx = None
        if low.startswith("note:"):
            app._write_note(val.split(":", 1)[1].strip())
        elif low.startswith("catalyst:"):
            app._write_catalyst(val.split(":", 1)[1].strip())
        elif low.startswith("claim:"):
            app._amend_thesis_claim(val.split(":", 1)[1].strip())
        elif low.startswith("rule:"):
            app._amend_thesis_rule(val.split(":", 1)[1].strip())
        elif low.startswith("scenario:") or low.startswith("what if ") or low.startswith("what-if "):
            idea = val.split(":", 1)[1].strip() if ":" in val.split(" ", 1)[0] else val.split(" ", 1)[1].strip()
            app._hub_scenario(idea)
            return
        else:
            up = val.upper()
            if up in (app._baskets_by_ticker or {}) or (("." in val or up == val) and " " not in val and 1 < len(val) <= 8):
                app._set_focus(up, move_cursor=True)        # a bare ticker = "look at this name" (the default subject)
                app._toast(f"focus → {up}", TEAL)
            elif val.startswith("@"):
                parts = val[1:].split(None, 1)
                brief = parts[1] if len(parts) > 1 else ""
                # free-form by default: scope ONLY to a ticker the user explicitly typed, never the
                # global focus — an unscoped @agent question is about what you asked, not the open card.
                app._delegate(parts[0], brief, subject=app._detect_ticker(brief),
                              continue_thread=True)          # the chat compose continues the open chat
            else:
                agent, verb, tk = app._route_intent(val)
                if tk:
                    app._set_focus(tk)                       # the intent named a name → look at it
                if agent:
                    # subject = the explicitly named ticker only (tk), or None for a free-form chat —
                    # the focused name is no longer auto-applied to whatever you type.
                    app._delegate(agent, val, subject=tk, verb=verb,
                                  continue_thread=True)
                else:
                    app._ask_agent(val, ticker=tk, continue_thread=True)
                    app._toast("routed to the orchestrator — it'll pick the agent", TEAL)
        self.paint_all()

    def concierge_context(self) -> str:
        return "Quest Log"

    def on_click(self, event) -> None:
        pass                                               # full-screen home — no backdrop dismiss


def _bar_markup(frac: float, color: str, width: int = 18) -> str:
    """A block-char progress bar as markup (the eased Bar of the mock, cell-snapped)."""
    fill = max(0, min(width, round(width * float(frac))))
    return f"[{color}]{'█' * fill}[/][{BORDER}]{'░' * (width - fill)}[/]"


