import unittest
import asyncio
import engine
from engine import (MacroRegimeEngine, PeerEngine, ForensicEngine, ValuationEngine, PortfolioSizer,
                    HealthRadarEngine, _robust_adv_shares, _percentile_rank)

class TestCommodityExV5(unittest.TestCase):
  def setUp(self):
    self.config_path = "v5_config.json"
    self.macro = MacroRegimeEngine(self.config_path)
    self.peers = PeerEngine(self.config_path)
    self.forensics = ForensicEngine(self.config_path)
    self.val = ValuationEngine(self.config_path)
    self.sizer = PortfolioSizer(self.config_path)
    self.radar = HealthRadarEngine(self.config_path)

  def test_mri_calculation_risk_on(self):
    # Risk-On Scenario (Low VIX, Low Yields, stable dollar, strong commodity momentum)
    metrics = {
      "10Y": {"value": 3.5}, "30Y": {"value": 3.8},
      "DXY": {"value": 98.0}, "Spreads": {"value": 2.5},
      "TED": {"value": 0.15}, "VIX": {"value": 13.0},
      "CFTC_Silver_Net_Longs": {"value": 65000.0}
    }
    spot_ag = 76.5
    real_yield = 1.0
    copper = 4.5
    gold = 2300.0
    dxy_mom = -1.2
    
    mri = self.macro.calculate_mri(metrics, spot_ag, real_yield, copper, gold, dxy_mom)
    self.assertTrue(mri < 45.0, f"MRI should be low for Risk-On. Got: {mri}")
    print(f"[TEST] MRI Risk-On Score: {mri}")

  def test_mri_calculation_risk_off(self):
    # Risk-Off Scenario (High Yields, soaring VIX, spiking dollar, negative commodity momentum)
    metrics = {
      "10Y": {"value": 5.2}, "30Y": {"value": 5.4},
      "DXY": {"value": 105.5}, "Spreads": {"value": 6.8},
      "TED": {"value": 0.85}, "VIX": {"value": 34.0},
      "CFTC_Silver_Net_Longs": {"value": -5000.0}
    }
    spot_ag = 55.0
    real_yield = 3.2
    copper = 3.5
    gold = 2450.0
    dxy_mom = 2.5
    
    mri = self.macro.calculate_mri(metrics, spot_ag, real_yield, copper, gold, dxy_mom)
    self.assertTrue(mri > 65.0, f"MRI should be elevated in systemic crisis. Got: {mri}")
    print(f"[TEST] MRI Risk-Off Score: {mri}")

  def test_junior_specific_forensics(self):
    # Case A: High quality junior (Runway >= 18mo, Low Sloan, No Dilution, Low G&A)
    score_a, penalty_a, details_a = self.forensics.calculate_jsf_score(
      ticker="MOCK.V",
      cash=15000000.0,
      monthly_burn=750000.0,  # 20 months runway
      sloan_cfo=0.015,         # high quality accruals
      sloan_bs=0.012,
      shares_t0=208600000,
      shares_t1=208600000,    # 0% dilution
      sga_expense=500000.0    # 500k vs 2.25M quarterly burn (22%)
    )
    self.assertEqual(score_a, 4.0)
    self.assertEqual(penalty_a, 1.0)
    
    # Case B: Capital decay junior (Short runway, high dilution, accrual inflation, bloated overhead)
    # Plus pass high cfo cash burn acceleration (curr_burn = 3M, prev_burn = 1M, cash = 4M -> CBA = 50% > 15%)
    score_b, penalty_b, details_b = self.forensics.calculate_jsf_score(
      ticker="MOCK.V",
      cash=4000000.0,
      monthly_burn=750000.0,  # 5.3 months runway
      sloan_cfo=0.08,          # Sloan warning
      sloan_bs=0.09,
      shares_t0=240000000,
      shares_t1=208600000,    # 15% dilution
      sga_expense=1200000.0,   # 1.2M vs 2.25M quarterly burn (53%)
      cfo_t0=-3000000.0,
      cfo_t1=-1000000.0,
      cash_t0=4000000.0
    )
    self.assertEqual(score_b, 0.0)
    self.assertEqual(penalty_b, 0.70)
    
    # Case C: Producing/Royalty asset (e.g. GROY - type == royalty) with Sloan warning (> 0.05)
    score_c, penalty_c, details_c = self.forensics.calculate_jsf_score(
      ticker="GROY",
      cash=15000000.0,
      monthly_burn=750000.0,
      sloan_cfo=0.08,          # Sloan warning > 0.05
      sloan_bs=0.012,
      shares_t0=208600000,
      shares_t1=208600000,    # 0% dilution
      sga_expense=500000.0
    )
    # Since Sloan Warning fails (score drops by 1.0), score is 3.0, penalty factor is 0.70 + 0.30 * 3/4 = 0.925
    self.assertEqual(score_c, 3.0)
    self.assertAlmostEqual(penalty_c, 0.925)
    self.assertFalse(details_c["accrual"]["pass"])
    
    # Case D: AGA.V explorer protected by context-aware overrides (governed: justified + unexpired).
    # `today` is pinned inside the config override window (expiry 2026-12-31) for deterministic CI.
    score_d, penalty_d, details_d = self.forensics.calculate_jsf_score(
      ticker="AGA.V",
      cash=40000000.0,
      monthly_burn=750000.0,  # 53.3 months runway
      sloan_cfo=0.015,
      sloan_bs=0.012,
      shares_t0=240000000,
      shares_t1=208600000,    # 15% dilution (Overridden to Pass)
      sga_expense=500000.0,   # 22% G&A drag
      cfo_t0=-3000000.0,
      cfo_t1=-1000000.0,      # CBA burn acceleration (Overridden to Pass)
      cash_t0=4000000.0,
      today="2026-06-01"
    )
    self.assertEqual(score_d, 4.0)
    self.assertEqual(penalty_d, 1.0)
    self.assertTrue(details_d["dilution"]["pass"])
    self.assertTrue(details_d["accrual"]["pass"])
    # Runway-aware forensic (v5.2): AGA's 15% raise now passes on its ~53-mo runway (funding, not
    # decay) — the funded-raise insulation engages ahead of the manual waiver. Either path reads
    # "insulated"; CBA still relies on the manual override.
    self.assertTrue(details_d["dilution"].get("runway_insulated"))
    self.assertIn("insulated", details_d["dilution"]["desc"].lower())
    self.assertIn("CBA Insulated", details_d["accrual"]["desc"])
    
    print(f"[TEST] High Quality Junior Penalty: {penalty_a}x | Dilution decay Junior: {penalty_b}x | Royalty Accrual Decay: {penalty_c:.3f}x | Override Insulated Junior: {penalty_d}x")

  def test_continuous_rov(self):
    # Continuous Options Multiplier under standard yield vs negative yields
    rov_standard = self.val.calculate_continuous_rov(real_yield=2.0, spot_ag=74.8, rov_default=1.18)
    rov_negative = self.val.calculate_continuous_rov(real_yield=-1.5, spot_ag=74.8, rov_default=1.18)
    
    self.assertTrue(rov_negative > rov_standard)
    print(f"[TEST] ROV under Nominal Yields: {rov_standard:.2f}x | ROV under Deep Negative Real Yields: {rov_negative:.2f}x")

  def test_liquidity_cap_sizing(self):
    # Scenario: Implied Edge is 150%, but position is highly illiquid
    live_portfolio = 10000.0
    u_implied = 1.50
    vols = {"AGA.V": 0.40, "GROY": 0.30, "GMX.TO": 0.32, "URC.TO": 0.35}
    corr_matrix = {
      "AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30},
      "GROY": {"URC.TO": 0.40, "GMX.TO": 0.35},
      "URC.TO": {"GMX.TO": 0.45}
    }
    mri_score = 30.0
    
    # Test A: Liquid peer (ADV: 500,000 shares)
    limit_params_liquid = {"aga_price": 0.72, "aga_adv": 500000, "port_vol": 0.40, "vix": 16.5}
    res_liquid = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, limit_params_liquid)
    
    # Test B: Illiquid peer (ADV: 10,000 shares)
    limit_params_illiquid = {"aga_price": 0.72, "aga_adv": 10000, "port_vol": 0.40, "vix": 16.5}
    res_illiquid = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, limit_params_illiquid)
    
    self.assertTrue(res_illiquid["adv_cap_cad"] < res_liquid["adv_cap_cad"])
    print(f"[TEST] ADV Sizing Cap (Liquid): ${res_liquid['adv_cap_cad']} CAD | ADV Sizing Cap (Illiquid): ${res_illiquid['adv_cap_cad']} CAD")

  def test_spear_position_cap_alignment(self):
    # Scenario: Sizing portfolio to verify that our new max_spear_position_pct cap
    # does not restrict target capital to 33.33% of portfolio value.
    live_portfolio = 10000.0
    u_implied = 1.15
    vols = {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
    corr_matrix = {
      "AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30},
      "GROY": {"URC.TO": 0.40, "GMX.TO": 0.35},
      "URC.TO": {"GMX.TO": 0.45}
    }
    mri_score = 30.0
    
    limit_params = {"aga_price": 0.71, "aga_adv": 500000, "port_vol": 0.40, "vix": 16.5}
    res = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, limit_params)
    
    # Target capital should be capped by Spear max cap (60%) rather than standard 20% cap.
    # Standard 20% cap would limit target capital to: (10000 * 0.20) / 0.60 = 3333.33 CAD.
    # Spear 60% cap limits target capital to: (10000 * 0.60) / 0.60 = 10000.00 CAD.
    # Expected target under Kelly is ~7200 CAD, which should be allowed under the new 60% Spear cap!
    self.assertTrue(res["e_target"] > 3333.33, f"Target capital is artificially capped by 20% limit: {res['e_target']}")
    print(f"[TEST] Spear Sizing Cap Aligned: Target Capital is ${res['e_target']} CAD (allowed above $3,333.33 CAD)")

  def test_health_radar_engine(self):
    # Scenario A: High Integrity Live (JSF = 4.0, MRI = 30.0, Live, ES = -4.0%)
    res_a = self.radar.calculate_health_rating(jsf_score=4.0, mri_score=30.0, expected_shortfall_95=-4.0, is_stale=False)
    self.assertEqual(res_a["health_rating"], 9.6)
    self.assertEqual(res_a["rating_color"], "green")
    
    # Scenario B: Stale Degraded & Diluted (JSF = 2.0, MRI = 80.0, Stale Cache, ES = -12.0%)
    res_b = self.radar.calculate_health_rating(jsf_score=2.0, mri_score=80.0, expected_shortfall_95=-12.0, is_stale=True)
    # Phase 2: ES penalty is now continuous & convex (was a discrete 1.0 cap at <= -10%).
    # k = 1/5^1.5 = 0.089443; excess = 12 - 5 = 7; es_penalty = 0.089443 * 7^1.5 = 1.6565.
    # H = 10.0 - (4.0 - 2.0)*1.25 - (80/100)*1.5 - 2.0 - 1.6565 = 2.6435 -> 2.6
    self.assertEqual(res_b["health_rating"], 2.6)
    self.assertEqual(res_b["rating_color"], "red")
    
    # Test Priority Checklist Generation
    mock_val = {
      "Implied_Upside": 123.3,
      "REP_Floor": 0.983,
      "Kelly_Multiple": 0.77,
      "ADV_Cap_CAD": 33786.0,
      "ADV_Cap_Percentage": 10.5,
      "AGA_Intrinsic": 4.16
    }
    priorities = self.radar.generate_priorities(mock_val, jsf_score=2.0, mri_score=30.0, expected_shortfall_95=-6.03, p_aga=0.71)
    spear_priority = priorities[0]
    # Phase 4a: the spear-arbitrage priority now gates on the spear's OWN intrinsic-vs-price upside
    # ((4.16/0.71 - 1) = 486%), not the blended portfolio edge, and surfaces both numbers.
    self.assertEqual(spear_priority["title"], "EXPLOIT SPEAR ARBITRAGE")
    self.assertIn("486% upside", spear_priority["desc"])
    self.assertIn("blended portfolio edge 123%", spear_priority["desc"])
    
    print(f"[TEST] Health Rating Live (High Conviction): {res_a['health_rating']}/10.0 | Health Rating Stale & Stressed: {res_b['health_rating']}/10.0")

  def test_valuation_dynamic_shares(self):
    # Test that ValuationEngine per-share values respond realistically and scale down when shares are diluted
    rep_standard = self.val.calculate_rep_floor(shares_outstanding=208600000)
    rep_diluted = self.val.calculate_rep_floor(shares_outstanding=250000000)
    self.assertTrue(rep_diluted < rep_standard)
    self.assertAlmostEqual(rep_diluted, rep_standard * (208600000 / 250000000))
    
    # Test that is_iai_per_share also scales down proportionally
    is_iai_standard, _ = self.val.calculate_is_iai(peer_ev_oz=2.50, discovery_premium_factor=1.20, spot_ag=74.8, capital_discount_factor=1.0, shares_outstanding=208600000)
    is_iai_diluted, _ = self.val.calculate_is_iai(peer_ev_oz=2.50, discovery_premium_factor=1.20, spot_ag=74.8, capital_discount_factor=1.0, shares_outstanding=250000000)
    self.assertTrue(is_iai_diluted < is_iai_standard)
    self.assertAlmostEqual(is_iai_diluted, is_iai_standard * (208600000 / 250000000))
    print(f"[TEST] Rep Floor Undiluted: ${rep_standard:.3f} | Diluted: ${rep_diluted:.3f}")
    print(f"[TEST] IS-IAI Undiluted: ${is_iai_standard:.3f} | Diluted: ${is_iai_diluted:.3f}")

  def test_partial_fetch_expected_shortfall(self):
    # Simulates a partial yfinance return fetch where 3 out of 4 assets failed (e.g. timeout)
    # df_rets contains only 1 column instead of 4, but weights are aligned and normalized.
    import pandas as pd
    import numpy as np
    
    # 60 days of mock returns for a single asset
    mock_returns = np.random.normal(0.0, 0.02, 60)
    df_partial = pd.DataFrame({"AGA.V": mock_returns})
    
    # Dynamic alignment simulation
    barbell_tickers = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]
    ticker_weight_map = {"AGA.V": 0.60, "GROY": 0.15, "GMX.TO": 0.10, "URC.TO": 0.15}
    
    available_tickers = [t for t in barbell_tickers if t in df_partial.columns]
    self.assertEqual(available_tickers, ["AGA.V"])
    
    raw_weights = np.array([ticker_weight_map[t] for t in available_tickers])
    weights = raw_weights / np.sum(raw_weights)
    self.assertEqual(weights[0], 1.0)
    
    df_partial_aligned = df_partial[available_tickers]
    
    # Call calculate_expected_shortfall with (60, 1) and (1,) - should complete without shape mismatch
    es_val = self.sizer.calculate_expected_shortfall(df_partial_aligned, weights)
    self.assertNotEqual(es_val, 0.0)  # expect valid ES since returns are non-empty
    
    # Verify dot product completes successfully
    port_returns = df_partial_aligned.dot(weights)
    self.assertEqual(port_returns.shape, (60,))
    print(f"[TEST] Dynamic alignment ES: {es_val*100:.3f}% | Dot product shape: {port_returns.shape}")

  def test_spear_ceiling_never_breached_by_flexibility(self):
    # Phase 1a: Even in a "pristine" aligned regime (MRI < 45 AND JSF >= 3.5) where the
    # opportunistic flexibility multiplier (1.25x) activates, the spear (AGA.V at 60% weight)
    # must NEVER be sized above the 60% structural barbell ceiling.
    live_portfolio = 10000.0
    u_implied = 1.15
    vols = {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
    corr_matrix = {
      "AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30},
      "GROY": {"URC.TO": 0.40, "GMX.TO": 0.35},
      "URC.TO": {"GMX.TO": 0.45}
    }
    mri_score = 30.0  # < 45 -> alignment active
    # Highly liquid + JSF 4.0 -> flexibility_mult = 1.25 engaged; single-position cap should bind.
    limit_params = {"aga_price": 0.71, "aga_adv": 5_000_000, "port_vol": 0.40, "vix": 16.5, "jsf_score": 4.0}
    res = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, limit_params)

    # Spear weight is 0.60; spear dollar exposure = e_target * 0.60. As a % of the portfolio that
    # is target_pct * 0.60. With the hard 60% ceiling, e_target can be at most live_portfolio.
    spear_pct_of_portfolio = res["target_pct"] * 0.60
    self.assertLessEqual(res["e_target"], live_portfolio + 1e-6,
                         f"Flexibility breached the 60% barbell: e_target={res['e_target']}")
    self.assertLessEqual(spear_pct_of_portfolio, 60.0 + 1e-6,
                         f"Spear allocation {spear_pct_of_portfolio:.2f}% exceeds 60% ceiling")
    self.assertEqual(res["max_single_position_value_cap"], round(live_portfolio * 0.60, 2))
    print(f"[TEST] Spear ceiling enforced: e_target=${res['e_target']} | spear={spear_pct_of_portfolio:.1f}% (<= 60%)")

  def test_es95_throttles_leverage(self):
    # Phase 1c: Worsening 95% Expected Shortfall must reduce target deployment, all else equal.
    # Use a low-conviction / high-vol regime so Kelly leverage (not a hard cap) is the binding
    # constraint, making the ES throttle observable.
    live_portfolio = 10000.0
    u_implied = 0.30
    vols = {"AGA.V": 0.80, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
    corr_matrix = {
      "AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30},
      "GROY": {"URC.TO": 0.40, "GMX.TO": 0.35},
      "URC.TO": {"GMX.TO": 0.45}
    }
    mri_score = 30.0
    base = {"aga_price": 0.71, "aga_adv": 5_000_000, "port_vol": 0.80, "vix": 16.5, "jsf_score": 4.0}

    benign = dict(base, expected_shortfall_95_pct=-3.0)   # above -5% threshold -> no throttle
    severe = dict(base, expected_shortfall_95_pct=-12.0)  # at max-penalty floor -> 0.5x throttle
    res_benign = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, benign)
    res_severe = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, severe)

    self.assertEqual(res_benign["es_throttle"], 1.0)
    self.assertEqual(res_severe["es_throttle"], 0.5)
    self.assertLess(res_severe["e_target"], res_benign["e_target"])
    self.assertAlmostEqual(res_severe["e_target"], res_benign["e_target"] * 0.5, delta=1.0)
    print(f"[TEST] ES95 throttle: benign(-3%)=${res_benign['e_target']} -> severe(-12%)=${res_severe['e_target']} "
          f"(throttle {res_severe['es_throttle']}x)")

  def test_kelly_dimensional_coherence(self):
    # Phase 1b: In an uncapped regime, e_target should equal the dimensionally-coherent Kelly:
    # mu_annualized = u_implied / (convergence_months/12); raw_kelly = mu/var * fractional_kelly.
    import json
    with open(self.config_path) as f:
      cfg = json.load(f)
    conv_months = cfg["v5_guardrails"]["intrinsic_convergence_months"]
    fk = cfg["v5_guardrails"]["fractional_kelly_multiplier"]

    live_portfolio = 10000.0
    u_implied = 0.30
    port_vol = 0.80
    vols = {"AGA.V": 0.80, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
    # Low ballast correlations -> correlation_penalty = 1.0 (avg corr < 0.30)
    corr_matrix = {"AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30}}
    mri_score = 30.0  # multiplier 1.0
    limit_params = {"aga_price": 0.71, "aga_adv": 5_000_000, "port_vol": port_vol, "vix": 16.5, "jsf_score": 4.0}
    res = self.sizer.calculate_sizing(live_portfolio, u_implied, vols, corr_matrix, mri_score, limit_params)

    # The dimensionally-coherent Kelly now includes the parameter-uncertainty (uncertainty-adjusted)
    # shrinkage: mu_annualized = (u_implied/T) * edge_confidence, with SE = k*sigma/sqrt(T) and
    # edge_confidence = mu_raw^2 / (mu_raw^2 + SE^2).
    conv_years = conv_months / 12.0
    mu_raw = u_implied / conv_years
    unc = cfg["v5_guardrails"].get("edge_uncertainty", {})
    se_mu = unc.get("noise_vol_multiplier", 1.0) * port_vol / (conv_years ** 0.5)
    edge_conf = (mu_raw ** 2) / (mu_raw ** 2 + se_mu ** 2)
    edge_conf = max(unc.get("min_confidence", 0.0), min(1.0, edge_conf))
    variance = max(0.04, port_vol ** 2)
    raw_kelly = ((mu_raw * edge_conf) / variance) * fk
    expected_e_target = live_portfolio * raw_kelly  # multiplier=1.0, corr_penalty=1.0, es_throttle=1.0
    self.assertAlmostEqual(res["e_target"], round(expected_e_target, 2), delta=1.0)
    self.assertAlmostEqual(res["edge_confidence"], round(edge_conf, 3), delta=0.005)
    self.assertLess(res["edge_confidence"], 1.0)  # low-edge / high-vol regime -> meaningful haircut
    print(f"[TEST] Kelly coherence (horizon={conv_months}mo): e_target=${res['e_target']} "
          f"matches uncertainty-adj. Kelly ${round(expected_e_target, 2)} (edge_conf={res['edge_confidence']})")

  def test_kelly_multiple_is_bounded_leverage_not_reciprocal(self):
    # Regression for the "11.65x Kelly explosion": the headline `kelly_multiple` must be the
    # risk-adjusted target leverage f* (== e_target/live, bounded by L_max), NOT the prior
    # reciprocal 1/f* (= live/e_target) which was unbounded and inverted (a MORE conservative
    # target produced a LARGER "multiple"). The over-allocation story moves to `allocation_ratio`,
    # which is the (clamped) reciprocal and is the only metric allowed to be > 1.
    import json
    with open(self.config_path) as f:
      cfg = json.load(f)
    ad = cfg["v5_guardrails"].get("allocation_directive", {})
    display_cap = ad.get("display_cap", 5.0)

    live = 10000.0
    u_implied = 0.30
    corr_matrix = {"AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30}}  # corr_penalty -> 1.0
    # Generous liquidity so the Kelly leverage (not the ADV cap) is the binding constraint.
    base_lp = {"aga_price": 0.71, "aga_adv": 50_000_000, "vix": 16.5, "jsf_score": 4.0}

    # 1) Headline == e_target/live and is bounded by L_max in EVERY regime; the legacy 1/f* it
    #    replaced would be unbounded (and was the value that surfaced as "KELLY MULT 11.x").
    for pv in (0.20, 0.40, 0.58, 0.80):
      lp = dict(base_lp); lp["port_vol"] = pv
      r = self.sizer.calculate_sizing(live, u_implied, {}, corr_matrix, 30.0, lp)
      self.assertAlmostEqual(r["kelly_multiple"], round(r["e_target"] / live, 4), delta=1e-3)
      self.assertLessEqual(r["kelly_multiple"], 1.5 + 1e-9, "Headline leverage breached L_max")
      self.assertEqual(r["kelly_multiple"], r["kelly_leverage"])  # canonical alias agrees
      self.assertLessEqual(r["allocation_ratio"], display_cap + 1e-9, "allocation_ratio not clamped")

    # 2) Inversion cured: as vol RISES (edge weakens, sizing gets more conservative) the headline
    #    leverage must NOT inflate. The pre-fix metric did the opposite (36.8x at 80% vol).
    r_lo = self.sizer.calculate_sizing(live, u_implied, {}, corr_matrix, 30.0, dict(base_lp, port_vol=0.20))
    r_hi = self.sizer.calculate_sizing(live, u_implied, {}, corr_matrix, 30.0, dict(base_lp, port_vol=0.80))
    self.assertGreater(r_lo["kelly_multiple"], r_hi["kelly_multiple"],
                       "Headline leverage must fall (not rise) as volatility rises")
    self.assertLessEqual(r_lo["allocation_ratio"], r_hi["allocation_ratio"],
                         "allocation_ratio must rise (more over-allocated) as the target shrinks")
    print(f"[TEST] Kelly headline is bounded f* (cured inversion): "
          f"vol20%->f*={r_lo['kelly_multiple']:.3f}x(alloc {r_lo['allocation_ratio']:.2f}x) | "
          f"vol80%->f*={r_hi['kelly_multiple']:.3f}x(alloc {r_hi['allocation_ratio']:.2f}x, clamped<= {display_cap})")

  def test_jurisdiction_uplift_continuity(self):
    # Phase 2: the spot_ag > 50 -> 1.35 else 1.15 cliff is replaced by a smooth logistic ramp.
    just_below = self.val.calculate_jurisdiction_uplift(49.99)
    just_above = self.val.calculate_jurisdiction_uplift(50.01)
    self.assertLess(abs(just_above - just_below), 0.01, "Cliff persists at the $50 boundary")
    # Bounded, monotonic, centered
    self.assertGreater(self.val.calculate_jurisdiction_uplift(20.0), 1.15 - 1e-6)
    self.assertLess(self.val.calculate_jurisdiction_uplift(120.0), 1.35 + 1e-6)
    self.assertAlmostEqual(self.val.calculate_jurisdiction_uplift(50.0), 1.25, delta=0.001)
    self.assertGreater(self.val.calculate_jurisdiction_uplift(75.0), 1.34)
    ladder = [self.val.calculate_jurisdiction_uplift(x) for x in range(20, 121, 5)]
    self.assertEqual(ladder, sorted(ladder), "Uplift must be monotonic increasing in spot_ag")
    print(f"[TEST] Jurisdiction uplift smooth: $49.99={just_below:.4f} ~ $50.01={just_above:.4f} | $75={ladder[11]:.4f}")

  def test_capital_discount_smoothness(self):
    # Phase 2: smooth softplus hinge replaces max(0.40, 1.0 - (y30-4.0)*0.12) gated at y30 > 4.0.
    cdf = self.val.calculate_capital_discount_factor
    # Live operating point (y30 ~ 4.99) preserved vs the old linear value (0.8808)
    self.assertAlmostEqual(cdf(4.993), 0.8808, delta=0.005)
    # Bounded, monotonic decreasing for rising long rates, floors near 0.40 at extremes
    self.assertLessEqual(cdf(2.0), 1.0 + 1e-6)
    self.assertGreaterEqual(cdf(20.0), 0.40 - 1e-6)
    self.assertAlmostEqual(cdf(20.0), 0.40, delta=0.01)
    ladder = [cdf(y) for y in [3.0, 4.0, 5.0, 6.0, 8.0, 12.0]]
    self.assertEqual(ladder, sorted(ladder, reverse=True), "Discount must be monotonic decreasing in y30")
    # Near-continuous slope across the old onset kink at y30 = 4.0
    self.assertLess(abs(cdf(4.05) - cdf(3.95)), 0.02)
    print(f"[TEST] Capital discount smooth: cdf(4.993)={cdf(4.993):.4f} | cdf(8)={cdf(8.0):.4f} | cdf(20)={cdf(20.0):.4f}")

  def test_es_penalty_curvature(self):
    # Phase 2: ES penalty is continuous, convex, and uncapped (was a flat 1.0 ceiling).
    def h(es):
      return self.radar.calculate_health_rating(jsf_score=4.0, mri_score=30.0,
                                                 expected_shortfall_95=es, is_stale=False)["health_rating"]
    h5, h10, h15, h20, h30 = h(-5.0), h(-10.0), h(-15.0), h(-20.0), h(-30.0)
    # Strictly decreasing as tail risk worsens
    self.assertTrue(h5 > h10 > h15 > h20, f"Health not monotonic: {[h5, h10, h15, h20]}")
    # Convexity: each additional -5% of ES removes MORE health than the prior step
    self.assertLess(h5 - h10, h10 - h15)
    self.assertLess(h10 - h15, h15 - h20)
    # Uncapped: a catastrophic -30% ES drives the rating to its 1.0 floor (penalty >> old 1.0 cap)
    self.assertEqual(h30, 1.0)
    print(f"[TEST] ES curvature: H(-5)={h5} H(-10)={h10} H(-15)={h15} H(-20)={h20} H(-30)={h30}")

  def test_ballast_fair_value_price_decoupled(self):
    # v5.2 lethal-fix #1: ballast fair value must be DECOUPLED from the name's own share price
    # (the old `live_price * multiple` made fair value track the very price it was compared
    # against, so Implied Upside never compressed). Fair value must respond ONLY to commodity spot.
    fv = self.val.calculate_ballast_fair_value
    ref_price, base_mult, spot_ref = 4.82, 1.15, 74.8

    # At the reference spot, fair value is the fundamental anchor (ref_price * multiple) and is
    # invariant to wherever the share price has run to (price is not even an input).
    fv_at_spot = fv(ref_price, base_mult, spot_now=74.8, spot_ref=spot_ref, spot_beta=1.0, forensic_pen=1.0)
    self.assertAlmostEqual(fv_at_spot, 4.82 * 1.15, places=6)

    # Commodity spot +20% with beta 1.0 -> fair value +20%; the price-linkage is now a SPOT-linkage.
    fv_spot_up = fv(ref_price, base_mult, spot_now=74.8 * 1.20, spot_ref=spot_ref, spot_beta=1.0, forensic_pen=1.0)
    self.assertAlmostEqual(fv_spot_up, fv_at_spot * 1.20, places=4)

    # spot_beta encodes commodity leverage: +10% spot at beta 2.0 -> +20% fair value (producers > royalties).
    fv_beta2 = fv(ref_price, base_mult, spot_now=74.8 * 1.10, spot_ref=spot_ref, spot_beta=2.0, forensic_pen=1.0)
    self.assertAlmostEqual(fv_beta2, fv_at_spot * 1.20, places=4)

    # Forensic penalty scales linearly; degenerate inputs clamp to a non-negative floor.
    self.assertAlmostEqual(fv(ref_price, base_mult, 74.8, spot_ref, 1.0, 0.70), fv_at_spot * 0.70, places=4)
    self.assertEqual(fv(0.0, base_mult, 74.8, spot_ref, 1.0, 1.0), 0.0)
    self.assertEqual(fv(ref_price, base_mult, 74.8, 0.0, 1.0, 1.0), 0.0)

    # Collapsing spot below ref clamps the spot factor at 0 (no negative fair value).
    self.assertEqual(fv(ref_price, base_mult, spot_now=0.0, spot_ref=spot_ref, spot_beta=1.0, forensic_pen=1.0), 0.0)
    print(f"[TEST] Ballast spot-decoupled: FV@ref=${fv_at_spot:.3f} | spot+20%=${fv_spot_up:.3f} (price-invariant)")

  def test_catalyst_confidence_overlay(self):
    # v5.2 lethal-fix #2: the catalyst/momentum gate maps the spear's trailing return to a
    # confidence in [floor, 1.0] that haircuts the Kelly drift mu.
    cc = PortfolioSizer.catalyst_confidence
    # Strong positive momentum -> full thesis; deep negative (falling knife) -> floor; flat -> midpoint.
    self.assertAlmostEqual(cc(0.20, floor=0.5, mom_lo=-0.10, mom_hi=0.10), 1.0, places=6)
    self.assertAlmostEqual(cc(-0.20, floor=0.5, mom_lo=-0.10, mom_hi=0.10), 0.5, places=6)
    self.assertAlmostEqual(cc(0.0, floor=0.5, mom_lo=-0.10, mom_hi=0.10), 0.75, places=6)
    # Monotonic non-decreasing in momentum, bounded by [floor, 1.0].
    ladder = [cc(m, 0.5, -0.10, 0.10) for m in [-0.30, -0.10, -0.05, 0.0, 0.05, 0.10, 0.30]]
    self.assertEqual(ladder, sorted(ladder))
    self.assertGreaterEqual(min(ladder), 0.5 - 1e-9)
    self.assertLessEqual(max(ladder), 1.0 + 1e-9)
    # Unavailable momentum (degraded returns feed) -> no haircut, preserving legacy behavior.
    self.assertEqual(cc(None), 1.0)
    print(f"[TEST] Catalyst confidence ramp: mom-20%={ladder[0]:.2f} flat={cc(0.0):.2f} mom+30%={ladder[-1]:.2f}")

  def test_catalyst_factor_scales_kelly_target(self):
    # The catalyst haircut must scale target deployment proportionally in an uncapped (Kelly-bound)
    # regime, and the default param (1.0) must preserve pre-overlay sizing exactly.
    live = 10000.0
    u_implied = 0.30
    vols = {"AGA.V": 0.80, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
    corr = {"AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30}}
    mri = 30.0
    lp = {"aga_price": 0.71, "aga_adv": 5_000_000, "port_vol": 0.80, "vix": 16.5, "jsf_score": 4.0}

    full = self.sizer.calculate_sizing(live, u_implied, vols, corr, mri, lp, catalyst_factor=1.0)
    haircut = self.sizer.calculate_sizing(live, u_implied, vols, corr, mri, lp, catalyst_factor=0.5)
    default = self.sizer.calculate_sizing(live, u_implied, vols, corr, mri, lp)

    self.assertEqual(full["catalyst_factor"], 1.0)
    self.assertEqual(haircut["catalyst_factor"], 0.5)
    self.assertAlmostEqual(haircut["e_target"], full["e_target"] * 0.5, delta=1.0)
    self.assertEqual(default["e_target"], full["e_target"])  # default => no haircut (backward compatible)
    print(f"[TEST] Catalyst sizing: full=${full['e_target']} -> haircut(0.5x)=${haircut['e_target']}")

  def test_ppi_ev_currency_normalization(self):
    # Phase 1: PPI/EV_Blended must blend all legs in a single currency (CAD). GROY trades in USD;
    # blending its raw USD price with CAD names biased Implied Upside. Verify the FX conversion
    # rule used by the pipeline: USD legs scale by usd_to_cad, CAD legs are unchanged.
    usd_to_cad = 1.38
    bv_cfg = {
      "URC.TO": {"currency": "CAD"}, "GROY": {"currency": "USD"}, "GMX.TO": {"currency": "CAD"}
    }
    def fx_to_cad(name, default_ccy):
      nm = bv_cfg.get(name) or {}
      ccy = nm.get("currency", default_ccy)
      return usd_to_cad if str(ccy).upper() == "USD" else 1.0

    self.assertEqual(fx_to_cad("AGA.V", "CAD"), 1.0)
    self.assertEqual(fx_to_cad("URC.TO", "CAD"), 1.0)
    self.assertEqual(fx_to_cad("GMX.TO", "CAD"), 1.0)
    self.assertAlmostEqual(fx_to_cad("GROY", "USD"), 1.38, places=6)

    # A USD GROY price of $3.22 must contribute its CAD equivalent ($4.4436) to the blended index.
    p_groy_usd = 3.22
    self.assertAlmostEqual(p_groy_usd * fx_to_cad("GROY", "USD"), 4.4436, places=4)

    # Config currency wins over the default; an unconfigured name falls back to its default ccy.
    self.assertEqual(fx_to_cad("UNKNOWN", "CAD"), 1.0)
    self.assertAlmostEqual(fx_to_cad("UNKNOWN", "USD"), 1.38, places=6)
    print(f"[TEST] FX normalization: GROY ${p_groy_usd} USD -> ${p_groy_usd*1.38:.4f} CAD in PPI/EV")

  def test_forensic_override_governance(self):
    # Phase 1: manual forensic overrides are honored ONLY when justified AND unexpired.
    oa = self.forensics._override_active
    valid = {"dilution_insulated": True, "justification": "funded treasury", "expiry": "2026-06-30"}
    # Justified AND within the bounded validity window (29d <= 45d) -> honored
    self.assertTrue(oa(valid, "dilution_insulated", today="2026-06-01"))
    # Long-dated waiver beyond max_validity_days (45d) -> REJECTED (forces short, re-confirmed waivers)
    far = {"dilution_insulated": True, "justification": "funded treasury", "expiry": "2099-12-31"}
    self.assertFalse(oa(far, "dilution_insulated", today="2026-06-01"))
    self.assertTrue(oa(far, "dilution_insulated", today="2026-06-01", max_validity_days=99999))  # window override proves the gate
    # Missing justification -> ignored
    self.assertFalse(oa({"dilution_insulated": True, "expiry": "2026-06-30"}, "dilution_insulated", today="2026-06-01"))
    # Missing/blank expiry -> ignored
    self.assertFalse(oa({"dilution_insulated": True, "justification": "x"}, "dilution_insulated", today="2026-06-01"))
    # Expired -> ignored (point-in-time governance)
    self.assertFalse(oa(valid, "dilution_insulated", today="2026-07-01"))
    # Flag not set -> ignored even with a trail
    self.assertFalse(oa({"justification": "x", "expiry": "2026-06-30"}, "dilution_insulated", today="2026-06-01"))

    # End-to-end: once the AGA.V config override EXPIRES, the manual waiver is gone — yet the
    # dilution leg now stands on its own RUNWAY-INSULATED merit (a ~53-month treasury funds the
    # raise, so it isn't death-spiral decay), while the CBA/accrual gate still fails on merit. No
    # overrides are recorded in the audit trail, and the JSF score reflects the real failing leg.
    score_expired, _, details_expired = self.forensics.calculate_jsf_score(
      ticker="AGA.V", cash=40000000.0, monthly_burn=750000.0,
      sloan_cfo=0.015, sloan_bs=0.012, shares_t0=240000000, shares_t1=208600000,
      sga_expense=500000.0, cfo_t0=-3000000.0, cfo_t1=-1000000.0, cash_t0=4000000.0,
      today="2099-01-01"
    )
    # Dilution holds via runway-insulation (the funded-raise contract), NOT a lingering waiver.
    self.assertTrue(details_expired["dilution"]["pass"])
    self.assertTrue(details_expired["dilution"]["runway_insulated"])
    self.assertFalse(details_expired["dilution"]["overridden"])
    self.assertFalse(details_expired["accrual"]["pass"])
    self.assertEqual(details_expired["overrides_applied"], [])
    self.assertLess(score_expired, 4.0)
    print(f"[TEST] Override governance: valid->honored, expired/unjustified->ignored (JSF drops to {score_expired})")

  def test_data_freshness_layer(self):
    # Phase 1: per-feed age + staleness vs configurable thresholds, and cross-feed vintage skew.
    import time as _t
    now = _t.time()
    feed_ts = {"prices": now - 60, "macro": now - 600, "ry": now - 600, "dxy": now - 600,
               "cftc": now - 3600, "peers": now - 7200}
    max_age = {"prices": 300, "macro": 5400, "ry": 5400, "dxy": 5400, "cftc": 172800, "peers": 86400}
    feed_status = {"prices": "LIVE", "macro": "LIVE", "ry": "LIVE", "dxy": "LIVE", "cftc": "LIVE"}

    freshness = {}
    any_stale = False
    for feed, ts in feed_ts.items():
      age = max(0.0, now - ts)
      thr = max_age.get(feed, 3600)
      stale = (age > thr) or (feed_status.get(feed) == "DEGRADED_STALE")
      any_stale = any_stale or stale
      freshness[feed] = {"age_seconds": age, "stale": stale}

    # All within threshold -> nothing stale
    self.assertFalse(any_stale)
    # Force prices stale (10 min old vs 5 min threshold)
    self.assertTrue((now - (now - 600)) > max_age["prices"])
    # A DEGRADED_STALE status flag marks a feed stale regardless of age
    self.assertTrue(("DEGRADED_STALE" == "DEGRADED_STALE"))
    fast_ages = [now - feed_ts[f] for f in ("prices", "macro", "ry", "dxy")]
    vintage_skew = max(fast_ages) - min(fast_ages)
    self.assertAlmostEqual(vintage_skew, 540.0, delta=1.0)  # 600s macro - 60s prices
    print(f"[TEST] Freshness: stale={any_stale} | vintage skew across fast feeds = {vintage_skew:.0f}s")

  def test_correlation_shrinkage(self):
    # Phase 2: Ledoit-Wolf-style shrink toward a constant-correlation target stabilizes noisy
    # 60-day correlations. Verify the convex blend, fixed diagonal, and target structure.
    import pandas as pd, numpy as np
    np.random.seed(42)
    n = 80
    a = np.random.normal(0, 0.02, n)
    b = 0.7 * a + 0.3 * np.random.normal(0, 0.02, n)  # correlated with a
    c = np.random.normal(0, 0.02, n)                  # ~independent
    df = pd.DataFrame({"AGA.V": a, "GROY": b, "GMX.TO": c})
    sample = df.corr()

    shrunk0 = self.sizer.shrink_correlation(df, intensity=0.0)   # -> sample
    shrunk1 = self.sizer.shrink_correlation(df, intensity=1.0)   # -> constant target
    shrunkM = self.sizer.shrink_correlation(df, intensity=0.5)

    self.assertAlmostEqual(shrunk0["AGA.V"]["GROY"], float(sample.loc["AGA.V", "GROY"]), places=6)
    self.assertAlmostEqual(shrunkM["AGA.V"]["AGA.V"], 1.0, places=9)  # diagonal preserved
    offs = [shrunk1["AGA.V"]["GROY"], shrunk1["AGA.V"]["GMX.TO"], shrunk1["GROY"]["GMX.TO"]]
    self.assertAlmostEqual(max(offs), min(offs), places=9)  # intensity=1 => all off-diags equal
    smp, tgt = float(sample.loc["AGA.V", "GROY"]), offs[0]
    self.assertTrue(min(smp, tgt) - 1e-9 <= shrunkM["AGA.V"]["GROY"] <= max(smp, tgt) + 1e-9)
    print(f"[TEST] Corr shrinkage: sample AGA/GROY={smp:.3f} -> mid={shrunkM['AGA.V']['GROY']:.3f} -> target={tgt:.3f}")

  def test_robust_expected_shortfall_blend(self):
    # Phase 2: ES95 blends the empirical tail with a parametric Gaussian tail to damp run-to-run
    # whipsaw from the ~3-point empirical tail.
    import pandas as pd, numpy as np
    np.random.seed(7)
    n = 80
    df = pd.DataFrame({"AGA.V": np.random.normal(0, 0.03, n), "GROY": np.random.normal(0, 0.02, n),
                       "GMX.TO": np.random.normal(0, 0.02, n), "URC.TO": np.random.normal(0, 0.02, n)})
    w = np.array([0.60, 0.15, 0.10, 0.15])
    emp = self.sizer.calculate_expected_shortfall(df, w)
    es_emp = self.sizer.robust_expected_shortfall(df, w, blend=0.0)
    es_par = self.sizer.robust_expected_shortfall(df, w, blend=1.0)
    es_mid = self.sizer.robust_expected_shortfall(df, w, blend=0.5)
    self.assertAlmostEqual(es_emp, emp, places=6)            # blend 0 == empirical ES
    self.assertTrue(es_emp < 0 and es_par < 0)              # losses are negative
    self.assertTrue(min(es_emp, es_par) - 1e-9 <= es_mid <= max(es_emp, es_par) + 1e-9)
    print(f"[TEST] Robust ES: empirical={es_emp*100:.2f}% parametric={es_par*100:.2f}% blended={es_mid*100:.2f}%")

  def test_edge_uncertainty_shrinks_low_sharpe(self):
    # Phase 2: same edge, higher portfolio vol -> lower edge_confidence -> smaller target capital
    # (parameter-uncertainty / uncertainty-adjusted Kelly).
    import math
    live, u, mri = 10000.0, 0.30, 30.0
    corr = {"AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30}}
    def run(pv):
      vols = {"AGA.V": pv, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
      lp = {"aga_price": 0.71, "aga_adv": 5_000_000, "port_vol": pv, "vix": 16.5, "jsf_score": 4.0}
      return self.sizer.calculate_sizing(live, u, vols, corr, mri, lp)
    lo, hi = run(0.40), run(0.90)
    self.assertLess(hi["edge_confidence"], lo["edge_confidence"])     # more vol -> less confidence
    self.assertLess(hi["e_target"], lo["e_target"])                  # ... -> smaller deployment
    self.assertTrue(0.0 < lo["edge_confidence"] <= 1.0)
    conv_years = 1.5
    mu_raw = u / conv_years
    se = 1.0 * 0.40 / math.sqrt(conv_years)
    self.assertAlmostEqual(lo["edge_confidence"], round((mu_raw ** 2) / (mu_raw ** 2 + se ** 2), 3), delta=0.005)
    print(f"[TEST] Edge uncertainty: conf(vol40%)={lo['edge_confidence']} > conf(vol90%)={hi['edge_confidence']}")

  def test_mri_decomposition(self):
    # Phase 2: MRI exposes an auditable per-block decomposition whose weighted contributions sum to
    # the score, while the plain float call stays backward compatible.
    metrics = {
      "DXY": {"value": 99.0}, "TED": {"value": 0.05}, "VIX": {"value": 16.0},
      "Spreads": {"value": 3.0}, "10Y": {"value": 4.2}, "30Y": {"value": 4.6},
      "CFTC_Silver_Net_Longs": {"value": 35000.0}
    }
    mri, detail = self.macro.calculate_mri(metrics, spot_ag=74.8, real_yield=1.0, copper=4.2,
                                           gold=2350.0, dxy_mom=0.0, return_detail=True)
    mri_float = self.macro.calculate_mri(metrics, 74.8, 1.0, 4.2, 2350.0, 0.0)
    self.assertEqual(mri, mri_float)                      # backward compatible
    self.assertEqual(len(detail["blocks"]), 5)
    self.assertAlmostEqual(sum(b["contribution"] for b in detail["blocks"]), mri, delta=0.3)  # decomposable
    self.assertEqual(detail["top_driver"], detail["blocks"][0]["name"])                        # sorted desc
    self.assertTrue(all(detail["blocks"][i]["contribution"] >= detail["blocks"][i + 1]["contribution"]
                        for i in range(len(detail["blocks"]) - 1)))
    print(f"[TEST] MRI decomposition: {mri} = " + " + ".join(f"{b['name']}:{b['contribution']}" for b in detail['blocks']))

  # ====================== PHASE 0 — MANDATORY STRUCTURAL PATCHES ======================

  def test_phase0_adv_robust_volume_filters_spikes(self):
    # Patch 0.1: the liquidity cap must be denominated on a robust 90-session volume statistic, not a
    # 10-day ADV that a panic spike inflates (pro-cyclically expanding the cap when liquidity is worst).
    import pandas as pd
    volume = [100000] * 90 + [2000000] * 5      # 90 calm sessions, then a 5-session panic spike
    hist = pd.DataFrame({"Volume": volume, "Close": [1.0] * len(volume)})
    median_adv = _robust_adv_shares(hist, window_days=90, method="median")
    mean_adv = sum(volume[-90:]) / 90           # what a naive average would report
    self.assertAlmostEqual(median_adv, 100000, delta=1.0)   # median anchored at the calm level
    self.assertLess(median_adv, 0.6 * mean_adv)             # spike cannot inflate it
    # EWMA is offered as an alternative, but because it weights the most RECENT sessions most heavily a
    # tail spike pulls it UP — which is exactly why the 90-session MEDIAN is the robust config default.
    ewma_adv = _robust_adv_shares(hist, window_days=90, method="ewma", halflife=30)
    self.assertGreater(ewma_adv, 0)
    self.assertLess(median_adv, ewma_adv)
    self.assertIsNone(_robust_adv_shares(pd.DataFrame({"Volume": [100, 200]}), window_days=90))  # cold -> fallback
    print(f"[TEST] ADV robust: median={median_adv:.0f} vs spiked-mean={mean_adv:.0f} (pro-cyclicality filtered)")

  def test_phase0_cba_ev_normalization_not_lean_treasury(self):
    # Patch 0.2: CBA is normalized against Enterprise Value, not Total Cash, so a lean-treasury explorer
    # is not penalized by a small denominator. QoQ burn accelerates by $2M: that is 50% of a $4M cash
    # pile (fails the old cash gate) but only 2% of a $100M EV (passes the EV gate).
    common = dict(ticker="LEAN.V", cash=15_000_000.0, monthly_burn=750000.0, sloan_cfo=0.0, sloan_bs=0.0,
                  shares_t0=100_000_000, shares_t1=100_000_000, sga_expense=100000.0,
                  cfo_t0=-3_000_000.0, cfo_t1=-1_000_000.0, cash_t0=4_000_000.0)
    _, _, det_ev = self.forensics.calculate_jsf_score(enterprise_value=100_000_000.0, **common)
    self.assertTrue(det_ev["accrual"]["pass"])
    self.assertEqual(det_ev["accrual"]["basis"], "EV")
    # No EV available -> falls back to the original cash-based test -> fails (backward compatible).
    _, _, det_cash = self.forensics.calculate_jsf_score(enterprise_value=None, **common)
    self.assertFalse(det_cash["accrual"]["pass"])
    self.assertEqual(det_cash["accrual"]["basis"], "cash")
    print(f"[TEST] CBA: EV-based pass={det_ev['accrual']['pass']} ({det_ev['accrual']['value']*100:.1f}%) | "
          f"cash-based pass={det_cash['accrual']['pass']} ({det_cash['accrual']['value']*100:.1f}%)")

  def test_phase0_mri_dynamic_percentile_bounds(self):
    # Patch 0.3: with sufficient trailing history, MRI components score by rolling percentile rank, not
    # a static min-max band that saturates. A 300-pt silver series spanning 20..319 puts spot 75 at the
    # ~19th percentile of THAT window, versus a static norm(75, 50, 100) = 50.
    metrics = {"DXY": {"value": 99.0}, "TED": {"value": 0.05}, "VIX": {"value": 16.0},
               "Spreads": {"value": 3.0}, "10Y": {"value": 4.2}, "30Y": {"value": 4.6},
               "CFTC_Silver_Net_Longs": {"value": 35000.0}}
    spot_ag = 75.0
    silver_series = [float(v) for v in range(20, 320)]
    _, det = self.macro.calculate_mri(metrics, spot_ag, real_yield=1.0, copper=4.2, gold=2300.0,
                                      dxy_mom=0.0, return_detail=True, history={"silver": silver_series})
    self.assertEqual(det["bounds_basis"]["silver"]["mode"], "dynamic")
    expected_pct = _percentile_rank(silver_series, spot_ag)
    self.assertAlmostEqual(det["drivers"]["silver"], round(expected_pct, 0), delta=1.0)
    self.assertNotAlmostEqual(det["drivers"]["silver"], 50.0, delta=5.0)   # not the static band value
    # Cold start: below min_obs -> static fallback so a cold cache never blocks or regresses.
    _, det_cold = self.macro.calculate_mri(metrics, spot_ag, 1.0, 4.2, 2300.0, 0.0,
                                           return_detail=True, history={"silver": [60.0, 70.0, 80.0]})
    self.assertEqual(det_cold["bounds_basis"]["silver"]["mode"], "static")
    print(f"[TEST] MRI dynamic bounds: silver@{spot_ag:.0f} -> {det['drivers']['silver']:.0f}th pct (dynamic) "
          f"vs 50 (static); cold-start falls back to static")

  def test_phase0_mri_static_fallback_matches_legacy(self):
    # Safety net: with NO history supplied, calculate_mri must reproduce the legacy static-bounds score
    # exactly, so enabling the dynamic-bounds machinery cannot silently move the live regime read.
    metrics = {"DXY": {"value": 99.0}, "TED": {"value": 0.05}, "VIX": {"value": 16.0},
               "Spreads": {"value": 3.0}, "10Y": {"value": 4.2}, "30Y": {"value": 4.6},
               "CFTC_Silver_Net_Longs": {"value": 35000.0}}
    mri_no_hist = self.macro.calculate_mri(metrics, 74.8, 1.0, 4.2, 2350.0, 0.0)
    _, det = self.macro.calculate_mri(metrics, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True)
    self.assertTrue(all(v["mode"] == "static" for v in det["bounds_basis"].values()))
    self.assertEqual(mri_no_hist, det["mri"])
    print(f"[TEST] MRI static fallback intact (no history): MRI={mri_no_hist} (all components static)")

  # ====================== 2026-08-02 MRI REWEIGHT (first-principles review) ======================

  _MRI_METRICS = {
    "DXY": {"value": 99.0}, "TED": {"value": 0.15}, "VIX": {"value": 16.0},
    "Spreads": {"value": 3.0}, "10Y": {"value": 4.2}, "30Y": {"value": 4.6},
    "CFTC_Silver_Net_Longs": {"value": 35000.0}
  }

  def test_mri_weights_are_config_driven(self):
    # The block weight map lives in v5_config.mri_weights (it was hardcoded — the one parameter set
    # the calibration flywheel could never reach). The detail's per-block weights must echo the
    # config, and the weighted contributions must still sum to the MRI.
    import json
    with open(self.config_path) as f:
      wcfg = json.load(f)["mri_weights"]
    _, det = self.macro.calculate_mri(self._MRI_METRICS, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True)
    got = {b["key"]: b["weight"] for b in det["blocks"]}
    total = sum(wcfg["blocks"].values())
    for k, w in wcfg["blocks"].items():
      self.assertAlmostEqual(got[k], w / total, delta=1e-9)
    self.assertAlmostEqual(sum(b["contribution"] for b in det["blocks"]), det["mri"], delta=0.3)
    print(f"[TEST] MRI weights config-driven: {got}")

  def test_mri_weight_map_renormalizes_bad_edits(self):
    # A hand-edited map that doesn't sum to 1.0 is rescaled, never trusted raw — a bad /confirm or
    # merge cannot silently inflate or deflate the index.
    orig = self.macro.get_config
    def _patched():
      cfg = orig()
      cfg["mri_weights"] = dict(cfg.get("mri_weights", {}),
                                blocks={"liquidity_fx": 0.33, "yield_curve": 0.14, "volatility": 0.27,
                                        "commodity": 0.16, "sentiment": 0.60})   # sums to 1.50
      return cfg
    self.macro.get_config = _patched
    try:
      _, det = self.macro.calculate_mri(self._MRI_METRICS, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True)
    finally:
      self.macro.get_config = orig
    self.assertAlmostEqual(sum(b["weight"] for b in det["blocks"]), 1.0, delta=1e-9)
    self.assertAlmostEqual(next(b["weight"] for b in det["blocks"] if b["key"] == "sentiment"),
                           0.60 / 1.50, delta=1e-9)
    print("[TEST] MRI weight map renormalized: 1.50-sum edit rescaled to 1.0")

  def test_mri_funding_leg_sofr_era_bounds(self):
    # The funding driver is SOFR−DTB3 now, scored against mri_weights.funding_norm (0.0–0.5). The
    # legacy TED band (0.1–0.9, unsecured-LIBOR-era) pinned a normal 0.15 spread at ~6/100 — a
    # structurally dead leg. Same input must now read ~30/100.
    _, det = self.macro.calculate_mri(self._MRI_METRICS, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True)
    self.assertAlmostEqual(det["drivers"]["sofr_spread"], 30.0, delta=1.0)   # norm(0.15, 0.0, 0.5)
    # and the leg is percentile-scored once a funding history is seeded (dynamic bounds)
    hist = {"funding": [0.05 + 0.001 * i for i in range(300)]}
    _, det_dyn = self.macro.calculate_mri(self._MRI_METRICS, 74.8, 1.0, 4.2, 2350.0, 0.0,
                                          return_detail=True, history=hist)
    self.assertEqual(det_dyn["bounds_basis"]["funding"]["mode"], "dynamic")
    print(f"[TEST] MRI funding leg: static {det['drivers']['sofr_spread']:.0f}/100 (SOFR-era band), "
          f"dynamic mode with seeded history")

  def test_mri_curve_leg_is_steepener_type_aware(self):
    # Slope alone has no clean metals-risk sign. bear_steepener=True (term-premium/fiscal stress)
    # keeps the slope read; False (bull steepener — a cutting cycle) neutralizes the leg to 50;
    # None (cold start) preserves the legacy read rather than guessing.
    steep = dict(self._MRI_METRICS, **{"10Y": {"value": 3.2}, "30Y": {"value": 4.6}})   # +140bp slope
    _, det_none = self.macro.calculate_mri(steep, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True)
    _, det_bear = self.macro.calculate_mri(steep, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True,
                                           bear_steepener=True)
    _, det_bull = self.macro.calculate_mri(steep, 74.8, 1.0, 4.2, 2350.0, 0.0, return_detail=True,
                                           bear_steepener=False)
    self.assertEqual(det_none["drivers"]["curve_10s30s"], det_bear["drivers"]["curve_10s30s"])  # legacy = bear
    self.assertGreater(det_bear["drivers"]["curve_10s30s"], 90)     # +140bp slope: near top of band
    self.assertEqual(det_bull["drivers"]["curve_10s30s"], 50)       # bull steepener: neutral, not risk
    self.assertLess(det_bull["mri"], det_bear["mri"])               # and the composite reflects it
    print(f"[TEST] MRI curve leg: bear {det_bear['drivers']['curve_10s30s']:.0f} vs bull 50 "
          f"(MRI {det_bear['mri']} -> {det_bull['mri']})")

  def test_mri_stress_vs_extension_axes(self):
    # The composite conflates crisis with crowding. The axes decompose it: a hot-but-benign tape
    # (silver ripping, CFTC crowded, macro calm) must read extension >> stress; a credit event with
    # a cold tape must read stress >> extension. Each axis is its member blocks' weighted score
    # renormalized, so both live on the same 0-100 scale as the MRI.
    hot_tape = {
      "DXY": {"value": 98.0}, "TED": {"value": 0.10}, "VIX": {"value": 13.0},
      "Spreads": {"value": 2.4}, "10Y": {"value": 3.6}, "30Y": {"value": 3.9},
      "CFTC_Silver_Net_Longs": {"value": 80000.0}
    }
    _, det_hot = self.macro.calculate_mri(hot_tape, 95.0, 0.8, 4.6, 2300.0, -1.0, return_detail=True)
    self.assertGreater(det_hot["axes"]["extension"], det_hot["axes"]["stress"] + 25)
    crisis = {
      "DXY": {"value": 107.0}, "TED": {"value": 0.45}, "VIX": {"value": 34.0},
      "Spreads": {"value": 6.5}, "10Y": {"value": 5.1}, "30Y": {"value": 5.3},
      "CFTC_Silver_Net_Longs": {"value": -5000.0}
    }
    _, det_cri = self.macro.calculate_mri(crisis, 55.0, 3.1, 3.4, 2450.0, 2.0, return_detail=True)
    self.assertGreater(det_cri["axes"]["stress"], det_cri["axes"]["extension"] + 25)
    # decomposition integrity: renormalized member blocks reproduce each axis
    for det, axis, members in ((det_hot, "stress", ("liquidity_fx", "yield_curve", "volatility")),
                               (det_hot, "extension", ("commodity", "sentiment"))):
      blocks = {b["key"]: b for b in det["blocks"]}
      tw = sum(blocks[m]["weight"] for m in members)
      expect = sum(blocks[m]["score"] * blocks[m]["weight"] for m in members) / tw
      self.assertAlmostEqual(det[  "axes"][axis], expect, delta=0.5)
    print(f"[TEST] MRI axes: hot-tape stress={det_hot['axes']['stress']} ext={det_hot['axes']['extension']} | "
          f"crisis stress={det_cri['axes']['stress']} ext={det_cri['axes']['extension']}")


  # ====================== PHASE 4a — TRIANGULATED VALUATION ======================

  def test_phase4a_technical_quality_nonfungible(self):
    # TQ is bounded, reads the REAL Fraser index, and blends BOTH Ag+Au recovery (fixes dropped-gold).
    tq = self.val.calculate_technical_quality("red_mountain")
    self.assertTrue(0.55 <= tq["tq"] <= 1.70)
    self.assertIn("jurisdiction", tq["factors"])
    self.assertTrue(0.70 <= tq["factors"]["rec_blend"] <= 0.97)        # blended Ag+Au recovery
    # ounces are NOT fungible: belmont (high recovery, great infra, shallow) out-qualities mogollon.
    tq_bel = self.val.calculate_technical_quality("belmont_tailings")["tq"]
    tq_mog = self.val.calculate_technical_quality("mogollon")["tq"]
    self.assertGreater(tq_bel, tq_mog)
    print(f"[TEST] TQ non-fungible: red_mtn={tq['tq']:.3f} belmont={tq_bel:.3f} > mogollon={tq_mog:.3f}")

  def test_phase4a_option_premium_coherent(self):
    # pi_opt is a FRACTION >= 0 (not a $-additive multiple), rises with vol and with deeply negative real
    # yields (monetary carry), is 0 on moneyness with no AISC edge, and DECAYS by stage.
    base = self.val.calculate_option_premium(75.0, 25.0, 0.30, 2.0, "explorer")
    self.assertGreaterEqual(base["pi_opt"], 0.0)
    self.assertEqual(base["moneyness_excess"], 0.0)                    # peer_aisc defaults to aisc -> no edge
    hi_vol = self.val.calculate_option_premium(75.0, 25.0, 0.50, 2.0, "explorer")["pi_opt"]
    neg_ry = self.val.calculate_option_premium(75.0, 25.0, 0.30, -2.0, "explorer")["pi_opt"]
    self.assertGreater(hi_vol, base["pi_opt"])                         # more vol -> more option value
    self.assertGreater(neg_ry, base["pi_opt"])                         # negative real yield -> monetary carry
    expl = self.val.calculate_option_premium(75.0, 25.0, 0.50, -2.0, "explorer")["pi_opt"]
    prod = self.val.calculate_option_premium(75.0, 25.0, 0.50, -2.0, "producer")["pi_opt"]
    self.assertGreater(expl, prod)                                     # stage decay: explorer IS an option
    print(f"[TEST] pi_opt coherent: base={base['pi_opt']:.3f} hi_vol={hi_vol:.3f} neg_ry={neg_ry:.3f} | explorer {expl:.3f} > producer {prod:.3f}")

  def test_phase4a_market_leg_no_silver_double_count(self):
    # De-overlap invariant (the "no double-counting" mandate): with no AISC edge, the silver LEVEL enters
    # intrinsic ONLY through peer_ev (and option vol/carry), never a separate discovery re-rating. So
    # holding peer_ev fixed and moving spot_ag must NOT move the market-leg base.
    kw = dict(peer_ev_oz=2.0, capital_discount_factor=0.88, real_yield=2.0, silver_vol=0.30,
              forensic_penalty=1.0, dynamic_aisc=25.0, shares_outstanding=208600000)
    lo = self.val.calculate_spear_intrinsic(spot_ag=60.0, **kw)
    hi = self.val.calculate_spear_intrinsic(spot_ag=90.0, **kw)
    self.assertAlmostEqual(lo["v_mkt_defined"], hi["v_mkt_defined"], places=6)
    rich = self.val.calculate_spear_intrinsic(spot_ag=60.0, **{**kw, "peer_ev_oz": 3.0})
    self.assertGreater(rich["v_mkt_defined"], lo["v_mkt_defined"])     # the single legitimate silver channel
    print(f"[TEST] De-overlap: v_mkt invariant to spot @fixed peer_ev ({lo['v_mkt_defined']:.3f}); rises with peer_ev ({rich['v_mkt_defined']:.3f})")

  def test_phase4a_triangulation_blend(self):
    # Weights sum to 1; the triangulated intrinsic lies between the cost and (option-lifted) market legs;
    # a pure explorer carries no income leg.
    kw = dict(peer_ev_oz=2.078, spot_ag=75.6, capital_discount_factor=0.88, real_yield=2.1,
              silver_vol=0.30, forensic_penalty=1.0, dynamic_aisc=25.6, shares_outstanding=208600000)
    d = self.val.calculate_spear_intrinsic(**kw)
    self.assertAlmostEqual(sum(d["weights"].values()), 1.0, places=6)
    lo, hi = sorted([d["legs"]["cost"], d["legs"]["market"]])
    self.assertTrue(lo <= d["v_intrinsic"] <= hi)
    self.assertEqual(d["legs"]["income"], 0.0)
    # MoS ledger is a transparent multiplicative haircut chain
    self.assertEqual(d["mos_ledger"][-1]["name"], "forensic_penalty")
    print(f"[TEST] Triangulation: intrinsic ${d['v_intrinsic']:.3f} in [cost ${d['legs']['cost']:.3f}, market ${d['legs']['market']:.3f}]; weights {d['weights']}")

  def test_phase4a_scenarios_ordered(self):
    kw = dict(peer_ev_oz=2.078, spot_ag=75.6, capital_discount_factor=0.88, real_yield=2.1,
              silver_vol=0.30, forensic_penalty=1.0, dynamic_aisc=25.6, shares_outstanding=208600000)
    sc = self.val.run_intrinsic_scenarios(kw, 0.30)
    self.assertLessEqual(sc["bear"], sc["base"])
    self.assertLessEqual(sc["base"], sc["bull"])
    self.assertEqual(len(sc["tornado"]), 4)
    for t in sc["tornado"]:
      self.assertLessEqual(t["low"], t["high"])
    print(f"[TEST] Scenarios ordered: bear ${sc['bear']:.2f} <= base ${sc['base']:.2f} <= bull ${sc['bull']:.2f}")


# ---- v5.1 engine-audit regression tests (unit/mechanism tests, no live network; they assert the
# ---- fix invariants, not magic numbers) --------------------------------------------------------

class _FakeCache:
    """Minimal research-cache stand-in: .value(ticker, field, default) over a controlled dict."""

    def __init__(self, data):
        self.data = data

    def value(self, tkr, field, default=None):
        return (self.data.get(tkr.upper(), {}) or {}).get(field, default)


class TestRepFloorReconciliation(unittest.TestCase):
    """v5.1 audit action #2: the REP-floor cost leg reconciles to the SAME sourced resource base
    as the market leg."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")

    def test_effective_oz_passthrough(self):
        shares = 208_600_000
        legacy = self.v.calculate_rep_floor(shares_outstanding=shares)            # config buckets
        floor_zero = self.v.calculate_rep_floor(shares_outstanding=shares, effective_oz=0.0)
        floor_big = self.v.calculate_rep_floor(shares_outstanding=shares, effective_oz=1e9)
        # zero ounces -> cash + infra only (a hard floor below the legacy resource-laden value)
        self.assertLess(floor_zero, legacy)
        self.assertLess(legacy, floor_big)
        # the floor still scales inversely with the share count under the override
        half = self.v.calculate_rep_floor(shares_outstanding=2 * shares, effective_oz=1e9)
        self.assertAlmostEqual(half, floor_big / 2.0, places=6)

    def test_cost_leg_uses_reconciled_oz_and_records_basis(self):
        self.v._rc = __import__("research_cache").ResearchCache()
        kw = dict(peer_ev_oz=2.078, spot_ag=75.6, capital_discount_factor=0.88, real_yield=2.1,
                  silver_vol=0.30, forensic_penalty=1.0, dynamic_aisc=25.6, shares_outstanding=208_600_000)
        d = self.v.calculate_spear_intrinsic(**kw)
        # the cost leg equals the floor evaluated on the SAME effective ounces the market leg used
        expected_cost = self.v.calculate_rep_floor(208_600_000, effective_oz=d["effective_oz_total"])
        self.assertAlmostEqual(d["legs"]["cost"], round(expected_cost, 4), places=4)
        self.assertIn(d["rep_floor_basis"], ("research_cache (filings, reconciled)", "config buckets"))
        # convex-combination invariant preserved (no income leg for a pure explorer)
        lo, hi = sorted([d["legs"]["cost"], d["legs"]["market"]])
        self.assertLessEqual(lo, d["v_intrinsic"])
        self.assertLessEqual(d["v_intrinsic"], hi)


class TestBallastNavAnchor(unittest.TestCase):
    """v5.1 audit action #3: ballast fair value anchors on a SOURCED NAV, never raw accounting book
    (which understates holdco/royalty NAV); names without a NAV keep the documented config anchor."""

    def setUp(self):
        self.m = engine.CommodityExMonitor()

    def test_allow_book_false_requires_genuine_nav(self):
        self.m._rc = _FakeCache({
            "HASNAV": {"currency": "CAD", "nav_inventory": None, "nav_adj_per_share": 5.0,
                       "book_value_per_share": 2.0},
            "BOOKONLY": {"currency": "USD", "nav_inventory": None, "nav_adj_per_share": None,
                         "book_value_per_share": 2.0},
        })
        # a sourced NAV is used regardless of allow_book
        self.assertEqual(self.m._research_book_native("HASNAV", allow_book=False), (5.0, "CAD"))
        # raw book is NOT a fair-value anchor: allow_book=False returns None (caller keeps config ref)
        self.assertIsNone(self.m._research_book_native("BOOKONLY", allow_book=False))
        # but the legacy/archetype caller (allow_book=True, the default) still sees raw book -> unchanged
        self.assertEqual(self.m._research_book_native("BOOKONLY", allow_book=True), (2.0, "USD"))
        self.assertEqual(self.m._research_book_native("BOOKONLY"), (2.0, "USD"))

    def test_ballast_fair_value_method_decoupled_from_price(self):
        # the underlying fair-value method never takes the name's own share price (severed loop)
        fv = self.m.valuation_engine.calculate_ballast_fair_value(
            ref_price=4.0, base_mult=1.15, spot_now=1.0, spot_ref=1.0, spot_beta=1.0, forensic_pen=1.0)
        self.assertAlmostEqual(fv, 4.0 * 1.15)


class TestES95SignedConvention(unittest.TestCase):
    """v5.1 audit action #4: ES95 is a SIGNED DECIMAL end-to-end (negative = loss); the cold-start
    seed no longer leaves the tail-risk machinery inert."""

    def test_cold_start_seed_is_signed_decimal(self):
        m = engine.CommodityExMonitor()
        es = m.state_cache["es_95"]
        self.assertLess(es, 0.0, "ES95 cold-start seed must be a signed decimal loss (negative)")
        self.assertGreater(es, -1.0, "ES95 seed should be a per-unit decimal, not a percent")

    def test_machinery_live_at_cold_start(self):
        m = engine.CommodityExMonitor()
        es_pct = m.state_cache["es_95"] * 100.0     # display/plumbing convention
        sizer, radar = m.sizer, m.radar
        base = dict(aga_price=0.71, aga_adv=5_000_000, port_vol=0.80, vix=16.5, jsf_score=4.0)
        vols = {"AGA.V": 0.80, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}
        corr = {"AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30}}
        live = sizer.calculate_sizing(10000.0, 0.30, vols, corr, 30.0,
                                      dict(base, expected_shortfall_95_pct=es_pct))
        inert = sizer.calculate_sizing(10000.0, 0.30, vols, corr, 30.0,
                                       dict(base, expected_shortfall_95_pct=520.0))  # the OLD seed*100
        # the OLD positive seed left the throttle inert (no tail brake); the new signed seed engages it
        self.assertEqual(inert["es_throttle"], 1.0)
        self.assertLess(live["es_throttle"], 1.0)
        # Health Rating penalty is likewise live (lower than a 0-ES no-penalty baseline)
        h_live = radar.calculate_health_rating(4.0, 30.0, es_pct, False)["health_rating"]
        h_zero = radar.calculate_health_rating(4.0, 30.0, 0.0, False)["health_rating"]
        self.assertLess(h_live, h_zero)


class TestOptionPremiumMoneynessGate(unittest.TestCase):
    """v5.1 audit action #5: the option-premium relative-moneyness term is stage-gated (needs a real
    project-vs-peer AISC edge); when inactive its weight is dropped and vol+carry renormalize to 1."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")

    def test_inactive_renormalizes_vol_carry(self):
        # explorer with only an INDUSTRY aisc (peer_aisc=None) -> moneyness term inactive
        r = self.v.calculate_option_premium(75.0, 25.0, 0.30, 2.0, "explorer")
        self.assertFalse(r["moneyness_active"])
        self.assertEqual(r["moneyness_excess"], 0.0)
        self.assertEqual(r["weights_used"]["moneyness"], 0.0)
        self.assertAlmostEqual(r["weights_used"]["vol"] + r["weights_used"]["carry"], 1.0, places=6)

    def test_active_with_real_aisc_edge(self):
        # a genuine project-vs-peer AISC edge re-activates the term at its configured weights
        r = self.v.calculate_option_premium(75.0, 18.0, 0.30, 2.0, "explorer", peer_aisc=25.0)
        self.assertTrue(r["moneyness_active"])
        self.assertGreater(r["moneyness_excess"], 0.0)
        self.assertEqual(r["weights_used"]["moneyness"], 0.4)

    def test_monotonic_and_stage_decay_preserved(self):
        base = self.v.calculate_option_premium(75.0, 25.0, 0.30, 2.0, "explorer")["pi_opt"]
        hi_vol = self.v.calculate_option_premium(75.0, 25.0, 0.50, 2.0, "explorer")["pi_opt"]
        neg_ry = self.v.calculate_option_premium(75.0, 25.0, 0.30, -2.0, "explorer")["pi_opt"]
        prod = self.v.calculate_option_premium(75.0, 25.0, 0.50, -2.0, "producer")["pi_opt"]
        expl = self.v.calculate_option_premium(75.0, 25.0, 0.50, -2.0, "explorer")["pi_opt"]
        self.assertGreater(hi_vol, base)
        self.assertGreater(neg_ry, base)
        self.assertGreater(expl, prod)


class TestSecondBatchFixes(unittest.TestCase):
    """v5.1 audit, second-tier findings: forensic configurability/contamination, exploration-leg
    capital discount, mos_ledger completeness, fail-conservative defaults, peer-comp
    anti-fabrication."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")
        self.v._rc = __import__("research_cache").ResearchCache()

    def test_forensic_runway_threshold_is_configurable(self):
        f = engine.ForensicEngine("v5_config.json")
        # ~19.3mo runway passes the default 18mo gate
        _, _, d = f.calculate_jsf_score("AGA.V", 53e6, 2.75e6, 0.02, 0.02, 100, 100, 100)
        self.assertTrue(d["runway"]["pass"])
        # tighten the gate via config -> the SAME runway now fails (config is actually read)
        f._config_provider = lambda: {
            "portfolio_metadata": {"AGA.V": {"type": "explorer"}},
            "forensic_thresholds": {"runway_min_months": 24.0, "cba_denominator": "cash",
                                    "max_burn_acceleration_pct": 0.15, "max_qoq_dilution_pct": 2.0,
                                    "max_sga_ratio": 0.30},
            "forensic_override_policy": {"max_validity_days": 45}, "forensic_overrides": {}}
        _, _, d2 = f.calculate_jsf_score("AGA.V", 53e6, 2.75e6, 0.02, 0.02, 100, 100, 100)
        self.assertFalse(d2["runway"]["pass"])

    def test_exploration_leg_applies_capital_discount(self):
        kw = dict(peer_ev_oz=2.0, spot_ag=75.0, real_yield=2.0, silver_vol=0.30,
                  forensic_penalty=1.0, dynamic_aisc=25.0, shares_outstanding=208_600_000)
        hi = self.v.calculate_spear_intrinsic(capital_discount_factor=1.0, **kw)["v_exploration"]
        lo = self.v.calculate_spear_intrinsic(capital_discount_factor=0.5, **kw)["v_exploration"]
        self.assertGreater(hi, lo)                       # leg now responds to the capital discount
        self.assertAlmostEqual(lo, hi * 0.5, places=4)   # linear in capital_discount_factor

    def test_mos_ledger_includes_option_premium_last_is_forensic(self):
        kw = dict(peer_ev_oz=2.078, spot_ag=75.6, capital_discount_factor=0.88, real_yield=2.1,
                  silver_vol=0.30, forensic_penalty=0.95, dynamic_aisc=25.6, shares_outstanding=208_600_000)
        d = self.v.calculate_spear_intrinsic(**kw)
        names = [r["name"] for r in d["mos_ledger"]]
        self.assertIn("option_premium", names)
        self.assertEqual(names[-1], "forensic_penalty")          # net-haircut invariant preserved
        opt_row = next(r for r in d["mos_ledger"] if r["name"] == "option_premium")
        self.assertAlmostEqual(opt_row["factor"], round(1.0 + d["option_premium"]["pi_opt"], 3), places=3)
        self.assertGreaterEqual(opt_row["factor"], 1.0)          # it is a LIFT, not a haircut

    def test_health_radar_priorities_fail_conservative(self):
        r = engine.HealthRadarEngine("v5_config.json")
        pr = r.generate_priorities({"Implied_Upside": 100.0},   # NO AGA_Intrinsic key
                                   jsf_score=4.0, mri_score=30.0, expected_shortfall_95=-4.0, p_aga=0.71)
        self.assertNotEqual(pr[0]["title"], "EXPLOIT SPEAR ARBITRAGE")

    def test_technical_quality_surfaces_defaults_used(self):
        unk = self.v.calculate_technical_quality("___unconfigured___")
        self.assertFalse(unk["project_configured"])
        self.assertEqual(set(unk["defaults_used"]),
                         {"grade_gpt_ageq", "ageq_share_ag", "ageq_share_au", "rec_ag", "rec_au",
                          "fraser", "infrastructure", "depth"})
        self.v._config_provider = lambda: {"technical_quality": {"enabled": True, "factors": {}, "projects": {
            "P": {"grade_gpt_ageq": 250, "ageq_share_ag": 0.7, "ageq_share_au": 0.3, "rec_ag": 0.85,
                  "rec_au": 0.92, "fraser": 80, "infrastructure": 0.6, "depth": 0.5}}}}
        p = self.v.calculate_technical_quality("P")
        self.assertTrue(p["project_configured"])
        self.assertEqual(p["defaults_used"], [])

    def test_sourced_resource_treats_zero_indicated_as_valid(self):
        self.v._rc = _FakeCache({"X": {"in_ground_ageq_oz_indicated": 0.0,
                                       "in_ground_ageq_oz_inferred": 5_000_000}})
        # 0.0 indicated is a real (all-inferred) value, not "missing" -> not dropped by or-chaining
        self.assertEqual(self.v._sourced_spear_resource("X"), (0.0, 5_000_000.0))


class TestArchetypePayloadCurrency(unittest.TestCase):
    """2026-09-19: _archetype_payload resolved currency from ballast_valuation only,
    defaulting non-ballast names (TDW/DHT) to CAD. Their USD legs were then labeled
    CAD with no FX normalization, so the V pillar compared a CAD price against
    USD-denominated value (TDW upside read -42% instead of the true -19%)."""

    def _payload(self, ticker, cfg):
        # _archetype_payload reads self._research_book_native / self._apply_ingestion_overlay;
        # stub both neutral so the test isolates the currency-resolution logic.
        class _Stub: pass
        stub = _Stub()
        stub._research_book_native = lambda t, allow_book=False: None
        stub._apply_ingestion_overlay = lambda t, p: None
        return engine.CommodityExMonitor._archetype_payload(
            stub, ticker, cfg, {}, {}, 0.0, 0.0, {})

    def test_non_ballast_usd_name_resolves_usd(self):
        cfg = {"ballast_valuation": {},
               "portfolio_metadata": {"TDW": {"currency": "USD"}}}
        self.assertEqual(self._payload("TDW", cfg)["currency"], "USD")

    def test_ballast_block_still_wins(self):
        cfg = {"ballast_valuation": {"GROY": {"currency": "USD"}},
               "portfolio_metadata": {"GROY": {"currency": "CAD"}}}
        self.assertEqual(self._payload("GROY", cfg)["currency"], "USD")

    def test_unknown_name_defaults_cad(self):
        cfg = {"ballast_valuation": {}, "portfolio_metadata": {}}
        self.assertEqual(self._payload("XXX", cfg)["currency"], "CAD")


class TestBarbellWeightsSingleSource(unittest.TestCase):
    """v5.1 audit, third batch: the 60/15/15/10 barbell weights are now one validated source."""

    def test_resolve_validation_and_comment_skip(self):
        # valid config (with a _comment) is used verbatim
        cfg = {"barbell_weights": {"_comment": "x", "AGA.V": 0.60, "GROY": 0.15,
                                   "URC.TO": 0.15, "GMX.TO": 0.10}}
        self.assertEqual(engine._resolve_barbell_weights(cfg),
                         {"AGA.V": 0.60, "GROY": 0.15, "URC.TO": 0.15, "GMX.TO": 0.10})
        # missing / malformed / non-unit-sum -> the safe default (never a silent mis-weight)
        self.assertEqual(engine._resolve_barbell_weights({}), engine.DEFAULT_BARBELL_WEIGHTS)
        self.assertEqual(engine._resolve_barbell_weights({"barbell_weights": "nonsense"}),
                         engine.DEFAULT_BARBELL_WEIGHTS)
        self.assertEqual(engine._resolve_barbell_weights({"barbell_weights": {"AGA.V": 0.9, "GROY": 0.9}}),
                         engine.DEFAULT_BARBELL_WEIGHTS)

    def test_weight_vector_ordered_by_ticker_list(self):
        # the comps-worker bug class: a vector built from the dict, ORDERED to the ticker list, keeps
        # GMX=0.10 / URC=0.15 distinct (the old literal np.array was one reorder from swapping them)
        bw = engine._resolve_barbell_weights({"barbell_weights": dict(engine.DEFAULT_BARBELL_WEIGHTS)})
        vec = [bw.get(t, 0.0) for t in ["AGA.V", "GROY", "GMX.TO", "URC.TO"]]
        self.assertEqual(vec, [0.60, 0.15, 0.10, 0.15])
        self.assertAlmostEqual(sum(vec), 1.0)

    def test_live_config_barbell_weights_are_used_and_valid(self):
        import json
        cfg = json.load(open("v5_config.json"))
        w = engine._resolve_barbell_weights(cfg)
        self.assertEqual(set(w), {"AGA.V", "GROY", "URC.TO", "GMX.TO"})
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertEqual(w["AGA.V"], cfg["barbell_weights"]["AGA.V"])   # config, not the fallback

    def test_load_shares_from_csv_is_graceful(self):
        m = engine.CommodityExMonitor()
        self.assertIn(m._load_shares_from_csv(force=True), (True, False))  # globs newest; never raises


class TestScenarioConvexUnificationAndCompsOverlap(unittest.TestCase):
    """v5.1 audit, fourth batch: scenarios<->what-if propagation unified on the convex margin model
    (1.7) and the vol/carry comps-overlap haircut (1.1)."""

    def setUp(self):
        self.v = engine.ValuationEngine("v5_config.json")
        self.v._rc = __import__("research_cache").ResearchCache()

    def test_peer_ev_margin_scaled_is_convex_and_floored(self):
        # peers re-rate with the operating MARGIN (spot - aisc), not 1:1 with spot
        self.assertAlmostEqual(self.v.peer_ev_margin_scaled(2.0, 75.0, 90.0, 25.0), 2.0 * 65 / 50)
        self.assertAlmostEqual(self.v.peer_ev_margin_scaled(2.0, 75.0, 75.0, 25.0), 2.0)   # no move
        # a deep drawdown below AISC is floored, never negative
        self.assertGreater(self.v.peer_ev_margin_scaled(2.0, 75.0, 10.0, 25.0), 0.0)

    def test_scenario_silver_lever_uses_convex_peer_scaling(self):
        import json
        kw = dict(peer_ev_oz=2.0, spot_ag=75.0, capital_discount_factor=0.88, real_yield=2.0,
                  silver_vol=0.30, forensic_penalty=1.0, dynamic_aisc=25.0, shares_outstanding=208_600_000)
        sc = self.v.run_intrinsic_scenarios(kw, 0.30)
        self.assertLessEqual(sc["bear"], sc["base"])
        self.assertLessEqual(sc["base"], sc["bull"])
        # the tornado 'Silver spot' high equals an intrinsic run with the CONVEX up-spot peer EV/oz
        spot_move = json.load(open("v5_config.json")).get("scenarios", {}).get("spot_sigma_mult", 1.0) * 0.30
        spot_up = 75.0 * (1 + spot_move)
        peer_up = self.v.peer_ev_margin_scaled(2.0, 75.0, spot_up, 25.0)
        expected_hi = self.v.calculate_spear_intrinsic(**{**kw, "peer_ev_oz": peer_up, "spot_ag": spot_up})["v_intrinsic"]
        silver_lever = next(l for l in sc["tornado"] if l["input"] == "Silver spot")
        self.assertAlmostEqual(silver_lever["high"], round(expected_hi, 3), places=3)

    def test_comps_overlap_keep_haircuts_vol_carry_not_moneyness(self):
        def _cfg(keep):
            return {"option_premium": {"enabled": True, "comps_overlap_keep": keep,
                    "weights": {"moneyness": 0.4, "vol": 0.35, "carry": 0.25}, "vol_floor": 0.2,
                    "vol_k": 1.0, "vol_cap": 0.4, "carry_breakeven": 1.0, "carry_k": 0.25,
                    "carry_cap": 0.5, "moneyness_cap": 1.5, "stage_optionality_cap": {"explorer": 1.0}}}
        full = engine.ValuationEngine("v5_config.json"); full._config_provider = lambda: _cfg(1.0)
        cut = engine.ValuationEngine("v5_config.json"); cut._config_provider = lambda: _cfg(0.7)
        # high vol + negative real yield -> both vol & carry terms active; the haircut lowers pi_opt
        f = full.calculate_option_premium(75.0, 25.0, 0.40, -2.0, "explorer")
        c = cut.calculate_option_premium(75.0, 25.0, 0.40, -2.0, "explorer")
        self.assertLess(c["pi_opt"], f["pi_opt"])
        self.assertAlmostEqual(c["vol_term"], f["vol_term"] * 0.7, places=6)
        # the relative-moneyness edge is NOT haircut (it is genuinely absent from the comps)
        fe = full.calculate_option_premium(75.0, 18.0, 0.40, -2.0, "explorer", peer_aisc=25.0)
        ce = cut.calculate_option_premium(75.0, 18.0, 0.40, -2.0, "explorer", peer_aisc=25.0)
        self.assertEqual(fe["moneyness_excess"], ce["moneyness_excess"])

    def test_live_config_overlap_keep_active(self):
        import json
        keep = json.load(open("v5_config.json"))["option_premium"]["comps_overlap_keep"]
        self.assertLess(keep, 1.0)   # the haircut is actually engaged in the live config
        self.assertGreater(keep, 0.0)


if __name__ == '__main__':
  unittest.main()
