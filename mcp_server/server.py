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
# Tools.
#
# Almost every tool is a pure pass-through of the identically named ``core``
# function, so we register those directly: FastMCP derives each tool's name,
# parameter schema, and description from the core function's signature and
# docstring (which are the canonical, curated versions).
#
# Only the handful of tools whose MCP-facing signature intentionally DIFFERS
# from core's (hidden internal knobs, a relaxed default) keep explicit wrapper
# functions below — see "Adapter wrappers".
#
# Return values are dicts (structured) which FastMCP serializes for the client.
# --------------------------------------------------------------------------- #

# Pure pass-throughs: tool name == core function name; schema + description come
# straight from core.  Keep this list in registration (display) order.
_PASSTHROUGH_TOOLS: tuple[str, ...] = (
    # -- File operations (read-only reads; guarded writes) --
    "read_file",
    "edit_file",
    # -- Run commands --
    "run_tests",
    "run_engine",
    # -- Cockpit / GUI steering --
    "get_ui_context",
    "send_ui_command",
    "pin_insight",
    "highlight_ticker",
    "clear_insight",
    "switch_tab",
    "get_fundamentals",
    "get_treasury_curve",
    "pipeline_event",
    "get_pipeline_status",
    "apply_scenario",
    # -- PREDICT arb scanner (Wealthsimple Predict / Kalshi) --
    "predict_scan",
    "predict_opportunities",
    "predict_fair_value",
    # -- Dynamic configuration (cockpit-editable tunables; engine-backed) --
    "list_params",
    "set_param",
    "propose_param_change",
    "set_barbell_weights",
    "cut_holding",
    "set_nav",
    "list_pending_changes",
    "confirm_param_change",
    "save_scenario",
    "list_scenarios",
    # -- Git helpers --
    "git_status",
    "git_commit",
    # -- Project state / analysis --
    "correlation_check",
    "dual_sided_valuation",
    "narrative_check",
    "memory_write",
    "memory_query",
    "get_world_state",
    "daily_brief",
    "record_outcome",
    "conviction_book",
    "calibration_scorecard",
    "sweep_outcomes",
    "backfill_decisions",
    "candidate_base_rate",
    "story_card",
    # -- Validation flywheel (valuation ledger · replay · discovery · graduation) --
    "valuation_snapshot_now",
    "valuation_ledger_query",
    "replay_grade",
    "add_candidate",
    "graduate_candidate",
    "promote_to_eval",
    "demote_from_eval",
    "remove_holding",
    "sweep_scout_outcomes",
    # -- Forge layer (M1 calendar · M2 thesis/ledger · M3 sentinel · M6 swap) --
    "catalyst_write",
    "catalyst_query",
    "catalyst_seed_macro",
    "thesis_write",
    "thesis_claim_set",
    "get_ledger",
    "sentinel_sweep",
    "sentinel_ack",
    "council_swap",
    "council_reconcile",
    # -- Status / reference --
    "get_ingestion_status",
    "get_glossary",
    "get_config_values",
    "get_project_overview",
    # -- Prompt helper --
    "improve_prompt_for_claude",
)

for _name in _PASSTHROUGH_TOOLS:
    mcp.tool()(getattr(core, _name))


# --------------------------------------------------------------------------- #
# Adapter wrappers — the MCP-facing signature intentionally differs from core's
# (internal knobs hidden from clients, a relaxed default, or a renamed core
# function). Do NOT collapse these into the pass-through list: FastMCP would
# expose core's full signature (or the wrong name/schema title).
# --------------------------------------------------------------------------- #

@mcp.tool()
def discovery_screen(slot: str, gates_json: str = "") -> dict:
    """Run the quantitative discovery screen over the maintained candidate universe — slot-fit
    FIRST (the thesis-slot mandate), then stage / jurisdiction / market-cap / survival /
    REP-floor-coverage hard gates, each kill logged with its reason. Survivors carry data_gaps +
    a stage-conditioned base-rate anchor. @scout enriches survivors; the screen is the funnel."""
    return core.run_discovery_screen(slot=slot, gates_json=gates_json)  # renamed core fn

@mcp.tool()
def list_files(subdir: str = ".", pattern: str = "*", recursive: bool = False) -> dict:
    """List files in the repo under `subdir` (glob `pattern`). Read-only, repo-scoped."""
    return core.list_files(subdir, pattern, recursive)  # hides core's `limit` knob


@mcp.tool()
def run_ingestion(force: bool = False, tickers: str | None = None,
                  providers: str | None = None, catalysts: bool = False,
                  sentiment: bool = False, verbose: bool = False) -> dict:
    """Refresh the open-source data cache via ingestion_pipeline.py. `force` bypasses TTL."""
    return core.run_ingestion(force, tickers, providers, catalysts, sentiment, verbose)  # hides `timeout`


@mcp.tool()
def run_valuation_whatif(ticker: str = "", overrides: str = "") -> dict:
    """Scenario what-if: revalue a holding under overrides (e.g. "silver=+5 ry=-0.5 peer=+20%").
    Knobs: silver/ag, gold, ry, vol, peer, mri, dxy. Leave ticker empty to use the GUI's focused
    name. Returns base vs scenario intrinsic + upside via the engine's shared /action/whatif route."""
    return core.run_valuation_whatif(ticker, overrides)  # relaxes core's required `ticker`


@mcp.tool()
def git_diff(path: str | None = None, staged: bool = False) -> dict:
    """Unified diff of the working tree (or the index with staged=true). Read-only."""
    return core.git_diff(path, staged)  # hides core's `max_chars` knob


@mcp.tool()
def get_conviction_ratings() -> dict:
    """Live Conviction-Mode T/Q/V ratings + directives from the running engine's /state.
    Now surfaces the full asymmetry the Dialectic Council debates: per name the rho (payoff ratio),
    phi (floor coverage), upside/downside legs, the commodity-aware tailwind decomposition, the JSF
    gate (cap + reason), confidence ribbon, price ladder, and taxonomy (archetype/subarchetype)."""
    return core.get_conviction_ratings()  # hides `with_calibration` (internal capture callers)


@mcp.tool()
def record_decision(ticker: str, verdict: str = "") -> dict:
    """Freeze a structured DECISION (legs, rho, phi, JSF cap, archetype, price-at-decision) into
    Living Memory so it can later be graded against reality. Reads the live engine rating."""
    return core.record_decision(ticker=ticker, verdict=verdict)  # hides `source` attribution


@mcp.tool()
def record_conviction(ticker: str, confidence: float, basis: str = "") -> dict:
    """H5 Conviction Book — log a live confidence reading (0–100% or a 0–1 fraction) on an open thesis,
    updated as evidence lands. Each reading is immutable and linked to the name's open decision, so the
    forecast TRAIL is Brier-scored at close (was your confidence honest, not just your direction?).
    Refuses if no decision is frozen for the name (record_decision first)."""
    return core.record_conviction(ticker=ticker, confidence=confidence, basis=basis)  # hides `source`


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
