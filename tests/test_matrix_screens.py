"""
Tests for the M3 screen renderers (matrix/screens/*) — Forge-Matrix M3. Each screen must produce an
encodable 64x32 RGB frame, survive an empty/degraded MatrixState, and tolerate per-name None fields
(quick-monitoring panel must never crash on missing data). Layout exactness is judged offline (PNG),
not asserted pixel-by-pixel; these pin the contract + robustness.
"""
import unittest

from matrix import encode_anim
from matrix import screens
from matrix.contract import MatrixState, StressIndex, WatchItem
from matrix.screens import base

MS = MatrixState(
    net_tilt="RISK-OFF", mri=58.0, regime_label="DEFENSIVE", posture_cap=0.8,
    stress=(StressIndex("VIX", 25.4, "stress"), StressIndex("HY Spread", 4.6, "stress"),
            StressIndex("Gold/Silver", 82.0, "elevated"), StressIndex("Copper/Gold ×1k", 1.7, "calm")),
    watchlist=(
        WatchItem("AGA", 1.00, 2.4, rating=8, directive="ACCUMULATE", rho=3.2, floor_coverage=1.85),
        WatchItem("GROY", 2.00, -1.1, rating=6, directive="HOLD", rho=1.4, floor_coverage=1.2),
        WatchItem("GMX", 0.62, 0.0, rating=5, directive="TRIM", rho=0.9, floor_coverage=0.95),
        WatchItem("URC", 3.10, 3.3, rating=7, directive="ACCUMULATE", rho=2.1, floor_coverage=1.5)),
    stale=False)


class ScreenRenderTests(unittest.TestCase):
    def test_all_screens_render_encodable_64x32_rgb(self):
        for name, render in screens.SCREENS.items():
            img = render(MS)
            self.assertEqual(img.size, (64, 32), name)
            self.assertEqual(img.mode, "RGB", name)
            self.assertEqual(len(encode_anim([img], [100])), 4102, name)   # round-trips through encoder

    def test_screens_survive_empty_state(self):
        for name, render in screens.SCREENS.items():
            self.assertEqual(render(MatrixState()).size, (64, 32), name)

    def test_screens_survive_partial_none_fields(self):
        ms = MatrixState(watchlist=(WatchItem("AGA"),), stress=(StressIndex("VIX"),))
        for name, render in screens.SCREENS.items():
            render(ms)            # None last/rating/rho/value must not raise

    def test_expected_screen_set(self):
        self.assertEqual(set(screens.SCREENS), {"regime_watchlist", "conviction_board", "asymmetry", "stress"})

    def test_stale_marker_drawn_top_right(self):
        img = screens.regime_watchlist(MatrixState(stale=True))
        self.assertEqual(img.load()[base.W - 1, 0], base.cfg.PALETTE["stress"])


if __name__ == "__main__":
    unittest.main()
