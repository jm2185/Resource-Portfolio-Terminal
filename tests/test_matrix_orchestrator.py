"""
Tests for the M5 orchestrator (matrix/orchestrator.py) — Forge-Matrix M5. All I/O is injected, so the
tick() loop is exercised with mocks: upload-on-change, skip-on-unchanged, defer under the min-upload
interval, timed rotation, the device-button hold, stale-on-engine-down, and upload-error resilience.
"""
import unittest

from matrix.orchestrator import MatrixOrchestrator

STATE = {
    "mri": 58.0,
    "macro_tape": {"net_tilt": "RISK-OFF", "signals": [{"label": "VIX", "value": 25.0, "bias": "risk_off"}]},
    "posture": {"label": "DEFENSIVE", "cap": 0.8},
    "nodes": {"AGA.V": {"price": 1.0, "role": "The Spear", "shares": 1}},
    "conviction_mode": {"baskets": [{"ticker": "AGA.V", "rating": 8, "directive": "ACCUMULATE"}]},
}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def adv(self, dt):
        self.t += dt


def make(**kw):
    box = {"state": kw.get("state", STATE), "prices": {}, "bench": [], "focus": False}
    ups = []
    clk = Clock()

    def uploader(p):
        if kw.get("upload_raises"):
            raise RuntimeError("device unreachable")
        ups.append(p)

    o = MatrixOrchestrator(
        state_fetcher=lambda: box["state"],
        price_fetcher=lambda tk: box["prices"],
        bench_loader=lambda: box["bench"],
        ohlc_fetcher=lambda tk: [],          # no network in tests
        logo_fetcher=lambda tk: False,
        uploader=uploader,
        focus_fetcher=(lambda: box["focus"]) if kw.get("with_focus") else None,
        views=kw.get("views", ["ambient", "conviction_board"]),
        cycle_interval=10.0, ambient_dwell=10.0, min_upload_interval=5.0, clock=clk,
    )
    return o, ups, clk, box


class TickTests(unittest.TestCase):
    def test_first_tick_uploads(self):
        o, ups, _, _ = make()
        r = o.tick()
        self.assertEqual(r["action"], "upload")
        self.assertEqual(len(ups), 1)

    def test_unchanged_state_skips(self):
        o, ups, clk, _ = make()
        o.tick()
        clk.adv(6)                      # past min-upload interval
        self.assertEqual(o.tick()["action"], "skip")
        self.assertEqual(len(ups), 1)   # no second upload

    def test_change_defers_within_min_interval(self):
        o, ups, _, box = make()
        o.tick()
        box["prices"] = {"AGA.V": {"last": 1.0, "change_pct": 2.4}}   # new content, no clock advance
        self.assertEqual(o.tick()["action"], "defer")
        self.assertEqual(len(ups), 1)

    def test_change_reuploads_after_min_interval(self):
        o, ups, clk, box = make()
        o.tick()
        clk.adv(6)
        box["prices"] = {"AGA.V": {"last": 1.0, "change_pct": 2.4}}
        self.assertEqual(o.tick()["action"], "upload")
        self.assertEqual(len(ups), 2)

    def test_rotation_advances_view(self):
        o, _, clk, _ = make()
        self.assertEqual(o.tick()["view"], "ambient")
        clk.adv(11)                     # past cycle interval
        self.assertEqual(o.tick()["view"], "conviction_board")

    def test_focus_button_holds_rotation(self):
        o, _, clk, box = make(with_focus=True)
        o.tick()
        box["focus"] = True
        clk.adv(11)                     # would rotate, but the button is held
        r = o.tick()
        self.assertEqual(r["view"], "ambient")
        self.assertEqual(o._panel_idx, 0)

    def test_detail_mode_cycles_holdings_only(self):
        o, _, clk, box = make(views=["detail"])
        box["state"] = {**STATE, "conviction_mode": {"baskets": [
            {"ticker": "AGA.V", "rating": 8}, {"ticker": "GROY", "rating": 6}]}}
        box["bench"] = ["LUN.TO"]            # bench must NOT get a detail card
        self.assertEqual(len(o._panels(o.build_state())), 2)   # 2 holdings, bench excluded
        p0 = o.tick()["panel"]
        clk.adv(11)                          # rotate to the next holding
        p1 = o.tick()["panel"]
        self.assertEqual(p0[0], "detail")
        self.assertNotEqual(p0, p1)

    def test_ambient_dwells_longer_than_boards(self):
        o, _, clk, _ = make(views=["ambient", "conviction_board"])
        o.ambient_dwell, o.cycle_interval = 30.0, 10.0
        self.assertEqual(o.tick()["view"], "ambient")
        clk.adv(15)                          # < ambient dwell -> still ambient
        self.assertEqual(o.tick()["view"], "ambient")
        clk.adv(20)                          # past 30s -> rotates off ambient
        self.assertEqual(o.tick()["view"], "conviction_board")

    def test_loop_packs_one_frame_per_screen(self):
        o, _, _, _ = make(views=["ambient", "conviction_board", "asymmetry", "stress"])
        frames, delays = o.build_loop_frames(o.build_state())
        self.assertEqual(len(frames), 4)
        self.assertTrue(all(d > 0 for d in delays))

    def test_loop_first_push_uploads_single_anim(self):
        o, ups, _, _ = make(views=["conviction_board", "asymmetry"])
        r = o.push_loop()
        self.assertEqual((r["action"], r["frames"]), ("upload", 2))
        self.assertEqual(len(ups), 1)        # ONE upload holds the whole rotation

    def test_loop_skips_when_unchanged(self):
        o, ups, clk, _ = make(views=["conviction_board"])
        o.push_loop()
        clk.adv(10)
        self.assertEqual(o.push_loop()["action"], "skip")
        self.assertEqual(len(ups), 1)

    def test_loop_respects_frame_cap(self):
        o, _, _, box = make(views=["detail"])
        box["state"] = {**STATE, "conviction_mode": {"baskets": [
            {"ticker": "AGA.V"}, {"ticker": "GROY"}, {"ticker": "GMX.TO"}]}}   # 3 holdings
        o.loop_max_frames = 2
        frames, _ = o.build_loop_frames(o.build_state())
        self.assertEqual(len(frames), 2)          # capped from 3

    def test_engine_down_renders_stale_frame(self):
        o, ups, _, _ = make(state=None)
        r = o.tick()
        self.assertEqual(r["action"], "upload")
        self.assertTrue(r["stale"])
        self.assertEqual(len(ups), 1)

    def test_upload_error_is_caught_and_retries(self):
        o, _, clk, _ = make(upload_raises=True)
        self.assertEqual(o.tick()["action"], "error")
        clk.adv(6)
        self.assertEqual(o.tick()["action"], "error")   # not stuck; re-attempts


if __name__ == "__main__":
    unittest.main()
