"""monitor_protocol — the shared protocol layer under the six SENTINEL/monitor modules
(num coercion · clamp · glossary tooltip · one-level config merge · the select_fresh dedup
skeleton). Pure helpers, hand-verifiable; also pins that the six consumers still speak the
same contract through their thin wrappers."""
import unittest

import monitor_protocol as mp


class NumTests(unittest.TestCase):
    def test_finite_numbers_pass_through(self):
        self.assertEqual(mp.num(3), 3.0)
        self.assertEqual(mp.num("2.5"), 2.5)
        self.assertEqual(mp.num(-0.1), -0.1)

    def test_garbage_nan_inf_none_all_none(self):
        for bad in (None, "x", {}, [], float("nan"), float("inf"), float("-inf")):
            self.assertIsNone(mp.num(bad))


class ClampTests(unittest.TestCase):
    def test_clamps_into_unit_interval_by_default(self):
        self.assertEqual(mp.clamp(-0.2), 0.0)
        self.assertEqual(mp.clamp(0.4), 0.4)
        self.assertEqual(mp.clamp(1.7), 1.0)

    def test_custom_bounds(self):
        self.assertEqual(mp.clamp(5, 0, 10), 5)
        self.assertEqual(mp.clamp(-5, 0, 10), 0)
        self.assertEqual(mp.clamp(15, 0, 10), 10)


class TooltipTests(unittest.TestCase):
    GLOSSARY = {"k": {"what": "the thing", "scale": "0..1", "influence": "the panel",
                      "edge": "read early"}}

    def test_flattens_in_canonical_order_with_labels(self):
        txt = mp.tooltip(self.GLOSSARY, "k")
        self.assertEqual(txt.split("\n"), ["the thing", "Good vs bad: 0..1",
                                           "Drives: the panel", "Note: read early"])

    def test_partial_entry_skips_missing_fields(self):
        txt = mp.tooltip({"k": {"what": "w", "influence": "i"}}, "k")
        self.assertEqual(txt, "w\nDrives: i")

    def test_unknown_key_and_none_glossary_are_empty(self):
        self.assertEqual(mp.tooltip(self.GLOSSARY, "nope"), "")
        self.assertEqual(mp.tooltip(None, "k"), "")


class MergedConfigTests(unittest.TestCase):
    DEFAULTS = {"z_min": 2.5, "rvol_min": 3.0, "weights": {"a": 0.5, "b": 0.5}}

    def test_no_config_returns_defaults_copy(self):
        cfg = mp.merged_config(self.DEFAULTS, None, "mod")
        self.assertEqual(cfg, self.DEFAULTS)
        self.assertIsNot(cfg, self.DEFAULTS)

    def test_named_block_overlays(self):
        cfg = mp.merged_config(self.DEFAULTS, {"mod": {"z_min": 4.0}, "other": {"z_min": 9}}, "mod")
        self.assertEqual(cfg["z_min"], 4.0)
        self.assertEqual(cfg["rvol_min"], 3.0)

    def test_bare_dict_without_block_is_the_block(self):
        cfg = mp.merged_config(self.DEFAULTS, {"rvol_min": 5.0}, "mod")
        self.assertEqual(cfg["rvol_min"], 5.0)

    def test_dict_values_merge_one_level_deep(self):
        cfg = mp.merged_config(self.DEFAULTS, {"mod": {"weights": {"a": 0.9}}}, "mod")
        self.assertEqual(cfg["weights"], {"a": 0.9, "b": 0.5})     # b survives
        self.assertEqual(self.DEFAULTS["weights"], {"a": 0.5, "b": 0.5})  # defaults untouched

    def test_non_dict_block_is_ignored(self):
        cfg = mp.merged_config(self.DEFAULTS, {"mod": "garbage"}, "mod")
        self.assertEqual(cfg, self.DEFAULTS)


class SelectFreshTests(unittest.TestCase):
    """The shared dedup skeleton — fire once per (ticker, state) per day, re-fire next day."""

    @staticmethod
    def _run(flags, fired, today):
        return mp.select_fresh(flags, fired, today=today, ticker_field="ticker",
                               state_fn=lambda r: {"key": r.get("key")},
                               is_repeat=lambda prev, st: prev.get("key") == st["key"])

    def test_first_fire_is_fresh_and_recorded(self):
        fresh, fired = self._run([{"ticker": "X", "key": "a"}], {}, "2026-07-02")
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fired["X"], {"date": "2026-07-02", "key": "a"})

    def test_same_state_same_day_is_deduped(self):
        _, fired = self._run([{"ticker": "X", "key": "a"}], {}, "2026-07-02")
        fresh, _ = self._run([{"ticker": "X", "key": "a"}], fired, "2026-07-02")
        self.assertEqual(fresh, [])

    def test_new_state_same_day_refires(self):
        _, fired = self._run([{"ticker": "X", "key": "a"}], {}, "2026-07-02")
        fresh, fired = self._run([{"ticker": "X", "key": "b"}], fired, "2026-07-02")
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fired["X"]["key"], "b")

    def test_next_day_refires_by_design(self):
        _, fired = self._run([{"ticker": "X", "key": "a"}], {}, "2026-07-02")
        fresh, _ = self._run([{"ticker": "X", "key": "a"}], fired, "2026-07-03")
        self.assertEqual(len(fresh), 1)

    def test_never_mutates_the_input_ledger(self):
        fired = {"X": {"date": "2026-07-01", "key": "a"}}
        self._run([{"ticker": "X", "key": "b"}], fired, "2026-07-02")
        self.assertEqual(fired, {"X": {"date": "2026-07-01", "key": "a"}})

    def test_blank_ticker_and_none_rows_skipped_gracefully(self):
        fresh, fired = self._run([{"ticker": "", "key": "a"}, None, {}], {}, "2026-07-02")
        self.assertEqual(fresh, [])
        self.assertEqual(fired, {})

    def test_empty_and_none_inputs(self):
        self.assertEqual(self._run(None, None, "2026-07-02"), ([], {}))


class ConsumerContractTests(unittest.TestCase):
    """The six monitors' thin wrappers still speak the shared contract."""

    def test_all_six_tooltips_flatten_through_the_shared_helper(self):
        import conventional_sentinel as cs
        import correlation_monitor as cm
        import divergence_monitor as dm
        import oil_supply_monitor as om
        import productivity_monitor as pm
        import rates_monitor as rm
        pairs = [(dm.divergence_tooltip, dm.DIVERGENCE_GLOSSARY),
                 (cm.correlation_tooltip, cm.CORRELATION_GLOSSARY),
                 (cs.conventional_sentinel_tooltip, cs.CONVENTIONAL_SENTINEL_GLOSSARY),
                 (pm.productivity_tooltip, pm.PRODUCTIVITY_GLOSSARY),
                 (om.oil_tooltip, om.OIL_GLOSSARY),
                 (rm.rates_tooltip, rm.RATES_GLOSSARY)]
        for fn, glossary in pairs:
            key = next(iter(glossary))
            self.assertEqual(fn(key), mp.tooltip(glossary, key))
            self.assertEqual(fn("does_not_exist"), "")

    def test_divergence_select_fresh_sign_semantics_survive(self):
        import divergence_monitor as dm
        flag = {"name": "AGA.V", "residual": 0.12, "rvol": 4.0}
        fresh, fired = dm.select_fresh([flag], {}, today="2026-07-02")
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fired["AGA.V"], {"date": "2026-07-02", "sign": 1,
                                          "residual": 0.12, "rvol": 4.0})
        # same sign same day → deduped; a sign FLIP is a new event
        self.assertEqual(dm.select_fresh([flag], fired, today="2026-07-02")[0], [])
        flipped, _ = dm.select_fresh([{"name": "AGA.V", "residual": -0.1}], fired, today="2026-07-02")
        self.assertEqual(len(flipped), 1)

    def test_correlation_select_fresh_worsened_bucket_semantics_survive(self):
        import correlation_monitor as cm
        _, fired = cm.select_fresh([{"id": "correlation_drift", "ticker": "X.TO", "corr": 0.61}],
                                   {}, today="2026-07-02")
        self.assertEqual(fired["X.TO"]["bucket"], 0.6)
        same, _ = cm.select_fresh([{"ticker": "X.TO", "corr": 0.63}], fired, today="2026-07-02")
        self.assertEqual(same, [])                          # jitter inside the decile
        worse, _ = cm.select_fresh([{"ticker": "X.TO", "corr": 0.78}], fired, today="2026-07-02")
        self.assertEqual(len(worse), 1)                     # a worsened bucket re-fires

    def test_conventional_select_fresh_zone_key_semantics_survive(self):
        import conventional_sentinel as cs
        _, fired = cs.select_fresh([{"ticker": "EEFT", "zone": "below_floor", "id": "asymmetry_zone_cross"}],
                                   {}, today="2026-07-02")
        self.assertEqual(fired["EEFT"]["key"], "below_floor")
        same, _ = cs.select_fresh([{"ticker": "EEFT", "zone": "below_floor"}], fired, today="2026-07-02")
        self.assertEqual(same, [])
        moved, _ = cs.select_fresh([{"ticker": "EEFT", "zone": "accumulate"}], fired, today="2026-07-02")
        self.assertEqual(len(moved), 1)


if __name__ == "__main__":
    unittest.main()
