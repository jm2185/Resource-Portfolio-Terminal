"""
Tests for the M3 screen renderers (matrix/screens/*) — Forge-Matrix M3. Each screen must produce an
encodable 64x32 RGB frame, survive an empty/degraded MatrixState, and tolerate per-name None fields
(quick-monitoring panel must never crash on missing data). Layout exactness is judged offline (PNG),
not asserted pixel-by-pixel; these pin the contract + robustness.
"""
import unittest

from matrix import encode_anim
from matrix import encoder as enc
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
    def test_all_screens_render_encodable_rgb(self):
        for name, render in screens.SCREENS.items():
            img = render(MS)
            self.assertEqual(img.size, (128, 64), name)
            self.assertEqual(img.mode, "RGB", name)
            self.assertEqual(len(encode_anim([img], [100])), 4 + enc.frame_bytes(), name)

    def test_screens_survive_empty_state(self):
        for name, render in screens.SCREENS.items():
            self.assertEqual(render(MatrixState()).size, (128, 64), name)

    def test_screens_survive_partial_none_fields(self):
        ms = MatrixState(watchlist=(WatchItem("AGA"),), stress=(StressIndex("VIX"),))
        for name, render in screens.SCREENS.items():
            render(ms)            # None last/rating/rho/value must not raise

    def test_expected_screen_set(self):
        self.assertEqual(set(screens.SCREENS),
                         {"regime_watchlist", "conviction_board", "asymmetry", "stress", "detail",
                          "no_data"})

    def test_stale_marker_drawn_top_right(self):
        img = screens.regime_watchlist(MatrixState(stale=True))
        self.assertEqual(img.load()[base.W - 1, 0], base.cfg.PALETTE["stress"])

    def test_dir_short_extracts_action_keyword(self):
        from matrix.screens.conviction_board import _dir_short
        self.assertEqual(_dir_short("BELOW FLOOR — ACCUMULATE"), "ACC")   # action, not "BELO"
        self.assertEqual(_dir_short("HOLD slot vs U-UN.T"), "HOLD")
        self.assertEqual(_dir_short("TRIM"), "TRIM")
        self.assertEqual(_dir_short(""), "")

    def test_stress_value_precision(self):
        # Full-width stress rows have room for 2 decimals (2.2 -> '2.19', VIX 18.42), tapering for big
        # numbers so the right-aligned value never crowds the label.
        from matrix.screens.stress import _fmt_val
        self.assertEqual(_fmt_val(2.19), "2.19")
        self.assertEqual(_fmt_val(18.42), "18.42")
        self.assertEqual(_fmt_val(-0.55), "-0.55")
        self.assertEqual(_fmt_val(120.34), "120.3")
        self.assertEqual(_fmt_val(1500.0), "1500")
        self.assertEqual(_fmt_val(None), "--")

    def test_sparkline_draws_and_tolerates_short_input(self):
        from PIL import Image
        img = Image.new("RGB", (128, 64))
        base.draw_sparkline(img, 2, 31, 100, 18, [1, 3, 2, 5, 4, 6], (0, 240, 90), axis=(80, 80, 80))
        self.assertTrue(any(img.load()[x, y] != (0, 0, 0) for x in range(2, 102) for y in range(31, 49)))
        base.draw_sparkline(img, 0, 0, 10, 10, [1], (255, 255, 255))   # <2 points -> no crash


if __name__ == "__main__":
    unittest.main()


class NoDataCardTests(unittest.TestCase):
    """A blank BALANCED screen is a REGIME CLAIM the panel isn't entitled to make. Engine down (or a
    payload carrying nothing usable) must render as an explicit NO ENGINE card, not as calm defaults."""

    def test_default_state_would_have_claimed_balanced(self):
        self.assertEqual(MatrixState().net_tilt, "BALANCED")   # the trap this card exists for

    def test_card_renders_full_panel(self):
        img = screens.no_data(MatrixState(no_data=True, stale=True))
        self.assertEqual(img.size, (128, 64))

    def test_card_paints_red_edges_no_live_screen_does(self):
        img = screens.no_data(MatrixState(no_data=True))
        px = img.load()
        self.assertEqual(px[0, 0], base.cfg.PALETTE["stress"])
        self.assertEqual(px[base.W - 1, base.H - 1], base.cfg.PALETTE["stress"])
        # a live screen leaves the bottom edge alone -> the two are never confusable
        self.assertNotEqual(screens.regime_watchlist(MatrixState()).load()[0, base.H - 1],
                            base.cfg.PALETTE["stress"])

    def test_blind_duration_is_never_fabricated(self):
        from matrix.screens.no_data import _blind_for
        self.assertEqual(_blind_for(MatrixState()), "")                       # no build time -> silent
        self.assertEqual(_blind_for(MatrixState(generated_at=1000.0), now=1030.0), "30s")
        self.assertEqual(_blind_for(MatrixState(generated_at=1000.0), now=1600.0), "10m")
        self.assertEqual(_blind_for(MatrixState(generated_at=1000.0), now=1000.0 + 7200), "2h")
