"""
Tests for the catalyst calendar (catalyst_calendar.py, Forge M1).

Pins the acceptance criteria as executable guarantees:
  * a catalyst is a WINDOW — query returns entries whose [start,end] overlaps [now, now+within_days];
  * name vs macro filtering — ticker=None includes macro (ticker:null) events; a named query excludes
    other names but can fold in macro via include_macro;
  * supersede — a superseding edit HIDES the original from query but PRESERVES it in the file;
  * the macro seeder is grounded-or-silent (rule-deterministic cadences only; no invented FOMC) and
    idempotent.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone

import catalyst_calendar as cc


# a fixed "now" so every window test is deterministic — a Wednesday
NOW = "2026-06-10T00:00:00Z"


class CalendarBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.cal = cc.CatalystCalendar(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)


class WindowQueryTests(CalendarBase):
    def test_within_days_overlap_only(self):
        # in-window (Q3, overlaps next 30d? starts 2026-07-01, 21d out) -> YES at within_days=30
        self.cal.write(kind="drill_result", title="Q3 Nevada drill", ticker="AGA.V",
                       window_start="2026-07-01", window_end="2026-09-30")
        # far future (starts >30d out) -> NO at 30, YES at 200
        self.cal.write(kind="pea", title="PEA 2027", ticker="AGA.V",
                       window_start="2027-01-01", window_end="2027-03-31")
        # already past (ended before now) -> never
        self.cal.write(kind="assay", title="old assays", ticker="AGA.V",
                       window_start="2026-04-01", window_end="2026-05-01")
        within30 = self.cal.query("AGA.V", within_days=30, now=NOW)
        self.assertEqual([e["title"] for e in within30], ["Q3 Nevada drill"])
        within365 = self.cal.query("AGA.V", within_days=365, now=NOW)
        self.assertEqual(len(within365), 2)                      # the past one stays excluded

    def test_currently_open_window_is_included(self):
        # window straddling now (started yesterday, ends in a week) overlaps [now, now+1]
        self.cal.write(kind="financing_window", title="open raise", ticker="AGA.V",
                       window_start="2026-06-09", window_end="2026-06-17")
        hits = self.cal.query("AGA.V", within_days=1, now=NOW)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["_window_open"])

    def test_has_within_and_next_for(self):
        self.cal.write(kind="drill_result", title="soon", ticker="AGA.V",
                       window_start="2026-06-20", window_end="2026-06-25")
        self.assertTrue(self.cal.has_within("AGA.V", 30, now=NOW))
        self.assertFalse(self.cal.has_within("AGA.V", 5, now=NOW))   # 10d out, not within 5
        nxt = self.cal.next_for("AGA.V", now=NOW)
        self.assertEqual(nxt["title"], "soon")


class MacroFilterTests(CalendarBase):
    def setUp(self):
        super().setUp()
        self.cal.write(kind="drill_result", title="AGA drill", ticker="AGA.V",
                       window_start="2026-06-20", window_end="2026-06-25")
        self.cal.write(kind="royalty_payment", title="GROY Q2", ticker="GROY",
                       window_start="2026-06-22", window_end="2026-06-22")
        self.cal.write(kind="macro", macro_kind="fomc", title="FOMC", ticker=None,
                       window_start="2026-06-17", window_end="2026-06-18", source="manual",
                       source_url="https://www.federalreserve.gov/")

    def test_ticker_none_includes_macro_and_all_names(self):
        allhits = self.cal.query(ticker=None, within_days=30, now=NOW)
        kinds = {e["kind"] for e in allhits}
        self.assertEqual(len(allhits), 3)
        self.assertIn("macro", kinds)

    def test_named_query_excludes_other_names_and_macro(self):
        aga = self.cal.query("AGA.V", within_days=30, now=NOW)
        self.assertEqual([e["title"] for e in aga], ["AGA drill"])

    def test_named_query_can_fold_in_macro(self):
        aga_plus = self.cal.query("AGA.V", within_days=30, include_macro=True, now=NOW)
        titles = sorted(e["title"] for e in aga_plus)
        self.assertEqual(titles, ["AGA drill", "FOMC"])


class SupersedeTests(CalendarBase):
    def test_supersede_hides_original_but_preserves_in_file(self):
        orig = self.cal.write(kind="drill_result", title="Q3 drill (guided)", ticker="AGA.V",
                              window_start="2026-07-01", window_end="2026-09-30",
                              confidence="guided")
        # the issuer slips the date — correct it
        new = self.cal.supersede(orig["id"], window_start="2026-08-01", window_end="2026-10-31",
                                 status="delayed")
        live = self.cal.query("AGA.V", within_days=365, status=None, now=NOW)
        ids = {e["id"] for e in live}
        self.assertIn(new["id"], ids)
        self.assertNotIn(orig["id"], ids)                        # original hidden from query
        # ...but preserved in the raw file (audit trail)
        raw = self.cal.all(include_markers=True)
        self.assertTrue(any(e.get("id") == orig["id"] for e in raw))
        self.assertTrue(any(e.get("supersedes") == orig["id"] for e in raw))

    def test_set_status_transitions_via_supersede(self):
        e = self.cal.write(kind="assay", title="assays", ticker="AGA.V",
                           window_start="2026-06-20", window_end="2026-06-25")
        self.cal.set_status(e["id"], "hit")
        pend = self.cal.query("AGA.V", within_days=365, status="pending", now=NOW)
        self.assertEqual(len(pend), 0)
        hit = self.cal.query("AGA.V", within_days=365, status="hit", now=NOW)
        self.assertEqual(len(hit), 1)
        # hits_by_kind surfaces it for the grammar's event:<name>
        self.assertIn("assay", self.cal.hits_by_kind("AGA.V"))


class MacroSeedTests(CalendarBase):
    def test_seed_is_grounded_and_idempotent(self):
        n = cc.seed_macro(self.cal, now=NOW, horizon_days=60)
        self.assertGreater(n, 0)
        again = cc.seed_macro(self.cal, now=NOW, horizon_days=60)
        self.assertEqual(again, 0)                               # idempotent: nothing duplicated
        macro = self.cal.query(ticker=None, within_days=60, now=NOW)
        seeded_kinds = {e["macro_kind"] for e in macro}
        self.assertIn("cot_print", seeded_kinds)                 # rule-deterministic -> seeded
        self.assertIn("nfp", seeded_kinds)
        self.assertNotIn("fomc", seeded_kinds)                   # NOT invented (Fed sets the date)

    def test_cot_lag_window_is_tue_to_fri(self):
        cc.seed_macro(self.cal, now=NOW, horizon_days=20)
        cots = [e for e in self.cal.query(ticker=None, within_days=20, now=NOW)
                if e["macro_kind"] == "cot_print"]
        self.assertTrue(cots)
        for c in cots:
            ws = datetime.fromisoformat(c["window_start"].replace("Z", "+00:00"))
            we = datetime.fromisoformat(c["window_end"].replace("Z", "+00:00"))
            self.assertEqual(ws.weekday(), 1)                    # Tuesday as-of
            self.assertEqual(we.weekday(), 4)                    # Friday release
            self.assertEqual(c["confidence"], "scheduled")


class ValidationTests(CalendarBase):
    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.cal.write(kind="not_a_kind", title="x", window_start="2026-07-01")

    def test_bad_window_rejected(self):
        with self.assertRaises(ValueError):
            self.cal.write(kind="assay", title="x", window_start="2026-09-01",
                           window_end="2026-07-01")                # end before start

    def test_scheduled_named_catalyst_requires_a_source_url(self):
        # grounded-or-silent (hard invariant #6): the firmest confidence — the one pre-commitment
        # rules trust — must be straight-to-source. Softer confidences pass but are stamped.
        with self.assertRaises(ValueError):
            self.cal.write(kind="drill_result", title="firm date, no source", ticker="AGA.V",
                           window_start="2026-08-01", confidence="scheduled")
        ok = self.cal.write(kind="drill_result", title="sourced", ticker="AGA.V",
                            window_start="2026-08-01", confidence="scheduled",
                            source_url="https://www.newsfilecorp.com/release/123456")
        self.assertTrue(ok["grounded"])
        soft = self.cal.write(kind="drill_result", title="expected Q3", ticker="AGA.V",
                              window_start="2026-08-01", confidence="estimated")
        self.assertFalse(soft["grounded"])                     # allowed, but the gap is visible
        macro = self.cal.write(kind="macro", macro_kind="cot_print", title="COT",
                               window_start="2026-08-01", confidence="scheduled")
        self.assertIsNone(macro["grounded"])                   # rule-deterministic macro: exempt


if __name__ == "__main__":
    unittest.main(verbosity=2)
