"""
Run: ``python -m unittest tests.test_book_change -v``

Locks the CHANGE object (book_change.py): the BEFORE→AFTER diff + deltas for cut / rotate /
reweight, the AGA-capped redistribution matching what remove_holding actually applies, the spear
ceiling invariant, the council/bear attachment from (injected) Living Memory, and the refusals.
Pure + injected — no engine, no TUI, no ticker.
"""
import unittest

import book_change as bc


# a 4-name book with per-name facts (lifted from an engine /state snapshot in production)
BOOK = [
    {"ticker": "AGA.V", "weight": 0.34, "role": "spear", "conviction": 8.0, "runway": 30},
    {"ticker": "GMX.TO", "weight": 0.28, "role": "ballast", "conviction": 6.0, "runway": 40},
    {"ticker": "GROY", "weight": 0.24, "role": "ballast", "conviction": 6.5, "runway": 50},
    {"ticker": "URC.TO", "weight": 0.14, "role": "ballast", "conviction": 5.0, "runway": 19},
]


class _FakeMem:
    def __init__(self, council=None, bear=None):
        self._council, self._bear = council, bear
    def latest(self, *, ticker=None, type=None):
        return self._council if type == "council_verdict" else None
    def query(self, *, ticker=None, tag=None, limit=50, **_):
        return [self._bear] if (tag == "bear" and self._bear) else []


def _w(p, tk):
    return next((r["weight"] for r in p["after"] if r["ticker"] == tk), None)


class CutTest(unittest.TestCase):
    def test_cut_redistributes_and_conserves(self):
        p = bc.propose_change({"kind": "cut", "ticker": "URC.TO"}, BOOK)
        self.assertTrue(p["ok"])
        self.assertEqual(p["kind"], "CUT")
        self.assertIsNone(_w(p, "URC.TO"))                       # gone
        self.assertAlmostEqual(sum(r["weight"] for r in p["after"]), 1.0, places=5)
        self.assertAlmostEqual(p["deltas"]["weight_freed"], 0.14, places=4)
        self.assertEqual(p["deltas"]["names"], {"before": 4, "after": 3})
        self.assertTrue(p["premortem_required"])
        self.assertEqual(p["commit"]["steps"], 2)

    def test_cut_caps_the_spear(self):
        # AGA already at the 60% ceiling: cutting a ballast must NOT push it over.
        book = [{"ticker": "AGA.V", "weight": 0.60, "role": "spear"},
                {"ticker": "GROY", "weight": 0.25, "role": "ballast"},
                {"ticker": "URC.TO", "weight": 0.15, "role": "ballast"}]
        p = bc.propose_change({"kind": "cut", "ticker": "URC.TO"}, book)
        self.assertTrue(p["ok"])
        self.assertLessEqual(_w(p, "AGA.V"), 0.60 + 1e-9)
        self.assertEqual(p["warnings"], [])

    def test_cut_refusals(self):
        self.assertIn("structural", bc.propose_change({"kind": "cut", "ticker": "AGA.V"}, BOOK)["error"])
        self.assertIn("not in the book", bc.propose_change({"kind": "cut", "ticker": "ZZZ"}, BOOK)["error"])
        two = [{"ticker": "AGA.V", "weight": 0.6}, {"ticker": "GROY", "weight": 0.4}]
        self.assertIn("no ballast", bc.propose_change({"kind": "cut", "ticker": "GROY"}, two)["error"])


class RotateTest(unittest.TestCase):
    def test_rotate_in_takes_out_weight_and_carries_facts(self):
        mem = _FakeMem(council={"id": "c1", "text": "SWAP — qualified yes."},
                       bear={"id": "b1", "text": "SILV runway 9mo — financing before Q2 or it breaks."})
        p = bc.propose_change(
            {"kind": "rotate", "out": "URC.TO", "in": "SILV",
             "in_facts": {"role": "spear", "conviction": 7.1, "runway": 9}}, BOOK, mem=mem)
        self.assertTrue(p["ok"])
        self.assertEqual(p["kind"], "ROTATE")
        self.assertAlmostEqual(_w(p, "SILV"), 0.14, places=4)          # SILV takes URC's 14%
        self.assertIsNone(_w(p, "URC.TO"))
        self.assertEqual(p["deltas"]["names"], {"before": 4, "after": 4})
        # spear share moves AGA(34) + SILV(14) = 48%
        self.assertAlmostEqual(p["deltas"]["spear_share"]["after"], 0.48, places=4)
        # min runway drops 19 (URC) -> 9 (SILV)
        self.assertEqual(p["deltas"]["min_runway"]["before"], 19.0)
        self.assertEqual(p["deltas"]["min_runway"]["after"], 9.0)
        # council + bear travel WITH the proposal
        self.assertEqual(p["council"]["id"], "c1")
        self.assertIn("financing", p["bear"]["text"])

    def test_rotate_breaching_ceiling_warns(self):
        book = [{"ticker": "AGA.V", "weight": 0.55, "role": "spear"},
                {"ticker": "URC.TO", "weight": 0.45, "role": "ballast"}]
        p = bc.propose_change({"kind": "rotate", "out": "URC.TO", "in": "SILV",
                               "in_facts": {"role": "spear"}}, book)
        self.assertTrue(p["ok"])
        self.assertTrue(any("ceiling" in w for w in p["warnings"]))   # 55%+45% spear = 100% > 60%


class ReweightTest(unittest.TestCase):
    def test_reweight_explicit_vector(self):
        p = bc.propose_change({"kind": "reweight",
                               "weights": {"AGA.V": 0.5, "GMX.TO": 0.2, "GROY": 0.2, "URC.TO": 0.1}}, BOOK)
        self.assertTrue(p["ok"])
        self.assertAlmostEqual(_w(p, "AGA.V"), 0.5, places=4)
        self.assertAlmostEqual(sum(r["weight"] for r in p["after"]), 1.0, places=5)

    def test_reweight_bad_sum_refused(self):
        p = bc.propose_change({"kind": "reweight", "weights": {"AGA.V": 0.5, "GROY": 0.3}}, BOOK)
        self.assertFalse(p["ok"])
        self.assertIn("sum to 1.0", p["error"])


class SummaryTest(unittest.TestCase):
    def test_summarize_renders_signal_first(self):
        p = bc.propose_change({"kind": "cut", "ticker": "URC.TO"}, BOOK)
        s = bc.summarize(p)
        self.assertIn("CUT · URC.TO", s)
        self.assertIn("pre-mortem required", s)
        self.assertIn("two-step", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
