"""Cockpit-side Council-verdict convergence read (commodityex_tui._council_convergence — not
council.py) — must survive BOTH schemas without crashing the card.
council.py writes convergence as a dict {bull,bear,contested}; agent-written verdicts write a display
string like '58/42' with contested/convergence_label as sibling keys. The string form hit
`'str'.get(...)` and crashed the whole cockpit (the OGN.V crash)."""
import unittest

import commodityex_tui as t


class CouncilConvergenceTests(unittest.TestCase):
    def test_dict_schema_council_py(self):
        meta = {"stance": "HOLD", "convergence": {"bull": 58, "bear": 42, "contested": True}}
        conv_str, contested = t._council_convergence(meta)
        self.assertEqual(conv_str, "58/42")
        self.assertTrue(contested)

    def test_string_schema_agent_written_does_not_crash(self):
        # the exact OGN.V crash: convergence is the STRING '58/42', contested/label are siblings
        meta = {"stance": "HOLD", "directive": "FAIR VALUE — HOLD",
                "convergence": "58/42", "convergence_label": "AGREEMENT", "contested": False}
        conv_str, contested = t._council_convergence(meta)      # used to raise 'str' has no attribute 'get'
        self.assertEqual(conv_str, "58/42")
        self.assertFalse(contested)

    def test_string_schema_contested_true(self):
        meta = {"convergence": "51/49", "contested": True}
        conv_str, contested = t._council_convergence(meta)
        self.assertEqual(conv_str, "51/49")
        self.assertTrue(contested)

    def test_falls_back_to_label_when_no_numbers(self):
        conv_str, contested = t._council_convergence({"convergence_label": "AGREEMENT"})
        self.assertEqual(conv_str, "AGREEMENT")
        self.assertFalse(contested)

    def test_empty_and_nondict_meta_are_graceful(self):
        for meta in ({}, None, "garbage", []):
            conv_str, contested = t._council_convergence(meta)
            self.assertEqual(conv_str, "")
            self.assertFalse(contested)


if __name__ == "__main__":
    unittest.main()
