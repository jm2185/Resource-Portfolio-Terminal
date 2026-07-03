"""The zero-intrinsic stamp-guard (2026-07-02 reassessment, Phase 0.3). A snapshot whose central
estimate did not compute (intrinsic missing or exactly 0.0) is a FAILED valuation — stamping it with
a real band (SOLID / FAIR) fabricates a valuation the engine never made and floods the immutable
ledger (the 80 phantom GROY zeros). This pins: auto-cadence never stamps one; an explicit write is
flagged; a real valuation is untouched; and grading excludes both the flagged rows and pre-existing
phantom zeros written before the guard.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import valuation_ledger as vl
import replay


def _snap(ticker="GROY", intrinsic=0.0, price=4.44, band="SOLID / FAIR"):
    return {"ticker": ticker, "archetype": "asset_light_yield", "price": price,
            "intrinsic": intrinsic, "band": band, "directive": "QUALITY — CORE HOLD",
            "ladder": {"floor": 4.45, "base": intrinsic}}


class ZeroIntrinsicStampGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.led = vl.ValuationLedger(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_auto_cadence_refuses_a_failed_valuation(self):
        # material_change / daily cadence must NOT stamp a phantom SOLID/FAIR row
        self.assertIsNone(self.led.maybe_record(_snap(intrinsic=0.0), trigger="material_change"))
        self.assertEqual(self.led.all(), [])

    def test_auto_cadence_records_a_real_valuation(self):
        rec = self.led.maybe_record(_snap(intrinsic=3.65), trigger="material_change")
        self.assertIsNotNone(rec)
        self.assertNotIn("valuation_failed", rec)

    def test_explicit_write_of_a_failed_valuation_is_flagged_not_silent(self):
        rec = self.led.record(_snap(intrinsic=0.0), trigger="decision")
        self.assertTrue(rec.get("valuation_failed"))     # honest flag, not a silent SOLID/FAIR

    def test_none_intrinsic_is_a_failed_valuation(self):
        self.assertTrue(vl.valuation_failed({"intrinsic": None}))
        self.assertTrue(vl.valuation_failed({"intrinsic": 0.0}))
        self.assertFalse(vl.valuation_failed({"intrinsic": 3.65}))

    def test_grader_excludes_phantom_zeros_written_before_the_guard(self):
        # simulate a pre-guard phantom row (intrinsic 0.0, NO flag) landing directly in the file
        import json
        with open(self.tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({**_snap(intrinsic=0.0), "id": "old1", "ts": "2026-06-20T00:00:00Z",
                                 "trigger": "material_change", "schema_version": vl.SCHEMA_VERSION}) + "\n")

        class _Hist:
            def close_on(self, *_a, **_k):
                return {"date": "2026-09-20", "close": 5.0}

        grades = replay.grade_ledger(self.led, _Hist(), horizon_days=90)
        self.assertEqual(grades, [])                      # the phantom zero is never graded


if __name__ == "__main__":
    unittest.main()
