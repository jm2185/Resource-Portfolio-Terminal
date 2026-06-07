"""
Tests for the trigger grammar (trigger_grammar.py, Forge M2) — the security-critical piece.

Pins: every token type parses and evaluates; precedence is correct; NO code execution is possible
(out-of-vocabulary identifiers fail to PARSE — there is no path to eval/exec); malformed expressions
fail closed (GrammarError at parse, False at eval, never an exception that could crash a sweep);
missing metrics fail closed to False (a rule can never spuriously fire on absent data).
"""
import unittest

import trigger_grammar as tg
from trigger_grammar import GrammarError, evaluate, parse, safe_eval


class TokenTests(unittest.TestCase):
    def test_all_comparators(self):
        for expr, expect in [("phi < 1.0", True), ("phi <= 0.92", True), ("phi > 1.0", False),
                             ("rho >= 3.0", True), ("rho == 3.1", True), ("rho != 3.0", True)]:
            self.assertEqual(evaluate(expr, {"phi": 0.92, "rho": 3.1}), expect, expr)

    def test_boolean_precedence(self):
        ctx = {"phi": 0.92, "rho": 3.1, "mri": 47}
        # NOT binds tighter than AND tighter than OR
        self.assertTrue(evaluate("phi < 1.0 AND rho > 1.0", ctx))
        self.assertFalse(evaluate("phi < 1.0 AND rho < 1.0", ctx))
        self.assertTrue(evaluate("phi > 5 OR rho > 1.0", ctx))
        self.assertTrue(evaluate("NOT phi > 1.0", ctx))
        self.assertTrue(evaluate("(phi < 1.0 OR mri > 90) AND rho > 1.0", ctx))

    def test_bare_boolean_metric(self):
        self.assertTrue(evaluate("window_open", {"window_open": True}))
        self.assertFalse(evaluate("window_open", {"window_open": False}))
        self.assertTrue(evaluate("NOT dilution_ok", {"dilution_ok": False}))

    def test_true_false_literals(self):
        self.assertTrue(evaluate("true", {}))
        self.assertFalse(evaluate("false", {}))

    def test_helper_catalyst_within_days(self):
        ctx = {"phi": 0.92, "catalyst_within_days": lambda n: n >= 30}
        self.assertTrue(evaluate("catalyst_within_days(30)", ctx))
        self.assertFalse(evaluate("catalyst_within_days(10)", ctx))
        # no_catalyst_within_days is the negation
        self.assertFalse(evaluate("no_catalyst_within_days(30)", ctx))
        self.assertTrue(evaluate("no_catalyst_within_days(10)", ctx))

    def test_event_ref_and_before(self):
        ctx = {"events": {"assays": 100, "bought_deal": 200}}
        self.assertTrue(evaluate("event:assays", ctx))
        self.assertFalse(evaluate("event:permit", ctx))
        self.assertTrue(evaluate("before(event:assays, event:bought_deal)", ctx))
        self.assertFalse(evaluate("before(event:bought_deal, event:assays)", ctx))

    def test_before_with_unoccurred_event_is_false(self):
        # the r2 pattern: exit if a bought-deal lands BEFORE assays. Neither occurred yet -> no fire.
        self.assertFalse(evaluate("before(event:bought_deal, event:assays)", {"events": {}}))


class FailClosedTests(unittest.TestCase):
    def test_missing_metric_is_false_not_error(self):
        fired, notes = safe_eval("phi < 1.0", {})              # phi absent
        self.assertFalse(fired)
        self.assertTrue(any("missing metric" in n for n in notes))

    def test_missing_helper_is_false(self):
        self.assertFalse(evaluate("catalyst_within_days(30)", {}))   # no callable supplied

    def test_malformed_raises_at_parse(self):
        for bad in ["phi <", "phi < < 1", "AND phi", "no_catalyst_within_days()",
                    "before(event:a)", "(phi < 1", "phi 1.0"]:
            with self.assertRaises(GrammarError, msg=bad):
                parse(bad)

    def test_malformed_is_false_at_eval_never_raises(self):
        # evaluate must swallow a parse error and fail closed
        self.assertFalse(evaluate("phi < < 1", {"phi": 0.5}))
        self.assertFalse(evaluate("", {}))

    def test_arity_enforced(self):
        with self.assertRaises(GrammarError):
            parse("catalyst_within_days(1, 2)")
        with self.assertRaises(GrammarError):
            parse("before(event:a, event:b, event:c)")


class SecurityTests(unittest.TestCase):
    """The hard line (Build Spec §7): memory content is NEVER executed. Anything that isn't in the
    closed whitelist must fail to PARSE — there is no code path from a trigger string to exec/eval."""

    def test_no_dunder_or_import_parses(self):
        for evil in ["__import__('os')", "os.system('rm -rf /')", "().__class__",
                     "eval('1+1')", "exec('x=1')", "open('/etc/passwd')",
                     "phi.__class__", "lambda: 1"]:
            with self.assertRaises(GrammarError, msg=evil):
                parse(evil)

    def test_unknown_identifier_rejected(self):
        with self.assertRaises(GrammarError):
            parse("sharpe_ratio > 2")                          # not a known metric
        with self.assertRaises(GrammarError):
            parse("frobnicate(30)")                            # not a known function

    def test_evil_string_eval_is_false_and_inert(self):
        # even via the non-raising entry point, nothing executes; result is just False
        sentinel = {"tripped": False}

        def boom(_):                                            # would flip state IF ever called
            sentinel["tripped"] = True
            return True
        # a malicious string can't reach this callable — it isn't a known helper name
        self.assertFalse(evaluate("boom(1)", {"boom": boom}))
        self.assertFalse(sentinel["tripped"])


class IntrospectionTests(unittest.TestCase):
    def test_metrics_referenced(self):
        m = tg.metrics_referenced("phi < 1.0 AND rho > runway_months OR mri == 50")
        self.assertEqual(m, {"phi", "rho", "runway_months", "mri"})

    def test_metrics_referenced_on_bad_expr_is_empty(self):
        self.assertEqual(tg.metrics_referenced("phi < <"), set())


class M3AcceptanceTests(unittest.TestCase):
    """The exact r1 from the spec: 'phi < 1.0 AND no_catalyst_within_days(30)'."""

    def test_r1_fires_when_phi_low_and_no_catalyst(self):
        ctx = {"phi": 0.92, "catalyst_within_days": lambda n: False}   # nothing in the window
        self.assertTrue(evaluate("phi < 1.0 AND no_catalyst_within_days(30)", ctx))

    def test_r1_quiet_when_catalyst_in_window(self):
        ctx = {"phi": 0.92, "catalyst_within_days": lambda n: True}    # a drill result is coming
        self.assertFalse(evaluate("phi < 1.0 AND no_catalyst_within_days(30)", ctx))

    def test_r1_quiet_when_phi_healthy(self):
        ctx = {"phi": 1.30, "catalyst_within_days": lambda n: False}
        self.assertFalse(evaluate("phi < 1.0 AND no_catalyst_within_days(30)", ctx))


if __name__ == "__main__":
    unittest.main(verbosity=2)
