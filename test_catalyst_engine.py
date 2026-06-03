"""Tests for the Phase 8 catalyst engine (signal reactivity).

Run: ``python -m unittest test_catalyst_engine``. Pure-Python, deterministic via ``as_of``.
"""

import json
import os
import tempfile
import unittest
from datetime import date

from catalyst_engine import (
    summarize_catalysts,
    build_catalyst_overlays,
    load_catalyst_feed,
    merge_catalyst_config,
    classify_headline,
    match_ticker,
    attribute,
    clean_title,
    dedupe_events,
)


class TestNoHallucination(unittest.TestCase):
    def test_item_without_title_is_discarded(self):
        s = summarize_catalysts([{"ticker": "AGA.V", "type": "drill_result", "impact": 0.8,
                                  "date": "2026-05-30"}], as_of=AOD)   # NO headline
        self.assertEqual(s["count"], 0)                                 # discarded, not fabricated

    def test_blank_title_is_discarded(self):
        s = summarize_catalysts([ev(headline="   ", date="2026-05-30")], as_of=AOD)
        self.assertEqual(s["count"], 0)

    def test_label_is_exact_source_title(self):
        s = summarize_catalysts([ev(headline="Drills 900 g/t Ag over 3m", date="2026-05-30")], as_of=AOD)
        self.assertEqual(s["recent"][0]["label"], "Drills 900 g/t Ag over 3m")  # verbatim, not summarized

    def test_clean_title_never_invents(self):
        self.assertEqual(clean_title("  Hello   world \n"), "Hello world")
        self.assertEqual(clean_title(None), "")
        self.assertEqual(clean_title(123), "")

    def test_max_age_60d_hard_filter(self):
        s = summarize_catalysts([ev(date="2026-03-01")], as_of=AOD)     # ~93 days -> beyond 60
        self.assertEqual(s["count"], 0)

    def test_dated_flag_after_30d(self):
        fresh = summarize_catalysts([ev(date="2026-05-30")], as_of=AOD)["recent"][0]
        dated = summarize_catalysts([ev(date="2026-04-20")], as_of=AOD)["recent"][0]  # ~43d
        self.assertFalse(fresh["stale"])
        self.assertTrue(dated["stale"])

    def test_low_relevance_item_dropped(self):
        s = summarize_catalysts([ev(date="2026-05-30", relevance=0.3)],
                                config={"catalysts": {"min_relevance_score": 0.5}}, as_of=AOD)
        self.assertEqual(s["count"], 0)
        keep = summarize_catalysts([ev(date="2026-05-30", relevance=0.6)],
                                   config={"catalysts": {"min_relevance_score": 0.5}}, as_of=AOD)
        self.assertEqual(keep["count"], 1)

AOD = date(2026, 6, 2)


def ev(**o):
    base = {"ticker": "AGA.V", "date": "2026-05-26", "type": "drill_result",
            "headline": "hit", "impact": 0.8, "magnitude": 0.9}
    base.update(o)
    return base


class TestSummarize(unittest.TestCase):
    def test_positive_drill_boosts_conviction(self):
        s = summarize_catalysts([ev()], as_of=AOD)
        self.assertGreater(s["conviction_delta"], 0.0)
        self.assertEqual(s["count"], 1)
        self.assertEqual(s["recent"][0]["type"], "drill_result")

    def test_conviction_delta_is_capped(self):
        many = [ev(date="2026-06-01", impact=1.0, magnitude=1.0) for _ in range(10)]
        s = summarize_catalysts(many, config={"catalysts": {"conviction_delta_cap": 0.25}}, as_of=AOD)
        self.assertLessEqual(s["conviction_delta"], 0.25 + 1e-9)

    def test_recency_decay(self):
        recent = summarize_catalysts([ev(date="2026-05-30")], as_of=AOD)["conviction_delta"]
        old = summarize_catalysts([ev(date="2026-01-05")], as_of=AOD)["conviction_delta"]
        self.assertGreater(recent, old)

    def test_window_excludes_ancient_events(self):
        s = summarize_catalysts([ev(date="2024-01-01")],
                                config={"catalysts": {"recent_window_days": 180}}, as_of=AOD)
        self.assertEqual(s["count"], 0)
        self.assertEqual(s["conviction_delta"], 0.0)

    def test_financing_yields_dilution(self):
        s = summarize_catalysts(
            [ev(type="financing", impact=-0.4, share_change_pct=0.14, headline="raise")], as_of=AOD)
        self.assertIsNotNone(s["dilution_velocity"])
        self.assertAlmostEqual(s["dilution_velocity"], 0.14, places=3)

    def test_financings_accumulate_within_lookback(self):
        evs = [ev(type="financing", share_change_pct=0.05, date="2026-05-01"),
               ev(type="financing", share_change_pct=0.04, date="2026-03-01")]
        s = summarize_catalysts(evs, as_of=AOD)
        self.assertAlmostEqual(s["dilution_velocity"], 0.09, places=3)

    def test_permitting_takes_latest_stage(self):
        evs = [ev(type="permitting", stage_to="PEA", date="2026-02-01", impact=0.3),
               ev(type="permitting", stage_to="PFS", date="2026-05-10", impact=0.4)]
        s = summarize_catalysts(evs, as_of=AOD)
        self.assertEqual(s["permitting_stage"], "PFS")

    def test_negative_news_lowers_net_signal(self):
        pos = summarize_catalysts([ev(impact=0.8)], as_of=AOD)["net_signal"]
        neg = summarize_catalysts([ev(impact=-0.8)], as_of=AOD)["net_signal"]
        self.assertGreater(pos, 0)
        self.assertLess(neg, 0)

    def test_drill_p_discovery_accumulates(self):
        s = summarize_catalysts([ev(p_discovery_delta=0.06, date="2026-06-01")], as_of=AOD)
        self.assertGreater(s["p_discovery_delta"], 0.0)

    def test_recent_capped_and_sorted_newest_first(self):
        evs = [ev(date="2026-04-01", headline="old"), ev(date="2026-05-30", headline="new"),
               ev(date="2026-05-01", headline="mid")]
        s = summarize_catalysts(evs, config={"catalysts": {"max_display": 2}}, as_of=AOD)
        self.assertEqual(len(s["recent"]), 2)
        self.assertEqual(s["recent"][0]["label"], "new")

    def test_graceful_garbage(self):
        # Garbage entries and an unparseable date are dropped gracefully (no exception);
        # the one valid recent event still scores.
        s = summarize_catalysts([None, 5, {"ticker": "X"}, ev(date="not-a-date"), ev(date="2026-05-30")],
                                as_of=AOD)
        self.assertIsInstance(s["conviction_delta"], float)
        self.assertEqual(s["count"], 1)
        self.assertGreater(s["conviction_delta"], 0.0)


class TestBuildOverlays(unittest.TestCase):
    def test_groups_by_ticker(self):
        evs = [ev(ticker="AGA.V"), ev(ticker="GMX.TO", type="financing", share_change_pct=0.2)]
        ov = build_catalyst_overlays(evs, ["AGA.V", "GMX.TO", "GROY"], as_of=AOD)
        self.assertGreater(ov["AGA.V"]["conviction_delta"], 0)
        self.assertIsNotNone(ov["GMX.TO"]["dilution_velocity"])
        self.assertEqual(ov["GROY"]["count"], 0)             # no events -> neutral


class TestFeedLoader(unittest.TestCase):
    def test_missing_file(self):
        f = load_catalyst_feed("does/not/exist.json")
        self.assertEqual(f["status"], "missing")
        self.assertEqual(f["events"], [])

    def test_corrupt_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{ not json ]")
            p = fh.name
        try:
            f = load_catalyst_feed(p)
            self.assertEqual(f["status"], "error")
            self.assertEqual(f["events"], [])
        finally:
            os.unlink(p)

    def test_valid_envelope(self):
        env = {"schema_version": 1, "generated_at": "2026-05-30T12:00:00",
               "ttl_seconds": 86400, "events": [ev()]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(env, fh); p = fh.name
        try:
            f = load_catalyst_feed(p)
            self.assertIn(f["status"], ("live", "stale"))    # depends on wall clock
            self.assertEqual(len(f["events"]), 1)
        finally:
            os.unlink(p)

    def test_seed_feed_loads(self):
        if os.path.exists("data/catalysts.json"):
            f = load_catalyst_feed("data/catalysts.json")
            self.assertGreater(len(f["events"]), 0)


class TestVPillarReactivity(unittest.TestCase):
    def test_drill_lifts_bull_and_base(self):
        s = summarize_catalysts([ev(type="drill_result", impact=0.85, magnitude=0.9,
                                    date="2026-05-30", p_discovery_delta=0.06)], as_of=AOD)
        self.assertGreater(s["bull_uplift_pct"], 0.05)
        self.assertGreater(s["base_uplift_pct"], 0.0)
        self.assertLess(s["base_uplift_pct"], s["bull_uplift_pct"])  # base moves less than bull
        self.assertTrue(s["v_moved"])
        self.assertGreater(s["p_discovery_delta"], 0.0)
        self.assertTrue(s["v_drivers"])

    def test_v_uplift_is_recency_weighted(self):
        recent = summarize_catalysts([ev(type="grade_beat", impact=0.8, date="2026-05-30")], as_of=AOD)["bull_uplift_pct"]
        old = summarize_catalysts([ev(type="grade_beat", impact=0.8, date="2026-01-10")], as_of=AOD)["bull_uplift_pct"]
        self.assertGreater(recent, old)

    def test_v_uplift_bounded_by_cap(self):
        many = [ev(type="drill_result", impact=1.0, magnitude=1.0, date="2026-06-01") for _ in range(8)]
        s = summarize_catalysts(many, config={"catalysts": {"bull_uplift_cap": 0.25}}, as_of=AOD)
        self.assertLessEqual(s["bull_uplift_pct"], 0.25 + 1e-9)

    def test_financing_does_not_move_v(self):
        s = summarize_catalysts([ev(type="financing", impact=-0.4, share_change_pct=0.1)], as_of=AOD)
        self.assertEqual(s["bull_uplift_pct"], 0.0)          # v_impact_weights[financing] = 0
        self.assertFalse(s["v_moved"])

    def test_drill_routed_mostly_to_v_not_q(self):
        # With default weights a drill's V uplift should dominate its Q nudge.
        s = summarize_catalysts([ev(type="drill_result", impact=0.85, magnitude=0.9, date="2026-05-30")], as_of=AOD)
        self.assertGreater(s["bull_uplift_pct"], s["conviction_delta"])


class TestClassifier(unittest.TestCase):
    def test_drill_with_grade_number(self):
        c = classify_headline("Silver47 drills 1,240 g/t AgEq over 4.2m at Red Mountain")
        self.assertIn(c["type"], ("drill_result", "grade_beat"))
        self.assertEqual(c["grade_gpt"], 1240.0)             # comma-tolerant
        self.assertEqual(c["type"], "grade_beat")            # >=250 g/t promotes
        self.assertGreater(c["impact"], 0.6)
        self.assertGreater(c["p_discovery_delta"], 0.0)

    def test_financing_is_negative(self):
        c = classify_headline("Company announces C$22M bought deal financing")
        self.assertEqual(c["type"], "financing")
        self.assertLess(c["impact"], 0.0)
        self.assertGreater(c["magnitude"], 0.5)              # $22M -> larger dilution magnitude

    def test_permitting_stage(self):
        c = classify_headline("Plan of Operations accepted; advancing to feasibility")
        self.assertEqual(c["type"], "permitting")
        self.assertEqual(c["stage_to"], "DFS")

    def test_resource_estimate(self):
        c = classify_headline("Maiden NI 43-101 mineral resource estimate of 50 Moz")
        self.assertEqual(c["type"], "resource_expansion")
        self.assertGreater(c["impact"], 0.0)

    def test_generic_news_neutral(self):
        c = classify_headline("Company appoints new board director")
        self.assertEqual(c["type"], "news")
        self.assertLess(abs(c["impact"]), 0.3)

    def test_negative_sentiment_tilt(self):
        c = classify_headline("Company reports drilling delay and going concern doubt")
        self.assertLess(c["impact"], classify_headline("Company reports strong high-grade results")["impact"])


class TestMatchAndDedupe(unittest.TestCase):
    def test_attribute_scores_strength(self):
        al = {"AGA.V": ["silver47", "red mountain"], "GMX.TO": ["goldmining inc"]}
        self.assertEqual(attribute("Silver47 drills high grade", al), ("AGA.V", 0.6))   # single word
        self.assertEqual(attribute("GoldMining Inc reports", al), ("GMX.TO", 1.0))       # multi-word co
        self.assertEqual(attribute("Generic silver prices rise", al), (None, 0.0))       # unattributed

    def test_match_longest_alias_wins(self):
        al = {"AGA.V": ["silver47", "red mountain"], "GMX.TO": ["gold mining x"]}
        self.assertEqual(match_ticker("Silver47 drills at Red Mountain", al), "AGA.V")
        self.assertIsNone(match_ticker("Unrelated macro headline", al))

    def test_dedupe_by_link_keeps_higher_trust(self):
        evs = [{"ticker": "AGA.V", "headline": "x", "date": "2026-05-26", "link": "u1", "_trust": 1},
               {"ticker": "AGA.V", "headline": "x!", "date": "2026-05-26", "link": "u1", "_trust": 3}]
        out = dedupe_events(evs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["_trust"], 3)

    def test_dedupe_by_headline_date_when_no_link(self):
        evs = [{"ticker": "AGA.V", "headline": "Drills 1240 g/t!", "date": "2026-05-26"},
               {"ticker": "AGA.V", "headline": "drills 1240 g/t", "date": "2026-05-26"}]
        self.assertEqual(len(dedupe_events(evs)), 1)         # normalized headline+date collision

    def test_dedupe_cross_link_same_story(self):
        # Same press release from two aggregators (different URLs) -> merged; higher trust kept.
        evs = [{"ticker": "AGA.V", "headline": "Silver47 drills 1240 g/t", "date": "2026-05-26",
                "link": "http://a/1", "_trust": 1},
               {"ticker": "AGA.V", "headline": "silver47 drills 1240 g/t", "date": "2026-05-26",
                "link": "http://b/2", "_trust": 3}]
        out = dedupe_events(evs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["_trust"], 3)

    def test_dedupe_distinct_stories_kept(self):
        evs = [{"ticker": "AGA.V", "headline": "Drill hit", "date": "2026-05-26", "link": "u1"},
               {"ticker": "AGA.V", "headline": "Financing closed", "date": "2026-05-20", "link": "u2"}]
        self.assertEqual(len(dedupe_events(evs)), 2)


class TestConfig(unittest.TestCase):
    def test_partial_merge(self):
        cfg = merge_catalyst_config({"catalysts": {"half_life_days": 30}})
        self.assertEqual(cfg["half_life_days"], 30)
        self.assertIn("impact_weights", cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
