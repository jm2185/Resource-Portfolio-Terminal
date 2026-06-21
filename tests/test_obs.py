"""Tests for obs.swallow — observability for swallowed exceptions (lose the blindness, keep never-crash)."""
import os
import unittest

import obs


class SwallowTest(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get("CEX_DEBUG")

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("CEX_DEBUG", None)
        else:
            os.environ["CEX_DEBUG"] = self._orig

    def test_silent_and_nonraising_when_off(self):
        os.environ["CEX_DEBUG"] = "0"
        self.assertFalse(obs.enabled())
        try:
            raise ValueError("boom")
        except Exception:
            obs.swallow("ctx")                      # off → no raise, no log (never-crash preserved)

    def test_logs_with_context_and_exc_when_on(self):
        os.environ["CEX_DEBUG"] = "1"
        with self.assertLogs("cex", level="WARNING") as cm:
            try:
                raise ValueError("boom")
            except Exception:
                obs.swallow("prices.aga")
        self.assertTrue(any("prices.aga" in m and "boom" in m for m in cm.output))

    def test_no_active_exception_is_safe(self):
        os.environ["CEX_DEBUG"] = "1"
        obs.swallow("ctx")                          # nothing being handled → records nothing, no raise

    def test_enabled_flag_parsing(self):
        for off in ("", "0", "false", "no", "off", "FALSE"):
            os.environ["CEX_DEBUG"] = off
            self.assertFalse(obs.enabled())
        for on in ("1", "true", "yes", "debug"):
            os.environ["CEX_DEBUG"] = on
            self.assertTrue(obs.enabled())


if __name__ == "__main__":
    unittest.main()
