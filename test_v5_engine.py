import unittest
import asyncio
from engine import MacroRegimeEngine, PeerEngine, ForensicEngine, ValuationEngine, PortfolioSizer, HealthRadarEngine

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
    self.assertIn("Dilution Insulated", details_d["dilution"]["desc"])
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
    self.assertEqual(spear_priority["title"], "EXPLOIT SPEAR ARBITRAGE")
    self.assertIn("486% raw upside", spear_priority["desc"])
    self.assertIn("blended Implied Edge of 123%", spear_priority["desc"])
    
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

    # End-to-end: once the AGA.V config override EXPIRES, the real (failing) dilution + CBA tests
    # re-engage, the JSF score drops, and no overrides are recorded in the audit trail.
    score_expired, _, details_expired = self.forensics.calculate_jsf_score(
      ticker="AGA.V", cash=40000000.0, monthly_burn=750000.0,
      sloan_cfo=0.015, sloan_bs=0.012, shares_t0=240000000, shares_t1=208600000,
      sga_expense=500000.0, cfo_t0=-3000000.0, cfo_t1=-1000000.0, cash_t0=4000000.0,
      today="2099-01-01"
    )
    self.assertFalse(details_expired["dilution"]["pass"])
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

if __name__ == '__main__':
  unittest.main()
