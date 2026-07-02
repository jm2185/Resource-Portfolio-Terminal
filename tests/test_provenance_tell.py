"""The rail's provenance tells (2026-07-02 reassessment finding #2). The engine computes
``floor_degraded`` / ``quality_proxy_only`` on every rating; the cockpit rendered neither, so a
proxy/unsourced floor looked identical to a sourced one and a market-confidence-proxy Q identical to
an earned one. This pins the pure helper the rail consumes: a degraded floor and a proxy Q now
produce a visible marker, a clean name produces none. (Confirmed live on 2026-07-02: 3 of 4 held
names ran floor_degraded=True with zero visual tell.)
"""
import unittest

import commodityex_tui as t


class ProvenanceTell(unittest.TestCase):
    def test_clean_name_has_no_markers(self):
        p = t._provenance_tell({"floor_degraded": False, "quality_proxy_only": False})
        self.assertEqual(p["floor_marker"], "")
        self.assertEqual(p["q_marker"], "")
        self.assertFalse(p["floor_degraded"])
        self.assertFalse(p["quality_proxy_only"])

    def test_degraded_floor_gets_a_marker(self):
        p = t._provenance_tell({"floor_degraded": True})
        self.assertTrue(p["floor_marker"].strip())        # a non-empty visible tell
        self.assertTrue(p["floor_degraded"])

    def test_proxy_quality_gets_a_marker(self):
        p = t._provenance_tell({"quality_proxy_only": True})
        self.assertTrue(p["q_marker"].strip())
        self.assertTrue(p["quality_proxy_only"])

    def test_missing_flags_default_clean(self):
        p = t._provenance_tell({})
        self.assertEqual(p["floor_marker"], "")
        self.assertEqual(p["q_marker"], "")

    def test_none_basket_is_safe(self):
        p = t._provenance_tell(None)
        self.assertFalse(p["floor_degraded"])
        self.assertFalse(p["quality_proxy_only"])


if __name__ == "__main__":
    unittest.main()
