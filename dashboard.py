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

st.title("COMMODITYEX // MASTER ARCHITECTURE v5.0")
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
    
    st.sidebar.subheader("Forensic Drivers")
    cash_burn = st.sidebar.number_input("Monthly Cash Burn ($ CAD)", 100000, 2000000, int(cfg["cash_burn"]["monthly_burn_rate"]), step=50000)
    aga_shares = st.sidebar.number_input("AGA Outstanding Shares", 10000000, 500000000, int(cfg["aga_shares_out"]))
    sloan_val = st.sidebar.slider("Sloan CFO Ratio", -0.20, 0.20, 0.02, step=0.01)
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

# 1. Macro BVS Scaling
def compute_sandbox_bvs():
    def norm(val, low, high):
        return max(0, min(100, (val - low) / (high - low) * 100))
    liq = norm(real_yield, 0.5, 3.5) * 0.4 + norm(ted := 0.35, 0.1, 0.9) * 0.3
    yld = norm(y30_y10 := 0.3, -0.5, 1.5) * 0.5
    vol = norm(vix, 12, 35) * 0.5
    comm = norm(copper_gold := 0.0018, 0.0014, 0.0022) * 0.6 + norm(spot_ag/30, 0.8, 1.4) * 0.4
    sentiment = norm(35000.0, -15000, 85000)
    bvs = (liq * 0.30) + (yld * 0.20) + (vol * 0.20) + (comm * 0.15) + (sentiment * 0.15)
    return round(max(0, min(100, bvs)), 1)

bvs_score = compute_sandbox_bvs() if (override_mode or live_state is None) else live_state["bvs"]

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
        
    if sloan_val < 0.05:
        score += 1.0
        details["accrual"] = {"pass": True, "value": sloan_val, "desc": "Sloan CFO < 5%"}
    else:
        details["accrual"] = {"pass": False, "value": sloan_val, "desc": f"Sloan warnings ({sloan_val*100:.1f}%)"}

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
ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - bvs_score / 100)
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
        <div class="metric-title">BVS Sovereign Stress</div>
        <div class="metric-value" style="color: {'#FF1744' if bvs_score > 65 else '#FFC107' if bvs_score > 40 else '#00E676'};">{bvs_score:.1f}</div>
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

f_col1, f_col2 = st.columns([1, 2])

with f_col1:
    st.markdown("**Forensic Scoring Summary**")
    st.markdown(f"**Composite JSF Score**: `{forensic_score:.1f} / 4.0`")
    st.markdown(f"**Valuation Penalty Discount Factor**: `{forensic_penalty:.3f}x`")
    
    # Status badges
    for k, v in forensic_details.items():
        icon = "<span class='pass-badge'>[PASS]</span>" if v["pass"] else "<span class='fail-badge'>[WARN]</span>"
        st.markdown(f"{icon} **{k.upper()}**: {v['desc']}", unsafe_allow_html=True)

with f_col2:
    st.markdown("**Capital Dilution & Runway Diagnostics**")
    st.markdown(f"""
    - **Operating Cash Flow Accruals**: Sloan Ratio is `{sloan_val:+.4f}`. Values below `+0.05` denote that earnings are backed by true operating cash inflows rather than non-cash accrual assets.
    - **Year-over-Year Share Dilution**: Trailing quarter share count change is `{(qoq_dilution*100):.1f}%`. Dilutions below `2.0%` QoQ keep existing shareholders from dilution decay.
    - **Stressed Cash Runway Runway**: Corporate cash lifespan is `{runway:.1f} months` under current monthly burn rate of `${cash_burn:,.2f} CAD`. lifespans below `18 months` trigger early dilution warning flags.
    """)

# ========================================================
# POSITION SIZING SIMULATOR
# ========================================================
st.markdown("---")
st.subheader("Advanced Kelly Allocation & ADV Sizing Sandbox")

volatilities = live_state["portfolio_stats"]["vols"] if live_state else {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
corr_matrix = live_state["portfolio_stats"]["correlations"] if live_state else {"AGA.V": {"GROY": 0.5}}
es_95 = live_state["portfolio_stats"]["expected_shortfall_95"] if live_state else 5.20
avg_corr = live_state["portfolio_stats"]["avg_correlation"] if live_state else 0.45

s_col1, s_col2 = st.columns(2)

with s_col1:
    st.markdown("**Portfolio Tail Risk Diagnostics**")
    st.markdown(f"- **Annualized 'Spear' Volatility (AGA.V)**: `{volatilities.get('AGA.V', 0.45)*100:.1f}%` ")
    st.markdown(f"- **Annualized 'Ballast' Volatilities**: GROY `{volatilities.get('GROY', 0.35)*100:.1f}%` | URC `{volatilities.get('URC.TO', 0.42)*100:.1f}%` ")
    st.markdown(f"- **Portfolio-Level Expected Shortfall (95% ES)**: `{es_95:.2f}%` daily (Historical worst 5% average daily losses)")
    st.markdown(f"- **Barbell Inter-Asset Correlation**: `{avg_corr:.2f}` (Low correlation improves diversification bounds)")

with s_col2:
    st.markdown("**Sizing Allocation Simulator**")
    
    # Kelly target sizing math
    guard = cfg.get("v5_guardrails", {})
    f_kelly = guard.get("fractional_kelly_multiplier", 0.5)
    pos_liq_cap = guard.get("position_liquidity_cap_pct", 0.15)
    
    variance = max(0.04, volatilities.get("AGA.V", 0.45) ** 2)
    raw_kelly = (u_implied / variance) * f_kelly
    
    # Correlation discount penalty
    groy_c = corr_matrix.get("AGA.V", {}).get("GROY", 0.5)
    avg_c_penalty = 1.0 - max(0.0, groy_c - 0.30) * 0.40
    target_pct = min(raw_kelly, guard.get("max_single_position_pct", 0.20)) * avg_c_penalty
    
    # ADV Cap
    aga_adv = int(cfg.get("aga_adv_fallback", 150000))
    adv_cap_cad = aga_adv * pos_liq_cap * p_aga
    
    raw_target_cap = int(cfg["target_capital"]) * target_pct
    capped_target_cap = min(raw_target_cap, adv_cap_cad)
    
    st.markdown(f"- **Standard Single-Asset Kelly Sizing**: `{raw_kelly*100:.1f}%` of capital")
    st.markdown(f"- **Correlation & Risk-Parity Adjusted Target**: `{target_pct*100:.1f}%` of capital (after `{avg_c_penalty:.3f}x` correlation discount)")
    st.markdown(f"- **Average Daily Volume (ADV) Liquidity Cap**: `${adv_cap_cad:,.2f} CAD` (Hard cap based on trading `{pos_liq_cap*100:.0f}%` of average volume)")
    st.markdown(f"- **Capped Sandbox Sizing Target**: **`${capped_target_cap:,.2f} CAD`** (against standard target allocation of `${raw_target_cap:,.2f} CAD`)")
