"""
Tests for the Sentinel (sentinel.py, Forge M3) — the crown jewel.

Pins the exact math against hand-checked fixtures (the discipline the engine uses for its
$4.64 → $1.69 reprice check):
  * liquidity-runway days_50/days_90 and the ES95 negative-percent → fraction reconciliation;
  * the no-ADV fail-safe (cannot grant a size-band exception);
  * the financing-window blend + renormalization when a term is missing;
  * the death-spiral flag toggling exactly at the boundary;
  * thesis-integrity recompute (engine claims) with manual claims untouched;
  * the r1 pre-commitment rule firing ONCE, then deduping to open / suppressing when acknowledged.
"""
import unittest

import sentinel as sen


class LiquidityRunwayTests(unittest.TestCase):
    def test_hand_checked_fixture(self):
        # adv90=100k, es95=-6.0% -> frac -0.06; -(-0.06)=0.06; 0.06-free(0.05)=0.01; stress=1-0.01=0.99
        # per_day = 100000*0.99*0.20 = 19800 ; days_90 = 0.9*200000/19800 = 9.0909...
        r = sen.liquidity_runway(100000, -6.0, 200000)
        self.assertAlmostEqual(r["stress"], 0.99, places=4)
        self.assertAlmostEqual(r["per_day"], 19800.0, places=0)
        self.assertAlmostEqual(r["days_50"], 5.05, places=2)
        self.assertAlmostEqual(r["days_90"], 9.09, places=2)
        self.assertFalse(r["runway_ok"])                          # 9.09 > 5

    def test_liquid_small_position_gets_exception(self):
        r = sen.liquidity_runway(1_000_000, -2.0, 100000)         # es below 'free' -> no stress
        self.assertEqual(r["stress"], 1.0)
        self.assertAlmostEqual(r["days_90"], 0.45, places=2)
        self.assertTrue(r["runway_ok"])

    def test_es95_unit_reconciliation_floors_stress(self):
        # an extreme negative-percent ES tips the stress to the 0.25 floor, never below
        r = sen.liquidity_runway(100000, -80.0, 100000)
        self.assertEqual(r["stress"], 0.25)

    def test_no_adv_is_failsafe(self):
        r = sen.liquidity_runway(None, -4.0, 100000)
        self.assertIsNone(r["days_90"])
        self.assertFalse(r["runway_ok"])                          # cannot grant an exception
        self.assertIn("fail-safe", r["note"])


class FinancingWindowTests(unittest.TestCase):
    def test_window_open_near_highs_above_placement(self):
        w = sen.financing_window(1.00, last_placement_price=0.70, rep_floor=0.50,
                                 lo52=0.40, hi52=1.10, dilution_ok=True)
        self.assertTrue(w["window_open"])
        self.assertGreater(w["prem_to_placement"], 0)             # above the last raise
        self.assertEqual(w["state"], "open")

    def test_window_closing_below_placement_near_lows(self):
        w = sen.financing_window(0.45, last_placement_price=0.80, rep_floor=0.50,
                                 lo52=0.40, hi52=1.10, dilution_ok=False)
        self.assertFalse(w["window_open"])
        self.assertLess(w["prem_to_placement"], 0)

    def test_renormalizes_when_placement_missing(self):
        # no last_placement_price and no 52w -> blend over {floor_headroom, dilution_ok} only
        w = sen.financing_window(1.00, rep_floor=0.50, dilution_ok=True)
        self.assertIsNone(w["prem_to_placement"])
        self.assertIn("last_placement_price missing", w["provenance"])
        self.assertEqual(w["terms_used"], ["floor_headroom", "dilution_ok"])
        # blend over the 2 available terms only: (0.20*sat(1.0) + 0.20*1.0)/0.40 = 0.9404
        self.assertAlmostEqual(w["score"], 0.9404, places=3)
        self.assertTrue(w["window_open"])

    def test_death_spiral_boundary(self):
        base = dict(last_placement_price=0.80, lo52=0.30, hi52=1.00)
        # below floor + runway 5.9mo + sieve failing -> TRUE
        on = sen.financing_window(0.50, rep_floor=0.55, dilution_ok=False, runway_months=5.9, **base)
        self.assertTrue(on["death_spiral"])
        # runway exactly 6.0 -> FALSE (strict <)
        off1 = sen.financing_window(0.50, rep_floor=0.55, dilution_ok=False, runway_months=6.0, **base)
        self.assertFalse(off1["death_spiral"])
        # price at floor (not below) -> FALSE
        off2 = sen.financing_window(0.55, rep_floor=0.55, dilution_ok=False, runway_months=5.0, **base)
        self.assertFalse(off2["death_spiral"])
        # sieve clean -> FALSE
        off3 = sen.financing_window(0.50, rep_floor=0.55, dilution_ok=True, runway_months=5.0, **base)
        self.assertFalse(off3["death_spiral"])
        # runway unknown -> suppressed (not assumed false-data), FALSE
        off4 = sen.financing_window(0.50, rep_floor=0.55, dilution_ok=False, runway_months=None, **base)
        self.assertFalse(off4["death_spiral"])


class ThesisIntegrityTests(unittest.TestCase):
    def test_engine_claim_recompute_and_manual_untouched(self):
        claims = [
            {"id": "c1", "text": "18mo runway", "metric": "runway_months", "op": ">=",
             "threshold": 18, "check": "engine", "status": "holds"},
            {"id": "c2", "text": "permitting edge", "metric": None, "check": "manual",
             "status": "holds"},
        ]
        # live runway only 12 -> c1 breaks; c2 manual stays holds -> 1/2 = 0.50 < floor 0.60
        r = sen.thesis_integrity(claims, {"runway_months": 12})
        self.assertEqual(r["holds"], 1)
        self.assertEqual(r["broken"], ["c1"])
        self.assertTrue(r["below_floor"])
        self.assertAlmostEqual(r["score"], 0.5, places=3)

    def test_all_hold(self):
        claims = [{"id": "c1", "text": "x", "metric": "phi", "op": ">=", "threshold": 1.0,
                   "check": "engine"}]
        r = sen.thesis_integrity(claims, {"phi": 1.3})
        self.assertEqual(r["score"], 1.0)
        self.assertFalse(r["below_floor"])

    def test_missing_metric_is_unknown_not_holds(self):
        claims = [{"id": "c1", "text": "x", "metric": "phi", "op": ">=", "threshold": 1.0,
                   "check": "engine"}]
        r = sen.thesis_integrity(claims, {})                       # phi missing
        self.assertEqual(r["statuses"][0]["status"], "unknown")
        self.assertEqual(r["holds"], 0)


class RuleFiringTests(unittest.TestCase):
    R1 = {"id": "r1", "trigger": "phi < 1.0 AND no_catalyst_within_days(30)",
          "action": "trim_to", "arg": 0.40}

    def _ctx(self, *, catalyst=False):
        return {"phi": 0.92, "catalyst_within_days": lambda n: catalyst}

    def test_r1_fires_new_then_open_then_acked(self):
        # tick 1: fires NEW
        fired = sen.evaluate_rules([self.R1], self._ctx(), thesis_id="thesis_1")
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["status"], "new")
        self.assertTrue(fired[0]["proposal"])                     # a trim PROPOSES, never auto-acts
        key = fired[0]["key"]
        self.assertEqual(key, "thesis_1:r1")
        # tick 2: alert already open -> dedupe to 'open' (does not re-fire as new)
        again = sen.evaluate_rules([self.R1], self._ctx(), thesis_id="thesis_1", open_keys={key})
        self.assertEqual(again[0]["status"], "open")
        # once acknowledged -> 'acked'
        acked = sen.evaluate_rules([self.R1], self._ctx(), thesis_id="thesis_1",
                                   acknowledged_keys={key})
        self.assertEqual(acked[0]["status"], "acked")

    def test_r1_quiet_when_catalyst_in_window(self):
        fired = sen.evaluate_rules([self.R1], self._ctx(catalyst=True), thesis_id="thesis_1")
        self.assertEqual(fired, [])

    def test_exit_rule_is_high_risk(self):
        r = {"id": "r2", "trigger": "death_spiral", "action": "exit"}
        fired = sen.evaluate_rules([r], {"death_spiral": True}, thesis_id="t")
        self.assertEqual(fired[0]["level"], "risk")
        self.assertTrue(fired[0]["proposal"])                     # exits PROPOSE, never auto-fire


class SweepTests(unittest.TestCase):
    def _basket(self, **over):
        b = {"ticker": "AGA.V",
             "asymmetry": {"floor_coverage": 0.92, "rho": 3.1, "upside_pct": 140.0},
             "ladder": {"price": 0.80, "floor": 0.60, "bull": 1.50},
             "gate": {"applied": False, "cap": 4.5},
             "dilution_velocity": 0.01, "runway_months": 20}
        b.update(over)
        return b

    def test_sweep_fires_r1_and_pins_new_alert(self):
        thesis = {"id": "thesis_1", "ticker": "AGA.V",
                  "claims": [{"id": "c1", "text": "runway", "metric": "runway_months",
                              "op": ">=", "threshold": 18, "check": "engine"}],
                  "rules": [{"id": "r1", "trigger": "phi < 1.0 AND no_catalyst_within_days(30)",
                             "action": "trim_to", "arg": 0.40}]}
        st = sen.sweep_name(ticker="AGA.V", basket=self._basket(),
                            node={"shares": 100000, "price": 0.80},
                            portfolio_stats={"expected_shortfall_95": -4.0},
                            thesis=thesis, adv90=500000,
                            catalyst_within_days=lambda n: False)
        new_keys = {a["key"] for a in st["new_alerts"]}
        self.assertIn("thesis_1:r1", new_keys)
        self.assertEqual(st["integrity"]["score"], 1.0)           # runway 20 >= 18 holds

    def test_sweep_quiet_when_catalyst_coming(self):
        thesis = {"id": "thesis_1", "ticker": "AGA.V",
                  "rules": [{"id": "r1", "trigger": "phi < 1.0 AND no_catalyst_within_days(30)",
                             "action": "trim_to", "arg": 0.40}]}
        st = sen.sweep_name(ticker="AGA.V", basket=self._basket(),
                            node={"shares": 100000}, portfolio_stats={"expected_shortfall_95": -4.0},
                            thesis=thesis, adv90=500000, catalyst_within_days=lambda n: True)
        self.assertEqual(st["new_alerts"], [])

    def test_sweep_emits_death_spiral_alert(self):
        b = self._basket(ladder={"price": 0.50, "floor": 0.60}, dilution_velocity=0.05,
                         runway_months=4)
        st = sen.sweep_name(ticker="AGA.V", basket=b, node={"shares": 100000},
                            portfolio_stats={"expected_shortfall_95": -4.0}, adv90=500000)
        self.assertTrue(st["death_spiral"])
        self.assertTrue(any(a["key"] == "AGA.V:death_spiral" and a["priority"] == "high"
                            for a in st["alerts"]))

    def test_sweep_size_gate_breach_when_at_ceiling_without_runway(self):
        # big position, thin ADV -> runway not ok; at_ceiling -> the gate flags a BREACH
        st = sen.sweep_name(ticker="AGA.V", basket=self._basket(),
                            node={"shares": 5_000_000}, portfolio_stats={"expected_shortfall_95": -6.0},
                            adv90=100000, at_ceiling=True)
        self.assertFalse(st["size_band_exception_allowed"])
        self.assertIn("BREACH", st["size_gate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
