"""CommodityEx FastAPI layer — the HTTP/WebSocket surface over the engine orchestrator.

Mechanically moved out of engine.py (Arch 2 split): the `engine = CommodityExMonitor()`
singleton, the websocket broadcaster, the lifespan hook and every route are verbatim. The
launch entrypoint is unchanged — `python engine.py` imports `app` from here in its
`__main__` block and runs uvicorn on 127.0.0.1:8000 exactly as before; `uvicorn engine_api:app`
(or the lazy `engine.app` re-export) reaches the same single app instance.
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from dynamic_config import ConfigError
from engine import CommodityExMonitor

engine = CommodityExMonitor()
active_websockets = []

async def websocket_broadcaster():
    last_broadcast_state = None
    while True:
        current_state_json = json.dumps(engine.published_state)   # A1.9: complete frames only
        if current_state_json != last_broadcast_state:
            dead_sockets = []
            for ws in active_websockets:
                try: 
                    await ws.send_text(current_state_json)
                except Exception: 
                    dead_sockets.append(ws)
            for ws in dead_sockets: 
                active_websockets.remove(ws)
            last_broadcast_state = current_state_json
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the worker tasks (A1.9: all supervised — a dead loop must be visible, never silent)
    import task_supervision as _tsup
    tasks = engine.start_background_tasks()
    _health = engine.terminal_state.setdefault("worker_health", {})
    engine_task = _tsup.create_supervised("eval_loop", engine._run_loop(), health=_health)
    broadcaster_task = _tsup.create_supervised("ws_broadcaster", websocket_broadcaster(), health=_health)
    yield
    engine_task.cancel()
    broadcaster_task.cancel()
    for t in tasks:
        t.cancel()
    import os
    os._exit(0)

app = FastAPI(title="CommodityEx Terminal Engine", lifespan=lifespan)

@app.get("/state")
async def get_state():
    # A1.9: serve the last COMPLETE published frame, never the live working dict mid-write.
    return engine.published_state

@app.get("/dashboard")
async def dashboard():
    """The visual glance cockpit (web/cockpit.html) — a THIN consumer of /state, same contract as
    the TUI and the matrix node. Served same-origin so its fetch("/state") polling just works."""
    from fastapi.responses import FileResponse
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "web", "cockpit.html")
    return FileResponse(path, media_type="text/html")

@app.post("/action/whatif")
async def action_whatif(body: dict):
    """Shared action spine (Iteration 2): scenario revaluation. Body: {ticker, overrides}.
    The run_valuation_whatif MCP tool, the /whatif cockpit command and a future Flutter button
    all POST here, so every face computes the identical result."""
    return engine.run_whatif(body.get("ticker"), body.get("overrides", {}))

@app.get("/ui/state")
async def get_ui_state():
    """What a frontend is currently showing — read by agents via the get_ui_context MCP tool."""
    return engine.ui.get()

@app.post("/ui/state")
async def post_ui_state(body: dict):
    """A frontend (Flutter) reports its on-screen context: {focused_ticker, active_view,
    current_scenario, visible_tickers, selected_whatif}. Partial patches are merged."""
    return engine.set_ui_state(body)

@app.post("/ui/command")
async def post_ui_command(body: dict):
    """Agents steer the frontend: {action: focus|view|scenario|highlight|alert, args:{...}}
    -> broadcast on /ws under terminal_state['ui_command']."""
    return engine.push_ui_command(body)

# ---- Ambient agent-activity bus (Claude Code hooks / agents -> live cockpit stream) ----
@app.post("/agent/activity")
async def agent_activity_post(body: dict):
    """Record what an agent is doing: {agent, kind, summary, ticker?}. kind is prompt | tool |
    response | note | proposal. Rides terminal_state['agent_activity'] (and /ws), so the cockpit
    Signals rail streams agent work with zero extra polling. Used by the .claude/hooks scripts."""
    return engine.record_agent_activity(body)

@app.get("/agent/activity")
async def agent_activity_get():
    return {"agent_activity": engine.published_state.get("agent_activity", [])}

@app.post("/action/ask")
async def action_ask(body: dict):
    """The dashboard command bar's spine: an operator question typed into the web cockpit.

    GROUNDED-OR-SILENT applied to the desk itself — a question the operator asked must never
    evaporate because no agent happened to be listening (the web bar previously fired a toast and
    dropped the text). It lands in TWO places: the ephemeral desk tape (agent_activity, so the TUI
    and any agent pane see it live) and the IMMUTABLE record (Living Memory, tagged ``ask``), so the
    thread survives a restart and the next agent session can pick it up with memory_query.
    Decision-support only: recording a question never mutates the book."""
    text = " ".join(str((body or {}).get("text", "")).split())[:2000]
    if not text:
        return {"ok": False, "error": "empty question"}
    ticker = (body or {}).get("ticker") or None
    engine.record_agent_activity({"agent": "operator", "kind": "prompt",
                                  "summary": text, "ticker": ticker})
    entry_id = None
    try:
        import living_memory
        lm = getattr(engine, "_lm", None) or living_memory.LivingMemory()
        engine._lm = lm
        entry = lm.write("note", text=f"ASK (cockpit) — {text}", ticker=ticker,
                         source="operator", provenance="user", tags=["ask", "cockpit"],
                         regime={"mri": engine.terminal_state.get("mri"),
                                 "posture": (engine.terminal_state.get("posture") or {}).get("code")})
        entry_id = entry["id"]
    except Exception as e:                      # the tape still has it — never lose the question
        logging.warning("ask not persisted to memory (tape still holds it): %s", e)
    return {"ok": True, "text": text, "memory_id": entry_id,
            "note": "recorded to the desk tape + Living Memory; answered in the Claude pane"}

@app.post("/pipeline/event")
async def pipeline_event_post(payload: dict):
    return engine.record_pipeline_event(payload or {})

@app.get("/pipeline")
async def pipeline_get():
    return engine.published_state.get("pipeline", {})

# ---- PREDICT arb scanner (Wealthsimple Predict / Kalshi; read-only feed, alert-only outputs) ----
@app.get("/predict")
async def predict_get():
    """The last swept PREDICT dash (L1 structural + L2 value opportunities, net of fees)."""
    return engine.published_state.get("predict_arb", {})

@app.post("/predict/refresh")
async def predict_refresh_post():
    """On-demand fetch + sweep + fire — the predict_scan MCP tool's refresh path."""
    return await engine.predict_refresh()

@app.post("/predict/fair_value")
async def predict_fair_value_post(body: dict):
    """Record a SOURCED first-principles probability (p̂) for one market -> the L2 lane.
    {ticker, p_hat, band?, source, note?}. Grounded-or-silent: source required."""
    return engine.set_predict_fair_value(body or {})

# ---- FMP (free-tier: fundamentals + treasury; hard-cached + daily-budget-capped, on-demand) ----
@app.get("/fmp/fundamentals")
async def fmp_fundamentals(ticker: str = ""):
    if not getattr(engine, "fmp", None):
        return {"error": "FMP unavailable (no key / module). Set FMP_API_KEY in .env."}
    if not ticker:
        return {"error": "ticker required"}
    return engine.fmp.profile(ticker)

@app.get("/fmp/treasury")
async def fmp_treasury():
    if not getattr(engine, "fmp", None):
        return {"error": "FMP unavailable (no key / module). Set FMP_API_KEY in .env."}
    return engine.fmp.treasury()

@app.get("/fmp/budget")
async def fmp_budget():
    if not getattr(engine, "fmp", None):
        return {"available": False}
    return {"available": True, "calls_remaining": engine.fmp.calls_remaining(),
            "daily_budget": engine.fmp.daily_budget}

# ---- Dynamic configuration (overlay on v5_config.json; hot-reloaded each loop) ----
def _dc_guard():
    if getattr(engine, "dconfig", None) is None:
        return {"error": "dynamic config unavailable"}
    return None

@app.get("/config/params")
async def config_params():
    """Effective tunables + which are overridden (the editable allowlist)."""
    return _dc_guard() or {"params": engine.dconfig.list_params()}

def _write_source_ok(source) -> bool:
    """Human-in-the-loop gate on APPLYING a config mutation. Only the cockpit/human channel may
    write directly OR confirm a pending change; every agent/MCP source must route through
    /config/propose and the operator's /confirm. Audit A2.2 hardened the DIRECT-write endpoint;
    the 2026-07-02 reassessment (finding #1) found the CONFIRM side was source-blind — the same
    gate now guards both, so an agent can neither self-write nor self-confirm a tunable."""
    s = str(source or "")
    return s == "cockpit" or s.startswith("human")


@app.post("/config/param")
async def config_set(body: dict):
    """Set an override directly — HUMAN-ONLY (audit A2.2: the proposal gate is a hard line, not
    etiquette). Only the cockpit/human channel may write directly; any agent source is refused and
    told to route through /config/propose -> the /confirm gate. {key, value} -> hot-applies."""
    if (g := _dc_guard()):
        return g
    src_id = str(body.get("source", "cockpit"))
    if not _write_source_ok(src_id):
        return {"refused": True, "source": src_id,
                "error": "direct param writes are human-only — agents must use /config/propose "
                         "(propose_param_change) and the operator's /confirm gate"}
    try:
        res = engine.dconfig.set_param(body.get("key"), body.get("value"),
                                       source=body.get("source", "cockpit"), reason=body.get("reason"))
        engine._refresh_effective_config()   # file defaults + overrides -> reaches every engine provider
        return {"ok": True, **res}
    except ConfigError as e:
        return {"error": str(e)}

@app.post("/config/param/reset")
async def config_reset(body: dict):
    if (g := _dc_guard()):
        return g
    res = engine.dconfig.reset_param(body.get("key"))
    engine._refresh_effective_config()   # file defaults + overrides -> reaches every engine provider
    return {"ok": True, **res}

@app.post("/config/propose")
async def config_propose(body: dict):
    """Agents propose a change with reasoning -> pending queue (nothing applies until confirmed)."""
    if (g := _dc_guard()):
        return g
    try:
        return {"ok": True, **engine.dconfig.propose(body.get("key"), body.get("value"),
                                                     body.get("reason"), body.get("proposed_by", "agent"))}
    except ConfigError as e:
        return {"error": str(e)}

@app.post("/config/cut_holding")
async def config_cut_holding(body: dict):
    """Cut a book holding to 0% and redistribute its weight across the survivors (AGA.V capped at the
    60% spear ceiling) -> filed as a PROPOSAL (sum-to-1 + ceiling validated); the operator /confirms."""
    if (g := _dc_guard()):
        return g
    try:
        return {"ok": True, **engine.dconfig.propose_cut_holding(
            body.get("ticker"), reason=body.get("reason"),
            proposed_by=body.get("proposed_by", "agent"))}
    except ConfigError as e:
        return {"error": str(e)}

@app.get("/config/pending")
async def config_pending():
    return _dc_guard() or {"pending": engine.dconfig.pending()}

@app.post("/config/confirm")
async def config_confirm(body: dict):
    """Human confirms a pending change -> applied + hot-reloaded. HUMAN-ONLY, same gate as the
    direct-write endpoint: confirming applies a mutation, so an agent source is refused (finding #1,
    2026-07-02 reassessment — the confirm side was previously source-blind). The cockpit UI and the
    operator's /confirm both present as ``cockpit``; agents must leave the trigger to the operator."""
    if (g := _dc_guard()):
        return g
    src_id = str(body.get("source", "cockpit"))
    if not _write_source_ok(src_id):
        return {"refused": True, "source": src_id,
                "error": "confirming a pending change is human-only — the operator applies via the "
                         "cockpit /confirm gate; agents may only propose"}
    try:
        res = engine.dconfig.confirm(int(body.get("id")), source=src_id)
        engine._refresh_effective_config()   # file defaults + overrides -> reaches every engine provider
        return {"ok": True, **res}
    except (ConfigError, TypeError, ValueError) as e:
        return {"error": str(e)}

@app.post("/config/reject")
async def config_reject(body: dict):
    if (g := _dc_guard()):
        return g
    return {"ok": True, **engine.dconfig.reject(int(body.get("id")))}

@app.post("/research/nav")
async def research_set_nav(body: dict):
    """Record a SOURCED per-share NAV for a ballast name -> research_cache ``nav_adj_per_share``, the
    tier-2 mark ``_ballast_fv`` anchors on INSTEAD of the accounting book that understates
    holdco/royalty fair value (the cause of e.g. GMX's '-59% upside' artifact). Grounded-or-silent:
    a source_url is REQUIRED. Point-in-time (restatements keep history). Effective next eval cycle."""
    if (g := _dc_guard()):
        return g
    tk = str(body.get("ticker", "")).strip().upper()
    src = str(body.get("source_url", "") or body.get("source", "")).strip()
    try:
        nav = float(body.get("nav_per_share"))
    except (TypeError, ValueError):
        return {"error": "nav_per_share must be a number"}
    if not tk:
        return {"error": "ticker required"}
    if nav <= 0:
        return {"error": "nav_per_share must be > 0"}
    if not src:
        return {"error": "a source_url is required (grounded-or-silent — a NAV needs a source)"}
    as_of = str(body.get("as_of") or "").strip() or time.strftime("%Y-%m-%d")
    conf = str(body.get("confidence", "med"))
    try:
        if getattr(engine, "_rc", None) is None:
            import research_cache as _rcmod
            engine._rc = _rcmod.ResearchCache()
        entry = engine._rc.set(tk, "nav_adj_per_share", nav, source=src, as_of=as_of,
                               confidence=conf, note="cockpit set_nav (sourced ballast NAV anchor)")
        return {"ok": True, "ticker": tk, "nav_adj_per_share": nav, "as_of": as_of,
                "restated": bool(entry.get("restated")),
                "message": f"{tk} NAV anchor set to {nav} (as of {as_of}); _ballast_fv uses it next cycle."}
    except Exception as e:
        return {"error": str(e)}

@app.get("/config/scenarios")
async def config_scenarios():
    return _dc_guard() or {"scenarios": engine.dconfig.list_scenarios()}

@app.post("/config/scenario")
async def config_scenario(body: dict):
    """Save a named what-if scenario {name, overrides}. Loadable via /whatif <TICKER> <name>."""
    if (g := _dc_guard()):
        return g
    try:
        return {"ok": True, **engine.dconfig.save_scenario(body.get("name"), body.get("overrides"),
                                                           source=body.get("source", "cockpit"))}
    except ConfigError as e:
        return {"error": str(e)}

# ---- Research dossiers / decision memos (read-only; backs the cockpit Dossier tab) ----
@app.get("/decisions")
async def list_decisions(limit: int = 50):
    """Index of research dossiers in data/decisions/*.md (newest first). Agents write these via
    the /dossier skill; the cockpit renders them. Read-only."""
    return engine.list_decisions(limit)

@app.get("/decisions/item")
async def read_decision(name: str = ""):
    """Full markdown body of one dossier by file name (path-traversal-guarded). Read-only."""
    return engine.read_decision(name)

@app.post("/decisions/delete")
async def delete_decision(payload: dict):
    """Delete one dossier by file name (path-traversal-guarded)."""
    return engine.delete_decision((payload or {}).get("name", ""))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    await websocket.send_text(json.dumps(engine.terminal_state))
    try:
        while True: 
            await websocket.receive_text()
    except:
        if websocket in active_websockets: 
            active_websockets.remove(websocket)
