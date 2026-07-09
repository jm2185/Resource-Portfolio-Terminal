"""MRI input honesty (2026-07-02 reassessment finding #3). calculate_mri falls to silent plausible
defaults when a sub-input is missing, and a present-but-STALE/BASELINE metric reads as confidently as
a LIVE one. This pins the METADATA fix: the detail now carries `degraded` / `data_fabricated` /
`fabricated_inputs` / `degraded_inputs` so a regime read computed on defaults is distinguishable from
a live one. The MRI NUMBER is unchanged — the scalar-value behaviour stays pinned by test_v5_engine.
"""
import os
import unittest

from engine import MacroRegimeEngine

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "v5_config.json")


def _live(**over):
    m = {"10Y": {"value": 3.5, "status": "LIVE"}, "30Y": {"value": 3.8, "status": "LIVE"},
         "DXY": {"value": 98.0, "status": "LIVE"}, "Spreads": {"value": 2.5, "status": "LIVE"},
         "TED": {"value": 0.15, "status": "LIVE"}, "VIX": {"value": 13.0, "status": "LIVE"},
         "CFTC_Silver_Net_Longs": {"value": 65000.0, "status": "LIVE"}}
    m.update(over)
    return m


class MriInputHonesty(unittest.TestCase):
    def setUp(self):
        self.macro = MacroRegimeEngine(_CONFIG)

    def _detail(self, metrics):
        _mri, detail = self.macro.calculate_mri(metrics, 76.5, 1.0, 4.5, 2300.0, -1.2,
                                                return_detail=True)
        return detail

    def test_all_live_is_not_degraded(self):
        d = self._detail(_live())
        self.assertFalse(d["degraded"])
        self.assertFalse(d["data_fabricated"])
        self.assertEqual(d["fabricated_inputs"], [])
        self.assertEqual(d["degraded_inputs"], [])

    def test_missing_input_is_fabricated(self):
        m = _live()
        del m["VIX"]                                   # metric absent -> the hardcoded default stands in
        d = self._detail(m)
        self.assertTrue(d["degraded"])
        self.assertTrue(d["data_fabricated"])
        self.assertIn("VIX", d["fabricated_inputs"])

    def test_stale_input_is_degraded_not_fabricated(self):
        d = self._detail(_live(CFTC_Silver_Net_Longs={"value": 35000.0, "status": "INITIAL_BASELINE"}))
        self.assertTrue(d["degraded"])
        self.assertFalse(d["data_fabricated"])          # present, just not LIVE
        self.assertIn("CFTC_Silver_Net_Longs", d["degraded_inputs"])

    def test_number_unchanged_by_the_flag(self):
        # the flag is metadata only: a degraded read still returns a real scalar MRI (fail-safe),
        # never suppressed — the honesty is in the badge, not a changed number
        m = _live()
        del m["DXY"]
        mri_only = self.macro.calculate_mri(m, 76.5, 1.0, 4.5, 2300.0, -1.2)
        self.assertIsInstance(mri_only, float)
        self.assertTrue(0.0 <= mri_only <= 100.0)


class MriPositionalInputHonesty(unittest.TestCase):
    """2026-07-08 reassessment (TF3 NEW-A): the 07-02 scan covered only the seven metrics-dict
    inputs — the four POSITIONAL legs (silver / real_yield / copper / gold) carried no flag at
    all, so a cold-start fabricated real_yield=1.0 flowed into the regime read unbadged.
    ``input_status`` closes that: the caller passes each leg's feed status; absent legs are
    skipped (never guessed)."""

    def setUp(self):
        self.macro = MacroRegimeEngine(_CONFIG)

    def _detail(self, input_status):
        _mri, detail = self.macro.calculate_mri(_live(), 76.5, 1.0, 4.5, 2300.0, -1.2,
                                                return_detail=True, input_status=input_status)
        return detail

    def test_baseline_positional_leg_is_fabricated(self):
        d = self._detail({"real_yield": "INITIAL_BASELINE", "silver": "LIVE"})
        self.assertTrue(d["degraded"])
        self.assertTrue(d["data_fabricated"])
        self.assertIn("real_yield", d["fabricated_inputs"])
        self.assertNotIn("silver", d["fabricated_inputs"] + d["degraded_inputs"])

    def test_stale_positional_leg_is_degraded(self):
        d = self._detail({"silver": "DEGRADED_STALE"})
        self.assertTrue(d["degraded"])
        self.assertIn("silver", d["degraded_inputs"])

    def test_absent_statuses_are_skipped_never_guessed(self):
        d = self._detail({"copper": None})
        self.assertFalse(d["degraded"])
        d = self._detail(None)                          # default: no positional statuses at all
        self.assertFalse(d["degraded"])

    def test_number_unchanged_by_positional_flags(self):
        base, _ = self.macro.calculate_mri(_live(), 76.5, 1.0, 4.5, 2300.0, -1.2, return_detail=True)
        flagged, _ = self.macro.calculate_mri(_live(), 76.5, 1.0, 4.5, 2300.0, -1.2, return_detail=True,
                                              input_status={"real_yield": "INITIAL_BASELINE"})
        self.assertEqual(base, flagged)


class ColdStartSeedsNeverBadgeLive(unittest.TestCase):
    """The 07-02 born-LIVE fix was CFTC-only; dxy/ry seeded the identical defect. Pin all three
    cold-start statuses as INITIAL_BASELINE by reading the seed dict straight from the source
    (no engine boot — the seed literals are the contract)."""

    def test_seed_statuses(self):
        import re
        src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine.py")
        src = open(src_path, encoding="utf-8").read()
        for key in ("dxy_status", "ry_status", "cftc_status"):
            m = re.search(rf'"{key}":\s*"([A-Z_]+)"', src)
            self.assertIsNotNone(m, f"seed for {key} not found")
            self.assertEqual(m.group(1), "INITIAL_BASELINE",
                             f"cold-start {key} must never badge a fabricated default LIVE")


if __name__ == "__main__":
    unittest.main()
