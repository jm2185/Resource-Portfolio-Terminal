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
    
    # Case D: AGA.V explorer protected by context-aware overrides
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
      cash_t0=4000000.0
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

    mu_annualized = u_implied / (conv_months / 12.0)
    variance = max(0.04, port_vol ** 2)
    raw_kelly = (mu_annualized / variance) * fk
    expected_e_target = live_portfolio * raw_kelly  # multiplier=1.0, corr_penalty=1.0, es_throttle=1.0
    self.assertAlmostEqual(res["e_target"], round(expected_e_target, 2), delta=1.0)
    print(f"[TEST] Kelly coherence (horizon={conv_months}mo): e_target=${res['e_target']} "
          f"matches mu/var Kelly ${round(expected_e_target, 2)}")

  def test_cba_insolvent_buffer_hard_fails(self):
    # Phase 3: a near-insolvent explorer (cash buffer -> 0) while still burning must FAIL the CBA
    # test. Previously total_cash <= 0 produced CBA = 0 and auto-PASSED, masking the distress.
    score, penalty, details = self.forensics.calculate_jsf_score(
      ticker="MOCK.V",
      cash=50000.0,            # tiny remaining cash
      monthly_burn=750000.0,   # ~0.07 months runway -> runway fails too
      sloan_cfo=0.0, sloan_bs=0.0,
      shares_t0=208600000, shares_t1=208600000,  # no dilution
      sga_expense=100000.0,
      cfo_t0=-2000000.0,       # actively burning
      cfo_t1=-1900000.0,
      cash_t0=0.0              # insolvent buffer
    )
    self.assertFalse(details["accrual"]["pass"], "Insolvent buffer must fail the CBA test")
    self.assertIn("Insolvent", details["accrual"]["desc"])
    print(f"[TEST] CBA insolvent buffer -> FAIL (score {score}/4.0, '{details['accrual']['desc']}')")

  def test_cba_missing_prior_burn_defers_to_runway(self):
    # Phase 3: with no reliable prior-quarter burn, CBA no longer grants a free pass; it defers to
    # cash-runway adequacy. Healthy runway -> pass; short runway -> fail.
    healthy = self.forensics.calculate_jsf_score(
      ticker="MOCK.V", cash=15000000.0, monthly_burn=750000.0,   # 20 mo runway
      sloan_cfo=0.0, sloan_bs=0.0, shares_t0=208600000, shares_t1=208600000, sga_expense=100000.0)
    short = self.forensics.calculate_jsf_score(
      ticker="MOCK.V", cash=3000000.0, monthly_burn=750000.0,    # 4 mo runway
      sloan_cfo=0.0, sloan_bs=0.0, shares_t0=208600000, shares_t1=208600000, sga_expense=100000.0)
    self.assertTrue(healthy[2]["accrual"]["pass"], "Healthy runway should pass indeterminate CBA")
    self.assertFalse(short[2]["accrual"]["pass"], "Short runway should fail indeterminate CBA")
    print(f"[TEST] CBA indeterminate defers to runway: healthy={healthy[2]['accrual']['pass']} short={short[2]['accrual']['pass']}")

  def test_dilution_sign_with_share_expansion(self):
    # Phase 3 / ordering guard: with shares_t0 = most-recent (per latest_first), QoQ share
    # expansion yields a POSITIVE dilution that fails the < 2% test; a buyback floors to 0 (pass).
    expanded = self.forensics.calculate_jsf_score(
      ticker="MOCK.V", cash=15000000.0, monthly_burn=750000.0,
      sloan_cfo=0.0, sloan_bs=0.0,
      shares_t0=230000000, shares_t1=200000000,  # +15% expansion
      sga_expense=100000.0)
    buyback = self.forensics.calculate_jsf_score(
      ticker="MOCK.V", cash=15000000.0, monthly_burn=750000.0,
      sloan_cfo=0.0, sloan_bs=0.0,
      shares_t0=190000000, shares_t1=200000000,  # -5% reduction
      sga_expense=100000.0)
    self.assertFalse(expanded[2]["dilution"]["pass"], "15% share expansion must fail dilution test")
    self.assertGreater(expanded[2]["dilution"]["value"], 0.0)
    self.assertTrue(buyback[2]["dilution"]["pass"], "Share reduction must pass (floored to 0)")
    self.assertEqual(buyback[2]["dilution"]["value"], 0.0)
    print(f"[TEST] Dilution sign: expansion={expanded[2]['dilution']['value']*100:.1f}% (fail) | buyback floored to {buyback[2]['dilution']['value']*100:.1f}% (pass)")

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

if __name__ == '__main__':
  unittest.main()
