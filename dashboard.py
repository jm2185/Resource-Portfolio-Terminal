import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
import json
import os
import requests

# Layout Changes Summary (v5.1 Single-Screen Monospace Educator):
# - Compressed typography and metrics cards padding to guarantee single-screen fit.
# - Wrapped Sandbox controls in a collapsed expander within the left column.
# - Implemented interactive st.session_state highlighting: clicking MRI or JSF glows related metrics.
# - Cleaned up visual relationships (arrows ➔) and progressive tooltips.
# - Reduced Plotly chart heights to 280px to prevent vertical scrolling.
# - Exposed complete engine metadata for synchronized tooltips.

st.set_page_config(layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #08080A; color: #D0D0D5; font-family: 'Courier New', Courier, monospace; }
    .metric-card { background-color: #121214; border: 1.5px solid #222226; border-radius: 6px; padding: 10px; text-align: center; transition: all 0.3s; }
    .metric-card-mri-glow { background-color: #121214; border: 1.5px solid #00E676 !important; border-radius: 6px; padding: 10px; text-align: center; box-shadow: 0 0 10px rgba(0, 230, 118, 0.3); transition: all 0.3s; }
    .metric-card-jsf-glow { background-color: #121214; border: 1.5px solid #FF9800 !important; border-radius: 6px; padding: 10px; text-align: center; box-shadow: 0 0 10px rgba(255, 152, 0, 0.3); transition: all 0.3s; }
    .metric-title { color: #8C8C92; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; cursor: help; border-bottom: 1px dotted #444; display: inline-block; }
    .metric-value { color: #FFFFFF; font-size: 20px; font-weight: bold; margin-top: 3px; }
    .header-row { display: flex; justify-content: space-between; align-items: center; background-color: #0E0E10; padding: 6px 12px; border-bottom: 1px solid #1E1E22; margin-bottom: 10px; border-radius: 4px; }
    .header-item { font-size: 11px; font-family: monospace; font-weight: bold; }
    .val-diagram { display: flex; justify-content: space-around; align-items: center; background-color: #0E0E10; padding: 10px; border-radius: 6px; margin-top: 6px; margin-bottom: 6px; border: 1.5px solid #222226; transition: all 0.3s; }
    .val-diagram-mri-glow { display: flex; justify-content: space-around; align-items: center; background-color: #0E0E10; padding: 10px; border-radius: 6px; margin-top: 6px; margin-bottom: 6px; border: 1.5px solid #00E676; box-shadow: 0 0 10px rgba(0, 230, 118, 0.3); transition: all 0.3s; }
    .val-diagram-jsf-glow { display: flex; justify-content: space-around; align-items: center; background-color: #0E0E10; padding: 10px; border-radius: 6px; margin-top: 6px; margin-bottom: 6px; border: 1.5px solid #FF9800; box-shadow: 0 0 10px rgba(255, 152, 0, 0.3); transition: all 0.3s; }
    div.stButton > button { font-family: monospace; font-size: 11px; font-weight: bold; background-color: #121214; border: 1px solid #222226; color: #D0D0D5; padding: 3px 8px; border-radius: 4px; }
    div.stButton > button:hover { border-color: #00E676; color: #00E676; }
</style>
""", unsafe_allow_html=True)

st.title("COMMODITYEX // MONITOR v5.1")
st.caption("TACTICAL SINGLE-SCREEN DECISION COCKPIT")

CONFIG_PATH = "v5_config.json"
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)
cfg = load_config()

@st.cache_data(ttl=2)
def get_live_state():
    try:
        res = requests.get("http://127.0.0.1:8000/state", timeout=1.5)
        if res.status_code == 200: return res.json()
    except Exception: pass
    return None

live_state = get_live_state()
metadata = live_state.get("metric_metadata", {}) if live_state else {}
def get_meta(key, field="definition"): 
    return metadata.get(key, {}).get(field, "Detailed description currently loading...")

is_stale = live_state is None or live_state.get("status") == "DEGRADED_STALE"

# Initialize Session States
if "override_mode" not in st.session_state: st.session_state.override_mode = False
if "highlighted_metric" not in st.session_state: st.session_state.highlighted_metric = None

if st.session_state.override_mode or live_state is None:
    if "spot_ag" not in st.session_state: st.session_state.spot_ag = float(live_state["metrics"]["Spot_Ag"]["value"]) if live_state else 74.8
    if "peer_ev" not in st.session_state: st.session_state.peer_ev = float(live_state["v4_valuation"]["Mean_Peer_EV_oz"]) if live_state else 2.50
    if "real_yield" not in st.session_state: st.session_state.real_yield = 1.8
    if "wti_oil" not in st.session_state: st.session_state.wti_oil = float(live_state["metrics"]["WTI"]["value"]) if live_state else 80.0
    if "vix" not in st.session_state: st.session_state.vix = float(live_state["metrics"]["VIX"]["value"]) if live_state else 16.5
    if "sofr_val" not in st.session_state: st.session_state.sofr_val = 5.31
    if "dgs3mo_val" not in st.session_state: st.session_state.dgs3mo_val = 5.22
    if "cash_burn" not in st.session_state: st.session_state.cash_burn = int(cfg["cash_burn"]["monthly_burn_rate"])
    if "aga_shares" not in st.session_state: st.session_state.aga_shares = int(cfg["aga_shares_out"])
    if "sloan_val" not in st.session_state: st.session_state.sloan_val = 0.02
    if "sloan_bs_val" not in st.session_state: st.session_state.sloan_bs_val = 0.015
    if "qoq_dilution" not in st.session_state: st.session_state.qoq_dilution = 0.0

# Sync sandbox inputs
override_mode = st.session_state.override_mode
if override_mode or live_state is None:
    spot_ag = st.session_state.spot_ag
    peer_ev = st.session_state.peer_ev
    real_yield = st.session_state.real_yield
    wti_oil = st.session_state.wti_oil
    vix = st.session_state.vix
    sofr_val = st.session_state.sofr_val
    dgs3mo_val = st.session_state.dgs3mo_val
    sofr_spread = sofr_val - dgs3mo_val
    cash_burn = st.session_state.cash_burn
    aga_shares = st.session_state.aga_shares
    sloan_val = st.session_state.sloan_val
    sloan_bs_val = st.session_state.sloan_bs_val
    qoq_dilution = st.session_state.qoq_dilution
else:
    metrics = live_state["metrics"]
    val = live_state["v4_valuation"]
    forensics = live_state["forensics"]
    spot_ag = float(metrics["Spot_Ag"]["value"])
    peer_ev = float(val["Mean_Peer_EV_oz"])
    real_yield = float(live_state["portfolio_stats"].get("real_yield", 1.8))
    wti_oil = float(metrics["WTI"]["value"])
    vix = float(metrics["VIX"]["value"])
    sofr_spread = float(metrics["TED"]["value"]) if "TED" in metrics else 0.05
    cash_burn = int(cfg["cash_burn"]["monthly_burn_rate"])
    aga_shares = int(cfg["aga_shares_out"])
    sloan_val = float(forensics["sloan_cfo"])
    sloan_bs_val = float(forensics.get("sloan_bs", 0.015))
    qoq_dilution = float(forensics["details"].get("dilution", {}).get("value", 0.0))

def compute_sandbox_mri():
    def norm(v, l, h): return max(0, min(100, (v - l) / (h - l) * 100))
    liq = norm(99.0 - 100, -5, 8) * 0.30 + norm(sofr_spread, 0.1, 0.9) * 0.20 + norm(real_yield, 0.5, 3.5) * 0.30
    yld = norm(0.54, -0.5, 1.5) * 0.50 + norm(4.44, 3.0, 5.5) * 0.50
    vol = norm(vix, 12, 35) * 0.50 + norm(3.5, 2, 7) * 0.50
    # Slider sandbox has no trailing history, so it uses the engine's legacy commodity-score fallback
    # (the live terminal computes the regime-stationary v2 score from cached copper/gold/silver windows).
    comm = norm(0.00136, 0.0010, 0.0018) * 0.60 + norm(spot_ag, 50.0, 100.0) * 0.40
    sentiment = norm(35000.0, -15000, 85000)
    mri = (liq * 0.30) + (yld * 0.20) + (vol * 0.20) + (comm * 0.15) + (sentiment * 0.15)
    return round(max(0, min(100, mri)), 1)
mri_score = compute_sandbox_mri() if (override_mode or live_state is None) else (live_state.get("mri") or 45.0)

def compute_sandbox_forensics():
    score = 0.0
    details = {}
    rf = cfg["rep_floor_params"]
    cash_component = rf["cash_treasury_m"] * 1_000_000
    runway = cash_component / cash_burn if cash_burn > 0 else 99.0
    if runway >= 18.0: score += 1.0; details["runway"] = {"pass": True, "value": runway, "desc": "Runway >= 18 mo"}
    else: details["runway"] = {"pass": False, "value": runway, "desc": f"Short Runway ({runway:.1f} mo)"}
    sloan_pass = (sloan_val < 0.05) and (sloan_bs_val < 0.05)
    if sloan_pass: score += 1.0; details["accrual"] = {"pass": True, "value": sloan_val, "desc": f"Sloan < 5%"}
    else: details["accrual"] = {"pass": False, "value": max(sloan_val, sloan_bs_val), "desc": f"Accrual overload"}
    if qoq_dilution < 0.02: score += 1.0; details["dilution"] = {"pass": True, "value": qoq_dilution, "desc": "Dilution < 2% QoQ"}
    else: details["dilution"] = {"pass": False, "value": qoq_dilution, "desc": f"Dilution expansion"}
    dp = 0.0 if qoq_dilution < 0.02 else 1.0
    rp = 0.0 if runway >= 18.0 else 1.0
    cp = 0.0 if sloan_pass else 1.0
    wp = 0.35 * dp + 0.21666666666666667 * (rp + cp)
    penalty = 1.0 - 0.30 * wp
    return score, penalty, details, runway

if override_mode or live_state is None:
    forensic_score, forensic_penalty, forensic_details, runway = compute_sandbox_forensics()
else:
    forensic_score = live_state["forensics"]["jsf_score"]
    forensic_penalty = live_state["forensics"]["penalty_factor"]
    forensic_details = live_state["forensics"]["details"]
    runway = live_state["forensics"]["runway"]

# Engine Valuation Formulations
base_aisc = cfg["dynamic_discovery_v5"]["estimated_industry_aisc_2026"]
dynamic_aisc = base_aisc + max(0, wti_oil - 80.0) * 0.15
phi_margin = max(0.58, (spot_ag - dynamic_aisc) / spot_ag) if spot_ag > dynamic_aisc else 0.05
commodity_leverage = spot_ag / dynamic_aisc if dynamic_aisc > 0 else 1.0
exp_scalar = cfg["dynamic_discovery_v5"].get("explorer_re_rating_scalar", 1.68)
raw_factor = commodity_leverage * phi_margin * exp_scalar
spot_dev = max(0, (spot_ag - 76.5) / 50)
ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - mri_score / 100)
discovery_premium_factor = max(0.50, min(raw_factor, ceiling))
negative_yield_premium = min(0.50, max(0.0, 1.0 - real_yield) * 0.25)
rov = cfg.get("rov_default", 1.18) * (1.0 + negative_yield_premium)

def calculate_sandbox_intrinsic(p_ev, s_ag):
    rf = cfg["rep_floor_params"]
    cash_component = rf["cash_treasury_m"] * 1_000_000
    infra_component = rf["permitting_infra_premium_m"] * 1_000_000
    buckets = cfg.get("project_buckets_oz_AgEq", {})
    target_mi_pct = cfg.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
    total_effective_oz = 0.0
    for proj, oz in buckets.items():
        mi_pct = target_mi_pct.get(proj, 0.50)
        total_effective_oz += (oz * mi_pct * 1.0) + (oz * (1.0 - mi_pct) * 0.50)
    resource_component = total_effective_oz * rf["stressed_resource_per_oz"]
    total_rep_value = cash_component + resource_component + infra_component
    rep_floor = (total_rep_value * rf["conservatism_scalar"]) / aga_shares
    # Smooth logistic ramp (synced with engine.calculate_jurisdiction_uplift): no cliff at $50.
    _ju = cfg.get("jurisdiction_uplift_params", {"low": 1.15, "high": 1.35, "center_spot_ag": 50.0, "steepness": 0.30})
    jurisdiction_uplift = _ju["low"] + (_ju["high"] - _ju["low"]) / (1.0 + float(np.exp(-_ju["steepness"] * (s_ag - _ju["center_spot_ag"]))))
    recovery = cfg.get("metallurgical_recovery", {})
    is_iai_total = 0.0
    for proj, oz in buckets.items():
        rec_silver = recovery.get(proj, {}).get("silver", 0.85)
        mi_pct = target_mi_pct.get(proj, 0.50)
        effective_oz = (oz * mi_pct * 1.0) + (oz * (1.0 - mi_pct) * 0.50)
        is_iai_total += effective_oz * p_ev * discovery_premium_factor * jurisdiction_uplift * rec_silver
    is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / aga_shares
    exp = cfg.get("exploration_upside", {})
    exp_premium_total = exp.get("expected_future_oz", 0) * p_ev * jurisdiction_uplift * exp.get("probability_of_discovery", 0.25)
    exp_per_share = exp_premium_total / aga_shares * exp.get("weight", 0.12)
    aga_intrinsic = (0.15 * rep_floor) + (0.70 * is_iai_per_share * forensic_penalty) + (0.15 * rov) + exp_per_share
    return aga_intrinsic, is_iai_per_share, exp_per_share, rep_floor

aga_intrinsic, is_iai_per_share, exp_per_share, rep_floor = calculate_sandbox_intrinsic(peer_ev, spot_ag)

p_aga = float(live_state["nodes"]["AGA.V"]["price"]) if live_state else 0.72
p_urc = float(live_state["nodes"]["URC.TO"]["price"]) if live_state else 4.81
p_groy = float(live_state["nodes"]["GROY"]["price"]) if live_state else 3.27
p_gmx = float(live_state["nodes"]["GMX.TO"]["price"]) if live_state else 2.08
ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)
ev_blended = (0.60 * aga_intrinsic) + (0.15 * p_urc * 1.15) + (0.15 * p_groy * 1.15) + (0.10 * p_gmx * 1.20)
u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

if override_mode or live_state is None:
    es_val_sim = -5.20
    h_score = 10.0 - (4.0 - forensic_score)*1.25 - (mri_score/100.0)*1.5
    h_score = round(max(1.0, min(10.0, h_score)), 1)
    if h_score >= 8.5: r_color = "#00E676"; r_desc = "HIGH INTEGRITY - STRONGLY ACTIONABLE"
    elif h_score >= 6.0: r_color = "#FFC107"; r_desc = "MODERATE QUALITY - EXERCISE GUARDRAILS"
    else: r_color = "#FF1744"; r_desc = "HIGH NOISE - EXTREME CAUTION"
    if mri_score > 65: directive = "DEFENSIVE MODE - PROTECT CAPITAL"
    elif h_score >= 8.5: directive = "HIGH CONVICTION ZONE - DEPLOY CAPITAL"
    else: directive = "HOLD POSITION - MONITOR TAPE"
    health_radar_priorities = [
        {"emoji": "🛒", "color": "#00E676", "title": "VALUATION ALIGNMENT", "desc": f"Blended Implied Edge of {u_implied*100:.1f}% represents massive torque potential."},
        {"emoji": "🛡️", "color": "#00E676", "title": "FORENSIC SHIELD", "desc": f"JSF Score secure at {forensic_score:.1f}/4.0. Dilution risk minimized."},
        {"emoji": "🔄", "color": "#00E676", "title": "MACRO SIZING CAPS", "desc": f"MRI Score is safe at {mri_score:.1f}. Sizing limits standard."}
    ]
else:
    health_radar = live_state.get("health_radar", {})
    h_score = health_radar.get("health_rating", 10.0)
    rcn = health_radar.get("rating_color", "green")
    r_color = "#00E676" if rcn == "green" else "#FFC107" if rcn == "orange" else "#FF1744"
    r_desc = health_radar.get("rating_desc", "PENDING")
    directive = live_state.get("directive", "Waiting...")
    icon_to_emoji = {"shopping_cart_outlined": "🛒", "info_outline": "ℹ️", "warning_amber_rounded": "⚠️", "verified_user_outlined": "🛡️", "lock_clock": "⏳", "swap_horizontal_circle_outlined": "🔄", "balance_outlined": "⚖️", "check_circle_outline": "✅"}
    color_to_hex = {"green": "#00E676", "orange": "#FFC107", "red": "#FF1744", "white": "#E0E0E0"}
    health_radar_priorities = []
    for p in health_radar.get("priorities", []):
        health_radar_priorities.append({
            "emoji": icon_to_emoji.get(p.get("icon", ""), "ℹ️"),
            "color": color_to_hex.get(p.get("color", ""), "#E0E0E0"),
            "title": p.get("title", ""),
            "desc": p.get("desc", "")
        })

# Global Style class helper based on highlighted metrics
highlighted = st.session_state.highlighted_metric
def get_card_class(metric_name):
    if not highlighted:
        return "metric-card"
    if highlighted.lower() == metric_name.lower():
        return "metric-card-jsf-glow" if highlighted == "JSF" else "metric-card-mri-glow"
    
    # Check relationship dynamically from metadata
    metric_meta = metadata.get(highlighted, {})
    related = metric_meta.get("related_metrics", [])
    if any(str(r).lower() == metric_name.lower() for r in related):
        return "metric-card-jsf-glow" if highlighted == "JSF" else "metric-card-mri-glow"
    return "metric-card"

# TOP HEADER ROW
mri_color = "#00E676" if mri_score < 45 else "#FFC107" if mri_score <= 65 else "#FF1744"
status_color = "#FF9800" if is_stale else "#00E676"
status_text = "DEGRADED STALE" if is_stale else "LIVE REAL-TIME"

st.write("")
cols_header = st.columns([1.5, 2.8, 3.2, 2.5])
with cols_header[0]:
    st.markdown(f"<div style='font-family: monospace; font-size:11px; color:{status_color}; font-weight:bold; padding-top:6px;'>● {status_text}</div>", unsafe_allow_html=True)
with cols_header[1]:
    h_cls = "color: #00E676; font-weight:bold;" if highlighted in ["MRI", "JSF"] else f"color: {r_color};"
    h_bg = "background-color: rgba(0,230,118,0.06); border: 1px solid #00E676;" if highlighted == "MRI" else "background-color: rgba(255,152,0,0.06); border: 1px solid #FF9800;" if highlighted == "JSF" else ""
    st.markdown(f"<div style='font-family: monospace; font-size:11.5px; border-radius: 4px; padding: 2px 8px; {h_bg}' title=\"{get_meta('Health Rating')}\">HEALTH RATING: <span style='{h_cls}'>{h_score:.1f}/10.0 ({r_desc[:12]})</span></div>", unsafe_allow_html=True)
with cols_header[2]:
    st.markdown(f"<div style='font-family: monospace; font-size:11.5px; padding-top:6px;'>DIRECTIVE: <span style='color: #FFF; font-weight:bold;'>{directive}</span></div>", unsafe_allow_html=True)
with cols_header[3]:
    if st.button(f"🧭 MRI Index: {mri_score:.1f}", key="mri_click_header_btn", use_container_width=True):
        st.session_state.highlighted_metric = "MRI" if st.session_state.highlighted_metric != "MRI" else None
        st.rerun()

metric_compass = st.toggle("🧭 Pinned Metric Compass / Glossary", help="View definitions and formulas for all core metrics.")
if metric_compass:
    with st.expander("Metric Compass & Educational Guide", expanded=True):
        mc_cols = st.columns(4)
        keys = list(metadata.keys())
        for idx, m_name in enumerate(keys):
            m_data = metadata[m_name]
            with mc_cols[idx % 4]:
                st.markdown(f"<strong style='color:#FFF; font-size:11px;'>{m_name}</strong>", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size: 10px; color: #8C8C92; line-height:1.25;'>{m_data.get('definition', '')}</div>", unsafe_allow_html=True)
                if 'actionability' in m_data: st.markdown(f"<div style='font-size: 9.5px; color:#A0A0A5; font-style:italic; margin-top:2px;'>Usage: {m_data['actionability']}</div>", unsafe_allow_html=True)
                st.markdown("<hr style='margin: 4px 0; border-color: #222;'>", unsafe_allow_html=True)

# MAIN CONTENT AREA
col_left, col_center, col_right = st.columns([1.1, 2.9, 2.0])

with col_left:
    st.markdown("<div style='font-size:11px; font-weight:bold; color:#A0A0A5; margin-bottom:4px;'>CONTROLS & SHIELDS</div>", unsafe_allow_html=True)
    override_toggle = st.checkbox("Activate Sandbox", value=st.session_state.override_mode, key="override_toggle_widget")
    if override_toggle != st.session_state.override_mode:
        st.session_state.override_mode = override_toggle
        st.rerun()

    if st.session_state.override_mode or live_state is None:
        with st.expander("🛠️ Sandbox Adjusters", expanded=False):
            st.session_state.spot_ag = st.slider("Spot Ag ($/oz)", 15.0, 100.0, float(st.session_state.spot_ag), step=0.5)
            st.session_state.peer_ev = st.slider("Peer EV/oz ($)", 0.5, 15.0, float(st.session_state.peer_ev), step=0.1)
            st.session_state.wti_oil = st.slider("WTI Crude", 40.0, 130.0, float(st.session_state.wti_oil), step=1.0)
            st.session_state.vix = st.slider("VIX Volatility", 9.0, 50.0, float(st.session_state.vix), step=0.5)
            st.session_state.sloan_val = st.slider("Sloan CFO Accruals", -0.15, 0.15, float(st.session_state.sloan_val), step=0.01)

    st.markdown("<hr style='margin: 6px 0; border-color: #222;'>", unsafe_allow_html=True)
    
    # Forensic Score styled button to trigger highlights
    st.markdown(f"<div style='font-size:9px; color:#6C6C72; text-align:center;'>💡 Click shield below to trace forecasts</div>", unsafe_allow_html=True)
    if st.button(f"🔬 FORENSIC JSF: {forensic_score:.1f} / 4.0", key="jsf_click_btn", use_container_width=True):
        st.session_state.highlighted_metric = "JSF" if st.session_state.highlighted_metric != "JSF" else None
        st.rerun()
        
    st.markdown(f"<div style='font-size:9.5px; color:#8C8C92; text-align:center; margin-top:2px;'>Accrual Penalty: {forensic_penalty:.3f}x</div>", unsafe_allow_html=True)
    
    with st.expander("🔍 Explorer Sieve", expanded=False):
        cba_pass = forensic_details.get("accrual", {}).get("pass", True)
        cba_desc = forensic_details.get("accrual", {}).get("desc", "")
        st.markdown(f"<div style='font-size:10px; color:{'#00E676' if cba_pass else '#FF1744'}'>CBA Accrual: {'PASS' if cba_pass else 'FAIL'} — {cba_desc}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:10px; color:#8C8C92;'>Runway: {runway:.1f} mo</div>", unsafe_allow_html=True)

    with st.expander("📊 Producer Sieve", expanded=False):
        sloan_cfo_pass = sloan_val < 0.05
        st.markdown(f"<div style='font-size:10px; color:{'#00E676' if sloan_cfo_pass else '#FF1744'}'>Sloan CFO: {sloan_val:+.3f}</div>", unsafe_allow_html=True)

with col_center:
    st.markdown("<div style='font-size:11px; font-weight:bold; color:#A0A0A5; margin-bottom:4px;'>VALUATION SYNTHESIS</div>", unsafe_allow_html=True)
    
    # Valuation widgets row
    st.markdown(f"""
    <div style="display:flex; gap:8px; margin-bottom:6px;">
        <div class="{get_card_class('IS-IAI')}" style="flex:1;">
            <div class="metric-title" title="{get_meta('IS-IAI')}">IS-IAI (In-Situ)</div>
            <div class="metric-value">${is_iai_per_share:.3f}</div>
        </div>
        <div class="{get_card_class('ROV')}" style="flex:1;">
            <div class="metric-title" title="{get_meta('ROV')}">ROV Premium</div>
            <div class="metric-value">{rov:.2f}x</div>
        </div>
        <div class="{get_card_class('Discovery Premium')}" style="flex:1;">
            <div class="metric-title" title="{get_meta('Discovery Premium')}">Disc. Premium</div>
            <div class="metric-value">{discovery_premium_factor:.2f}x</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Visual diagram with dynamic glow border
    diag_cls = "val-diagram-mri-glow" if highlighted == "MRI" else "val-diagram-jsf-glow" if highlighted == "JSF" else "val-diagram"
    st.markdown(f"""
    <div class="{diag_cls}">
        <div style="text-align:center;">
            <div style="font-size:9.5px; color:#8C8C92;" title="{get_meta('REP Floor')}">REP Floor Support</div>
            <div style="font-size:13.5px; font-weight:bold; color:#00E676;">${rep_floor:.3f}</div>
        </div>
        <div style="color:#444; font-size:18px; font-weight:bold;">➔</div>
        <div style="text-align:center;">
            <div style="font-size:10px; color:#8C8C92; font-weight:bold;">AGA.V Intrinsic</div>
            <div style="font-size:22px; font-weight:bold; color:#FFFFFF;">${aga_intrinsic:.3f} CAD</div>
        </div>
        <div style="color:#444; font-size:18px; font-weight:bold;">➔</div>
        <div style="text-align:center;">
            <div style="font-size:9.5px; color:#8C8C92;">Implied Edge</div>
            <div style="font-size:13.5px; font-weight:bold; color:#00E676;">{u_implied*100:.1f}%</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    t1, t2 = st.tabs(["💡 Forensic: Accruals", "💡 Macro Sizing Drivers"])
    with t1: st.markdown(f"<div style='font-size:10px; color:#D0D0D5; line-height:1.3;'>{get_meta('Sloan Ratios', 'actionability')}</div>", unsafe_allow_html=True)
    with t2: st.markdown(f"<div style='font-size:10px; color:#D0D0D5; line-height:1.3;'>{get_meta('MRI', 'actionability')}</div>", unsafe_allow_html=True)

with col_right:
    st.markdown("<div style='font-size:11px; font-weight:bold; color:#A0A0A5; margin-bottom:4px;'>SIZING & RADAR</div>", unsafe_allow_html=True)
    
    # NOTE: the engine is the single source of truth for live sizing (it exports the full waterfall:
    # Regime_Scaled_Capital, Macro_Multiplier, Active_Ceiling_Triggered, etc.). This block recomputes
    # the same formulas because the dashboard doubles as a SANDBOX: in override mode the sliders drive
    # these inputs, so the values must be derived locally. It is kept in lock-step with engine.calculate_sizing.
    guard = cfg.get("v5_guardrails", {})
    port_vol = 0.40
    port_variance = max(0.04, port_vol ** 2)
    # Dimensional coherence (synced with engine.calculate_sizing): convert the TOTAL convergence
    # return into an ANNUALIZED drift before applying Kelly f* = mu / sigma^2.
    convergence_years = max(0.25, guard.get("intrinsic_convergence_months", 18.0) / 12.0)
    mu_annualized = u_implied / convergence_years
    raw_portfolio_kelly = (mu_annualized / port_variance) * guard.get("fractional_kelly_multiplier", 0.5)
    max_leverage_allowed = 1.5 if vix <= 15.0 else max(0.60, 1.5 - ((vix - 15.0) * 0.045))
    # ES95 tail-risk throttle (synced with engine): scale leverage down as daily ES deteriorates.
    es_cfg = guard.get("es_throttle", {"no_penalty_pct": -5.0, "max_penalty_pct": -12.0, "max_reduction": 0.5})
    es_pct = float(live_state.get("portfolio_stats", {}).get("expected_shortfall_95", 0.0)) if not (override_mode or live_state is None) else 0.0
    if es_pct < es_cfg["no_penalty_pct"] and es_cfg["no_penalty_pct"] > es_cfg["max_penalty_pct"]:
        _sev = min(1.0, (es_cfg["no_penalty_pct"] - es_pct) / (es_cfg["no_penalty_pct"] - es_cfg["max_penalty_pct"]))
        es_throttle = 1.0 - es_cfg["max_reduction"] * _sev
    else:
        es_throttle = 1.0
    target_portfolio_leverage = min(raw_portfolio_kelly, max_leverage_allowed) * 0.76 * es_throttle
    multiplier = 1.00 if mri_score < 40 else 0.85 if mri_score < 65 else 0.55 if mri_score < 80 else 0.25
    live_portfolio_value = float(live_state["v4_valuation"]["Total_Equity"]) if not (override_mode or live_state is None) else float(cfg.get("target_capital", 5360.0))
    raw_target_cap = live_portfolio_value * target_portfolio_leverage * multiplier

    aga_adv = int(cfg.get("aga_adv_fallback", 150000))
    is_aligned = (mri_score < 45.0) and (forensic_score >= 3.5)
    flexibility_mult = 1.25 if is_aligned else 1.0
    cap_percentage = max(0.02, guard.get("position_liquidity_cap_pct", 0.15) * (1.0 - (mri_score / 100.0))) * flexibility_mult
    adv_cap_cad = aga_adv * cap_percentage * p_aga
    # Flexibility may loosen the liquidity cap above, but NEVER the structural 60% spear ceiling.
    max_pos_limit_cad = live_portfolio_value * guard.get("max_spear_position_pct", 0.60)
    
    max_by_liquidity_cap = adv_cap_cad / 0.60 
    max_by_single_pos_cap = max_pos_limit_cad / 0.60
    capped_target_cap = min(raw_target_cap, max_by_liquidity_cap, max_by_single_pos_cap)
    
    is_pos_binding = (capped_target_cap == max_by_single_pos_cap)
    is_liq_binding = (capped_target_cap == max_by_liquidity_cap)
    pos_cap_color = '#FF9800' if is_pos_binding else '#00E676'
    liq_cap_color = '#FF9800' if is_liq_binding else '#00E676'
    
    # Sieve Waterfall card with reactive glow
    is_mri_glow = (highlighted == "MRI")
    sieve_border = "border: 1.5px solid #00E676; box-shadow: 0 0 10px rgba(0, 230, 118, 0.3);" if is_mri_glow else "border: 1.5px solid #222226;"
    st.markdown(f"""
    <div style="background-color: #121214; {sieve_border} border-radius: 6px; padding: 10px; margin-bottom: 6px; font-family: monospace;">
        <div style="font-size: 9px; color: #8C8C92; margin-bottom: 4px; font-weight: bold;">VERTICAL CAPITAL SIEVE</div>
        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="color:#AAA; font-size:10px;">[1] REGIME SCALED</span><span style="color:#FFF; font-size:10px;">${raw_target_cap:,.0f}</span></div>
        <div style="display:flex; justify-content:space-between; margin-bottom:2px;"><span style="color:#AAA; font-size:10px;">[2] SPEAR CAP (60%)</span><span style="color:{pos_cap_color}; font-size:10px;">${max_pos_limit_cad:,.0f}</span></div>
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;"><span style="color:{'#00E676' if is_mri_glow else '#AAA'}; font-size:10px;" title="{get_meta('ADV Cap')}">[3] LIQUIDITY ({cap_percentage*100:.1f}% ADV) {'★' if is_mri_glow else ''}</span><span style="color:{liq_cap_color}; font-size:10px;">${adv_cap_cad:,.0f}</span></div>
        <div style="border-top:1px solid #333; padding-top:4px; display:flex; justify-content:space-between;"><span style="color:#00E676; font-size:10px; font-weight:bold;">● TARGET DEPLOY</span><span style="color:#00E676; font-size:11.5px; font-weight:bold;">${capped_target_cap:,.0f} CAD</span></div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"<div style='font-size:9.5px; color:#8C8C92; margin-bottom:2px;' title='{get_meta('Priorities')}'>TACTICAL RADAR PRIORITIES</div>", unsafe_allow_html=True)
    for p in health_radar_priorities[:2]:
        with st.expander(f"{p['emoji']} {p['title']}", expanded=True):
            st.markdown(f"<div style='font-size:9.5px; color:{p['color']}; line-height:1.2;'>{p['desc']}</div>", unsafe_allow_html=True)

# BOTTOM ANCHORED SECTION (TABS)
st.markdown("<hr style='margin: 8px 0; border-color: #222;'>", unsafe_allow_html=True)
tab_exec, tab_sens = st.tabs(["📊 Barbell Execution Sieve", "🔬 Sensitivity & Curve Structures"])

with tab_exec:
    weights = {"AGA.V": 0.60, "GROY": 0.15, "URC.TO": 0.15, "GMX.TO": 0.10}
    table_rows_html = ""
    for ticker, w in weights.items():
        price = 0.71 if ticker == "AGA.V" else 4.81 if ticker == "URC.TO" else 3.27 if ticker == "GROY" else 2.08
        shares = live_state["nodes"][ticker].get("shares", 0.0) if live_state and "nodes" in live_state and ticker in live_state["nodes"] else (5000.0 if ticker == "AGA.V" else 161.0 if ticker == "GROY" else 130.0 if ticker == "URC.TO" else 230.0)
        
        current_value = shares * price * (1.38 if ticker == "GROY" else 1.0)
        current_weight = (current_value / live_portfolio_value) * 100 if live_portfolio_value > 0 else 0.0
        
        target_value = capped_target_cap * w
        div_price = price * (1.38 if ticker == "GROY" else 1.0)
        target_shares = target_value / div_price if div_price > 0 else 0.0
        delta_shares = target_shares - shares
        
        intrinsic_val = float(live_state["v4_valuation"]["AGA_Intrinsic"]) if live_state and "v4_valuation" in live_state and "AGA_Intrinsic" in live_state["v4_valuation"] else aga_intrinsic
        
        if abs(delta_shares) < 100: directive_act, dir_color, bg_color = "HOLD", "#888888", "transparent"
        elif delta_shares > 0:
            if ticker == "AGA.V" and price > intrinsic_val: directive_act, dir_color, bg_color = "HOLD (Premium)", "#FF9800", "rgba(255, 152, 0, 0.06)"
            else: directive_act, dir_color, bg_color = "ACCUMULATE", "#00E676", "rgba(0, 230, 118, 0.06)"
        else: directive_act, dir_color, bg_color = "TRIM", "#FF9800", "rgba(255, 152, 0, 0.06)"
            
        table_rows_html += f'''
        <tr style="border-bottom: 1px solid #1E1E22; font-size: 10px;">
            <td style="padding: 6px 4px; font-weight: bold; color: #FFFFFF;">{ticker}</td>
            <td style="padding: 6px 4px; color: #8C8C92;">{"Spear" if ticker == "AGA.V" else "Ballast"}</td>
            <td style="padding: 6px 4px; text-align: right; font-family: monospace;">{shares:,.0f}</td>
            <td style="padding: 6px 4px; text-align: right; font-family: monospace; color: #CCCCCC;">{current_weight:.1f}%</td>
            <td style="padding: 6px 4px; text-align: right; font-family: monospace; color: #00E676;">{w*100:.1f}%</td>
            <td style="padding: 6px 4px; text-align: right; font-family: monospace; color: #CCCCCC;">{target_shares:,.0f}</td>
            <td style="padding: 6px 4px; text-align: right; font-family: monospace; font-weight: bold; color: {dir_color};">{delta_shares:+,.0f}</td>
            <td style="padding: 6px 4px; text-align: center;"><span style="background-color: {bg_color}; color: {dir_color}; border: 1px solid {dir_color}4d; border-radius: 4px; padding: 2px 6px; font-size: 8px; font-weight: bold;">{directive_act}</span></td>
        </tr>
        '''
        
    st.markdown(f"""
    <div style="background-color: #0E0E10; border: 1px solid #1E1E22; border-radius: 6px; padding: 8px;">
        <table style="width:100%; border-collapse: collapse; font-family: monospace;">
            <thead>
                <tr style="border-bottom: 1.5px solid #1E1E22; color: #8C8C92; font-size: 9px; text-align: left;">
                    <th style="padding: 4px;">ASSET</th><th style="padding: 4px;">ROLE</th><th style="padding: 4px; text-align: right;">HOLDINGS</th>
                    <th style="padding: 4px; text-align: right;">CUR WT</th><th style="padding: 4px; text-align: right;">TGT WT</th>
                    <th style="padding: 4px; text-align: right;">TGT SHARES</th><th style="padding: 4px; text-align: right;">DELTA</th>
                    <th style="padding: 4px; text-align: center;">ORDER</th>
                </tr>
            </thead>
            <tbody>{table_rows_html}</tbody>
        </table>
    </div>
    """, unsafe_allow_html=True)

with tab_sens:
    left_panel, right_panel = st.columns(2)
    with left_panel:
        st.markdown("<div style='font-size:10px; font-weight:bold; color:#8C8C92;'>Silver Price vs. Peer ev/oz ($ CAD) Intrinsic Grid</div>", unsafe_allow_html=True)
        silver_range = np.linspace(20, 100, 9)
        peer_ev_range = np.linspace(1.0, 10.0, 10)
        grid = []
        for s_price in silver_range:
            row = []
            for p_multiple in peer_ev_range:
                intrinsic, _, _, _ = calculate_sandbox_intrinsic(p_multiple, s_price)
                row.append(round(intrinsic, 2))
            grid.append(row)
        df_heatmap = pd.DataFrame(grid, index=[f"${x:.0f}" for x in silver_range], columns=[f"${y:.1f}" for y in peer_ev_range])
        fig_heat = px.imshow(df_heatmap, labels=dict(x="Peer Comps EV/oz ($ CAD)", y="Spot Silver ($/oz)", color="AGA Intrinsic"), color_continuous_scale="Greys", aspect="auto")
        fig_heat.update_layout(paper_bgcolor="#08080A", plot_bgcolor="#08080A", font_color="#D0D0D5", margin=dict(l=10, r=10, t=10, b=10), height=200)
        st.plotly_chart(fig_heat, use_container_width=True)

    with right_panel:
        st.markdown("<div style='font-size:10px; font-weight:bold; color:#8C8C92;'>Tornado Chart: 20% Metric Swings</div>", unsafe_allow_html=True)
        base_val = aga_intrinsic
        swing_keys = ["Spot Silver", "Peer EV/oz", "Real Yields"]
        lows, highs = [], []
        l_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev, spot_ag * 0.8)
        h_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev, spot_ag * 1.2)
        lows.append(l_intrinsic); highs.append(h_intrinsic)
        
        l_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev * 0.8, spot_ag)
        h_intrinsic, _, _, _ = calculate_sandbox_intrinsic(peer_ev * 1.2, spot_ag)
        lows.append(l_intrinsic); highs.append(h_intrinsic)
        
        rov_l = cfg.get("rov_default", 1.18) * (1.0 + min(0.50, max(0.0, 1.0 - (real_yield + 1.0)) * 0.25))
        rov_h = cfg.get("rov_default", 1.18) * (1.0 + min(0.50, max(0.0, 1.0 - (real_yield - 1.0)) * 0.25))
        lows.append(base_val - (rov - rov_l) * 0.15); highs.append(base_val + (rov_h - rov) * 0.15)

        swings = [abs(h - l) for l, h in zip(lows, highs)]
        sorted_indices = np.argsort(swings)
        sorted_keys = [swing_keys[i] for i in sorted_indices]
        sorted_lows = [lows[i] for i in sorted_indices]
        sorted_highs = [highs[i] for i in sorted_indices]

        fig_tor = go.Figure()
        fig_tor.add_trace(go.Bar(y=sorted_keys, x=[l - base_val for l in sorted_lows], name="-20% Swing", orientation='h', marker=dict(color="#FF1744")))
        fig_tor.add_trace(go.Bar(y=sorted_keys, x=[h - base_val for h in sorted_highs], name="+20% Swing", orientation='h', marker=dict(color="#00E676")))
        fig_tor.update_layout(barmode='relative', paper_bgcolor="#08080A", plot_bgcolor="#08080A", font_color="#D0D0D5", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), margin=dict(l=10, r=10, t=10, b=10), height=200)
        st.plotly_chart(fig_tor, use_container_width=True)
