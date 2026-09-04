"""Sizer correlation set is book-derived, with per-pair provenance (2026-07-08, TF2 #3).

The sizer's diversification gauge hardcoded the GROY/URC/GMX trio at 0.50-if-missing over a
hardcoded /3.0 — so a removed holding kept being averaged in at a phantom 0.50, a new ballast
never joined, and a missing correlation silently read as real diversification. Pins:
  * the ballast set = barbell_weights keys minus the spear (membership is data);
  * a departed name contributes nothing (no phantom-0.50 residue);
  * every pair is stamped measured|default, and defaults are enumerated.
"""
import json
import os
import tempfile
import unittest

from engines.sizer import PortfolioSizer

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "v5_config.json")

_CORR = {"AGA.V": {"GROY": 0.20, "URC.TO": 0.40, "GMX.TO": 0.60}}
_VOLS = {"AGA.V": 0.40, "GROY": 0.30, "GMX.TO": 0.32, "URC.TO": 0.35}
_LIMITS = {"aga_price": 0.72, "aga_adv": 500000, "port_vol": 0.40, "vix": 16.5}


def _size(sizer, corr):
    return sizer.calculate_sizing(10000.0, 1.50, _VOLS, corr, 30.0, _LIMITS)


def _temp_config(barbell):
    cfg = json.load(open(_CONFIG))
    cfg["barbell_weights"] = barbell
    tmp = tempfile.mktemp(suffix=".json")
    with open(tmp, "w") as f:
        json.dump(cfg, f)
    return tmp


#: a PINNED three-ballast book. These tests are about the averaging/provenance MECHANISM, so they
#: must not read the live barbell — they used to, and rotted when URC.TO and GMX.TO left the book
#: (the very failure mode the module docstring above is about). The names here are fixtures.
_PINNED_BARBELL = {"AGA.V": 0.60, "GROY": 0.15, "URC.TO": 0.15, "GMX.TO": 0.10}


class SizerCorrMembershipTests(unittest.TestCase):
    def test_full_book_matches_legacy_average(self):
        tmp = _temp_config(dict(_PINNED_BARBELL))
        try:
            res = _size(PortfolioSizer(tmp), _CORR)
            self.assertAlmostEqual(res["avg_ballast_corr"], round((0.20 + 0.40 + 0.60) / 3.0, 2))
            self.assertEqual(res["corr_source"],
                             {"GROY": "measured", "URC.TO": "measured", "GMX.TO": "measured"})
            self.assertEqual(res["corr_default_pairs"], [])
        finally:
            os.remove(tmp)

    def test_missing_pair_is_stamped_default_not_silently_real(self):
        corr = {"AGA.V": {"GROY": 0.20, "GMX.TO": 0.60}}          # URC.TO pair missing
        tmp = _temp_config(dict(_PINNED_BARBELL))
        try:
            res = _size(PortfolioSizer(tmp), corr)
            self.assertEqual(res["corr_source"]["URC.TO"], "default")
            self.assertEqual(res["corr_default_pairs"], ["URC.TO"])
            self.assertAlmostEqual(res["avg_ballast_corr"], round((0.20 + 0.50 + 0.60) / 3.0, 2))
        finally:
            os.remove(tmp)

    def test_live_barbell_membership_drives_the_gauge(self):
        # the live-config half, kept SEPARATE and derived: whatever the book holds today is what
        # the gauge averages — no phantom, no literal.
        from tests.helpers import live_ballasts
        res = _size(PortfolioSizer(_CONFIG), _CORR)
        self.assertEqual(set(res["corr_source"]), live_ballasts())

    def test_removed_holding_leaves_no_phantom(self):
        # cut URC.TO from the barbell: the gauge must average TWO ballasts, not a phantom trio
        tmp = _temp_config({"AGA.V": 0.60, "GROY": 0.25, "GMX.TO": 0.15})
        try:
            res = _size(PortfolioSizer(tmp), _CORR)
            self.assertNotIn("URC.TO", res["corr_source"])
            self.assertAlmostEqual(res["avg_ballast_corr"], round((0.20 + 0.60) / 2.0, 2))
        finally:
            os.remove(tmp)

    def test_new_ballast_joins_without_a_code_edit(self):
        tmp = _temp_config({"AGA.V": 0.60, "GROY": 0.15, "URC.TO": 0.10,
                            "GMX.TO": 0.10, "NEW.TO": 0.05})
        try:
            res = _size(PortfolioSizer(tmp), _CORR)
            self.assertIn("NEW.TO", res["corr_source"])
            self.assertEqual(res["corr_source"]["NEW.TO"], "default")   # no pair yet — visible, not fictive
        finally:
            os.remove(tmp)


if __name__ == "__main__":
    unittest.main()
