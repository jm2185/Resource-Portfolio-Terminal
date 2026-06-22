"""Fed Net Liquidity monitor — the QUANTITY-of-money tell. Unit alignment (the one gotcha), the
trend classification, the sharp-drain flag, and graceful dormancy on thin inputs."""
import unittest

import liquidity_monitor as lm


class NetLiquidityFormulaTests(unittest.TestCase):
    def test_unit_alignment_to_billions(self):
        # WALCL/WDTGAL are $millions on FRED, RRPONTSYD is $billions — the whole point of the module.
        # 6,600,000 mn − 800,000 mn = 5,800 bn; − 400 bn RRP = 5,400 bn.
        self.assertEqual(lm.net_liquidity_bn(6_600_000, 800_000, 400), 5400.0)

    def test_missing_leg_is_none_never_partial(self):
        self.assertIsNone(lm.net_liquidity_bn(6_600_000, None, 400))
        self.assertIsNone(lm.net_liquidity_bn(None, None, None))


class TrendTests(unittest.TestCase):
    def _assess(self, cur, prev):
        return lm.assess(walcl_musd=cur, tga_musd=0, rrp_busd=0, prev_net_liq_bn=prev)

    def test_expanding(self):
        r = lm.assess(walcl_musd=5_500_000, tga_musd=0, rrp_busd=0, prev_net_liq_bn=5400.0)
        self.assertEqual(r["direction"], "EXPANDING")
        self.assertEqual(r["bias"], "risk_on")
        self.assertEqual(r["change_4w_bn"], 100.0)
        self.assertFalse(r["flags"])

    def test_contracting_no_flag(self):
        r = lm.assess(walcl_musd=5_320_000, tga_musd=0, rrp_busd=0, prev_net_liq_bn=5400.0)
        self.assertEqual(r["direction"], "CONTRACTING")    # −80bn: past contract, short of sharp
        self.assertEqual(r["bias"], "risk_off")
        self.assertFalse(r["flags"])

    def test_sharp_contraction_raises_flag(self):
        r = lm.assess(walcl_musd=5_200_000, tga_musd=0, rrp_busd=0, prev_net_liq_bn=5400.0)
        self.assertEqual(r["direction"], "SHARPLY-CONTRACTING")   # −200bn
        self.assertEqual(r["bias"], "risk_off")
        self.assertEqual(r["flags"][0]["id"], "net_liquidity_drain")
        self.assertIn("spear", r["read"])

    def test_neutral_band(self):
        r = lm.assess(walcl_musd=5_410_000, tga_musd=0, rrp_busd=0, prev_net_liq_bn=5400.0)
        self.assertEqual(r["direction"], "NEUTRAL")        # +10bn inside the band
        self.assertEqual(r["bias"], "neutral")

    def test_prior_from_three_legs(self):
        # exercise the prior-from-components path (not the precomputed prev_net_liq_bn)
        r = lm.assess(walcl_musd=6_600_000, tga_musd=800_000, rrp_busd=400,
                      prev_walcl_musd=6_650_000, prev_tga_musd=800_000, prev_rrp_busd=400)
        self.assertEqual(r["net_liquidity_bn"], 5400.0)
        self.assertEqual(r["change_4w_bn"], -50.0)         # 5400 − 5450

    def test_config_override_threshold(self):
        r = lm.assess(walcl_musd=5_300_000, tga_musd=0, rrp_busd=0, prev_net_liq_bn=5400.0,
                      config={"liquidity_monitor": {"sharp_contract_bn": -90.0}})
        self.assertEqual(r["direction"], "SHARPLY-CONTRACTING")   # −100bn now trips the lowered bar


class DormancyTests(unittest.TestCase):
    def test_dormant_without_components(self):
        r = lm.assess(prev_net_liq_bn=5400.0)
        self.assertFalse(r["available"])
        self.assertEqual(r["direction"], "UNKNOWN")

    def test_level_only_without_prior(self):
        r = lm.assess(walcl_musd=6_600_000, tga_musd=800_000, rrp_busd=400)
        self.assertTrue(r["available"])
        self.assertEqual(r["direction"], "LEVEL-ONLY")
        self.assertIsNone(r["change_4w_bn"])
        self.assertEqual(r["net_liquidity_t"], 5.4)

    def test_units_note_is_explicit(self):
        r = lm.assess(walcl_musd=6_600_000, tga_musd=800_000, rrp_busd=400, prev_net_liq_bn=5400.0)
        self.assertIn("$mn", r["note"])
        self.assertIn("$bn", r["note"])


if __name__ == "__main__":
    unittest.main()
