"""
Run: ``python -m unittest test_valuation_actions -v``  (stdlib only).

Covers the pure what-if helpers (override grammar + diffing) and an integration check
that the archetype revaluation actually responds to a macro override — i.e. that a
``run_valuation_whatif`` on a silver explorer moves intrinsic the right direction.
"""

import copy
import unittest

from valuation_actions import (
    canonical, parse_override, parse_overrides, summarize_delta, REGIME_KEYS, MACRO_KEYS,
)


class TestOverrideGrammar(unittest.TestCase):
    def test_absolute_delta_percent(self):
        self.assertEqual(parse_override(79.8, None), 79.8)
        self.assertEqual(parse_override("79.8", 30.0), 79.8)
        self.assertEqual(parse_override("+5", 30.0), 35.0)
        self.assertEqual(parse_override("-0.5", 1.8), 1.3)
        self.assertAlmostEqual(parse_override("+20%", 2.0), 2.4)
        self.assertAlmostEqual(parse_override("-10%", 2.0), 1.8)

    def test_percent_needs_base_and_bad_value_raises(self):
        with self.assertRaises(ValueError):
            parse_override("+20%", None)
        with self.assertRaises(ValueError):
            parse_override("abc", 1.0)

    def test_aliases_and_parsing(self):
        self.assertEqual(canonical("silver"), "spot_ag")
        self.assertEqual(canonical("RY"), "real_yield")
        self.assertIsNone(canonical("nonsense"))
        ov = parse_overrides("silver=+5 ry=-0.5 peer=+20% bogus=9")
        self.assertEqual(ov, {"spot_ag": "+5", "real_yield": "-0.5", "peer_ev_oz": "+20%"})
        self.assertEqual(parse_overrides({"silver": "+5"}), {"spot_ag": "+5"})

    def test_key_sets_consistent(self):
        self.assertTrue(REGIME_KEYS.issubset({"real_yield", "silver_vol", "mri", "dxy"}))
        self.assertIn("spot_ag", MACRO_KEYS)


class TestSummarizeDelta(unittest.TestCase):
    def test_diff_intrinsic_and_upside(self):
        base = {"intrinsic_after_forensic": 1.00, "legs": {"market": 1.0}}
        scen = {"intrinsic_after_forensic": 1.50, "legs": {"market": 1.5}}
        out = summarize_delta(base, scen, price=1.00, applied={"spot_ag": {"from": 30, "to": 45}})
        self.assertEqual(out["base"]["intrinsic"], 1.00)
        self.assertEqual(out["scenario"]["intrinsic"], 1.50)
        self.assertEqual(out["delta"]["intrinsic_pct"], 50.0)
        self.assertEqual(out["base"]["upside_pct"], 0.0)     # 1.00 / 1.00 - 1
        self.assertEqual(out["scenario"]["upside_pct"], 50.0)  # 1.50 / 1.00 - 1
        self.assertEqual(out["delta"]["upside_pp"], 50.0)

    def test_handles_missing_gracefully(self):
        out = summarize_delta({}, {}, price=None, applied={})
        self.assertIsNone(out["delta"]["intrinsic_pct"])
        self.assertIsNone(out["base"]["upside_pct"])


class TestArchetypeRevaluationResponds(unittest.TestCase):
    """The integration heart of run_whatif: get_valuation must move when a macro knob moves."""

    def setUp(self):
        try:
            from archetypes import build_default_router, REGIME_ORDER
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"archetypes unavailable: {exc}")
        self.router = build_default_router()        # default reads v5_config.json
        self.neutral = [0.0] * len(REGIME_ORDER)

    def _aga_payload(self, peer_ev=2.08):
        # Per ENGINE_DESIGN, the explorer's re-rating flows through peer EV/oz (the absolute silver
        # level is intentionally decoupled to avoid double-counting), so peer_ev is the mover here.
        return {
            "currency": "CAD", "price": 0.71, "shares_out": 120_000_000, "aisc": 18.0,
            "macro": {"spot_ag": 30.0, "gold": 2400.0, "real_yield": 1.8,
                      "silver_vol": 0.35, "capital_discount": 0.9, "y30": 4.8},
            "comps": {"peer_ev_oz": peer_ev},
            "financials": {"cash": 8_000_000, "monthly_burn": 600_000},
        }

    def test_peer_rerate_raises_explorer_intrinsic(self):
        base = self.router.get_valuation("AGA.V", self._aga_payload(2.08), self.neutral)
        scen = self.router.get_valuation("AGA.V", self._aga_payload(3.12), self.neutral)  # +50% peer EV/oz
        bi = base.get("intrinsic_after_forensic")
        si = scen.get("intrinsic_after_forensic")
        self.assertIsInstance(bi, (int, float))
        self.assertIsInstance(si, (int, float))
        self.assertGreater(si, bi, "a +50% peer EV/oz re-rate must raise the explorer intrinsic")

    def test_whatif_diff_shape_end_to_end(self):
        p = self._aga_payload(2.08)
        base = self.router.get_valuation("AGA.V", p, self.neutral)
        scen = self.router.get_valuation("AGA.V", self._aga_payload(3.12), self.neutral)
        out = summarize_delta(base, scen, p["price"], {"peer_ev_oz": {"from": 2.08, "to": 3.12}})
        self.assertGreater(out["delta"]["intrinsic_pct"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
