"""CommodityEx FastAPI layer — the HTTP/WebSocket surface over the engine orchestrator.

Mechanically moved out of engine.py (Arch 2 split): the `engine = CommodityExMonitor()`
singleton, the websocket broadcaster, the lifespan hook and every route are verbatim. The
launch entrypoint is unchanged — `python engine.py` imports `app` from here in its
`__main__` block and runs uvicorn on 127.0.0.1:8000 exactly as before; `uvicorn engine_api:app`
(or the lazy `engine.app` re-export) reaches the same single app instance.
"""

import asyncio
import json
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

@app.post("/pipeline/event")
async def pipeline_event_post(payload: dict):
    return engine.record_pipeline_event(payload or {})

@app.get("/pipeline")
async def pipeline_get():
    return engine.published_state.get("pipeline", {})

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

@app.post("/config/param")
async def config_set(body: dict):
    """Set an override directly — HUMAN-ONLY (audit A2.2: the proposal gate is a hard line, not
    etiquette). Only the cockpit/human channel may write directly; any agent source is refused and
    told to route through /config/propose -> the /confirm gate. {key, value} -> hot-applies."""
    if (g := _dc_guard()):
        return g
    src_id = str(body.get("source", "cockpit"))
    if not (src_id == "cockpit" or src_id.startswith("human")):
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
    """Human confirms a pending change -> applied + hot-reloaded."""
    if (g := _dc_guard()):
        return g
    try:
        res = engine.dconfig.confirm(int(body.get("id")), source=body.get("source", "cockpit"))
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
