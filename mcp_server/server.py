#!/usr/bin/env python3
"""
CommodityEx Quant Monitor v5.3 — local MCP server (Phase 1).

A thin FastMCP transport wrapper around ``core.py``. Exposes high-value tools and
project-state resources over stdio so subscription-based clients (Claude Code,
Cursor + Gemini, Grok, …) can collaborate on this repo with less manual
copy-paste. No API keys are required for the MCP layer itself.

Run directly:   python mcp_server/server.py      (speaks MCP over stdio)
Connect it from a client per mcp_server/README.md.

IMPORTANT: stdio transport uses *stdout* for the protocol. Never ``print()`` here —
diagnostics must go to stderr (logging is configured accordingly below).
"""

from __future__ import annotations

import logging
import os
import sys

# Make `import core` work no matter what directory the client launches us from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - guidance for first-time setup
    sys.stderr.write(
        "ERROR: the MCP SDK is not installed.\n"
        "  pip install -r mcp_server/requirements-mcp.txt\n"
    )
    raise

# All logging to stderr; stdout is reserved for the MCP protocol.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [cex-mcp] %(levelname)s %(message)s")
log = logging.getLogger("cex-mcp")

mcp = FastMCP("commodity-ex")

# --------------------------------------------------------------------------- #
# Tools — each is a 1:1 wrapper so FastMCP derives the schema from the signature.
# Return values are dicts (structured) which FastMCP serializes for the client.
# --------------------------------------------------------------------------- #


# ---- File operations (read-only reads; guarded writes) -------------------- #

@mcp.tool()
def list_files(subdir: str = ".", pattern: str = "*", recursive: bool = False) -> dict:
    """List files in the repo under `subdir` (glob `pattern`). Read-only, repo-scoped."""
    return core.list_files(subdir, pattern, recursive)


@mcp.tool()
def read_file(path: str, max_bytes: int = 100_000) -> dict:
    """Read a UTF-8 text file from inside the repo. Read-only; secrets are blocked."""
    return core.read_file(path, max_bytes)


@mcp.tool()
def edit_file(path: str, old_string: str, new_string: str, confirm: bool = False) -> dict:
    """Exact-string replace in a repo file (set confirm=true to apply; backs up first).
    Create a new file by passing old_string="" for a path that does not exist yet."""
    return core.edit_file(path, old_string, new_string, confirm)


# ---- Run commands --------------------------------------------------------- #

@mcp.tool()
def run_tests(target: str | None = None, timeout: int = 300) -> dict:
    """Run the test suite (pytest if present, else unittest). `target` narrows to one file."""
    return core.run_tests(target, timeout)


@mcp.tool()
def run_ingestion(force: bool = False, tickers: str | None = None,
                  providers: str | None = None, catalysts: bool = False,
                  sentiment: bool = False, verbose: bool = False) -> dict:
    """Refresh the open-source data cache via ingestion_pipeline.py. `force` bypasses TTL."""
    return core.run_ingestion(force, tickers, providers, catalysts, sentiment, verbose)


@mcp.tool()
def run_engine(action: str = "start", force_refresh: bool = False) -> dict:
    """Manage the FastAPI engine on :8000 (start|stop|status|restart). Serves /state.
    force_refresh runs ingestion --force before starting so it boots on fresh data."""
    return core.run_engine(action, force_refresh)


@mcp.tool()
def run_dashboard(action: str = "start") -> dict:
    """Manage the Streamlit dashboard on :8501 (start|stop|status|restart). Reads /state."""
    return core.run_dashboard(action)


@mcp.tool()
def run_valuation_whatif(ticker: str = "", overrides: str = "") -> dict:
    """Scenario what-if: revalue a holding under overrides (e.g. "silver=+5 ry=-0.5 peer=+20%").
    Knobs: silver/ag, gold, ry, vol, peer, mri, dxy. Leave ticker empty to use the GUI's focused
    name. Returns base vs scenario intrinsic + upside via the engine's shared /action/whatif route."""
    return core.run_valuation_whatif(ticker, overrides)


@mcp.tool()
def get_ui_context() -> dict:
    """What the GUI (Flutter) is currently showing — focused ticker / view / scenario / visible
    tickers / selected what-if — so you can ground analysis in the user's on-screen context. Read-only."""
    return core.get_ui_context()


@mcp.tool()
def send_ui_command(action: str, ticker: str = "", view: str = "", scenario: str = "") -> dict:
    """Steer the GUI. action: focus | view | scenario | highlight | alert (pass ticker/view/scenario
    as relevant). Use only to follow the user's request. Flutter picks it up over /ws."""
    return core.send_ui_command(action, ticker, view, scenario)


# ---- Git helpers ---------------------------------------------------------- #

@mcp.tool()
def git_status() -> dict:
    """Current branch and short working-tree status. Read-only."""
    return core.git_status()


@mcp.tool()
def git_diff(path: str | None = None, staged: bool = False) -> dict:
    """Unified diff of the working tree (or the index with staged=true). Read-only."""
    return core.git_diff(path, staged)


@mcp.tool()
def git_commit(message: str, add_all: bool = False, paths: str | None = None,
               confirm: bool = False) -> dict:
    """Stage and commit (set confirm=true). Never pushes; refuses protected/secret files."""
    return core.git_commit(message, add_all, paths, confirm)


# ---- Project state (also exposed as resources below) ---------------------- #

@mcp.tool()
def get_conviction_ratings() -> dict:
    """Live Conviction-Mode T/Q/V ratings + directives from the running engine's /state."""
    return core.get_conviction_ratings()


@mcp.tool()
def get_ingestion_status() -> dict:
    """Freshness and per-source status of data/ingestion_cache.json."""
    return core.get_ingestion_status()


@mcp.tool()
def get_glossary(key: str | None = None) -> dict:
    """Rating glossary (T/Q/V, JSF, runway, …). Pass a `key` for one term's full entry."""
    return core.get_glossary(key)


@mcp.tool()
def get_config_values(section: str | None = None) -> dict:
    """Key values from v5_config.json. Pass a `section` name for its full contents."""
    return core.get_config_values(section)


@mcp.tool()
def get_project_overview() -> dict:
    """One-shot orientation: architecture, entrypoints, tickers, current branch."""
    return core.get_project_overview()


# ---- Prompt helper -------------------------------------------------------- #

@mcp.tool()
def improve_prompt_for_claude(task: str, context: str | None = None,
                              files: str | None = None, mode: str = "implement") -> dict:
    """Refine a rough request into a high-quality Claude Code prompt (local, no API).
    mode: implement | debug | review | explain. `files` is a comma-separated hint list."""
    return core.improve_prompt_for_claude(task, context, files, mode)


# --------------------------------------------------------------------------- #
# Resources — same providers, for resource-aware clients (e.g. Claude Desktop).
# Tool-only clients (Cursor, etc.) still reach everything through the tools above.
# --------------------------------------------------------------------------- #

def _json(obj) -> str:
    import json
    return json.dumps(obj, indent=2, default=str)


@mcp.resource("cex://overview")
def res_overview() -> str:
    """Project orientation (architecture, entrypoints, tickers)."""
    return _json(core.get_project_overview())


@mcp.resource("cex://conviction")
def res_conviction() -> str:
    """Live Conviction-Mode ratings from the engine."""
    return _json(core.get_conviction_ratings())


@mcp.resource("cex://ingestion")
def res_ingestion() -> str:
    """Latest ingestion cache freshness/status."""
    return _json(core.get_ingestion_status())


@mcp.resource("cex://glossary")
def res_glossary() -> str:
    """Rating glossary (T/Q/V pillars and survival metrics)."""
    return _json(core.get_glossary())


@mcp.resource("cex://config")
def res_config() -> str:
    """Key configuration values from v5_config.json."""
    return _json(core.get_config_values())


if __name__ == "__main__":
    log.info("Starting CommodityEx MCP server (repo=%s, readonly=%s)",
             core.REPO_ROOT, core.READONLY)
    mcp.run()  # stdio transport by default
