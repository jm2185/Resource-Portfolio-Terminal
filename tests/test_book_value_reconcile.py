"""Integrity guard for the sourced book-value-per-share (the GROY 10× floor collapse). The floor math
is correct; it was fed a bad input — a book value ~10× too small (0.31 vs the real 3.13 = $722M equity
÷ 231M shares) drove GROY's margin-of-safety floor to ~$0.32 on a $2.86 name, and nothing caught it.
``reconciled_book_value`` cross-checks the value against equity÷shares (both independently sourced) so a
single corrupted field can no longer set the floor. These tests pin: clean data is a no-op, the 10×
error is caught and the self-consistent value wins, and the edges (missing equity, goodwill, bad bvps).
"""
import unittest

from research_cache import reconciled_book_value


# GROY's real filings facts (data/research_cache.json): equity $721.994M, 230,809,201 shares, no
# goodwill → book value/share = 3.128 ≈ the sourced 3.13.
EQUITY = 721_994_000
SHARES = 230_809_201
TRUE_BVPS = 3.13


class ReconcileBookValue(unittest.TestCase):
    def test_clean_data_is_a_noop(self):
        val, ok, _ = reconciled_book_value(TRUE_BVPS, EQUITY, SHARES)
        self.assertTrue(ok)
        self.assertEqual(val, TRUE_BVPS)                       # trusts the direct source

    def test_catches_the_groy_10x_too_small(self):
        val, ok, note = reconciled_book_value(0.313, EQUITY, SHARES)   # the corrupted input
        self.assertFalse(ok)                                  # flagged
        self.assertAlmostEqual(val, EQUITY / SHARES, places=4)  # equity-derived 3.13 wins, not 0.31
        self.assertIn("inconsistent", note)

    def test_catches_10x_too_large(self):
        val, ok, _ = reconciled_book_value(31.3, EQUITY, SHARES)
        self.assertFalse(ok)
        self.assertAlmostEqual(val, EQUITY / SHARES, places=4)

    def test_tangible_vs_total_gap_is_tolerated(self):
        # a legitimate <2× difference (goodwill/intangibles) must NOT trip the guard
        val, ok, _ = reconciled_book_value(3.13, EQUITY, SHARES, goodwill=200_000_000)
        self.assertTrue(ok)                                   # (722−200)/231 = 2.26, ratio 1.38 < 2
        self.assertEqual(val, 3.13)

    def test_goodwill_nets_from_equity_in_the_expected(self):
        # when bvps is missing, the derived value uses TANGIBLE equity (equity − goodwill)
        val, ok, _ = reconciled_book_value(None, EQUITY, SHARES, goodwill=100_000_000)
        self.assertFalse(ok)
        self.assertAlmostEqual(val, (EQUITY - 100_000_000) / SHARES, places=4)

    def test_no_equity_to_check_passes_through_unverified(self):
        val, ok, note = reconciled_book_value(3.13, None, None)
        self.assertTrue(ok)                                   # nothing to check against → trust it
        self.assertEqual(val, 3.13)
        self.assertIn("unverified", note)

    def test_bad_bvps_with_no_fallback_returns_none(self):
        val, ok, _ = reconciled_book_value(None, None, None)
        self.assertIsNone(val)
        self.assertFalse(ok)

    def test_zero_and_negative_are_rejected(self):
        val, ok, _ = reconciled_book_value(0, EQUITY, SHARES)      # bad bvps → equity-derived wins
        self.assertAlmostEqual(val, EQUITY / SHARES, places=4)
        self.assertFalse(ok)
        val2, ok2, _ = reconciled_book_value(3.13, -5, SHARES)     # bad equity → can't check
        self.assertTrue(ok2)
        self.assertEqual(val2, 3.13)


if __name__ == "__main__":
    unittest.main()
