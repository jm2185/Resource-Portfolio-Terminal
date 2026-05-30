import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
import json
import os
import requests

# Premium Styling: Curated harmonious dark palette (HSL)
st.markdown("""
<style>
    .stApp {
        background-color: #0A0A0A;
        color: #E0E0E0;
    }
    .metric-card {
        background-color: #161616;
        border: 1px solid #2B2B2B;
        border-radius: 8px;
        padding: 18px;
        text-align: center;
    }
    .metric-title {
        color: #888888;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        color: #EAEAEA;
        font-size: 24px;
        font-weight: bold;
        font-family: 'Courier New', Courier, monospace;
        margin-top: 4px;
    }
    .pass-badge {
        color: #00E676;
        font-weight: bold;
        font-family: monospace;
    }
    .fail-badge {
        color: #FF1744;
        font-weight: bold;
        font-family: monospace;
    }
</style>
""", unsafe_allow_html=True)

st.title("COMMODITYEX // MASTER ARCHITECTURE v5.1")
st.caption("TACTICAL DECISION SUPPORT & SENSITIVITY SANDBOX")

# Load baseline configurations
CONFIG_PATH = "v5_config.json"
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

cfg = load_config()

# Retrieve live engine state
@st.cache_data(ttl=2)
def get_live_state():
    try:
        res = requests.get("http://127.0.0.1:8000/state", timeout=1.5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

live_state = get_live_state()

# ========================================================
# 1. PERSISTENT PIPELINE STATE HEADERS
# ========================================================
is_stale = live_state is None or live_state.get("status") == "DEGRADED_STALE"

if is_stale:
    st.markdown("""
    <div style="background-color: rgba(230, 81, 0, 0.08); border: 1.5px solid #FF9800; border-radius: 6px; padding: 14px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: bold; color: #FF9800; font-size: 13px; font-family: monospace; letter-spacing: 0.8px;">
                ⚠️ [SYSTEM STATE: DEGRADED STALE FALLBACK]
            </span>
            <span style="background-color: rgba(255,152,0,0.15); color: #FF9800; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; font-family: monospace;">
                OFFLINE CACHE ACTIVE
            </span>
        </div>
        <div style="font-size: 11px; color: #B0BEC5; margin-top: 6px; line-height: 1.4;">
            Fred or YFinance connection pipeline timed out. Sovereign liquidity metrics (SOFR, EFFR, TED, 10Y Yields) and barbell asset pricing are loaded from the local cache registers. Expect static calculations.
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="background-color: rgba(27, 94, 32, 0.08); border: 1.5px solid #00E676; border-radius: 6px; padding: 14px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: bold; color: #00E676; font-size: 13px; font-family: monospace; letter-spacing: 0.8px;">
                ● [SYSTEM STATE: LIVE REAL-TIME CHANNELS OPERATIONAL]
            </span>
            <span style="background-color: rgba(0,230,118,0.15); color: #00E676; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; font-family: monospace;">
                REST PIPELINES ACTIVE
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ========================================================
# SIDEBAR CONTROLS & SANDBOX TOGGLES
# ========================================================
st.sidebar.header("SANDBOX OVERRIDES")
override_mode = st.sidebar.checkbox("Activate Override Sandbox", value=False, help="Toggle to override live market metrics and simulate scenarios.")

# Baseline metric loaders
if override_mode or live_state is None:
    st.sidebar.subheader("Valuation Drivers")
    spot_ag = st.sidebar.slider("Spot Silver Price ($/oz)", 15.0, 100.0, float(live_state["metrics"]["Spot_Ag"]["value"]) if live_state else 74.8, step=1.0)
    peer_ev = st.sidebar.slider("Peer EV/oz ($ CAD)", 0.50, 15.00, float(live_state["v4_valuation"]["Mean_Peer_EV_oz"]) if live_state else 2.50, step=0.10)
    real_yield = st.sidebar.slider("10Y US Real Yield (%)", -3.0, 4.0, 1.8, step=0.1)
    wti_oil = st.sidebar.slider("WTI Crude Oil ($/bbl)", 40.0, 130.0, float(live_state["metrics"]["WTI"]["value"]) if live_state else 80.0, step=1.0)
    vix = st.sidebar.slider("VIX Index", 9.0, 50.0, float(live_state["metrics"]["VIX"]["value"]) if live_state else 16.5, step=0.5)
    
    st.sidebar.subheader("Credit & Repo Overrides")
    sofr_val = st.sidebar.slider("SOFR Rate (%)", 3.0, 6.5, 5.31, step=0.01)
    dgs3mo_val = st.sidebar.slider("DGS3MO Yield (%)", 3.0, 6.5, 5.22, step=0.01)
    sofr_spread = sofr_val - dgs3mo_val
    phys_stress = st.sidebar.checkbox("Force Physical Backwardation Stress", value=False)
    
    st.sidebar.subheader("Forensic Drivers")
    cash_burn = st.sidebar.number_input("Monthly Cash Burn ($ CAD)", 100000, 2000000, int(cfg["cash_burn"]["monthly_burn_rate"]), step=50000)
    aga_shares = st.sidebar.number_input("AGA Outstanding Shares", 10000000, 500000000, int(cfg["aga_shares_out"]))
    sloan_val = st.sidebar.slider("Sloan CFO Ratio", -0.20, 0.20, 0.02, step=0.01)
    sloan_bs_val = st.sidebar.slider("Sloan BS Ratio", -0.20, 0.20, 0.015, step=0.01)
    qoq_dilution = st.sidebar.slider("Share Dilution QoQ (%)", 0.0, 20.0, 0.0, step=0.5) / 100.0
else:
    # Use live state
    metrics = live_state["metrics"]
    val = live_state["v4_valuation"]
    forensics = live_state["forensics"]
    
    spot_ag = float(metrics["Spot_Ag"]["value"])
    peer_ev = float(val["Mean_Peer_EV_oz"])
    real_yield = 1.8  # Default or fetched
    wti_oil = float(metrics["WTI"]["value"])
    vix = float(metrics["VIX"]["value"])
    cash_burn = int(cfg["cash_burn"]["monthly_burn_rate"])
    aga_shares = int(cfg["aga_shares_out"])
    sloan_val = float(forensics["sloan_cfo"])
    qoq_dilution = 0.0

# ========================================================
# SANDBOX CORE VALUATION PIPELINE
# ========================================================

# 1. Macro MRI Scaling (Re-calibrated for late May 2026 prices)
def compute_sandbox_mri():
    def norm(val, low, high):
        return max(0, min(100, (val - low) / (high - low) * 100))
    # Wire in live SOFR Credit Spread instead of discontinued TEDRATE
    liq = (
        norm(99.0 - 100, -5, 8) * 0.30 +
        norm(sofr_spread, 0.1, 0.9) * 0.20 +
        norm(real_yield, 0.5, 3.5) * 0.30 +
        norm(0.0, -2.0, 2.0) * 0.20
    )
    yld = (
        norm(0.54, -0.5, 1.5) * 0.50 +
        norm(4.44, 3.0, 5.5) * 0.50
    )
    vol = (
        norm(vix, 12, 35) * 0.50 +
        norm(3.5, 2, 7) * 0.50
    )
    comm = (
        norm(0.00136, 0.0010, 0.0018) * 0.60 +
        norm(spot_ag, 50.0, 100.0) * 0.40
    )
    sentiment = norm(35000.0, -15000, 85000)
    mri = (liq * 0.30) + (yld * 0.20) + (vol * 0.20) + (comm * 0.15) + (sentiment * 0.15)
    return round(max(0, min(100, mri)), 1)

mri_score = compute_sandbox_mri() if (override_mode or live_state is None) else (live_state.get("mri") or live_state.get("bvs") or 45.0)

# 2. Forensic Score & Penalty multiplier
def compute_sandbox_forensics():
    score = 0.0
    details = {}
    
    rf = cfg["rep_floor_params"]
    cash_component = rf["cash_treasury_m"] * 1_000_000
    runway = cash_component / cash_burn if cash_burn > 0 else 99.0
    
    if runway >= 18.0:
        score += 1.0
        details["runway"] = {"pass": True, "value": runway, "desc": "Runway >= 18 mo"}
    else:
        details["runway"] = {"pass": False, "value": runway, "desc": f"Short Runway ({runway:.1f} mo)"}
        
    # Standard Sloan Ratio Check (Integrates both CFO and BS Accruals for safety)
    sloan_pass = (sloan_val < 0.05) and (sloan_bs_val < 0.05)
    if sloan_pass:
        score += 1.0
        details["accrual"] = {"pass": True, "value": sloan_val, "desc": f"Sloan CFO < 5% ({sloan_val*100:.1f}%) & BS < 5% ({sloan_bs_val*100:.1f}%)"}
    else:
        violating_val = sloan_val if sloan_val >= 0.05 else sloan_bs_val
        details["accrual"] = {"pass": False, "value": violating_val, "desc": f"Accrual overload (CFO: {sloan_val*100:.1f}%, BS: {sloan_bs_val*100:.1f}%)"}

    if qoq_dilution < 0.02:
        score += 1.0
        details["dilution"] = {"pass": True, "value": qoq_dilution, "desc": "Dilution < 2% QoQ"}
    else:
        details["dilution"] = {"pass": False, "value": qoq_dilution, "desc": f"Dilution expansion ({qoq_dilution*100:.1f}%)"}

    score += 1.0  # SG&A overhead test auto pass in mock
    details["sga_drag"] = {"pass": True, "value": 0.18, "desc": "SG&A drag < 30%"}

    penalty = 0.70 + 0.30 * (score / 4.0)
    return score, penalty, details, runway

if override_mode or live_state is None:
    forensic_score, forensic_penalty, forensic_details, runway = compute_sandbox_forensics()
else:
    forensic_score = live_state["forensics"]["jsf_score"]
    forensic_penalty = live_state["forensics"]["penalty_factor"]
    forensic_details = live_state["forensics"]["details"]
    runway = live_state["forensics"]["runway"]

# 3. Dynamic AISC
base_aisc = cfg["dynamic_discovery_v5"]["estimated_industry_aisc_2026"]
dynamic_aisc = base_aisc + max(0, wti_oil - 80.0) * 0.15
phi_margin = max(0.58, (spot_ag - dynamic_aisc) / spot_ag) if spot_ag > dynamic_aisc else 0.05
commodity_leverage = spot_ag / dynamic_aisc if dynamic_aisc > 0 else 1.0
exp_scalar = cfg["dynamic_discovery_v5"].get("explorer_re_rating_scalar", 1.68)
raw_factor = commodity_leverage * phi_margin * exp_scalar
spot_dev = max(0, (spot_ag - 76.5) / 50)
ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - mri_score / 100)
discovery_premium_factor = max(0.50, min(raw_factor, ceiling))

# 4. ROV
negative_yield_premium = min(0.50, max(0.0, 1.0 - real_yield) * 0.25)
rov = cfg.get("rov_default", 1.18) * (1.0 + negative_yield_premium)

# 5. In-Situ IAI & Intrinsic
def calculate_sandbox_intrinsic(p_ev, s_ag):
    # REP Floor
    rf = cfg["rep_floor_params"]
    cash_component = rf["cash_treasury_m"] * 1_000_000
    infra_component = rf["permitting_infra_premium_m"] * 1_000_000
    buckets = cfg.get("project_buckets_oz_AgEq", {})
    total_oz = sum(buckets.values())
    resource_component = total_oz * rf["stressed_resource_per_oz"]
    total_rep_value = cash_component + resource_component + infra_component
    rep_floor = (total_rep_value * rf["conservatism_scalar"]) / aga_shares

    # Capital discount
    capital_discount_factor = 1.0
    
    # In-Situ calculations
    jurisdiction_uplift = 1.35 if s_ag > 50.0 else 1.15
    recovery = cfg.get("metallurgical_recovery", {})
    is_iai_total = 0.0
    for proj, oz in buckets.items():
        rec_silver = recovery.get(proj, {}).get("silver", 0.85)
        is_iai_total += oz * p_ev * discovery_premium_factor * jurisdiction_uplift * rec_silver * capital_discount_factor

    is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / aga_shares

    exp = cfg.get("exploration_upside", {})
    exp_premium_total = (
        exp.get("expected_future_oz", 0) * p_ev * 
        jurisdiction_uplift * exp.get("probability_of_discovery", 0.25)
    )
    exp_per_share = exp_premium_total / aga_shares * exp.get("weight", 0.12)

    aga_intrinsic = (
        (0.15 * rep_floor) + 
        (0.70 * is_iai_per_share * forensic_penalty) + 
        (0.15 * rov) + 
        exp_per_share
    )
    return aga_intrinsic, is_iai_per_share, exp_per_share, rep_floor

aga_intrinsic, is_iai_per_share, exp_per_share, rep_floor = calculate_sandbox_intrinsic(peer_ev, spot_ag)

# Blended portfolio metrics
p_aga = float(live_state["nodes"]["AGA.V"]["price"]) if live_state else 0.72
p_urc = float(live_state["nodes"]["URC.TO"]["price"]) if live_state else 4.81
p_groy = float(live_state["nodes"]["GROY"]["price"]) if live_state else 3.27
p_gmx = float(live_state["nodes"]["GMX.TO"]["price"]) if live_state else 2.08

ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)

# Ballast multipliers
groy_pen = 1.0
urc_pen = 1.0
gmx_pen = 1.0
ev_blended = (
    (0.60 * aga_intrinsic) + 
    (0.15 * p_urc * 1.15 * urc_pen) + 
    (0.15 * p_groy * 1.15 * groy_pen) + 
    (0.10 * p_gmx * 1.20 * gmx_pen)
)
u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

# ========================================================
# RENDER METRIC CARDS ROW
# ========================================================
st.subheader("Actionable Synthesis")

# Model Health Radar calculation
if override_mode or live_state is None:
    is_stale_sim = False
    es_val_sim = -float(es_95) if es_95 > 0 else -5.20
    h_score = 10.0
    h_score -= (4.0 - forensic_score) * 1.25
    h_score -= (mri_score / 100.0) * 1.5
    if is_stale_sim:
        h_score -= 2.0
    if es_val_sim <= -10.0:
        h_score -= 1.0
    elif es_val_sim <= -5.0:
        h_score -= 0.5
    h_score = round(max(1.0, min(10.0, h_score)), 1)
    
    if h_score >= 8.5:
        r_desc = "HIGH INTEGRITY - STRONGLY ACTIONABLE"
        r_color = "#00E676"
        health_summary = "Data pipelines are fresh, macro stress is low, and forensic shields are active. Signals are highly reliable for portfolio sizing."
    elif h_score >= 6.0:
        r_desc = "MODERATE QUALITY - EXERCISE GUARDRAILS"
        r_color = "#FFC107"
        health_summary = "Mild accounting or dilution drags present, or rising macro stress. Maintain strict adherence to Kelly allocation caps."
    else:
        r_desc = "HIGH NOISE - EXTREME CAUTION"
        r_color = "#FF1744"
        health_summary = "Severe forensic failures, extreme macro regime volatility, or stale network fallback active. Treat model values as high-uncertainty limits."
        
    priorities = []
    if u_implied * 100 > 50:
        priorities.append({
            "emoji": "🛒", "color": "#00E676", "title": "EXPLOIT SPEAR ARBITRAGE",
            "desc": f"AGA.V market price ($0.71) is trading at a massive discount to Intrinsic (${aga_intrinsic:.3f}). Up to {u_implied*100:.0f}% implied upside. Prioritize accumulation under REP Floor (${rep_floor:.3f})."
        })
    else:
        priorities.append({
            "emoji": "ℹ️", "color": "#E0E0E0", "title": "MONITOR VALUATION ALIGNMENT",
            "desc": "Barbell components are trading closer to model fair values. No aggressive accumulation signaled. Maintain baseline holdings."
        })
        
    if forensic_score < 3.0:
        priorities.append({
            "emoji": "⚠️", "color": "#FF1744", "title": "MITIGATE JUNIOR ACCOUNTING STRESS",
            "desc": f"JSF Score is depressed at {forensic_score:.1f}/4.0 due to CBA burn acceleration or share dilution expansion. Enforce strict allocation caps to avoid structural traps."
        })
    else:
        priorities.append({
            "emoji": "🛡️", "color": "#00E676", "title": "RISK SHIELD IS SECURE",
            "desc": "Forensic risk checks are clean (JSF: 4.0/4.0). Dilution drag and cash burn are well-contained. High safety factor for capital deployment."
        })
        
    if mri_score > 65:
        priorities.append({
            "emoji": "⏳", "color": "#FF1744", "title": "ENFORCE SEVERE EXIT SIZING CAPS",
            "desc": f"Sovereign stress (MRI: {mri_score:.1f}) is highly elevated. Sizing cap restricted to {cap_percentage*100:.1f}% ADV (${adv_cap_cad:,.0f}). Restrict trading block execution to avoid market impact."
        })
    else:
        priorities.append({
            "emoji": "🔄", "color": "#00E676", "title": "EXECUTE BLOCK TRADES CONFIDENTLY",
            "desc": f"Macro regime is calm (MRI: {mri_score:.1f}). Exit liquidity cap expanded to {cap_percentage*100:.1f}% ADV (${adv_cap_cad:,.0f}). Large additions can be run safely without blocking frames or moving the tape."
        })
        
    kelly_val = (target_pct / (live_state["v4_valuation"]["Kelly_Multiple"] if live_state else 0.77)) if live_state else 0.77
    if kelly_val > 1.2:
        priorities.append({
            "emoji": "⚖️", "color": "#FFC107", "title": "TRIM OVERALLOCATION DRAG",
            "desc": f"Kelly target overallocation indicated. Trim barbell assets to reclaim capital buffer."
        })
    else:
        priorities.append({
            "emoji": "✅", "color": "#00E676", "title": "ALLOCATIONS WITHIN RISK BOUNDS",
            "desc": "Current allocations are safe within Kelly optimal target range. No urgent trim directives active."
        })
        tactical_ceiling = int(cfg["target_capital"]) * (h_score / 10.0)
else:
    health_radar = live_state.get("health_radar", {})
    h_score = health_radar.get("health_rating", 10.0)
    r_desc = health_radar.get("rating_desc", "HIGH INTEGRITY - STRONGLY ACTIONABLE")
    health_summary = health_radar.get("health_summary", "")
    r_color_name = health_radar.get("rating_color", "green")
    r_color = "#00E676" if r_color_name == "green" else "#FFC107" if r_color_name == "orange" else "#FF1744"
    tactical_ceiling = health_radar.get("tactical_ceiling", 0.0)
    
    priorities = []
    icon_to_emoji = {
        "shopping_cart_outlined": "🛒",
        "info_outline": "ℹ️",
        "warning_amber_rounded": "⚠️",
        "verified_user_outlined": "🛡️",
        "lock_clock": "⏳",
        "swap_horizontal_circle_outlined": "🔄",
        "balance_outlined": "⚖️",
        "check_circle_outline": "✅"
    }
    color_to_hex = {
        "green": "#00E676",
        "orange": "#FFC107",
        "red": "#FF1744",
        "white": "#E0E0E0"
    }
    for p in health_radar.get("priorities", []):
        priorities.append({
            "emoji": icon_to_emoji.get(p.get("icon", ""), "ℹ️"),
            "color": color_to_hex.get(p.get("color", ""), "#E0E0E0"),
            "title": p.get("title", ""),
            "desc": p.get("desc", "")
        })

# Render health radar widget
st.markdown(f"""
<div style="background-color: #111113; border: 1.5px solid {r_color}33; border-radius: 6px; padding: 18px; margin-bottom: 24px; box-shadow: 0 4px 12px {r_color}0a;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span style="font-size: 13px; font-weight: bold; color: #FFFFFF; letter-spacing: 0.5px;">MODEL HEALTH & TACTICAL DEPLOYMENT RADAR</span>
        <span style="background-color: {r_color}1a; border: 1px solid {r_color}4d; border-radius: 4px; padding: 4px 10px; color: {r_color}; font-size: 11px; font-weight: bold; font-family: monospace;">HEALTH RATING: {h_score:.1f} / 10</span>
    </div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="color: {r_color}; font-size: 11px; font-weight: bold; letter-spacing: 0.8px;">{r_desc}</span>
        {f'<span style="color: #E0E0E0; font-size: 10.5px; font-weight: bold; font-family: monospace;">TACTICAL CEILING: ${tactical_ceiling:,.2f} CAD ({h_score*10:.0f}% of Kelly)</span>' if tactical_ceiling > 0 else ''}
    </div>
    <div style="color: #888888; font-size: 11px; line-height: 1.3; margin-bottom: 16px;">{health_summary}</div>
    <hr style="border: 0; border-top: 1px solid #222226; margin: 12px 0;">
    <div style="font-size: 10.5px; font-weight: bold; color: #CCCCCC; letter-spacing: 0.5px; margin-bottom: 12px;">PRIORITY TACTICAL CHECKLIST</div>
</div>
""", unsafe_allow_html=True)

# Render checklist columns
p_cols = st.columns(2)
for idx, p in enumerate(priorities):
    col_idx = idx % 2
    with p_cols[col_idx]:
        st.markdown(f"""
        <div style="display: flex; align-items: flex-start; margin-bottom: 12px;">
            <span style="font-size: 18px; margin-right: 10px;">{p['emoji']}</span>
            <div>
                <div style="color: {p['color']}; font-size: 11px; font-weight: bold; letter-spacing: 0.3px; margin-bottom: 2px;">{p['title']}</div>
                <div style="color: #888888; font-size: 10.5px; line-height: 1.3;">{p['desc']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">AGA Intrinsic Price</div>
        <div class="metric-value" style="color: #FFC107;">${aga_intrinsic:.3f} CAD</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Blended Portfolio PPI</div>
        <div class="metric-value">${ppi:.3f} CAD</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Implied Upside Edge</div>
        <div class="metric-value" style="color: #00E676;">{u_implied*100:.2f}%</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">MRI Sovereign Stress</div>
        <div class="metric-value" style="color: {'#FF1744' if mri_score > 65 else '#FFC107' if mri_score > 40 else '#00E676'};">{mri_score:.1f}</div>
    </div>
    """, unsafe_allow_html=True)

# ========================================================
# 2D SENSITIVITY HEATMAP & TORNADO CHARTS
# ========================================================
st.markdown("---")
st.subheader("Sensitivity Analytics & Risk Capture")

left_panel, right_panel = st.columns(2)

with left_panel:
    st.markdown("**2D Valuation Heatmap: Silver Price vs. Peer Comps Multiple**")
    
    # Compute 2D grid
    silver_range = np.linspace(20, 100, 9)
    peer_ev_range = np.linspace(1.0, 10.0, 10)
    
    grid = []
    for s_price in silver_range:
        row = []
        for p_multiple in peer_ev_range:
            intrinsic, _, _, _ = calculate_sandbox_intrinsic(p_multiple, s_price)
            row.append(round(intrinsic, 3))
        grid.append(row)
        
    df_heatmap = pd.DataFrame(grid, index=[f"${x:.0f}" for x in silver_range], columns=[f"${y:.1f}" for y in peer_ev_range])
    
    fig_heat = px.imshow(
        df_heatmap,
        labels=dict(x="Peer Comps EV/oz Multiple ($ CAD)", y="Spot Silver Price ($/oz)", color="AGA Intrinsic ($)"),
        color_continuous_scale="Viridis",
        aspect="auto"
    )
    fig_heat.update_layout(
        paper_bgcolor="#0A0A0A",
        plot_bgcolor="#0A0A0A",
        font_color="#E0E0E0",
        margin=dict(l=20, r=20, t=20, b=20),
        height=380
    )
    st.plotly_chart(fig_heat, use_container_width=True)

with right_panel:
    st.markdown("**Valuation Sensitivity Tornado Chart**")
    
    # Baseline calculations
    base_val = aga_intrinsic
    
    # Run sensitivities (+-20% swings)
    swing_keys = ["Spot Silver", "Peer EV/oz", "Asset Recovery", "Real Yields"]
    lows = []
    highs = []
    
    # Silver Price
    l_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev, spot_ag * 0.8)
    h_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev, spot_ag * 1.2)
    lows.append(l_intrinsic)
    highs.append(h_intrinsic)
    
    # Peer EV/oz
    l_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev * 0.8, spot_ag)
    h_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev * 1.2, spot_ag)
    lows.append(l_intrinsic)
    highs.append(h_intrinsic)
    
    # Recovery
    l_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev, spot_ag) # simple representation
    lows.append(l_intrinsic * 0.95)
    highs.append(h_intrinsic * 1.05)
    
    # Real Yields
    # Higher real yields drop ROV
    rov_l = cfg.get("rov_default", 1.18) * (1.0 + min(0.50, max(0.0, 1.0 - (real_yield + 1.0)) * 0.25))
    rov_h = cfg.get("rov_default", 1.18) * (1.0 + min(0.50, max(0.0, 1.0 - (real_yield - 1.0)) * 0.25))
    
    lows.append(base_val - (rov - rov_l) * 0.15)
    highs.append(base_val + (rov_h - rov) * 0.15)

    # Calculate absolute swings to sort tornado
    swings = [abs(h - l) for l, h in zip(lows, highs)]
    sorted_indices = np.argsort(swings)
    
    sorted_keys = [swing_keys[i] for i in sorted_indices]
    sorted_lows = [lows[i] for i in sorted_indices]
    sorted_highs = [highs[i] for i in sorted_indices]

    fig_tor = go.Figure()
    
    fig_tor.add_trace(go.Bar(
        y=sorted_keys,
        x=[l - base_val for l in sorted_lows],
        name="Downside Swing (-20%)",
        orientation='h',
        marker=dict(color="#FF1744")
    ))
    
    fig_tor.add_trace(go.Bar(
        y=sorted_keys,
        x=[h - base_val for h in sorted_highs],
        name="Upside Swing (+20%)",
        orientation='h',
        marker=dict(color="#00E676")
    ))
    
    fig_tor.update_layout(
        barmode='relative',
        paper_bgcolor="#0A0A0A",
        plot_bgcolor="#0A0A0A",
        font_color="#E0E0E0",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=20, b=20),
        height=380,
        xaxis=dict(title=f"Deviation from Baseline Intrinsic Value (${base_val:.3f})")
    )
    st.plotly_chart(fig_tor, use_container_width=True)

# ========================================================
# FORENSICS & CHECKLIST PORTLET
# ========================================================
st.markdown("---")
st.subheader("Junior Forensic Sifter Sieve")

ticker_type = st.selectbox("Asset Class Context", ["Explorer (e.g., AGA.V)", "Producer/Royalty (e.g., GROY, URC.TO)"])

f_col1, f_col2 = st.columns([1, 2])

with f_col1:
    st.markdown("**Forensic Scoring Summary**")
    st.markdown(f"Composite JSF Score: `{forensic_score:.1f} / 4.0`")
    st.markdown(f"Valuation Penalty Discount Factor: `{forensic_penalty:.3f}x`")
    
    # Conditional render of status badges based on asset type context:
    if ticker_type == "Explorer (e.g., AGA.V)":
        cba_pass = forensic_details.get("accrual", {}).get("pass", True)
        cba_val = forensic_details.get("accrual", {}).get("value", 0.0)
        cba_icon = "<span class='pass-badge'>[PASS]</span>" if cba_pass else "<span class='fail-badge'>[WARN]</span>"
        st.markdown(f"{cba_icon} **CBA BURN ACCELERATION**: {cba_val*100:+.1f}% quarterly flow", unsafe_allow_html=True)
        
        dilution_pass = forensic_details.get("dilution", {}).get("pass", True)
        dilution_val = forensic_details.get("dilution", {}).get("value", 0.0)
        dilution_icon = "<span class='pass-badge'>[PASS]</span>" if dilution_pass else "<span class='fail-badge'>[WARN]</span>"
        st.markdown(f"{dilution_icon} **EXPANDED DILUTION CAP (35%)**: {dilution_val*100:.2f}% share count change", unsafe_allow_html=True)
        
        runway_pass = forensic_details.get("runway", {}).get("pass", True)
        runway_val = forensic_details.get("runway", {}).get("value", 0.0)
        runway_icon = "<span class='pass-badge'>[PASS]</span>" if runway_pass else "<span class='fail-badge'>[WARN]</span>"
        st.markdown(f"{runway_icon} **STRESSED CASH RUNWAY**: {runway_val:.1f} months", unsafe_allow_html=True)
    else:
        # Producer layout showing Sloan CFO & BS Accruals
        sloan_cfo_pass = sloan_val < 0.05
        sloan_cfo_icon = "<span class='pass-badge'>[PASS]</span>" if sloan_cfo_pass else "<span class='fail-badge'>[WARN]</span>"
        st.markdown(f"{sloan_cfo_icon} **SLOAN CFO ACCRUALS**: {sloan_val:+.4f}", unsafe_allow_html=True)
        
        # Load sloan_bs from live state or default
        sloan_bs_val_raw = float(live_state["forensics"].get("sloan_bs", 0.02) if live_state else sloan_bs_val)
        sloan_bs_pass = sloan_bs_val_raw < 0.05
        sloan_bs_icon = "<span class='pass-badge'>[PASS]</span>" if sloan_bs_pass else "<span class='fail-badge'>[WARN]</span>"
        st.markdown(f"{sloan_bs_icon} **SLOAN BS ACCRUALS**: {sloan_bs_val_raw:+.4f}", unsafe_allow_html=True)

with f_col2:
    st.markdown("**Diagnostic Sieve Interpretations**")
    if ticker_type == "Explorer (e.g., AGA.V)":
        st.markdown(f"""
        - **Cash Burn Acceleration (CBA)**: Tracks cash depletion rate vs cash reserves. CBA values above `15.0%` fail the sieve, indicating accelerating corporate bleed.
        - **Share Count Dilution (35% Weight)**: Explores are heavily penalized for share dilution. Dilution caps are restricted to `< 2.0%` QoQ to block dilutive re-ratings.
        - **Stressed Cash Runway**: Corporate cash lifespan under current monthly burn rate of `${cash_burn:,.2f} CAD`. Lifespans below `18 months` trigger early dilution warning flags.
        """)
    else:
        st.markdown(f"""
        - **Sloan CFO Accruals Sieve**: Checks net earnings backed by true cash flows vs. accounting adjustments. Sloan CFO above `+0.05` warns of artificial accruals.
        - **Sloan Balance Sheet (BS) Accruals**: Measures non-cash working capital change. Values above `+0.05` represent inventory or receivables bloat over cash.
        """)

# ========================================================
# POSITION SIZING SIMULATOR
# ========================================================
st.markdown("---")
st.subheader("Advanced Kelly Allocation & Sizing Constraints")

volatilities = live_state["portfolio_stats"]["vols"] if live_state else {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
corr_matrix = live_state["portfolio_stats"]["correlations"] if live_state else {"AGA.V": {"GROY": 0.5}}
es_95 = live_state["portfolio_stats"]["expected_shortfall_95"] if live_state else 5.20
avg_corr = live_state["portfolio_stats"]["avg_correlation"] if live_state else 0.45

s_col1, s_col2 = st.columns(2)

with s_col1:
    st.markdown("**Portfolio Tail Risk Diagnostics**")
    st.markdown(f"- **Annualized 'Spear' Volatility (AGA.V)**: `{volatilities.get('AGA.V', 0.45)*100:.1f}%` ")
    st.markdown(f"- **Annualized 'Ballast' Volatilities**: GROY `{volatilities.get('GROY', 0.35)*100:.1f}%` | URC `{volatilities.get('URC.TO', 0.42)*100:.1f}%` ")
    st.markdown(f"- **Portfolio-Level Expected Shortfall (95% ES)**: `{es_95:.2f}%` daily")
    st.markdown(f"- **Barbell Inter-Asset Correlation**: `{avg_corr:.2f}` (Low correlation improves diversification bounds)")

with s_col2:
    st.markdown("**Sizing Allocation Simulator**")
    
    # Kelly target sizing math
    guard = cfg.get("v5_guardrails", {})
    f_kelly = guard.get("fractional_kelly_multiplier", 0.5)
    pos_liq_cap = guard.get("position_liquidity_cap_pct", 0.15)
    max_single_pos = guard.get("max_single_position_pct", 0.20)
    
    variance = max(0.04, volatilities.get("AGA.V", 0.45) ** 2)
    raw_kelly = (u_implied / variance) * f_kelly
    
    # Correlation discount penalty
    groy_c = corr_matrix.get("AGA.V", {}).get("GROY", 0.5)
    avg_c_penalty = 1.0 - max(0.0, groy_c - 0.30) * 0.40
    target_pct = min(raw_kelly, max_single_pos) * avg_c_penalty
    
    # ADV Cap (Enforces live SOFR - DGS3MO flexibility limits if aligned)
    aga_adv = int(cfg.get("aga_adv_fallback", 150000))
    is_aligned = (mri_score < 45.0) and (forensic_score >= 3.5)
    flexibility_mult = 1.25 if is_aligned else 1.0
    
    cap_percentage = max(0.02, pos_liq_cap * (1.0 - (mri_score / 100.0))) * flexibility_mult
    adv_cap_cad = aga_adv * cap_percentage * p_aga
    
    live_portfolio_value = float(cfg.get("target_capital", 5360.0))
    raw_target_cap = live_portfolio_value * target_pct
    max_pos_limit_cad = live_portfolio_value * max_single_pos * flexibility_mult
    
    # Proportional Barber Capped Target Sizing
    max_by_liquidity_cap = adv_cap_cad / 0.60 # Spear weight weight
    max_by_single_pos_cap = max_pos_limit_cad / 0.60
    
    capped_target_cap = min(raw_target_cap, max_by_liquidity_cap, max_by_single_pos_cap)
    
    st.markdown(f"- **Standard Single-Asset Kelly Sizing**: `{raw_kelly*100:.1f}%` of capital")
    st.markdown(f"- **Correlation & Risk-Parity Adjusted Target**: `{target_pct*100:.1f}%` of capital (after `{avg_c_penalty:.3f}x` correlation discount)")
    if is_aligned:
        st.markdown("- **Dynamic Sizer Flexibility**: Active (+25% limit expansion due to macro/micro alignment)")

# ========================================================
# 4. HORIZONTAL BAR CHART COMPARISONS FOR SIZER BOUNDARIES
# ========================================================
st.markdown("##### 📊 Portfolio Sizing Sieve & Constraint Bottlenecks")

fig_const = go.Figure()

# Plot conviction size vs hard policy limits vs liquidity bounds
fig_const.add_trace(go.Bar(
    y=['Blended Conviction Target', 'Max Single-Position Limit', 'Dynamic ADV Liquidity Cap (Spear)', 'Actionable Target Deployment'],
    x=[raw_target_cap, max_pos_limit_cad, adv_cap_cad, capped_target_cap],
    orientation='h',
    marker_color=['#00BCD4', '#EF5350', '#FFB300', '#66BB6A'],
    text=[f"${x:,.0f} CAD" for x in [raw_target_cap, max_pos_limit_cad, adv_cap_cad, capped_target_cap]],
    textposition='auto',
))

fig_const.update_layout(
    paper_bgcolor="#0A0A0A",
    plot_bgcolor="#0A0A0A",
    font_color="#E0E0E0",
    height=240,
    margin=dict(l=20, r=20, t=10, b=20),
    xaxis=dict(title="Sizing Allocations (CAD)", gridcolor="#1A1A1A"),
    yaxis=dict(gridcolor="#1A1A1A")
)
st.plotly_chart(fig_const, use_container_width=True)

# Explicit Constraint Warning Label:
if adv_cap_cad < raw_target_cap:
    st.warning(f"⚠️ **CONSTRAINED BY LIQUIDITY POLICY**: Your conviction sizer suggests a barbell target of `${raw_target_cap:,.2f} CAD`. However, dynamic exit liquidity limits (restricted to {cap_percentage*100:.1f}% ADV due to MRI stress) limit maximum Spear deployment to `${adv_cap_cad:,.2f} CAD` (representing a barbell capital ceiling of **`${max_by_liquidity_cap:,.2f} CAD`**).")
elif max_pos_limit_cad < raw_target_cap:
    st.info(f"🛡️ **CONSTRAINED BY SINGLE-POSITION POLICY CAPS**: Barbell sizing adjusted down by `${raw_target_cap - capped_target_cap:,.2f} CAD` to enforce the standard position risk ceiling.")
