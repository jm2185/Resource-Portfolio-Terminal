import unittest
import asyncio
from engine import MacroRegimeEngine, PeerEngine, ForensicEngine, ValuationEngine, PortfolioSizer

class TestCommodityExV5(unittest.TestCase):
  def setUp(self):
    self.config_path = "v5_config.json"
    self.macro = MacroRegimeEngine(self.config_path)
    self.peers = PeerEngine(self.config_path)
    self.forensics = ForensicEngine(self.config_path)
    self.val = ValuationEngine(self.config_path)
    self.sizer = PortfolioSizer(self.config_path)

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
      ticker="AGA.V",
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
      ticker="AGA.V",
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
    
    print(f"[TEST] High Quality Junior Penalty: {penalty_a}x | Dilution decay Junior: {penalty_b}x | Royalty Accrual Decay: {penalty_c:.3f}x")

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

if __name__ == '__main__':
  unittest.main()
