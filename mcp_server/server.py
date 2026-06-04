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


@mcp.tool()
def pin_insight(ticker: str, note: str, badge: str = "✦", level: str = "info") -> dict:
    """Leave a persistent visual badge + note on a ticker in the cockpit (Book + Watchlist + Notes).
    level: info | good | warn | risk (colour). Use after a real, tool-grounded finding — e.g. a
    verified catalyst, a forensic flag, a regime tailwind — so the analyst sees it at a glance."""
    return core.pin_insight(ticker, note, badge, level)


@mcp.tool()
def highlight_ticker(ticker: str, reason: str, level: str = "info", ttl: int = 90) -> dict:
    """Transiently draw the eye to a ticker with a one-line reason (auto-expires after ttl seconds)."""
    return core.highlight_ticker(ticker, reason, level, ttl)


@mcp.tool()
def clear_insight(ticker: str = "") -> dict:
    """Remove agent badges/notes for a ticker (or all names if ticker is empty)."""
    return core.clear_insight(ticker)


@mcp.tool()
def switch_tab(tab: str) -> dict:
    """Switch the cockpit's main view so the analyst lands where your analysis applies.
    tab: book | whatif | regime | dossier."""
    return core.switch_tab(tab)


@mcp.tool()
def get_fundamentals(ticker: str) -> dict:
    """FMP fundamentals snapshot (price, market cap, beta, 52-wk range, volume, sector, exchange),
    engine-cached and daily-budget-capped so repeats are free. FMP free tier has NO news/catalysts —
    use WebSearch/WebFetch straight-to-source (issuer PR / SEDAR+ / EDGAR) for those."""
    return core.get_fundamentals(ticker)


@mcp.tool()
def get_treasury_curve() -> dict:
    """Latest US Treasury curve (1mo…30yr) via FMP, engine-cached 6h — one call covers every tenor."""
    return core.get_treasury_curve()


@mcp.tool()
def apply_scenario(scenario: str = "", overrides: str = "", ticker: str = "", to_book: bool = False) -> dict:
    """Run a what-if visibly in the Live What-If tab. Pass a saved `scenario` name or raw `overrides`
    (e.g. 'silver=+5 ry=-0.5 peer=+20%'); optional `ticker` focuses the name first. The cockpit fills
    the override line, switches to the tab, and runs it — the analyst sees your scenario, not just text."""
    return core.apply_scenario(scenario, overrides, ticker, to_book)


# ---- Dynamic configuration (cockpit-editable tunables; engine-backed) ----- #

@mcp.tool()
def list_params() -> dict:
    """List editable tunables: effective value, default, allowed range, and whether overridden."""
    return core.list_params()


@mcp.tool()
def set_param(key: str, value: float, confirm: bool = False) -> dict:
    """Set a tunable override directly (needs confirm=true). Prefer propose_param_change for agents."""
    return core.set_param(key, value, confirm)


@mcp.tool()
def propose_param_change(key: str, value: float, reason: str) -> dict:
    """Propose a tunable change WITH reasoning -> pending queue; a human confirms before it applies."""
    return core.propose_param_change(key, value, reason)


@mcp.tool()
def list_pending_changes() -> dict:
    """List proposed-but-unconfirmed config changes (key, value, reason, who)."""
    return core.list_pending_changes()


@mcp.tool()
def confirm_param_change(change_id: int) -> dict:
    """Apply a pending proposed config change by id (the human confirmation step)."""
    return core.confirm_param_change(change_id)


@mcp.tool()
def save_scenario(name: str, overrides: str) -> dict:
    """Save a named what-if scenario (overrides like 'silver=+5 ry=-0.5'); load via run_valuation_whatif(ticker, name)."""
    return core.save_scenario(name, overrides)


@mcp.tool()
def list_scenarios() -> dict:
    """List saved what-if scenarios and their override knobs."""
    return core.list_scenarios()


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
