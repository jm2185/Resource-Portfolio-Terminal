"""
Value-mode directive logic (asymmetry_rating._directive).

Pins the fix to the rating≥7 short-circuit: a high-rated value name is "QUALITY — CORE HOLD" ONLY
when it is NOT also deeply below fair value. A high-conviction name trading ≥12% under its (e.g.
metal-re-rated) fair value is an ACCUMULATE — cheapness wins over the rating. Without this, a re-rate
that LIFTS the score would perversely flip a name from ACCUMULATE to CORE HOLD (the GROY case).
"""
import unittest

import asymmetry_rating as ar


def _d(rating, upside, mode="value", phi=0.9, gate=None):
    V = {"mode": mode, "upside_pct": upside, "floor_coverage": phi}
    return ar._directive({}, rating, gate or {"applied": False, "cap": 10.0}, V)


class ValueModeDirectiveTests(unittest.TestCase):
    def test_high_rated_and_cheap_is_accumulate_not_core_hold(self):
        # THE fix: rating 7.5 AND +20% below fair value → ACCUMULATE (cheapness wins)
        self.assertEqual(_d(7.5, 20.0), "BELOW FAIR VALUE — ACCUMULATE")

    def test_high_rated_and_not_cheap_is_core_hold(self):
        self.assertEqual(_d(7.5, 2.0), "QUALITY — CORE HOLD")

    def test_low_rated_and_cheap_is_accumulate(self):
        self.assertEqual(_d(6.5, 20.0), "BELOW FAIR VALUE — ACCUMULATE")

    def test_low_rated_and_fair_is_hold(self):
        self.assertEqual(_d(6.5, 2.0), "FAIR VALUE — HOLD")

    def test_rich_value_name_trims(self):
        self.assertEqual(_d(6.0, -20.0), "RICH — TRIM")

    def test_groy_rerate_does_not_flip_accumulate_to_hold(self):
        # before re-rate: 6.8, +13% → ACCUMULATE.  after re-rate lifts it: 7.4, +57% → STILL ACCUMULATE.
        self.assertEqual(_d(6.8, 13.0), "BELOW FAIR VALUE — ACCUMULATE")
        self.assertEqual(_d(7.4, 57.0), "BELOW FAIR VALUE — ACCUMULATE")

    def test_severe_forensic_gate_still_overrides_everything(self):
        # a genuinely severe forensic cap still wins (unchanged behaviour)
        self.assertEqual(_d(7.5, 20.0, gate={"applied": True, "cap": 4.0}),
                         "FORENSIC DECAY — AVOID / DE-RISK")


if __name__ == "__main__":
    unittest.main()
