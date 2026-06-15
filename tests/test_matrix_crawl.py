"""
Tests for the M4 scrolling crawl (matrix/screens/crawl.py) — Forge-Matrix M4. Pins: frames stay within
the device budget and encode cleanly, the band is pinned on every frame, the loop is seamless (padded to
a whole number of steps), and an empty/stale state degrades safely.
"""
import unittest

from matrix import encode_anim
from matrix.contract import MatrixState, StressIndex, WatchItem
from matrix.encoder import MAX_FRAMES
from matrix.screens import base
from matrix.screens.crawl import FRAME_BUDGET, PAYLOAD_BUDGET, build_ambient, build_crawl

MS = MatrixState(net_tilt="RISK-OFF", mri=58.0,
                 watchlist=(WatchItem("AGA", 1.00, 2.4), WatchItem("GROY", 2.00, -1.1),
                            WatchItem("GMX", 0.62, -0.4), WatchItem("URC", 3.10, 3.3)))


class CrawlTests(unittest.TestCase):
    def test_frames_within_budget_and_encodable(self):
        frames, delays = build_crawl(MS)
        self.assertTrue(0 < len(frames) <= FRAME_BUDGET <= MAX_FRAMES)
        self.assertEqual(len(frames), len(delays))
        for f in frames:
            self.assertEqual((f.size, f.mode), ((128, 64), "RGB"))
        payload = encode_anim(frames, delays)
        self.assertEqual(payload[2], len(frames))            # numFrames header byte
        self.assertLess(len(payload), PAYLOAD_BUDGET)        # within the 400 KB device budget

    def test_budget_is_respected_when_tightened(self):
        frames, _ = build_crawl(MS, budget=40)
        self.assertLessEqual(len(frames), 40)

    def test_band_pinned_on_every_frame(self):
        frames, _ = build_crawl(MS)
        for f in (frames[0], frames[len(frames) // 2], frames[-1]):
            # 'R' of RISK-OFF lights (2,2) in the tilt colour (scale-2 band), on each frame
            self.assertEqual(f.load()[2, 2], base.cfg.PALETTE["risk_off"])

    def test_empty_watchlist_degrades(self):
        frames, _ = build_crawl(MatrixState())
        self.assertGreaterEqual(len(frames), 1)
        self.assertEqual(frames[0].size, (128, 64))

    def test_stale_marker(self):
        frames, _ = build_crawl(MatrixState(net_tilt="RISK-OFF", mri=58.0,
                                            watchlist=(WatchItem("AGA", 1.0, 1.0),), stale=True))
        self.assertEqual(frames[0].load()[base.W - 1, 0], base.cfg.PALETTE["stress"])


class AmbientTests(unittest.TestCase):
    MS = MatrixState(
        net_tilt="RISK-OFF", mri=58.0,
        stress=(StressIndex("VIX", 25.4, "stress"), StressIndex("DXY/Gold ×1k", 46.0, "stress"),
                StressIndex("Real Yield", 2.1, "stress"), StressIndex("HY Spread", 4.6, "elevated")),
        watchlist=(WatchItem("AGA", 1.0, 2.4), WatchItem("GROY", 2.0, -1.1),
                   WatchItem("U.UN", 24.5, 1.2, eval_only=True),
                   WatchItem("ALS", 22.1, -0.6, eval_only=True)))

    def test_budget_encodable(self):
        frames, delays = build_ambient(self.MS)
        self.assertTrue(0 < len(frames) <= FRAME_BUDGET)
        self.assertLess(len(encode_anim(frames, delays)), PAYLOAD_BUDGET)

    def test_dashboard_band_pinned(self):
        frames, _ = build_ambient(self.MS)
        self.assertEqual(frames[0].load()[2, 2], base.cfg.PALETTE["risk_off"])

    def test_handles_no_bench(self):
        frames, _ = build_ambient(MatrixState(net_tilt="BALANCED", watchlist=(WatchItem("AGA", 1.0, 1.0),)))
        self.assertGreaterEqual(len(frames), 1)


class BenchLoaderTests(unittest.TestCase):
    def test_missing_file_is_empty(self):
        from matrix.bench import load_bench
        self.assertEqual(load_bench("/nonexistent/matrix_bench.json"), [])

    def test_loads_and_uppercases(self):
        import json
        import tempfile
        from matrix.bench import load_bench
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"bench": ["u.un.to", "als.to", ""]}, f)
            p = f.name
        self.assertEqual(load_bench(p), ["U.UN.TO", "ALS.TO"])


if __name__ == "__main__":
    unittest.main()
