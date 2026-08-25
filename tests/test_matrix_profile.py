"""
Tests for M2 device-claim profile (matrix/profile.py) — pure patch/verify logic + injected-I/O claim.
The patch must be version-safe: only touch keys the device actually reports.
"""
import unittest

from matrix import profile

CFG = {"dGif": False, "dStock": True, "dWeath": True, "dMlb": True,
       "stocks": "AAPL,MSFT", "bright": 50, "twelveDataKey": ""}


class PatchTests(unittest.TestCase):
    def test_patch_sets_gif_on_natives_off_stocks_cleared(self):
        p = profile.commodityex_patch(CFG)
        self.assertEqual(p["dGif"], "true")
        self.assertEqual(p["dStock"], "false")
        self.assertEqual(p["dWeath"], "false")
        self.assertEqual(p["stocks"], "")

    def test_patch_only_includes_existing_keys(self):
        p = profile.commodityex_patch(CFG)
        self.assertNotIn("dNba", p)          # absent from CFG -> not invented (version-safe)
        self.assertNotIn("dNfl", p)

    def test_patch_empty_config_is_empty(self):
        self.assertEqual(profile.commodityex_patch({}), {})


class VerifyTests(unittest.TestCase):
    def test_owns_panel_when_gif_on_natives_off(self):
        v = profile.verify({"dGif": "true", "dStock": "false", "dWeath": "false", "stocks": ""})
        self.assertTrue(v["gif_on"])
        self.assertEqual(v["natives_on"], [])
        self.assertTrue(v["stocks_cleared"])
        self.assertTrue(v["owns_panel"])

    def test_not_owns_panel_when_a_native_on(self):
        v = profile.verify({"dGif": "true", "dStock": "true"})
        self.assertIn("dStock", v["natives_on"])
        self.assertFalse(v["owns_panel"])


class ClaimTests(unittest.TestCase):
    def _store(self):
        return {"cfg": dict(CFG)}

    def test_dry_run_does_not_write(self):
        store = self._store()
        res = profile.claim_device("h", reader=lambda h: store["cfg"],
                                   writer=lambda h, p, **k: store["cfg"].update(p))
        self.assertFalse(res["applied"])
        self.assertEqual(store["cfg"]["dGif"], False)        # untouched

    def test_confirm_applies_and_verifies(self):
        store = self._store()

        def writer(h, p, **k):
            store["cfg"].update(p)
            return "ok"

        res = profile.claim_device("h", confirm=True, reader=lambda h: store["cfg"], writer=writer)
        self.assertTrue(res["applied"])
        self.assertTrue(res["verify"]["owns_panel"])
        self.assertEqual(store["cfg"]["stocks"], "")


if __name__ == "__main__":
    unittest.main()


class EnsureOwnedTests(unittest.TestCase):
    """The ownership sentinel: re-assert the claim ONLY when the panel has drifted back to its own
    content. A healthy device must be a pure read — this runs on a loop, and every write is flash."""

    OWNED = {"dGif": "true", "dStock": "false", "dWeath": "false", "stocks": ""}

    def _io(self, cfg):
        store = {"cfg": dict(cfg), "writes": 0}

        def reader(h):
            return dict(store["cfg"])

        def writer(h, patch, **k):
            store["writes"] += 1
            store["cfg"].update(patch)
            return "ok"

        return store, reader, writer

    def test_healthy_device_is_a_pure_read_no_write(self):
        store, reader, writer = self._io(self.OWNED)
        res = profile.ensure_owned("h", reader=reader, writer=writer)
        self.assertTrue(res["owned"])
        self.assertFalse(res["reclaimed"])
        self.assertEqual(store["writes"], 0)          # flash-wear: healthy never writes

    def test_reverted_to_factory_is_reclaimed(self):
        # the reported failure: device back on its native screens, our anim no longer shown
        store, reader, writer = self._io({"dGif": "false", "dStock": "true", "dWeath": "true",
                                          "stocks": "AAPL,MSFT"})
        res = profile.ensure_owned("h", reader=reader, writer=writer)
        self.assertTrue(res["reclaimed"])
        self.assertTrue(res["owned"])                 # verified AFTER the write, not assumed
        self.assertEqual(store["writes"], 1)
        self.assertEqual(store["cfg"]["dGif"], "true")
        self.assertEqual(store["cfg"]["dStock"], "false")
        self.assertEqual(store["cfg"]["stocks"], "")

    def test_reclaim_names_what_took_the_panel(self):
        store, reader, writer = self._io({"dGif": "false", "dStock": "true", "dWeath": "false"})
        res = profile.ensure_owned("h", reader=reader, writer=writer)
        self.assertIn("dStock", res["lost"])          # a native screen came back
        self.assertIn("dGif", res["lost"])            # and our anim slot was switched off

    def test_single_native_re_enabled_is_reclaimed(self):
        # dGif still on, but one native screen re-enabled in the device web UI steals rotation slots
        store, reader, writer = self._io({"dGif": "true", "dNhl": "true", "stocks": ""})
        res = profile.ensure_owned("h", reader=reader, writer=writer)
        self.assertTrue(res["reclaimed"])
        self.assertEqual(store["cfg"]["dNhl"], "false")

    def test_unknown_firmware_refuses_to_invent_keys(self):
        store, reader, writer = self._io({"someOtherKey": 1})
        res = profile.ensure_owned("h", reader=reader, writer=writer)
        self.assertFalse(res["owned"])
        self.assertFalse(res["reclaimed"])
        self.assertEqual(store["writes"], 0)          # nothing safe to write -> say so, don't guess
        self.assertIn("cannot re-claim", res["note"])


class ObserveOnlyTests(unittest.TestCase):
    """repair=False: keep REPORTING a lost panel but stop writing. For a device that won't hold the
    claim — retrying forever is a flash-wear loop and a panel that reloads on every attempt."""

    def _io(self):
        store = {"cfg": {"dGif": "false", "dStock": "true"}, "writes": 0}
        return store, (lambda h: dict(store["cfg"])), (lambda h, p, **k: (store.__setitem__("writes", store["writes"] + 1), store["cfg"].update(p), "ok")[-1])

    def test_observe_only_reports_the_loss_without_writing(self):
        store, reader, writer = self._io()
        res = profile.ensure_owned("h", reader=reader, writer=writer, repair=False)
        self.assertFalse(res["owned"])
        self.assertFalse(res["reclaimed"])
        self.assertIn("dStock", res["lost"])          # still visible
        self.assertEqual(store["writes"], 0)          # but no flash write

    def test_repair_true_still_writes(self):
        store, reader, writer = self._io()
        profile.ensure_owned("h", reader=reader, writer=writer, repair=True)
        self.assertEqual(store["writes"], 1)

    def test_observe_only_on_a_healthy_device_is_just_owned(self):
        store = {"cfg": {"dGif": "true", "dStock": "false"}}
        res = profile.ensure_owned("h", reader=lambda h: dict(store["cfg"]),
                                   writer=lambda h, p, **k: "ok", repair=False)
        self.assertTrue(res["owned"])
