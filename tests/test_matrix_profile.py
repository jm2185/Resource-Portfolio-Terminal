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
