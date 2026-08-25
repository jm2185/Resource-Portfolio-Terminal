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
        cycle_interval=10.0, ambient_dwell=10.0, min_upload_interval=5.0,
        animated_refresh_interval=kw.get("animated_refresh_interval", 60.0), clock=clk,
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

    def test_static_panel_skips_when_render_unchanged(self):
        # Edge-flicker regression: the engine /state churns a field the conviction board doesn't draw
        # (live prices/change_pct). ms-hash changes, but the rendered pixels are identical -> the panel
        # must NOT be re-uploaded (re-pushing identical bytes makes the device visibly refresh).
        o, ups, clk, box = make(views=["conviction_board"])
        o.tick()
        self.assertEqual(len(ups), 1)
        clk.adv(6)                                              # past min-upload interval
        box["prices"] = {"AGA.V": {"last": 9.99, "change_pct": 88.0}}   # board shows none of this
        r = o.tick()
        self.assertEqual(r["action"], "skip")
        self.assertEqual(r.get("reason"), "unchanged-render")
        self.assertEqual(len(ups), 1)                          # no redundant second upload

    def test_change_defers_within_min_interval(self):
        o, ups, _, box = make()
        o.tick()
        box["prices"] = {"AGA.V": {"last": 1.0, "change_pct": 2.4}}   # new content, no clock advance
        self.assertEqual(o.tick()["action"], "defer")
        self.assertEqual(len(ups), 1)

    def test_animated_screen_defers_value_churn_then_refreshes_slowly(self):
        # The ambient LOOPS on the device, so re-uploading it to show a new price RESTARTS the scroll
        # (the flash the user reports). While it stays the active panel a value change must DEFER past
        # the short min-interval and refresh only on the slow animated cadence — churn can't strobe it.
        o, ups, clk, box = make(views=["ambient"], animated_refresh_interval=60.0)
        o.tick()                                                     # ambient uploaded
        self.assertEqual(len(ups), 1)
        clk.adv(6)                                                   # past min_upload (5s)...
        box["prices"] = {"AGA.V": {"last": 1.0, "change_pct": 2.4}}  # ...but a price ticked
        self.assertEqual(o.tick()["action"], "defer")                # no reload-flash
        self.assertEqual(len(ups), 1)
        clk.adv(60)                                                  # past the animated refresh cadence
        self.assertEqual(o.tick()["action"], "upload")               # one controlled value refresh
        self.assertEqual(len(ups), 2)

    def test_static_screen_unaffected_by_animated_throttle(self):
        # The throttle is animated-only: a STATIC board still re-uploads at the normal min-interval
        # when content it actually draws changes (basket rating/directive here).
        o, ups, clk, box = make(views=["conviction_board"])
        o.tick()
        self.assertEqual(len(ups), 1)
        clk.adv(6)
        box["state"] = {**STATE, "conviction_mode":
                        {"baskets": [{"ticker": "AGA.V", "rating": 3, "directive": "TRIM"}]}}
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
        self.assertTrue(r["held"])      # pin state reported back

    def test_stamp_pin_border(self):
        from matrix.orchestrator import _stamp_pin
        from matrix import config as cfg
        from PIL import Image
        f = Image.new("RGB", (12, 8), (0, 0, 0))
        p = _stamp_pin(f)
        self.assertNotEqual(p.getpixel((0, 0)), (0, 0, 0))   # corner lit -> border drawn
        # the cue MUST be the amber attention colour, not white (a missing palette key once fell
        # back to white 'text', which is indistinguishable from ordinary panel text).
        self.assertEqual(p.getpixel((0, 0)), cfg.PALETTE["elevated"])
        self.assertNotEqual(p.getpixel((0, 0)), cfg.PALETTE["text"])
        self.assertEqual(f.getpixel((0, 0)), (0, 0, 0))      # original untouched (copy)

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


class ClaimSentinelTests(unittest.TestCase):
    """The panel-ownership sentinel. The failure it exists for: the device reverts to its factory
    screens, our render is unchanged, tick() skips forever, every upload path reports success — and
    the glass plays the device's own content. So the check must run independently of uploading."""

    def _make(self, results, interval=100.0):
        box = {"n": 0}

        def checker():
            box["n"] += 1
            r = results[min(box["n"] - 1, len(results) - 1)]
            if isinstance(r, Exception):
                raise r
            return r

        # ONE view with a huge dwell: rotation can never cause an upload, so an upload in these
        # tests means the sentinel put our content back — not a screen change.
        o, ups, clk, _ = make(views=["ambient"])
        o.ambient_dwell = o.cycle_interval = 1e6
        o.claim_checker = checker
        o.claim_check_interval = interval
        o._last_claim_check = -1e9
        return o, ups, clk, box

    OWNED = {"owned": True, "reclaimed": False}
    RECLAIMED = {"owned": True, "reclaimed": True, "lost": ["dStock", "dGif"]}
    LOST = {"owned": False, "reclaimed": False, "note": "device reports no known keys"}

    def test_injected_uploader_never_builds_a_device_checker(self):
        o, _, _, _ = make()                          # the test harness injects an uploader
        self.assertIsNone(o.claim_checker)           # so nothing here reaches for the network

    def test_healthy_panel_reports_claim_and_uploads_normally(self):
        o, ups, _, _ = self._make([self.OWNED])
        r = o.tick()
        self.assertEqual(r["action"], "upload")
        self.assertTrue(r["claim"]["owned"])
        self.assertNotIn("panel_owned", r)            # healthy result keeps its existing shape

    def test_reclaim_forces_our_content_back_onto_an_unchanged_render(self):
        # THE regression: unchanged state would skip forever while the panel showed factory content.
        o, ups, clk, _ = self._make([self.OWNED, self.RECLAIMED])
        o.tick()
        self.assertEqual(len(ups), 1)
        clk.adv(10.0)
        self.assertEqual(o.tick()["action"], "skip")  # nothing changed, no check due -> quiet
        self.assertEqual(len(ups), 1)
        clk.adv(200.0)                                # claim check now due; it reports a re-claim
        r = o.tick()
        self.assertTrue(r["claim"]["reclaimed"])
        self.assertEqual(r["action"], "upload")       # dedupe cleared -> our frame goes back up
        self.assertEqual(len(ups), 2)

    def test_check_runs_on_its_own_cadence_not_every_tick(self):
        o, _, clk, box = self._make([self.OWNED])
        o.tick()
        self.assertEqual(box["n"], 1)
        clk.adv(10.0)
        o.tick()
        self.assertEqual(box["n"], 1)                 # within the interval -> no device read
        clk.adv(200.0)
        o.tick()
        self.assertEqual(box["n"], 2)

    def test_unrecoverable_loss_is_stamped_on_the_result(self):
        o, _, _, _ = self._make([self.LOST])
        r = o.tick()
        self.assertFalse(r["panel_owned"])            # loud, not silent
        self.assertFalse(r["claim"]["owned"])

    def test_check_failure_never_breaks_the_tick(self):
        o, ups, _, _ = self._make([RuntimeError("device unreachable")])
        r = o.tick()
        self.assertEqual(r["action"], "upload")       # rendering continues regardless
        self.assertNotIn("claim", r)

    def test_self_loop_mode_also_asserts_ownership(self):
        # push_loop needs it most: one upload, then quiet for as long as the data holds.
        o, ups, clk, _ = self._make([self.OWNED, self.RECLAIMED])
        o.push_loop()
        self.assertEqual(len(ups), 1)
        clk.adv(200.0)
        r = o.push_loop()
        self.assertTrue(r["claim"]["reclaimed"])
        self.assertEqual(r["action"], "upload")
        self.assertEqual(len(ups), 2)


class ReclaimFightTests(unittest.TestCase):
    """The device fights back: it keeps re-enabling its native screens. We must NOT re-claim forever —
    each attempt is a flash write and a forced panel reload, which is what 'glitching' looks like."""

    def _make(self, interval=100.0):
        """A device that never holds the claim: every check finds it reverted and re-claims."""
        calls = []

        def checker(repair=True):
            calls.append(repair)
            if not repair:
                return {"owned": False, "reclaimed": False, "lost": ["dStock"],
                        "note": "not repairing"}
            return {"owned": True, "reclaimed": True, "lost": ["dStock"]}

        o, ups, clk, _ = make(views=["ambient"])
        o.ambient_dwell = o.cycle_interval = 1e6
        o.claim_checker = checker
        o.claim_check_interval = interval
        o._last_claim_check = -1e9
        return o, ups, clk, calls

    def _run_checks(self, o, clk, n):
        for _ in range(n):
            clk.adv(1e6)              # always past any backed-off interval
            o.tick()

    def test_only_the_first_reclaim_forces_a_reupload(self):
        o, ups, clk, _ = self._make()
        self._run_checks(o, clk, 1)
        self.assertEqual(len(ups), 1)                 # first tick uploads anyway
        self._run_checks(o, clk, 1)
        self.assertEqual(len(ups), 1)                 # 2nd re-claim must NOT force another push
        self._run_checks(o, clk, 1)
        self.assertEqual(len(ups), 1)                 # nor the 3rd — no reload-per-attempt

    def test_gives_up_writing_after_max_attempts(self):
        from matrix import config as mcfg
        o, _, clk, calls = self._make()
        self._run_checks(o, clk, mcfg.MAX_RECLAIM_ATTEMPTS + 2)
        self.assertEqual(calls[:mcfg.MAX_RECLAIM_ATTEMPTS], [True] * mcfg.MAX_RECLAIM_ATTEMPTS)
        self.assertFalse(calls[mcfg.MAX_RECLAIM_ATTEMPTS])        # then observe-only
        self.assertFalse(calls[-1])

    def test_backoff_grows_so_we_stop_hammering_the_device(self):
        o, _, clk, calls = self._make(interval=100.0)
        self.assertEqual(o._claim_interval(), 100.0)              # healthy cadence
        self._run_checks(o, clk, 1)
        self.assertEqual(o._claim_interval(), 200.0)              # 1 failed stick -> doubled
        self._run_checks(o, clk, 1)
        self.assertEqual(o._claim_interval(), 400.0)

    def test_backoff_is_capped(self):
        from matrix import config as mcfg
        o, _, clk, _ = self._make(interval=100.0)
        self._run_checks(o, clk, 12)
        self.assertLessEqual(o._claim_interval(), mcfg.CLAIM_BACKOFF_CAP_S)

    def test_a_device_that_holds_the_claim_resets_the_streak(self):
        o, _, clk, _ = self._make()
        self._run_checks(o, clk, 2)
        self.assertEqual(o._reclaim_streak, 2)
        o.claim_checker = lambda repair=True: {"owned": True, "reclaimed": False}
        self._run_checks(o, clk, 1)
        self.assertEqual(o._reclaim_streak, 0)                    # back to the healthy cadence
        self.assertEqual(o._claim_interval(), o.claim_check_interval)

    def test_zero_arg_checker_still_works(self):
        # an injected checker need not accept the repair kwarg (signature-dispatched, not TypeError)
        o, _, clk, _ = self._make()
        o.claim_checker = lambda: {"owned": True, "reclaimed": False}
        self._run_checks(o, clk, 1)
        self.assertTrue(o._panel_owned)

    def test_a_typeerror_inside_the_checker_is_not_retried_as_bad_arity(self):
        o, _, clk, _ = self._make()
        boom = []

        def checker(repair=True):
            boom.append(1)
            raise TypeError("a real bug inside the checker")

        o.claim_checker = checker
        self._run_checks(o, clk, 1)
        self.assertEqual(len(boom), 1)                            # called once, not twice
