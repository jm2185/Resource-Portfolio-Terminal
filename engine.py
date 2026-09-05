"""
Layout Changes Summary:
Condensation approach for the v5.1 Professional Educational Terminal:
- Introduced `metric_metadata` dictionary into the terminal state within the orchestrator (`CommodityExMonitor.__init__`).
- This dictionary populates the new "Metric Compass" panel and inline educational tooltips across the frontends (Streamlit and Flutter) to explain first-principles definitions, calculation contexts, actionability, relationships, and indicator signals for all core terminal metrics.
- No calculations were modified; all structural logic remains identical to v5.0.
"""

import threading

# ====================== SIGNAL SHIELD ======================
# The runtime signal shield (silences signal registration from non-main threads, e.g. OpenBB
# workers) moved to engines/util.py with the rest of the shared low-level utilities (Arch 2
# split) and is installed as a side effect of this import — kept FIRST, before yfinance/OpenBB
# load, exactly as before. The util names are re-bound here so `engine._save_to_disk_cache`,
# `engine.eval_only_tickers` etc. keep working unchanged (tests monkeypatch them on this
# module, and the orchestrator below resolves them through these module globals).
from engines.util import (                                                    # noqa: F401
    CACHE_FILE, _save_to_cache, _load_from_cache,
    _save_to_disk_cache, _load_from_disk_cache,
    _percentile_rank, _robust_adv_shares, _realized_vol, _is_pos, _age_days_iso,
    DEFAULT_BARBELL_WEIGHTS, _resolve_barbell_weights,
    book_tickers, native_ladder, eval_only_tickers,
)
# ========================================================

import asyncio
import copy
import yfinance as yf
import os

import obs  # CEX_DEBUG-gated logging for swallowed exceptions on data/compute paths (lose the blindness)
import datetime
import glob
import re
import json
import logging
import time
import pandas as pd
import numpy as np
import uvicorn

# Arch 5: first-party helpers that were previously imported lazily INSIDE each calling method,
# 2-7 times each (task_supervision, market_data, living_memory, research_cache, …). None of them
# imports engine back (no cycle) and all are stdlib-light, so one top-level import replaces the
# repeats. Imports that MUST stay lazy, and why:
#   * ``from openbb import obb`` (CFTC/FRED paths) — heavy optional dependency, loaded on demand;
#   * ``import yfinance as yf`` inside _fetch_treasury_curve_free — tests inject a stub module via
#     sys.modules at CALL time (test_treasury_curve_basis), which a module-global would bypass;
#   * ``import engine_api`` (PEP 562 re-exports / __main__) — circular by design;
#   * ``import requests`` in the FRED CSV fallback — optional network path, kept inside its guard;
#   * single-site module imports (price_history, holdco_nav, liquidity_monitor, the per-surface
#     monitors, regime_lens/inflation_regime/regime_posture, …) — not duplicated, left at their
#     one call site under its defensive try/except.
import commodity_regime
import conventional_sentinel
import correlation_monitor
import divergence_monitor
import holdco_nav_feed
import kalshi_client
import living_memory
import macro_snapshot
import market_data
import monitor_protocol
import predict_arb_monitor
import research_cache
import sentinel_board
import task_supervision

# Phase 5b: the Polymorphic Archetype Factory (pure-Python, no heavy deps). Imported here
# so the orchestrator can emit supplementary, CAD-normalized triangulated valuations
# alongside — never instead of — the legacy valuation path. archetypes.py never imports
# engine.py, so there is no circular dependency.
from archetypes import build_default_router, load_config, TickerNotRegisteredError, REGIME_ORDER
from ui_state import UIStateManager
from book_invariants import SPEAR_CEILING  # noqa: F401 — the 60% invariant, one shared source of truth
from dynamic_config import DynamicConfigManager, ConfigError
try:
    from fmp_client import FMPClient            # free-tier FMP: fundamentals + treasury, hard-cached
except Exception:                               # pragma: no cover - optional dependency-light helper
    FMPClient = None

# Research dossiers / decision memos written by the /dossier skill (agents) and rendered
# read-only by the cockpit Dossier tab. Absolute so it resolves regardless of launch cwd.
DECISIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "decisions")

# PREDICT arb scanner stores (Wealthsimple Predict / Kalshi). The ledger is append-only — every
# fired opportunity with its full pricing context at fire time, the scanner's own replay-gradeable
# track record; fair_values holds the SOURCED L2 probabilities (p̂) written via /predict/fair_value.
# Env-overridable so tests never touch the real files.
PREDICT_LEDGER_PATH = os.environ.get(
    "CEX_PREDICT_LEDGER_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "predict_ledger.jsonl"))
PREDICT_FV_PATH = os.environ.get(
    "CEX_PREDICT_FV_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "predict_fair_values.json"))

# Phase 7: the dependency-free T-Q-V Asymmetry Rating that powers the primary Conviction Mode
# view. Pure supplement — guarded so the engine still runs if the module is absent.
try:
    from asymmetry_rating import build_conviction_state
except Exception:  # pragma: no cover - conviction overlay is strictly additive
    build_conviction_state = None

# Phase 8: live catalyst reactivity. Events (drill/financing/permitting/catalyst) become
# bounded signal overlays on the TQV inputs + a recent-catalyst list. Guarded import.
try:
    from catalyst_engine import load_catalyst_feed, build_catalyst_overlays
except Exception:  # pragma: no cover - catalyst layer is strictly additive
    load_catalyst_feed = None
    build_catalyst_overlays = None

# Phase 6: optional open-source ingestion overlay. The engine reads the cache that
# ingestion_pipeline.py compiles; the import is guarded so the engine still runs if
# the module (or one of its deps) is absent. ingestion_pipeline never imports engine.py.
try:
    from ingestion_pipeline import load_ingestion_cache
except Exception:  # pragma: no cover - ingestion layer is strictly optional
    load_ingestion_cache = None

# Phase 8 (debug fix): the LIVE catalyst refresher. Without this, the engine only ever
# served the static checked-in feed file (catalysts looked "hardcoded"). Guarded + optional.
try:
    from ingestion_pipeline import refresh_catalyst_feed
except Exception:  # pragma: no cover - live refresh is strictly optional / offline-safe
    refresh_catalyst_feed = None

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# ========================================================
# v5 MODULAR ENGINE ARCHITECTURE
# ========================================================
# The six pure compute engines moved to the engines/ package (mechanical, Arch 2 split).
# Re-exported so `from engine import ValuationEngine` / `engine.MacroRegimeEngine` and every
# existing test/module keep working unchanged.
from engines import (MacroRegimeEngine, PeerEngine, ForensicEngine,           # noqa: F401
                     ValuationEngine, HealthRadarEngine, PortfolioSizer)

# ========================================================
# MAIN COMMODITYEX MONITOR SYSTEM (v5)
# ========================================================

#: Durable QUEST-LOG feed — the agent-activity stream persisted across restarts (mirrors the
#: Living-Memory JSONL pattern). A ROLLING record (bounded), not the immutable forecast trail.
AGENT_ACTIVITY_PATH = "data/agent_activity.jsonl"
AGENT_ACTIVITY_BUFFER = 40                 # live in-memory ring-buffer depth (matches the published frame)
AGENT_ACTIVITY_KEEP = 1000                 # bounded on-disk retention (rewritten to this tail on load)


class CommodityExMonitor:
    def __init__(self):
        # NB: this monitor never connects to a broker. Market data comes from Yahoo
        # (market_data.py) + FMP (fmp_client.py) + the engine's own yfinance fetches; there is
        # no IBKR/IB-Gateway integration (the old host/port/client_id scaffolding was vestigial —
        # assigned and never read — and was removed). Positions/weights are config-sourced.
        self.config_path = "v5_config.json"
        
        # Instantiate v5 Core Engine Modules
        self.macro_engine = MacroRegimeEngine(self.config_path)
        self.peer_engine = PeerEngine(self.config_path)
        self.forensic_engine = ForensicEngine(self.config_path)
        self.valuation_engine = ValuationEngine(self.config_path)
        self.sizer = PortfolioSizer(self.config_path)
        self.radar = HealthRadarEngine(self.config_path)

        # Phase 5b (ADDITIVE): build the Polymorphic Archetype Factory router once at
        # construction. It routes each portfolio name by cash-flow lifecycle and produces a
        # supplementary, CAD-normalized triangulated valuation in PARALLEL with the legacy
        # path — it never replaces any existing valuation. Wrapped defensively so a config or
        # router problem can never block monitor startup; on failure the archetype block is
        # simply omitted from terminal_state. (Snapshot of config at init; the router picks up
        # live FX each cycle, see _compute_archetype_valuations.)
        self.config: dict = {}
        self.archetype_router = None
        try:
            self.config = load_config(self.config_path)
            self.archetype_router = build_default_router(self.config)
        except Exception as e:
            logging.warning("Phase 5b archetype router unavailable (non-fatal): %s", e)

        # Engine-owned UI-context broker (cockpit <-> Flutter merge). The engine holds the
        # instance + routes + terminal_state; the manager is a small orchestrated module.
        self.ui = UIStateManager()
        self._agent_seq = 0          # monotonic id for the ambient agent-activity bus
        self.fmp = FMPClient() if FMPClient else None   # on-demand only (never in the eval loop)

        # Dynamic config overlay (engine-owned): v5_config.json = defaults, SQLite = overrides,
        # merged into self.config and hot-reloaded each loop. Reduces hardcoding over time.
        try:
            self.dconfig = DynamicConfigManager(self.config)
            self.config = self.dconfig.effective()
        except Exception as e:
            self.dconfig = None
            logging.warning("dynamic config overlay unavailable (non-fatal): %s", e)

        # Route EVERY core engine's get_config() through the single effective-config provider so the
        # confirmed overlay (and live file edits) actually reach valuation / JSF / sizing / radar /
        # directives. Without this the engines re-read the raw file and the /confirm overlay was a
        # no-op on the live book (it only ever touched what-ifs / archetypes). One read per cycle.
        for _eng in (self.macro_engine, self.peer_engine, self.forensic_engine,
                     self.valuation_engine, self.sizer, self.radar):
            _eng._config_provider = self._effective_config

        self.last_macro_update = 0
        self.last_price_update = 0
        self.last_cftc_update = 0
        self.last_peer_update = 0
        
        self.cached_prices = {}
        self.cached_mean_peer_ev_oz = None
        self.macro_fail_count = 0
        
        self.shares = {}
        self.uroy_call_price = 0.60
        self.last_csv_mtime = 0

        # Thread safety lock for in-memory cache access
        self.state_lock = threading.Lock()
        
        # Thread-safe in-memory cache for decoupled background tasks
        self.state_cache = {
            # Cold-start defaults aligned to the PeerEngine fallbacks (~$2.5 CAD/oz, ~$0.48/oz disc cost)
            # so the first eval cycle before the peer worker populates live comps is realistic, not a
            # stale $65/oz placeholder that would flash an absurd intrinsic/directive on startup.
            "mean_peer_ev": 2.5,
            "peer_details": [],
            "avg_disc_cost": 0.48,
            
            "y10": 4.35,
            "y30": 4.65,
            "spr": 2.71,
            "ted": 0.05,
            "eff": 4.33,
            "vix": 16.5,
            "macro_status": "LIVE",
            
            "prices": {
                "CL=F": 89.5, "DX-Y.NYB": 99.0, "SI=F": 74.8,
                "AGA.V": 0.72, "GROY": 3.22, "GMX.TO": 2.04, "URC.TO": 4.82,
                "USDCAD=X": 1.38, "^VIX3M": 18.5
            },
            "prices_status": "LIVE",
            
            "dxy_mom": 0.0,
            "current_dxy": 99.0,
            "dxy_status": "INITIAL_BASELINE",   # 99.0 is a BASELINE, not a live read — the 07-02
            # born-LIVE fix (cftc_status below) was one-metric-wide; dxy/ry are the same pattern
            # (2026-07-08 reassessment). The macro worker flips these to LIVE on first sync.

            "usd_to_cad": 1.38,

            "real_yield": 1.0,
            "ry_status": "INITIAL_BASELINE",
            
            "copper": 4.2,
            "gold": 2350.0,
            
            "m1_price": 74.8,
            "m180_price": 74.8,
            
            "cftc_net_longs": 35000.0,
            "cftc_status": "INITIAL_BASELINE",   # the 35000 default is a BASELINE, not a live read —
            # never badge the cold-start fabricated value LIVE (2026-07-02 reassessment finding #3);
            # the CFTC worker flips it to LIVE on its first successful sync (else DEGRADED_STALE).

            # Per-feed point-in-time stamps (epoch secs) for the data-freshness layer; seeded at
            # construction so the cockpit doesn't false-alarm before the first worker cycle.
            "prices_ts": time.time(), "macro_ts": time.time(), "ry_ts": time.time(),
            "dxy_ts": time.time(), "cftc_ts": time.time(), "peers_ts": time.time(),

            "forensic_metrics": {
                "AGA.V": {
                    "sloan_cfo": 0.021, "sloan_bs": 0.024, "shares_t0": 208600000, "shares_t1": 208600000, "sga_t0": 450000,
                    "cfo_t0": None, "cfo_t1": None, "cash_t0": None
                },
                "GROY": {"sloan_cfo": 0.02, "sloan_bs": 0.02},
                "URC.TO": {"sloan_cfo": 0.02, "sloan_bs": 0.02},
                "GMX.TO": {"sloan_cfo": 0.02, "sloan_bs": 0.02}
            },
            
            "df_rets": None,
            "corr_matrix": {
                "AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30},
                "GROY": {"URC.TO": 0.40, "GMX.TO": 0.35},
                "URC.TO": {"GMX.TO": 0.45}
            },
            "vols": {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42},
            # ES95 convention (v5.1 fix): a SIGNED DECIMAL daily tail loss (negative = loss), the
            # same scale the comps worker writes (robust_expected_shortfall) and that the display/
            # plumbing converts to a signed percent via *100. The prior seed (5.2) was a positive
            # percent: *100 -> +520, which is neither < the -5% throttle floor nor below the Health
            # free band, so the entire tail-risk machinery sat INERT until the first comps cycle (~4h).
            # -0.052 == a coherent ~-5.2% cold-start so the throttle/Health penalty are live from t0.
            "es_95": -0.052,
            "port_vol": 0.40,
            "avg_corr": 0.45,

            "aga_adv": 150000,

            # Phase 0: trailing per-driver history feeding the MRI rolling-percentile bounds.
            # Empty until the macro worker seeds it; calculate_mri falls back to static norms meanwhile.
            "mri_history": {}
        }

        # A1.9 (atomic snapshot-swap): readers (/state, /ws, GET buses) are served _published_state
        # — a complete frame swapped in one reference assignment after each eval cycle / interactive
        # mutation — never the live working dict mid-write. None until the first publish (readers
        # fall back to terminal_state through the published_state property, same as before).
        self._published_state = None
        self.terminal_state = {
            "macro_regime": "Pending Data...",
            "directive": "Waiting for tape...",
            "metrics": {
                "10Y": {"value": 4.45, "status": "STALE_FALLBACK"},
                "30Y": {"value": 4.98, "status": "STALE_FALLBACK"},
                "WTI": {"value": 87.36, "status": "STALE_FALLBACK"},
                "DXY": {"value": 98.9, "status": "STALE_FALLBACK"},
                "Spot_Ag": {"value": 75.62, "status": "STALE_FALLBACK"},
                "Spreads": {"value": 2.72, "status": "STALE_FALLBACK"},
                "TED": {"value": 0.05, "status": "STALE_FALLBACK"},
                "EFFR": {"value": 4.33, "status": "STALE_FALLBACK"},
                "VIX": {"value": 15.74, "status": "STALE_FALLBACK"},
                "CFTC_Silver_Net_Longs": {"value": 35000.0, "status": "INITIAL_BASELINE"},
                "PHYSICAL_STRESS": {"value": False, "status": "INITIAL_BASELINE"},
                "DXY_MOMENTUM": {"value": 0.0, "status": "INITIAL_BASELINE"}
            },
            "nodes": {},
            "v4_valuation": {},
            "conviction_mode": {"status": "pending", "view": "conviction", "primary": True, "baskets": []},
            "agent_activity": [],   # ambient stream of what the agents are doing (hooks/agents POST here)
            "agent_annotations": {},  # ticker -> [badge/insight] left by agents (pin_insight/highlight)
            "agent_reply": None,    # the agent's latest full reply text (for the cockpit's prompt panel)
            "treasury_curve": None,  # full US Treasury curve via FMP (1mo…30yr), refreshed ~4x/day
            "pipeline": {"status": "idle", "theme": None, "stage": None, "started": None,
                         "updated": None, "events": [], "result": None, "verdicts": {}},
            "forensics": {
                "jsf_score": 4.0,
                "penalty_factor": 1.0,
                "runway": 70.8,
                "sloan_cfo": 0.02,
                "sloan_bs": 0.02
            },
            "portfolio_stats": {
                "expected_shortfall_95": 0.0,
                "avg_correlation": 0.0
            },
            "signals": [],
            "kill_switches": {"AGA_V": "SAFE (Pending Drill Assays)"},
            "systemic_stress": 0.0,
            "mri": 45.0,
            "metric_metadata": {
                "MRI": {
                    "definition": "Macro Regime Index. Aggregates systemic conditions by measuring tightness in dollar funding, credit, yield curve pressure, tail volatility, physical commodity strength, and speculative positioning.",
                    "calculation": "Linear blend of five normalized components, weights config-driven via mri_weights (defaults: liquidity 0.33, volatility 0.27, commodities 0.16, yields 0.14, sentiment 0.10). Decomposes into a STRESS axis (liquidity+yields+volatility — drives the sizer multiplier, health penalty, defensive directive) and an EXTENSION axis (commodities+sentiment — how hot/crowded the metals trade is; gates adds).",
                    "actionability": "In the silver barbell portfolio, readings <45 favor full fractional Kelly allocation to the AGA.V spear under the REP Floor. Readings >65 trigger automatic reduction of the ADV liquidity cap, redirecting focus to ballast protection in GROY, URC.TO, and GMX.TO.",
                    "relationships": "Inversely affects dynamic ADV sizing cap; directly penalizes Health Rating; interacts with real yield to modulate ROV.",
                    "signals": "Green (<45): Favorable for deployment. Orange (45-65): Maintain guardrails. Red (>65): Prioritize capital preservation.",
                    "related_metrics": ["Health Rating", "ADV Cap", "Discovery Premium", "ROV", "Term Structure", "AISC Uplift", "10Y", "30Y", "TED", "DXY", "Spreads", "VIX", "WTI", "Spot_Ag", "CFTC_Silver_Net_Longs"]
                },
                "JSF": {
                    "definition": "Junior Survival Factor. A rigorous forensic accounting sieve scoring exploration and development assets against capital destruction risks.",
                    "calculation": "Discrete 0-4 point scale evaluating Cash Runway (>18mo), Accruals/Burn Acceleration (CBA <15% or Sloan <5%), Share Dilution (<2% QoQ), and SG&A Drag (<30% of burn).",
                    "actionability": "Scores <3.5 trigger strict allocation limits for AGA.V regardless of macro conditions, enforcing capital preservation against opaque balance sheet decay.",
                    "relationships": "Directly modulates the Forensic Penalty applied to IS-IAI valuation; heavily influences Health Rating.",
                    "signals": "Green (4.0): Risk shield secure. Orange (3.0-3.5): Mild drags, enforce caps. Red (<3.0): Severe forensic failure, extreme caution.",
                    "related_metrics": ["Health Rating", "Forensic Penalty", "IS-IAI", "CBA", "Dilution Sieve", "Sloan Ratios"]
                },
                "Health Rating": {
                    "definition": "A 1-10 composite score quantifying the overall reliability and safety of the terminal's valuation and sizing signals.",
                    "calculation": "Starts at 10.0, penalized by JSF degradation (forensics multiplier), high MRI (macro multiplier), stale data pipelines, and excessive ES95 tail risk.",
                    "actionability": "Determines the Tactical Ceiling for portfolio capital. A low rating indicates that model outputs contain high noise and should be treated as high-uncertainty limits rather than targets.",
                    "relationships": "Synthesizes JSF, MRI, ES95, and data pipeline status.",
                    "signals": "Green (>=8.5): High integrity, actionable. Orange (6.0-8.4): Moderate quality, exercise guardrails. Red (<6.0): High noise, extreme caution.",
                    "related_metrics": ["JSF", "MRI", "ES95"]
                },
                "REP Floor": {
                    "definition": "Resource, Execution, and Permitting Floor. The stressed, bare-minimum liquidation value of an asset.",
                    "calculation": "Aggregates raw cash treasury, heavily discounted inferred/measured ounces (symmetric 50% inferred haircut) RECONCILED to the sourced resource (filings magnitude + the real sitewide M&I/inferred split, not the optimistic config buckets), and permitting/infrastructure sunk costs, divided by shares outstanding.",
                    "actionability": "Serves as the ultimate downside support level for AGA.V. Buying near or below the REP Floor provides maximal margin of safety for the spear position.",
                    "relationships": "The COST leg of the Phase 4a triangulated AGA Intrinsic (confidence-tilted; ~30% stage weight for a pure explorer), reconciled to the SAME sourced resource base as the market leg. (The legacy fixed 15% weight is superseded.)",
                    "signals": "Green: Price < REP Floor (Deep value). Orange: Price near REP Floor. Red: Price significantly above REP Floor.",
                    "related_metrics": ["AGA.V Intrinsic"]
                },
                "ES95": {
                    "definition": "Expected Shortfall at 95% Confidence. Measures the average expected loss in the worst 5% of portfolio return scenarios.",
                    "calculation": "Derived from 60-day historical returns of the barbell components (AGA.V, GROY, URC.TO, GMX.TO) weighted by current allocation.",
                    "actionability": "Used to monitor tail risk. Reported as a SIGNED percent (negative = loss); a 95% ES worse than -5% (more negative) triggers Health-Rating penalties and throttles aggregate leverage via the ES95 Tail Brake in the Sizing Waterfall.",
                    "relationships": "Directly throttles Portfolio Sizer leverage (es_throttle); penalizes Health Rating via continuous convex function; interacts with Portfolio Volatility and Kelly Multiple.",
                    "signals": "Green (> -5%): Contained tail risk. Orange (-5% to -10%): Elevated tail risk. Red (< -10%): Severe downside exposure.",
                    "related_metrics": ["Health Rating", "VIX", "Kelly", "ADV Cap"]
                },
                "ADV Cap": {
                    "definition": "Average Daily Volume Liquidity Cap. The maximum dollar allocation permitted based on the asset's trading liquidity.",
                    "calculation": "Percentage (scaling down from max 15% as MRI increases) of the 10-day Average Daily Volume (ADV) in CAD.",
                    "actionability": "Prevents over-allocation into illiquid assets (AGA.V). Ensures exit liquidity without moving the tape, enforcing strict block execution frames.",
                    "relationships": "Inversely correlated with MRI; directly limits the E_Target (target capital allocation).",
                    "signals": "Green: Cap expanded (high liquidity/low macro stress). Orange: Cap standard. Red: Cap severely restricted.",
                    "related_metrics": ["MRI"]
                },
                "ROV": {
                    "definition": "Real Option Value (LEGACY). The old additive convexity premium for silver assets; superseded in Phase 4a by the stage-decayed option-convexity premium (1+pi_opt).",
                    "calculation": "Base premium (1.18x) modulated continuously by negative real yields (premium scales as yields drop <1%) and silver price volatility.",
                    "actionability": "Diagnostic only. The 'monetary battery' convexity it represented now flows through the option premium (realized vol + monetary carry) that multiplies the market leg, not a separate additive ROV term.",
                    "relationships": "SUPERSEDED: no longer carries an independent weight in the authoritative triangulated AGA Intrinsic (the legacy ~15% additive weight is retained only in the v4_valuation reconciliation baseline). Convexity now lives in the option premium on the market leg.",
                    "signals": "Green: High convexity environment (low yields, rising vol). Orange: Neutral. Red: Low convexity (high real yields).",
                    "related_metrics": ["10Y", "VIX", "Spot_Ag", "AGA.V Intrinsic"]
                },
                "Peer EV/oz": {
                    "definition": "Peer Enterprise Value per Ounce. The market-implied price paid for silver resources in the ground among comparable developers.",
                    "calculation": "Liquidity-weighted average of adjusted EV/oz across a basket of peers, factoring in stage multipliers, jurisdictional risk, and measured/indicated confidence.",
                    "actionability": "Provides the baseline multiple for valuing AGA.V's ounces in the IS-IAI metric. Identifies if the broad sector is undervalued or overheated.",
                    "relationships": "Directly multiplies effective ounces in IS-IAI calculation; informs Discovery Premium.",
                    "signals": "Green: Sector heavily discounted. Orange: Fair value. Red: Sector overvalued.",
                    "related_metrics": ["IS-IAI"]
                },
                "Sloan Ratios": {
                    "definition": "Sloan Accrual Ratios (CFO & Balance Sheet). Measures the quality of earnings and cash flow persistence.",
                    "calculation": "(Net Income - Operating Cash Flow) / Total Assets, and similar balance sheet accrual derivations.",
                    "actionability": "High accruals (>5%) indicate non-cash earnings inflation or opaque capital capitalization. Used in the JSF to flag potential accounting stress in ballast assets (GROY, URC.TO, GMX.TO).",
                    "relationships": "Core component of the JSF; drives forensic penalties on ballast valuations.",
                    "signals": "Green (<5%): Clean cash-backed earnings. Orange: Monitor accruals. Red (>5%): Accrual overload, high accounting risk.",
                    "related_metrics": ["JSF"]
                },
                "Discovery Premium": {
                    "definition": "Discovery Premium Factor. The market reward multiple for active, high-grade exploration success and resource expansion.",
                    "calculation": "Product of commodity leverage (spot vs AISC), profit margins, and an explorer re-rating scalar, capped dynamically by macro conditions (MRI) and spot deviations.",
                    "actionability": "Diagnostic only (the v4_valuation reconciliation baseline). Speculative torque is no longer applied as a separate multiplier; it is captured once via the live peer EV/oz and once via the stage-decayed option premium.",
                    "relationships": "REMOVED in Phase 4a from the authoritative valuation: this ~3.3x operating-leverage multiple double-counted the silver level already priced into peer EV/oz, so it was deleted from the triangulated market leg (silver torque now flows ONCE via peer EV/oz, ONCE via the option premium).",
                    "signals": "Green: Market rewarding discovery. Orange: Neutral. Red: Market ignoring drill results (macro cap active).",
                    "related_metrics": ["MRI", "Spot_Ag", "AISC Uplift", "IS-IAI"]
                },
                "IS-IAI": {
                    "definition": "In-Situ Inferred & Indicated Valuation (LEGACY). The old comps-based core asset value; superseded in Phase 4a by the de-overlapped MARKET leg of the triangulation.",
                    "calculation": "LEGACY formula: Effective ounces * Peer EV/oz * Discovery Premium * Jurisdiction Uplift * Recovery * Capital Discount. The authoritative market leg DROPS the Discovery Premium multiplier (double-count) and grades ounces by Technical Quality instead.",
                    "actionability": "SUPERSEDED: the legacy 70%-weight IS-IAI is replaced by the confidence-tilted Cost+Market+Income triangulation. Its job — comps x effective ounces x geological confidence — now lives in the de-overlapped MARKET leg (peer EV/oz x technical quality x capital discount). Retained as a v4_valuation diagnostic only.",
                    "relationships": "Requires Peer EV/oz and the macro Capital Discount Factor; modulated by JSF Forensic Penalty. (No longer multiplied by the removed Discovery Premium.)",
                    "signals": "Green: High intrinsic value relative to price. Orange: Fairly valued. Red: Overvalued relative to peers.",
                    "related_metrics": ["JSF", "Peer EV/oz", "Discovery Premium", "AGA.V Intrinsic"]
                },
                "Priorities": {
                    "definition": "Actionable Strategic Directives generated by the Health Radar.",
                    "calculation": "Rule-based synthesis evaluating Implied Edge (valuation arbitrage), JSF Score (accounting safety), MRI (macro scaling), and Kelly Multiple (overallocation).",
                    "actionability": "Provides the 1-2-3 step execution plan for the portfolio manager. Determines whether to exploit spear arbitrage, enforce sizing caps, or trim overallocations.",
                    "relationships": "Aggregates all major engine outputs (Valuation, Forensics, Macro, Sizing) into plain text.",
                    "signals": "Green: Proceed with execution. Orange: Trim or hold with caution. Red: Defensive mitigation required.",
                    "related_metrics": []
                },
                "CBA": {
                    "definition": "Cash Burn Acceleration. Measures whether quarter-over-quarter cash outflow is expanding relative to the company's size.",
                    "calculation": "QoQ change in burn (Burn = -CFO) normalized by ENTERPRISE VALUE (a size proxy; gate ~3%) so a deliberately lean treasury does not self-incriminate. Falls back to the legacy /Total Cash basis (gate 15%) when EV is unavailable; both are recorded for audit.",
                    "actionability": "An accelerating burn (above the EV-normalized ~3% gate, or the legacy 15%-of-cash fallback) warns of explosive cash drain and imminent dilution; it fails the JSF accrual test and triggers capital-preservation caps.",
                    "relationships": "Core component of the JSF Score for explorers.",
                    "signals": "Green (<15%): Burn stable or decelerating. Red (>15%): Rapidly accelerating burn, dilution imminent.",
                    "related_metrics": ["JSF"]
                },
                "Dilution Sieve": {
                    "definition": "Weighted quarterly share count expansion screen designed to catch dilution-heavy juniors.",
                    "calculation": "(Shares_T0 - Shares_T1) / Shares_T1 (QoQ share count growth).",
                    "actionability": "Share dilution >= 2% QoQ fails the sieve, triggering a 35% weight penalty on the JSF explorer score to discount resources.",
                    "relationships": "Weights dilution at 35% of the explorer forensic penalty applied to IS-IAI.",
                    "signals": "Green (<2%): Protected from equity dilution. Red (>=2%): Sieve failure, high valuation decay.",
                    "related_metrics": ["JSF"]
                },
                "AISC Uplift": {
                    "definition": "Dynamic margin adjustment modeling energy and oil cost impacts on mining economics.",
                    "calculation": "Base AISC + max(0, WTI Crude Oil - 80.0) * 0.15.",
                    "actionability": "A high WTI price increases operating costs, which shrinks profit margins and compresses the Discovery Premium.",
                    "relationships": "Directly reduces phi profit margins and limits the Discovery Premium ceiling.",
                    "signals": "Green: Energy drag neutral (WTI < $80). Red: Energy inflation squeeze (WTI > $80).",
                    "related_metrics": ["WTI", "Discovery Premium"]
                },
                "Term Structure": {
                    "definition": "Futures curve pricing gradient measuring physical metal tightness.",
                    "calculation": "True if Month 1 futures price exceeds Month 6 price (Backwardation); False otherwise (Contango).",
                    "actionability": "Indicates direct immediate physical demand. Backwardation triggers a physical stress premium (up to 25%) on resources.",
                    "relationships": "Adds an immediate supply premium to the project Jurisdiction Uplift.",
                    "signals": "Green: Backwardation (Physical stress premium active). Red: Contango (Standard spot structure).",
                    "related_metrics": ["Spot_Ag", "Discovery Premium"]
                },
                "10Y": {
                    "definition": "10-Year US Treasury Yield. Standard benchmark for global risk-free discount rates.",
                    "calculation": "Live yield fetched from data pipelines.",
                    "actionability": "Direct component of real interest rate calculations, which in turn modulate silver Real Option Value (ROV).",
                    "relationships": "Feeds into MRI and Real Yield formulas.",
                    "signals": "Green (<3.75%): Accommodative. Orange (3.75-4.75%): Tightening. Red (>4.75%): Restrictive.",
                    "related_metrics": ["MRI", "ROV"]
                },
                "30Y": {
                    "definition": "30-Year US Treasury Yield. Standard long-term risk-free rate pricing.",
                    "calculation": "Live yield fetched from data pipelines.",
                    "actionability": "Used to monitor steepening vs. inversion of the long end of the yield curve.",
                    "relationships": "Feeds into MRI curve steepening formula.",
                    "signals": "Green (<4.00%): Stable. Red (>5.00%): Curve stress.",
                    "related_metrics": ["MRI"]
                },
                "TED": {
                    "definition": "SOFR Spread / TED Spread equivalent. Measures stress in money markets and commercial banking liquidity.",
                    "calculation": "3-Month SOFR rate minus 3-Month US Treasury bill yield.",
                    "actionability": "Spikes > 0.40% indicate systemic liquidity strain in the interbank repo market.",
                    "relationships": "Core component of MRI Liquidity weight.",
                    "signals": "Green (<0.20%): Liquid. Red (>0.45%): Acute interbank stress.",
                    "related_metrics": ["MRI", "Health Rating"]
                },
                "DXY": {
                    "definition": "US Dollar Index. Measures strength of the USD against a basket of foreign currencies.",
                    "calculation": "Live exchange rate index value.",
                    "actionability": "Strong USD (>104) typically suppresses global asset prices and compresses liquidity.",
                    "relationships": "Feeds into MRI Liquidity weight.",
                    "signals": "Green (<100): Weak dollar tailwind. Red (>104): Strong dollar headwind.",
                    "related_metrics": ["MRI"]
                },
                "Spreads": {
                    "definition": "High Yield Corporate Bond Option-Adjusted Spreads.",
                    "calculation": "Weighted index yield premium over Treasuries.",
                    "actionability": "Rising credit spreads indicate credit stress, raising financing costs for resource juniors.",
                    "relationships": "Feeds into MRI credit component.",
                    "signals": "Green (<3.50%): Tight spreads, healthy credit. Red (>5.00%): Wide spreads, elevated defaults.",
                    "related_metrics": ["MRI", "Health Rating"]
                },
                "VIX": {
                    "definition": "CBOE Volatility Index. Measures standard market-implied near-term tail risk.",
                    "calculation": "VIX implied volatility percentage index.",
                    "actionability": "High VIX (>23) triggers cash reserve preservation targets.",
                    "relationships": "Feeds into MRI volatility component and ROV expansion formula.",
                    "signals": "Green (<15.0): Low fear. Red (>23.0): Extreme market fear.",
                    "related_metrics": ["MRI", "ROV", "Health Rating"]
                },
                "WTI": {
                    "definition": "West Texas Intermediate Crude Oil spot price.",
                    "calculation": "Live dollar spot price per barrel.",
                    "actionability": "High oil costs (>80) increase energy fuel surcharges at remote mine sites, raising explorer AISC costs.",
                    "relationships": "Feeds into AISC energy uplift formula.",
                    "signals": "Green (<$75): Low mining fuel costs. Red (>$85): Inflationary energy squeeze.",
                    "related_metrics": ["MRI", "AISC Uplift"]
                },
                "Spot_Ag": {
                    "definition": "Spot Silver price per ounce in USD.",
                    "calculation": "Live global spot price.",
                    "actionability": "The primary macro pricing factor for silver leverage barbell components.",
                    "relationships": "Directly impacts Discovery Premium and Term Structure calculations.",
                    "signals": "Green (>$32): Bull market surge. Red (<$24): Bear market capitulation.",
                    "related_metrics": ["MRI", "ROV", "Discovery Premium", "Term Structure"]
                },
                "CFTC_Silver_Net_Longs": {
                    "definition": "CFTC Silver Non-Commercial Net Speculator Position.",
                    "calculation": "Speculator long contracts minus short contracts.",
                    "actionability": "Extreme net-shorts represent highly bullish contrarian capitulation setups.",
                    "relationships": "Feeds into MRI contrarian sentiment weight.",
                    "signals": "Green: Capitulation net-short. Red: Overcrowded net-long.",
                    "related_metrics": ["MRI"]
                },
                "GSR": {
                    "definition": "Gold/Silver Ratio. The number of silver ounces needed to buy one ounce of gold. A key macro indicator for precious metals relative valuation.",
                    "calculation": "Gold Spot Price / Silver Spot Price.",
                    "actionability": "GSR below 75 signals silver outperformance (bullish for the barbell thesis). GSR above 85 signals extreme silver undervaluation or risk-off conditions — historically a contrarian accumulation signal for silver assets.",
                    "relationships": "Inversely correlated with silver momentum; high GSR historically precedes silver rallies. Contextualizes MRI commodity component.",
                    "signals": "Green (<75): Silver outperforming, bullish momentum. Orange (75-85): Neutral ratio. Red (>85): Extreme undervaluation or risk-off.",
                    "related_metrics": ["MRI", "Spot_Ag", "Discovery Premium"]
                }
            }
        }

        # Restore the persisted QUEST-LOG feed so past agent runs/replies survive a restart (the feed
        # was previously an in-memory ring buffer that re-initialized empty every start).
        self._reload_agent_feed()

    def _effective_config(self) -> dict:
        """The single source of truth the engine providers read each call: the per-cycle effective
        config (`self.config` == file defaults + confirmed overrides), rebuilt once per cycle by
        `_refresh_effective_config`. Falls back to a raw file read if `self.config` is somehow empty
        (e.g. the overlay failed at construction) so an engine call can never be starved of config."""
        cfg = getattr(self, "config", None)
        if isinstance(cfg, dict) and cfg:
            return cfg
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _refresh_effective_config(self) -> dict:
        """Rebuild `self.config` for the cycle from a FRESH read of v5_config.json (so direct file
        edits to any key still hot-reload — most config is outside the dynamic-config allowlist and
        can only change via the file) layered with the confirmed SQLite overrides. One disk read per
        cycle replaces the per-engine-method reads, and every engine sees the SAME snapshot for the
        whole cycle (no mid-cycle TOCTOU). Returns the effective dict."""
        try:
            with open(self.config_path, "r") as f:
                defaults = json.load(f)
        except Exception as e:
            logging.warning("config reload failed; reusing last effective config: %s", e)
            return self._effective_config()
        if getattr(self, "dconfig", None) is not None:
            try:
                self.dconfig.set_defaults(defaults)
                self.config = self.dconfig.effective()
            except Exception as e:
                logging.warning("overlay merge failed; using raw file defaults: %s", e)
                self.config = defaults
        else:
            self.config = defaults
        return self.config

    def start_background_tasks(self):
        # A1.9: every worker is SUPERVISED — a crash (or an impossible return from an infinite
        # loop) is recorded into terminal_state["worker_health"], flips the status line on the
        # next eval, and republishes immediately. Surfacing only — no silent auto-restart.
        health = self.terminal_state.setdefault("worker_health", {})

        def _on_death(name, error):
            logging.error("background worker %s DIED: %s", name, error)
            self.terminal_state["status"] = "DEGRADED_WORKER_DOWN: " + name
            self.publish_state()

        self.tasks = [
            task_supervision.create_supervised("prices", self._prices_worker(), health=health, on_death=_on_death),
            task_supervision.create_supervised("macro", self._macro_worker(), health=health, on_death=_on_death),
            task_supervision.create_supervised("cftc", self._cftc_worker(), health=health, on_death=_on_death),
            task_supervision.create_supervised("comps", self._comps_worker(), health=health, on_death=_on_death),
            task_supervision.create_supervised("predict", self._predict_worker(), health=health, on_death=_on_death),
        ]
        return self.tasks

    def _load_shares_from_csv(self, force=False):
        # Glob the NEWEST holdings export (cwd or alongside the engine) instead of pinning to a
        # single dated filename, so the book's position truth isn't frozen to a stale snapshot.
        # BOTH naming styles: Wealthsimple exports arrive as 'holdingsreport<date>.csv' (no dashes,
        # 2026-08 reality) as well as the older 'holdings-report-*.csv' — the narrow glob silently
        # ignored the operator's real export and the engine kept pricing a stale book.
        # (.gitignore covers the same widened pattern — these files carry the account number.)
        _here = os.path.dirname(os.path.abspath(__file__))
        _pats = ("holdings-report-*.csv", "holdings*report*.csv")
        _cands = [p for p in {q for pat in _pats
                              for q in glob.glob(pat) + glob.glob(os.path.join(_here, pat))}
                  if os.path.exists(p)]
        holdings_path = max(_cands, key=os.path.getmtime) if _cands else None
        if not holdings_path:
            return False
        try:
            mtime = os.path.getmtime(holdings_path)
            self._holdings_csv = {"file": os.path.basename(holdings_path),
                                  "age_days": round(max(0.0, time.time() - mtime) / 86400.0, 1)}
            if not force and mtime == self.last_csv_mtime:
                return True

            df = pd.read_csv(holdings_path)
            new_shares = {}
            new_conv = {}                              # conventional positions: {ticker: {units, unit_price}}
            for _, row in df.iterrows():
                symbol = str(row.get('Symbol', '')).strip().upper()
                if not symbol or symbol == 'NAN':
                    continue
                try:
                    qty = float(row.get('Quantity', 0))
                except:
                    qty = 0
                # An OPTION row (e.g. 'GROY  260821C00003000') must never overwrite the
                # underlying's EQUITY share count — only the UROY branch below is meant to
                # match an option row (the tracked UROY call).
                sec_type = str(row.get('Security Type', '')).strip().upper()
                is_option = sec_type == 'OPTION' or bool(re.search(r'\d{6}[CP]\d{8}$', symbol))
                if 'AGA' in symbol and not is_option:
                    new_shares['AGA'] = qty
                elif 'URC' in symbol and 'UROY' not in symbol and not is_option:
                    new_shares['URC'] = qty
                elif 'GROY' in symbol and not is_option:
                    new_shares['GROY'] = qty
                elif 'GMX' in symbol and not is_option:
                    new_shares['GMX'] = qty
                elif 'UROY' in symbol:
                    new_shares['UROY_CALL'] = qty
                    try:
                        self.uroy_call_price = float(row.get('Market Price', 0.60))
                    except Exception:
                        self.uroy_call_price = 0.60
                else:
                    # DATA-DRIVEN conventional matching (2026-08-02): any portfolio_metadata entry
                    # with lane:'conventional' + a ws_symbol maps its CSV row here — units AND the
                    # export's own market price (the instrument's unit value; a CDR has no vendor
                    # quote and its ratio ≠ 1, so the reference price must never mark it). This is
                    # what makes add_holding one call: registering the entry IS the integration —
                    # no per-name loader branch, ever again.
                    try:
                        import conventional_holdings as _chl
                        _wsmap = _chl.ws_symbol_map(self.config.get("portfolio_metadata"))
                    except Exception:
                        _wsmap = {}
                    _hit = next((cfg_tk for ws, cfg_tk in _wsmap.items() if ws in symbol), None)
                    if _hit:
                        new_conv[_hit] = {"units": qty}
                        try:
                            new_conv[_hit]["unit_price"] = float(row.get('Market Price', 0.0))
                        except Exception:
                            new_conv[_hit]["unit_price"] = 0.0
            if new_shares or new_conv:
                self.shares = new_shares
                self.conv_positions = new_conv         # consumed by NAV + the conventional sleeve
                self.last_csv_mtime = mtime
                print(f"Loaded share quantities from CSV: {self.shares}"
                      + (f" + conventional: {new_conv}" if new_conv else ""))
                return True
        except Exception as e:
            print(f"Failed to load shares from CSV: {e}")
        return False

    def _get_fallback_price(self, ticker):
        fallbacks = {
            "AGA.V": 0.71, "GROY": 3.22, "GMX.TO": 2.04,
            "URC.TO": 4.82, "SI=F": 74.8, "CL=F": 89.5, "DX-Y.NYB": 99.0,
            "^VIX3M": 18.5
        }
        return fallbacks.get(ticker, 0.0)

    # ==================== DECOUPLED BACKGROUND WORKERS ====================

    async def _prices_worker(self):
        while True:
            try:
                t_start = time.time()
                # Compute Month 6 forward silver contract ticker dynamically
                now = datetime.datetime.now()
                curr_month = now.month
                curr_year_short = now.year % 100
                if curr_month in [1, 2]: code, yr = "N", curr_year_short
                elif curr_month in [3, 4, 5]: code, yr = "Z", curr_year_short
                elif curr_month in [6, 7, 8]: code, yr = "H", curr_year_short + 1
                else: code, yr = "N", curr_year_short + 1
                m180_ticker = f"SI{code}{yr:02d}.CMX"

                # Standard consolidated tickers list (15 items) + the promoted EVAL set, so a
                # graduated candidate gets a live mark the cycle after promotion (config
                # hot-reloads through _refresh_effective_config; the worker re-reads each loop)
                eval_tks = eval_only_tickers(self.config)
                tickers = [
                    "CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO", "USDCAD=X",
                    "JPY=X", "HG=F", "GC=F", "^IRX", "^TNX", "^TYX", "^VIX", m180_ticker
                ] + eval_tks

                # Perform a single bulk HTTP download to Yahoo
                def get_bulk_data():
                    try:
                        df = yf.download(tickers, period="10d", group_by="ticker", progress=False)
                        return df
                    except Exception as e:
                        print(f"[Prices Worker] yfinance bulk download failed: {e}")
                        return None

                df = await asyncio.to_thread(get_bulk_data)

                # 1. Parse Prices — provenance-aware (audit fix). A holding's CURRENT price prefers
                # the live intraday quote (regularMarketPrice): the daily bulk bar lags a session and
                # is frequently NaN on the latest day for an individual name, so the prior
                # df[t]['Close'].dropna().iloc[-1] silently served a 1-2 day-old close as if LIVE.
                # Now: intraday -> dated daily close (flagged stale if not today) -> last-good cache
                # -> hardcoded constant (last resort), STAMPING per-ticker as_of/stale so a stale
                # mark can never masquerade as live again. Intraday is independent of the bulk df,
                # so holdings still get a fresh mark even if the bulk download partially fails.
                md = getattr(self, "_md", None)
                if md is None:
                    md = market_data.MarketData(fmp=getattr(self, "fmp", None))
                    self._md = md
                today_d = now.date()
                hold_equities = set(book_tickers(self.config)) | set(eval_tks)
                # last-good cache holds ONLY fresh marks ({tk: {price, as_of}}), so a fetch-miss falls
                # back to the last REAL price, never the hardcoded fallback (the oscillation amplifier).
                lastgood = _load_from_cache("prices_lastgood", {})
                if not lastgood:                               # one-time migrate off the legacy caches
                    _pj = _load_from_cache("prices", {}); _aj = _load_from_cache("prices_asof", {})
                    lastgood = {t: {"price": float(_pj[t]), "as_of": _aj.get(t)}
                                for t in _pj if _is_pos(_pj.get(t))}

                def _intraday_for_holdings():
                    out = {}
                    for tk in hold_equities:
                        try:
                            q = md.yahoo_quote(tk)
                            if q and not q.get("stale") and _is_pos(q.get("price")):
                                out[tk] = float(q["price"])
                        except Exception:
                            obs.swallow(f"prices.intraday.{tk}")    # a quote fault must be visible (CEX_DEBUG)
                    return out
                intraday_map = await asyncio.to_thread(_intraday_for_holdings)

                prices, prices_asof, prices_stale, resolved = {}, {}, {}, {}
                primary_tickers = ["CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO", "USDCAD=X", "JPY=X", "^VIX3M"] + eval_tks
                for t in primary_tickers:
                    daily = []
                    try:
                        if df is not None and t in df.columns.levels[0]:
                            ser = df[t]['Close'].dropna()
                            daily = [(idx.date(), float(v)) for idx, v in ser.items()]
                    except Exception as e:
                        print(f"[Prices Worker] Price parse error for {t}: {e}")
                        daily = []
                    _lg = lastgood.get(t)
                    lg = _lg if (isinstance(_lg, dict) and _is_pos(_lg.get("price"))) else None
                    r = market_data.resolve_freshness(daily_closes=daily,
                                                      intraday=intraday_map.get(t),
                                                      last_good=lg, today=today_d)
                    if r.get("price") is None:
                        r = {"price": self._get_fallback_price(t), "as_of": None,
                             "stale": True, "source": "hardcoded-fallback"}
                    resolved[t] = r
                    prices[t] = r["price"]
                    prices_asof[t] = r["as_of"]
                    prices_stale[t] = bool(r["stale"])

                # carry forward ONLY fresh marks → the last-good cache never holds a fallback, so the
                # next fetch-miss resolves to the last REAL price (flagged stale), not the constant.
                lastgood = market_data.merge_last_good(lastgood, resolved)
                _save_to_cache("prices_lastgood", lastgood)
                _save_to_cache("prices", prices)
                _save_to_cache("prices_asof", prices_asof)
                # Honest status: a stale/fallback mark on ANY holding demotes the feed from LIVE so
                # the cockpit/rating can flag it (the old code hard-coded "LIVE" right here, which is
                # how a multi-day-stale holding kept reading as live).
                _stale_holdings = sorted(t for t in hold_equities if prices_stale.get(t))
                prices_status = "DEGRADED" if _stale_holdings else "LIVE"
                if _stale_holdings:
                    print(f"[Prices Worker] DEGRADED — stale/fallback marks: {', '.join(_stale_holdings)}")

                # 2. Parse Copper and Gold
                copper, gold = 4.2, 2350.0
                try:
                    if df is not None and "HG=F" in df.columns.levels[0]:
                        cu_hist = df["HG=F"]['Close'].dropna()
                        if not cu_hist.empty: copper = float(cu_hist.iloc[-1])
                    if df is not None and "GC=F" in df.columns.levels[0]:
                        au_hist = df["GC=F"]['Close'].dropna()
                        if not au_hist.empty: gold = float(au_hist.iloc[-1])
                    _save_to_cache("copper_gold", {"copper": copper, "gold": gold})
                except Exception as e:
                    print(f"[Prices Worker] Copper/Gold parse error: {e}")
                    cached = _load_from_cache("copper_gold", {"copper": 4.2, "gold": 2350.0})
                    copper, gold = cached["copper"], cached["gold"]

                # 2b. Divergence SENTINEL inputs (the decoupling auto-fire) — today's per-name session
                # return + volume + a spike-robust ADV, plus the dominant commodity session returns, ALL
                # from the 10d frame already in hand, so the sentinel costs NO extra network. "Today's"
                # return uses the freshest resolved price over the last COMPLETE prior daily close, so it
                # doesn't wait on the (often-late) latest daily bar. Best-effort; never disturbs prices.
                try:
                    def _prior_close(sym):
                        if df is None or sym not in df.columns.levels[0]:
                            return None
                        ser = df[sym]['Close'].dropna()
                        prior = [float(v) for idx, v in ser.items() if idx.date() < today_d]
                        return prior[-1] if prior else None
                    def _div_ret(cur, sym):
                        pc = _prior_close(sym)
                        return (float(cur) / pc - 1.0) if (pc and pc > 0 and _is_pos(cur)) else None
                    def _adv_prior(sym):
                        if df is None or sym not in df.columns.levels[0]:
                            return None
                        v = df[sym]['Volume'].dropna()
                        v = v[v > 0].iloc[:-1]                 # exclude the latest bar; rvol = latest / prior median
                        return float(v.median()) if len(v) >= 4 else None
                    def _last_vol(sym):
                        if df is None or sym not in df.columns.levels[0]:
                            return None
                        v = df[sym]['Volume'].dropna()
                        return float(v.iloc[-1]) if len(v) else None
                    def _fresh_ret(cur, sym, tk):
                        # a STALE/fallback mark must never manufacture a false decouple (the same hazard
                        # the calibration flywheel gates against) → null the return when the mark isn't live
                        return None if prices_stale.get(tk) else _div_ret(cur, sym)
                    div_inputs = {
                        "by_ticker": {tk: {"day_return": _fresh_ret(prices.get(tk), tk, tk),
                                           "volume": _last_vol(tk), "adv": _adv_prior(tk)}
                                      for tk in sorted(hold_equities)},
                        "factors": {"silver": _fresh_ret(prices.get("SI=F"), "SI=F", "SI=F"),
                                    "gold": _div_ret(gold, "GC=F"), "copper": _div_ret(copper, "HG=F")},
                        "ts": time.time(),
                    }
                    with self.state_lock:
                        self.state_cache["divergence_inputs"] = div_inputs
                except Exception:
                    obs.swallow("prices.divergence_inputs")

                # 3. Silver Term Structure
                m1_price = prices.get("SI=F", 74.8)
                m180_price = m1_price
                try:
                    if df is not None and m180_ticker in df.columns.levels[0]:
                        m180_hist = df[m180_ticker]['Close'].dropna()
                        if not m180_hist.empty: m180_price = float(m180_hist.iloc[-1])
                except Exception as e:
                    print(f"[Prices Worker] Term structure parse error: {e}")

                # 4. Sovereign Rates & Volatility proxies (Real-Time backup / feed). Write ONLY the tenors
                # the feed actually returned — NEVER a fabricated constant. When a tenor is missing it is
                # left ABSENT, so the macro merge keeps the FRED/cached value (its `if _yf_vix > 0` and
                # `.get(key, prior)` guards already treat absence as "no live override", and that path
                # carries an honest DEGRADED_STALE status). The old code seeded 4.45/4.98/4.33/15.74 and,
                # when the feed died, cached those AS IF LIVE — a 'calm sensor' that read VIX 15.74 / 10Y
                # 4.45 with LIVE status. A blank that degrades visibly is safer than a confident wrong number.
                try:
                    def _curve_close(sym):
                        if df is not None and sym in df.columns.levels[0]:
                            s = df[sym]['Close'].dropna()
                            if not s.empty:
                                return float(s.iloc[-1])
                        return None
                    yf_macro = {}
                    for _k, _sym in (("y10", "^TNX"), ("y30", "^TYX"), ("y3mo", "^IRX"), ("vix", "^VIX")):
                        _v = _curve_close(_sym)
                        if _v is not None:
                            yf_macro[_k] = _v
                    _save_to_cache("yf_live_macro", yf_macro)   # partial/empty ⇒ FRED/cached stands, honestly
                    if not yf_macro:
                        print("[Prices Worker] live macro feed (^TNX/^TYX/^IRX/^VIX) empty — "
                              "FRED/cached values stand (no fabricated mark)")
                except Exception as e:
                    print(f"[Prices Worker] Live yields parse error: {e}")

                # 5. Silver ADV volume
                aga_adv = 150000
                try:
                    aga_adv = await self.sizer.get_liquidity_cap("AGA.V")
                except Exception as e:
                    print(f"[Prices Worker] Liquidity cap error: {e}")

                # Update State Cache
                with self.state_lock:
                    self.state_cache["prices"] = prices
                    self.state_cache["prices_status"] = prices_status
                    self.state_cache["prices_asof"] = prices_asof
                    self.state_cache["prices_stale"] = prices_stale
                    self.state_cache["prices_ts"] = time.time()
                    self.state_cache["usd_to_cad"] = prices.get("USDCAD=X", 1.38)
                    self.state_cache["copper"] = copper
                    self.state_cache["gold"] = gold
                    self.state_cache["m1_price"] = m1_price
                    self.state_cache["m180_price"] = m180_price
                    self.state_cache["aga_adv"] = aga_adv

                elapsed = time.time() - t_start
                print(f"[*] [Prices Worker] Synchronized live prices successfully in {elapsed:.3f}s (1 consolidated yfinance call).")
            except Exception as ex:
                print(f"[!] [Prices Worker] Main Loop Error: {ex}")
            await asyncio.sleep(60)

    async def _macro_worker(self):
        while True:
            try:
                # 1. FRED macro data
                res, status = await self.macro_engine.fetch_macro_data()
                
                # 2. Real yield
                real_yield, ry_status = await self.macro_engine.fetch_real_yield()
                
                # 3. DXY momentum
                dxy_mom, current_dxy, dxy_status = await self.macro_engine.fetch_dxy_momentum()

                # 4. MRI rolling-percentile history (Phase 0): disk-cached with a 24h TTL, so polling
                #    it on the 30-min macro cadence almost always hits the cache and is near-free. Stored
                #    independently of `res` so the dynamic bounds survive a FRED/macro fetch failure.
                mri_history = await self.macro_engine.fetch_mri_history()
                if mri_history:
                    with self.state_lock:
                        self.state_cache["mri_history"] = mri_history

                # Update State Cache
                if res and len(res) >= 6:
                    with self.state_lock:
                        self.state_cache["y10"] = res[0]
                        self.state_cache["y30"] = res[1]
                        self.state_cache["spr"] = res[2]
                        self.state_cache["ted"] = res[3]
                        self.state_cache["eff"] = res[4]
                        self.state_cache["vix"] = res[5]
                        self.state_cache["macro_status"] = status
                        self.state_cache["macro_ts"] = time.time()

                        self.state_cache["real_yield"] = real_yield
                        self.state_cache["ry_status"] = ry_status
                        self.state_cache["ry_ts"] = time.time()

                        self.state_cache["dxy_mom"] = dxy_mom
                        self.state_cache["current_dxy"] = current_dxy
                        self.state_cache["dxy_status"] = dxy_status
                        self.state_cache["dxy_ts"] = time.time()
                    print(f"[*] [Macro Worker] Synchronized live FRED and macro parameters successfully.")
            except Exception as ex:
                print(f"[!] [Macro Worker] Main Loop Error: {ex}")
            await asyncio.sleep(1800) # 30 minutes

    async def _cftc_worker(self):
        retry_delay = 300  # 5 minutes for transient failures
        standard_sleep = 14400  # 4 hours
        
        while True:
            try:
                # Load configuration parameters
                cfg = self.peer_engine.get_config()
                cftc_cfg = cfg.get("cftc_params", {
                    "primary_contract_code": "CFTC_084691",
                    "fallback_contract_code": "CFTC_084691",
                    "managed_money_multiplier_0_to_1": 100000,
                    "managed_money_multiplier_0_to_100": 1000
                })
                primary_code = cftc_cfg["primary_contract_code"]
                fallback_code = cftc_cfg["fallback_contract_code"]

                def openbb_cftc():
                    from openbb import obb
                    # Direct, explicit retrieval of standard institutional Silver Futures
                    cftc_router = None
                    if hasattr(obb, "regulators") and hasattr(obb.regulators, "cftc"):
                        cftc_router = obb.regulators.cftc
                    elif hasattr(obb, "cftc"):
                        cftc_router = obb.cftc

                    if cftc_router is not None:
                        try:
                            # Prioritize direct lookup via precise code (CFTC_084691)
                            res = cftc_router.cot(code=primary_code)
                        except Exception:
                            try:
                                search_res = cftc_router.cot_search(query="silver")
                                df_search = search_res.to_dataframe()
                                if not df_search.empty:
                                    # Prioritize standard institutional code
                                    silver_rows = df_search[df_search['code'] == primary_code]
                                    if silver_rows.empty:
                                        # Filter out micro/mini/CBOT retail contracts explicitly
                                        silver_rows = df_search[df_search['name'].str.contains('SILVER', case=False, na=False)]
                                        silver_rows = silver_rows[~silver_rows['name'].str.contains('MICRO|MINI|E-MINI|CBOT', case=False, na=False)]
                                    target_code = str(silver_rows['code'].iloc[0]) if not silver_rows.empty else str(df_search['code'].iloc[0])
                                    res = cftc_router.cot(code=target_code)
                                else:
                                    res = cftc_router.cot(code=fallback_code)
                            except Exception:
                                res = cftc_router.cot(code=fallback_code)
                    elif hasattr(obb, "regulators") and hasattr(obb.regulators, "cftc"):
                        try:
                            res = obb.regulators.cftc.cot(id="silver")
                        except Exception:
                            res = obb.regulators.cftc.cot(symbol="silver")
                    else:
                        raise AttributeError("CFTC router missing.")
                    return res.to_dataframe()

                df_cot = await asyncio.to_thread(openbb_cftc)
                if not df_cot.empty:
                    # Map columns for O(1) homogeneous pairing lookup
                    col_map = {str(c).lower().replace("_", "").replace(" ", ""): c for c in df_cot.columns}
                    
                    # Homogeneous Speculator Category Preferences (Managed Money preferred for professional sentiment)
                    spec_categories = [
                        ("managedmoney", "mmoney"),
                        ("noncommercial", "noncomm")
                    ]
                    
                    long_col, short_col = None, None
                    for cat_aliases in spec_categories:
                        for alias in cat_aliases:
                            # Find all columns matching speculator category and containing 'long' or 'short'
                            longs = [orig for clean, orig in col_map.items() if alias in clean and "long" in clean]
                            shorts = [orig for clean, orig in col_map.items() if alias in clean and "short" in clean]
                            if longs and shorts:
                                # Filter out percentage columns first to prioritize raw counts
                                raw_longs = [c for c in longs if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                                raw_shorts = [c for c in shorts if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                                if raw_longs and raw_shorts:
                                    long_col, short_col = raw_longs[0], raw_shorts[0]
                                else:
                                    long_col, short_col = longs[0], shorts[0]
                                break
                        if long_col and short_col:
                            break

                    if long_col and short_col:
                        df_valid = df_cot.dropna(subset=[long_col, short_col])
                        if not df_valid.empty:
                            latest_row = df_valid.iloc[-1]
                            long_val, short_val = float(latest_row[long_col]), float(latest_row[short_col])
                            
                            # Handle percentage scale detection (unified contract counts conversion)
                            # Patched: Robustly classify values <= 100.0 (but > 1.0) as percentages even if column lacks 'pct'
                            is_pct = ("pct" in str(long_col).lower() or "percent" in str(long_col).lower() or 
                                      (abs(long_val) <= 100.0 and abs(short_val) <= 100.0 and (abs(long_val) > 1.0 or abs(short_val) > 1.0)))
                            is_decimal_fraction = (abs(long_val) <= 1.0 and abs(short_val) <= 1.0)
                            
                            if is_pct or is_decimal_fraction:
                                if is_decimal_fraction:
                                    # 0.0 - 1.0 scale
                                    scale_mult = cftc_cfg["managed_money_multiplier_0_to_1"]
                                else:
                                    # 0 - 100 scale (e.g. 45.0)
                                    scale_mult = cftc_cfg["managed_money_multiplier_0_to_100"]
                                net_position = (long_val - short_val) * scale_mult
                            else:
                                # Raw Contract Counts
                                net_position = long_val - short_val
                                
                            with self.state_lock:
                                self.state_cache["cftc_net_longs"] = net_position
                                self.state_cache["cftc_status"] = "LIVE"
                                self.state_cache["cftc_ts"] = time.time()
                            print(f"[*] [CFTC Worker] Speculative net positioning synced successfully: {net_position:+,}")
                            await asyncio.sleep(standard_sleep)
                            continue
                
                # If df_cot is empty, treat as failure
                raise ValueError("Retrieved COT dataframe is empty.")

            except Exception as e:
                print(f"[!] [CFTC Worker] Error occurred: {e}")
                with self.state_lock:
                    self.state_cache["cftc_status"] = "DEGRADED_STALE"
                print(f"[*] [CFTC Worker] Status degraded. Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

    async def _comps_worker(self):
        while True:
            try:
                # 1. Peer Comps ev/oz — pass the LIVE FX so USD-listed peers convert at the current
                # rate, not the hardcoded 1.38 default (the EV/oz blend drifts with CAD otherwise).
                with self.state_lock:
                    _usd_to_cad = self.state_cache.get("usd_to_cad", 1.38)
                mean_peer_ev, peer_details, avg_disc_cost = await self.peer_engine.fetch_and_calculate_weighted_comps(usd_to_cad=_usd_to_cad)
                
                # 2. Forensic metrics — over the live book (membership is data-driven, not hardcoded).
                tickers = book_tickers(self.config)
                forensic_data = {}
                for t in tickers:
                    try:
                        m = await self.forensic_engine.fetch_forensic_metrics(t)
                        if m:
                            forensic_data[t] = m
                    except Exception as e:
                        print(f"[Comps Worker] Forensic metric fetch error for {t}: {e}")

                # 3. Barbell tickers historical returns
                barbell_tickers = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]
                df_rets, corr_matrix, vols = await self.sizer.fetch_historical_returns(barbell_tickers)
                # Separate (sizing-untouched) pull of the dominant commodity factors so the divergence
                # SENTINEL can regress each name on DATE-ALIGNED 60d factor returns for a context-aware β
                # + residual σ. Kept OUT of the barbell frame above so shrink_correlation / ES / sizing
                # stay byte-for-byte unchanged. 4h cadence (this worker) → never hammers; a failure just
                # drops the sentinel to its absolute gate (graceful).
                try:
                    factor_rets, _, _ = await self.sizer.fetch_historical_returns(["SI=F", "GC=F"])
                except Exception:
                    factor_rets = None
                # Long-window (120d) correlation matrix — feeds the correlation-DRIFT trend (60d vs 120d)
                # in the conventional-core independence monitor (correlation_monitor.assess_book_independence).
                # Separate + fenced so the 60d sizing/ES frame above stays byte-for-byte unchanged; a failure
                # just drops drift to n/a (graceful). Same 4h cadence → never hammers.
                try:
                    _wlong = int((self.config.get("correlation_monitor", {}) or {}).get("window_long", 120))
                    _, corr_matrix_long, _ = await self.sizer.fetch_historical_returns(barbell_tickers, lookback_days=_wlong)
                except Exception:
                    corr_matrix_long = None

                es_95 = -0.052          # signed decimal (negative = loss); overwritten by the live compute below
                port_vol = 0.40
                avg_corr = 0.45
                if df_rets is not None and not df_rets.empty:
                    # Derive the weight vector from the single barbell-weights source, ORDERED to the
                    # ticker list (the old literal np.array([0.60,0.15,0.10,0.15]) was one reorder from
                    # silently mis-weighting GMX vs URC).
                    _bw = _resolve_barbell_weights(self.config)
                    weights = np.array([_bw.get(t, 0.0) for t in barbell_tickers])
                    es_95 = self.sizer.robust_expected_shortfall(df_rets, weights)
                    port_returns = df_rets.dot(weights)
                    port_vol = float(port_returns.std() * np.sqrt(252))
                    corr_sum = 0.0
                    corr_count = 0
                    for i, t1 in enumerate(barbell_tickers):
                        for j, t2 in enumerate(barbell_tickers):
                            if i < j:
                                corr_sum += corr_matrix.get(t1, {}).get(t2, 0.0)
                                corr_count += 1
                    avg_corr = corr_sum / corr_count if corr_count > 0 else 0.0

                with self.state_lock:
                    self.state_cache["mean_peer_ev"] = mean_peer_ev
                    self.state_cache["peer_details"] = peer_details
                    self.state_cache["avg_disc_cost"] = avg_disc_cost
                    self.state_cache["peers_ts"] = time.time()
                    if forensic_data:
                        self.state_cache["forensic_metrics"].update(forensic_data)
                    if df_rets is not None:
                        self.state_cache["df_rets"] = df_rets
                        self.state_cache["corr_matrix"] = corr_matrix
                        self.state_cache["vols"] = vols
                        self.state_cache["es_95"] = es_95
                        self.state_cache["port_vol"] = port_vol
                        self.state_cache["avg_corr"] = avg_corr
                    self.state_cache["factor_rets"] = factor_rets   # 60d SI=F/GC=F returns → divergence β/σ
                    self.state_cache["corr_matrix_long"] = corr_matrix_long  # 120d ρ → correlation-drift trend
                print(f"[*] [Comps Worker] Synced weighted comps, returns, and forensics successfully.")
            except Exception as ex:
                print(f"[!] [Comps Worker] Error: {ex}")
            await asyncio.sleep(14400) # 4 hours

    # ==================== ORCHESTRATOR LOOP (INSTANT CPU-BOUND CALCULATIONS) ====================

    # ================= PHASE 5b — ADDITIVE ARCHETYPE INTEGRATION =================
    # The three helpers below bridge the Polymorphic Archetype Factory into the live
    # loop. They are pure-Python, side-effect-free w.r.t. the legacy valuation, and the
    # only entry point (_compute_archetype_valuations) is fully isolated in try/except.

    def _build_regime_impact_vector(self, mri_score: float, real_yield: float,
                                    silver_vol: float, dxy_mom: float,
                                    cfg: "dict | None" = None) -> tuple:
        """Derive the Druckenmiller-style RegimeImpactVector
        ``(alpha_option, alpha_margin, alpha_cyclical, alpha_yield, alpha_delta)`` from the
        live macro state, each clamped to [-1, 1]. Positive alpha = a tailwind for that
        archetype's lifecycle (lean in); negative = headwind (fade).

        Layer A is fully config-driven via ``archetype_factory.regime_derivation``: the
        normalization pivots/scales AND the per-alpha signal weights are read from config,
        with EVERY value falling back to the in-code default below if the block is missing or
        a key is absent/malformed — so behavior is identical to the prior hardcoded version
        until the JSON is actively tuned. Pivots double as center+scale; ``*_scale`` keys are
        pure denominators (guarded against zero). The live ``cfg`` is passed in by the loop so
        edits to the JSON take effect on the next cycle (no restart)."""
        def c(x: float) -> float:
            return max(-1.0, min(1.0, x))

        # In-code defaults == the original hardcoded constants (the safety fallback).
        D = {
            "mri_pivot": 50.0, "neg_yield_breakeven": 1.0, "neg_yield_scale": 2.0,
            "vol_pivot": 0.30, "dxy_scale": 2.0,
            "alpha_option":   {"risk_on": 0.45, "vol_edge": 0.35, "neg_yield": 0.20},
            "alpha_margin":   {"neg_yield": 0.55, "stress": 0.45},
            "alpha_cyclical": {"risk_on": 0.55, "vol_edge": 0.25, "weak_usd": 0.20},
            "alpha_yield":    {"neg_yield": 0.70, "risk_on": 0.15},
            "alpha_delta":    {"risk_on": 0.50, "weak_usd": 0.30, "vol_edge": 0.20},
        }
        cfg = cfg if cfg is not None else self.config
        try:
            der = (cfg or {}).get("archetype_factory", {}).get("regime_derivation", {})
            der = der if isinstance(der, dict) else {}
        except Exception:
            der = {}

        def num(key: str, nonzero: bool = False) -> float:
            """Config value for `key`, else the in-code default; guarded finite (and nonzero
            for denominators)."""
            try:
                v = der.get(key, None)
                v = float(v) if v is not None else float(D[key])
                if v != v:                              # NaN guard
                    v = float(D[key])
            except (TypeError, ValueError):
                v = float(D[key])
            return float(D[key]) if (nonzero and v == 0.0) else v

        def wmap(key: str) -> dict:
            w = der.get(key, None)
            return w if isinstance(w, dict) else D[key]

        mri_pivot = num("mri_pivot", nonzero=True)
        ny_be     = num("neg_yield_breakeven")
        ny_scale  = num("neg_yield_scale", nonzero=True)
        vol_pivot = num("vol_pivot", nonzero=True)
        dxy_scale = num("dxy_scale", nonzero=True)

        signals = {
            "risk_on":   c((mri_pivot - mri_score) / mri_pivot),     # >0 risk-on (low MRI), <0 stress
            "neg_yield": c((ny_be - real_yield) / ny_scale),         # >0 when real yields are low/negative
            "vol_edge":  c(((silver_vol or vol_pivot) - vol_pivot) / vol_pivot),  # >0 elevated silver vol
            "weak_usd":  c(-(dxy_mom or 0.0) / dxy_scale),           # >0 when the dollar is rolling over
        }
        signals["stress"] = max(0.0, -signals["risk_on"])           # only the stress side

        def alpha(key: str) -> float:
            w = wmap(key)
            total = 0.0
            for sig, val in signals.items():
                try:
                    total += float(w.get(sig, 0.0)) * val
                except (TypeError, ValueError):
                    continue
            return c(total)

        return (alpha("alpha_option"), alpha("alpha_margin"), alpha("alpha_cyclical"),
                alpha("alpha_yield"), alpha("alpha_delta"))

    # ---- commodity-aware tailwind plumbing (gold ≠ silver ≠ uranium; royalties share the lean) ----
    def _name_commodity(self, tkr: str) -> str:
        """The underlying metal for a name (drives its commodity tailwind). Spear = silver;
        ballast from the (now-corrected) config tags."""
        if tkr == "AGA.V":
            return "silver"
        return (self.config.get("ballast_valuation", {}).get(tkr, {}) or {}).get("commodity", "silver")

    def _uranium_mom(self):
        """Uranium momentum (its own regime signal), fetched once and cached ~6h. Defensive."""
        if getattr(self, "_uranium_mom_ts", 0) and (time.time() - self._uranium_mom_ts) < 21600:
            return getattr(self, "_uranium_mom_val", None)
        self._uranium_mom_ts = time.time()
        self._uranium_mom_val = None
        try:
            if getattr(self, "_md", None) is None:
                self._md = market_data.MarketData(fmp=getattr(self, "fmp", None))
            um = self._md.uranium_momentum()
            self._uranium_mom_val = (um or {}).get("value")
        except Exception:
            obs.swallow("feed.uranium_momentum")
        return self._uranium_mom_val

    def _commodity_signals(self, snap: dict = None) -> dict:
        """The live macro signals consumed by commodity_regime, split into the two channels:
        STRUCTURAL/forward (real_yield · gsr · uranium_term LEVELS) and near-term MOMENTUM
        (dxy_mom · uranium_mom · risk_on tape). The tailwind reads only the structural channel
        (action plan P1.1); momentum is surfaced separately and never enters the T pillar.

        Arch 5: the shared signals resolve through ONE macro_snapshot per cycle — pass the cycle's
        ``snap`` to reuse it; omitted (standalone/legacy call) it resolves fresh from terminal_state,
        identically. The neutral defaults (RY 2.0 · GSR 80.0 · dxy_mom 0.0) are THIS consumer's —
        the posture dial deliberately reads an absent signal as None instead (driver omitted)."""
        if snap is None:
            snap = macro_snapshot.snapshot(self.terminal_state)

        def d(key, default):
            v = snap.get(key)
            return default if v is None else v
        return {
            # structural (forward) — LEVELS the tailwind is built from
            "real_yield": d("real_yield", 2.0),
            "gsr": d("gsr", 80.0),
            "uranium_term": snap.get("uranium_term"),
            # near-term MOMENTUM (tape) — kept OUT of the structural tailwind; compute_momentum only
            "dxy_mom": d("dxy_mom", 0.0),
            "risk_on": d("risk_on", 0.0),
            "uranium_mom": self._uranium_mom() or 0.0,
        }

    def _commodity_regime_lean(self, commodity: str, signals: dict = None):
        """Commodity-specific STRUCTURAL (forward) regime lean ∈ [-1,1] from the live macro LEVELS.
        None on failure (the rating then falls back to the archetype+MRI blend — never a fabricated
        tailwind). Backward-looking momentum is deliberately excluded — see _commodity_momentum_lean.
        ``signals``: the resolved _commodity_signals dict (pass the cycle's copy to skip re-resolution)."""
        try:
            return commodity_regime.compute(commodity, **(signals or self._commodity_signals()))
        except Exception:
            return None

    def _commodity_momentum_lean(self, commodity: str, signals: dict = None):
        """Commodity near-term MOMENTUM ∈ [-1,1] — a SEPARATE, LABELED factor (action plan P1.1)
        surfaced for display/context only; it NEVER feeds the structural tailwind / the T pillar."""
        try:
            return commodity_regime.compute_momentum(commodity, **(signals or self._commodity_signals()))
        except Exception:
            return None

    def _fred_latest(self, series_id):
        """Latest value of a FRED series — OpenBB-FIRST. Delegates to _fred_recent (which tries
        ``obb.economy.fred_series`` BEFORE the anonymous CSV host) and takes the newest point, so the
        2Y cash anchor (DGS2) populates even where the FRED CSV endpoint is firewalled. The recurring
        FRED flakiness was precisely the CSV-only path going dormant behind a firewall; routing through
        OpenBB mirrors the b558f13 fix that lit Net-Liquidity/Breakeven back up. None on any failure —
        never fabricates."""
        pts = self._fred_recent(series_id, max_rows=12)
        return pts[-1][1] if pts else None

    @staticmethod
    def _bill_discount_to_bey(discount_pct, days: int = 91):
        """Convert a T-bill BANK-DISCOUNT rate (percent — how ^IRX is quoted) to a bond-equivalent
        yield (percent), so the 3M sits on the SAME investment basis as the coupon tenors
        (^FVX/^TNX/^TYX, quoted in yield). ^IRX uses a 360-day discount basis; mixing it raw with the
        coupon yields biases the front of the curve ~10bp LOW. Standard money-market identity for a
        bill with t ≤ 182 days:  BEY = (365·d) / (360 − d·t),  d = discount rate (decimal),
        t = days to maturity (13-week bill ≈ 91d). Returns the input UNCHANGED when the result would
        be non-finite or out of a sane band (never fabricates a nonsensical yield); None on bad input."""
        try:
            d = float(discount_pct) / 100.0
        except (TypeError, ValueError):
            return None
        t = float(days)
        denom = 360.0 - d * t
        if denom <= 0.0 or not (0.0 < d < 0.25):       # out of range → don't transform, return as-is
            return round(float(discount_pct), 3)
        return round((365.0 * d) / denom * 100.0, 3)

    def _fetch_treasury_curve_free(self):
        """VP (Phase-V completion): the full UST curve from FREE, sandbox-reachable feeds — yfinance
        index/futures tickers (^IRX 3M · 2YY=F 2Y · ^FVX 5Y · ^TNX 10Y · ^TYX 30Y) — replacing the
        plan-gated FMP treasury endpoint. ONE-BASIS curve (audit fix): the 2Y prefers CASH (FRED DGS2)
        over the 2YY=F FUTURE so the 2s10s steepener isn't a cash-vs-futures basis, and the 3M ^IRX
        bank-discount quote is converted to a bond-equivalent yield. Each tenor carries an as-of date
        and a ``basis`` tag (which instrument it came from). Cached ~3h on disk; returns the curve dict
        or None. (Pure data fetch; never fabricates a missing tenor.)"""
        cached = _load_from_disk_cache("treasury_curve_free", 3.0)
        if cached is not None:
            return cached["result"]
        tenors, asof, basis = {}, {}, {}
        tickmap = (("^IRX", "month3"), ("2YY=F", "year2"), ("^FVX", "year5"),
                   ("^TNX", "year10"), ("^TYX", "year30"))
        basis_tags = {"month3": "bill-discount→BEY (^IRX)", "year2": "future (2YY=F)",
                      "year5": "cash yield (^FVX)", "year10": "cash yield (^TNX)",
                      "year30": "cash yield (^TYX)"}
        try:
            # Deliberately re-imported at CALL time (not the module global): tests inject a stub
            # yfinance via sys.modules right before calling this (test_treasury_curve_basis).
            import yfinance as yf
            df = yf.download([t for t, _ in tickmap], period="5d", group_by="ticker", progress=False)
            lv0 = list(getattr(df.columns, "levels", [[]])[0]) if df is not None else []
            for tk, key in tickmap:
                try:
                    if tk in lv0:
                        s = df[tk]["Close"].dropna()
                        if len(s):
                            val = round(float(s.iloc[-1]), 3)
                            # ^IRX is a 360-day BANK-DISCOUNT rate; put the 3M on the coupon tenors'
                            # bond-equivalent basis so the front of the curve isn't ~10bp low.
                            if key == "month3":
                                bey = self._bill_discount_to_bey(val)
                                if bey is not None:
                                    val = bey
                            tenors[key] = val
                            asof[key] = str(s.index[-1].date())
                            basis[key] = basis_tags.get(key, "")
                except Exception:
                    obs.swallow("feed.treasury_curve")
        except Exception as e:
            print(f"[!] treasury curve yfinance fetch failed: {e}")
        # 2Y: prefer CASH (FRED DGS2) over the 2YY=F FUTURE so the 2s10s spread is cash-vs-cash, not a
        # cash-vs-futures basis (the future carries delivery/carry that contaminates the steepener
        # signal). DGS2 goes through the OpenBB-first _fred_latest, so it survives a firewalled CSV
        # host; the future (fetched above) stands as the fallback only when BOTH FRED paths miss.
        # Disk-cached ~3h + run off the event loop, so this never re-hammers FRED.
        y2_cash = self._fred_latest("DGS2")
        if y2_cash is not None:
            tenors["year2"] = round(y2_cash, 3)
            asof["year2"] = "FRED latest"
            basis["year2"] = "cash yield (FRED DGS2)"
        if not tenors:
            return None
        result = {"date": datetime.date.today().isoformat(), "tenors": tenors, "as_of": asof,
                  "basis": basis,
                  "source": ("free curve — 2Y cash DGS2 (2YY=F future fallback), 3M ^IRX→BEY, "
                             "5Y/10Y/30Y cash ^FVX/^TNX/^TYX"),
                  "cached": False}
        _save_to_disk_cache("treasury_curve_free", {"result": result})
        return result

    @staticmethod
    def _fred_points_from_df(df, max_rows=120):
        """Oldest→newest (date_str, value) points from a FRED-series DataFrame (date index, value in the
        first column) — the OpenBB path's parser. [] on empty/malformed. Pure (no network)."""
        try:
            if df is None or getattr(df, "empty", True):
                return []
            d = df.replace(".", np.nan).dropna().tail(max_rows)
            pts = []
            for idx, row in d.iterrows():
                dd = idx.date() if hasattr(idx, "date") else idx
                pts.append((str(dd)[:10], float(row.iloc[0])))
            return pts
        except Exception:
            return []

    def _fred_recent(self, series_id, max_rows=120):
        """Recent (date_str, value) points for a FRED series — for LEVEL + TREND. Tries OpenBB FIRST
        (``obb.economy.fred_series`` — the same path the engine's core macro metrics already use, and the
        one that works where the anonymous CSV host is firewalled), then the free anonymous CSV.
        Oldest→newest, last ``max_rows``; [] on any failure; never fabricates."""
        # Level 1 — OpenBB (works where the raw CSV endpoint is blocked; mirrors fetch_raw_fred)
        try:
            from openbb import obb
            if os.path.exists("FRED_API_KEY"):
                with open("FRED_API_KEY") as _f:
                    obb.user.credentials.fred_api_key = _f.read().strip()
            pts = self._fred_points_from_df(obb.economy.fred_series(series_id).to_dataframe(), max_rows)
            if pts:
                return pts
        except Exception:
            obs.swallow("fred.recent.openbb")
        # Level 2 — free anonymous CSV (sandbox-blocked in some envs)
        try:
            import requests
            import io
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(4, 6))
            if r.status_code == 200 and series_id in (r.text.splitlines()[0] if r.text else ""):
                d = pd.read_csv(io.StringIO(r.text)).replace(".", np.nan).dropna()
                if series_id in d.columns and not d.empty:
                    dc = d.columns[0]
                    d = d.tail(max_rows)
                    return [(str(row[dc]), float(row[series_id])) for _, row in d.iterrows()]
        except Exception as e:
            print(f"[!] FRED recent fetch failed for {series_id}: {e}")
        return []

    @staticmethod
    def _latest_and_prior(points, days_back=28):
        """From (date_str 'YYYY-MM-DD', value) points oldest→newest, return (latest, prior≈``days_back``
        before the latest). Date-matched, so mixed FRED frequencies align (weekly WALCL vs daily RRP).
        (None, None) on empty; (latest, None) if nothing is old enough."""
        if not points:
            return (None, None)

        def _d(s):
            try:
                return datetime.date.fromisoformat(str(s)[:10])
            except Exception:
                return None
        dated = [(_d(s), v) for s, v in points if _d(s) is not None]
        if not dated:
            return (None, None)
        latest_date, latest_val = dated[-1]
        target = latest_date - datetime.timedelta(days=days_back)
        prior = None
        for dt, v in dated:                          # last point on/before the target date
            if dt <= target:
                prior = v
        return (latest_val, prior)

    def _fetch_macro_quantities_free(self):
        """Fed net-liquidity legs (WALCL/WDTGAL/RRPONTSYD) + inflation-decomposition legs (DGS10 nominal,
        DFII10 real) from the free FRED CSV endpoint, each as (latest, ~4-week-prior) so the liquidity
        and inflation-regime monitors read both LEVEL and TREND.

        Cached ~6h on SUCCESS. A FAILURE (blocked endpoint) is NEGATIVELY cached (~30min retry) AND
        guarded by a single-series circuit-breaker, so an unreachable FRED costs ONE short request per
        ~30min — NOT five hanging requests every macro cycle (the perf regression this guards against:
        un-cached failures + sequential 10s timeouts were stalling the regime/holdings build ~50s/cycle).
        Returns a dict or None (blocked → None → monitors dormant); never fabricates."""
        cached = _load_from_disk_cache("macro_quantities_free", 6.0)
        if cached is not None and cached.get("result") is not None:
            return cached["result"]                          # fresh positive (<=6h)
        recent = _load_from_disk_cache("macro_quantities_free", 0.5)     # negative retry interval ~30min
        if recent is not None and recent.get("result") is None:
            return None                                      # recently probed & unreachable — don't re-hammer

        # circuit-breaker: probe ONE series; if FRED is unreachable, negatively cache and bail at once
        # (never hang sequentially on the other four).
        walcl_pts = self._fred_recent("WALCL")
        if not walcl_pts:
            _save_to_disk_cache("macro_quantities_free", {"result": None})
            return None

        def lp(points, days=28):
            return self._latest_and_prior(points, days)
        walcl = lp(walcl_pts)
        tga, rrp = lp(self._fred_recent("WDTGAL")), lp(self._fred_recent("RRPONTSYD"))
        nom, real = lp(self._fred_recent("DGS10")), lp(self._fred_recent("DFII10"))
        result = {"walcl": walcl, "tga": tga, "rrp": rrp, "nominal_10y": nom, "real_10y": real,
                  "source": "FRED free CSV (WALCL/WDTGAL/RRPONTSYD/DGS10/DFII10)"}
        _save_to_disk_cache("macro_quantities_free", {"result": result})
        return result

    def _rates_assessment(self):
        """P2.1 rates dashboard — the bear-steepener / fiscal-dominance UPSTREAM tell. Reads the rate
        LEVELS the engine already has (the free treasury_curve year2/5/10/30 + Fed funds), records a
        daily snapshot for the lookback window (so 'the long end rising over a window' is assessable),
        and returns the rates_monitor assessment. Defensive — None on any failure (never fabricates)."""
        try:
            import rates_monitor
            import rates_history
            m = self.terminal_state.get("metrics", {}) or {}

            def mv(*keys, default=None):
                return macro_snapshot.metric_value(m, *keys, default=default)

            def _f(x):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return None
            tc = (self.terminal_state.get("treasury_curve") or {}).get("tenors") or {}
            rates = {
                "dgs2": _f(tc.get("year2")),
                "dgs5": _f(tc.get("year5")),
                "dgs10": _f(tc.get("year10")) if tc.get("year10") is not None else _f(mv("10Y")),
                "dgs30": _f(tc.get("year30")) if tc.get("year30") is not None else _f(mv("30Y")),
                "fedfunds": _f(mv("EFFR", "FEDFUNDS")),
            }
            rates = {k: v for k, v in rates.items() if v is not None}
            if not rates:
                return None
            rates_history.record(rates)                       # idempotent daily snapshot
            window = int((self.config.get("rates_monitor") or {}).get("window_days", 21))
            prior = rates_history.prior_within(window)
            move = _f(mv("MOVE"))                              # None unless MOVE is wired (graceful)
            return rates_monitor.assess(rates, prior=prior, move=move, config=self.config)
        except Exception:
            return None

    def _productivity_assessment(self):
        """P2.2 AI-productivity thesis-breaker watch. Reads a BLS output/hour series + industry
        breadth if wired (terminal_state['productivity']); otherwise returns the monitor's graceful
        dormant read. Defensive — never fabricates a series."""
        try:
            import productivity_monitor
            p = self.terminal_state.get("productivity") or {}
            return productivity_monitor.assess(
                p.get("output_per_hour"), breadth=p.get("breadth"),
                industry_contributions=p.get("industry_contributions"),
                breadth_prior=p.get("breadth_prior"), config=self.config)
        except Exception:
            return None

    def _oil_supply_assessment(self):
        """P2.4 oil-supply-risk watch — objective proxies only (no intent score). Reads WTI/Brent/OVX
        + the futures front/deferred if wired; graceful (dormant) otherwise. Headlines are context only."""
        try:
            import oil_supply_monitor
            m = self.terminal_state.get("metrics", {}) or {}

            def mv(*keys, default=None):
                return macro_snapshot.metric_value(m, *keys, default=default)
            oil = self.terminal_state.get("oil") or {}
            return oil_supply_monitor.assess(
                wti=mv("WTI", "WTI_SPOT"), brent=mv("BRENT", "BRENT_SPOT"), ovx=mv("OVX"),
                front=oil.get("front"), deferred=oil.get("deferred"),
                headlines=oil.get("headlines"), config=self.config)
        except Exception:
            return None

    def _divergence_baseline(self, holdings):
        """Per-name β + residual σ for the divergence SENTINEL, regressed on DATE-ALIGNED 60d returns
        (the comps worker's ``df_rets[name]`` vs ``factor_rets[SI=F/GC=F]``) so 'decoupled' means beyond
        normal FOR THIS NAME (a +6% residual flags a low-vol royalty, not the high-vol spear). Falls
        back to the name's own total vol as a CONSERVATIVE σ when its factor history isn't cached. The
        math lives in the pure ``divergence_monitor``; this only marshals already-cached frames. Never
        raises (a thin/absent cache ⇒ the sentinel uses its absolute gate)."""
        out = {}
        try:
            sc = getattr(self, "state_cache", None) or {}
            df_rets, factor_rets, vols = sc.get("df_rets"), sc.get("factor_rets"), (sc.get("vols") or {})
            fac_sym = {"silver": "SI=F", "gold": "GC=F"}
            # NB: an Index is truthiness-ambiguous, so extract columns without `or []` boolean-coercion
            df_cols = list(df_rets.columns) if df_rets is not None and hasattr(df_rets, "columns") else []
            fr_cols = list(factor_rets.columns) if factor_rets is not None and hasattr(factor_rets, "columns") else []
            for h in (holdings or []):
                tk = (h or {}).get("ticker")
                if not tk:
                    continue
                fac_key, _ = divergence_monitor.factor_for(
                    commodity=(h or {}).get("commodity", ""), slot=(h or {}).get("slot", ""),
                    archetype=(h or {}).get("archetype", ""))
                sym = fac_sym.get(fac_key)
                name_r, factor_r = [], []
                if tk in df_cols and sym and sym in fr_cols:
                    try:                                       # date-align name & factor on common sessions
                        joined = pd.concat([df_rets[tk].rename("n"), factor_rets[sym].rename("f")],
                                           axis=1).dropna()
                        name_r = [float(x) for x in joined["n"].values]
                        factor_r = [float(x) for x in joined["f"].values]
                    except Exception:
                        name_r, factor_r = [], []
                av = vols.get(tk)                              # conservative fallback σ = own daily total vol
                fallback_sigma = (float(av) / (252.0 ** 0.5)) if _is_pos(av) else None
                out[tk] = divergence_monitor.baseline_from_returns(
                    name_r, factor_r, fallback_sigma=fallback_sigma)
        except Exception:
            obs.swallow("divergence.baseline")
        return out

    def _scenario_learned_observations(self):
        """Closed-outcome observations for the scenario-payoff learner (scenario_engine.assess): each
        VERIFIED (non-suspect) flywheel OUTCOME that carries a ``realized_scenario`` label →
        ``{slot, scenario, payoff∈[-1,1]}``. Payoff = the realized return saturated (a ±50% move ⇒ ±1).
        Read-only + best-effort: returns [] on any gap, so the payoff matrix stays a pure PRIOR until
        scenario-labeled outcomes exist — nothing fabricated. Slot resolves from config
        portfolio_metadata; the scenario was stamped at close from the live scenario weights."""
        try:
            lm = getattr(self, "_lm", None) or living_memory.LivingMemory()
            meta_pm = (self.config or {}).get("portfolio_metadata", {}) or {}
            NORM = 0.5                                  # a ±50% realized move saturates the payoff to ±1
            out = []
            for e in lm.query(type="outcome", limit=0):
                m = e.get("meta") or {}
                scen = str(m.get("realized_scenario") or "").strip().upper()
                if not scen or m.get("suspect"):        # unlabeled or quarantined (unverified mark) → skip
                    continue
                ret = m.get("signed")
                if ret is None:
                    ret = m.get("realized_return")
                slot = (meta_pm.get(e.get("ticker")) or {}).get("thesis_slot")
                if ret is None or not slot:
                    continue
                out.append({"slot": slot, "scenario": scen,
                            "payoff": max(-1.0, min(1.0, float(ret) / NORM))})
            return out
        except Exception:
            obs.swallow("scenario.learned_obs")
            return []

    def _divergence_assessment(self, holdings):
        """The automated decoupling SENTINEL — assess every holding's session move against its dominant
        commodity factor on real volume, reusing only already-cached data (prices-worker session returns
        + comps-worker 60d β/σ): NO new network. Returns the board dash; the per-cycle FIRING (pin +
        Living-Memory log, deduped) is done by ``_fire_divergence``."""
        sc = getattr(self, "state_cache", None) or {}
        snap = sc.get("divergence_inputs") or {}
        baseline = self._divergence_baseline(holdings)
        dash = divergence_monitor.assess_book(holdings, snapshot=snap, baseline=baseline, config=self.config)
        dash["as_of"] = snap.get("ts")
        return dash

    def _fire_divergence(self, div):
        """Auto-pin + auto-log each FRESH decoupling (deduped via ``state_cache['divergence_fired']``) so
        a stock-specific move surfaces on its card and in Living Memory WITHOUT the operator clicking
        Explain. Decision-support only — a pin + a 'sentinel' note, never a book action. Never raises."""
        flags = (div or {}).get("flags") or []
        if not flags:
            return
        today = datetime.date.today().isoformat()
        sc = getattr(self, "state_cache", None)
        fired = (sc or {}).get("divergence_fired") or {}
        fresh, fired_next = divergence_monitor.select_fresh(flags, fired, today=today)
        if isinstance(sc, dict):
            sc["divergence_fired"] = fired_next
        if not fresh:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code")}
        for r in fresh:
            tk = r.get("name")
            direction = str(r.get("direction") or "—")
            resid = (r.get("residual") or 0.0) * 100.0
            rvol = r.get("rvol") or 0.0
            basis = " σ-normalized" if r.get("decoupled_basis") == "sigma" else ""
            note = (f"SENTINEL: decoupled from {r.get('factor')} — {resid:+.1f}% unexplained on "
                    f"{rvol:.1f}× vol ({direction.lower()}){basis}. Run /explain-move.")
            try:                                               # 1) the clickable pin on the name's card
                self._agent_seq = int(getattr(self, "_agent_seq", 0)) + 1
                self.record_annotation({"action": "pin_insight", "seq": self._agent_seq, "agent": "sentinel",
                                        "args": {"ticker": tk, "badge": "⚡", "level": "warn",
                                                 "reason": note, "agent": "sentinel"}})
            except Exception:
                obs.swallow("divergence.pin")
            try:                                               # 2) the durable, regime-stamped event log
                lm = getattr(self, "_lm", None)
                if lm is None:
                    lm = living_memory.LivingMemory()
                    self._lm = lm
                lm.write("sentinel", text=note, ticker=tk, regime=regime, source="engine",
                         tags=["sentinel", "divergence", "auto", direction.lower()])
            except Exception:
                obs.swallow("divergence.log")

    # ==================== PREDICT ARB SCANNER (Wealthsimple Predict / Kalshi) ====================
    # Predict is a routed front-end to Kalshi, so the scanner prices the SOURCE venue's public book
    # (official market-data API, read-only by construction — kalshi_client has no order endpoints)
    # and treats the WS side as a friction model. ALL math lives in the pure predict_arb_monitor;
    # the engine legs below only fetch (worker), marshal (assessment) and fire (alerts). Alerts
    # only — the scanner NEVER executes; the operator trades in the Predict app.

    def _predict_cfg(self):
        return monitor_protocol.merged_config(
            predict_arb_monitor.DEFAULT_PREDICT_ARB_CONFIG, self.config, "predict_arb_monitor")

    def _predict_fetch_snapshot(self):
        """One two-stage fetch against Kalshi's public API: quotes for the configured series first,
        then orderbook DEPTH only for the tickers involved in candidate violations (rate-friendly).
        Blocking — the worker runs it via to_thread."""
        cfg = self._predict_cfg()
        client = getattr(self, "_kalshi", None)
        if client is None:
            client = kalshi_client.KalshiPublicClient()
            self._kalshi = client
        series = list(cfg.get("series") or []) or list(kalshi_client.DEFAULT_SERIES)
        snap = kalshi_client.build_snapshot(client, series=series)
        for tk in predict_arb_monitor.candidate_orderbook_tickers(snap, config=cfg):
            ob = client.get_orderbook(tk)
            if ob is not None:
                snap["orderbooks"][tk] = kalshi_client.parse_orderbook(ob)
        return snap

    async def _predict_worker(self):
        """PREDICT feed worker — polls the Kalshi public book on its own cadence and drops the
        normalized snapshot into state_cache for the eval loop's pure sweep (the eval cycle itself
        makes NO new network calls). Failures degrade to the stale snapshot, stamped — never a
        crash, never a fabricated book."""
        while True:
            interval = 300.0
            try:
                cfg = self._predict_cfg()
                interval = max(60.0, float(cfg.get("scan_interval_s", 300.0) or 300.0))
                snap = await asyncio.to_thread(self._predict_fetch_snapshot)
                with self.state_lock:
                    if snap.get("events"):
                        self.state_cache["predict_snapshot"] = snap
                        self.state_cache["predict_status"] = "LIVE"
                    else:
                        self.state_cache["predict_status"] = "DEGRADED_EMPTY"
                    self.state_cache["predict_ts"] = time.time()
                try:                    # the universe cache — what the scanner is sweeping, on disk
                    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "data", "predict_universe.json"), "w") as f:
                        json.dump({"ts": snap.get("ts"), "series": snap.get("series"),
                                   "events": [{**{k: e.get(k) for k in (
                                       "event_ticker", "series_ticker", "title", "category",
                                       "mutually_exclusive", "available_on_brokers")},
                                       "n_markets": len(e.get("markets") or [])}
                                       for e in (snap.get("events") or [])]}, f, indent=1)
                except OSError:
                    pass
            except Exception as e:
                print(f"[!] [Predict Worker] Error occurred: {e}")
                with self.state_lock:
                    self.state_cache["predict_status"] = "DEGRADED_STALE"
            await asyncio.sleep(interval)

    def _predict_fair_values(self):
        """The L2 lane's inputs: data/predict_fair_values.json → {market_ticker: {p_hat, band,
        source, as_of}}, written via /predict/fair_value (grounded-or-silent — a p̂ needs a source).
        Missing/corrupt file ⇒ {} → L2 stays silent while L1 is unaffected."""
        try:
            with open(PREDICT_FV_PATH) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_predict_fair_value(self, body):
        """Record a SOURCED first-principles probability for one Kalshi/Predict market — the L2
        model input (options-implied · OIS · nowcast · climatology · operator judgment). Grounded-
        or-silent: a source is REQUIRED; p_hat validated into [0,1]; band optional [lo, hi].
        Restatements overwrite the ticker's entry (the fired ledger keeps history)."""
        b = body or {}
        tk = str(b.get("ticker") or "").strip().upper()
        src = str(b.get("source") or "").strip()
        if not tk:
            return {"error": "ticker required (the Kalshi market ticker, e.g. KXFED-26SEP-T4.00)"}
        if not src:
            return {"error": "a source is required (grounded-or-silent — a p̂ needs provenance)"}
        try:
            p = float(b.get("p_hat"))
        except (TypeError, ValueError):
            return {"error": "p_hat must be a number in [0, 1]"}
        if p > 1.0 and p <= 100.0:
            p /= 100.0                              # accept percent form, same as record_conviction
        if not (0.0 <= p <= 1.0):
            return {"error": "p_hat must be in [0, 1] (or 0–100%)"}
        band = b.get("band")
        if band is not None:
            try:
                band = sorted([float(band[0]), float(band[1])])
                band = [max(0.0, band[0]), min(1.0, band[1])]
            except (TypeError, ValueError, IndexError):
                return {"error": "band must be [lo, hi] probabilities"}
        fv = self._predict_fair_values()
        fv[tk] = {"p_hat": round(p, 4), "band": band, "source": src,
                  "as_of": time.strftime("%Y-%m-%d"), "note": str(b.get("note") or "")[:300]}
        try:
            os.makedirs(os.path.dirname(PREDICT_FV_PATH), exist_ok=True)
            with open(PREDICT_FV_PATH, "w") as f:
                json.dump(fv, f, indent=1)
        except OSError as e:
            return {"error": f"could not persist fair values: {e}"}
        return {"ok": True, "ticker": tk, **fv[tk],
                "message": f"{tk} p̂={p:.2f} recorded; the L2 sweep uses it next cycle."}

    def _predict_arb_assessment(self):
        """Marshal the worker's cached snapshot + the sourced fair values into the pure sweep.
        NO network; a missing snapshot yields an honest 'warming up' dash, never a raise."""
        sc = getattr(self, "state_cache", None) or {}
        dash = predict_arb_monitor.assess_book(sc.get("predict_snapshot") or {},
                                               fair_values=self._predict_fair_values(),
                                               config=self.config)
        dash["status"] = sc.get("predict_status")
        dash["fetched_ts"] = sc.get("predict_ts")
        return dash

    def _fire_predict_arb(self, dash):
        """Auto-log each FRESH net-positive PREDICT opportunity (deduped via
        ``state_cache['predict_arb_fired']`` — once per basket per day, re-firing when the net
        widens ≥1¢): a Signals-rail note + a regime-stamped Living-Memory sentinel entry + an
        append-only predict_ledger line carrying the full pricing context at fire time (the
        scanner's own replay-gradeable track record). Alerts only; never a book action; never
        raises. The PREDICT twin of ``_fire_divergence``."""
        flags = (dash or {}).get("flags") or []
        if not flags:
            return
        today = datetime.date.today().isoformat()
        sc = getattr(self, "state_cache", None)
        fired = (sc or {}).get("predict_arb_fired") or {}
        fresh, fired_next = predict_arb_monitor.select_fresh(flags, fired, today=today)
        if isinstance(sc, dict):
            sc["predict_arb_fired"] = fired_next
        if not fresh:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code")}
        by_id = {o.get("id"): o for o in (dash or {}).get("opportunities") or []}
        for r in fresh:
            note = f"PREDICT: {r.get('text')}"
            try:                                               # 1) the cockpit Signals rail
                act = getattr(self, "record_agent_activity", None)
                if callable(act):
                    act({"agent": "predict", "kind": "note", "summary": note,
                         "ticker": r.get("event_ticker")})
            except Exception:
                obs.swallow("predict.activity")
            try:                                               # 2) the durable, regime-stamped log
                lm = getattr(self, "_lm", None)
                if lm is None:
                    lm = living_memory.LivingMemory()
                    self._lm = lm
                lm.write("sentinel", text=note, ticker=r.get("event_ticker"), regime=regime,
                         source="engine",
                         tags=["sentinel", "predict_arb", "auto",
                               str(r.get("lane") or "").lower(), str(r.get("kind") or "opp")])
            except Exception:
                obs.swallow("predict.log")
            try:                                               # 3) the append-only fired ledger
                os.makedirs(os.path.dirname(PREDICT_LEDGER_PATH), exist_ok=True)
                with open(PREDICT_LEDGER_PATH, "a") as f:
                    f.write(json.dumps(
                        {"ts": time.time(), "date": today,
                         **{k: r.get(k) for k in ("id", "lane", "kind", "event_ticker",
                                                  "net", "level")},
                         "opportunity": by_id.get(r.get("id")) or {},
                         "fees_model": (dash or {}).get("fees_model")}, default=str) + "\n")
            except Exception:
                obs.swallow("predict.ledger")

    async def predict_refresh(self):
        """On-demand fetch + sweep + fire (POST /predict/refresh ← the predict_scan MCP tool):
        the same pipeline as worker + eval cycle, compressed into one awaitable pass."""
        snap = await asyncio.to_thread(self._predict_fetch_snapshot)
        with self.state_lock:
            self.state_cache["predict_snapshot"] = snap
            self.state_cache["predict_status"] = "LIVE" if snap.get("events") else "DEGRADED_EMPTY"
            self.state_cache["predict_ts"] = time.time()
        dash = self._predict_arb_assessment()
        self.terminal_state["predict_arb"] = dash
        self._fire_predict_arb(dash)
        self.publish_state()
        return dash

    def _fire_correlation_drift(self, ci):
        """Auto-pin + auto-log each FRESH correlation-drift / conventional-redundant alarm (deduped via
        ``state_cache['correlation_fired']``) so a sleeve creeping into the spear's factor surfaces on its
        card and in Living Memory WITHOUT the operator asking. Decision-support only — a pin + a 'sentinel'
        note, never a book action. The trend companion to ``_fire_divergence``. Never raises."""
        flags = (ci or {}).get("flags") or []
        if not flags:
            return
        today = datetime.date.today().isoformat()
        sc = getattr(self, "state_cache", None)
        fired = (sc or {}).get("correlation_fired") or {}
        fresh, fired_next = correlation_monitor.select_fresh(flags, fired, today=today)
        if isinstance(sc, dict):
            sc["correlation_fired"] = fired_next
        if not fresh:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code")}
        for r in fresh:
            tk = r.get("ticker")
            level = r.get("level", "warn")
            note = f"SENTINEL: {r.get('text')}"
            try:                                               # 1) the clickable pin on the name's card
                self._agent_seq = int(getattr(self, "_agent_seq", 0)) + 1
                self.record_annotation({"action": "pin_insight", "seq": self._agent_seq, "agent": "sentinel",
                                        "args": {"ticker": tk, "badge": "🔗", "level": level,
                                                 "reason": note, "agent": "sentinel"}})
            except Exception:
                obs.swallow("correlation.pin")
            try:                                               # 2) the durable, regime-stamped event log
                lm = getattr(self, "_lm", None)
                if lm is None:
                    lm = living_memory.LivingMemory()
                    self._lm = lm
                lm.write("sentinel", text=note, ticker=tk, regime=regime, source="engine",
                         tags=["sentinel", "correlation", "auto", r.get("id") or "drift"])
            except Exception:
                obs.swallow("correlation.log")

    def _fire_conventional_zones(self, cz):
        """Auto-pin + auto-log each FRESH conventional-core zone cross / rebalance drift (deduped via
        ``state_cache['conventional_zones_fired']``) — a deep-value name crossing below its floor, a
        compounder crossing above its priced-in ceiling, a sleeve drifting off its target weight.
        Decision-support only; never a book action. Mirrors ``_fire_correlation_drift``. Never raises."""
        flags = (cz or {}).get("flags") or []
        if not flags:
            return
        today = datetime.date.today().isoformat()
        sc = getattr(self, "state_cache", None)
        fired = (sc or {}).get("conventional_zones_fired") or {}
        fresh, fired_next = conventional_sentinel.select_fresh(flags, fired, today=today)
        if isinstance(sc, dict):
            sc["conventional_zones_fired"] = fired_next
        if not fresh:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code")}
        for r in fresh:
            tk = r.get("ticker")
            level = r.get("level", "info")
            note = f"SENTINEL: {r.get('text')}"
            badge = "⚖" if r.get("id") == "rebalance_drift" else "📐"
            try:                                               # 1) the clickable pin on the name's card
                self._agent_seq = int(getattr(self, "_agent_seq", 0)) + 1
                self.record_annotation({"action": "pin_insight", "seq": self._agent_seq, "agent": "sentinel",
                                        "args": {"ticker": tk, "badge": badge, "level": level,
                                                 "reason": note, "agent": "sentinel"}})
            except Exception:
                obs.swallow("conventional.pin")
            try:                                               # 2) the durable, regime-stamped event log
                lm = getattr(self, "_lm", None)
                if lm is None:
                    lm = living_memory.LivingMemory()
                    self._lm = lm
                lm.write("sentinel", text=note, ticker=tk, regime=regime, source="engine",
                         tags=["sentinel", "conventional", "auto", r.get("id") or "zone"])
            except Exception:
                obs.swallow("conventional.log")

    def _fire_narrative_break(self, flags):
        """Auto-pin + auto-log each FRESH narrative break (a turnaround claim whose receipt REVERSED —
        the value-trap confirmation), deduped via ``state_cache['narrative_fired']``. Decision-support
        only; mirrors ``_fire_conventional_zones``. Never raises."""
        import narrative_integrity
        flags = flags or []
        if not flags:
            return
        today = datetime.date.today().isoformat()
        sc = getattr(self, "state_cache", None)
        fired = (sc or {}).get("narrative_fired") or {}
        fresh, fired_next = narrative_integrity.select_fresh(flags, fired, today=today)
        if isinstance(sc, dict):
            sc["narrative_fired"] = fired_next
        if not fresh:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code")}
        for r in fresh:
            tk = r.get("ticker")
            note = f"SENTINEL: {r.get('text')}"
            try:                                               # 1) the clickable pin on the name's card
                self._agent_seq = int(getattr(self, "_agent_seq", 0)) + 1
                self.record_annotation({"action": "pin_insight", "seq": self._agent_seq, "agent": "sentinel",
                                        "args": {"ticker": tk, "badge": "📰", "level": r.get("level", "warn"),
                                                 "reason": note, "agent": "sentinel"}})
            except Exception:
                obs.swallow("narrative.pin")
            try:                                               # 2) the durable, regime-stamped event log
                lm = getattr(self, "_lm", None)
                if lm is None:
                    lm = living_memory.LivingMemory()
                    self._lm = lm
                lm.write("sentinel", text=note, ticker=tk, regime=regime, source="engine",
                         tags=["sentinel", "narrative", "auto", "break"])
            except Exception:
                obs.swallow("narrative.log")

    def _research_book_floor(self, tkr: str):
        """Real book-value/share floor (CAD) for a ballast name from the sourced research cache —
        replaces the 10%×reference placeholder. None when unsourced (engine keeps its own floor)."""
        try:
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            bv = self._rc.value(tkr, "book_value_per_share")
            if bv is None:
                return None
            # Integrity guard (same as _research_book_native): a 10× units slip in book value would
            # otherwise collapse the ballast floor. Reconcile against (equity − goodwill) ÷ shares.
            bv_rec, ok, note = research_cache.reconciled_book_value(
                bv, self._rc.value(tkr, "total_equity"), self._rc.value(tkr, "shares_out"),
                goodwill=self._rc.value(tkr, "goodwill"))
            if not ok:
                logging.warning("[book-value] %s floor reconciled: %s", tkr, note)
            bv = bv_rec if bv_rec is not None else bv
            fx = 1.0
            if str(self._rc.value(tkr, "currency") or "CAD").upper() == "USD":
                try:
                    if getattr(self, "_md", None) is None:
                        self._md = market_data.MarketData(fmp=getattr(self, "fmp", None))
                    fx = (self._md.yahoo_quote("USDCAD=X") or {}).get("price") or 1.39
                except Exception:
                    fx = 1.39
            return float(bv) * float(fx)
        except Exception:
            return None

    def _live_spots_usd(self) -> dict:
        """The live USD spots the engine already fetches, keyed for nav_mark's two-tier resolve
        (gold GC=F · silver SI=F · copper HG=F). Uranium has no live feed — it stays stamped."""
        prices = (self.state_cache.get("prices") or {}) if isinstance(
            getattr(self, "state_cache", None), dict) else {}
        return {"gold": prices.get("GC=F"), "silver": prices.get("SI=F"),
                "copper": prices.get("HG=F")}

    def _research_book_native(self, tkr: str, allow_book: bool = True):
        """Sourced book/NAV per share in the name's NATIVE currency (no FX) + its currency, from the
        research cache. Preference order (V1 mark-NAV-to-spot):
          1. ``nav_inventory`` — structured inputs recomputed LIVE each cycle (inventory × spot ×
             FX, carrying as the NRV floor; nav_mark.py). Quality/staleness stashed in
             ``self._nav_quality[tkr]`` for the ribbon + Story Card.
          2. ``nav_adj_per_share`` — the static hand-stamped mark (the dark-ship fallback).
          3. ``book_value_per_share`` — raw accounting book (only when ``allow_book`` is True).
        ``allow_book=False`` returns None unless a GENUINE NAV mark (tier 1/2) exists — callers that
        need a fair-value anchor use this, because raw accounting book systematically understates NAV
        for holdco/royalty/physical structures and would inject false downside. None when unsourced."""
        try:
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            if not hasattr(self, "_nav_quality"):
                self._nav_quality = {}
            ccy = str(self._rc.value(tkr, "currency") or "CAD").upper()
            # 1) live compute from structured inventory (ships dark behind the static fallback)
            inv = self._rc.value(tkr, "nav_inventory")
            if isinstance(inv, dict):
                try:
                    import nav_mark
                    fx = self.state_cache.get("usd_to_cad") if isinstance(
                        getattr(self, "state_cache", None), dict) else None
                    mark = nav_mark.nav_from_inventory(inv, live_spots=self._live_spots_usd(),
                                                       usd_to_cad=fx or 1.38)
                    if mark and mark.get("nav_per_share") and mark["nav_per_share"] > 0:
                        self._nav_quality[tkr] = mark
                        return float(mark["nav_per_share"]), ccy
                except Exception as e:
                    logging.warning("[NAV-mark] %s live compute failed (falling back to static): %s",
                                    tkr, e)
            # 2) static spot-adjusted NAV — accounting book understates NAV for names that carry
            #    physical inventory at cost (e.g. URC.TO uranium holdings).
            nav_adj = self._rc.value(tkr, "nav_adj_per_share")
            if nav_adj is not None and float(nav_adj) > 0:
                self._nav_quality.pop(tkr, None)            # static mark: no live-quality claim
                return float(nav_adj), ccy
            bv = self._rc.value(tkr, "book_value_per_share")
            if bv is None or not allow_book:
                return None
            # Integrity guard: cross-check the sourced book-value/share against (equity − goodwill) ÷
            # shares — a units/decimal slip in one field (the GROY 10× error) would otherwise collapse
            # the floor unnoticed. On a gross divergence the self-consistent equity-derived value wins.
            bv_rec, ok, note = research_cache.reconciled_book_value(
                bv, self._rc.value(tkr, "total_equity"), self._rc.value(tkr, "shares_out"),
                goodwill=self._rc.value(tkr, "goodwill"))
            if not ok:
                logging.warning("[book-value] %s reconciled: %s", tkr, note)
            return (float(bv_rec) if bv_rec is not None else float(bv)), ccy
        except Exception:
            return None

    def _holdco_ladder_cad(self, tkr: str, cfg: dict):
        """The SOURCED layered-NAV ladder for a royalty/holdco (holdco_nav), FX-normalized to the CAD the
        rating uses, so φ/upside stay clean ratios:
          * ``bear``  = hard floor (producing DCF net of G&A + net liquid) — the REP-equivalent margin of
                        safety that SUPERSEDES the cost-basis book proxy (book is 'the labelled fallback,
                        never the override' — this is the override it was waiting for).
          * ``base``  = risked NAV (floor + Σ pipeline NPV × stage-probability) — the fair value that
                        replaces the DEGRADED anchor behind GMX's negative-upside artifact.
          * ``bull``  = blue sky (+ optionality) — currently == base until the optionality lens is built.
        ``floor_sourced`` gates the bear wire; ``pipeline_sourced`` gates the base/bull wire (without a
        sourced pipeline, risked NAV == floor, so wiring base would just re-create a negative — we don't).
        Fail-safe: any error → None (keep the existing legs), never a raise into the rating path."""
        try:
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            res = holdco_nav_feed.assess_from_cache(self._rc, tkr)
            feed = res.get("feed") or {}
            if not (res.get("available") and feed.get("floor_sourced") and _is_pos(res.get("hard_floor_ps"))):
                return None                                # not fully fed → keep the existing legs
            bv = (cfg.get("ballast_valuation", {}) or {}).get(tkr, {}) or {}
            pmd = (cfg.get("portfolio_metadata", {}) or {}).get(tkr, {}) or {}
            ccy = str(bv.get("currency") or pmd.get("currency") or "CAD").upper()
            fx = float(self.state_cache.get("usd_to_cad") or 1.38) if ccy == "USD" else 1.0
            return {"bear": float(res["hard_floor_ps"]) * fx,
                    "base": float(res.get("risked_nav_ps") or res["hard_floor_ps"]) * fx,
                    "bull": float(res.get("blue_sky_ps") or res["hard_floor_ps"]) * fx,
                    "floor_sourced": True, "pipeline_sourced": bool(feed.get("pipeline_sourced"))}
        except Exception as e:
            logging.warning("[holdco-ladder] %s sourced NAV-ladder read failed: %s", tkr, e)
            return None

    def _holdco_fair_value_cad(self, tkr: str, cfg: dict, *, mode: str,
                               price_cad=None, floor_cad=None):
        """The archetype-aware CENTRAL fair value (holdco_nav.central_fair_value), FX-normalized to the
        CAD the rating uses, with the PURE anti-crush wire gate carried through:
          * ``mode='royalty'`` → tangible carried-book NAV = (total_equity − goodwill)/shares. The
            audited mark of EVERY owned royalty — the fair value the producing-CF floor (bear) and the
            modelled-pipeline ladder both miss. This is what makes a name like GROY read CHEAP vs its
            book instead of reverting to a degraded anchor.
          * ``mode='holdco'`` (PG) → net-liquid floor + risked modelled pipeline + a peer portfolio mark;
            pipeline-only ⇒ LOW confidence, which the wire gate REFUSES to assert below price (the GMX
            anti-crush — it waits for a sourced peer mark rather than manufacturing a false negative).
        The caller wires ``base`` to ``fair_value_ps`` ONLY when ``wire`` is true. Fail-safe: any error →
        None (keep the existing fair-value anchor), never a raise into the rating path."""
        try:
            import holdco_nav as _hn
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            raw = holdco_nav_feed.fair_value_inputs_from_cache(self._rc, tkr)
            sh = _hn._num(raw.get("shares"))
            if not (sh and sh > 0):
                return None                                    # no share count → can't go per-share
            bv = (cfg.get("ballast_valuation", {}) or {}).get(tkr, {}) or {}
            pmd = (cfg.get("portfolio_metadata", {}) or {}).get(tkr, {}) or {}
            ccy = str(raw.get("currency") or bv.get("currency") or pmd.get("currency") or "CAD").upper()
            fx = float(self.state_cache.get("usd_to_cad") or 1.38) if ccy == "USD" else 1.0

            def _cad(x):
                v = _hn._num(x)
                return v * fx if v is not None else None

            rp_cad = 0.0
            if raw.get("pipeline_assets"):                     # holdco floor+pipeline base, NPV native → CAD
                rp = _hn.risked_pipeline_from_assets(raw["pipeline_assets"], config=cfg).get("risked_pipeline_value")
                rp_cad = _cad(rp) or 0.0
            return _hn.central_fair_value(
                mode=mode, price=price_cad, shares=sh,
                total_equity=_cad(raw.get("total_equity")), goodwill=_cad(raw.get("goodwill")),
                equity_confidence=raw.get("equity_confidence") or "high",
                hard_floor_ps=floor_cad, risked_pipeline_value=rp_cad,
                peer_portfolio_value=_cad(raw.get("peer_portfolio_value")),
                rerated_book_value=_cad(raw.get("rerated_book_value")),    # gated by config royalty_rerate.enabled
                rerated_confidence=raw.get("rerated_confidence") or "med",
                rerated_verified=bool(raw.get("rerated_verified")),        # verify-before-wire (independent verifier)
                blue_sky_value=_cad(raw.get("blue_sky_value")),            # verified dev-pipeline increment → bull leg
                blue_sky_verified=bool(raw.get("blue_sky_verified")),
                config=cfg)
        except Exception as e:
            logging.warning("[holdco-fv] %s central fair value read failed: %s", tkr, e)
            return None

    def _ingestion_overlay_data(self) -> dict:
        """Phase 6: load ``data/ingestion_cache.json`` once, memoized by file mtime.
        Returns the cached ``{'macro': ..., 'tickers': ...}`` dict, or ``{}`` when the
        cache is absent (the normal pre-ingestion state) or unreadable. Never raises, so
        the orchestrator can never be brought down by the ingestion layer."""
        if load_ingestion_cache is None:
            return {}
        path = "data/ingestion_cache.json"
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return {}                                      # no cache yet -> silent no-op
        if getattr(self, "_ingestion_mtime", None) == mtime:
            return self._ingestion_overlay_cached
        env = load_ingestion_cache(path)
        data = env.get("data", {}) if isinstance(env, dict) else {}
        self._ingestion_mtime = mtime
        self._ingestion_overlay_cached = data or {}
        if data:
            logging.info("[Ingestion] overlay loaded from %s (%d tickers; macro: %s)",
                         path, len(data.get("tickers", {})), ",".join(sorted(data.get("macro", {}))))
        else:
            logging.warning("[Ingestion] cache present but empty/unreadable: %s", path)
        return self._ingestion_overlay_cached

    def _apply_ingestion_overlay(self, ticker: str, payload: dict) -> None:
        """Overlay cached open-source ingestion data onto a live-built payload. Live
        worker feeds take precedence; the cache only fills gaps. Fully graceful — an
        absent/stale cache is a no-op, so the legacy path is byte-for-byte unchanged
        when no ingestion cache is present."""
        data = self._ingestion_overlay_data()
        if not data:
            return
        macro = payload.setdefault("macro", {})
        for key, value in (data.get("macro") or {}).items():
            if macro.get(key) is None:
                macro[key] = value
        tov = (data.get("tickers") or {}).get(ticker) or {}
        for section in ("financials", "comps", "conviction_signals"):
            src = tov.get(section)
            if not src:
                continue
            dst = payload.get(section)
            if not isinstance(dst, dict):
                dst = {}
                payload[section] = dst
            for key, value in src.items():
                if dst.get(key) is None:
                    dst[key] = value
        if payload.get("shares_out") is None and tov.get("shares_out") is not None:
            payload["shares_out"] = tov["shares_out"]

    def _ingestion_status(self) -> dict:
        """Phase 6c: summarize the open-source ingestion cache (data/ingestion_cache.json)
        for the cockpit — availability, per-source freshness, and overlay coverage. Purely
        additive and read-only; returns a small JSON-safe dict and never raises."""
        if load_ingestion_cache is None:
            return {"available": False, "reason": "module_absent"}
        env = load_ingestion_cache("data/ingestion_cache.json")
        if not isinstance(env, dict):
            return {"available": False, "reason": "no_cache"}
        now = time.time()
        generated_at = env.get("generated_at")
        age = max(0.0, now - generated_at) if generated_at else None
        ttl = env.get("ttl_seconds")
        stale = bool(age is not None and ttl and age > ttl)
        cache_data = env.get("data") if isinstance(env.get("data"), dict) else {}
        sources = {}
        for name, meta in (env.get("sources") or {}).items():
            meta = meta if isinstance(meta, dict) else {}
            fetched_at = meta.get("fetched_at")
            sources[name] = {
                "status": meta.get("status", "unknown"),
                "age_minutes": round((now - fetched_at) / 60.0, 1) if fetched_at else None,
            }
        return {
            "available": True,
            "schema_version": env.get("schema_version"),
            "generated_at": generated_at,
            "age_minutes": round(age / 60.0, 1) if age is not None else None,
            "ttl_seconds": ttl,
            "stale": stale,
            "sources": sources,
            "ticker_count": len(cache_data.get("tickers", {})),
            "macro_keys": sorted(cache_data.get("macro", {})),
        }

    def _archetype_payload(self, ticker: str, cfg: dict, prices: dict, macro: dict,
                           dynamic_aisc: float, mean_peer_ev: float, forensic_metrics: dict) -> dict:
        """Assemble the per-ticker ``data_payload`` for the archetype factory from live state.
        Ballast names read ref_price / spot_ref / currency from config automatically, so their
        market & cost legs are fully live; income-leg inputs not present in the live feed
        (royalty cash flow, mine production) simply degrade out of the confidence-tilted blend."""
        bv = cfg.get("ballast_valuation", {}).get(ticker, {})
        fin = dict(forensic_metrics.get(ticker, {}))
        pmeta = cfg.get("portfolio_metadata", {}).get(ticker, {}) if isinstance(
            cfg.get("portfolio_metadata"), dict) else {}
        payload: dict = {
            "currency": bv.get("currency", "CAD"),
            "price": prices.get(ticker),
            "macro": dict(macro),
            "comps": {},
            "financials": fin,
            # 3rd taxonomy axis (display/correlation only; valuation unchanged): the sub-archetype
            # overlay + orthogonal sector tags, surfaced through the valuation summary.
            "subarchetype": pmeta.get("subarchetype"),
            "sector_tags": pmeta.get("sector_tags", []),
        }
        # Surface the ballast anchors so the archetype's market leg sees the SAME spot_ref it scales
        # against (_commodity_spot returns spot_ref for non-silver -> an exact neutral 1.0 factor;
        # absent these it would fall back to live silver spot and mis-scale the gold/uranium names).
        if bv:
            if bv.get("spot_ref") is not None:
                payload["spot_ref"] = bv.get("spot_ref")
            if bv.get("commodity"):
                payload["commodity"] = bv.get("commodity")
            # NO-HARDCODE: drive the intrinsic off the SOURCED NAV per share when we have it.
            # _research_book_native prefers nav_adj_per_share (spot-adjusted NAV) over the raw
            # accounting book_value_per_share, so names like URC.TO whose IFRS book understates NAV
            # (uranium at cost/NRV, not spot) get a market-leg anchor that reflects true NAV.
            #
            # Separation of concerns: book_value_per_share → cost leg (the thin asset-light floor);
            # nav_adj_per_share (or falling back to config ref_price) → ref_price market leg anchor.
            # The two can legitimately diverge — carrying-value book IS the floor, but the market
            # leg should reflect economic NAV (spot-marked inventory + royalty NPV), not IFRS cost.
            nat = self._research_book_native(ticker)
            if nat is not None:
                bv_native, bv_ccy = nat
                if _is_pos(bv_native):
                    payload["book_value_per_share"] = bv_native      # cost leg: accounting floor
                    payload["ref_price"] = bv_native                 # market-leg NAV anchor (sourced)
                    payload["currency"] = bv_ccy
            # If only raw book_value_per_share is available (no nav_adj), also set it on the cost
            # leg but do NOT override ref_price — the config ref_price is a better market anchor
            # than an understated accounting book (relevant for URC.TO before nav_adj is sourced).
            else:
                try:
                    if getattr(self, "_rc", None) is None:
                        self._rc = research_cache.ResearchCache()
                    raw_bv = self._rc.value(ticker, "book_value_per_share")
                    if raw_bv is not None and float(raw_bv) > 0:
                        bv_ccy = str(self._rc.value(ticker, "currency") or "CAD").upper()
                        payload["book_value_per_share"] = float(raw_bv)  # cost floor only
                        payload["currency"] = bv_ccy
                        # ref_price intentionally NOT overridden — config value is the NAV anchor
                except Exception:
                    pass
        if ticker == "AGA.V":
            # the Option-Convexity spear: live peer comp + dynamic AISC, plus a best-effort
            # explorer forensic feed (treasury & burn from config, dilution from the live feed)
            payload["shares_out"] = cfg.get("aga_shares_out")
            payload["aisc"] = dynamic_aisc
            payload["currency"] = "CAD"
            payload["comps"] = {"peer_ev_oz": mean_peer_ev}
            fin.setdefault("cash", cfg.get("rep_floor_params", {}).get("cash_treasury_m", 0.0) * 1e6)
            fin.setdefault("monthly_burn", cfg.get("cash_burn", {}).get("monthly_burn_rate"))
            if "sga_t0" in fin:
                fin.setdefault("sga_expense", fin["sga_t0"])
        self._apply_ingestion_overlay(ticker, payload)
        return payload

    def _register_eval_names(self, cfg: dict, router) -> None:
        """Hot-register newly promoted EVAL names (``portfolio_metadata[t].eval_only``) onto the
        archetype router so a promotion rates on the NEXT engine cycle — no restart. Mirrors
        build_default_router's routing precedence (explicit archetype, else the type map); an
        unknown archetype is skipped explicitly, never guessed. Idempotent and non-fatal."""
        try:
            from archetypes import ARCHETYPE_BY_TYPE, ARCHETYPE_REGISTRY
            known = set(router.registered_tickers())
            routing = {**ARCHETYPE_BY_TYPE, **(cfg.get("archetype_routing") or {})}
            for tkr in eval_only_tickers(cfg):
                if tkr in known:
                    continue
                meta = (cfg.get("portfolio_metadata") or {}).get(tkr) or {}
                name = meta.get("archetype") or routing.get(str(meta.get("type", "")).lower())
                cls = ARCHETYPE_REGISTRY.get(name) if isinstance(name, str) else None
                if cls is None:
                    logging.warning("eval name %s skipped: unknown archetype %r", tkr, name)
                    continue
                router.register_asset(tkr, cls(tkr, cfg, fx_rates=getattr(router, "fx_rates", None)),
                                      label=f"{meta.get('type', '?')}/{meta.get('stage', '?')} [eval]")
                logging.info("eval name %s hot-registered (archetype %s)", tkr, name)
        except Exception as e:                            # supplementary; never crashes the loop
            logging.warning("eval-name registration skipped (non-fatal): %s", e)

    def _compute_archetype_valuations(self, *, cfg: dict, prices: dict, spot_ag: float,
                                      gold: float, real_yield: float, silver_vol: float,
                                      dynamic_aisc: float, capital_discount_factor: float,
                                      mean_peer_ev: float, usd_to_cad: float, mri_score: float,
                                      dxy_mom: float, forensic_metrics: dict) -> dict:
        """Value every registered portfolio name through the Polymorphic Archetype Factory,
        in PARALLEL with the legacy valuation. Pure supplement — a per-ticker failure
        (incl. TickerNotRegisteredError) is captured per name and never propagates, so the
        main loop cannot crash. Returns the dict stored at
        ``terminal_state['archetype_valuation_detail']``."""
        router = self.archetype_router
        if router is None:
            return {"status": "unavailable", "results": {}}
        self._register_eval_names(cfg, router)

        regime_vector = self._build_regime_impact_vector(mri_score, real_yield, silver_vol, dxy_mom, cfg=cfg)
        macro = {"spot_ag": spot_ag, "gold": gold, "real_yield": real_yield,
                 "silver_vol": silver_vol, "capital_discount": capital_discount_factor,
                 "y30": self.state_cache.get("y30")}
        weights = {k: v for k, v in cfg.get("archetype_barbell_weights",
                   {"AGA.V": 0.60, "URC.TO": 0.15, "GROY": 0.15, "GMX.TO": 0.10}).items()
                   if not str(k).startswith("_")}

        results: dict = {}
        book_cad = 0.0
        for ticker in router.registered_tickers():
            try:
                # Push the LIVE USD->CAD rate onto the registered instance (the router was built
                # at init from a config snapshot) so USD names (GROY) normalize to CAD correctly.
                router.resolve(ticker).fx_rates["USD"] = usd_to_cad
                payload = self._archetype_payload(ticker, cfg, prices, macro, dynamic_aisc,
                                                  mean_peer_ev, forensic_metrics)
                summary = router.get_valuation(ticker, payload, regime_vector)
                results[ticker] = summary
                book_cad += weights.get(ticker, 0.0) * summary.get("intrinsic_after_forensic", 0.0)
            except TickerNotRegisteredError as e:
                results[ticker] = {"status": "not_registered", "error": str(e)}
            except Exception as e:                       # supplementary block must never crash the loop
                logging.warning("Phase 5b archetype valuation failed for %s (non-fatal): %s", ticker, e)
                results[ticker] = {"status": "error", "error": str(e)}

        # Stash the live inputs so on-demand what-if (run_whatif / POST /action/whatif) can
        # revalue any name against the very same base the dashboard is showing.
        self._whatif_base = {
            "macro": dict(macro), "regime_vector": list(regime_vector),
            "prices": dict(prices), "forensic_metrics": forensic_metrics,
            "dynamic_aisc": dynamic_aisc, "mean_peer_ev": mean_peer_ev,
            "usd_to_cad": usd_to_cad, "mri": mri_score, "real_yield": real_yield,
            "silver_vol": silver_vol, "dxy_mom": dxy_mom,
        }
        return {
            "status": "live",
            "regime_impact_vector": {name: round(v, 4) for name, v in zip(REGIME_ORDER, regime_vector)},
            "results": results,
            "barbell": {"weights": weights, "blended_intrinsic_cad": round(book_cad, 4)},
            "correlation_groups": router.correlation_groups(),
        }

    def run_whatif(self, ticker, overrides):
        """On-demand scenario revaluation (Iteration 2 action spine). Re-runs the archetype
        valuation for one name against the LAST live inputs with macro/peer/regime overrides and
        diffs base vs scenario. Backs POST /action/whatif and the run_valuation_whatif MCP tool, so
        a GUI button, the /whatif cockpit command and the agents all share one implementation."""
        from valuation_actions import (parse_overrides, parse_override, summarize_delta,
                                       REGIME_KEYS, MACRO_KEYS)
        router = self.archetype_router
        base = getattr(self, "_whatif_base", None)
        if router is None or base is None:
            return {"error": "engine warming up — no base valuation yet; retry shortly"}
        ticker = ticker or self.ui.focused_ticker          # default to whatever the GUI is showing
        if not ticker:
            return {"error": "no ticker given and no focused ticker in the GUI"}
        try:
            router.resolve(ticker)
        except Exception:
            return {"error": f"unknown ticker {ticker!r}", "available": list(router.registered_tickers())}
        # A bare overrides string naming a saved scenario loads that scenario's knobs.
        if (isinstance(overrides, str) and overrides.strip() and "=" not in overrides
                and getattr(self, "dconfig", None) is not None):
            scen = self.dconfig.get_scenario(overrides.strip())
            if scen:
                overrides = scen
        ov = parse_overrides(overrides)
        if not ov:
            return {"error": "no recognized overrides",
                    "knobs": ["silver", "gold", "ry", "vol", "peer", "mri", "dxy"],
                    "example": "silver=+5 ry=-0.5 peer=+20%"}

        cfg = self.config
        prices = base["prices"]; macro0 = base["macro"]; fm = base["forensic_metrics"]
        aisc = base["dynamic_aisc"]; peer0 = base["mean_peer_ev"]
        try:
            router.resolve(ticker).fx_rates["USD"] = base["usd_to_cad"]
        except Exception:
            pass

        # Base (recompute for an apples-to-apples diff against the scenario).
        base_payload = self._archetype_payload(ticker, cfg, prices, macro0, aisc, peer0, fm)
        base_summary = router.get_valuation(ticker, base_payload, base["regime_vector"])

        # Scenario: apply overrides to macro / peer / regime scalars.
        applied = {}
        macro_s = dict(macro0); peer_s = peer0
        rs = {"mri": base["mri"], "real_yield": base["real_yield"],
              "silver_vol": base["silver_vol"], "dxy": base["dxy_mom"]}
        regime_dirty = False
        for k, spec in ov.items():
            try:
                if k == "peer_ev_oz":
                    peer_s = parse_override(spec, peer0)
                    applied[k] = {"from": peer0, "to": round(peer_s, 4)}
                elif k in MACRO_KEYS:
                    cur = macro0.get(k); newv = parse_override(spec, cur)
                    macro_s[k] = newv; applied[k] = {"from": cur, "to": round(newv, 4)}
                    if k in REGIME_KEYS:
                        rs[k] = newv; regime_dirty = True
                elif k in REGIME_KEYS:           # mri / dxy (not macro fields)
                    cur = rs.get(k); newv = parse_override(spec, cur)
                    rs[k] = newv; applied[k] = {"from": cur, "to": round(newv, 4)}
                    regime_dirty = True
            except ValueError as e:
                return {"error": str(e)}

        # A silver move MUST reprice an explorer whose value rides peer EV/oz. The live comps already
        # embed the current metal level, so in a hypothetical we scale peer EV/oz with the operating
        # margin (spot − industry AISC) — a convex response — unless the user set peer by hand. Uses the
        # SAME peer_ev_margin_scaled helper as the scenario tornado so the two surfaces agree. Scoped to
        # the what-if only: base valuations and ratings are untouched.
        if "spot_ag" in applied and "peer_ev_oz" not in applied and peer0:
            aisc_ref = float(cfg.get("dynamic_discovery_v5", {}).get("estimated_industry_aisc_2026", 24.5) or 24.5)
            s0 = float(macro0.get("spot_ag") or 0.0)
            s1 = float(macro_s.get("spot_ag") or 0.0)
            if abs(s1 - s0) > 1e-9:
                peer_s = self.valuation_engine.peer_ev_margin_scaled(peer0, s0, s1, aisc_ref)
                applied["peer_ev_oz"] = {"from": round(peer0, 4), "to": round(peer_s, 4),
                                         "auto": "scaled with silver margin"}

        scen_payload = self._archetype_payload(ticker, cfg, prices, macro_s, aisc, peer_s, fm)
        # Re-assert overrides so they win over any ingestion overlay applied during payload build.
        for k in MACRO_KEYS:
            if k in applied:
                scen_payload.setdefault("macro", {})[k] = macro_s[k]
        if "peer_ev_oz" in applied:
            scen_payload.setdefault("comps", {})["peer_ev_oz"] = peer_s
        scen_regime = (self._build_regime_impact_vector(rs["mri"], rs["real_yield"], rs["silver_vol"],
                       rs["dxy"], cfg=cfg) if regime_dirty else base["regime_vector"])
        scen_summary = router.get_valuation(ticker, scen_payload, scen_regime)

        # The intrinsic is CAD-normalized but the payload price is NATIVE — pass the price in the
        # intrinsic's currency (CAD) so upside = intrinsic ÷ price is a correct ratio that matches
        # the conviction view (a USD name like GROY otherwise reads ~60% upside instead of +14%).
        native_price = base_payload.get("price")
        ccy = str(base_payload.get("currency", "CAD")).upper()
        price_cad = (native_price * base["usd_to_cad"]
                     if ccy == "USD" and native_price else native_price)
        out = summarize_delta(base_summary, scen_summary, price_cad, applied)
        out["ticker"] = ticker
        out["archetype"] = scen_summary.get("archetype")
        out["display_ccy"] = "CAD"      # whatif works in the valuation (CAD) basis end-to-end
        return out

    def set_ui_state(self, state: dict) -> dict:
        """A frontend reports what it is showing (read-side of the merge). Thin orchestration over
        the engine-owned UIStateManager; agents read it via GET /ui/state / get_ui_context."""
        return {"ok": True, "ui_state": self.ui.update(state)}

    # ------------------------------------------------------------------ A1.9 snapshot publish
    def publish_state(self) -> None:
        """Atomic snapshot-swap (audit A1.9): deep-copy the working ``terminal_state`` into the
        published frame readers are served. Called at the END of every eval cycle and after each
        interactive mutation (ui_command / annotation / activity / pipeline event), so interactivity
        stays immediate while a /state or /ws read can never observe a half-updated book (e.g. new
        prices beside the prior cycle's intrinsic). Failure keeps the prior frame — readers degrade
        to slightly stale-but-complete, never torn."""
        try:
            snap = copy.deepcopy(self.terminal_state)
            with self.state_lock:
                self._published_state = snap            # one reference assignment = the swap
        except Exception as e:
            logging.warning("state publish failed (readers keep the prior complete frame): %s", e)

    @property
    def published_state(self) -> dict:
        """The frame readers consume: the last complete published snapshot, or the live dict
        before the first publish (startup parity with the pre-A1.9 behavior)."""
        return self._published_state if self._published_state is not None else self.terminal_state

    def push_ui_command(self, cmd: dict) -> dict:
        """Agents steer the frontend (write-side). The command rides the existing /ws terminal_state
        feed under 'ui_command'; the frontend acts when 'seq' increases."""
        c = cmd or {}
        try:
            command = self.ui.command(c.get("action"), c.get("args", {}))
        except ValueError as e:
            return {"error": str(e)}
        self.terminal_state["ui_command"] = command
        if command.get("action") in ("pin_insight", "highlight", "clear_insight"):
            try:
                self.record_annotation(command)
            except Exception:
                pass            # a bad annotation must never disturb the command stream
        self.publish_state()    # interactive mutation -> immediate complete frame for readers
        return {"ok": True, "command": command}

    def record_annotation(self, command: dict) -> None:
        """Agents leave visual traces on the dashboard. pin_insight = persistent badge, highlight =
        transient (TTL), clear_insight = remove. Stored per-ticker in terminal_state so the cockpit
        renders badges/notes next to names. Bounded + self-pruning of expired entries."""
        args = command.get("args", {}) or {}
        action = command.get("action")
        ticker = str(args.get("ticker") or "").strip()
        store = self.terminal_state.setdefault("agent_annotations", {})
        now = time.time()
        for k in list(store.keys()):                       # prune expired everywhere first
            store[k] = [a for a in store[k] if not a.get("ttl") or (now - a.get("ts", now)) < a["ttl"]]
            if not store[k]:
                del store[k]
        if action == "clear_insight":
            store.pop(ticker, None) if ticker else store.clear()
            return
        if not ticker:
            return
        store.setdefault(ticker, []).append({
            "ticker": ticker,
            "badge": str(args.get("badge") or ("✦" if action == "pin_insight" else "◆"))[:2],
            "reason": str(args.get("reason") or args.get("note") or "")[:500],
            "level": str(args.get("level") or "info"),     # info | good | warn | risk
            "agent": str(args.get("agent") or command.get("agent") or "agent")[:24],
            "ts": now,
            "ttl": (None if action == "pin_insight" else float(args.get("ttl", 90) or 90)),
            "seq": command.get("seq"),
        })
        del store[ticker][:-5]                             # cap 5 per name

    def _append_agent_activity_line(self, record: dict) -> None:
        """Append one QUEST-LOG entry to the durable JSONL (append-only). Never raises — a disk problem
        must not disturb the eval loop (same discipline as the in-memory bus)."""
        try:
            os.makedirs(os.path.dirname(AGENT_ACTIVITY_PATH) or ".", exist_ok=True)
            with open(AGENT_ACTIVITY_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _reload_agent_feed(self) -> None:
        """Load the persisted QUEST-LOG feed back into terminal_state on startup: the recent buffer, the
        last full reply, and the monotonic seq counter — so past agent runs survive a restart. Rewrites
        the file to its bounded tail when oversized. Never raises."""
        try:
            if not os.path.exists(AGENT_ACTIVITY_PATH):
                return
            rows = []
            with open(AGENT_ACTIVITY_PATH, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
            if not rows:
                return
            rows = rows[-AGENT_ACTIVITY_KEEP:]                  # bounded retention (rolling, not an audit trail)
            buf = [{k: r.get(k) for k in ("seq", "ts", "agent", "kind", "summary", "ticker")}
                   for r in rows[-AGENT_ACTIVITY_BUFFER:]]
            last_reply = None
            for r in rows:
                if r.get("text"):
                    last_reply = {"text": r["text"], "agent": r.get("agent"), "ts": r.get("ts")}
            self.terminal_state["agent_activity"] = buf
            if last_reply:
                self.terminal_state["agent_reply"] = last_reply
            self._agent_seq = max([self._agent_seq] + [int(r.get("seq", 0) or 0) for r in rows])
            if len(rows) >= AGENT_ACTIVITY_KEEP:               # truncate the file to the bounded tail
                try:
                    with open(AGENT_ACTIVITY_PATH, "w", encoding="utf-8") as fh:
                        for r in rows:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                except Exception:
                    pass
        except Exception:
            pass

    def record_agent_activity(self, ev: dict) -> dict:
        """Ambient agent-activity bus. Claude Code hooks (and agents directly) POST what they are
        doing — prompt / tool / response / note / proposal — and it rides terminal_state under
        'agent_activity' so the cockpit streams the agents working without anyone calling a steer
        tool. Bounded ring buffer; never raises (a bad event must not disturb the eval loop)."""
        e = ev or {}
        self._agent_seq += 1
        entry = {
            "seq": self._agent_seq,
            "ts": time.time(),
            "agent": str(e.get("agent", "agent"))[:24],
            "kind": str(e.get("kind", "note"))[:16],
            "summary": " ".join(str(e.get("summary", "")).split())[:200],
            "ticker": (str(e.get("ticker"))[:12] if e.get("ticker") else None),
        }
        buf = self.terminal_state.setdefault("agent_activity", [])
        buf.append(entry)
        del buf[:-AGENT_ACTIVITY_BUFFER]     # keep only the most recent N in the live frame
        reply = None
        if e.get("text"):             # a full reply (Stop hook) -> the cockpit's prompt-output panel
            reply = {"text": str(e.get("text"))[:6000], "agent": entry["agent"], "ts": entry["ts"]}
            self.terminal_state["agent_reply"] = reply
        # durable QUEST-LOG: persist the entry (with the full reply text when present) so the feed
        # survives a restart, then reload picks it back up.
        self._append_agent_activity_line({**entry, "text": reply["text"]} if reply else entry)
        self.publish_state()          # interactive mutation -> immediate complete frame
        return {"ok": True, "seq": entry["seq"]}

    def record_pipeline_event(self, ev: dict) -> dict:
        """Live status for a backgrounded research pipeline (scout→synthesis→verifier) so the cockpit
        shows progress while the user keeps chatting. The runner posts start/done; the headless agent
        posts stage transitions + per-name verdicts. Bounded; never raises."""
        e = ev or {}
        now = time.time()
        p = self.terminal_state.setdefault(
            "pipeline", {"status": "idle", "theme": None, "stage": None, "started": None,
                         "updated": None, "events": [], "result": None, "verdicts": {}})
        status = str(e.get("status") or p.get("status") or "running")[:16]
        stage = e.get("stage")
        msg = " ".join(str(e.get("message", "")).split())[:200]
        if status == "running" and (p.get("status") in (None, "idle", "done", "error") and not p.get("started")):
            p.update({"started": now, "events": [], "result": None, "verdicts": {}})
        if e.get("theme"):
            p["theme"] = str(e.get("theme"))[:80]
        if stage:
            p["stage"] = str(stage)[:24]
        p["status"] = status
        p["updated"] = now
        if e.get("ticker") and (e.get("verdict") or e.get("message")):
            tk = str(e["ticker"])[:12]
            cur = p.setdefault("verdicts", {}).get(tk)
            cur = dict(cur) if isinstance(cur, dict) else ({"verdict": str(cur)} if cur else {})
            if e.get("verdict"):
                cur["verdict"] = str(e["verdict"])[:16]
            if e.get("message"):
                cur["note"] = str(e["message"])[:240]
            p["verdicts"][tk] = cur
        if e.get("result"):
            p["result"] = str(e.get("result"))[:4000]
        if stage or msg:
            p.setdefault("events", []).append(
                {"ts": now, "stage": p.get("stage"), "status": status, "message": msg})
            del p["events"][:-30]
        self.publish_state()          # interactive mutation -> immediate complete frame
        return {"ok": True, "status": p["status"], "stage": p.get("stage")}

    # ---- research dossiers / decision memos (read-only; engine owns the file I/O) -------
    def list_decisions(self, limit: int = 50) -> dict:
        """Index the research dossiers under ``data/decisions/*.md`` (newest first) so the cockpit
        Dossier tab is a real research surface, not a placeholder. The cockpit stays a thin consumer:
        all file I/O and ticker inference live here. Agents write these via the /dossier skill."""
        try:
            os.makedirs(DECISIONS_DIR, exist_ok=True)
        except OSError:
            pass
        items = []
        for path in glob.glob(os.path.join(DECISIONS_DIR, "*.md")):
            try:
                st = os.stat(path)
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(4000)
            except OSError:
                continue
            name = os.path.basename(path)
            title = next((ln.lstrip("# ").strip() for ln in head.splitlines() if ln.strip()), name)
            items.append({
                "name": name,
                "ticker": self._guess_decision_ticker(name, head),
                "title": title[:120],
                "mtime": st.st_mtime,
                "age_minutes": round((time.time() - st.st_mtime) / 60.0, 1),
                "size": st.st_size,
                "preview": " ".join(head.split())[:240],
            })
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return {"dir": DECISIONS_DIR, "count": len(items), "decisions": items[: max(1, int(limit))]}

    def read_decision(self, name: str) -> dict:
        """Return one dossier's markdown body. Path-traversal-guarded to ``data/decisions/``."""
        if not name or not str(name).endswith(".md"):
            return {"error": "name must be a .md file in the decisions dir"}
        base = os.path.abspath(DECISIONS_DIR)
        target = os.path.abspath(os.path.join(base, os.path.basename(str(name))))
        if os.path.dirname(target) != base or not os.path.isfile(target):
            return {"error": f"no such decision {name!r}"}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                return {"name": os.path.basename(target), "markdown": f.read(200_000)}
        except OSError as e:
            return {"error": str(e)}

    def delete_decision(self, name: str) -> dict:
        """Delete one dossier by file name. Path-traversal-guarded to ``data/decisions/``."""
        if not name or not str(name).endswith(".md"):
            return {"error": "name must be a .md file in the decisions dir"}
        base = os.path.abspath(DECISIONS_DIR)
        target = os.path.abspath(os.path.join(base, os.path.basename(str(name))))
        if os.path.dirname(target) != base or not os.path.isfile(target):
            return {"error": f"no such decision {name!r}"}
        try:
            os.remove(target)
            return {"ok": True, "deleted": os.path.basename(target)}
        except OSError as e:
            return {"error": str(e)}

    @staticmethod
    def _guess_decision_ticker(name: str, head: str):
        """Best-effort ticker tag for a dossier from its filename / first lines (book names first)."""
        blob = (name + " " + head).upper()
        for t in ("AGA.V", "GMX.TO", "URC.TO", "GROY"):
            if t in blob:
                return t
        return os.path.splitext(name)[0].split("_")[0].split("-")[0].upper() or None

    @staticmethod
    def _spear_quality_inputs(cfg: dict) -> dict:
        """Derive the spear's junior-miner quality lenses (ounce-weighted head grade, total
        contained AgEq ounces, ounce-weighted blended Ag+Au recovery) from the config resource
        model, for the Conviction Mode Q pillar. Graceful: missing data simply drops a lens."""
        buckets = cfg.get("project_buckets_oz_AgEq", {}) or {}
        projects = (cfg.get("technical_quality", {}) or {}).get("projects", {}) or {}
        out: dict = {}
        total_oz = sum(float(v) for v in buckets.values() if _is_pos(v))
        if total_oz > 0:
            out["resource_oz"] = total_oz
            g_num = r_num = 0.0
            for name, oz in buckets.items():
                if not _is_pos(oz):
                    continue
                p = projects.get(name, {}) if isinstance(projects.get(name), dict) else {}
                if _is_pos(p.get("grade_gpt_ageq")):
                    g_num += float(oz) * float(p["grade_gpt_ageq"])
                ag_s, au_s = p.get("ageq_share_ag"), p.get("ageq_share_au")
                ag_r, au_r = p.get("rec_ag"), p.get("rec_au")
                if all(_is_pos(x) or x == 0 for x in (ag_s, au_s, ag_r, au_r)) and (ag_s is not None):
                    r_num += float(oz) * (float(ag_s) * float(ag_r) + float(au_s) * float(au_r))
            if g_num > 0:
                out["grade_gpt"] = round(g_num / total_oz, 1)
            if r_num > 0:
                out["recovery"] = round(r_num / total_oz, 4)
        return out

    def _maybe_refresh_live_catalysts(self, cfg: dict, cat_cfg: dict, path: str) -> None:
        """PHASE 8 (debug fix): run the configured live providers (EDGAR / RSS / manual CSV) and
        rewrite the canonical feed file, but only when it is older than ``live_refresh_seconds`` so
        the eval loop never hammers the feeds. Fully robust: any failure logs and leaves the existing
        feed in place (we then serve whatever is on disk). Logs which providers succeeded/failed."""
        if refresh_catalyst_feed is None:
            logging.warning("Phase 8 live feeds requested but refresh_catalyst_feed is unavailable; "
                            "serving cached feed at %s", path)
            return
        ttl = float(cat_cfg.get("live_refresh_seconds", cat_cfg.get("ttl_seconds", 86400)) or 0.0)
        now = time.time()
        # In-process throttle (don't re-refresh every basket/eval cycle within one run).
        last = getattr(self, "_catalyst_live_refresh_ts", 0.0)
        if last and ttl and (now - last) < ttl:
            return
        # On-disk freshness: if the feed file was generated within the TTL, skip the network too.
        if ttl and os.path.exists(path):
            try:
                with open(path, "r") as fh:
                    gen = json.load(fh).get("generated_at")
                if gen:
                    gen_ts = datetime.datetime.fromisoformat(str(gen).replace("Z", "")).timestamp()
                    if (now - gen_ts) < ttl:
                        self._catalyst_live_refresh_ts = now
                        return
            except (OSError, ValueError, json.JSONDecodeError):
                pass  # unreadable/corrupt -> fall through and refresh
        try:
            res = refresh_catalyst_feed(cfg, path=path)
            self._catalyst_live_refresh_ts = now
            logging.info("Phase 8 live catalyst refresh: status=%s providers=%s count=%s",
                         res.get("status"), res.get("providers"), res.get("count"))
        except Exception as e:                          # never let a feed problem break the eval loop
            self._catalyst_live_refresh_ts = now
            logging.warning("Phase 8 live catalyst refresh failed (serving cached feed at %s): %s",
                            path, e)

    def _catalyst_feed(self, cfg: dict) -> dict:
        """PHASE 8 (additive): serve the catalyst feed, memoized by file mtime so the eval loop does
        not re-read the file every cycle. Graceful: returns an empty feed on any problem.

        ``catalysts.use_live_feeds`` controls sourcing:
          * true  -> refresh the feed from the configured live providers (EDGAR/RSS/manual CSV) on a
                     TTL, then serve the rewritten file.
          * false -> serve EMPTY (the explicit fallback) so a stale checked-in file is never
                     presented as if it were live. Set ``serve_seed_when_disabled: true`` to instead
                     serve the on-disk seed for an offline demo."""
        if load_catalyst_feed is None:
            return {"status": "unavailable", "events": []}
        cat_cfg = cfg.get("catalysts", {}) if isinstance(cfg.get("catalysts"), dict) else {}
        if cat_cfg.get("enabled", True) is False:
            return {"status": "disabled", "events": []}
        path = cat_cfg.get("feed_path", "data/catalysts.json")
        use_live = bool(cat_cfg.get("use_live_feeds", False))
        if use_live:
            self._maybe_refresh_live_catalysts(cfg, cat_cfg, path)
        elif not cat_cfg.get("serve_seed_when_disabled", False):
            return {"status": "live_disabled", "events": [],
                    "reason": "catalysts.use_live_feeds is false (fallback: empty)"}
        try:
            mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
        except OSError:
            mtime = 0.0
        cache = getattr(self, "_catalyst_cache", None)
        if cache and cache.get("path") == path and cache.get("mtime") == mtime:
            return cache["feed"]
        feed = load_catalyst_feed(path)                  # events are historical -> use even if stale
        self._catalyst_cache = {"path": path, "mtime": mtime, "feed": feed}
        return feed

    def _regime_posture(self, mri_score: float, signals: dict = None) -> dict:
        """Forge Phase 3: the book-level regime posture (stance + size cap) from the live regime —
        the Druckenmiller master risk dial. Reads MRI + net_tilt + real_yield + DXY momentum through
        the cycle's shared macro_snapshot (``signals``; resolved fresh — identically — when called
        standalone) and routes through the pure regime_posture module. An absent signal stays None
        (the driver is omitted from the cap, per regime_posture.compute) — deliberately NOT the
        commodity-tailwind's neutral defaults. Defensive: any problem -> a neutral BALANCED / 1.0x
        posture, never raises."""
        try:
            import regime_posture
            snap = signals if signals is not None else macro_snapshot.snapshot(self.terminal_state)
            return regime_posture.compute(
                mri=mri_score,
                net_tilt=snap.get("net_tilt"),
                real_yield=snap.get("real_yield"),
                dxy_mom=snap.get("dxy_mom"))
        except Exception:
            return {"code": "balanced", "label": "BALANCED", "cap": 1.0, "headwind": False,
                    "drivers": [], "rationale": "posture unavailable"}

    def _emit_cockpit_events(self) -> None:
        """Forge nervous system #1: turn this cycle's meaningful state deltas into semantic events.
        Every event rides the ephemeral desk-tape bus (/agent/activity); only the signal-worthy ones
        (posture flips, JSF trips) are persisted to the immutable Living Memory audit record — so the
        track record stays clean while the nervous system stays live. Never raises."""
        self._run_coherence_decay()
        import cockpit_events
        curr = cockpit_events.snapshot(self.terminal_state)
        prev = getattr(self, "_event_prev", None)
        # Don't let a DEGENERATE cycle (conviction block errored -> no baskets -> empty gates)
        # become the baseline: it would make the next good cycle re-fire every still-applied gate
        # as a fresh "trip". Keep the last good snapshot as prev until real gates return.
        if curr.get("gates"):
            self._event_prev = curr
        events = cockpit_events.detect_events(prev or {}, curr)
        if not events:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code"),
                  "net_tilt": (self.terminal_state.get("macro_tape") or {}).get("net_tilt")}
        lm = None
        for e in events:
            try:                                          # ephemeral bus -> the desk tape
                self.record_agent_activity({"agent": "engine", "kind": e["kind"],
                                            "summary": e["summary"], "ticker": e.get("ticker")})
            except Exception:
                pass
            if not e.get("persist"):
                continue
            try:                                          # signal-worthy -> the audit record
                if lm is None:
                    lm = getattr(self, "_lm", None) or living_memory.LivingMemory()
                    self._lm = lm
                mtype = "regime_snapshot" if e["kind"] == "posture" else "note"
                lm.write(mtype, text=e["summary"], ticker=e.get("ticker"), regime=regime,
                         source="engine", tags=[e["kind"], "event"])
            except Exception:
                pass

        # Forge nervous system #5: reactive triggers — the desk talks back. DECISION-SUPPORT ONLY
        # (pin/highlight, never a book action); rate-limited via the cooldown ledger; loop-safe
        # (annotations are not state events, so they can't re-trigger). Defensive.
        try:
            import cockpit_triggers
            fired = getattr(self, "_trigger_fired", {})
            annos = self.terminal_state.setdefault("agent_annotations", {})
            badges = {"warn": "▲", "risk": "⚠", "good": "◆", "info": "●"}
            for a in cockpit_triggers.evaluate(events, fired=fired):
                slot = annos.setdefault(a.get("ticker") or "_book", [])
                slot.append({"badge": badges.get(a["level"], "✦"), "level": a["level"],
                             "reason": a["text"][:60], "agent": "desk"})
                del slot[:-3]
                fired[a["key"]] = time.time()
            self._trigger_fired = fired
        except Exception:
            pass

    def _run_coherence_decay(self) -> None:
        """F3 (docs/FABLE_INTEGRATION.md), the deterministic layer: (a) the coherence checker — the
        known contradiction patterns between surfaces (directive vs floor, severe gate vs bullish
        directive, stale pins, the cap loosening against a rising MRI), run over the completed
        cycle's state; (b) the conclusion-decay sweep — every non-superseded Memory entry carrying
        structured ``meta.assumptions`` re-checked against live facts, a dead claim flagging the
        conclusion DECAYED. Both MEASURE only (decision-support; superseding stays a deliberate
        act), both ride /state (``coherence`` / ``conclusion_decay``), and new coherence findings
        annotate once (deduped) rather than every cycle. Never raises."""
        try:
            import coherence_check
            import conclusion_decay
            lm = getattr(self, "_lm", None) or living_memory.LivingMemory()
            self._lm = lm
            pinned, superseded = coherence_check.memory_inputs(lm)
            res = coherence_check.check_state(self.terminal_state,
                                              pinned_entries=pinned, superseded_ids=superseded)
            prev = getattr(self, "_coherence_prev", None)
            curr = coherence_check.snapshot(self.terminal_state)
            self._coherence_prev = curr
            extra = coherence_check.check_delta(prev, curr)
            if extra:
                res["findings"].extend(extra)
                res["n"] = len(res["findings"])
                res["read"] = (f"{res['n']} contradiction(s): "
                               + ", ".join(sorted({f["id"] for f in res["findings"]})))
            self.terminal_state["coherence"] = res

            # annotate NEW findings only (a persisting contradiction shouldn't re-badge each cycle)
            seen = getattr(self, "_coherence_seen", set())
            annos = self.terminal_state.setdefault("agent_annotations", {})
            for f in res["findings"]:
                if (f["id"], f.get("ticker")) in seen:
                    continue
                slot = annos.setdefault(f.get("ticker") or "_book", [])
                slot.append({"badge": "⚠" if f["level"] == "risk" else "▲", "level": f["level"],
                             "reason": f["why"][:60], "agent": "coherence"})
                del slot[:-3]
            self._coherence_seen = {(f["id"], f.get("ticker")) for f in res["findings"]}

            facts = conclusion_decay.facts_from_state(self.terminal_state)
            entries = [e for e in lm.all() if e.get("id") not in superseded
                       and (e.get("meta") or {}).get("assumptions")]
            self.terminal_state["conclusion_decay"] = conclusion_decay.sweep(entries, facts)
        except Exception:
            obs.swallow("coherence_decay")

    def _turn_calibration_flywheel(self, *, horizon_days: int = 90, interval_s: int = 3600) -> None:
        """H3 capture loop, turned deterministically (the 'close the loop' fix). Once per ``interval_s``:
        freeze a gradeable DECISION for every held name that lacks an open one, and CLOSE open decisions
        at their horizon (or on a stance change) at the live mark — writing the same ``decision`` /
        ``outcome`` Living-Memory schema the MCP capture tools use, so both paths feed one shared ledger
        the scorecard and the agent prior already read. The decision logic is the pure, tested
        ``calibration.plan_flywheel_actions``; this method is just the engine-side I/O. Never raises."""
        import calibration
        now = time.time()
        if now - getattr(self, "_flywheel_ts", 0.0) < max(60, int(interval_s)):
            return
        # GATE on COMPUTED live prices: never freeze or grade a bet before the price worker has stamped
        # fresh marks this session. On startup the basket prices are stale fallbacks AND prices_stale is
        # still empty, so the per-name stale guard below is blind — a freeze on a fallback that then jumps
        # to the live mark mints a phantom ~0-day ±N% grade (the 'suspect' outcomes). Defer until prices
        # are demonstrably live (the worker stamps prices_ts each successful cycle).
        _pts = (getattr(self, "state_cache", None) or {}).get("prices_ts")
        if not _pts or (now - float(_pts)) > 1800:
            return
        conv = self.terminal_state.get("conviction_mode") or {}
        baskets = conv.get("baskets") or []
        if not baskets:
            return                                          # nothing rated yet — don't prime on an empty book
        # lazily bind the shared Living-Memory handle (same store the events path uses)
        lm = getattr(self, "_lm", None)
        if lm is None:
            lm = living_memory.LivingMemory()
            self._lm = lm

        # Shape each HELD basket the way decision_from_rating expects (ladder + asymmetry{rho,φ} + gate),
        # exactly as get_conviction_ratings does — eval-only names are rated, NOT held, so they get no
        # decision; unpriced names (feed miss) are skipped until a mark returns.
        shaped = []
        for b in baskets:
            if b.get("eval_only") or not _is_pos((b.get("ladder") or {}).get("price")):
                continue
            V = (b.get("pillars") or {}).get("V", {}) if isinstance(b.get("pillars"), dict) else {}
            shaped.append({"ticker": b.get("ticker"), "directive": b.get("directive"),
                           "archetype": b.get("archetype"), "ladder": b.get("ladder") or {},
                           "asymmetry": {"rho": V.get("rho"), "floor_coverage": V.get("floor_coverage")},
                           "gate": b.get("gate") or {}})
        if not shaped:
            return

        # Open decisions = frozen decisions with no linked outcome yet (newest-first).
        closed_ids = set()
        for o in lm.query(type="outcome", limit=0):
            closed_ids.update(o.get("refs") or [])
        open_decisions = [d for d in lm.query(type="decision", limit=0)
                          if d.get("id") not in closed_ids]

        def _age(ts):
            d = _age_days_iso(ts)
            return None if d is None else int(d)

        # A stale / hardcoded-fallback mark must NEVER freeze or grade a bet: an intermittently-missing
        # feed (e.g. a holding whose mark flaps between the real price and the fallback) would otherwise
        # flip the stance every turn and mint a stream of PHANTOM ±N% win/loss grades that poison the
        # learned base rate. Skip those names until a trustworthy mark returns.
        stale_tickers = {str(t).upper() for t, s in
                         ((getattr(self, "state_cache", None) or {}).get("prices_stale") or {}).items() if s}
        plan = calibration.plan_flywheel_actions(open_decisions, shaped, horizon_days=horizon_days,
                                                 age_days_fn=_age, stale_tickers=stale_tickers)
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code"),
                  "net_tilt": (self.terminal_state.get("macro_tape") or {}).get("net_tilt")}
        n_closed = n_frozen = 0

        # CLOSE first (grade the old bet at the live mark) so a re-freeze of the same name is clean.
        for c in plan.get("close", []):
            dec = c["decision"]
            scored = calibration.score_outcome(dec.get("meta") or {}, c["realized_price"],
                                               horizon_days=horizon_days)
            if scored.get("status") != "scored":
                continue
            # QUARANTINE — a grade counts toward the learned base rate ONLY if the bet was frozen on a
            # VERIFIED-FRESH mark (mark_fresh). A legacy/unverified freeze is still recorded for the
            # audit trail but flagged suspect + excluded from the roll-up, so a bad frozen price can
            # never poison the track record (defense behind the stale-mark + last-good feed guards).
            scored["suspect"] = not bool((dec.get("meta") or {}).get("mark_fresh"))
            # H5 — Brier-score the thesis's CONFIDENCE TRAIL against the realized result, so the
            # outcome records whether the desk's stated confidence was honest, not just directional.
            try:
                trail = [float((e.get("meta") or {}).get("confidence"))
                         for e in lm.query(type="conviction", limit=0, newest_first=False)
                         if dec.get("id") in (e.get("refs") or [])
                         and (e.get("meta") or {}).get("confidence") is not None]
                brier = calibration.brier_score(trail, scored.get("result")) if trail else None
                if brier:
                    scored["brier"] = brier
            except Exception:
                pass
            txt = (f"OUTCOME {scored['result'].upper()} {scored['realized_return']*100:+.0f}% "
                   f"@{horizon_days}d (leg {scored['leg_hit']}) · {c['reason']}"
                   + (" · ⚠ suspect (unverified mark)" if scored["suspect"] else ""))
            # Stamp the macro scenario that was LIVE at close (argmax of the engine's OWN scenario
            # weights), so the scenario-payoff matrix can ground itself on realized, labeled outcomes
            # (scenario_engine.learned_slot_payoffs). Best-effort: no weights ⇒ no label ⇒ that cell
            # stays a pure prior. A flywheel grade is a deterministic engine number → provenance=engine.
            try:
                _sw = (self.terminal_state.get("scenario_engine") or {}).get("weights") or {}
                if _sw:
                    scored["realized_scenario"] = max(_sw, key=_sw.get)
            except Exception:
                obs.swallow("scenario.realized_label")
            _tags = ["outcome", scored["result"], "flywheel"] + (["suspect"] if scored["suspect"] else [])
            lm.write("outcome", text=txt, ticker=dec.get("ticker"),
                     tags=_tags, regime=regime,
                     meta=scored, refs=[dec.get("id")], source="engine-flywheel", provenance="engine")
            n_closed += 1

        for b in plan.get("freeze", []):
            decision = calibration.decision_from_rating(b)
            decision["mark_fresh"] = True                # frozen on a fresh mark (stale names skipped above)
            legs = decision.get("legs", {}) or {}
            txt = (f"DECISION {decision.get('verdict','')} @ {decision.get('price')} "
                   f"[floor {legs.get('floor')} · bull {legs.get('bull')}]")
            dec_entry = lm.write("decision", text=txt, ticker=decision.get("ticker"),
                                 tags=["decision", "flywheel"], regime=regime, meta=decision,
                                 source="engine-flywheel")
            n_frozen += 1
            # H5 ergonomics — SEED the confidence trail from the engine's own priors (archetype base
            # rate, else implied breakeven 1/(1+ρ)) so Brier calibration is never null for lack of a
            # typed reading (2026-07-28: 'calibration is too manual input heavy'). Tagged seeded=True;
            # an operator record_conviction overrides simply by appending to the trail.
            try:
                seed = calibration.seed_confidence(decision)
                if seed:
                    lm.write("conviction", ticker=decision.get("ticker"),
                             text=(f"CONVICTION {decision.get('ticker')} "
                                   f"{seed['confidence']*100:.0f}% — {seed['basis']}"),
                             tags=["conviction", "seed", "flywheel"], regime=regime,
                             meta={"confidence": seed["confidence"], "basis": seed["basis"],
                                   "seeded": True, "decision_id": dec_entry.get("id")},
                             refs=[dec_entry.get("id")], source="engine-flywheel", provenance="engine")
            except Exception:
                obs.swallow("flywheel.seed_confidence")

        # Persist the per-archetype LEARNED base-rate roll-up (deduped once/day) — the durable,
        # regime-stamped artifact discovery (D4) and the agent prior anchor to, so a find is judged
        # against the desk's OWN closed track record, not only the published outside view.
        try:
            scored = [e.get("meta", {}) for e in lm.query(type="outcome", limit=0)
                      if (e.get("meta") or {}).get("status") == "scored"]
            learned = calibration.learned_base_rates(scored)
            if learned:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                recent = lm.query(type="calibration_snapshot", limit=1)
                if not (recent and str(recent[0].get("ts", ""))[:10] == today):
                    lm.write("calibration_snapshot",
                             text=f"per-archetype learned base rates ({len(learned)} archetype(s))",
                             tags=["calibration", "flywheel"], regime=regime,
                             meta={"learned": learned}, source="engine-flywheel")
        except Exception as e:
            logging.warning("calibration snapshot skipped (non-fatal): %s", e)

        self._flywheel_ts = now
        if n_closed or n_frozen:
            logging.info("calibration flywheel: froze %d, closed %d decision(s)", n_frozen, n_closed)

    def _record_valuation_ledger(self, cfg: dict) -> None:
        """Validation flywheel (Phase 1): stamp each name's full valuation state point-in-time
        into the append-only valuation ledger (``data/valuation_ledger.jsonl``) — the keystone
        record the replay harness grades. RECORDS the blocks this cycle already computed (the
        conviction baskets, the triangulation legs, the live regime) plus the research-cache
        input provenance copied BY VALUE; never recomputes anything. Cadence (daily mark +
        material change + seed) is enforced inside ``maybe_record``. Caller fences exceptions."""
        import valuation_ledger as _vl
        if getattr(self, "_vledger", None) is None:
            self._vledger = _vl.ValuationLedger()
            self._engine_git_sha = _vl.git_sha()
        conv = self.terminal_state.get("conviction_mode") or {}
        baskets = conv.get("baskets") or []
        if not baskets:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code"),
                  "net_tilt": (self.terminal_state.get("macro_tape") or {}).get("net_tilt")}
        avd = (self.terminal_state.get("archetype_valuation_detail") or {})
        results = avd.get("results", {}) if isinstance(avd, dict) else {}
        cfg_hash = _vl.config_hash(cfg)
        rc = None
        try:
            rc = research_cache.ResearchCache()
        except Exception:
            rc = None
        # Phase 2.1 — the replay harness's ground truth: stamp today's price mark into the
        # daily-close store every cycle (same-day marks converge to the close; past dates are
        # immutable). Re-instantiated per call so a concurrent backfill is read, never clobbered.
        _hist = None
        try:
            import price_history as _ph
            _hist = _ph.PriceHistory()
        except Exception:
            _hist = None
        _hist_dirty = False
        today_utc = time.strftime("%Y-%m-%d", time.gmtime())
        for b in baskets:
            tkr = b.get("ticker")
            if not tkr:
                continue
            summ = results.get(tkr) if isinstance(results.get(tkr), dict) else {}
            inputs = _vl.inputs_from_provenance(rc.provenance(tkr)) if rc is not None else {}
            snap = _vl.snapshot_from_basket(
                b, inputs=inputs, regime=regime,
                legs={"values": (summ or {}).get("legs"),
                      "weights": (summ or {}).get("weights"),
                      "confidence": (summ or {}).get("confidence")},
                rep_floor=(cfg.get("rep_floor_params") if tkr == "AGA.V" else None),
                config_hash=cfg_hash, engine_git_sha=self._engine_git_sha)
            self._vledger.maybe_record(snap)
            if _hist is not None and snap.get("price"):
                r = _hist.record_mark(tkr, today_utc, snap["price"], today=today_utc, save=False)
                if r.get("ok") and not r.get("duplicate"):
                    _hist_dirty = True
        if _hist is not None and _hist_dirty:
            _hist._save()

    def _compute_conviction_mode(self, *, cfg: dict, cad_prices: dict, mri_score: float,
                                 net_tilt: str, forensic_metrics: dict,
                                 macro_signals: dict = None) -> dict:
        """PHASE 7/8 (additive): build the primary Conviction Mode block — the 0-10 T-Q-V Asymmetry
        Rating per basket — from blocks already computed this cycle (``valuation_detail``,
        ``archetype_valuation_detail``, ``forensics``, ``mri``) plus live CAD prices, with a Phase 8
        live-catalyst overlay (drill/financing/permitting events nudge conviction / trip the forensic
        gate / advance the permitting lens) and a recent-catalyst list per card. It reads NONE of the
        diversified-book sizing machinery (caps / ES95 / shrinkage / Kelly). Isolated so it can never
        crash the eval loop."""
        if build_conviction_state is None:
            return {"status": "unavailable", "baskets": []}

        vd = self.terminal_state.get("valuation_detail", {}) or {}
        avd = self.terminal_state.get("archetype_valuation_detail", {}) or {}
        results = avd.get("results", {}) if isinstance(avd, dict) else {}
        forensics = self.terminal_state.get("forensics", {}) or {}
        meta = cfg.get("portfolio_metadata", {})

        # Phase 8: catalyst overlays per ticker (bounded; graceful empty when no feed).
        cat_feed = self._catalyst_feed(cfg)
        overlays = {}
        if build_catalyst_overlays is not None and cat_feed.get("events"):
            try:
                overlays = build_catalyst_overlays(cat_feed["events"], list(cad_prices), cfg)
            except Exception as e:
                logging.warning("Phase 8 catalyst overlay skipped (non-fatal): %s", e)

        def _dilution_velocity(tkr):
            m = forensic_metrics.get(tkr) or {}
            s0, s1 = m.get("shares_t0"), m.get("shares_t1")
            try:
                if s0 and s1 and s1 > 0:
                    return max(0.0, (float(s0) / float(s1) - 1.0)) * 4.0   # QoQ -> annualized
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            return None

        # Validation flywheel (Phase 5 interlock): the EMPIRICAL market-leg sigma — the measured
        # dispersion across the live peer comp — feeds the spear's distributional ribbon instead
        # of an assumed band. Defensive: absent peers/module -> None (the confidence map applies).
        peer_market_sigma = None
        try:
            import peer_normalization as _pn_audit
            _audit = _pn_audit.comp_audit(getattr(self.peer_engine, "peer_data_cache", None) or {})
            peer_market_sigma = (_audit or {}).get("rel_dispersion")
        except Exception:
            peer_market_sigma = None

        # Arch 5: resolve the commodity-regime macro inputs ONCE for the whole basket loop (from
        # the cycle's shared macro_snapshot when the caller passed it) instead of re-reading
        # terminal_state twice per name. Same values, one resolution.
        csig = self._commodity_signals(macro_signals)

        assets = []
        for tkr, price in cad_prices.items():
            summ = results.get(tkr, {}) if isinstance(results.get(tkr), dict) else {}
            legs = summ.get("legs", {}) if isinstance(summ.get("legs"), dict) else {}
            conf = summ.get("confidence", {}) if isinstance(summ.get("confidence"), dict) else {}
            pm = meta.get(tkr, {}) if isinstance(meta.get(tkr), dict) else {}
            is_spear = (tkr == "AGA.V")

            # Floor = the cost/REP leg. The spear uses its authoritative triangulation cost leg; a
            # ballast (asset-light) name uses the archetype's REP-equivalent floor (net liquid backing +
            # stressed royalty NAV) and falls back to the sourced book value ONLY when that floor is a
            # degraded proxy (asset-backing inputs not sourced). Book understates a royalty's floor, so
            # it is the labelled fallback, never the override (the OGN.V $0.50-on-$3.75 lesson).
            floor = (vd.get("legs", {}) or {}).get("cost") if is_spear else legs.get("cost")
            if not _is_pos(floor):
                floor = legs.get("cost")
            floor_degraded = False
            _hl = None                                          # holdco-NAV ladder (set below for ballast)
            if not is_spear:
                cost_bd = (summ.get("component_breakdown", {}) or {}).get("cost", {}) or {}
                if bool(cost_bd.get("degraded_proxy")) or not _is_pos(floor):
                    _bvf = self._research_book_floor(tkr)     # sourced book — a labelled proxy floor
                    if _is_pos(_bvf):
                        floor = _bvf
                    floor_degraded = True
                # The SOURCED layered-NAV ladder (holdco_nav) supersedes the cost-basis book proxy for a
                # royalty/holdco: bear=hard floor (REP-equivalent margin of safety), base=risked NAV,
                # bull=blue sky. The floor (bear) wires whenever the floor is sourced; base/bull wire below
                # only when the PIPELINE is sourced (else risked NAV == floor and base would re-create the
                # false negative). FX-normalized; fail-safe (None → keep existing legs).
                _hl = self._holdco_ladder_cad(tkr, cfg)
                # The sourced hard floor (producing-CF DCF + net liquid) only REPLACES the existing
                # floor when it is HIGHER — never lower it. A producing-CF-only floor UNDERSTATES a
                # royalty carrying a large PRE-PRODUCTION book (GROY: a 0.28 producing floor under a
                # 3.13 carried book), so forcing it would crush the asset-backed downside the OGN.V
                # $0.50-on-$3.75 lesson exists to protect. Higher, more representative floor wins.
                _cur_floor = floor if _is_pos(floor) else 0.0
                if _hl and _is_pos(_hl.get("bear")) and _hl["bear"] >= _cur_floor:
                    floor = _hl["bear"]
                    floor_degraded = False                    # now a sourced floor, not a proxy

            if is_spear and isinstance(vd.get("scenarios"), dict):
                sc = vd["scenarios"]
                base_v, bull_v, bear_v = sc.get("base"), sc.get("bull"), sc.get("bear")
            else:
                # No per-asset scenario band -> single-point target (the ribbon widens to reflect it).
                base_v = summ.get("intrinsic_after_forensic") or summ.get("blended_intrinsic")
                bull_v = bear_v = None
            # Holdco/royalty fair value is NOT the risked-NAV ladder's base. That base is a CONSERVATIVE
            # floor-plus construct (producing-CF DCF + stage-risked modelled pipeline); a VALUE-mode name
            # reads upside straight off `base` (upside = base/price − 1), so wiring the conservative
            # risked NAV as fair value MANUFACTURES a false negative-upside — GROY's risked 0.43 against a
            # 3.13 carried royalty book is the tell, and GMX's 1.40 vs a 1.75 price the same. Until fair
            # value is anchored on the FULL carried royalty/holdco NAV (every owned royalty, not just the
            # producing slice) AND the blue-sky optionality is independently sourced, the ladder informs
            # the FLOOR (bear, wired above) and the story card only — it does NOT override the archetype
            # valuation's fair-value base/bull. (Wiring it prematurely crushed both names — 2026-06-25.)

            # The CENTRAL fair value, archetype-aware, DOES anchor `base` — but only through the pure
            # anti-crush wire gate: a royalty re-rates to its TANGIBLE carried-book NAV (the audited mark
            # of every owned royalty — what the producing-CF floor and the modelled pipeline both miss, so
            # GROY reads cheap vs book instead of negative); a PG holdco uses net-liquid + pipeline + a
            # peer mark, and pipeline-only is LOW confidence the gate REFUSES to assert below price (GMX
            # waits for a peer comp rather than manufacturing the false negative that crushed it before).
            _fv_wired = None
            if not is_spear:
                import quality_lenses as _ql
                _prof = {"archetype": summ.get("archetype") or pm.get("archetype"),
                         "subarchetype": summ.get("subarchetype") or pm.get("subarchetype")}
                _fvmode = "holdco" if _ql.is_holdco(_prof) else ("royalty" if _ql.is_royalty(_prof) else None)
                if _fvmode:
                    _fv = self._holdco_fair_value_cad(tkr, cfg, mode=_fvmode, price_cad=price, floor_cad=floor)
                    if _fv and _fv.get("wire") and _is_pos(_fv.get("fair_value_ps")):
                        base_v = _fv["fair_value_ps"]          # the carried-book / portfolio fair value
                        _fv_wired = _fv
                        if _is_pos(_fv.get("blue_sky_ps")):    # verified dev-pipeline increment → display bull leg
                            bull_v = _fv["blue_sky_ps"]        # (value-mode rating reads base, not bull — display only)

            asset = {
                "ticker": tkr,
                # Phase 7.4 niche-tag hook (forward-looking, non-breaking): a future sub-archetype
                # (e.g. "accretive_acquirer" under asset_light_yield) could attach here via
                # asymmetry_rating.niche_tags_for(archetype) to specialize tooltips/weights/gates
                # WITHOUT changing the five core archetypes. Nothing reads it yet.
                "archetype": summ.get("archetype") or pm.get("archetype", "_default"),
                "archetype_code": summ.get("archetype_code"),
                # 3rd taxonomy axis — finer sort within the archetype + orthogonal sector tags
                # (display/correlation only; does not move the rating). Prefer the valuation
                # summary's resolved values, fall back to the config metadata.
                "subarchetype": summ.get("subarchetype") or pm.get("subarchetype"),
                "subarchetype_label": summ.get("subarchetype_label"),
                "sector_tags": summ.get("sector_tags") or pm.get("sector_tags", []),
                "price": price,
                "floor": floor,
                "floor_degraded": floor_degraded,        # book/proxy floor (not the REP-equivalent) → render "pending"
                "base": base_v,
                "bull": bull_v,
                "bear": bear_v,
                "mri": mri_score,
                "regime_alpha": summ.get("regime_alpha", 0.0),
                # commodity-aware tailwind: each name's metal regime (gold ≠ silver ≠ uranium),
                # blended with the shared archetype lean in asymmetry_rating._pillar_macro_tailwind
                "commodity": self._name_commodity(tkr),
                "commodity_regime": self._commodity_regime_lean(self._name_commodity(tkr), csig),
                # near-term MOMENTUM (display/context only) — a SEPARATE, LABELED factor that the T
                # pillar never consumes; the tailwind stays forward-structural (action plan P1.1).
                "commodity_momentum": self._commodity_momentum_lean(self._name_commodity(tkr), csig),
                "forensic_score": (forensics.get("jsf_score") if is_spear else summ.get("forensic_score")),
                "conviction": summ.get("conviction", 0.5),
                "data_quality": summ.get("data_quality", "full" if summ else "sparse"),
                "runway_months": (forensics.get("runway") if is_spear else None),
                "dilution_velocity": _dilution_velocity(tkr),
                "fraser_index": pm.get("fraser_index"),
                "stage": pm.get("stage"),
                "management_score": pm.get("management_score"),
                "thesis_slot": pm.get("thesis_slot"),
                "thesis_slot_desc": pm.get("thesis_slot_desc"),
                # EVAL-set marker: rated alongside the book but holds no weight and enters no
                # sizing — the cockpit badges it so an eval row can never read as a holding.
                "eval_only": bool(pm.get("eval_only")),
                "market_confidence": conf.get("market"),
                # V1 mark-NAV-to-spot quality: tier (live|stamped) + staleness of the spot the NAV
                # was marked at — the ribbon widens on a stale stamp; the Story Card shows the tier.
                "nav_quality": getattr(self, "_nav_quality", {}).get(tkr),
                # Validation flywheel (Phase 3): the triangulation legs + their confidence tilts
                # reach the rating so the confidence ribbon becomes a propagated P10/P50/P90
                # ESTIMATE band (uncertainty.py) instead of a heuristic ±.
                "legs": legs or None,
                "leg_weights": summ.get("weights") if isinstance(summ.get("weights"), dict) else None,
                "leg_confidence": conf or None,
            }
            if is_spear and peer_market_sigma:
                # the spear's market leg is the peer comp — use its MEASURED dispersion as sigma
                asset["leg_sigma"] = {"market": peer_market_sigma}
            if is_spear:
                # Junior-miner quality checklist (grade / scale / metallurgy) from the config
                # resource model, so the Q pillar reads like a mining investor's checklist.
                asset.update(self._spear_quality_inputs(cfg))
                if _is_pos(vd.get("avg_tq")):
                    asset["avg_tq"] = vd.get("avg_tq")
            else:
                # Archetype-native Q for the ballast (royalty/holdco): feed the OBJECTIVE quality facts
                # from research_cache so the Q pillar scores them on their OWN lenses (operator quality,
                # balance sheet, accretion-per-share) instead of echoing market_confidence. Absent facts
                # drop their lens; a name with none stays `<set>_lenses_pending` until fed — quarterly-fed,
                # never hardcoded. price=None ⇒ the balance-sheet lens uses the stored static mark (FX-safe).
                try:
                    if getattr(self, "_rc", None) is None:
                        self._rc = research_cache.ResearchCache()
                    qin = (holdco_nav_feed.read_quality_inputs(self._rc, tkr).get("inputs") or {})
                    if qin:
                        asset["quality_inputs"] = qin
                except Exception as e:
                    logging.warning("[holdco-Q] %s quality-input read failed: %s", tkr, e)
                # the carried-book/portfolio fair-value read (basis · confidence · wire) — surfaced for the
                # story card so the desk SEES why base moved (or why a held-back read didn't move it).
                if _fv_wired is not None:
                    asset["fair_value_read"] = _fv_wired

            # ---- Phase 8: apply the bounded live-catalyst overlay to the rating inputs ----
            ov = overlays.get(tkr, {})
            if ov:
                cd = ov.get("conviction_delta") or 0.0
                if cd:                                         # Q: conviction nudge
                    asset["conviction"] = max(0.0, min(1.0, float(asset.get("conviction") or 0.5) + cd))
                if ov.get("dilution_velocity") is not None:    # gate: financings can trip it
                    base_dil = asset.get("dilution_velocity") or 0.0
                    asset["dilution_velocity"] = max(base_dil, float(ov["dilution_velocity"]))
                if ov.get("permitting_stage"):                 # Q permitting lens
                    asset["stage"] = ov["permitting_stage"]
                # V: drill/grade/resource catalysts lift the bull/base scenario bands (bounded).
                bu, be = ov.get("bull_uplift_pct") or 0.0, ov.get("base_uplift_pct") or 0.0
                if bu and _is_pos(asset.get("bull")):
                    asset["bull"] = float(asset["bull"]) * (1.0 + bu)
                if be and _is_pos(asset.get("base")):
                    asset["base"] = float(asset["base"]) * (1.0 + be)
            assets.append(asset)

        context = {"mri": round(float(mri_score), 1), "regime": net_tilt,
                   "catalyst_feed": cat_feed.get("status", "n/a"),
                   "note": "Conviction Mode is assessment-only: no position caps, ES95 throttle, "
                           "covariance shrinkage, or Kelly de-leveraging. See Detailed Analysis for those."}
        state = build_conviction_state(assets, config=cfg, meta=context)
        # Phase 8 review: keep Conviction Mode calm — the catalyst feed is collapsed by default
        # ("collapsed" | "expanded" | "hidden"); the reactivity itself lives in the rating/V move.
        state["catalyst_display"] = (cfg.get("catalysts", {}) or {}).get("card_display", "collapsed")

        # Per-name DISPLAY CURRENCY (consistency fix): every valuation leg (price/floor/base/bull)
        # in the basket is CAD-normalized for the blended-book math, but the cockpit shows each name
        # next to its NATIVE-currency fundamentals (FMP 52-wk range, mcap…). Mixing the two made a
        # USD name (GROY) read price $2.88 (USD) beside floor $4.38 (CAD) — a contradiction, even
        # though φ/upside (ratios) were always right. Attach the native currency + the fx used + a
        # native ladder DERIVED from the same CAD legs by the same fx, so the absolute points
        # reconcile exactly with the ratios. CAD names get fx 1.0 (no change).
        usd_to_cad = float(self.state_cache.get("usd_to_cad") or 1.38)
        bv_all = cfg.get("ballast_valuation", {}) if isinstance(cfg.get("ballast_valuation"), dict) else {}
        pm_all = cfg.get("portfolio_metadata", {}) if isinstance(cfg.get("portfolio_metadata"), dict) else {}
        for b in state.get("baskets", []):
            ov = overlays.get(b.get("ticker"), {})
            if ov:
                b["catalysts"] = ov.get("recent", [])
                b["catalyst_signal"] = ov.get("net_signal", 0.0)
                b["catalyst_count"] = ov.get("count", 0)
                if ov.get("v_moved"):                          # flag that V was catalyst-adjusted
                    b["v_catalyst"] = {
                        "bull_uplift_pct": ov.get("bull_uplift_pct", 0.0),
                        "base_uplift_pct": ov.get("base_uplift_pct", 0.0),
                        "p_discovery_delta": ov.get("p_discovery_delta", 0.0),
                        "drivers": ov.get("v_drivers", []),
                    }
            tk = b.get("ticker")
            bv = bv_all.get(tk) or {}
            ccy = str(bv.get("currency") or (pm_all.get(tk) or {}).get("currency") or "CAD").upper()
            fx = usd_to_cad if ccy == "USD" else 1.0
            b["display_ccy"] = ccy
            b["fx_to_cad"] = round(fx, 4)
            nat = native_ladder(b.get("ladder") or {}, fx)    # CAD legs ÷ fx (φ/upside preserved)
            if nat:
                b["ladder_native"] = nat
            # V2 — probability-weighted scenario NAV: E[NAV] across the frozen ladder legs under
            # probabilities DERIVED from the live signals (a drill/grade catalyst's p_discovery_delta
            # GROUNDS it; the regime tilt refines it). No probability-mover → the honest breakeven
            # inversion. The intrinsic-input P10/P50/P90 band already ships on confidence_ribbon; this
            # is the complementary scenario-outcome expectation. CAD basis (the cockpit converts).
            try:
                import valuation_actions as _va
                lad = b.get("ladder") or {}
                if _is_pos(lad.get("price")):
                    b["scenario_nav"] = _va.scenario_nav(
                        lad, p_discovery_delta=(ov or {}).get("p_discovery_delta"),
                        regime_tilt=net_tilt, price=lad.get("price"))
            except Exception as e:
                logging.debug("scenario NAV skipped for %s: %s", tk, e)
        return state

    async def evaluate_master_architecture(self, force_macro=False):
        # Rebuild the per-cycle effective config ONCE (file defaults + confirmed overrides) and let
        # every engine read this same snapshot via its provider — overlay reaches the live book.
        cfg = self._refresh_effective_config()

        if not self.shares or force_macro:
            self._load_shares_from_csv(force=True)

        # 1. READ INSTANT SNAPSHOTS FROM WORKER CACHE UNDER THREAD LOCK
        with self.state_lock:
            mean_peer_ev = self.state_cache["mean_peer_ev"]
            peer_details = self.state_cache["peer_details"]
            avg_disc_cost = self.state_cache["avg_disc_cost"]
            
            y10 = self.state_cache["y10"]
            y30 = self.state_cache["y30"]
            spr = self.state_cache["spr"]
            ted = self.state_cache["ted"]
            eff = self.state_cache["eff"]
            vix = self.state_cache["vix"]
            macro_status = self.state_cache["macro_status"]
            
            prices = self.state_cache["prices"].copy()
            prices_status = self.state_cache["prices_status"]
            prices_stale_map = dict(self.state_cache.get("prices_stale", {}) or {})
            prices_asof_map = dict(self.state_cache.get("prices_asof", {}) or {})
            
            dxy_mom = self.state_cache["dxy_mom"]
            current_dxy = self.state_cache["current_dxy"]
            dxy_status = self.state_cache["dxy_status"]
            
            usd_to_cad = self.state_cache["usd_to_cad"]
            
            real_yield = self.state_cache["real_yield"]
            ry_status = self.state_cache["ry_status"]
            
            copper = self.state_cache["copper"]
            gold = self.state_cache["gold"]
            
            m1_price = self.state_cache["m1_price"]
            m180_price = self.state_cache["m180_price"]
            
            cftc_net_longs = self.state_cache["cftc_net_longs"]
            cftc_status = self.state_cache["cftc_status"]
            
            forensic_data = self.state_cache["forensic_metrics"].get("AGA.V")
            
            ballast_sloans = {}
            for ticker in book_tickers(cfg):
                if ticker == "AGA.V":          # the spear's forensic is fetched separately (above)
                    continue
                m = self.state_cache["forensic_metrics"].get(ticker)
                ballast_sloans[ticker] = m["sloan_cfo"] if m else 0.02
                
            df_rets = self.state_cache["df_rets"]
            corr_matrix = self.state_cache["corr_matrix"].copy()
            vols = self.state_cache["vols"].copy()
            es_95 = self.state_cache.get("es_95", -0.052)   # signed decimal (negative = loss); see seed note
            port_vol = self.state_cache.get("port_vol", 0.40)
            avg_corr = self.state_cache.get("avg_corr", 0.45)
            
            aga_adv = self.state_cache["aga_adv"]
            mri_history = self.state_cache.get("mri_history", {})
            feed_ts = {f: self.state_cache.get(f + "_ts", 0.0) for f in ("prices", "macro", "ry", "dxy", "cftc", "peers")}
            feed_status = {"prices": prices_status, "macro": macro_status, "ry": ry_status, "dxy": dxy_status, "cftc": cftc_status}

        self.cached_mean_peer_ev_oz = mean_peer_ev

        # --- Data freshness / point-in-time layer (v5.2) ---
        # Each feed refreshes on its own worker cadence (prices ~60s, macro ~30m, CFTC weekly), so
        # their vintages diverge. Expose every feed's age + a staleness flag vs configurable
        # thresholds, plus the cross-feed vintage skew, so stale-mix / look-ahead risk is visible
        # in the cockpit rather than silent.
        fresh_cfg = cfg.get("data_freshness", {})
        max_age = fresh_cfg.get("max_age_seconds", {
            "prices": 300, "macro": 5400, "ry": 5400, "dxy": 5400, "cftc": 172800, "peers": 86400
        })
        now_ts = time.time()
        freshness = {}
        any_stale = False
        for feed, ts in feed_ts.items():
            age = max(0.0, now_ts - ts) if ts else None
            thr = max_age.get(feed, 3600)
            stale = (age is None) or (age > thr) or (feed_status.get(feed) in ("DEGRADED", "DEGRADED_STALE"))
            any_stale = any_stale or stale
            freshness[feed] = {
                "age_seconds": round(age, 1) if age is not None else None,
                "age_minutes": round(age / 60.0, 1) if age is not None else None,
                "as_of": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else None,
                "threshold_seconds": thr,
                "stale": bool(stale),
                "status": feed_status.get(feed, "LIVE")
            }
        fast_ages = [now_ts - feed_ts[f] for f in ("prices", "macro", "ry", "dxy") if feed_ts.get(f)]
        vintage_skew = round(max(fast_ages) - min(fast_ages), 1) if len(fast_ages) >= 2 else 0.0
        # cache-file vintages so the cockpit can show provenance honestly (forensic = quarterly).
        # mri_history's stale threshold MUST track the fetcher's own TTL (mri_dynamic_bounds.
        # refresh_hours, +1h fetch slack): a fixed probe tighter than the refresh TTL flags a
        # by-design-fresh cache as stale for the back half of every cycle, painting DEGRADED_STALE
        # and docking the flat health penalty on a healthy pipeline.
        _mri_ttl = int(float((cfg.get("mri_dynamic_bounds") or {}).get("refresh_hours", 24)) * 3600) + 3600
        for fkey, fpath, thr in (("forensic", ".cache/forensic_cache.json", 86400),
                                 ("mri_history", ".cache/disk_cache_mri_history.json", _mri_ttl)):
            try:
                mt = os.path.getmtime(fpath)
                age = max(0.0, now_ts - mt)
                freshness[fkey] = {
                    "age_seconds": round(age, 1), "age_minutes": round(age / 60.0, 1),
                    "as_of": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt)),
                    "threshold_seconds": thr, "stale": bool(age > thr), "status": "CACHED"}
                any_stale = any_stale or freshness[fkey]["stale"]
            except OSError:
                pass
        # Data-AGE staleness for prices: the feed can be fresh by FETCH age (the worker ran 60s ago)
        # yet serve a stale CLOSE (yfinance NaN-latest bar). Fold the worker's per-holding data
        # staleness in so a stale MARK trips the flag — and name which holding + its as-of for the
        # cockpit — rather than reading LIVE off a frozen price.
        _book_tk = tuple(book_tickers(cfg))
        _stale_holdings = sorted(t for t in _book_tk if prices_stale_map.get(t))
        if "prices" in freshness:
            if _stale_holdings:
                freshness["prices"]["stale"] = True
                freshness["prices"]["status"] = "DEGRADED_STALE"
                any_stale = True
            freshness["prices"]["stale_holdings"] = _stale_holdings
            freshness["prices"]["holdings_asof"] = {t: prices_asof_map.get(t) for t in _book_tk}
        self.terminal_state["data_freshness"] = {
            "feeds": freshness,
            "stale_feed_count": sum(1 for v in freshness.values() if v["stale"]),
            "vintage_skew_seconds": vintage_skew,
            "skew_warn_seconds": fresh_cfg.get("skew_warn_seconds", 5400),
            "any_stale": bool(any_stale),
            "holdings_csv": getattr(self, "_holdings_csv", None)   # which holdings file + its age (days)
        }

        # 2. POPULATE METRICS IN TERMINAL STATE
        self.terminal_state["metrics"].update({
            "10Y": {"value": y10, "status": macro_status}, 
            "30Y": {"value": y30, "status": macro_status},
            "Spreads": {"value": spr, "status": macro_status}, 
            "TED": {"value": ted, "status": macro_status},
            "EFFR": {"value": eff, "status": macro_status}, 
            "VIX": {"value": vix, "status": macro_status}
        })

        p_aga = prices.get("AGA.V", 0.71)
        p_urc = prices.get("URC.TO", 4.82)
        p_groy = prices.get("GROY", 3.22)
        p_gmx = prices.get("GMX.TO", 2.04)
        spot_ag = prices.get("SI=F", 74.8)
        # honest status for the silver leg: the 74.8 fallback is a fabricated baseline, not a read
        spot_ag_status = prices_status if "SI=F" in prices else "INITIAL_BASELINE"
        wti_price = prices.get("CL=F", 80.0)

        self.terminal_state["metrics"]["Spot_Ag"] = {"value": spot_ag, "status": prices_status}
        self.terminal_state["metrics"]["WTI"] = {"value": wti_price, "status": prices_status}
        self.terminal_state["metrics"]["DXY"] = {"value": current_dxy, "status": dxy_status}
        self.terminal_state["metrics"]["DXY_MOMENTUM"] = {"value": dxy_mom, "status": dxy_status}
        # Yen channel (carry-unwind canary): publish ONLY on a real fetch — no fabricated baseline.
        # A violent USDJPY drop (yen strength) is the liquidity-cascade tell; agents read the level
        # here and compute the 5d change ad hoc (tripwire levels live in Living Memory).
        p_jpy = prices.get("JPY=X")
        if _is_pos(p_jpy):
            self.terminal_state["metrics"]["USDJPY"] = {"value": p_jpy, "status": prices_status}
        self.terminal_state["metrics"]["CFTC_Silver_Net_Longs"] = {"value": cftc_net_longs, "status": cftc_status}

        # Gold/Silver Ratio — derived from existing state, no additional API call
        gsr = gold / spot_ag if spot_ag > 0 else 80.0
        self.terminal_state["metrics"]["GSR"] = {"value": round(gsr, 2), "status": prices_status}

        # 3. PORTFOLIO EQUITY VALUE CALCULATION
        live_portfolio_value = (
            self.shares.get('AGA', 0) * p_aga + self.shares.get('URC', 0) * p_urc +
            self.shares.get('GMX', 0) * p_gmx + self.shares.get('GROY', 0) * p_groy * usd_to_cad +
            self.shares.get('UROY_CALL', 0) * 100.0 * self.uroy_call_price * usd_to_cad +
            # conventional positions (data-driven from the export via ws_symbol_map): each leg is
            # units × the export's OWN market price — CAD instruments (the CDR is hedged), no FX
            # term; a CDR's reference price must never mark it (ratio ≠ 1).
            sum((p.get('units') or 0) * (p.get('unit_price') or 0.0)
                for p in getattr(self, 'conv_positions', {}).values())
        )
        if live_portfolio_value < 1000: live_portfolio_value = cfg.get("target_capital", 5360.0)

        # 4. SET LIVE VS DEGRADED STATUS (status flags OR age-based staleness from the freshness layer)
        if any_stale or "DEGRADED_STALE" in [macro_status, prices_status, dxy_status, ry_status, cftc_status]:
            self.terminal_state["status"] = "DEGRADED_STALE"
        else:
            self.terminal_state["status"] = "LIVE"
        # A1.9: a dead background worker means the data it owns is silently freezing — the status
        # line must say so (grounded-or-silent at the process level), whatever the feeds claim.
        try:
            _dead = task_supervision.dead_workers(self.terminal_state.get("worker_health"))
            if _dead:
                self.terminal_state["status"] = "DEGRADED_WORKER_DOWN: " + ",".join(_dead)
        except Exception:
            pass

        # Curve-leg steepener type: the SAME rates_dashboard.bear_steepener flag P2.1/P3/regime_lens
        # read, taken from the PRIOR cycle's state (the dashboard is assessed later this cycle).
        # One cycle of lag is immaterial — curve regimes persist for weeks; None on a cold start
        # keeps the leg's legacy slope read rather than guessing.
        _prev_rates = self.terminal_state.get("rates_dashboard") or {}
        _bs_flag = (_prev_rates.get("bear_steepener") or {}).get("active")
        mri_score, mri_detail = self.macro_engine.calculate_mri(
            self.terminal_state["metrics"], spot_ag, real_yield, copper, gold, dxy_mom,
            return_detail=True, history=mri_history,
            # positional-leg provenance (2026-07-08): the metrics scan never covered these bare
            # floats — a cold-start real_yield/silver default flowed in unflagged. copper/gold carry
            # no per-feed status today, so they are honestly omitted rather than guessed.
            input_status={"silver": spot_ag_status, "real_yield": ry_status},
            bear_steepener=(bool(_bs_flag) if _bs_flag is not None else None),
        )
        self.terminal_state["mri"] = mri_score
        self.terminal_state["mri_decomposition"] = mri_detail
        # Stress vs extension (see calculate_mri): defensive consumers (sizer multiplier, health
        # penalty, DEFENSIVE directive) read STRESS — a hot-but-benign tape must not derisk the
        # book; add-gates keep the composite (don't deploy into stress OR a top). Fallback to the
        # composite when an axis is unavailable (fail-safe detail, hand-rolled tests).
        _axes = mri_detail.get("axes") or {}
        mri_stress = _axes.get("stress") if isinstance(_axes.get("stress"), (int, float)) else mri_score
        mri_extension = _axes.get("extension") if isinstance(_axes.get("extension"), (int, float)) else mri_score
        self.terminal_state["mri_axes"] = {"stress": mri_stress, "extension": mri_extension}

        # --- Fluid Macro Tape (v5.2): the key cross-asset signals the regime read is built on,
        # each with a value, a directional regime bias, and a short read, so the cockpit can render
        # a dense, glanceable macro strip. All derived from existing state (+ optional VIX term
        # structure) — no extra network round-trips beyond the consolidated price call. ---
        vix_val = float(self.terminal_state["metrics"].get("VIX", {}).get("value", 16.5))
        vix3m = prices.get("^VIX3M", 0.0) or 0.0
        vix_term = (vix3m / vix_val) if (vix_val > 0 and vix3m > 0) else None  # >1 contango (calm), <1 backwardation (stress)
        cu_au = (copper / gold * 1000.0) if gold > 0 else None
        dxy_gold = (current_dxy / gold * 1000.0) if gold > 0 else None
        cftc_cfg = cfg.get("cftc_params", {"norm_low": -15000, "norm_high": 85000})
        cftc_pctile = max(0.0, min(100.0, (cftc_net_longs - cftc_cfg["norm_low"]) /
                                   max(1e-9, (cftc_cfg["norm_high"] - cftc_cfg["norm_low"])) * 100.0))

        def _tape(key, label, value, bias, read, fmt="{:.2f}"):
            return {"key": key, "label": label,
                    "value": round(value, 4) if isinstance(value, (int, float)) else value,
                    "display": (fmt.format(value) if isinstance(value, (int, float)) else "—"),
                    "bias": bias, "read": read}

        # --- Quantity-of-money + unbundled-inflation regime tells (the cockpit measures the COST of
        # money well but was blind to the QUANTITY — the spec-flows engine juniors trade on — and to
        # WHY real yields move). Off-thread + cached ~6h; graceful (a blocked FRED endpoint → dormant,
        # no rows). One-directional: macro-tape rows (net_liq→broad lens, breakeven→metals lens) plus
        # dedicated surfaces. ---
        try:
            mq = await asyncio.to_thread(self._fetch_macro_quantities_free)
        except Exception:
            mq = None
        liq_dash, infl_dash, infl_driver = None, None, None
        if mq:
            try:
                import liquidity_monitor
                import inflation_regime
                wl, pwl = mq.get("walcl", (None, None))
                tg, ptg = mq.get("tga", (None, None))
                rp, prp = mq.get("rrp", (None, None))
                liq_dash = liquidity_monitor.assess(
                    walcl_musd=wl, tga_musd=tg, rrp_busd=rp,
                    prev_walcl_musd=pwl, prev_tga_musd=ptg, prev_rrp_busd=prp, config=self.config)
                fnom, pnom = mq.get("nominal_10y", (None, None))
                frl, prl = mq.get("real_10y", (None, None))
                # decomposition stays single-source (FRED nominal vs FRED real → no cross-feed basis
                # mismatch); fall back to the engine's live 10Y / real-yield marks only for the LEVEL.
                nom_now = fnom if fnom is not None else (y10 if y10 else None)
                real_now = frl if frl is not None else (real_yield if real_yield is not None else None)
                infl_dash = inflation_regime.assess(
                    nominal_10y=nom_now, real_10y=real_now,
                    prev_nominal_10y=pnom, prev_real_10y=prl, config=self.config)
                infl_driver = (infl_dash or {}).get("decomp_read")
            except Exception:
                obs.swallow("regime.macro_quantities")

        macro_tape = [
            # G3: GSR is a LEVEL / relative-value read, not a risk-appetite vote — a low ratio means
            # silver is relatively cheap (a setup), NEVER "leadership" (a direction claim) while the
            # ratio is rising. Level-accurate label, neutral bias (direction is asserted by the lens).
            _tape("gsr", "Gold/Silver", gsr, "neutral",
                  "Silver very cheap vs gold (setup)" if gsr > 85 else
                  ("Silver relatively cheap vs gold" if gsr < 75 else "Balanced")),
            # G3: copper's level is supply-tightness-driven, not clean demand — caveat the reflation read.
            _tape("cu_au", "Copper/Gold ×1k", cu_au if cu_au is not None else 0.0,
                  "risk_on" if (cu_au or 0) > 1.5 else "risk_off",
                  "Reflation bid (supply-contaminated — caveat)" if (cu_au or 0) > 1.5 else "Defensive / slowdown"),
            # G3: resolve the contradiction — gold strength vs the dollar is a debasement / risk-OFF read
            # (label and bias must agree), not "gold dominant → risk_on".
            _tape("dxy_gold", "DXY/Gold ×1k", dxy_gold if dxy_gold is not None else 0.0,
                  "risk_on" if (dxy_gold or 0) > 45 else "risk_off",
                  "Dollar strong vs gold" if (dxy_gold or 0) > 45 else "Gold strong vs dollar"),
            _tape("dxy", "DXY", current_dxy if current_dxy is not None else 0.0,
                  "risk_off" if (current_dxy or 0) > 104 else ("risk_on" if (current_dxy or 0) < 100 else "neutral"),
                  "Strong dollar" if (current_dxy or 0) > 104 else ("Weak dollar" if (current_dxy or 0) < 100 else "Neutral"), "{:.1f}"),
            _tape("real_yield", "Real Yield", real_yield,
                  "risk_off" if real_yield > 2.0 else ("risk_on" if real_yield < 0.5 else "neutral"),
                  "Headwind for metals" if real_yield > 2.0 else ("Tailwind for metals" if real_yield < 0.5 else "Neutral"), "{:.2f}%"),
            _tape("sofr_spread", "SOFR Spread", ted,
                  "risk_off" if ted > 0.20 else "risk_on",
                  "Funding stress" if ted > 0.20 else "Funding calm", "{:+.2f}%"),
            _tape("hy_spread", "HY Spread", spr,
                  "risk_off" if spr > 4.0 else "risk_on",
                  "Credit stress" if spr > 4.0 else "Credit benign", "{:.2f}%"),
            _tape("curve_2s30s", "30Y–10Y", (y30 - y10),
                  "risk_off" if (y30 - y10) < 0 else "neutral",
                  "Inverted (late cycle)" if (y30 - y10) < 0 else "Positive slope", "{:+.2f}%"),
            _tape("vix", "VIX", vix_val,
                  "risk_off" if vix_val > 22 else ("risk_on" if vix_val < 15 else "neutral"),
                  "Elevated fear" if vix_val > 22 else ("Complacent" if vix_val < 15 else "Normal")),
            _tape("cftc", "CFTC Net %ile", cftc_pctile,
                  "risk_off" if cftc_pctile > 80 else ("risk_on" if cftc_pctile < 25 else "neutral"),
                  "Crowded long" if cftc_pctile > 80 else ("Washed out (contrarian)" if cftc_pctile < 25 else "Mid-range"), "{:.0f}"),
        ]
        if vix_term is not None:
            macro_tape.append(_tape("vix_term", "VIX Term (3M/1M)", vix_term,
                                    "risk_off" if vix_term < 1.0 else "risk_on",
                                    "Backwardation (stress)" if vix_term < 1.0 else "Contango (calm)", "{:.2f}"))
        # Fed net liquidity (broad/flows lens) — the QUANTITY of money the spear trades on
        if liq_dash and liq_dash.get("available"):
            macro_tape.append(_tape("net_liq", "Fed Net Liquidity",
                                    liq_dash.get("net_liquidity_t") if liq_dash.get("net_liquidity_t") is not None else 0.0,
                                    liq_dash.get("bias", "neutral"), liq_dash.get("read", "—"), "{:.2f}T"))
        # 10Y breakeven (metals lens) — and unbundle the EXISTING real-yield read with the WHY
        if infl_dash and infl_dash.get("available"):
            macro_tape.append(_tape("breakeven", "10Y Breakeven",
                                    infl_dash.get("breakeven") if infl_dash.get("breakeven") is not None else 0.0,
                                    infl_dash.get("bias", "neutral"), infl_dash.get("level_read", "—"), "{:.2f}%"))
            if infl_driver:
                for _row in macro_tape:
                    if _row.get("key") == "real_yield":
                        _row["read"] = f"{_row['read']} · {infl_driver}"
                        break

        # Seesaw-day classifier — JOIN the yield decomposition to the metals tape and name the day
        # (SEESAW-B / SEESAW-E / COMMON-ENEMY / BOTH-BID-A / LIQUIDATION). Evidence for the B⇄E axis;
        # graceful: no yesterday snapshot yet ⇒ dormant, no fabricated day type.
        try:
            import seesaw_day as _ssd
            _ssd.record_snapshot({"gold": gold, "silver": spot_ag, "y10": y10,
                                  "real": real_yield,
                                  "be": (infl_dash or {}).get("breakeven"),
                                  "vix": vix_val})
            _ss_prior = _ssd.prior_snapshot()
            if _ss_prior:
                _pg, _py = _ss_prior.get("gold"), _ss_prior.get("y10")
                _m_ret = ((gold / _pg - 1.0) * 100.0) if (_pg and gold) else None
                _dy10 = (y10 - _py) if (_py is not None and y10 is not None) else None
                _decomp = (infl_dash or {}).get("decomposition") or {}
                ss = _ssd.classify(metal_ret_pct=_m_ret, d_y10=_dy10,
                                   d_real=_decomp.get("d_real_yield"),
                                   d_breakeven=_decomp.get("d_breakeven"),
                                   config=self.config)
                if ss.get("available"):
                    macro_tape.append(_tape("seesaw", "Seesaw Day",
                                            _m_ret if _m_ret is not None else 0.0,
                                            ss.get("bias", "neutral"),
                                            f"{ss.get('day_type')}: {ss.get('read', '—')}", "{:+.2f}%"))
                    self.terminal_state["seesaw_day"] = ss
        except Exception:
            obs.swallow("regime.seesaw_day")

        risk_off_count = sum(1 for t in macro_tape if t["bias"] == "risk_off")
        risk_on_count = sum(1 for t in macro_tape if t["bias"] == "risk_on")
        self.terminal_state["macro_tape"] = {
            "signals": macro_tape,
            "risk_off_count": risk_off_count,
            "risk_on_count": risk_on_count,
            "net_tilt": "RISK-OFF" if risk_off_count > risk_on_count else ("RISK-ON" if risk_on_count > risk_off_count else "BALANCED"),
            "top_mri_driver": mri_detail.get("top_driver", "n/a"),
            "vix_term_structure": round(vix_term, 3) if vix_term is not None else None
        }
        # dedicated regime surfaces for the two new tells (graceful: omitted when FRED is unreachable)
        if liq_dash:
            self.terminal_state["net_liquidity"] = liq_dash
        if infl_dash:
            self.terminal_state["inflation_regime"] = infl_dash

        # VP (Phase-V completion): full UST curve from FREE feeds (yfinance ^IRX/2YY=F/^FVX/^TNX/^TYX),
        # replacing the plan-gated FMP treasury endpoint so 2s10s / 5s30s / 30Y-funds compute on LIVE
        # yields (year2/5/10/30 were previously null -> the rates leg ran partly blind). FMP stays as
        # optional redundancy if a plan tier later supports it. Off-thread + cached ~3h; loop never blocks.
        try:
            tc_free = await asyncio.to_thread(self._fetch_treasury_curve_free)
        except Exception:
            tc_free = None
        if tc_free and tc_free.get("tenors"):
            self.terminal_state["treasury_curve"] = tc_free
        elif getattr(self, "fmp", None):       # optional FMP redundancy (gated tier -> graceful no-op)
            try:
                tr = await asyncio.to_thread(self.fmp.treasury)
                cur = tr.get("data") if isinstance(tr, dict) else None
                if isinstance(cur, dict):
                    self.terminal_state["treasury_curve"] = {
                        "date": cur.get("date"),
                        "tenors": {k: cur.get(k) for k in
                                   ("month1", "month3", "month6", "year1", "year2", "year3",
                                    "year5", "year7", "year10", "year20", "year30")},
                        "source": "FMP", "cached": bool(tr.get("cached", True)),
                    }
            except Exception:
                pass

        # P2.1 rates dashboard — the bear-steepener / fiscal-dominance UPSTREAM tell. A standalone
        # regime surface (NOT a macro-tape risk-on/off vote: a firing bear-steepener is a LEADING
        # tailwind for the metals book, not a risk-off signal). One-directional: it feeds the
        # scenario weights (P3) and a dedicated panel; the engine never recomputes it backwards.
        rates_dash = self._rates_assessment()
        if rates_dash:
            self.terminal_state["rates_dashboard"] = rates_dash
        # Regime Engine v2 (G1+G2): split the blended macro-tape vote into two same-lens sub-scores —
        # Broad-Market Risk (context) and Metals Regime (drives conviction) — so a metals headwind
        # (elevated real yield, a firing bear-steepener) can no longer be buried by a broad risk-on
        # majority. The curve tell reads the SAME rates_dashboard.bear_steepener flag P2.1/P3 use (one
        # interpretation, no divergence). One-directional consumer of the tape; never re-blended.
        try:
            import regime_lens
            self.terminal_state["regime_lens"] = regime_lens.assess(
                self.terminal_state.get("macro_tape"), rates=rates_dash, config=self.config)
        except Exception:
            pass
        # P2.2 / P2.4 — the AI-productivity thesis-breaker + the oil-supply-risk watch (graceful when
        # their live feeds aren't wired). Standalone surfaces that also feed the consolidated board.
        prod_dash = self._productivity_assessment()
        if prod_dash:
            self.terminal_state["productivity_monitor"] = prod_dash
        oil_dash = self._oil_supply_assessment()
        if oil_dash:
            self.terminal_state["oil_supply"] = oil_dash

        # Shared by P2.3 / P3 / P4: the metric lookup, the USD/CAD dry-powder carry, and the holdings
        # list (book membership = barbell_weights keys + thesis_slot), built once.
        def _mv(*keys, default=None):
            return macro_snapshot.metric_value(self.terminal_state.get("metrics"), *keys, default=default)
        usdcad_read = None
        holdings = []
        try:
            usdcad_read = sentinel_board.usdcad_carry(_mv("EFFR", "FEDFUNDS"),
                                                      _mv("BOC_RATE", "CA_POLICY_RATE"),
                                                      trend=_mv("USDCAD_MOMENTUM"))
        except Exception:
            usdcad_read = None
        _bw = self.config.get("barbell_weights", {}) or {}
        _pm = self.config.get("portfolio_metadata", {}) or {}
        _bv = self.config.get("ballast_valuation", {}) or {}
        for tkr, wt in _bw.items():
            if tkr == "_comment" or not isinstance(wt, (int, float)):
                continue
            meta = _pm.get(tkr, {}) if isinstance(_pm.get(tkr), dict) else {}
            # commodity (axis 2) lives in ballast_valuation; the spear is silver. Feeds the divergence
            # sentinel's factor routing (and is inert for the other holdings consumers).
            commodity = (_bv.get(tkr, {}) or {}).get("commodity") or (
                "silver" if meta.get("thesis_slot") == "silver-spear" else "")
            holdings.append({"ticker": tkr, "weight": wt, "slot": meta.get("thesis_slot"),
                             "archetype": meta.get("archetype"), "commodity": commodity,
                             "scenario_payoffs": meta.get("scenario_payoffs")})

        # P2.3 — consolidate every upstream tell (new monitors + existing macro-tape signals + the
        # USD/CAD dry-powder carry) into ONE SENTINEL surface; each card shows its read + any flag and
        # names the scenario it feeds (one-directional into P3). Coverage gaps are listed honestly.
        try:
            self.terminal_state["sentinel_board"] = sentinel_board.build(
                rates=rates_dash, productivity=prod_dash, oil=oil_dash,
                macro_tape=self.terminal_state.get("macro_tape"), usdcad=usdcad_read)
        except Exception:
            pass
        # P3 — the scenario-robustness convergence point. Builds the four-scenario weights FROM the
        # signals above (rates→B, productivity→C, macro→A, copper→D) and scores every holding on
        # dispersion-penalized robustness across A/B/C/D. One-directional: a consumer of the monitors
        # that informs sizing/hedging (and surfaces the scenario-C / uranium hole), never the barbell.
        try:
            import scenario_engine
            # Whole-book scenario set (the CEG lesson): merge conventional-lane holdings (config
            # membership + explicit scenario_payoffs; live sleeve weight else book_share_fallback)
            # into the barbell before assessing, so the coverage gauge reads book truth — a hole a
            # conventional name was bought to cover no longer shows as uncovered.
            # index-lane holdings (index_lane.py) merge the same way — they exist to cover a hole,
            # so the coverage gauge must see them the moment they are held.
            conv_meta = {t: m for t, m in (self.config.get("portfolio_metadata") or {}).items()
                         if isinstance(m, dict) and m.get("lane") in ("conventional", "index")
                         and (m.get("units") or 0) > 0}
            scen_holdings = scenario_engine.merge_conventional(
                holdings, conv_meta, live_rows=self.terminal_state.get("conventional_sleeve"))
            self.terminal_state["scenario_engine"] = scenario_engine.assess(
                scen_holdings, rates=rates_dash, productivity=prod_dash, oil=oil_dash,
                macro_tape=self.terminal_state.get("macro_tape"), config=self.config,
                learned_observations=self._scenario_learned_observations())
        except Exception:
            pass

        # The automated decoupling SENTINEL — auto-fires a pin + a logged event the MOMENT a holding
        # decouples from its dominant commodity factor on real volume, so the operator never has to
        # click /explain-move to notice it. Reuses cached tape only (prices-worker session returns +
        # comps-worker 60d β/σ) → NO new network; deduped to once per event; decision-support only.
        try:
            div = self._divergence_assessment(holdings)
            self.terminal_state["divergence"] = div
            self._fire_divergence(div)
        except Exception:
            obs.swallow("divergence.assess")

        # Book-factor lens (read-only) — is this a PORTFOLIO or one bet wearing different tickers? The
        # realized single-factor read (avg pairwise ρ + each ballast's ρ to the spear) and the scenario
        # coverage (which futures the book has no answer to), measured from the cached corr matrix + the
        # scenario engine. It MEASURES the concentration/coverage critique; never an allocation call.
        try:
            import book_factor
            corr = (self.state_cache or {}).get("corr_matrix") or {}
            book_tks = [h.get("ticker") for h in holdings if h.get("ticker")]
            # a HELD index-lane diversifier is measured in the concentration read (it is the one name
            # whose whole job is to move that number) — membership is config, never the barbell.
            try:
                import index_lane as _il
                book_tks += [p["ticker"] for p in _il.positions(self.config.get("portfolio_metadata"))
                             if (p.get("units") or 0) > 0 and p["ticker"] not in book_tks]
            except Exception:
                obs.swallow("index_lane.book_tks")
            spear = next((h["ticker"] for h in holdings if h.get("slot") == "silver-spear"), "AGA.V")
            self.terminal_state["book_factor"] = {
                "concentration": book_factor.factor_concentration(corr, book_tks, spear=spear, config=self.config),
                "coverage": book_factor.scenario_coverage(self.terminal_state.get("scenario_engine") or {},
                                                          config=self.config),
            }
            # Crash-honest tail read (λ_L to the spear): average pairwise ρ converges to 1 exactly
            # when it matters; this measures each ballast's joint-worst-decile frequency from the
            # reproducible close store (price_history — never a live quote). Fenced separately so a
            # store problem can never take down the sibling gauges.
            try:
                import tail_dependence
                from price_history import PriceHistory
                lookback = int((self.config.get("book_factor") or {}).get(
                    "tail_lookback_days", tail_dependence.DEFAULT_TAIL_CONFIG["tail_lookback_days"]))
                closes = tail_dependence.closes_from_history(PriceHistory(), book_tks,
                                                             lookback_days=lookback)
                self.terminal_state["book_factor"]["tail"] = tail_dependence.book_tail_read(
                    closes, book_tks, spear=spear, config=self.config)
            except Exception:
                obs.swallow("book_factor.tail")
        except Exception:
            obs.swallow("book_factor")

        # Correlation / independence monitor (read-only) — is each sleeve still a SECOND THESIS, or has
        # it drifted into the spear's factor? The held-book role check (ρ to the spear + the 60d→120d
        # DRIFT trend), lane-aware: a conventional sleeve correlating to the spear is the alarm that
        # matters most. Complements book_factor's static 0.85 LEVEL alarm with the TREND; the
        # conventional core leans on this. MEASURES; never sizes. Fenced — never breaks the eval cycle.
        try:
            corr = (self.state_cache or {}).get("corr_matrix") or {}
            corr_long = (self.state_cache or {}).get("corr_matrix_long") or None
            spear = next((h["ticker"] for h in holdings if h.get("slot") == "silver-spear"), "AGA.V")
            ci = correlation_monitor.assess_book_independence(corr, holdings, spear=spear,
                                                             corr_matrix_long=corr_long, config=self.config)
            self.terminal_state["correlation_independence"] = ci
            self._fire_correlation_drift(ci)
        except Exception:
            obs.swallow("correlation_monitor")

        # PREDICT arb SENTINEL — the Wealthsimple Predict / Kalshi probability scanner. A pure
        # sweep over the predict worker's cached snapshot (NO new network in the eval cycle):
        # L1 structural Dutch books (parity / partition / ladder dominance) + L2 model-vs-market
        # edges, everything net of the WS fee + FX stack. Deduped auto-fire (Signals note +
        # Living-Memory sentinel + ledger line); alerts only — the operator executes in the app.
        try:
            pa = self._predict_arb_assessment()
            self.terminal_state["predict_arb"] = pa
            self._fire_predict_arb(pa)
        except Exception:
            obs.swallow("predict_arb.assess")

        # Conventional-core SENTINEL zones (read-only) — for conventional-lane holdings, the asymmetry-
        # zone cross (price crossing the dual-sided ladder's floor/base/bull) + the rebalance-band drift,
        # fired once per zone entry. The PRODUCER (conventional_holdings.py — built 2026-08-02 after a
        # real held CDR position rendered nowhere) reads portfolio_metadata entries with
        # lane:'conventional' + a dual_sided underwriting block, prices them via the cached/budget-
        # capped FMP client (profile TTL 1h ⇒ at most one live call per name per hour — the eval loop
        # never burns quota), and writes state_cache['dual_sided_reads'] {tk: {lens, price, ladder,
        # weight, target}} + the cockpit's terminal_state['conventional_sleeve'] rows. Membership is
        # portfolio_metadata+lane, NEVER barbell_weights — the lane guard keeps conventional names out
        # of the resource sizer/scout/council machinery. Until a conventional name is declared this is
        # a clean no-op. MEASURES; never sizes. Fenced — never breaks the eval cycle.
        try:
            import conventional_holdings as _ch
            pmeta = self.config.get("portfolio_metadata")
            conv_pos = _ch.positions(pmeta)
            if conv_pos:
                _fmp = getattr(self, "fmp", None)

                def _px(ref, _f=_fmp):
                    if not _f:
                        return None
                    return ((_f.profile(ref) or {}).get("data") or {}).get("price")

                _conv_pos_csv = getattr(self, "conv_positions", {}) or {}
                # the export's units override config's (fills beat declarations) and its market
                # price marks the instrument — units × REF price would mis-mark (CDR ratio ≠ 1).
                for _p in conv_pos:
                    _csv = _conv_pos_csv.get(_p["ticker"])
                    if _csv and _csv.get("units") is not None:
                        _p["units"] = _csv["units"]
                ds_reads = _ch.build_reads(
                    conv_pos, _px, config=self.config,
                    nav=live_portfolio_value,
                    unit_prices={t: (_conv_pos_csv.get(t) or {}).get("unit_price")
                                 for t in [_p["ticker"] for _p in conv_pos]})
                if isinstance(self.state_cache, dict):
                    self.state_cache["dual_sided_reads"] = ds_reads
                self.terminal_state["conventional_sleeve"] = _ch.sleeve_rows(ds_reads)
            else:
                ds_reads = (self.state_cache or {}).get("dual_sided_reads") or {}
                self.terminal_state["conventional_sleeve"] = []
            conv = [r for r in ds_reads.values() if isinstance(r, dict) and not r.get("error")]
            if conv:
                prev = (self.state_cache or {}).get("conventional_zones_prev") or {}
                cz = conventional_sentinel.assess_book(conv, prev_zones=prev, config=self.config)
                self.terminal_state["conventional_zones"] = cz
                if isinstance(self.state_cache, dict):
                    self.state_cache["conventional_zones_prev"] = cz["zones_next"]
                self._fire_conventional_zones(cz)
                # NIS (Phase 5): fire any narrative breaks the dual-sided reads carried (a turnaround
                # claim whose receipt reversed). Same dormant-until-conventional-holdings discipline.
                nflags = [f for r in conv for f in (r.get("narrative_flags") or [])]
                if nflags:
                    self._fire_narrative_break(nflags)
        except Exception:
            obs.swallow("conventional_sentinel")

        # INDEX-DIVERSIFIER lane (index_lane.py, 2026-09-05) — the same producer/sentinel shape as the
        # conventional lane: portfolio_metadata entries with lane:'index' + an index_lane read block are
        # priced (cached/budget-capped FMP, stored-price fallback STAMPED stale), valued at INDEX level
        # (street inputs → a ZONE, never a rating), banded against the lane's floor/ceiling, and run
        # through the conventional sentinel's zone-cross logic unchanged (same ladder shape). Writes
        # state_cache['index_reads'] + terminal_state['index_sleeve'] / ['index_zones']. Membership is
        # config, NEVER barbell_weights; the lane guard keeps it out of scout/council/discovery.
        # Clean no-op until an index name is declared. MEASURES; never sizes. Fenced.
        try:
            import index_lane as _il
            idx_pos = _il.positions(self.config.get("portfolio_metadata"))
            if idx_pos:
                _fmp_i = getattr(self, "fmp", None)

                def _px_i(ref, _f=_fmp_i):
                    if not _f:
                        return None
                    return ((_f.profile(ref) or {}).get("data") or {}).get("price")

                _csv_i = getattr(self, "conv_positions", {}) or {}
                for _p in idx_pos:
                    _c = _csv_i.get(_p["ticker"])
                    if _c and _c.get("units") is not None:
                        _p["units"] = _c["units"]
                idx_reads = _il.build_reads(
                    idx_pos, _px_i, config=self.config, nav=live_portfolio_value,
                    unit_prices={t: (_csv_i.get(t) or {}).get("unit_price")
                                 for t in [_p["ticker"] for _p in idx_pos]})
                if isinstance(self.state_cache, dict):
                    self.state_cache["index_reads"] = idx_reads
                self.terminal_state["index_sleeve"] = _il.sleeve_rows(idx_reads)
                good = [r for r in idx_reads.values() if isinstance(r, dict) and not r.get("error")]
                if good:
                    prev_i = (self.state_cache or {}).get("index_zones_prev") or {}
                    iz = conventional_sentinel.assess_book(good, prev_zones=prev_i, config=self.config)
                    self.terminal_state["index_zones"] = iz
                    if isinstance(self.state_cache, dict):
                        self.state_cache["index_zones_prev"] = iz["zones_next"]
                    self._fire_conventional_zones(iz)
            else:
                self.terminal_state["index_sleeve"] = []
        except Exception:
            obs.swallow("index_lane")

        # 5. MICRO FORENSICS RUNWAY
        rf_floor = self.valuation_engine.calculate_rep_floor()
        monthly_burn = cfg["cash_burn"]["monthly_burn_rate"]
        
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        cash_runway_months = cash_component / monthly_burn if monthly_burn > 0 else 99.0

        if forensic_data:
            sloan_cfo = forensic_data["sloan_cfo"]
            sloan_bs = forensic_data["sloan_bs"]
            shares_t0 = forensic_data["shares_t0"]
            shares_t1 = forensic_data["shares_t1"]
            sga_expense = forensic_data["sga_t0"]
            cfo_t0 = forensic_data.get("cfo_t0")
            cfo_t1 = forensic_data.get("cfo_t1")
            cash_t0 = forensic_data.get("cash_t0")
            aga_enterprise_value = forensic_data.get("enterprise_value")
        else:
            sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense = 0.021, 0.024, 208600000, 208600000, 450000
            cfo_t0, cfo_t1, cash_t0 = None, None, None
            aga_enterprise_value = None

        forensic_score, forensic_penalty, forensic_details = self.forensic_engine.calculate_jsf_score(
            "AGA.V", cash_component, monthly_burn,
            sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense,
            cfo_t0=cfo_t0, cfo_t1=cfo_t1, cash_t0=cash_t0, enterprise_value=aga_enterprise_value
        )
        
        self.terminal_state["forensics"] = {
            "jsf_score": forensic_score,
            "penalty_factor": round(forensic_penalty, 3),
            "runway": round(cash_runway_months, 1),
            "sloan_cfo": round(sloan_cfo, 4),
            "sloan_bs": round(sloan_bs, 4),
            "details": forensic_details,
            "overrides_applied": forensic_details.get("overrides_applied", [])
        }

        # 6. DYNAMIC AISC AND VALUATION MARGINS
        base_aisc = cfg["dynamic_discovery_v5"]["estimated_industry_aisc_2026"]
        dynamic_aisc = base_aisc + max(0, wti_price - 80.0) * 0.15
        capital_discount_factor = self.valuation_engine.calculate_capital_discount_factor(y30)

        # Live realized silver vol (Phase 4a) feeds the option-premium vol term, replacing the old
        # hardcoded 0.25. Derived from the cached 5y MRI silver history; falls back to 0.30 if absent.
        silver_vol = _realized_vol(mri_history.get("silver", []), lookback=60) or 0.30

        # 7. TERM STRUCTURE STRESS PREMIUMS
        if m1_price > 0 and m180_price > 0 and m1_price > m180_price:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": True, "status": "LIVE"}
            uplift_premium = min(0.25, max(0.0, (m1_price - m180_price) / m1_price) * 5.0)
        else:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": False, "status": "LIVE"}
            uplift_premium = 0.0

        # ---- LEGACY valuation (v5.2) — retained for ONE release as the reconciliation baseline and to
        # keep the v4_valuation diagnostic keys populated. NOT authoritative. discovery_premium_factor
        # here is the opaque ~3.3x operating-leverage multiple (=1.68*(spot-AISC)/AISC) Phase 4a removes;
        # ROV here is the dead/incoherent additive term. Both are superseded by the triangulation below.
        phi_margin = max(0.58, (spot_ag - dynamic_aisc) / spot_ag) if spot_ag > dynamic_aisc else 0.05
        commodity_leverage = spot_ag / dynamic_aisc if dynamic_aisc > 0 else 1.0
        exp_scalar = cfg["dynamic_discovery_v5"].get("explorer_re_rating_scalar", 1.68)
        raw_factor = commodity_leverage * phi_margin * exp_scalar
        spot_dev = max(0, (spot_ag - 76.5) / 50)
        ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - mri_score / 100)
        discovery_premium_factor = max(0.50, min(raw_factor, ceiling))
        rov = self.valuation_engine.calculate_continuous_rov(real_yield, spot_ag, cfg.get("rov_default", 1.18))
        is_iai_per_share, jurisdiction_uplift = self.valuation_engine.calculate_is_iai(
            mean_peer_ev, discovery_premium_factor, spot_ag, capital_discount_factor
        )
        jurisdiction_uplift = jurisdiction_uplift * (1.0 + uplift_premium)
        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (exp.get("expected_future_oz", 0) * mean_peer_ev *
                             jurisdiction_uplift * exp.get("probability_of_discovery", 0.25))
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)
        legacy_aga_intrinsic = (
            (0.15 * rf_floor) + (0.70 * is_iai_per_share * forensic_penalty) + (0.15 * rov) + exp_per_share
        )

        # ---- 8. NEW (Phase 4a) TRIANGULATED INTRINSIC (AUTHORITATIVE) ----
        # Confidence-tilted Cost + (quality-graded, de-overlapped) Market + Income blend. Sector silver
        # strength flows ONCE through the live peer EV/oz (market) and ONCE through the stage-decayed
        # option-convexity premium (income/option) — the redundant discovery_premium_factor and the dead
        # additive ROV are gone, so a single silver move can no longer be triple-counted.
        spear_kwargs = dict(
            peer_ev_oz=mean_peer_ev, spot_ag=spot_ag, capital_discount_factor=capital_discount_factor,
            real_yield=real_yield, silver_vol=silver_vol, forensic_penalty=forensic_penalty,
            dynamic_aisc=dynamic_aisc, shares_outstanding=cfg["aga_shares_out"],
        )
        spear_detail = self.valuation_engine.calculate_spear_intrinsic(**spear_kwargs)
        aga_intrinsic = spear_detail["v_intrinsic"]
        scenario_range = self.valuation_engine.run_intrinsic_scenarios(spear_kwargs, silver_vol)
        reconciliation = {
            "legacy_intrinsic": round(legacy_aga_intrinsic, 3),
            "new_intrinsic": round(aga_intrinsic, 3),
            "delta": round(aga_intrinsic - legacy_aga_intrinsic, 3),
            "delta_pct": round((aga_intrinsic / legacy_aga_intrinsic - 1.0) * 100, 1) if legacy_aga_intrinsic else None,
            "removed_discovery_multiple": round(discovery_premium_factor, 2),
            "note": "Phase 4a removed the embedded ~%.2fx discovery/operating-leverage multiple and the dead additive ROV; silver torque now flows once via peer EV/oz and once via the stage-decayed option premium." % discovery_premium_factor,
            "legacy_components": {"rep_floor": round(rf_floor, 3), "is_iai_x_pen": round(is_iai_per_share * forensic_penalty, 3),
                                  "rov": round(rov, 3), "exp": round(exp_per_share, 3)},
        }

        # --- Currency normalization (v5.2): the blended index PPI and EV_Blended are computed in
        # CAD. GROY trades in USD (NYSE American) while AGA.V/URC.TO/GMX.TO trade in CAD (TSX/TSX-V).
        # Previously PPI summed GROY's raw USD price with three CAD prices and EV_Blended mixed a
        # USD-anchored GROY sleeve into a CAD blend, biasing Implied Upside. Convert every leg to CAD
        # up front. Per-name currency is config-tunable via `ballast_valuation[name].currency`.
        bv_cfg = cfg.get("ballast_valuation", {})
        def _fx_to_cad(name, default_ccy):
            nm = bv_cfg.get(name) or {}
            ccy = nm.get("currency", default_ccy)
            return usd_to_cad if str(ccy).upper() == "USD" else 1.0
        bw = _resolve_barbell_weights(cfg)   # SINGLE validated source: book MEMBERSHIP (keys) + weights
        # Expose the EFFECTIVE (overlay-merged) book to readers — the cockpit's CHANGE diff and any
        # other consumer — so they never reconstruct it from the stale base config file after a
        # confirmed cut / reweight (which lives in the dynamic-config overlay, not v5_config.json).
        self.terminal_state["barbell_weights"] = dict(bw)
        SPEAR = "AGA.V"
        # Per-name native price for every CURRENT book member, normalized to CAD. Membership is
        # data-driven (whatever `barbell_weights` holds), so cutting/adding a name flows through here
        # with no code edit — and no KeyError when a cut name (e.g. URC.TO) is gone from the book.
        _native_px = {"AGA.V": p_aga, "URC.TO": p_urc, "GROY": p_groy, "GMX.TO": p_gmx}
        def _book_dccy(tk):
            return "USD" if str(tk).upper() == "GROY" else "CAD"   # GROY on NYSE American; the rest CAD
        cad_px = {tk: _native_px.get(tk, prices.get(tk, 0.0)) * _fx_to_cad(tk, _book_dccy(tk)) for tk in bw}
        p_aga_cad = cad_px.get(SPEAR, 0.0)                          # spear alias for the AGA-only blocks
        ppi = sum(bw[tk] * cad_px.get(tk, 0.0) for tk in bw)        # barbell-weighted CAD price index

        ballast_cfg = cfg.get("ballast_multiples", {"URC.TO": 1.15, "GROY": 1.15, "GMX.TO": 1.20})
        _ballast_default_mult = {"URC.TO": 1.15, "GROY": 1.15, "GMX.TO": 1.20}
        def _ballast_pen(tk):   # forensic (Sloan-accrual) penalty for one ballast name
            return 1.0 - min(0.30, max(0, ballast_sloans.get(tk, 0.0) - 0.05) * 2.0)

        # Spot-linked ballast fair value (v5.2): anchor each sleeve to a fundamental reference
        # re-scaled by LIVE commodity spot, NOT by the name's own share price. This severs the
        # self-referential `price * multiple` feedback loop where a rally manufactured matching
        # "fair value" and Implied Upside never compressed. ref_price defaults to the engine's
        # documented reference prices (the same constants used as live-price fallbacks), spot_ref
        # to the silver reference frame; commodity/ref_price/spot_ref/spot_beta are config-tunable
        # per name via `ballast_valuation` so an analyst can plug in a true NAV anchor.
        spot_ref_default = {"silver": 74.8, "gold": gold if gold and gold > 0 else 2650.0}
        ballast_defaults = {
            "URC.TO": {"ref_price": 4.82, "commodity": "uranium"},
            "GROY":   {"ref_price": 3.22, "commodity": "gold"},
            "GMX.TO": {"ref_price": 2.04, "commodity": "diversified"},
        }

        ballast_anchors = {}

        def _ballast_fv(name, base_mult, forensic_pen, fx):
            nm = bv_cfg.get(name, {})
            dflt = ballast_defaults.get(name, {})
            commodity = nm.get("commodity", dflt.get("commodity", "silver"))
            ref_price = nm.get("ref_price", dflt.get("ref_price", 1.0))
            # Anchor fair value on a SOURCED NAV (research_cache: live nav_inventory mark, else the
            # stamped nav_adj_per_share) rather than the frozen legacy price snapshot the config
            # ref_price encodes (those constants are an old price mark, NOT a NAV — a self-referential
            # anchor). allow_book=False: raw accounting book understates NAV for these holdco/royalty/
            # physical structures (a project generator carries royalties at cost, ~0.71 book vs ~2.04
            # price), so we NEVER anchor on it — we keep the documented config ref_price and FLAG the
            # name as still on a legacy anchor until a real NAV is sourced.
            anchor = "config_ref_price (legacy snapshot)"
            nav = self._research_book_native(name, allow_book=False)
            if nav is not None and _is_pos(nav[0]):
                ref_price, nav_ccy = nav
                anchor = "research_cache_nav"
                fx = usd_to_cad if str(nav_ccy).upper() == "USD" else 1.0   # use the SOURCED currency
            # Spot-link the fair value ONLY for silver (the engine's live, correctly-framed spot).
            # gold/uranium/diversified config spot_refs are stale/silver-framed, so a naive ratio
            # would distort — keep them NAV-anchored (neutral factor); their commodity signal lives in
            # the T-pillar tailwind (commodity_regime) and — for a sourced NAV — in the live-marked NAV.
            if commodity == "silver" and spot_ag and spot_ag > 0:
                spot_now = spot_ag
                spot_ref = nm.get("spot_ref", spot_ref_default.get("silver", spot_ag))
            else:
                spot_now = spot_ref = 1.0                     # neutral: fair value = ref × base_mult
            spot_beta = nm.get("spot_beta", 1.0)
            mult = nm.get("base_mult", base_mult)
            fv_native = self.valuation_engine.calculate_ballast_fair_value(
                ref_price, mult, spot_now, spot_ref, spot_beta, forensic_pen
            )
            fv_cad = fv_native * fx  # normalize the name's native-currency fair value into CAD
            ballast_anchors[name] = {"anchor": anchor, "ref_price_native": round(ref_price, 4),
                                     "fair_value_cad": round(fv_cad, 4)}
            return fv_cad

        # Every NON-spear book member is valued as ballast (the spear AGA.V is valued by the spear
        # engine above). Iterating the book keeps membership data-driven and KeyError-proof on a cut.
        ballast_fv = {}
        for _btk in bw:
            if _btk == SPEAR:
                continue
            ballast_fv[_btk] = _ballast_fv(
                _btk, ballast_cfg.get(_btk, _ballast_default_mult.get(_btk, 1.15)),
                _ballast_pen(_btk), _fx_to_cad(_btk, _book_dccy(_btk)),
            )

        ev_blended = (bw.get(SPEAR, 0.0) * aga_intrinsic) + sum(
            bw[_btk] * _fv for _btk, _fv in ballast_fv.items()
        )
        u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

        # Spear-level upside (triangulated intrinsic vs the spear's own CAD price) — used by the
        # directive gates (recalibrated for the de-inflated valuation) and the scenario band.
        spear_upside = (aga_intrinsic / p_aga_cad - 1.0) if p_aga_cad > 0 else 0.0
        if p_aga_cad > 0:
            scenario_range["implied_upside_pct"] = {
                k: round((scenario_range[k] / p_aga_cad - 1.0) * 100, 1) for k in ("bear", "base", "bull")
            }

        # Consolidated, auditable valuation breakdown (Phase 4a) — additive block; the legacy
        # v4_valuation keys remain populated so the cockpit never breaks mid-migration.
        self.terminal_state["valuation_detail"] = {
            "stage": spear_detail["stage"],
            "intrinsic": round(aga_intrinsic, 3),
            "spear_price_cad": round(p_aga_cad, 3),
            "spear_upside_pct": round(spear_upside * 100, 1),
            "legs": spear_detail["legs"],
            "weights": spear_detail["weights"],
            "confidence": spear_detail["confidence"],
            "v_mkt_defined": spear_detail["v_mkt_defined"],
            "v_exploration": spear_detail["v_exploration"],
            "tq_by_project": spear_detail["tq_by_project"],
            "avg_tq": spear_detail["avg_tq"],
            "option_premium": spear_detail["option_premium"],
            "mos_ledger": spear_detail["mos_ledger"],
            "silver_vol": round(silver_vol, 3),
            "scenarios": scenario_range,
            "reconciliation": reconciliation,
            "rep_floor_basis": spear_detail.get("rep_floor_basis"),
            "ballast_anchors": ballast_anchors,   # per-name: sourced NAV vs legacy config snapshot
        }

        # ============== PHASE 5b — ADDITIVE POLYMORPHIC ARCHETYPE VALUATIONS ==============
        # Supplementary, computed in PARALLEL with the legacy valuation_detail above; it never
        # replaces any legacy logic and is isolated so it can never crash the eval loop. Each
        # portfolio name is routed by cash-flow lifecycle and valued through the triangulated
        # archetype factory, FX-normalized to CAD, with the macro-asymmetry overlay driven by
        # the live MRI/yield/vol state. The cockpit may read this block when present, or ignore it.
        try:
            with self.state_lock:
                forensic_metrics = dict(self.state_cache.get("forensic_metrics", {}))
            self.terminal_state["archetype_valuation_detail"] = self._compute_archetype_valuations(
                cfg=cfg, prices=prices, spot_ag=spot_ag, gold=gold, real_yield=real_yield,
                silver_vol=silver_vol, dynamic_aisc=dynamic_aisc,
                capital_discount_factor=capital_discount_factor, mean_peer_ev=mean_peer_ev,
                usd_to_cad=usd_to_cad, mri_score=mri_score, dxy_mom=dxy_mom,
                forensic_metrics=forensic_metrics)
        except Exception as e:
            logging.warning("Phase 5b archetype valuation block skipped (non-fatal): %s", e)
            self.terminal_state["archetype_valuation_detail"] = {"status": "error", "error": str(e), "results": {}}

        # Arch 5: resolve the SHARED regime inputs (real_yield/GSR/uranium_term/dxy_mom from the
        # metrics dict + the tape's tilt) ONCE for this cycle — the conviction block's commodity
        # tailwinds and the posture dial below consume this same snapshot instead of each re-reading
        # terminal_state (regime_lens/inflation_regime already receive their inputs directly above).
        macro_snap = macro_snapshot.snapshot(self.terminal_state)

        # ============== PHASE 7 — CONVICTION MODE (PRIMARY VIEW, ADDITIVE) ==============
        # The 0-10 T-Q-V Asymmetry Rating per basket, assembled from the blocks just computed.
        # Assessment-only: it consumes NO position caps, ES95 throttle, covariance shrinkage, or
        # Kelly de-leveraging (those remain in Detailed Analysis). Isolated; never crashes the loop.
        try:
            with self.state_lock:
                fm_conv = dict(self.state_cache.get("forensic_metrics", {}))
            cad_prices = {tk: px for tk, px in cad_px.items() if _is_pos(px)}
            # The promoted EVAL set rates alongside the book (no weight, no sizing). A name with
            # no live mark yet (feed miss -> 0.0 fallback) is skipped rather than rated at zero.
            pm_all = cfg.get("portfolio_metadata", {})
            for _tk in eval_only_tickers(cfg):
                _pe = prices.get(_tk)
                if _is_pos(_pe):
                    _ccy = str((pm_all.get(_tk) or {}).get("currency", "CAD"))
                    cad_prices[_tk] = float(_pe) * _fx_to_cad(_tk, _ccy)
            self.terminal_state["conviction_mode"] = self._compute_conviction_mode(
                cfg=cfg, cad_prices=cad_prices, mri_score=mri_score,
                net_tilt=self.terminal_state.get("macro_tape", {}).get("net_tilt", "BALANCED"),
                forensic_metrics=fm_conv, macro_signals=macro_snap)
        except Exception as e:
            logging.warning("Phase 7 conviction-mode block skipped (non-fatal): %s", e)
            self.terminal_state["conviction_mode"] = {"status": "error", "error": str(e), "baskets": []}

        # Forge Phase 3: the book-level regime POSTURE (master temperature dial). Composes onto every
        # name's verdict (size cap) and the cockpit's visual temperature — never a name-level signal.
        try:
            self.terminal_state["posture"] = self._regime_posture(mri_score, signals=macro_snap)
        except Exception as e:
            logging.warning("Forge posture block skipped (non-fatal): %s", e)
            self.terminal_state["posture"] = {"code": "balanced", "label": "BALANCED", "cap": 1.0}

        # P4 — standing conditional actions over the live state (after posture is set): the AGA
        # proportional-add gate (3 conditions, hard-capped at the 60% spear ceiling), per-thesis
        # invalidation lines wired to the SENTINEL flags, and dry-powder deployment off the USD/CAD
        # carry tilt. A pure consumer of P2/P3 + posture; entry reads + per-name forensics come from the
        # agents, so the add gate fails closed (HOLD) until an entry is verified. `holdings`/`usdcad_read`
        # are method-locals built upstream this cycle.
        try:
            import conditionals
            self.terminal_state["conditionals"] = conditionals.assess(
                holdings, scenario=self.terminal_state.get("scenario_engine"),
                sentinel=self.terminal_state.get("sentinel_board"),
                posture=self.terminal_state.get("posture"), usdcad=usdcad_read,
                config=self.config)
        except Exception:
            pass
        # P5.1 — per-name thesis-variable monitors: the authoritative watch-list of what each holding's
        # thesis lives or dies on, with a conservative health rollup. The framework is attached as a
        # live surface; the agents / conviction pipeline supply the per-variable reads (price trends,
        # JSF, floor coverage, term price) — until then variables read 'unknown' (a gap, not a pass).
        try:
            import thesis_monitor
            self.terminal_state["thesis_monitors"] = [
                thesis_monitor.assess(h, config=self.config) for h in holdings if h.get("slot")]
        except Exception:
            pass

        # Validation flywheel (Phase 1): stamp the book point-in-time into the append-only
        # valuation ledger. RECORD-only — the ledger never recomputes engine output; the cadence
        # gate inside maybe_record (daily mark + material change) keeps the ~10s loop from
        # flooding the track record. Fenced: a ledger problem can never break the eval cycle.
        try:
            self._record_valuation_ledger(cfg)
        except Exception as e:
            logging.warning("valuation ledger stamp skipped (non-fatal): %s", e)

        # Forge nervous system #1: diff this cycle into SEMANTIC events (posture flip, JSF trip,
        # directive change) -> the desk tape (ephemeral /agent/activity bus), and persist ONLY the
        # signal-worthy ones to Living Memory (the immutable audit record stays clean). Defensive.
        try:
            self._emit_cockpit_events()
        except Exception as e:
            logging.warning("Forge event detection skipped (non-fatal): %s", e)

        # H3 — the calibration FLYWHEEL turn. The capture loop only has torque if decisions FREEZE at
        # the call and CLOSE at the horizon; until now a freeze needed a council to run and a close
        # needed an agent to remember the sweep tool. Turn it on the engine's own always-on heartbeat
        # (throttled): freeze a gradeable decision for every held name that lacks one, and grade open
        # decisions at horizon / on a stance change against the live mark. Defensive; quiet in steady
        # state (a held book with live, same-stance, pre-horizon bets writes nothing).
        try:
            self._turn_calibration_flywheel()
        except Exception as e:
            logging.warning("calibration flywheel turn skipped (non-fatal): %s", e)

        # Phase 6c: surface the open-source ingestion-cache provenance (additive, read-only).
        try:
            self.terminal_state["ingestion"] = self._ingestion_status()
        except Exception as e:
            logging.warning("Phase 6c ingestion status block skipped (non-fatal): %s", e)
            self.terminal_state["ingestion"] = {"available": False, "reason": "error"}

        # 9. PORTFOLIO STATISTICS
        self.terminal_state["portfolio_stats"] = {
            "expected_shortfall_95": round(es_95 * 100, 2),
            "avg_correlation": round(avg_corr, 2),
            "vols": vols,
            "correlations": corr_matrix
        }

        # 10. ACTIVE SIZING CALCULATIONS
        limit_params = {
            "aga_price": p_aga,
            "aga_adv": aga_adv,
            "port_vol": port_vol,
            "vix": vix,
            "jsf_score": forensic_score,
            "expected_shortfall_95_pct": round(es_95 * 100, 2)
        }

        # Catalyst/momentum gate on the Kelly drift: measure the spear's (AGA.V) trailing
        # cumulative return and let it confirm or haircut the intrinsic convergence thesis before
        # sizing. Defaults to no haircut (1.0) when the returns feed is unavailable.
        cat_overlay = cfg.get("v5_guardrails", {}).get("kelly_catalyst_overlay", {})
        overlay_on = cat_overlay.get("enabled", True)
        spear_momentum = None
        if overlay_on and df_rets is not None:
            try:
                if "AGA.V" in getattr(df_rets, "columns", []):
                    lb = int(cat_overlay.get("momentum_lookback_days", 20))
                    spear_rets = df_rets["AGA.V"].dropna().tail(lb)
                    if len(spear_rets) >= 5:
                        spear_momentum = float((1.0 + spear_rets).prod() - 1.0)
            except Exception as e:
                print(f"[!] Catalyst momentum calc error: {e}")
        catalyst_factor = self.sizer.catalyst_confidence(
            spear_momentum,
            floor=cat_overlay.get("confidence_floor", 0.5),
            mom_lo=cat_overlay.get("momentum_lower", -0.10),
            mom_hi=cat_overlay.get("momentum_upper", 0.10),
        ) if overlay_on else 1.0

        sizing_res = self.sizer.calculate_sizing(
            # STRESS axis, not the composite: the regime multiplier is a derisking dial — a bull
            # extension (silver hot, CFTC crowded, macro benign) must stop ADDS (directive gate,
            # composite) but never force-shrink the whole book's target the way credit stress does.
            live_portfolio_value, u_implied, vols, corr_matrix, mri_stress, limit_params,
            catalyst_factor=catalyst_factor
        )

        e_target_capped = sizing_res["e_target"]
        kelly_multiple = sizing_res["kelly_multiple"]          # risk-adjusted target leverage f* (<= L_max)
        allocation_ratio = sizing_res["allocation_ratio"]      # current book vs Kelly target (>1 => over-allocated)
        macro_regime = sizing_res["macro_regime"]
        
        # 11. STRATEGIC DIRECTIVES
        # Recalibrated for the de-inflated (double-count-removed) valuation: the high-conviction gate now
        # reads the SPEAR's own triangulated intrinsic-vs-price upside (robust, intuitive) rather than the
        # structurally-lower blended portfolio edge. JSF >= 3.5 still gates aggressive signals.
        spear_hc = cfg.get("directive_thresholds", {}).get("spear_upside_high_conviction", 0.80)
        # DEPLOY gates on the COMPOSITE (both axes must be benign — don't deploy into credit stress
        # OR into a crowded top); DEFENSIVE gates on the STRESS axis only (a hot-but-benign tape is
        # a stop-adding signal, not a protect-capital signal).
        if mri_score < 40 and spear_upside > spear_hc and forensic_score >= 3.5:
            directive = "HIGH CONVICTION ZONE - DEPLOY CAPITAL"
        elif mri_score < 40 and spear_upside > spear_hc and forensic_score < 3.5:
            directive = "CONVICTION GATED - JSF DEGRADED - SCALE CONSERVATIVELY"
        elif allocation_ratio > cfg.get("v5_guardrails", {}).get("allocation_directive", {}).get("trim_ratio", 2.0):
            directive = "CAUTION - OVER-ALLOCATED - TRIM EXPOSURE"
        elif mri_stress > 65:
            directive = "DEFENSIVE MODE - PROTECT CAPITAL"
        else:
            directive = "HOLD POSITION - MONITOR TAPE"

        self.terminal_state["macro_regime"] = macro_regime
        self.terminal_state["directive"] = directive
        
        # Compute blended catalyst probability from config structural weights
        cat_probs = cfg.get("catalyst_probabilities", {})
        struct_weights = cfg.get("structural_weights", {})
        blended_probability = sum(
            cat_probs.get(k, 0.50) * struct_weights.get(k, 0.0)
            for k in struct_weights
        )
        if sum(struct_weights.values()) > 0:
            blended_probability = blended_probability / sum(struct_weights.values())
        else:
            blended_probability = 0.65

        guard = cfg.get("v5_guardrails", {})
        self.terminal_state["v4_valuation"] = {
            "Total_Equity": round(live_portfolio_value, 2), 
            "E_Target": round(e_target_capped, 2),
            "PPI": round(ppi, 3), 
            "EV_Blended": round(ev_blended, 3), 
            "Implied_Upside": round(u_implied * 100, 2),
            "AGA_Intrinsic": round(aga_intrinsic, 3),
            "REP_Floor": round(spear_detail["legs"]["cost"], 3),   # reconciled cost leg (authoritative; legacy rf_floor kept only for the reconciliation baseline)
            "Cash_Runway_Months": round(cash_runway_months, 1), 
            "Kelly_Multiple": round(kelly_multiple, 2),       # risk-adjusted target leverage f* (bounded [0, L_max])
            "Kelly_Leverage": round(kelly_multiple, 4),       # explicit canonical alias (same value, finer precision)
            "allocation_ratio": round(allocation_ratio, 2),   # book vs Kelly target (>1 => over-allocated); clamped
            "BVS": round(mri_score, 1),
            "MRI": round(mri_score, 1), 
            "IS_IAI_Per_Share": round(is_iai_per_share, 3),
            "Exp_Premium_Per_Share": round(exp_per_share, 3), 
            "ROV": round(rov, 2),
            "Probability": round(blended_probability, 3),
            "Forensic_Penalty": round(forensic_penalty, 3),
            "Discovery_Premium_Factor": round(discovery_premium_factor, 3),
            "Mean_Peer_EV_oz": round(mean_peer_ev, 2),
            "ADV_Cap_CAD": sizing_res["adv_cap_cad"],
            "ADV_Cap_Percentage": sizing_res["cap_percentage"],
            "Discovery_Efficiency_Comps": round(avg_disc_cost, 2),
            "fractional_kelly_multiplier": guard.get("fractional_kelly_multiplier", 0.5),
            "position_liquidity_cap_pct": guard.get("position_liquidity_cap_pct", 0.15),
            "max_single_position_pct": guard.get("max_single_position_pct", 0.20),
            "max_spear_position_pct": guard.get("max_spear_position_pct", 0.60),
            "intrinsic_convergence_months": guard.get("intrinsic_convergence_months", 18.0),
            "ES_Throttle": sizing_res["es_throttle"],
            "usd_to_cad": round(usd_to_cad, 4),
            # Educational waterfall intermediates from the sizing engine
            "raw_kelly_leverage": sizing_res.get("raw_kelly_leverage", 0.0),
            "vix_capped_leverage": sizing_res.get("vix_capped_leverage", 0.0),
            "post_correlation_leverage": sizing_res.get("post_correlation_leverage", 0.0),
            "post_es_leverage": sizing_res.get("post_es_leverage", 0.0),
            "regime_multiplier": sizing_res.get("regime_multiplier", 1.0),
            "catalyst_factor": sizing_res.get("catalyst_factor", 1.0),
            "spear_momentum_pct": round(spear_momentum * 100, 2) if spear_momentum is not None else None,
            # Parameter-uncertainty (uncertainty-adjusted Kelly) + structured waterfall for the cockpit
            "edge_confidence": sizing_res.get("edge_confidence", 1.0),
            "mu_raw": sizing_res.get("mu_raw", 0.0),
            "mu_annualized": sizing_res.get("mu_annualized", 0.0),
            "se_mu": sizing_res.get("se_mu", 0.0),
            "sizing_waterfall": sizing_res.get("waterfall", [])
        }

        # URC.TO node removed 2026-08-02 with its decommission (config-only, never held) — a node
        # for a non-member was the last place the phantom still rendered.
        self.terminal_state["nodes"] = {
            "AGA.V": {"price": round(p_aga, 3), "role": "The Spear", "shares": self.shares.get("AGA", 0.0)},
            "GROY": {"price": round(p_groy, 2), "role": "Ballast", "shares": self.shares.get("GROY", 0.0)},
            "GMX.TO": {"price": round(p_gmx, 2), "role": "Ballast", "shares": self.shares.get("GMX", 0.0)}
        }

        # 11b. CLOSES — the last-60-day close window per book name from the reproducible CAD close
        # store (price_history), published on /state so the web cockpit's sparklines and chg60 ride
        # live data instead of its baked fixture (the fixture froze the sparks at its render date and
        # made chg60 a mixed-vintage number: live price over a stale base). Fenced separately — a
        # store hiccup costs the sparks, never the eval cycle.
        try:
            from datetime import date as _pd_date, timedelta as _pd_td
            from price_history import PriceHistory as _PH
            _hist = _PH()
            _t1 = _pd_date.today()
            _t0 = _t1 - _pd_td(days=60)
            _closes = {}
            for _tk in self.terminal_state["nodes"]:
                _win = _hist.window(_tk, _t0, _t1)
                if len(_win) >= 2:
                    _closes[_tk] = [[_d, round(_c, 4)] for _d, _c in _win]
            self.terminal_state["closes"] = _closes
        except Exception:
            self.terminal_state["closes"] = {}

        # 12. MODEL HEALTH RADAR
        is_stale = (self.terminal_state["status"] == "DEGRADED_STALE")
        es_val = self.terminal_state["portfolio_stats"]["expected_shortfall_95"]
        
        health_res = self.radar.calculate_health_rating(
            # STRESS axis: the macro penalty prices signal RELIABILITY under macro/credit stress —
            # a hot-but-benign metals tape (extension) doesn't make the pipes less trustworthy.
            forensic_score, mri_stress, es_val, is_stale
        )
        
        priority_res = self.radar.generate_priorities(
            self.terminal_state["v4_valuation"], forensic_score, mri_score, es_val, p_aga
        )
        
        health_rating = health_res["health_rating"]
        tactical_ceiling = e_target_capped * (health_rating / 10.0)

        self.terminal_state["health_radar"] = {
            "health_rating": health_rating,
            "rating_desc": health_res["rating_desc"],
            "rating_color": health_res["rating_color"],
            "health_summary": health_res["health_summary"],
            "tactical_ceiling": round(tactical_ceiling, 2),
            "priorities": priority_res
        }

        # --- Consolidated integrity panel (v5.2): one top-level block the cockpit can consume to
        # render model-risk alerts (data staleness + any active forensic waivers) prominently. ---
        df_summary = self.terminal_state.get("data_freshness", {})
        active_overrides = forensic_details.get("overrides_applied", [])
        stale_feeds = [name for name, v in df_summary.get("feeds", {}).items() if v.get("stale")]
        integrity_alerts = []
        if df_summary.get("any_stale"):
            integrity_alerts.append(f"STALE DATA: {', '.join(stale_feeds) or 'feed'} past freshness threshold")
        if df_summary.get("vintage_skew_seconds", 0) > df_summary.get("skew_warn_seconds", 5400):
            integrity_alerts.append(f"VINTAGE SKEW: feeds diverge by {df_summary.get('vintage_skew_seconds', 0)/60:.0f} min")
        for ov in active_overrides:
            integrity_alerts.append(
                f"FORENSIC WAIVER ACTIVE on AGA.V {ov.get('test', '').upper()} "
                f"(expires in {ov.get('days_until_expiry', '?')}d — confirm before relying on JSF)"
            )
        self.terminal_state["integrity"] = {
            "status": self.terminal_state.get("status", "LIVE"),
            "any_stale": bool(df_summary.get("any_stale", False)),
            "stale_feeds": stale_feeds,
            "stale_feed_count": df_summary.get("stale_feed_count", 0),
            "vintage_skew_seconds": df_summary.get("vintage_skew_seconds", 0),
            "forensic_overrides_active": active_overrides,
            "forensic_override_count": len(active_overrides),
            "requires_confirmation": any(o.get("requires_confirmation") for o in active_overrides),
            "alerts": integrity_alerts,
            "all_clear": (not integrity_alerts)
        }
        if integrity_alerts:
            print("─"*75)
            for a in integrity_alerts:
                print(f" [INTEGRITY] ⚠ {a}")

        # Terminal Print
        print("\n" + "═"*75)
        print(f" COMMODITYEX MONITOR v5.1 // CORE ENGINE LOG // {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("═"*75)
        print(f" [MACRO]    MRI: {mri_score:.1f} | REGIME: {macro_regime.upper()} ")
        print(f"            DXY Mom: {dxy_mom:+.2f}% | Expected Shortfall (95%): {es_val:.2f}% ")
        print(f"            DIRECTIVE: {directive}")
        print("─"*75)
        print(f" [RADAR]    Health Rating: {health_res['health_rating']:.1f}/10.0 ({health_res['rating_desc']})")
        for p in priority_res[:2]:
            print(f"            * {p['title']}: {p['desc'][:60]}...")
        print("─"*75)
        print(f" [SYNTHESIS] Equity Value: ${live_portfolio_value:,.2f} CAD")
        print(f"            Target Capital: ${e_target_capped:,.2f} CAD | ADV Sizing Cap: ${sizing_res['adv_cap_cad']:,.2f} CAD ({sizing_res['cap_percentage']:.1f}%)")
        print(f"            Kelly Leverage f*: {kelly_multiple:.3f}x | Alloc vs Target: {allocation_ratio:.2f}x | Implied Edge: {u_implied*100:.1f}%")
        print(f"            REP Floor:      ${spear_detail['legs']['cost']:.3f} | Cash Runway:  {cash_runway_months:.1f} mo")
        print("═"*75 + "\n")

        # A1.9: the eval cycle's writes are complete — publish one atomic frame for every reader.
        self.publish_state()

    async def _run_loop(self):
        while True:
            try:
                # evaluate_master_architecture() rebuilds self.config (file defaults + confirmed
                # overrides) at the top of every cycle via _refresh_effective_config(), so the prior
                # explicit hot-reload here is now redundant.
                await self.evaluate_master_architecture()
            except Exception as e:
                print(f"\n[!] Engine Loop Error: {e}")
            await asyncio.sleep(10)


# ====================== FASTAPI SETUP ======================
# The FastAPI app + routes (and the `engine = CommodityExMonitor()` singleton) moved to
# engine_api.py (mechanical, Arch 2 split). `python engine.py` launches the identical server
# below; `engine.app` / `uvicorn engine:app` still resolve — lazily, to the same single app.


def __getattr__(name):  # PEP 562 — lazy back-compat re-exports (avoids a circular import)
    if name in ("app", "engine", "active_websockets", "websocket_broadcaster", "lifespan",
                "_write_source_ok"):
        import engine_api
        return getattr(engine_api, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    from engine_api import app
    # access_log off + warning level: the ENGINE pane shows the capital/risk summary the loop
    # prints, not a wall of "GET /state 200 OK" — the cockpit polls several times a second.
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False, log_level="warning")
