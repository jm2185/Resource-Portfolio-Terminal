"""Point-in-time hygiene scan for the research cache (2026-07-08 reassessment, TF3 2.2).

The 07-02 sweep found hand-edited entries that bypassed set(): an out-of-vocabulary
"low-med" confidence and as_of dates postdating their own fetched_at — look-ahead seams in
the PIT store. The load-time validator promised then shipped as a different (book-value)
guard; this pins the real one: violations are DETECTED and SURFACED, loading never fails.
"""
import json
import os
import tempfile
import time
import unittest

import research_cache
from research_cache import ResearchCache, pit_violations

_NOW = time.time()


def _entry(**kw):
    e = {"value": 1.0, "source": "https://example.com/filing", "as_of": "2026-06-01",
         "confidence": "med", "fetched_at": _NOW}
    e.update(kw)
    return e


class PitViolationTests(unittest.TestCase):
    def test_clean_cache_has_no_violations(self):
        self.assertEqual(pit_violations({"AGA.V": {"cash": _entry()}}), [])

    def test_out_of_vocab_confidence_flagged(self):
        v = pit_violations({"GROY": {"blue_sky": _entry(confidence="low-med")}})
        self.assertEqual([x["kind"] for x in v], ["confidence_vocab"])
        self.assertEqual(v[0]["ticker"], "GROY")

    def test_look_ahead_as_of_flagged(self):
        # as_of five days after fetched_at — the exact GROY seam shape
        v = pit_violations({"GROY": {"rerate": _entry(
            as_of=time.strftime("%Y-%m-%d", time.gmtime(_NOW + 5 * 86400)))}})
        self.assertEqual([x["kind"] for x in v], ["look_ahead_as_of"])

    def test_same_day_grace_not_flagged(self):
        # a filing dated today, fetched this morning, is NOT a look-ahead
        v = pit_violations({"AGA.V": {"cash": _entry(
            as_of=time.strftime("%Y-%m-%d", time.gmtime(_NOW)))}})
        self.assertEqual(v, [])

    def test_load_is_never_fatal_and_surfaces_flags(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            with open(tmp, "w") as f:
                json.dump({"GROY": {"blue_sky": _entry(confidence="low-med")}}, f)
            rc = ResearchCache(path=tmp)                       # must not raise
            self.assertEqual(len(rc.pit_flags), 1)
            self.assertEqual(rc.get("GROY", "blue_sky")["confidence"], "low-med")  # data intact
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_set_path_produces_clean_entries(self):
        tmp = tempfile.mktemp(suffix=".json")
        try:
            rc = ResearchCache(path=tmp)
            rc.set("AGA.V", "cash", 41.0, "https://sedarplus.ca/x", "2026-05-31", confidence="med")
            self.assertEqual(pit_violations(rc._d), [])
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


if __name__ == "__main__":
    unittest.main()
