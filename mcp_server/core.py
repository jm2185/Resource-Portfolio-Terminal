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
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

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
    """Set a tunable override directly (needs confirm=true). Agents should prefer
    propose_param_change so a human reviews the reasoning first."""
    if not confirm:
        return {"status": "needs_confirmation",
                "message": f"Set {key}={value}? Re-call with confirm=true, "
                           f"or use propose_param_change to route it through review."}
    try:
        return _http_post_json("/config/param", {"key": key, "value": value, "source": "cockpit"})
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

def get_conviction_ratings() -> dict:
    """Live Conviction-Mode ratings from the running engine's ``/state`` feed."""
    try:
        state = _http_get_json(f"{ENGINE_URL}/state", timeout=2.0)
    except Exception:
        return {"engine_running": False,
                "hint": "Start the engine with run_engine(action='start'), then retry.",
                "endpoint": f"{ENGINE_URL}/state"}
    conv = state.get("conviction_mode") or {}
    baskets = []
    for b in conv.get("baskets", []):
        baskets.append({k: b.get(k) for k in
                        ("ticker", "archetype", "rating", "band", "directive",
                         "T", "Q", "V", "conviction") if k in b})
    return {"engine_running": True, "status": state.get("status"),
            "mri": state.get("mri"), "context": conv.get("context", {}),
            "top_pick": conv.get("top_pick"), "baskets": baskets or conv.get("baskets", [])}


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
