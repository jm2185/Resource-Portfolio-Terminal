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
def pipeline_event(stage: str = "", message: str = "", status: str = "running",
                   ticker: str = "", verdict: str = "", result: str = "", theme: str = "") -> dict:
    """Post a research-pipeline status update -> the cockpit's PIPELINE panel (so the desk sees the
    background run progress while the user keeps working). Call at each transition:
    stage ∈ scout|synthesis|verifier|done ; status ∈ running|done|error ; pass ticker+verdict for a
    per-name result (APPROVE/CONDITIONAL/REJECT), result=<final summary> on done."""
    return core.pipeline_event(stage, message, status, ticker, verdict, result, theme)


@mcp.tool()
def get_pipeline_status() -> dict:
    """Current background-pipeline status (theme, stage, per-name verdicts, recent events)."""
    return core.get_pipeline_status()


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
def set_barbell_weights(weights: dict, reason: str = "") -> dict:
    """Rebalance the book sleeve weights (e.g. after cutting a holding) — a validated vector
    (sum-to-1, 60% AGA spear ceiling), filed as a PROPOSAL for the operator's /confirm, then
    hot-reloaded. Example after cutting URC: {"AGA.V": 0.60, "GROY": 0.24, "GMX.TO": 0.16}."""
    return core.set_barbell_weights(weights, reason)


@mcp.tool()
def cut_holding(ticker: str, reason: str = "") -> dict:
    """Cut a book holding to 0% and redistribute its weight across the survivors pro-rata (AGA.V
    capped at the 60% spear ceiling). Filed as a PROPOSAL for the operator's /confirm — reflect a
    rotation (e.g. cut URC.TO) without editing config."""
    return core.cut_holding(ticker, reason)


@mcp.tool()
def set_nav(ticker: str, nav_per_share: float, source_url: str,
            as_of: str = "", confidence: str = "med") -> dict:
    """Set a SOURCED per-share NAV for a ballast holding so its fair value stops anchoring on the
    understated accounting book (fixes the holdco/royalty 'negative upside' / 'below floor'
    artifact, e.g. GMX's -59%). A source_url is required; effective next eval cycle."""
    return core.set_nav(ticker, nav_per_share, source_url, as_of, confidence)


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
    """Live Conviction-Mode T/Q/V ratings + directives from the running engine's /state.
    Now surfaces the full asymmetry the Dialectic Council debates: per name the rho (payoff ratio),
    phi (floor coverage), upside/downside legs, the commodity-aware tailwind decomposition, the JSF
    gate (cap + reason), confidence ribbon, price ladder, and taxonomy (archetype/subarchetype)."""
    return core.get_conviction_ratings()


@mcp.tool()
def correlation_check(ticker: str = "", candidate: str = "") -> dict:
    """Second thesis, or one bet with extra commissions? The conventional-core independence/role check.
    candidate="EEFT" → PRE-ADD screen from the cached close store: rho of the candidate to the spear and
    the book → INDEPENDENT / PARTIAL / REDUNDANT (the "different reasons" test that screens redundant
    leveraged-steepener duplicates OUT). No candidate → the HELD-BOOK monitor from /state: each sleeve's
    rho to the spear + the 60d->120d drift trend, lane-aware. ticker= focuses one held name. Read-only;
    MEASURES, never sizes."""
    return core.correlation_check(ticker=ticker, candidate=candidate)


@mcp.tool()
def dual_sided_valuation(ticker: str, inputs_json: str = "") -> dict:
    """Dual-sided conventional-equity valuation: BOTH lenses — compounder (reverse-DCF/expectations) and
    deep-value (SOTP + asset/FCF floor) — reconciled to the divergence spread (premium-franchise /
    mispricing-flag / converged) + the lead lens. inputs_json = the underwriting payload (price,
    shares_out, net_debt, fcf, wacc, cap_years, growth{p10,p50,p90}, segments[{name,value,multiple,
    bull_multiple}], nav_per_share, swing_segment, quality, management_score, regime_alpha). Price is
    enriched from FMP when absent. Swing probabilities are ASSERTED (n=0) until the base-rate seed. For
    conventional-lane names — priced, not scouted/councilled (the lane guard)."""
    return core.dual_sided_valuation(ticker=ticker, inputs_json=inputs_json)


@mcp.tool()
def narrative_check(ticker: str, claims_json: str = "", lens: str = "", archetype: str = "") -> dict:
    """Narrative-Integrity (NIS): does a management turnaround narrative have RECEIPTS or is it hand-
    waving? claims_json = JSON array of {claim, receipt, trend (improving/flat/deteriorating), source,
    kind, area?, risk?}. Returns the 0-1 integrity score, per-claim verdicts (confirmed/partial/
    unsupported/broken), the live RISK LOCUS (where pressure relocated — the Euronet->Ria lesson), and
    narrative_break flags. Fail-closed: no receipt => unsupported. Grades an OPERATING turnaround (JSF
    grades accounting; the catalyst-verifier grades resource catalysts)."""
    return core.narrative_check(ticker=ticker, claims_json=claims_json, lens=lens, archetype=archetype)


@mcp.tool()
def memory_write(type: str, text: str = "", ticker: str = "", tags: str = "",
                 source: str = "agent", meta_json: str = "", refs: str = "") -> dict:
    """Append a typed entry to Living Memory (the cockpit's shared, append-only research record).
    type in: note, thesis, decision, council_verdict, scenario_prior, regime_snapshot, outcome,
    catalyst, pin. Immutable + human-readable + git-versioned (the audit trail). tags comma-sep;
    meta_json optional structured payload. Captures the live engine regime context automatically."""
    return core.memory_write(type=type, text=text, ticker=ticker, tags=tags,
                             source=source, meta_json=meta_json, refs=refs)


@mcp.tool()
def memory_query(ticker: str = "", type: str = "", tag: str = "", contains: str = "",
                 regime_like: bool = False, limit: int = 20) -> dict:
    """Recall from Living Memory (filters AND together, newest-first, superseded hidden). Set
    regime_like=true to keep only entries captured under a regime similar to TODAY's — i.e. "how did
    this name / these archetypes behave under a regime like this one before?"."""
    return core.memory_query(ticker=ticker, type=type, tag=tag, contains=contains,
                             regime_like=regime_like, limit=limit)


@mcp.tool()
def get_world_state() -> dict:
    """One situational-awareness snapshot to ground an agent — regime + posture, the operator's
    focus + recent terminal actions, the book's verdicts, recent Living Memory. Call ONCE at the
    start instead of stitching get_conviction_ratings + memory_query + get_ui_context. {world, brief}."""
    return core.get_world_state()


@mcp.tool()
def daily_brief() -> dict:
    """The day-opener: the shared situational frame (regime · posture · rated book · recent memory)
    PLUS the actionable layer — per-name flags worth the operator's eyes today (BELOW REP floor,
    a binding forensic cap, a near-term catalyst, a stale feed). The agent-callable sibling of the
    cockpit's SessionStart brief; same engine /state, grounded-or-silent. Returns {ok, text, flags}."""
    return core.daily_brief()


@mcp.tool()
def record_decision(ticker: str, verdict: str = "") -> dict:
    """Freeze a structured DECISION (legs, rho, phi, JSF cap, archetype, price-at-decision) into
    Living Memory so it can later be graded against reality. Reads the live engine rating."""
    return core.record_decision(ticker=ticker, verdict=verdict)


@mcp.tool()
def record_outcome(ticker: str, realized_price: float, horizon_days: int = 90) -> dict:
    """Grade the latest frozen decision for a name against a realized price at a horizon and write the
    scored OUTCOME (leg hit, realized vs projected-bull return, upside capture, floor held) to Memory."""
    return core.record_outcome(ticker=ticker, realized_price=realized_price, horizon_days=horizon_days)


@mcp.tool()
def record_conviction(ticker: str, confidence: float, basis: str = "") -> dict:
    """H5 Conviction Book — log a live confidence reading (0–100% or a 0–1 fraction) on an open thesis,
    updated as evidence lands. Each reading is immutable and linked to the name's open decision, so the
    forecast TRAIL is Brier-scored at close (was your confidence honest, not just your direction?).
    Refuses if no decision is frozen for the name (record_decision first)."""
    return core.record_conviction(ticker=ticker, confidence=confidence, basis=basis)


@mcp.tool()
def conviction_book() -> dict:
    """H5 — the Conviction Book: every OPEN thesis with its live confidence, forecast-trail length and
    how confidence has moved, plus the book-level Brier calibration over closed theses (was the desk's
    confidence honest?). Read-only."""
    return core.conviction_book()


@mcp.tool()
def calibration_scorecard(by_archetype: bool = True) -> dict:
    """The expectancy scorecard over closed decisions — the Druckenmiller objective (slugging,
    expectancy, upside capture, downside containment); hit-rate demoted. Optionally split by archetype."""
    return core.calibration_scorecard(by_archetype=by_archetype)


@mcp.tool()
def sweep_outcomes(horizon_days: int = 90) -> dict:
    """Close every open decision that has reached its horizon, grading it at the current mark — the
    'record at horizon' half of the capture loop (run on a schedule or from /journal). Idempotent:
    already-graded decisions are skipped; names with no fresh price stay open. Feeds the calibration
    path/decision-quality/spear surfaces with real data."""
    return core.sweep_outcomes(horizon_days=horizon_days)


@mcp.tool()
def backfill_decisions(verdict: str = "") -> dict:
    """Prime the calibration loop: freeze an open decision for each current holding that lacks one, from
    the live book — so the flywheel starts accumulating now instead of from the next council verdict."""
    return core.backfill_decisions(verdict=verdict)


@mcp.tool()
def candidate_base_rate(archetype: str = "", sleeve: str = "", stage: str = "",
                        commodity: str = "") -> dict:
    """Reference-class base rate for a discovery candidate's archetype or sleeve (spear/ballast) — the
    OUTSIDE view (@scout/@synthesis anchor a candidate's score to this, not score in a vacuum). Pass
    ``stage`` (grassroots/pea/pfs/fs/construction) to condition on the candidate's actual stage
    (Flyvbjerg chain) and ``commodity`` for the precious-metals tilt. Returns the published prior
    (estimate + CI + source + line, plus stage_conditional / takeout_class), or a note when none maps."""
    return core.candidate_base_rate(archetype=archetype, sleeve=sleeve, stage=stage, commodity=commodity)


@mcp.tool()
def story_card(ticker: str = "") -> dict:
    """Narrative→number Story Card for a holding (Damodaran): the intrinsic decomposed into its named
    legs (method + value), the drivers behind it, and the BREAKPOINT — the move to its kill-switch
    (intrinsic → price). Makes a valuation legible and gradeable. First-order commodity breakpoint."""
    return core.story_card(ticker=ticker)


# ---- Validation flywheel (valuation ledger · replay · discovery · graduation) ---- #

@mcp.tool()
def valuation_snapshot_now(ticker: str = "") -> dict:
    """Stamp a point-in-time valuation snapshot into the append-only valuation ledger NOW — one
    name, or the whole live book when ticker is empty. The engine loop stamps daily marks and
    material changes automatically; this is the explicit operator stamp (trigger=manual)."""
    return core.valuation_snapshot_now(ticker=ticker)


@mcp.tool()
def valuation_ledger_query(ticker: str = "", since: str = "", trigger: str = "",
                           limit: int = 20) -> dict:
    """Read the valuation ledger — every name's full valuation state stamped point-in-time
    (intrinsic, ladder, ρ/φ, band, directive, gate, the input provenance it rested on, regime).
    Filters AND together; newest first. Read-only — agents never write the ledger."""
    return core.valuation_ledger_query(ticker=ticker, since=since, trigger=trigger, limit=limit)


@mcp.tool()
def replay_grade(horizon_days: int = 90) -> dict:
    """Grade the valuation ledger against the cached price history at a horizon — the VALUATION
    track record: intrinsic→price convergence, band coverage (PIT), REP-floor reliability, with
    small-n honesty (event counts always; expectancy only when warm). Also returns the ledger-fed
    base-rate posteriors. This is the answer to 'show me the alpha'."""
    return core.replay_grade(horizon_days=horizon_days)


@mcp.tool()
def discovery_screen(slot: str, gates_json: str = "") -> dict:
    """Run the quantitative discovery screen over the maintained candidate universe — slot-fit
    FIRST (the thesis-slot mandate), then stage / jurisdiction / market-cap / survival /
    REP-floor-coverage hard gates, each kill logged with its reason. Survivors carry data_gaps +
    a stage-conditioned base-rate anchor. @scout enriches survivors; the screen is the funnel."""
    return core.run_discovery_screen(slot=slot, gates_json=gates_json)


@mcp.tool()
def add_candidate(ticker: str, vehicle: str = "", commodity: str = "", slot: str = "",
                  stage: str = "", source: str = "", name: str = "", fields_json: str = "") -> dict:
    """Register or update a name in the discovery universe (data/candidate_universe.json) — the
    scout→universe feedback loop, so a found name feeds the NEXT discovery_screen instead of only
    landing on the watchlist. Grounded-or-silent: a source is REQUIRED. Stores the identity fields
    the screen gates on (vehicle, commodity, stage, slot) + best-effort numeric screen inputs via
    fields_json (fraser_index, mcap_cad_m, runway_months, dilution_annual, cash_cad_m,
    stressed_in_ground_cad_m, ev_cad_m). Dedupes by ticker; returns whether it now survives its
    slot. SCREEN inputs only — graduation still requires @verifier/@anti-scout to source them."""
    return core.add_candidate(ticker=ticker, vehicle=vehicle, commodity=commodity, slot=slot,
                              stage=stage, source=source, name=name, fields_json=fields_json)


@mcp.tool()
def graduate_candidate(ticker: str, verifier_ref: str = "", anti_scout_ref: str = "",
                       forensic_ref: str = "") -> dict:
    """The MANDATORY disconfirmation gate: graduate a scout candidate to the watchlist ONLY with
    all three receipts in Living Memory — a @verifier verdict, an @anti-scout sweep (CLEAN counts),
    and the forensic/JSF result. Pass each entry id, or leave a ref blank to auto-resolve the
    latest Memory entry for this ticker TAGGED with the role (verifier / anti_scout / forensic) —
    so the one-action gauntlet graduates without hand-collecting ids. Refuses if any is missing."""
    return core.graduate_candidate(ticker=ticker, verifier_ref=verifier_ref,
                                   anti_scout_ref=anti_scout_ref, forensic_ref=forensic_ref)


@mcp.tool()
def promote_to_eval(ticker: str, archetype: str, inputs_json: str = "",
                    graduation_ref: str = "", confirm: bool = False) -> dict:
    """Promote a GRADUATED candidate into the engine's EVAL set so the engine actually RATES it
    (live price, archetype valuation, T-Q-V conviction score — hot-loaded next cycle) while it
    holds NO barbell weight and enters NO sizing: rated, not held. Human-gated twice: requires
    the graduation entry (verifier + anti-scout + forensic receipts) in Living Memory, and
    confirm=true (a dry call returns the exact write plan). inputs_json may carry metadata
    fields (type/stage/currency/thesis_slot/sector_tags/…), a 'ballast' anchor block
    (commodity/ref_price/spot_ref), and 'research' facts ({field: {value, source, as_of}} —
    provenance mandatory)."""
    return core.promote_to_eval(ticker=ticker, archetype=archetype, inputs_json=inputs_json,
                                graduation_ref=graduation_ref, confirm=confirm)


@mcp.tool()
def demote_from_eval(ticker: str, reason: str = "", confirm: bool = False) -> dict:
    """Remove a name from the engine's EVAL set (inverse of promote_to_eval). Refuses to touch a
    real book holding — only eval_only entries can go; rotations go through /rotate. Needs
    confirm=true; writes a demotion entry to Living Memory."""
    return core.demote_from_eval(ticker=ticker, reason=reason, confirm=confirm)


@mcp.tool()
def remove_holding(ticker: str, reason: str = "", confirm: bool = False) -> dict:
    """Fully DECOMMISSION a book holding (the clean inverse of holding it). Unlike cut_holding —
    which only zeroes the barbell weight via a reversible overlay — this removes the name from book
    MEMBERSHIP and every ticker-keyed config block (barbell_weights with AGA-capped redistribution,
    portfolio_metadata, ballast_multiples/valuation, archetype_barbell_weights, catalyst aliases),
    so no dormant residue is left. Refuses the spear (AGA.V), unknown tickers, eval-only names (use
    demote_from_eval), and a removal that would leave no ballast. Two-step: a dry call returns the
    write plan; confirm=true applies it (timestamped backup) and clears any stale barbell overlay.
    For a SWAP, run /rotate first. This is the 'cut a name without editing code' path."""
    return core.remove_holding(ticker=ticker, reason=reason, confirm=confirm)


@mcp.tool()
def sweep_scout_outcomes(horizon_days: int = 90) -> dict:
    """Close out scout candidates that reached their horizon at the cached daily-close mark — the
    decaying watch that gives DISCOVERY a track record (graduated vs killed vs regret). Returns
    the scout scorecard: hit-rate headlines here BY DESIGN (a funnel's objective is frequency);
    the book's scorecard keeps expectancy first."""
    return core.sweep_scout_outcomes(horizon_days=horizon_days)


# ---- Forge layer (M1 calendar · M2 thesis/ledger · M3 sentinel · M6 swap) ---- #

@mcp.tool()
def catalyst_write(kind: str, title: str, window_start: str, window_end: str = "",
                   ticker: str = "", macro_kind: str = "", confidence: str = "estimated",
                   source: str = "manual", source_url: str = "", status: str = "pending",
                   linked_thesis: str = "", notes: str = "") -> dict:
    """Add a catalyst WINDOW to the shared calendar. A catalyst is a window, not a point ('expected
    Q3' → [start,end]). kind: drill_result|assay|pea|pfs|fs|financing_window|royalty_payment|permit|
    macro. ticker empty ⇒ a macro event. Grounded-or-silent: pass source_url straight-to-source."""
    return core.catalyst_write(kind, title, window_start, window_end, ticker, macro_kind,
                               confidence, source, source_url, status, linked_thesis, notes)


@mcp.tool()
def catalyst_query(ticker: str = "", within_days: int = 30, kind: str = "",
                   status: str = "pending", include_macro: bool = False) -> dict:
    """Pending catalysts overlapping the next `within_days`. ticker empty ⇒ all names + macro;
    include_macro=true folds the macro tape into a named query (the cockpit's upcoming strip)."""
    return core.catalyst_query(ticker, within_days, kind, status, include_macro)


@mcp.tool()
def catalyst_seed_macro(horizon_days: int = 90) -> dict:
    """Seed the rule-deterministic recurring macro windows (COT/NFP scheduled, CPI estimated; FOMC
    never invented). Idempotent — safe on a schedule."""
    return core.catalyst_seed_macro(horizon_days)


@mcp.tool()
def thesis_write(ticker: str, thesis_json: str = "", stance: str = "CONDITIONAL") -> dict:
    """Persist an underwriting THESIS (intangibles + load-bearing claims[] + pre-commitment rules[]).
    VALIDATED at save: every rule trigger is parsed through the safe grammar, every engine claim
    type-checked — a bad rule is rejected with a clear error, never written. stance:
    APPROVE|CONDITIONAL|REJECT."""
    return core.thesis_write(ticker, thesis_json, stance)


@mcp.tool()
def get_ledger(stance: str = "") -> dict:
    """The Thesis Ledger — every thesis joined to its realized outcomes; graveyard (REJECTs) + hall
    of fame side by side. stance optionally filters APPROVE|CONDITIONAL|REJECT."""
    return core.get_ledger(stance)


@mcp.tool()
def sentinel_sweep(ticker: str = "", autonomy: str = "auto") -> dict:
    """Run the Sentinel across the held book (or one ticker): diff live state vs each frozen thesis →
    liquidity-runway, financing-window/death-spiral, thesis-integrity, fired pre-commitment rules.
    Writes a per-name SENTINEL status; AUTONOMOUSLY pins alert-level findings; trims/exits surface as
    PROPOSALS to acknowledge (never auto-acted). autonomy: auto|propose."""
    return core.sentinel_sweep(ticker, autonomy)


@mcp.tool()
def sentinel_ack(ticker: str, key: str, action: str = "ack", reason: str = "") -> dict:
    """Acknowledge a fired Sentinel tripwire (act|snooze|void) so it leaves the live queue and does
    not re-fire. Append-only — the record survives (audit trail)."""
    return core.sentinel_ack(ticker, key, action, reason)


@mcp.tool()
def council_swap(incumbent: str, challenger: str, regime_inflection: bool = False) -> dict:
    """Reconcile an UP-TIER (swap): challenger vs incumbent under the friction-adjusted hurdle +
    catalyst lock (friction from the incumbent's liquidity runway; lock from the shared calendar).
    Returns SWAP / REJECT / DEFER with the arithmetic shown."""
    return core.council_swap(incumbent, challenger, regime_inflection)


@mcp.tool()
def council_reconcile(ticker: str, bull_claims_json: str = "", bear_claims_json: str = "",
                      improving: bool = False) -> dict:
    """Reconcile Bull vs Bear into ONE verdict for a rated name via the DETERMINISTIC reconciler
    (council.reconcile) — the Arbiter runs the signal-coherence rules through the module instead of
    by feel. READ-ONLY: pulls live ρ/φ/gate/ladder/directive/posture, writes nothing. Claims are JSON
    arrays of {side,text,grounded,field,weight,invalidation,provenance}. To record the verdict (and
    fire the calibration capture-hook), call memory_write(type='council_verdict') after."""
    return core.council_reconcile(ticker, bull_claims_json, bear_claims_json, improving)


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
