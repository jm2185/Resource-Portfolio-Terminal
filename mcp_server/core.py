"""
CommodityEx Quant Monitor v5.3 — MCP server core logic.

This module holds the *substance* of every MCP tool / resource as plain,
dependency-light Python functions. The transport layer (``server.py``) is a thin
FastMCP wrapper that registers these. Keeping the logic here means:

  * The same provider function backs both an MCP *tool* (works in every client)
    and an MCP *resource* (for resource-aware clients) — no duplication.
  * The logic is unit-testable without the MCP SDK installed (see ``selftest.py``).

Design rules (Phase 1 — minimal, local-first, subscription-compatible):
  * **Local-first.** No external services and no API keys are needed for the MCP
    layer itself — only the Python stdlib (plus the repo's own modules for the
    glossary). Optional FRED_API_KEY / MARKETAUX_API_KEY only improve the *data*
    ingestion, never the MCP layer.
  * **Safe by default.** Reads are unrestricted within the repo; writes, commits
    and process launches are guarded (repo-scoped paths, a sensitive-file
    deny-list, and an explicit ``confirm=True`` on anything destructive). Set
    ``CEX_MCP_READONLY=1`` to disable all mutating tools entirely.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# stdio transport reserves stdout for the protocol — diagnostics go to stderr via logging
# (configured by server.py); best-effort hooks LOG failures instead of swallowing them.
log = logging.getLogger("cex-mcp.core")

# --------------------------------------------------------------------------- #
# Repo location & safety configuration
# --------------------------------------------------------------------------- #

# Repo root = parent of this mcp_server/ directory, unless overridden. server.py
# resolves its own location, so the working directory of the client is irrelevant.
REPO_ROOT = Path(os.environ.get("CEX_REPO_ROOT", Path(__file__).resolve().parent.parent)).resolve()

# Global kill-switch: when set, every mutating tool refuses to run.
READONLY = os.environ.get("CEX_MCP_READONLY", "").strip() in ("1", "true", "yes", "on")

ENGINE_HOST = os.environ.get("CEX_ENGINE_HOST", "127.0.0.1")
ENGINE_PORT = int(os.environ.get("CEX_ENGINE_PORT", "8000"))
DASHBOARD_PORT = int(os.environ.get("CEX_DASHBOARD_PORT", "8501"))
ENGINE_URL = f"http://{ENGINE_HOST}:{ENGINE_PORT}"
_AGENT_NAME = os.environ.get("CEX_AGENT_NAME", "agent")   # who is leaving cockpit annotations

CONFIG_PATH = REPO_ROOT / "v5_config.json"
INGESTION_CACHE = REPO_ROOT / "data" / "ingestion_cache.json"
MEMORY_PATH = REPO_ROOT / "data" / "living_memory.jsonl"
LEDGER_PATH = REPO_ROOT / "data" / "valuation_ledger.jsonl"
PRICE_HISTORY_PATH = REPO_ROOT / "data" / "price_history.json"
UNIVERSE_PATH = REPO_ROOT / "data" / "candidate_universe.json"
CALENDAR_PATH = REPO_ROOT / "data" / "catalyst_calendar.jsonl"

# Runtime artifacts (git-ignored). Background-service logs/pids and edit backups.
LOG_DIR = REPO_ROOT / ".mcp_logs"
BACKUP_DIR = REPO_ROOT / ".mcp_backups"

# Directories never walked by list_files (noise / large / generated).
IGNORE_DIRS = {
    ".git", "__pycache__", ".dart_tool", "build", "Pods", ".gradle",
    "node_modules", "venv", ".venv", "env", ".mcp_logs", ".mcp_backups",
    ".idea", ".vscode",
}

# Files that must never be read through the MCP layer (real secrets only).
SENSITIVE_READ = ("FRED_API_KEY", "MARKETAUX_API_KEY")

# Files that must never be written/committed through the MCP layer. Config and
# generated caches are protected from accidental overwrite; secrets are absolute.
SENSITIVE_WRITE_NAMES = (
    "FRED_API_KEY", "MARKETAUX_API_KEY",
    "v5_config.json", "v4_config.json", "v3_config.json",
)
SENSITIVE_WRITE_DIRS = (".git", ".cache", ".mcp_logs", ".mcp_backups")


class SafetyError(Exception):
    """Raised when a request would touch something out-of-bounds."""


# --------------------------------------------------------------------------- #
# Path safety
# --------------------------------------------------------------------------- #

def _resolve_in_repo(rel: str) -> Path:
    """Resolve *rel* against the repo root and guarantee it stays inside it.

    Resolving first (then checking containment) defeats both ``..`` traversal and
    symlink escapes.
    """
    if rel is None:
        raise SafetyError("path is required")
    candidate = (REPO_ROOT / rel).resolve()
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError:
        raise SafetyError(f"path escapes the repository: {rel!r}")
    return candidate


def _guard_read(path: Path) -> None:
    if path.name in SENSITIVE_READ or path.suffix == ".env":
        raise SafetyError(f"refusing to read sensitive file: {path.name}")


def _guard_write(path: Path) -> None:
    if READONLY:
        raise SafetyError("server is in read-only mode (CEX_MCP_READONLY=1)")
    rel = path.relative_to(REPO_ROOT)
    if path.name in SENSITIVE_WRITE_NAMES or path.suffix == ".env":
        raise SafetyError(f"refusing to modify protected file: {path.name}")
    if rel.parts and rel.parts[0] in SENSITIVE_WRITE_DIRS:
        raise SafetyError(f"refusing to modify protected location: {rel.parts[0]}/")


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], timeout: int = 300) -> dict:
    """Run a command to completion in the repo root, capturing output."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout
        )
        out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        return {"returncode": proc.returncode, "output": out.strip()}
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return {"returncode": -1, "output": f"[timed out after {timeout}s]\n{partial}".strip()}
    except FileNotFoundError as exc:
        return {"returncode": 127, "output": f"command not found: {exc}"}


def _tail(text: str, max_lines: int = 60, max_chars: int = 8000) -> str:
    """Keep output payloads small for the model's context window."""
    if len(text) > max_chars:
        text = text[-max_chars:]
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = ["…(earlier output trimmed)…", *lines[-max_lines:]]
    return "\n".join(lines)


def _http_get_json(url: str, timeout: float = 2.0):
    """GET JSON with the stdlib (no `requests` dependency for the MCP layer)."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (localhost)
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(path: str, payload: dict, timeout: float = 5.0):
    """POST JSON to an engine endpoint and parse the reply (stdlib only)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{ENGINE_URL}{path}", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
        return json.loads(resp.read().decode("utf-8"))


def _engine_down() -> dict:
    return {"engine_running": False,
            "hint": "Start the engine with run_engine(action='start'), then retry.",
            "endpoint": ENGINE_URL}


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# 1. File operations
# --------------------------------------------------------------------------- #

def list_files(subdir: str = ".", pattern: str = "*", recursive: bool = False,
               limit: int = 400) -> dict:
    """List repo files under *subdir* (read-only, repo-scoped)."""
    base = _resolve_in_repo(subdir)
    if not base.exists():
        raise SafetyError(f"no such directory: {subdir}")
    if base.is_file():
        return {"base": subdir, "files": [str(base.relative_to(REPO_ROOT))], "count": 1}

    matches: list[str] = []
    truncated = False
    if recursive:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for name in sorted(files):
                p = Path(root) / name
                if p.match(pattern):
                    matches.append(str(p.relative_to(REPO_ROOT)))
                    if len(matches) >= limit:
                        truncated = True
                        break
            if truncated:
                break
    else:
        for p in sorted(base.glob(pattern)):
            if p.is_dir() and p.name in IGNORE_DIRS:
                continue
            tag = "/" if p.is_dir() else ""
            matches.append(str(p.relative_to(REPO_ROOT)) + tag)
            if len(matches) >= limit:
                truncated = True
                break

    return {"base": subdir, "pattern": pattern, "recursive": recursive,
            "count": len(matches), "truncated": truncated, "files": matches}


def read_file(path: str, max_bytes: int = 100_000) -> dict:
    """Read a UTF-8 text file from inside the repo (read-only)."""
    p = _resolve_in_repo(path)
    _guard_read(p)
    if not p.exists() or not p.is_file():
        raise SafetyError(f"no such file: {path}")
    raw = p.read_bytes()
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", "replace")
    return {"path": path, "bytes": len(raw), "truncated": truncated,
            "lines": text.count("\n") + 1, "content": text}


def edit_file(path: str, old_string: str, new_string: str, confirm: bool = False) -> dict:
    """Exact-string replacement in a repo file (destructive — needs ``confirm``).

    To **create** a new file, pass ``old_string=""`` for a path that does not yet
    exist; ``new_string`` becomes the full contents. Otherwise ``old_string`` must
    occur exactly once. A timestamped backup of any pre-existing file is written
    to ``.mcp_backups/`` before the change.
    """
    p = _resolve_in_repo(path)
    _guard_write(p)
    if not confirm:
        return {"status": "needs_confirmation",
                "message": "Destructive edit. Re-call with confirm=true to apply.",
                "path": path}

    creating = not p.exists()
    if creating:
        if old_string:
            raise SafetyError("file does not exist; pass old_string='' to create it")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_string, encoding="utf-8")
        return {"status": "created", "path": path, "bytes": len(new_string.encode())}

    original = p.read_text(encoding="utf-8", errors="replace")
    occurrences = original.count(old_string)
    if occurrences == 0:
        raise SafetyError("old_string not found in file")
    if occurrences > 1:
        raise SafetyError(f"old_string is not unique ({occurrences} matches); add context")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"{p.name}.{stamp}.bak"
    backup.write_text(original, encoding="utf-8")

    p.write_text(original.replace(old_string, new_string, 1), encoding="utf-8")
    return {"status": "edited", "path": path,
            "backup": str(backup.relative_to(REPO_ROOT))}


# --------------------------------------------------------------------------- #
# 2. Run commands (tests / ingestion / engine / dashboard)
# --------------------------------------------------------------------------- #

def _have_pytest() -> bool:
    return _run([sys.executable, "-m", "pytest", "--version"], timeout=30)["returncode"] == 0


def run_tests(target: str | None = None, timeout: int = 300) -> dict:
    """Run the Python test suite (pytest if available, else unittest).

    *target* may be a single ``test_*.py`` file (or pytest node id) to narrow the
    run; default executes the whole ``test_*.py`` suite.
    """
    if _have_pytest():
        cmd = [sys.executable, "-m", "pytest", "-q"]
        cmd += [target] if target else []
        runner = "pytest"
    else:
        cmd = [sys.executable, "-m", "unittest"]
        cmd += ["-v", target.replace(".py", "").replace("/", ".")] if target else [
            "discover", "-s", ".", "-p", "test_*.py"]
        runner = "unittest"
    res = _run(cmd, timeout=timeout)
    return {"runner": runner, "command": " ".join(cmd),
            "passed": res["returncode"] == 0, "returncode": res["returncode"],
            "output": _tail(res["output"], max_lines=80)}


def run_ingestion(force: bool = False, tickers: str | None = None,
                  providers: str | None = None, catalysts: bool = False,
                  sentiment: bool = False, verbose: bool = False,
                  timeout: int = 600) -> dict:
    """Refresh the open-source data cache (``ingestion_pipeline.py``).

    This is the home of the ``--force`` flag (bypasses TTL and refetches). Writes
    ``data/ingestion_cache.json`` which the engine overlays on its live payloads.
    """
    if READONLY and force:
        raise SafetyError("server is in read-only mode (CEX_MCP_READONLY=1)")
    cmd = [sys.executable, "ingestion_pipeline.py"]
    if force:
        cmd.append("--force")
    if tickers:
        cmd += ["--tickers", tickers]
    if providers:
        cmd += ["--providers", providers]
    if catalysts:
        cmd.append("--catalysts")
    if sentiment:
        cmd.append("--enable-sentiment")
    if verbose:
        cmd.append("--verbose")
    res = _run(cmd, timeout=timeout)
    return {"command": " ".join(cmd), "returncode": res["returncode"],
            "ok": res["returncode"] == 0, "output": _tail(res["output"], max_lines=80)}


# ---- Background services (engine API + Streamlit dashboard) ---------------- #

def _service_spec(name: str) -> dict:
    if name == "engine":
        return {
            "cmd": [sys.executable, "engine.py"],
            "log": LOG_DIR / "engine.log",
            "pid": LOG_DIR / "engine.pid",
            "ready": lambda: _engine_alive(),
            "url": f"{ENGINE_URL}/state",
            "port": ENGINE_PORT,
        }
    if name == "dashboard":
        return {
            "cmd": [sys.executable, "-m", "streamlit", "run", "dashboard.py",
                    "--server.headless=true", f"--server.port={DASHBOARD_PORT}"],
            "log": LOG_DIR / "dashboard.log",
            "pid": LOG_DIR / "dashboard.pid",
            "ready": lambda: _port_open(ENGINE_HOST, DASHBOARD_PORT),
            "url": f"http://{ENGINE_HOST}:{DASHBOARD_PORT}",
            "port": DASHBOARD_PORT,
        }
    raise SafetyError(f"unknown service: {name}")


def _engine_alive() -> bool:
    try:
        _http_get_json(f"{ENGINE_URL}/state", timeout=1.0)
        return True
    except Exception:
        return False


def _read_pid(spec: dict) -> int | None:
    try:
        return int(spec["pid"].read_text().strip())
    except Exception:
        return None


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _start_service(name: str, wait: float = 12.0) -> dict:
    spec = _service_spec(name)
    if READONLY:
        raise SafetyError("server is in read-only mode (CEX_MCP_READONLY=1)")
    if spec["ready"]() or _pid_running(_read_pid(spec)):
        return {"service": name, "status": "already_running", "url": spec["url"]}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = open(spec["log"], "w")  # noqa: SIM115 (handed to the child process)
    proc = subprocess.Popen(
        spec["cmd"], cwd=str(REPO_ROOT), stdout=log_fh, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    spec["pid"].write_text(str(proc.pid))

    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None:
            break  # process exited early — surface the log
        if spec["ready"]():
            return {"service": name, "status": "started", "pid": proc.pid,
                    "url": spec["url"], "log": str(spec["log"].relative_to(REPO_ROOT))}
        time.sleep(0.4)

    log_tail = _tail(spec["log"].read_text(errors="replace"), max_lines=25) if spec["log"].exists() else ""
    status = "exited" if proc.poll() is not None else "starting"
    return {"service": name, "status": status, "pid": proc.pid,
            "url": spec["url"], "log": str(spec["log"].relative_to(REPO_ROOT)),
            "note": "not confirmed ready within timeout — check the log",
            "log_tail": log_tail}


def _stop_service(name: str) -> dict:
    spec = _service_spec(name)
    if READONLY:
        raise SafetyError("server is in read-only mode (CEX_MCP_READONLY=1)")
    pid = _read_pid(spec)
    if not _pid_running(pid):
        return {"service": name, "status": "not_running"}
    import signal
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(10):
        if not _pid_running(pid):
            break
        time.sleep(0.3)
    if _pid_running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        spec["pid"].unlink()
    except OSError:
        pass
    return {"service": name, "status": "stopped", "pid": pid}


def _service_status(name: str) -> dict:
    spec = _service_spec(name)
    pid = _read_pid(spec)
    return {"service": name, "url": spec["url"], "port": spec["port"],
            "pid": pid, "process_alive": _pid_running(pid), "ready": spec["ready"]()}


def run_engine(action: str = "start", force_refresh: bool = False) -> dict:
    """Manage the FastAPI valuation engine (uvicorn on :8000, serves ``/state``).

    action: ``start`` | ``stop`` | ``status`` | ``restart``.
    force_refresh: run ``ingestion --force`` first so the engine boots on fresh data
    (the ``--force`` semantics the engine itself does not expose).
    """
    action = (action or "start").lower()
    pre = None
    if action in ("start", "restart") and force_refresh:
        pre = run_ingestion(force=True)
    if action == "status":
        return _service_status("engine")
    if action == "stop":
        return _stop_service("engine")
    if action == "restart":
        _stop_service("engine")
    res = _start_service("engine")
    if pre is not None:
        res["ingestion_force_refresh"] = {"ok": pre["ok"], "returncode": pre["returncode"]}
    return res


def run_dashboard(action: str = "start") -> dict:
    """Manage the Streamlit dashboard (``streamlit run dashboard.py`` on :8501).

    The dashboard reads the engine's ``/state`` feed — start ``run_engine`` first for
    live Conviction Mode. action: ``start`` | ``stop`` | ``status`` | ``restart``.
    """
    action = (action or "start").lower()
    if action == "status":
        return _service_status("dashboard")
    if action == "stop":
        return _stop_service("dashboard")
    if action == "restart":
        _stop_service("dashboard")
    res = _start_service("dashboard")
    if not _engine_alive():
        res["hint"] = "Engine API (:8000) is not up — dashboard Conviction Mode will be empty until run_engine."
    return res


def run_valuation_whatif(ticker: str, overrides: str = "") -> dict:
    """Scenario what-if: revalue a holding under macro/peer/regime overrides via the engine's
    shared /action/whatif route (Iteration 2 — same implementation a Flutter button would call).

    overrides: "silver=+5 ry=-0.5 peer=+20%" — knobs silver/ag, gold, ry, vol, peer, mri, dxy;
    values absolute (79.8), delta (+5/-0.5) or percent (+20%). Returns base vs scenario intrinsic
    + upside and the deltas. Needs the engine running.
    """
    # ticker may be empty — the engine falls back to the GUI's focused ticker (ui_state).
    try:
        return _http_post_json("/action/whatif", {"ticker": ticker or "", "overrides": overrides})
    except Exception:
        return _engine_down()


def get_ui_context() -> dict:
    """What the GUI (Flutter) is currently showing — focused ticker / view / scenario / visible
    tickers / selected what-if — so an agent can ground analysis in the user's on-screen context
    (read-side of the cockpit↔Flutter merge). focused_ticker=None when no frontend has reported."""
    try:
        ctx = _http_get_json(f"{ENGINE_URL}/ui/state", timeout=2.0)
    except Exception:
        return _engine_down()
    if not ctx or not ctx.get("focused_ticker"):
        return {"focused_ticker": None,
                "note": "no frontend has reported a focus yet", **(ctx or {})}
    return ctx


def send_ui_command(action: str, ticker: str = "", view: str = "", scenario: str = "") -> dict:
    """Steer the GUI (write-side). action: focus | view | scenario | highlight | alert. Pass a
    ticker/view/scenario as relevant. The Flutter app picks it up over /ws. Use only to follow the
    user's request, not unprompted."""
    if not action:
        raise SafetyError("action is required (focus | view | scenario | highlight | alert)")
    args = {k: v for k, v in (("ticker", ticker), ("view", view), ("scenario", scenario)) if v}
    try:
        return _http_post_json("/ui/command", {"action": action, "args": args})
    except Exception:
        return _engine_down()


def _ui_cmd(action: str, args: dict) -> dict:
    try:
        return _http_post_json("/ui/command", {"action": action, "args": args})
    except Exception:
        return _engine_down()


def pin_insight(ticker: str, note: str, badge: str = "✦", level: str = "info") -> dict:
    """Leave a persistent visual badge + note on a ticker in the cockpit (Book + Watchlist).
    level: info | good | warn | risk (drives colour). Use after a real finding, grounded in tools."""
    if not ticker or not note:
        return {"error": "ticker and note are required"}
    return _ui_cmd("pin_insight", {"ticker": ticker, "note": note, "badge": badge, "level": level,
                                   "agent": _AGENT_NAME})


def highlight_ticker(ticker: str, reason: str, level: str = "info", ttl: int = 90) -> dict:
    """Transient highlight (auto-expires after ttl seconds) drawing the eye to a name with a reason."""
    if not ticker:
        return {"error": "ticker is required"}
    return _ui_cmd("highlight", {"ticker": ticker, "reason": reason, "level": level, "ttl": ttl,
                                 "agent": _AGENT_NAME})


def clear_insight(ticker: str = "") -> dict:
    """Remove agent badges/notes for a ticker (or all if ticker is empty)."""
    return _ui_cmd("clear_insight", {"ticker": ticker})


def switch_tab(tab: str) -> dict:
    """Switch the cockpit's main view. tab: book | whatif | regime | dossier."""
    return _ui_cmd("switch_tab", {"view": tab})


def get_fundamentals(ticker: str) -> dict:
    """FMP fundamentals snapshot for a ticker (price, market cap, beta, 52-wk range, volume, sector).
    Engine-cached + daily-budget-capped on the free tier — repeats are free. Note: FMP free tier has
    NO news/catalysts/calendar (paid) — use WebSearch/WebFetch straight-to-source for those."""
    if not ticker:
        return {"error": "ticker required"}
    try:
        return _http_get_json(f"{ENGINE_URL}/fmp/fundamentals?ticker={ticker}", timeout=10.0)
    except Exception:
        return _engine_down()


def get_treasury_curve() -> dict:
    """Latest US Treasury curve (1mo…30yr) via FMP, engine-cached 6h. One call covers every tenor."""
    try:
        return _http_get_json(f"{ENGINE_URL}/fmp/treasury", timeout=10.0)
    except Exception:
        return _engine_down()


def pipeline_event(stage: str = "", message: str = "", status: str = "running",
                   ticker: str = "", verdict: str = "", result: str = "", theme: str = "") -> dict:
    """Post a research-pipeline status update so the cockpit's PIPELINE panel shows live progress
    while the user keeps working. Call at each stage transition (scout/synthesis/verifier/done)."""
    body = {k: v for k, v in (("stage", stage), ("message", message), ("status", status),
                              ("ticker", ticker), ("verdict", verdict), ("result", result),
                              ("theme", theme)) if v}
    try:
        return _http_post_json("/pipeline/event", body)
    except Exception:
        return _engine_down()


def get_pipeline_status() -> dict:
    """Current background-pipeline status (theme, stage, per-name verdicts, recent events)."""
    try:
        return _http_get_json(f"{ENGINE_URL}/pipeline", timeout=3.0)
    except Exception:
        return _engine_down()


def apply_scenario(scenario: str = "", overrides: str = "", ticker: str = "", to_book: bool = False) -> dict:
    """Load a what-if into the Live What-If tab and run it visibly. Pass a saved `scenario` name or
    raw `overrides` (e.g. 'silver=+5 ry=-0.5'); optional `ticker` focuses the name first."""
    return _ui_cmd("apply_scenario", {"scenario": scenario, "overrides": overrides,
                                      "ticker": ticker, "to_book": bool(to_book)})


# ---- Dynamic configuration (thin callers into the engine's /config/* routes) ----

def list_params() -> dict:
    """List editable tunables: effective value, default, range, and whether overridden."""
    try:
        return _http_get_json(f"{ENGINE_URL}/config/params", timeout=3.0)
    except Exception:
        return _engine_down()


def set_param(key: str, value: float, confirm: bool = False) -> dict:
    """Set a tunable — ALWAYS routed through the proposal queue (audit A2.2: the human gate is a
    hard line, not etiquette). The MCP channel is the agent channel, so this tool can never write
    config directly — even with confirm=true it files a PROPOSAL the operator applies via
    /confirm; the engine's /config/param endpoint independently refuses non-cockpit sources
    (defense in depth). ``confirm=true`` merely marks the proposal as operator-initiated intent."""
    reason = (f"set_param request ({'operator-initiated' if confirm else 'unconfirmed'}) — "
              f"auto-routed through the proposal queue; apply with /confirm")
    try:
        res = _http_post_json("/config/propose",
                              {"key": key, "value": value, "reason": reason,
                               "proposed_by": "mcp:set_param"})
        return {"status": "proposed", **(res if isinstance(res, dict) else {}),
                "message": (f"{key}={value} filed as a PROPOSAL (direct writes are human-only; "
                            f"audit A2.2). Review with list_pending_changes, apply via /confirm.")}
    except Exception:
        return _engine_down()


def set_barbell_weights(weights: dict, reason: str = "") -> dict:
    """Rebalance the BOOK SLEEVE weights (``barbell_weights``) — a validated vector over the same
    human-gated overlay as set_param. The overlay enforces: known book tickers only, each in [0,1],
    sums to 1.0, and AGA.V within the 60% spear ceiling. Files a PROPOSAL (direct writes are
    human-only); the operator applies via /confirm, then it hot-reloads.
    Example (after cutting URC): {"AGA.V": 0.60, "GROY": 0.24, "GMX.TO": 0.16}."""
    if not isinstance(weights, dict) or not weights:
        return {"error": "weights must be a non-empty {ticker: weight} map"}
    try:
        res = _http_post_json("/config/propose",
                              {"key": "barbell_weights", "value": weights,
                               "reason": reason or "rebalance book sleeve weights",
                               "proposed_by": "mcp:set_barbell_weights"})
        return {"status": "proposed", **(res if isinstance(res, dict) else {}),
                "message": ("book weights filed as a PROPOSAL (sum-to-1 + 60% AGA ceiling validated) "
                            "— review with list_pending_changes, apply via /confirm.")}
    except Exception:
        return _engine_down()


def cut_holding(ticker: str, reason: str = "") -> dict:
    """Cut a book holding to 0% and redistribute its weight across the survivors pro-rata (AGA.V
    capped at the 60% spear ceiling, so the weight flows to the ballast). Files a PROPOSAL for the
    operator's /confirm — the cockpit-native way to reflect a rotation without editing config."""
    try:
        res = _http_post_json("/config/cut_holding",
                              {"ticker": ticker, "reason": reason or f"cut {ticker}",
                               "proposed_by": "mcp:cut_holding"})
        return {"status": "proposed", **(res if isinstance(res, dict) else {}),
                "message": (f"{ticker} cut + redistribute filed as a PROPOSAL — review with "
                            f"list_pending_changes, apply via /confirm.")}
    except Exception:
        return _engine_down()


def set_nav(ticker: str, nav_per_share: float, source_url: str,
            as_of: str = "", confidence: str = "med") -> dict:
    """Record a SOURCED per-share NAV for a ballast holding (GMX.TO / GROY / URC.TO) so its fair
    value anchors on a real NAV instead of the understated accounting book — the cause of the
    holdco/royalty 'negative upside' / 'price below floor' artifacts (e.g. GMX's -59%). Writes the
    tier-2 ``nav_adj_per_share`` mark that ``_ballast_fv`` prefers; effective next eval cycle.
    GROUNDED-OR-SILENT: a ``source_url`` (issuer NAV disclosure / analyst NAV note) is REQUIRED."""
    if not source_url:
        return {"error": "a source_url is required (grounded-or-silent — a NAV needs a source)"}
    try:
        nav = float(nav_per_share)
    except (TypeError, ValueError):
        return {"error": "nav_per_share must be a number"}
    if nav <= 0:
        return {"error": "nav_per_share must be > 0"}
    try:
        res = _http_post_json("/research/nav",
                              {"ticker": ticker, "nav_per_share": nav, "source_url": source_url,
                               "as_of": as_of, "confidence": confidence})
        return res if isinstance(res, dict) else {"ok": True}
    except Exception:
        return _engine_down()


def propose_param_change(key: str, value: float, reason: str) -> dict:
    """Propose a tunable change WITH reasoning -> pending queue; a human confirms before it applies."""
    if not reason:
        raise SafetyError("a reason is required to propose a change")
    try:
        return _http_post_json("/config/propose",
                               {"key": key, "value": value, "reason": reason, "proposed_by": "agent"})
    except Exception:
        return _engine_down()


def list_pending_changes() -> dict:
    """List proposed-but-unconfirmed config changes (key, value, reason, who)."""
    try:
        return _http_get_json(f"{ENGINE_URL}/config/pending", timeout=3.0)
    except Exception:
        return _engine_down()


def confirm_param_change(change_id: int) -> dict:
    """Apply a pending proposed change by id (human confirmation step)."""
    try:
        return _http_post_json("/config/confirm", {"id": change_id})
    except Exception:
        return _engine_down()


def save_scenario(name: str, overrides: str) -> dict:
    """Save a named what-if scenario. overrides like 'silver=+5 ry=-0.5 peer=+20%'.
    Load it later via run_valuation_whatif(ticker, name)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from valuation_actions import parse_overrides
        ov = parse_overrides(overrides)
    except Exception:
        ov = {}
    if not ov:
        raise SafetyError("overrides like 'silver=+5 ry=-0.5' are required")
    try:
        return _http_post_json("/config/scenario", {"name": name, "overrides": ov})
    except Exception:
        return _engine_down()


def list_scenarios() -> dict:
    """List saved what-if scenarios and their override knobs."""
    try:
        return _http_get_json(f"{ENGINE_URL}/config/scenarios", timeout=3.0)
    except Exception:
        return _engine_down()


# --------------------------------------------------------------------------- #
# 3. Git helpers
# --------------------------------------------------------------------------- #

def git_status() -> dict:
    """Branch + short working-tree status (read-only)."""
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)["output"]
    porcelain = _run(["git", "status", "--porcelain", "--branch"], timeout=30)["output"]
    return {"branch": branch, "status": porcelain or "(clean)"}


def git_diff(path: str | None = None, staged: bool = False, max_chars: int = 12000) -> dict:
    """Unified diff of the working tree or index (read-only)."""
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--cached")
    if path:
        cmd += ["--", str(_resolve_in_repo(path).relative_to(REPO_ROOT))]
    res = _run(cmd, timeout=60)
    diff = res["output"]
    return {"command": " ".join(cmd), "truncated": len(diff) > max_chars,
            "diff": diff[:max_chars] if diff else "(no changes)"}


def git_commit(message: str, add_all: bool = False, paths: str | None = None,
               confirm: bool = False) -> dict:
    """Stage and commit (destructive — needs ``confirm``). Never pushes.

    Aborts if any staged path is a protected/sensitive file. Stage either an
    explicit comma-separated ``paths`` list or everything with ``add_all=True``.
    """
    if READONLY:
        raise SafetyError("server is in read-only mode (CEX_MCP_READONLY=1)")
    if not message or not message.strip():
        raise SafetyError("a non-empty commit message is required")
    if not confirm:
        return {"status": "needs_confirmation",
                "message": "Re-call with confirm=true to create the commit."}

    if paths:
        for rel in [s.strip() for s in paths.split(",") if s.strip()]:
            _run(["git", "add", "--", str(_resolve_in_repo(rel).relative_to(REPO_ROOT))], timeout=30)
    elif add_all:
        _run(["git", "add", "-A"], timeout=30)

    staged = _run(["git", "diff", "--cached", "--name-only"], timeout=30)["output"].splitlines()
    if not staged:
        return {"status": "nothing_staged",
                "message": "No staged changes. Pass add_all=true or a paths list."}
    blocked = [s for s in staged
               if Path(s).name in SENSITIVE_WRITE_NAMES or s.endswith(".env")
               or (Path(s).parts and Path(s).parts[0] in SENSITIVE_WRITE_DIRS)]
    if blocked:
        raise SafetyError(f"refusing to commit protected files: {blocked}")

    res = _run(["git", "commit", "-m", message], timeout=60)
    if res["returncode"] != 0:
        return {"status": "failed", "output": _tail(res["output"])}
    sha = _run(["git", "rev-parse", "--short", "HEAD"], timeout=30)["output"]
    return {"status": "committed", "commit": sha, "files": staged,
            "note": "Not pushed. Push manually when ready."}


# --------------------------------------------------------------------------- #
# 4. Project-state providers (backing both tools and resources)
# --------------------------------------------------------------------------- #

def _project_conviction_basket(b: dict) -> dict:
    """Project one engine basket into the agent-facing rating (the Dialectic Council's fact sheet).

    FORGE keystone (roadmap Idea 1 ①): the asymmetry the Bull/Bear actually argue over — ρ (payoff
    ratio), φ (floor coverage), upside/downside legs — plus the JSF gate reason, the confidence
    ribbon and the price ladder must reach the agents. The legacy projection flattened a basket to
    rating/band/directive and selected non-existent flat ``T/Q/V/conviction`` keys (they live under
    ``pillars.*.score``), so the pillar scores came back empty and ρ/φ/gate/ribbon/ladder never
    reached the debaters at all. This restores them — every number the Council reasons on, grounded.
    """
    pillars = b.get("pillars") or {}
    Tp = pillars.get("T") or {}
    Qp = pillars.get("Q") or {}
    Vp = pillars.get("V") or {}
    return {
        # identity + taxonomy (archetype = how it's valued; subarchetype = finer sort)
        "ticker": b.get("ticker"),
        "archetype": b.get("archetype"),
        "archetype_code": b.get("archetype_code"),
        "subarchetype": b.get("subarchetype"),
        "subarchetype_label": b.get("subarchetype_label"),
        "sector_tags": b.get("sector_tags"),
        # the single reconciled call + its tension
        "rating": b.get("rating"),
        "band": b.get("band"),
        "directive": b.get("directive"),
        # pillar SCORES (bugfix: previously empty — they live under pillars.*.score)
        "T": Tp.get("score"), "Q": Qp.get("score"), "V": Vp.get("score"),
        "conviction_lift": b.get("conviction_lift"),
        # ASYMMETRY — what the Bull/Bear debate; grounded, single numbers the engine refereed
        "asymmetry": {
            "rho": Vp.get("rho"), "floor_coverage": Vp.get("floor_coverage"),
            "payoff": Vp.get("payoff"), "support": Vp.get("support"),
            "upside_pct": Vp.get("upside_pct"), "downside_to_floor_pct": Vp.get("downside_to_floor_pct"),
            "mode": Vp.get("mode"),
        },
        # the macro tailwind decomposition (commodity-aware T): regime fit lives here
        "tailwind": {
            "score": Tp.get("score"), "commodity": Tp.get("commodity"),
            "commodity_regime": Tp.get("commodity_regime"),
            "commodity_contribution": Tp.get("commodity_contribution"),
            "alpha_contribution": Tp.get("alpha_contribution"),
        },
        # forensic gate (cap + reason) — the Bull must clear it; a thesis that ignores it is killed
        "gate": b.get("gate"),
        "confidence_ribbon": b.get("confidence_ribbon"),
        "ladder": b.get("ladder"),                  # floor / bear / base / bull / price
        # survival inputs the Forge Sentinel diffs against the thesis (M3): dilution velocity feeds
        # the dilution-sieve / financing-window read; runway_months the death-spiral flag
        "dilution_velocity": b.get("dilution_velocity"),
        "runway_months": b.get("runway_months"),
        # catalyst overlay (the V-move driver) if present
        "catalysts": b.get("catalysts"),
        "catalyst_signal": b.get("catalyst_signal"),
        "catalyst_count": b.get("catalyst_count"),
        # thesis-slot tagging: the barbell role this name fills; first screen for any rotation/replacement
        "thesis_slot": b.get("thesis_slot"),
        "thesis_slot_desc": b.get("thesis_slot_desc"),
    }


def get_conviction_ratings(with_calibration: bool = True) -> dict:
    """Live Conviction-Mode ratings from the running engine's ``/state`` feed. Unless
    ``with_calibration=False`` (the internal capture callers), folds in the calibration prior —
    per-archetype expectancy + base rate, the win-probability interval, the wealth PATH (+ path_warning),
    and the spear backstop — so every Council seat reading this inherits the loop's hard-won priors, not
    just the live asymmetry."""
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=2.0)
    except Exception:
        return {"engine_running": False,
                "hint": "Start the engine with run_engine(action='start'), then retry.",
                "endpoint": f"{ENGINE_URL}/state"}
    conv = state.get("conviction_mode") or {}
    baskets = [_project_conviction_basket(b) for b in conv.get("baskets", [])]
    out = {"engine_running": True, "status": state.get("status"),
           "mri": state.get("mri"), "context": conv.get("context", {}),
           "top_pick": conv.get("top_pick"), "baskets": baskets}
    if with_calibration:
        cp = _calibration_prior([b.get("archetype") for b in baskets])
        if cp:
            out["calibration"] = cp
    return out


def _living_memory():
    """Bind a LivingMemory to the repo store (importable from the MCP process)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import living_memory
    return living_memory.LivingMemory(path=str(MEMORY_PATH))


def memory_write(type: str, text: str = "", ticker: str = "", tags: str = "",
                 source: str = "agent", meta_json: str = "", refs: str = "") -> dict:
    """Append a typed entry to Living Memory — the cockpit's shared, append-only research record.

    Use this to persist anything worth carrying forward: a research ``note``, a reconciled
    ``council_verdict``, a ``scenario_prior``, a ``thesis``, a ``decision``, a ``regime_snapshot``,
    an ``outcome``, a ``catalyst``, or a ``pin``. Entries are immutable (a correction is a new entry
    that supersedes the old one), human-readable, and git-versioned — the family-vehicle audit trail.

    ``tags`` is comma-separated; ``meta_json`` an optional JSON object for type-specific structured
    payload (e.g. a decision's frozen legs + rho/phi). Captures the current engine regime context
    automatically when the engine is reachable, so the entry is recallable by regime later."""
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    tag_list = [t.strip() for t in str(tags).split(",") if t.strip()]
    ref_list = [r.strip() for r in str(refs).split(",") if r.strip()]
    meta = {}
    if meta_json:
        try:
            meta = json.loads(meta_json)
        except (ValueError, json.JSONDecodeError):
            return {"ok": False, "error": "meta_json is not valid JSON"}
    # best-effort live regime context so the entry is regime-recallable (never blocks the write)
    regime = None
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=1.5)
        conv_ctx = (state.get("conviction_mode") or {}).get("context", {})
        regime = {"mri": state.get("mri"),
                  "net_tilt": (state.get("macro_tape") or {}).get("net_tilt") or conv_ctx.get("regime"),
                  "posture": (state.get("posture") or {}).get("code")}
    except Exception:
        regime = None
    try:
        entry = mem.write(type, text=text, ticker=(ticker or None), tags=tag_list,
                          regime=regime, meta=meta, refs=ref_list, source=source)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    # CAPTURE HOOK — a reconciled council verdict deterministically freezes a gradeable decision (the
    # torque the calibration loop was missing). Best-effort: never blocks or fails the verdict write.
    if type == "council_verdict" and ticker:
        try:
            freeze_decision_if_new(ticker, str(meta.get("stance") or ""), source="council")
        except Exception as e:                  # best-effort, but NEVER silent — a quietly-dead
            log.warning("capture hook failed for %s (verdict written, decision NOT frozen): %s",
                        ticker, e)              # hook is how the flywheel stops without anyone noticing
    return {"ok": True, "id": entry["id"], "type": entry["type"], "ticker": entry["ticker"],
            "ts": entry["ts"]}


def memory_query(ticker: str = "", type: str = "", tag: str = "", contains: str = "",
                 regime_like: bool = False, limit: int = 20) -> dict:
    """Recall from Living Memory. Filters AND together (all optional). Set ``regime_like=true`` to
    keep only entries captured under a regime similar to the engine's CURRENT regime (this is how
    you ask "how did this name / these archetypes behave under a regime like today's?"). Returns
    newest-first; superseded entries are hidden."""
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}", "entries": []}
    rl = None
    if regime_like:
        try:
            state = _http_get_json(f"{ENGINE_URL}/state", timeout=1.5)
            conv_ctx = (state.get("conviction_mode") or {}).get("context", {})
            rl = {"mri": state.get("mri"),
                  "net_tilt": (state.get("macro_tape") or {}).get("net_tilt") or conv_ctx.get("regime"),
                  "posture": (state.get("posture") or {}).get("code")}
        except Exception:
            rl = None
    entries = mem.query(ticker=(ticker or None), type=(type or None), tag=(tag or None),
                        contains=(contains or None), regime_like=rl, limit=int(limit or 20))
    return {"ok": True, "count": len(entries), "stats": mem.stats(), "entries": entries}


def record_decision(ticker: str, verdict: str = "", source: str = "user") -> dict:
    """Freeze a structured DECISION record for a name into Living Memory — the legs (floor/bear/base/
    bull), ρ, φ, the JSF cap, archetype, and the price at decision — so it can later be graded against
    what actually happened (calibration). Reads the live engine rating for the frozen snapshot."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import calibration
    except Exception as e:
        return {"ok": False, "error": f"calibration unavailable: {e}"}
    ratings = get_conviction_ratings(with_calibration=False)
    if not ratings.get("engine_running"):
        return {"ok": False, "error": "engine not running — cannot freeze a decision"}
    basket = next((b for b in ratings.get("baskets", [])
                   if str(b.get("ticker", "")).upper() == ticker.upper()), None)
    if basket is None:
        return {"ok": False, "error": f"{ticker} not in the live book"}
    decision = calibration.decision_from_rating(basket, verdict=(verdict or None))
    # Validation flywheel (Phase 1.3.2 #3): join the decision to the FULL valuation state that
    # produced it — stamp a trigger="decision" ledger snapshot and carry its id in the decision
    # meta, so a graded decision is input-attributed, not just legs+ρ/φ. Best-effort: a ledger
    # problem never blocks the decision freeze.
    try:
        import valuation_ledger as vl
        try:
            inputs = vl.inputs_from_provenance(_research_cache().provenance(ticker))
        except Exception:
            inputs = {}
        snap = vl.snapshot_from_basket(basket, inputs=inputs,
                                       regime={"mri": ratings.get("mri")},
                                       engine_git_sha=vl.git_sha())
        rec = _valuation_ledger().record(snap, trigger="decision")
        decision["valuation_snapshot_id"] = rec["id"]
    except Exception as e:
        log.warning("decision frozen WITHOUT a ledger snapshot join: %s", e)
    text = (f"DECISION {decision.get('verdict','')} @ {decision.get('price')} "
            f"[floor {decision['legs'].get('floor')} · bull {decision['legs'].get('bull')}]")
    res = memory_write("decision", text=text, ticker=ticker, tags="decision",
                       source=source, meta_json=json.dumps(decision))
    return {**res, "decision": decision}


def record_outcome(ticker: str, realized_price: float, horizon_days: int = 90) -> dict:
    """Grade the latest frozen DECISION for a name against a realized price at a horizon, and write
    the scored OUTCOME to Living Memory (linked to the decision). Feeds the calibration scorecard:
    which leg was hit, realized vs projected-bull return, upside capture, whether the floor held."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import calibration
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"calibration/memory unavailable: {e}"}
    dec_entry = mem.latest(ticker=ticker, type="decision")
    if not dec_entry:
        return {"ok": False, "error": f"no frozen decision for {ticker} — record_decision first"}
    decision = dec_entry.get("meta", {}) or {}
    scored = calibration.score_outcome(decision, realized_price, horizon_days=horizon_days)
    if scored.get("status") != "scored":
        return {"ok": False, "error": scored.get("reason", "could not score"), "scored": scored}
    text = (f"OUTCOME {scored['result'].upper()} {scored['realized_return']*100:+.0f}% "
            f"@{horizon_days}d (leg {scored['leg_hit']})")
    res = memory_write("outcome", text=text, ticker=ticker, tags=f"outcome,{scored['result']}",
                       source="engine", meta_json=json.dumps(scored), refs=dec_entry.get("id", ""))
    return {**res, "scored": scored}


def record_conviction(ticker: str, confidence: float, basis: str = "", source: str = "user") -> dict:
    """H5 — log a point-in-time CONFIDENCE reading (0–100%, or a 0–1 fraction) on an open thesis: the
    desk's live conviction that THIS thesis pays, updated as evidence lands. Each reading is an
    immutable Living-Memory entry linked to the name's open decision, so the forecast TRAIL survives
    and gets Brier-scored at close (were you right AND was your confidence honest?). Refuses a reading
    with no open decision to anchor to — confidence floats only against a frozen bet."""
    tkr = (ticker or "").strip().upper()
    if not tkr:
        return {"ok": False, "error": "ticker required"}
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return {"ok": False, "error": "confidence must be a number (0–100% or a 0–1 fraction)"}
    if c > 1.0:
        c = c / 100.0                                      # accept 0–100 input, store 0–1
    if not (0.0 <= c <= 1.0):
        return {"ok": False, "error": f"confidence out of range: {confidence!r} (0–100% or 0–1)"}
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    dec = mem.latest(ticker=tkr, type="decision")
    if not dec:
        return {"ok": False, "refused": True,
                "error": f"no open decision for {tkr} — freeze one (record_decision) before pricing "
                         f"confidence; a forecast floats only against a frozen bet."}
    entry = mem.write("conviction", ticker=tkr,
                      text=f"CONVICTION {tkr} {c*100:.0f}%" + (f" — {basis}" if basis else ""),
                      tags=["conviction"], refs=[dec.get("id")],
                      meta={"confidence": round(c, 4), "basis": str(basis or ""),
                            "decision_id": dec.get("id")}, source=source)
    return {"ok": True, "id": entry["id"], "ticker": tkr, "confidence": round(c, 4),
            "decision_id": dec.get("id")}


def _conviction_trail(mem, decision_id: str) -> list:
    """The ordered (oldest→newest) confidence readings for one frozen decision — the forecast trail."""
    rows = [e for e in mem.query(type="conviction", limit=0, newest_first=False)
            if decision_id and decision_id in (e.get("refs") or [])]
    return rows


def conviction_book() -> dict:
    """H5 — the Conviction Book: every OPEN thesis with its live confidence (the latest reading), the
    length of its forecast trail, and how the confidence has moved; plus the book-level Brier
    calibration over CLOSED theses (was the desk's confidence honest, not just directionally right).
    Read-only. The trail itself is Brier-scored at close by the flywheel."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import calibration
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"calibration/memory unavailable: {e}"}
    open_decs = _open_decisions(mem)
    open_book = []
    for d in open_decs:
        trail = _conviction_trail(mem, d.get("id"))
        confs = [float((e.get("meta") or {}).get("confidence")) for e in trail
                 if (e.get("meta") or {}).get("confidence") is not None]
        latest = confs[-1] if confs else None
        move = (round(confs[-1] - confs[0], 4) if len(confs) >= 2 else None)
        open_book.append({
            "ticker": d.get("ticker"), "decision_id": d.get("id"),
            "verdict": (d.get("meta") or {}).get("verdict"),
            "confidence": latest, "trail_len": len(confs), "confidence_move": move,
            "age_days": _age_days(d.get("ts")),
        })
    open_book.sort(key=lambda r: (r["confidence"] is None, -(r["confidence"] or 0.0)))
    scored = [e.get("meta", {}) for e in mem.query(type="outcome", limit=0)
              if (e.get("meta") or {}).get("status") == "scored"]
    return {"ok": True, "open": open_book, "n_open": len(open_book),
            "brier_calibration": calibration.brier_aggregate(scored),
            "note": ("confidence is 0–1; the trail is Brier-scored at close — lower Brier = the "
                     "stated confidence tracked the truth, not just the direction.")}


# ----------------------------------------------------------------- capture loop
# The calibration flywheel only has torque if decisions are FROZEN at the moment of the call and
# OUTCOMES recorded at the horizon. These wire that capture so Tiers 1/2/4 see real data instead of an
# empty list: a council_verdict write auto-freezes a gradeable decision (the memory_write hook above),
# deduped so a re-affirmation doesn't pile up and a stance-change closes the old bet first;
# sweep_outcomes() closes decisions that reach their horizon at the current mark; backfill_decisions()
# primes the loop from the live book so it starts accumulating immediately.

def _age_days(ts: str) -> Optional[int]:
    """Whole days since an ISO timestamp (UTC), or None if unparseable."""
    if not ts:
        return None
    try:
        t = datetime.strptime(str(ts).replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).days
    except Exception:
        return None


def _open_decisions(mem, ticker: str = "") -> list:
    """Frozen decisions with no linked outcome yet — still live on the wealth path (newest first)."""
    closed = set()
    for o in mem.query(type="outcome", limit=0):
        for r in (o.get("refs") or []):
            closed.add(r)
    return [d for d in mem.query(ticker=(ticker or None), type="decision", limit=0)
            if d.get("id") not in closed]


def _action_key(s: str) -> str:
    """Coarse stance family so a re-affirmation dedupes across vocabularies (engine directive vs council
    stance): exit / trim / accumulate / hold. Delegates to calibration.stance_family — the single
    canonical map shared with the engine's deterministic flywheel turn (so a 'stance change' means the
    same thing on both paths)."""
    try:
        import calibration
        return calibration.stance_family(s)
    except Exception:
        return str(s or "").strip().upper()


def _current_price(ticker: str) -> Optional[float]:
    """Freshest mark for a name — the engine ladder price first (free), FMP fundamentals as fallback."""
    try:
        r = get_conviction_ratings(with_calibration=False)
        if r.get("engine_running"):
            b = next((x for x in r.get("baskets", [])
                      if str(x.get("ticker", "")).upper() == ticker.upper()), None)
            p = ((b or {}).get("ladder") or {}).get("price")
            if p:
                return float(p)
    except Exception:
        pass
    try:
        f = get_fundamentals(ticker) or {}
        p = f.get("price") or (f.get("fundamentals") or {}).get("price")
        if p:
            return float(p)
    except Exception:
        pass
    return None


def freeze_decision_if_new(ticker: str, verdict: str = "", source: str = "council") -> dict:
    """Freeze a gradeable decision for a name UNLESS the open one already holds the same stance (a
    re-affirmation — no duplicate, no clock reset). A stance CHANGE closes the open bet at the current
    mark first, then opens the new one. This is the deterministic capture the council loop was missing."""
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    opens = _open_decisions(mem, ticker)
    new_key = _action_key(verdict)
    if opens:
        cur = opens[0]
        cur_key = _action_key((cur.get("meta") or {}).get("verdict") or cur.get("text") or "")
        if cur_key == new_key:
            return {"ok": True, "skipped": "reaffirmation", "ticker": ticker, "stance": new_key}
        price = _current_price(ticker)              # stance changed → close the old bet at the mark
        if price is not None:
            try:
                record_outcome(ticker, price, horizon_days=max(1, _age_days(cur.get("ts")) or 1))
            except Exception as e:
                log.warning("could not close prior decision for %s at stance change: %s", ticker, e)
    return {**record_decision(ticker, verdict=verdict, source=source), "stance": new_key}


def sweep_outcomes(horizon_days: int = 90) -> dict:
    """Close every open decision that has reached its horizon, grading it at the current mark — the
    'record at horizon' half of the capture loop (host this on the recurring scheduler / call from
    /journal). Idempotent: already-graded decisions are skipped; names with no fresh price stay open."""
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    closed, skipped = [], []
    for d in _open_decisions(mem):
        ticker, age = d.get("ticker"), _age_days(d.get("ts"))
        if not ticker or age is None or age < horizon_days:
            skipped.append({"ticker": ticker, "age_days": age, "reason": "not due"})
            continue
        latest = mem.latest(ticker=ticker, type="decision")     # record_outcome grades the latest
        if not latest or latest.get("id") != d.get("id"):
            skipped.append({"ticker": ticker, "reason": "superseded"})
            continue
        price = _current_price(ticker)
        if price is None:
            skipped.append({"ticker": ticker, "reason": "no price"})
            continue
        res = record_outcome(ticker, price, horizon_days=horizon_days)
        (closed if res.get("ok") else skipped).append(
            {"ticker": ticker, "price": price, "result": (res.get("scored") or {}).get("result")})
    return {"ok": True, "closed": closed, "skipped": skipped, "n_closed": len(closed)}


def backfill_decisions(verdict: str = "") -> dict:
    """Prime the loop: freeze an open decision for each current holding that lacks one, from the live
    book — so the calibration flywheel starts accumulating now instead of from the next verdict."""
    r = get_conviction_ratings(with_calibration=False)
    if not r.get("engine_running"):
        return {"ok": False, "error": "engine not running — cannot backfill"}
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    frozen = []
    for b in r.get("baskets", []):
        t = b.get("ticker")
        if not t or _open_decisions(mem, t):
            continue
        res = freeze_decision_if_new(t, verdict or b.get("directive") or "", source="backfill")
        if res.get("ok") and not res.get("skipped"):
            frozen.append(t)
    return {"ok": True, "frozen": frozen, "n": len(frozen)}


def _calibration_prior(archetypes: Optional[list] = None) -> Optional[dict]:
    """Compact calibration prior (per-archetype expectancy + base rate, win-prob interval, wealth path +
    warning, spear backstop) for injection into the agent-facing frame. Single source shared by
    get_conviction_ratings and get_world_state, so every seat sees the same prior."""
    try:
        import calibration as _cal
        sc = calibration_scorecard(by_archetype=True)
        priored = sc.get("scorecard") if isinstance(sc, dict) and sc.get("ok") else None
        if not priored:
            return None
        book_arch = sorted({a for a in (archetypes or []) if a}) or None
        return _cal.brief_prior(priored, book_arch) or None
    except Exception as e:
        log.warning("calibration prior unavailable (desk frame ships without it): %s", e)
        return None


def calibration_scorecard(by_archetype: bool = True) -> dict:
    """The expectancy scorecard over all closed decisions in Living Memory — the Druckenmiller
    objective (slugging, expectancy, upside capture, downside containment); hit-rate demoted to
    secondary. Optionally split by archetype (tells the Bull/Bear where you run hot)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import calibration
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"calibration/memory unavailable: {e}"}
    scored = [e.get("meta", {}) for e in mem.query(type="outcome", limit=0)
              if (e.get("meta") or {}).get("status") == "scored"]
    # M7: fold in the seeded base-rate priors + the Ledger's REJECTs so the scorecard is useful even
    # when the personal sample is thin (reports estimate + credible interval, never a bare %).
    rejects = []
    try:
        import thesis_ledger
        rejects = thesis_ledger.Ledger(mem).graveyard()
    except Exception:
        rejects = []
    try:
        priored = calibration.priored_scorecard(scored, ledger_rejects=rejects)
        proposals = calibration.bias_proposals(priored)
    except Exception:                                  # base_rates optional — fall back to the core card
        priored = calibration.scorecard(scored, by_archetype=by_archetype)
        proposals = []
    out = {"ok": True, "scorecard": priored, "closed": len(scored),
           "bias_proposals": proposals,
           "note": ("Bias proposals route through propose_param_change → /confirm; never auto-applied."
                    if proposals else None)}
    # H5 — the confidence-calibration read (Brier over closed theses that carried a forecast trail):
    # expectancy says you were right; this says whether your CONFIDENCE was honest.
    try:
        out["brier_calibration"] = calibration.brier_aggregate(scored)
    except Exception:
        out["brier_calibration"] = None
    # validation flywheel: the VALUATION track record (replay over the ledger) rides beside the
    # decision scorecard — /journal reports both. Guarded: never fails the scorecard.
    try:
        vt = replay_grade(horizon_days=90)
        if vt.get("ok"):
            out["valuation_track"] = {"horizon_days": 90, "graded": vt.get("graded", 0),
                                      "report": vt.get("report"),
                                      "ledger_depth": (vt.get("ledger") or {}).get("records")}
    except Exception as e:
        log.warning("valuation track unavailable for the scorecard: %s", e)
    return out


def candidate_base_rate(archetype: str = "", sleeve: str = "", stage: str = "",
                        commodity: str = "") -> dict:
    """Reference-class base rate for a discovery candidate's archetype OR sleeve (spear/ballast) — the
    outside view @scout / @synthesis anchor a candidate's score to (Kahneman reference-class
    forecasting), so a find is judged against its archetype's published odds, not in a vacuum. Pass
    ``stage`` (grassroots/pea/pfs/fs/construction) to CONDITION the prior on the candidate's actual
    stage (Flyvbjerg chain) and ``commodity`` for the precious-metals tilt. Returns the prior (estimate
    + CI + source + a ready-to-cite line, plus stage_conditional / takeout_class when applicable) or a
    note when no researched prior maps."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import calibration
    except Exception as e:
        return {"ok": False, "error": f"calibration unavailable: {e}"}
    # H3→D4: fold the desk's OWN closed track record (the latest flywheel snapshot, else computed
    # live from outcomes) into the anchor, so a find is scored against the bar the book has cleared.
    learned = None
    try:
        mem = _living_memory()
        snap = mem.query(type="calibration_snapshot", limit=1)
        if snap:
            learned = (snap[0].get("meta") or {}).get("learned")
        if not learned:
            scored = [e.get("meta", {}) for e in mem.query(type="outcome", limit=0)
                      if (e.get("meta") or {}).get("status") == "scored"]
            learned = calibration.learned_base_rates(scored) or None
    except Exception:
        learned = None
    anchor = calibration.candidate_anchor(archetype or None, sleeve=sleeve or None,
                                          stage=stage or None, commodity=commodity or None,
                                          learned=learned)
    if not anchor:
        return {"ok": True, "anchor": None,
                "note": (f"no researched base rate maps to {archetype or sleeve or '—'} — score on "
                         f"merits, but flag the outside view as thin (no reference class).")}
    return {"ok": True, **anchor}


def story_card(ticker: str = "") -> dict:
    """Narrative→number Story Card for a holding (Damodaran discipline): the intrinsic decomposed into
    its named legs (with methods + values), the drivers behind it, and the BREAKPOINT — the move that
    takes the thesis to its kill-switch (intrinsic → price). Built from the engine's base valuation via
    the shared what-if route; the commodity breakpoint is first-order. Needs the engine running."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import valuation_actions as va
    except Exception as e:
        return {"ok": False, "error": f"valuation_actions unavailable: {e}"}
    res = run_valuation_whatif(ticker, "silver=+0")          # a no-op override returns the base valuation
    if not isinstance(res, dict) or res.get("error"):
        return {"ok": False, "error": (res or {}).get("error", "no valuation available")}
    # V1 mark-NAV-to-spot: surface the NAV mark's tier/staleness as a Story-Card driver so the
    # reader sees WHAT the intrinsic was marked against (live spot vs an analyst stamp + its age).
    drivers, ladder = {}, None
    try:
        ratings = get_conviction_ratings(with_calibration=False)
        b = next((bb for bb in ratings.get("baskets", [])
                  if str(bb.get("ticker", "")).upper() == (ticker or "").upper()), None)
        nq = (b or {}).get("nav_quality")
        if nq:
            import nav_mark
            note = nav_mark.quality_note(nq)
            if note:
                drivers["nav_mark"] = note
        ladder = (b or {}).get("ladder")
    except Exception as e:
        log.warning("nav-mark driver unavailable for the story card: %s", e)
        drivers = {}
    card = va.story_card(res.get("base") or {}, price=res.get("price"),
                         ticker=(ticker or "").upper() or None, drivers=(drivers or None))
    # V2: probability-weighted E[NAV] when a live signal grounds it (a drill/grade catalyst's
    # p_discovery_delta · the regime tilt), else the honest "what must you believe" breakeven bar.
    if ladder:
        card["scenario_ev"] = va.scenario_nav(
            ladder, price=res.get("price"),
            p_discovery_delta=(res.get("v_catalyst") or {}).get("p_discovery_delta"),
            regime_tilt=res.get("net_tilt"))
    return {"ok": True, "card": card, "render": va.render_story_card(card)}


# --------------------------------------------------------------------------- #
# Validation flywheel (docs/VALIDATION_FLYWHEEL_PLAN.md): the valuation ledger (Phase 1), the
# replay/grading harness (Phase 2), the discovery screen (Phase 6) and the graduation gate +
# scout sweep (Phase 7). The engine loop is the primary ledger writer; these tools read it,
# stamp manual/decision snapshots from ENGINE state only (Goodhart guard), and grade.
# --------------------------------------------------------------------------- #

def _valuation_ledger():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import valuation_ledger
    return valuation_ledger.ValuationLedger(path=str(LEDGER_PATH))


def _price_history():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import price_history
    return price_history.PriceHistory(path=str(PRICE_HISTORY_PATH))


def _snapshot_from_live(ticker: str, trigger: str = "manual") -> dict:
    """Stamp one ledger snapshot for a name from the LIVE engine rating (the projection carries
    ladder/asymmetry/gate/ribbon — all engine-sourced; an agent cannot supply the numbers)."""
    import valuation_ledger as vl
    ratings = get_conviction_ratings(with_calibration=False)
    if not ratings.get("engine_running"):
        return {"ok": False, "error": "engine not running — cannot snapshot"}
    basket = next((b for b in ratings.get("baskets", [])
                   if str(b.get("ticker", "")).upper() == ticker.upper()), None)
    if basket is None:
        return {"ok": False, "error": f"{ticker} not in the live book"}
    inputs = {}
    try:
        inputs = vl.inputs_from_provenance(_research_cache().provenance(ticker))
    except Exception:
        inputs = {}
    regime = {"mri": ratings.get("mri")}
    snap = vl.snapshot_from_basket(basket, inputs=inputs, regime=regime,
                                   engine_git_sha=vl.git_sha())
    rec = _valuation_ledger().record(snap, trigger=trigger)
    return {"ok": True, "snapshot_id": rec["id"], "ticker": rec["ticker"],
            "trigger": rec["trigger"], "ts": rec["ts"]}


def valuation_snapshot_now(ticker: str = "") -> dict:
    """Stamp a point-in-time valuation snapshot into the append-only ledger NOW (trigger=manual) —
    one name, or the whole live book when ticker is empty. The engine loop stamps daily marks and
    material changes automatically; this is the operator's explicit stamp."""
    if ticker:
        return _snapshot_from_live(ticker, trigger="manual")
    ratings = get_conviction_ratings(with_calibration=False)
    if not ratings.get("engine_running"):
        return {"ok": False, "error": "engine not running — cannot snapshot"}
    out = [_snapshot_from_live(b.get("ticker"), trigger="manual")
           for b in ratings.get("baskets", []) if b.get("ticker")]
    return {"ok": True, "snapshots": out, "n": sum(1 for r in out if r.get("ok"))}


def valuation_ledger_query(ticker: str = "", since: str = "", trigger: str = "",
                           limit: int = 20) -> dict:
    """Read the valuation ledger — the point-in-time record the replay harness grades. Filters
    AND together; newest first. Read-only (the ledger is append-only; agents never write it)."""
    try:
        led = _valuation_ledger()
    except Exception as e:
        return {"ok": False, "error": f"valuation ledger unavailable: {e}", "records": []}
    rows = led.query(ticker=(ticker or None), since=(since or None),
                     trigger=(trigger or None), limit=int(limit or 20))
    return {"ok": True, "count": len(rows), "stats": led.stats(), "records": rows}


def replay_grade(horizon_days: int = 90) -> dict:
    """Grade the valuation ledger against the cached price history at a horizon (Mode A: intrinsic
    →price convergence, band coverage / PIT, REP-floor reliability) — the valuation track record,
    with small-n honesty (event counts always; expectancy only when warm). Also returns the
    ledger-fed base-rate posteriors (floor reliability / band coverage per archetype)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import replay
        led = _valuation_ledger()
        hist = _price_history()
    except Exception as e:
        return {"ok": False, "error": f"replay/ledger/history unavailable: {e}"}
    grades = replay.grade_ledger(led, hist, horizon_days=int(horizon_days))
    rep = replay.report(grades)
    out = {"ok": True, "horizon_days": int(horizon_days), "graded": len(grades),
           "report": rep, "ledger": led.stats(), "price_history": hist.stats()}
    priors = replay.ledger_priors(grades)
    if priors:
        out["ledger_priors"] = priors
    return out


def run_discovery_screen(slot: str, gates_json: str = "") -> dict:
    """Run the quantitative discovery screen (slot-fit FIRST, then stage / jurisdiction / mcap /
    survival / REP-floor gates) over the maintained candidate universe
    (data/candidate_universe.json). Returns survivors (each with data_gaps + its base-rate anchor)
    and the auditable kill log. @scout enriches the survivors — the screen is the funnel."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import discovery_screen as ds
    except Exception as e:
        return {"ok": False, "error": f"discovery_screen unavailable: {e}"}
    gates = None
    if gates_json:
        try:
            gates = json.loads(gates_json)
        except (ValueError, json.JSONDecodeError):
            return {"ok": False, "error": "gates_json is not valid JSON"}
    uni = ds.load_universe(str(UNIVERSE_PATH))
    cfg_gates = dict(uni.get("screen_config") or {})
    cfg_gates.update(gates or {})
    res = ds.screen(uni.get("candidates") or [], slot=slot, gates=(cfg_gates or None))
    return {"ok": True, **res}


def graduate_candidate(ticker: str, verifier_ref: str, anti_scout_ref: str,
                       forensic_ref: str) -> dict:
    """The MANDATORY disconfirmation gate (Phase 7): a candidate may only graduate to the
    watchlist with all three receipts on record — a @verifier verdict, an @anti-scout sweep
    (CLEAN is valid and recorded), and the forensic/JSF result. Each ref must be a Living Memory
    entry id for THIS ticker. REFUSES otherwise — enforcement lives here at the MCP layer, not
    inside the TUI. Writes the ``graduation`` entry (refs = the receipts) on success."""
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    refs = {"verifier": verifier_ref, "anti_scout": anti_scout_ref, "forensic": forensic_ref}
    missing = [k for k, v in refs.items() if not str(v or "").strip()]
    if missing:
        return {"ok": False, "refused": True,
                "error": f"graduation REFUSED — missing receipt(s): {missing}. No candidate "
                         f"enters the watchlist un-disconfirmed (run @verifier and @anti-scout, "
                         f"record their verdicts to Memory, then retry with the entry ids)."}
    resolved = {}
    for role, rid in refs.items():
        e = mem.get(str(rid).strip())
        if not e:
            return {"ok": False, "refused": True,
                    "error": f"graduation REFUSED — {role} ref {rid!r} not found in Memory."}
        if (e.get("ticker") or "").upper() != ticker.upper():
            return {"ok": False, "refused": True,
                    "error": f"graduation REFUSED — {role} ref {rid!r} is for "
                             f"{e.get('ticker')!r}, not {ticker.upper()}."}
        resolved[role] = e["id"]
    warn = None
    if not mem.query(ticker=ticker, type="scout_candidate", limit=1):
        warn = ("no scout_candidate entry on record for this name — graduating outside the "
                "screen-first funnel; the scout scorecard cannot grade it.")
    entry = mem.write("graduation", ticker=ticker,
                      text=f"GRADUATED {ticker.upper()} — disconfirmation gate cleared "
                           f"(verifier + anti-scout + forensic receipts on record)",
                      tags=["graduation"], refs=list(resolved.values()),
                      meta={"receipts": resolved}, source="graduation-gate")
    out = {"ok": True, "id": entry["id"], "ticker": entry["ticker"], "receipts": resolved}
    if warn:
        out["warning"] = warn
    return out


# Fields a promotion may write into portfolio_metadata (scoped — never an arbitrary config edit).
_EVAL_META_FIELDS = ("type", "stage", "currency", "subarchetype", "sector_tags", "thesis_slot",
                     "thesis_slot_desc", "management_score", "fraser_index")
# Fields a promotion may write into ballast_valuation (the market-leg anchors).
_EVAL_BALLAST_FIELDS = ("currency", "ref_price", "commodity", "spot_ref")


def _load_raw_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _write_raw_config(cfg: dict) -> str:
    """Atomic v5_config.json write with a timestamped backup — the SANCTIONED scoped writer
    behind promote/demote. The generic edit_file deny-list still protects the file from
    arbitrary string edits; this path only ever writes validated eval-set sections, honors
    READONLY, and leaves a restorable backup."""
    if READONLY:
        raise SafetyError("server is in read-only mode (CEX_MCP_READONLY=1)")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"{CONFIG_PATH.name}.{stamp}.bak"
    backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    try:
        return str(backup.relative_to(REPO_ROOT))
    except ValueError:                       # sandboxed/overridden paths outside the repo root
        return str(backup)


def promote_to_eval(ticker: str, archetype: str, inputs_json: str = "",
                    graduation_ref: str = "", confirm: bool = False) -> dict:
    """Promote a GRADUATED candidate into the engine's EVAL set — the missing link between the
    watchlist and a live rating. The engine then rates it like a holding (price fetched,
    archetype-valued through the Polymorphic Factory, T-Q-V conviction-scored, hot-loaded next
    cycle — no restart) but it carries NO barbell weight and enters NO sizing: rated, not held.

    Gates (in order — enforcement lives here at the MCP layer):
      1. ``confirm=True`` — the explicit human gate; a dry call returns the exact write plan.
      2. A ``graduation`` entry for this ticker must exist in Living Memory (the mandatory
         verifier + anti-scout + forensic disconfirmation gate). No receipts, no rating.
      3. ``archetype`` must be a registered archetype class; never guessed.
      4. The ticker must not already be in the book (an existing eval entry is updated).

    ``inputs_json`` (optional JSON object) seeds the valuation inputs:
      * metadata fields: type, stage, currency, subarchetype, sector_tags, thesis_slot,
        thesis_slot_desc, management_score, fraser_index
      * ``ballast``: {currency, ref_price, commodity, spot_ref} — the market-leg anchors
      * ``research``: {field: {value, source, as_of, confidence?, note?}} — sourced filings
        facts (shares_out, book_value_per_share, cash…) written to the research cache with
        full provenance; unsourced values are refused.
    """
    tkr = str(ticker or "").strip().upper()
    if not tkr:
        return {"ok": False, "error": "ticker required"}
    if READONLY:
        return {"ok": False, "error": "server is in read-only mode (CEX_MCP_READONLY=1)"}
    try:
        inputs = json.loads(inputs_json) if str(inputs_json or "").strip() else {}
        if not isinstance(inputs, dict):
            raise ValueError("inputs_json must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        return {"ok": False, "error": f"bad inputs_json: {e}"}

    # Gate 2 — the disconfirmation receipts, via the graduation entry.
    try:
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"memory unavailable: {e}"}
    grad = None
    if str(graduation_ref or "").strip():
        grad = mem.get(str(graduation_ref).strip())
        if grad and (grad.get("ticker") or "").upper() != tkr:
            return {"ok": False, "refused": True,
                    "error": f"promotion REFUSED — graduation ref is for {grad.get('ticker')!r}, not {tkr}."}
    if grad is None:
        hits = mem.query(ticker=tkr, type="graduation", limit=1)
        grad = hits[0] if hits else None
    if grad is None:
        return {"ok": False, "refused": True,
                "error": f"promotion REFUSED — no graduation entry for {tkr} in Living Memory. "
                         f"Run the disconfirmation gate first (@verifier + @anti-scout + forensic, "
                         f"then graduate_candidate), then retry."}

    # Gate 3 — a real archetype class, never guessed.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from archetypes import ARCHETYPE_REGISTRY
    except ImportError as e:
        return {"ok": False, "error": f"archetypes module unavailable: {e}"}
    arch = str(archetype or "").strip()
    if arch not in ARCHETYPE_REGISTRY:
        return {"ok": False, "refused": True,
                "error": f"unknown archetype {arch!r}; valid: {sorted(ARCHETYPE_REGISTRY)}"}

    # Gate 4 — never silently overwrite a real holding's metadata.
    try:
        cfg = _load_raw_config()
    except Exception as e:
        return {"ok": False, "error": f"v5_config.json unreadable: {e}"}
    meta_all = cfg.setdefault("portfolio_metadata", {})
    existing = meta_all.get(tkr)
    if isinstance(existing, dict) and not existing.get("eval_only"):
        return {"ok": False, "refused": True,
                "error": f"{tkr} is already a BOOK holding — promotion targets candidates, "
                         f"not the book. Use /rotate for holdings."}

    entry = {k: inputs[k] for k in _EVAL_META_FIELDS if k in inputs}
    entry.update({"archetype": arch, "eval_only": True, "promoted_at": _now(),
                  "graduation_ref": grad.get("id")})
    ballast = {k: v for k, v in (inputs.get("ballast") or {}).items() if k in _EVAL_BALLAST_FIELDS}
    research = inputs.get("research") or {}
    bad = [f for f, spec in research.items()
           if not (isinstance(spec, dict) and spec.get("value") is not None
                   and str(spec.get("source", "")).strip() and str(spec.get("as_of", "")).strip())]
    if bad:
        return {"ok": False, "refused": True,
                "error": f"research fields missing value/source/as_of (provenance is mandatory): {bad}"}

    plan = {"portfolio_metadata": {tkr: entry},
            **({"ballast_valuation": {tkr: ballast}} if ballast else {}),
            **({"research_cache": sorted(research)} if research else {})}
    if not confirm:
        return {"ok": False, "status": "needs_confirmation", "plan": plan,
                "message": f"Would promote {tkr} to the engine EVAL set (rated, not held). "
                           f"Re-call with confirm=true to apply."}

    meta_all[tkr] = {**(existing if isinstance(existing, dict) else {}), **entry}
    if ballast:
        bv_all = cfg.setdefault("ballast_valuation", {})
        bv_all[tkr] = {**(bv_all.get(tkr) or {}), **ballast}
    try:
        backup = _write_raw_config(cfg)
    except Exception as e:
        return {"ok": False, "error": f"config write failed: {e}"}

    cached = []
    if research:
        rc = _research_cache()
        if rc is None:
            return {"ok": False, "error": "config written but research_cache unavailable — "
                                          "seed the sourced fields manually.", "backup": backup}
        for field, spec in research.items():
            rc.set(tkr, str(field), spec["value"], source=str(spec["source"]),
                   as_of=str(spec["as_of"]), confidence=str(spec.get("confidence", "med")),
                   note=str(spec.get("note", "")))
            cached.append(str(field))

    note = mem.write("promotion", ticker=tkr,
                     text=f"PROMOTED {tkr} to the engine EVAL set — archetype {arch}; rated "
                          f"alongside the book (no weight, no sizing) from the next engine cycle",
                     tags=["promotion", "eval"], refs=[grad.get("id")],
                     meta={"archetype": arch, "plan": plan}, source="promotion-gate")
    return {"ok": True, "id": note["id"], "ticker": tkr, "archetype": arch, "backup": backup,
            "research_cached": cached,
            "note": "config hot-reloads — the engine prices, values and rates this name on its "
                    "next cycle (engine build must include eval-set support). It holds no "
                    "barbell weight and enters no sizing math."}


def demote_from_eval(ticker: str, reason: str = "", confirm: bool = False) -> dict:
    """Remove a name from the engine's EVAL set (the inverse of ``promote_to_eval``). REFUSES
    to touch a real book holding — only entries flagged ``eval_only`` can be demoted. The
    research cache keeps its sourced history (point-in-time discipline); only the config entry
    goes. Writes a ``demotion`` entry to Living Memory."""
    tkr = str(ticker or "").strip().upper()
    if not tkr:
        return {"ok": False, "error": "ticker required"}
    if READONLY:
        return {"ok": False, "error": "server is in read-only mode (CEX_MCP_READONLY=1)"}
    try:
        cfg = _load_raw_config()
    except Exception as e:
        return {"ok": False, "error": f"v5_config.json unreadable: {e}"}
    meta = (cfg.get("portfolio_metadata") or {}).get(tkr)
    if not isinstance(meta, dict):
        return {"ok": False, "error": f"{tkr} is not in portfolio_metadata."}
    if not meta.get("eval_only"):
        return {"ok": False, "refused": True,
                "error": f"{tkr} is a BOOK holding, not an eval name — demotion refused. "
                         f"Rotations go through /rotate."}
    if not confirm:
        return {"ok": False, "status": "needs_confirmation",
                "message": f"Would remove {tkr} from the EVAL set (portfolio_metadata"
                           f"{' + ballast_valuation' if tkr in (cfg.get('ballast_valuation') or {}) else ''}). "
                           f"Re-call with confirm=true to apply."}
    cfg["portfolio_metadata"].pop(tkr, None)
    if tkr in (cfg.get("ballast_valuation") or {}):
        cfg["ballast_valuation"].pop(tkr, None)
    try:
        backup = _write_raw_config(cfg)
    except Exception as e:
        return {"ok": False, "error": f"config write failed: {e}"}
    try:
        mem = _living_memory()
        note = mem.write("demotion", ticker=tkr,
                         text=f"DEMOTED {tkr} from the engine EVAL set"
                              + (f" — {reason}" if str(reason or "").strip() else ""),
                         tags=["demotion", "eval"], source="promotion-gate")
        nid = note["id"]
    except Exception:
        nid = None
    return {"ok": True, "ticker": tkr, "backup": backup, "memory_id": nid,
            "note": "config hot-reloads — the name drops from ratings on the next engine cycle."}


def sweep_scout_outcomes(horizon_days: int = 90) -> dict:
    """Close out scout candidates that reached their horizon, grading each at the cached
    daily-close mark (never a live quote) — the decaying watch that gives DISCOVERY a track
    record. Idempotent per (candidate, horizon). Returns the scout scorecard (hit-rate headlines
    here BY DESIGN — a funnel's objective is frequency; the book's stays expectancy-first)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import calibration
        mem = _living_memory()
        hist = _price_history()
    except Exception as e:
        return {"ok": False, "error": f"calibration/memory/history unavailable: {e}"}
    from datetime import timedelta
    swept, skipped, rows = [], [], []
    graduated = {(e.get("ticker") or "").upper()
                 for e in mem.query(type="graduation", limit=0)}
    already = set()
    for o in mem.query(type="outcome", tag="scout", limit=0):
        for r in (o.get("refs") or []):
            already.add((r, (o.get("meta") or {}).get("horizon_days")))
    for c in mem.query(type="scout_candidate", limit=0, newest_first=False):
        meta = c.get("meta") or {}
        tkr, p0 = c.get("ticker"), meta.get("price_at_surfacing")
        try:
            p0 = float(p0)
        except (TypeError, ValueError):
            skipped.append({"ticker": tkr, "reason": "no price_at_surfacing frozen"})
            continue
        t0 = _age_days(c.get("ts"))
        if t0 is None or t0 < int(horizon_days):
            skipped.append({"ticker": tkr, "age_days": t0, "reason": "not due"})
            continue
        row_key = (c.get("id"), int(horizon_days))
        try:
            stamp = datetime.strptime(str(c.get("ts"))[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            skipped.append({"ticker": tkr, "reason": "bad timestamp"})
            continue
        mark = hist.close_on(tkr, stamp + timedelta(days=int(horizon_days)))
        if mark is None:
            skipped.append({"ticker": tkr, "reason": "no price history at horizon"})
            continue
        realized = mark["close"] / p0 - 1.0
        row = {"ticker": tkr, "archetype": meta.get("archetype"), "slot": meta.get("slot"),
               "graduated": (tkr or "").upper() in graduated,
               "realized_return": round(realized, 4), "horizon_days": int(horizon_days)}
        rows.append(row)
        if row_key not in already:
            mem.write("outcome", ticker=tkr,
                      text=(f"SCOUT OUTCOME {realized*100:+.0f}% @{horizon_days}d "
                            f"({'graduated' if row['graduated'] else 'not graduated'})"),
                      tags=["scout"], refs=[c.get("id")], meta=row, source="scout-sweep")
            swept.append(tkr)
    return {"ok": True, "swept": swept, "skipped": skipped,
            "scorecard": calibration.scout_scorecard(rows)}


# --------------------------------------------------------------------------- #
# Forge layer tools (M1 calendar · M2 thesis/ledger · M3 sentinel · M6 swap). Each is a thin,
# defensive wrapper: the engine/memory are the source of truth; these read, interpret, and persist.
# --------------------------------------------------------------------------- #

def _calendar():
    """Bind a CatalystCalendar to the repo store (importable from the MCP process)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import catalyst_calendar
    return catalyst_calendar.CatalystCalendar(path=str(CALENDAR_PATH))


def _research_cache():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import research_cache
        return research_cache.ResearchCache()
    except Exception:
        return None


def _set_path(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _effective_config() -> dict:
    """The effective config = static v5_config.json + the engine's live overlay (so the Forge
    tunables under ``forge.*`` honor any propose/confirm override). Degrades to the static file."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    try:
        for r in (list_params() or {}).get("params", []) or []:
            if isinstance(r, dict) and "key" in r and "value" in r:
                _set_path(cfg, r["key"], r["value"])
    except Exception:
        pass
    return cfg


def _live_regime():
    """Best-effort live regime context for stamping a Forge write (never blocks on the engine)."""
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=1.5)
        conv_ctx = (state.get("conviction_mode") or {}).get("context", {})
        return {"mri": state.get("mri"),
                "net_tilt": (state.get("macro_tape") or {}).get("net_tilt") or conv_ctx.get("regime"),
                "posture": (state.get("posture") or {}).get("code")}
    except Exception:
        return None


def catalyst_write(kind: str, title: str, window_start: str, window_end: str = "",
                   ticker: str = "", macro_kind: str = "", confidence: str = "estimated",
                   source: str = "manual", source_url: str = "", status: str = "pending",
                   linked_thesis: str = "", notes: str = "") -> dict:
    """Add a catalyst WINDOW to the shared calendar (M1). A catalyst is a window, not a point:
    'expected Q3' → [start, end]. ``ticker`` empty ⇒ a macro event. Grounded-or-silent: pass the
    ``source_url`` straight-to-source (issuer PR / SEDAR+ / EDGAR) — never invent a date."""
    if READONLY:
        return {"ok": False, "error": "MCP is read-only"}
    try:
        cal = _calendar()
        e = cal.write(kind=kind, title=title, window_start=window_start,
                      window_end=(window_end or None), ticker=(ticker or None),
                      macro_kind=(macro_kind or None), confidence=confidence, source=source,
                      source_url=source_url, status=status, linked_thesis=(linked_thesis or None),
                      notes=notes, regime=_live_regime())
        return {"ok": True, "id": e["id"], "ticker": e["ticker"], "kind": e["kind"],
                "window": [e["window_start"], e["window_end"]]}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def catalyst_query(ticker: str = "", within_days: int = 30, kind: str = "",
                   status: str = "pending", include_macro: bool = False) -> dict:
    """Pending catalysts overlapping the next ``within_days`` (M1). ``ticker`` empty ⇒ all names +
    macro; ``include_macro=true`` folds the macro tape into a named query (the cockpit strip)."""
    try:
        cal = _calendar()
        hits = cal.query(ticker=(ticker or None), within_days=int(within_days or 30),
                         kind=(kind or None), status=(status or None),
                         include_macro=bool(include_macro))
        return {"ok": True, "count": len(hits), "catalysts": hits, "stats": cal.stats()}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "catalysts": []}


def catalyst_seed_macro(horizon_days: int = 90) -> dict:
    """Seed the rule-deterministic recurring macro windows (COT/NFP scheduled, CPI estimated; never
    FOMC). Idempotent — safe to call on a schedule."""
    if READONLY:
        return {"ok": False, "error": "MCP is read-only"}
    try:
        import catalyst_calendar
        cal = _calendar()
        n = catalyst_calendar.seed_macro(cal, horizon_days=int(horizon_days or 90),
                                         regime=_live_regime())
        return {"ok": True, "seeded": n}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def thesis_write(ticker: str, thesis_json: str = "", stance: str = "CONDITIONAL") -> dict:
    """Persist an underwriting THESIS (intangibles + load-bearing claims[] + pre-commitment rules[],
    M2). ``thesis_json`` is the structured body (see thesis_ledger.build_thesis). VALIDATED at save:
    every rule trigger is parsed through the safe grammar, every engine claim type-checked — a bad
    rule is rejected here with a clear error, never written."""
    if READONLY:
        return {"ok": False, "error": "MCP is read-only"}
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import thesis_ledger
        mem = _living_memory()
    except Exception as e:
        return {"ok": False, "error": f"thesis layer unavailable: {e}"}
    try:
        body = json.loads(thesis_json) if thesis_json else {}
    except (ValueError, json.JSONDecodeError):
        return {"ok": False, "error": "thesis_json is not valid JSON"}
    body.setdefault("ticker", ticker)
    body.setdefault("stance", stance)
    body = thesis_ledger.build_thesis(body.get("ticker"), stance=body.get("stance"),
                                      archetype=body.get("archetype", ""),
                                      claims=body.get("claims"), rules=body.get("rules"),
                                      expected=body.get("expected"),
                                      linked_calendar=body.get("linked_calendar"),
                                      source_urls=body.get("source_urls"),
                                      regime_at_entry=_live_regime() or {},
                                      intangibles={k: v for k, v in body.items() if k not in (
                                          "ticker", "stance", "archetype", "claims", "rules",
                                          "expected", "linked_calendar", "source_urls")})
    ok, errors = thesis_ledger.validate_thesis(body)
    if not ok:
        return {"ok": False, "error": "invalid thesis", "errors": errors}
    entry = mem.write("thesis", text=thesis_ledger.thesis_summary_line(body),
                      ticker=body["ticker"], tags=["thesis", body["stance"].lower()],
                      regime=_live_regime(), meta=body, source=_AGENT_NAME)
    return {"ok": True, "id": entry["id"], "ticker": body["ticker"], "stance": body["stance"],
            "claims": len(body["claims"]), "rules": len(body["rules"])}


def get_ledger(stance: str = "") -> dict:
    """The Thesis Ledger (M2) — every thesis joined to its realized outcomes; the graveyard (REJECTs)
    and hall of fame side by side. ``stance`` optionally filters APPROVE / CONDITIONAL / REJECT."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import thesis_ledger
        mem = _living_memory()
        led = thesis_ledger.Ledger(mem)
        return {"ok": True, "entries": led.entries(stance=(stance or None)), "stats": led.stats()}
    except Exception as e:
        return {"ok": False, "error": str(e), "entries": []}


def _sentinel_open_keys(mem, ticker: str) -> tuple:
    """(open_keys, acked_keys) for a name — from the last sentinel sweep + any acks since."""
    open_keys, acked = set(), set()
    last = mem.latest(ticker=ticker, type="sentinel")
    if last:
        for a in ((last.get("meta") or {}).get("alerts") or []):
            if a.get("status") in ("new", "open"):
                open_keys.add(a.get("key"))
    for ack in mem.query(ticker=ticker, type="sentinel_ack", limit=200):
        k = (ack.get("meta") or {}).get("key")
        if k:
            acked.add(k)
    return open_keys, acked


def sentinel_sweep(ticker: str = "", autonomy: str = "auto") -> dict:
    """Run the Sentinel (M3) across the held book (or one ``ticker``): diff live state vs each frozen
    thesis → liquidity-runway, financing-window/death-spiral, thesis-integrity, fired pre-commitment
    rules. Writes a per-name SENTINEL status to Living Memory and, per Open-Decision #5, AUTONOMOUSLY
    pins alert-level findings; trims/exits surface as PROPOSALS to acknowledge (never auto-acted)."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import sentinel as sen
        mem = _living_memory()
        cal = _calendar()
        rc = _research_cache()
    except Exception as e:
        return {"ok": False, "error": f"sentinel layer unavailable: {e}"}
    ratings = get_conviction_ratings()
    if not ratings.get("engine_running"):
        return {"ok": False, "engine_running": False, "hint": "Start the engine, then retry."}
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=2.0)
    except Exception:
        return _engine_down()
    nodes = state.get("nodes") or {}
    pstats = state.get("portfolio_stats") or {}
    mri = state.get("mri")
    cfg = _effective_config()

    results, fired_total = [], 0
    for b in ratings.get("baskets", []):
        tk = b.get("ticker")
        if not tk or (ticker and tk.upper() != ticker.upper()):
            continue
        node = nodes.get(tk) or {}
        thesis = (mem.latest_thesis(tk) or {}).get("meta")
        open_keys, acked = _sentinel_open_keys(mem, tk)
        # resolve the M0 gap inputs (STATE_FIELDS): ADV / placement / 52w / runway from research_cache
        adv90 = node.get("adv_median_90") or (rc.value(tk, "adv_median_90") if rc else None) \
            or (rc.value(tk, "adv90") if rc else None)
        lpp = rc.value(tk, "last_placement_price") if rc else None
        lo52 = rc.value(tk, "low_52w") if rc else None
        hi52 = rc.value(tk, "high_52w") if rc else None
        # Phase 4: surface flagged two-source conflicts (cross_check demoted these fields to low
        # confidence; the Sentinel shows the WHY) — read from the cache notes, no network.
        conflicts = []
        if rc:
            for fld, entry in (rc.provenance(tk) or {}).items():
                note = str((entry or {}).get("note") or "")
                if "DATA CONFLICT" in note:
                    conflicts.append({"field": fld, "filings_value": entry.get("value"),
                                      "market_value": None, "disagreement": None,
                                      "note": note})
        st = sen.sweep_name(
            ticker=tk, basket=b, node=node, portfolio_stats=pstats, thesis=thesis, mri=mri,
            adv90=adv90, last_placement_price=lpp, lo52=lo52, hi52=hi52,
            catalyst_within_days=(lambda n, _tk=tk: cal.has_within(_tk, n, include_macro=True)),
            events=cal.hits_by_kind(tk), open_keys=open_keys, acknowledged_keys=acked, config=cfg,
            data_conflicts=conflicts)
        # persist the status (append-only)
        mem.write("sentinel", text=sen.status_to_memory_text(st), ticker=tk, tags=["sentinel"],
                  regime=_live_regime(), meta=st, source="sentinel")
        # autonomous alerts (Open-Decision #5): auto-pin alert-level NEW findings; PROPOSE trims/exits
        for a in st["new_alerts"]:
            fired_total += 1
            if autonomy == "auto" and a.get("auto_actable"):
                pin_insight(tk, a["text"][:140], badge="🛰", level=a.get("level", "warn"))
            else:
                highlight_ticker(tk, f"PROPOSAL: {a['text'][:120]}", level=a.get("level", "warn"))
        results.append({"ticker": tk, "summary": sen.status_to_memory_text(st),
                        "runway_ok": st["liquidity"].get("runway_ok"),
                        "integrity": st["integrity"].get("score"),
                        "death_spiral": st["death_spiral"], "new_alerts": len(st["new_alerts"]),
                        "size_gate": st["size_gate"]})
    return {"ok": True, "swept": len(results), "new_alerts": fired_total, "names": results}


def sentinel_ack(ticker: str, key: str, action: str = "ack", reason: str = "") -> dict:
    """Acknowledge a fired Sentinel tripwire (act / snooze / void) so it leaves the live queue and
    does not re-fire. Append-only — the record survives (audit trail)."""
    if READONLY:
        return {"ok": False, "error": "MCP is read-only"}
    try:
        mem = _living_memory()
        e = mem.write("sentinel_ack", text=f"ACK {action} {key} — {reason}"[:140], ticker=ticker,
                      tags=["sentinel", "ack", action], meta={"key": key, "action": action,
                                                              "reason": reason}, source=_AGENT_NAME)
        return {"ok": True, "id": e["id"], "key": key, "action": action}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def council_swap(incumbent: str, challenger: str, regime_inflection: bool = False) -> dict:
    """Reconcile an UP-TIER (swap) proposal (M6): @bull's challenger vs the incumbent, under the
    friction-adjusted hurdle + catalyst lock. Friction is computed from the incumbent's M3 liquidity
    runway; the catalyst lock reads the shared calendar. Returns SWAP / REJECT / DEFER with the math."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import council
        import sentinel as sen
        mem = _living_memory()
        cal = _calendar()
    except Exception as e:
        return {"ok": False, "error": f"swap layer unavailable: {e}"}
    ratings = get_conviction_ratings()
    if not ratings.get("engine_running"):
        return {"ok": False, "engine_running": False}
    baskets = {b.get("ticker", "").upper(): b for b in ratings.get("baskets", [])}
    inc_b = baskets.get(incumbent.upper())
    chl_b = baskets.get(challenger.upper())
    if not inc_b:
        return {"ok": False, "error": f"incumbent {incumbent} not in the live book"}
    def _persist(v) -> bool:
        try:
            ent = council.swap_to_memory_entry(v)
            mem.write(ent["type"], text=ent["text"], ticker=ent["ticker"], tags=ent["tags"],
                      regime=_live_regime(), meta=ent["meta"], source=_AGENT_NAME)
            return True
        except Exception as e:                  # the verdict still returns, but say it wasn't recorded
            log.warning("swap verdict NOT persisted to Living Memory: %s", e)
            return False

    # --- slot-fit gate: NON-NEGOTIABLE, ahead of valuation (CLAUDE.md barbell discipline). A rotation
    #     must fill the incumbent's thesis_slot first; a mismatch is REJECTED without scoring edge. ---
    pm = {}
    try:
        pm = (_effective_config() or {}).get("portfolio_metadata", {}) or {}
    except Exception:
        pm = {}
    def _slot(tk):
        return (pm.get(tk) or pm.get(tk.upper()) or {}).get("thesis_slot") or None
    inc_slot, chl_slot = _slot(incumbent), _slot(challenger)
    ok_slot, slot_reason = council.slot_gate(inc_slot, chl_slot)
    if not ok_slot:
        verdict = {"decision": "REJECT", "reason": "slot-mismatch",
                   "incumbent": incumbent.upper(), "challenger": challenger.upper(),
                   "incumbent_slot": inc_slot, "challenger_slot": chl_slot,
                   "rho": {"incumbent": (inc_b.get("asymmetry") or {}).get("rho"), "challenger": None},
                   "rationale": (f"REJECT — slot-mismatch: {challenger.upper()} fills the '{chl_slot}' "
                                 f"slot, but {incumbent.upper()} holds '{inc_slot}'. A rotation must fit "
                                 f"the same slot first, ahead of valuation — not scored on edge.")}
        persisted = _persist(verdict)
        return {"ok": True, "verdict": verdict, "slot_gate": slot_reason, "persisted": persisted}

    # --- challenger ρ: the live book first, then the research cache (an off-book / bench challenger);
    #     if neither has a ρ, say so plainly and point to valuation — never a dead-end error. ---
    off_book = False
    if chl_b:
        chl_rho = (chl_b.get("asymmetry") or {}).get("rho")
    else:
        off_book = True
        chl_rho = None
        try:
            rc0 = _research_cache()
            if rc0:
                chl_rho = rc0.value(challenger, "rho")
                if chl_rho is None:
                    asym = rc0.value(challenger, "asymmetry")
                    chl_rho = asym.get("rho") if isinstance(asym, dict) else None
        except Exception:
            chl_rho = None
        if chl_rho is None:
            return {"ok": False, "needs": "valuation", "challenger": challenger.upper(),
                    "hint": (f"{challenger.upper()} isn't in the live book and has no cached ρ — run "
                             f"/pipeline or @synthesis on it first so there's an asymmetry to compare.")}

    # incumbent exit friction from the live liquidity runway
    days_90 = None
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=2.0)
        node = (state.get("nodes") or {}).get(incumbent.upper(), {})
        pstats = state.get("portfolio_stats") or {}
        rc = _research_cache()
        adv90 = node.get("adv_median_90") or (rc.value(incumbent, "adv_median_90") if rc else None)
        liq = sen.liquidity_runway(adv90, pstats.get("expected_shortfall_95"), node.get("shares"))
        days_90 = liq.get("days_90")
    except Exception:
        days_90 = None
    nxt = cal.next_for(incumbent, include_macro=False)
    catalyst_days = nxt.get("_days_to_start") if nxt else None
    inc = {"ticker": incumbent.upper(), "rho": (inc_b.get("asymmetry") or {}).get("rho"),
           "days_90": days_90}
    chl = {"ticker": challenger.upper(), "rho": chl_rho}
    verdict = council.swap_verdict(inc, chl, catalyst_days=catalyst_days,
                                   regime_inflection=bool(regime_inflection),
                                   config=_effective_config())
    if off_book:
        verdict["off_book"] = True
    if slot_reason == "slot-unverified":
        verdict["slot_unverified"] = True
        missing = ([challenger.upper()] if not chl_slot else []) + ([incumbent.upper()] if not inc_slot else [])
        verdict["rationale"] = (verdict.get("rationale", "")
                                + f" ⚠ slot-fit UNVERIFIED — no configured thesis_slot for "
                                  f"{' and '.join(missing) or 'a side'}; confirm the challenger fills "
                                  f"the '{inc_slot or 'incumbent'}' slot before acting.")
    persisted = _persist(verdict)
    return {"ok": True, "verdict": verdict, "slot_gate": slot_reason, "persisted": persisted}


def get_world_state() -> dict:
    """One situational-awareness snapshot for an agent to ground itself in — regime + posture, what
    the operator is looking at, the operator's recent terminal actions, the book's verdicts, and
    recent Living Memory. Call this ONCE at the start instead of stitching get_conviction_ratings +
    memory_query + get_ui_context — so you never start blind. Returns {world, brief}."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import world_state
    except Exception as e:
        return {"ok": False, "error": f"world_state unavailable: {e}"}
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=2.0)
    except Exception:
        return {"ok": False, "engine_running": False,
                "hint": "Start the engine with run_engine(action='start')."}
    recent_mem, focus = [], None
    try:
        mem = _living_memory()
        recent_mem = mem.query(limit=5)
    except Exception:
        recent_mem = []
    try:
        ui = _http_get_json(f"{ENGINE_URL}/ui/state", timeout=1.5)
        focus = (ui or {}).get("focused_ticker")
    except Exception:
        focus = None
    # calibration flywheel (read side): fold the per-archetype prior into the frame so every agent
    # underwriting off this brief inherits "the bar this archetype has actually cleared" (+ base rate).
    # Shares the single source (_calibration_prior) with get_conviction_ratings.
    conv = state.get("conviction_mode") or {}
    cal_prior = _calibration_prior([b.get("archetype") for b in (conv.get("baskets") or [])])
    world = world_state.build(state, recent_memory=recent_mem, focus=focus, calibration=cal_prior)
    out = {"ok": True, "world": world, "brief": world_state.render_brief(world)}
    # validation flywheel: ledger depth — the operator sees the track record accruing.
    try:
        out["valuation_ledger"] = _valuation_ledger().stats()
    except Exception:
        pass
    return out


def _brief_flags(state: dict) -> list[dict]:
    """The actionable layer the raw world-frame doesn't surface: per-name flags worth the
    operator's eyes today — BELOW REP floor (accumulate), a binding forensic cap, a stale feed,
    or a near-term catalyst. Grounded-or-silent: a missing field is simply not flagged."""
    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    flags: list[dict] = []
    conv = state.get("conviction_mode") or {}
    for b in (conv.get("baskets") or []):
        tk = b.get("ticker")
        if not tk:
            continue
        V = (b.get("pillars") or {}).get("V") or {}
        cov = _num(V.get("floor_coverage"))
        if cov is not None and cov >= 1.0:                 # price at/under the REP liquidation floor
            flags.append({"ticker": tk, "level": "good", "kind": "below_floor",
                          "text": f"{tk} BELOW REP floor — accumulate signal"})
        dtf = _num(V.get("downside_to_floor_pct"))
        if cov is not None and cov < 1.0 and dtf is not None and dtf <= 12.0:
            flags.append({"ticker": tk, "level": "info", "kind": "near_floor",
                          "text": f"{tk} {dtf:.0f}% above its floor — well-protected"})
        gate = b.get("gate") or {}
        cap = _num(gate.get("cap"))
        if gate.get("applied") and cap is not None and cap <= 5.0:
            flags.append({"ticker": tk, "level": "risk", "kind": "forensic_cap",
                          "text": f"{tk} forensic gate capping rating at {cap:g} — {str(gate.get('reason', ''))[:42]}"})
        cs = _num(b.get("catalyst_signal"))
        cats = b.get("catalysts") or []
        if cats and (cs or 0) > 0:
            head = str((cats[0] or {}).get("headline", "")).strip()
            if head:
                flags.append({"ticker": tk, "level": "warn", "kind": "catalyst",
                              "text": f"{tk} catalyst live — {head[:50]}"})
    # stale-feed flag (book-level) — only when the engine itself reports staleness
    fresh = state.get("data_freshness") or {}
    stale_feeds = [k for k, v in (fresh.get("feeds") or {}).items() if (v or {}).get("stale")]
    if stale_feeds:
        flags.append({"ticker": None, "level": "warn", "kind": "stale",
                      "text": "stale feeds: " + ", ".join(stale_feeds[:4])})
    return flags


def daily_brief() -> dict:
    """The day-opener: the shared situational frame (regime · posture · rated book · recent memory)
    PLUS the actionable layer — per-name flags worth your eyes today (BELOW REP floor, a binding
    forensic cap, a near-term catalyst, a stale feed). This is the agent-callable sibling of the
    cockpit's SessionStart brief; the same engine /state, grounded-or-silent. Call it to open the
    day, or after a regime move, before deciding what to look at. Returns {ok, text, flags, ...}."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import world_state
    except Exception as e:
        return {"ok": False, "error": f"world_state unavailable: {e}"}
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=2.0)
    except Exception:
        return {"ok": False, "engine_running": False,
                "hint": "Start the engine with run_engine(action='start') — no live numbers until then."}
    try:
        recent_mem = _living_memory().query(limit=5)
    except Exception:
        recent_mem = []
    conv = state.get("conviction_mode") or {}
    cal_prior = _calibration_prior([b.get("archetype") for b in (conv.get("baskets") or [])])
    world = world_state.build(state, recent_memory=recent_mem, calibration=cal_prior)
    flags = _brief_flags(state)
    lines = [world_state.render_brief(world)]
    if flags:
        lines.append("## TODAY — what's worth your eyes")
        for f in flags:
            mark = {"good": "✓", "risk": "⚠", "warn": "•", "info": "·"}.get(f["level"], "·")
            lines.append(f"- {mark} {f['text']}")
    else:
        lines.append("## TODAY — no name-level flags; book is quiet.")
    return {"ok": True, "text": "\n".join(lines), "flags": flags,
            "regime": world.get("regime"), "top_pick": conv.get("top_pick"),
            "pipeline": world.get("pipeline")}


def get_ingestion_status() -> dict:
    """Freshness + per-source status of the open-source ingestion cache."""
    if not INGESTION_CACHE.exists():
        return {"cache_present": False,
                "path": str(INGESTION_CACHE.relative_to(REPO_ROOT)),
                "hint": "No cache yet — run_ingestion(force=true) to build it."}
    env = json.loads(INGESTION_CACHE.read_text())
    generated = env.get("generated_at")
    ttl = env.get("ttl_seconds")
    stale = None
    if isinstance(generated, (int, float)) and isinstance(ttl, (int, float)):
        stale = (time.time() - generated) > ttl
    data = env.get("data", {})
    return {"cache_present": True,
            "path": str(INGESTION_CACHE.relative_to(REPO_ROOT)),
            "schema_version": env.get("schema_version"),
            "generated_at": generated, "ttl_seconds": ttl, "stale": stale,
            "sources": env.get("sources", {}),
            "tickers": sorted((data.get("tickers") or {}).keys()),
            "has_macro": bool(data.get("macro"))}


def get_glossary(key: str | None = None) -> dict:
    """Rating glossary (T/Q/V pillars, JSF, runway, …) — the dashboard's source of truth."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from asymmetry_rating import ASYMMETRY_GLOSSARY, tooltip_text  # type: ignore
    except Exception as exc:  # heavy deps (numpy/pandas) may be missing
        return {"error": f"could not import glossary ({exc}). "
                         f"Install requirements.txt in this environment."}
    if key:
        entry = ASYMMETRY_GLOSSARY.get(key)
        if not entry:
            return {"error": f"unknown glossary key: {key}",
                    "keys": sorted(ASYMMETRY_GLOSSARY.keys())}
        return {"key": key, **entry, "tooltip": tooltip_text(key)}
    return {"count": len(ASYMMETRY_GLOSSARY),
            "entries": {k: v.get("what", "") for k, v in ASYMMETRY_GLOSSARY.items()}}


# Curated, safe slice of v5_config.json (the file has no secrets, but a 30 KB
# dump is wasteful — these are the values a collaborating model actually needs).
_CONFIG_HEADLINE_KEYS = (
    "target_capital", "friction_drag", "conservatism_scalar",
    "discovery_multiple", "rov_default",
)
_CONFIG_SECTIONS = (
    "portfolio_metadata", "directive_thresholds", "conviction_mode",
    "archetype_routing", "catalyst_probabilities", "forensic_thresholds",
    "health_radar", "ingestion", "scenarios", "structural_weights",
)


def get_config_values(section: str | None = None) -> dict:
    """Key configuration from ``v5_config.json``. Pass a *section* for its full contents."""
    if not CONFIG_PATH.exists():
        return {"error": "v5_config.json not found in repo root."}
    cfg = json.loads(CONFIG_PATH.read_text())
    if section:
        if section not in cfg:
            return {"error": f"unknown section: {section}",
                    "available_sections": [k for k in cfg if isinstance(cfg[k], (dict, list))]}
        return {"section": section, "value": cfg[section]}
    tickers = [t for t in cfg.get("portfolio_metadata", {}) if not t.startswith("_")]
    return {
        "headline": {k: cfg.get(k) for k in _CONFIG_HEADLINE_KEYS if k in cfg},
        "tickers": tickers,
        "directive_thresholds": cfg.get("directive_thresholds"),
        "available_sections": [s for s in _CONFIG_SECTIONS if s in cfg],
        "all_top_level_keys": list(cfg.keys()),
        "note": "Call get_config_values(section=...) for a section's full contents.",
    }


def get_project_overview() -> dict:
    """One-shot orientation for a model new to this repo (architecture + entrypoints)."""
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=20)["output"]
    return {
        "project": "CommodityEx Quant Monitor v5.3 (resource-portfolio-terminal)",
        "summary": ("Valuation/sizing engine for a concentrated junior mining + "
                    "royalty book. Cash-flow-lifecycle archetypes drive a T/Q/V "
                    "Conviction rating; a forensic 'JSF' survival sieve gates it."),
        "architecture": [
            "engine.py        — FastAPI app (uvicorn :8000). Builds terminal_state, serves GET /state and /ws.",
            "dashboard.py     — Streamlit UI (:8501). Reads the engine's /state feed.",
            "ingestion_pipeline.py — open-source data adapters -> data/ingestion_cache.json (CLI: --force).",
            "archetypes.py    — Polymorphic Archetype Factory (5 cash-flow archetypes).",
            "asymmetry_rating.py — Conviction-Mode T/Q/V rating + ASYMMETRY_GLOSSARY.",
            "catalyst_engine.py   — catalyst feeds -> data/catalysts.json.",
            "v5_config.json   — all tunables (git-ignored, local-only).",
        ],
        "run": {
            "engine": "python engine.py            (or MCP run_engine)",
            "dashboard": "streamlit run dashboard.py (or MCP run_dashboard)",
            "tests": "python -m pytest -q          (or MCP run_tests)",
            "ingestion": "python ingestion_pipeline.py --force (or MCP run_ingestion)",
        },
        "tickers": ["AGA.V", "GROY", "GMX.TO", "URC.TO"],
        "current_branch": branch,
        "docs": ["ENGINE_DESIGN.md", "PHASE7_CONVICTION_MODE.md",
                 "PHASE6_INGESTION.md", "PHASE8_CATALYSTS.md", "METRIC_COMPASS.md"],
    }


# --------------------------------------------------------------------------- #
# 5. Prompt helper — refine a rough ask into a Claude Code prompt (local, no API)
# --------------------------------------------------------------------------- #

_MODE_CHECKLISTS = {
    "implement": [
        "Make the smallest change that fully satisfies the request; match surrounding style.",
        "Run the relevant tests (MCP run_tests) and report pass/fail before claiming done.",
        "Develop on the designated feature branch; commit with a clear message; do not push unless asked.",
    ],
    "debug": [
        "Reproduce the failure first (run_tests or run_engine) and quote the actual error.",
        "Find the root cause before editing; explain it in one or two sentences.",
        "Add or adjust a test that would have caught the bug; then verify it passes.",
    ],
    "review": [
        "Read the diff (git_diff) and the touched files end to end before commenting.",
        "Flag correctness bugs first, then simplifications; cite file:line for each finding.",
        "Do not restate the obvious — only surface what genuinely needs attention.",
    ],
    "explain": [
        "Ground every claim in specific files/functions (use read_file); cite file:line.",
        "State what you verified vs. what you inferred.",
        "Be concise; lead with the answer, then the supporting detail.",
    ],
}


def improve_prompt_for_claude(task: str, context: str | None = None,
                              files: str | None = None, mode: str = "implement") -> dict:
    """Refine a rough request (e.g. from Gemini/Grok) into a high-quality Claude Code prompt.

    Pure local string-building — no API calls. Injects this repo's orientation,
    explicit constraints, file references and a mode-specific acceptance checklist
    so the receiving Claude Code session needs far less back-and-forth.
    """
    if not task or not task.strip():
        raise SafetyError("task is required")
    mode = mode.lower() if mode and mode.lower() in _MODE_CHECKLISTS else "implement"
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=20)["output"] or "the feature branch"
    file_list = [f.strip() for f in (files or "").split(",") if f.strip()]

    lines: list[str] = []
    lines.append(f"# Task ({mode})")
    lines.append(task.strip())
    lines.append("")
    lines.append("## Repository context")
    lines.append("CommodityEx Quant Monitor v5.3 (resource-portfolio-terminal): a Python valuation/")
    lines.append("sizing engine for a concentrated junior-mining + royalty book.")
    lines.append("- engine.py serves terminal_state over FastAPI (:8000 /state); dashboard.py is a")
    lines.append("  Streamlit UI that reads it; ingestion_pipeline.py (--force) refreshes the data cache.")
    lines.append("- Rating logic: asymmetry_rating.py (T/Q/V Conviction) + archetypes.py; tests are test_*.py.")
    if context and context.strip():
        lines.append("")
        lines.append("## Additional context")
        lines.append(context.strip())
    if file_list:
        lines.append("")
        lines.append("## Likely files to read first")
        for f in file_list:
            lines.append(f"- {f}")
    lines.append("")
    lines.append("## Constraints & definition of done")
    for item in _MODE_CHECKLISTS[mode]:
        lines.append(f"- {item}")
    lines.append(f"- Work on branch `{branch}`.")
    lines.append("- Do not modify or commit v5_config.json, FRED_API_KEY, or any *.env / secret.")
    lines.append("- Prefer the MCP tools (read_file, run_tests, git_diff) over manual copy-paste.")

    refined = "\n".join(lines)
    return {"mode": mode, "branch": branch, "refined_prompt": refined,
            "usage": "Paste 'refined_prompt' into Claude Code (or another MCP client) as the task."}
