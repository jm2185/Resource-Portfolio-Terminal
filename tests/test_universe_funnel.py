"""
Run: ``python -m unittest tests.test_universe_funnel -v``

Locks the discovery funnel's two new seams:
  * add_candidate — the scout→universe feedback loop (grounded write of a screen-input record,
    dedupe-by-ticker, immediate slot-survival feedback). File I/O is mocked.
  * graduate_candidate — auto-resolution of a BLANK receipt ref from the latest Memory entry for
    the ticker tagged with the role (verifier / anti_scout / forensic), so the one-action gauntlet
    graduates without hand-collected ids. The explicit-ref path still works.
"""

import copy
import unittest
from unittest import mock

import discovery_screen as ds
from mcp_server import core


def _universe():
    return {"schema": {}, "screen_config": {}, "candidates": [
        {"ticker": "OLD.V", "vehicle": "developer", "commodity": "silver", "slots": ["silver-spear"],
         "stage": "pfs", "source": "seed"},
    ]}


class AddCandidateTest(unittest.TestCase):
    def setUp(self):
        self._ro = mock.patch.object(core, "READONLY", False); self._ro.start(); self.addCleanup(self._ro.stop)
        self.written = {}
        self.p_load = mock.patch.object(ds, "load_universe", side_effect=lambda *_: copy.deepcopy(_universe()))
        self.p_write = mock.patch.object(core, "_write_universe", side_effect=lambda u: self.written.update(cfg=copy.deepcopy(u)))
        for p in (self.p_load, self.p_write):
            p.start(); self.addCleanup(p.stop)

    def test_requires_source(self):
        res = core.add_candidate("NEW.V", vehicle="explorer", commodity="silver", slot="silver-spear")
        self.assertFalse(res["ok"])
        self.assertIn("source", res["error"])
        self.assertNotIn("cfg", self.written)

    def test_adds_pea_explorer_and_it_survives_the_spear_slot(self):
        res = core.add_candidate("NEW.V", vehicle="explorer", commodity="silver", slot="silver-spear",
                                 stage="pea", source="issuer PR 2026-06-01",
                                 fields_json='{"fraser_index": 80, "mcap_cad_m": 60, "runway_months": 24, "dilution_annual": 0.1}')
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "added")
        self.assertEqual(self.written["cfg"]["candidates"][-1]["ticker"], "NEW.V")
        self.assertEqual(res["record"]["fraser_index"], 80.0)         # numeric coerced from fields_json
        self.assertTrue(res["screen_check"]["silver-spear"]["survives"])

    def test_pfs_developer_is_killed_at_the_stage_gate(self):
        res = core.add_candidate("ADV.V", vehicle="developer", commodity="silver", slot="silver-spear",
                                 stage="pfs", source="peer set")
        self.assertTrue(res["ok"])
        self.assertFalse(res["screen_check"]["silver-spear"]["survives"])
        self.assertEqual(res["screen_check"]["silver-spear"]["killed_at"], "stage_window")

    def test_dedupes_by_ticker_updates_in_place(self):
        res = core.add_candidate("OLD.V", vehicle="developer", commodity="silver", slot="silver-spear",
                                 stage="pea", source="re-reviewed: now PEA")
        self.assertEqual(res["action"], "updated")
        cands = self.written["cfg"]["candidates"]
        self.assertEqual(len(cands), 1)                               # not duplicated
        self.assertEqual(next(c for c in cands if c["ticker"] == "OLD.V")["stage"], "pea")

    def test_readonly_refuses(self):
        with mock.patch.object(core, "READONLY", True):
            res = core.add_candidate("NEW.V", vehicle="explorer", commodity="silver",
                                     slot="silver-spear", source="x")
        self.assertFalse(res["ok"])
        self.assertNotIn("cfg", self.written)


class _FakeMem:
    """Minimal Living Memory stub: tagged entries per role + a graduation writer."""
    def __init__(self, tagged):
        self._tagged = tagged                     # {role: {"id":..., "ticker":...}}
        self.by_id = {e["id"]: e for e in tagged.values()}
        self.written = []

    def query(self, *, ticker=None, type=None, tag=None, limit=50, newest_first=True, **_):
        if tag and tag in self._tagged and (self._tagged[tag]["ticker"].upper() == str(ticker).upper()):
            return [self._tagged[tag]]
        return []                                  # no scout_candidate, etc.

    def get(self, rid):
        return self.by_id.get(str(rid))

    def write(self, type, *, ticker=None, text="", tags=None, refs=None, meta=None, source=""):
        e = {"id": f"grad_{len(self.written)}", "ticker": ticker, "type": type, "refs": refs}
        self.written.append(e)
        return e


class GraduateAutoResolveTest(unittest.TestCase):
    def _mem(self, ticker="NEW.V"):
        return _FakeMem({
            "verifier":   {"id": "m_v", "ticker": ticker},
            "anti_scout": {"id": "m_a", "ticker": ticker},
            "forensic":   {"id": "m_f", "ticker": ticker},
        })

    def test_blank_refs_autoresolve_from_tags(self):
        mem = self._mem()
        with mock.patch.object(core, "_living_memory", return_value=mem):
            res = core.graduate_candidate("NEW.V")            # all refs blank
        self.assertTrue(res["ok"])
        self.assertEqual(res["receipts"], {"verifier": "m_v", "anti_scout": "m_a", "forensic": "m_f"})
        self.assertEqual(mem.written[-1]["type"], "graduation")

    def test_missing_tagged_receipt_refuses(self):
        mem = _FakeMem({"verifier": {"id": "m_v", "ticker": "NEW.V"},
                        "anti_scout": {"id": "m_a", "ticker": "NEW.V"}})   # no forensic
        with mock.patch.object(core, "_living_memory", return_value=mem):
            res = core.graduate_candidate("NEW.V")
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("refused"))
        self.assertIn("forensic", str(res["error"]))

    def test_explicit_refs_still_work(self):
        mem = self._mem()
        with mock.patch.object(core, "_living_memory", return_value=mem):
            res = core.graduate_candidate("NEW.V", verifier_ref="m_v", anti_scout_ref="m_a",
                                          forensic_ref="m_f")
        self.assertTrue(res["ok"])

    def test_wrong_ticker_ref_refuses(self):
        mem = _FakeMem({"verifier": {"id": "m_v", "ticker": "OTHER.V"},
                        "anti_scout": {"id": "m_a", "ticker": "NEW.V"},
                        "forensic": {"id": "m_f", "ticker": "NEW.V"}})
        with mock.patch.object(core, "_living_memory", return_value=mem):
            # explicit wrong-ticker ref is caught by the ticker-match guard
            res = core.graduate_candidate("NEW.V", verifier_ref="m_v", anti_scout_ref="m_a",
                                          forensic_ref="m_f")
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("refused"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
