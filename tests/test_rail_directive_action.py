"""
Rail directive-chip helper (`commodityex_tui._directive_action`).

The HOLDINGS rail shows the rating (conviction) and, next to it, the STANCE token. Rating and
stance are orthogonal — a name below its REP floor is ACCUMULATE at a lower rating while a name at
fair value is HOLD at a higher one — so this token makes "6.8/ACCUM beside 6.9/HOLD" legible instead
of hiding the directive in the detail card. These tests pin that every directive
`asymmetry_rating._directive` can emit maps to a sensible action token (and never the bare em-dash),
so a directive rename can't silently blank the chip.

Skips cleanly where Textual/rich aren't installed (the TUI is an optional cockpit pane).
"""
import inspect
import re
import unittest

try:
    import textual  # noqa: F401
    HAVE_TUI = True
except Exception:                                  # pragma: no cover
    HAVE_TUI = False


def _emitted_directives() -> list[str]:
    """The directive literals asymmetry_rating._directive can return, read live from its source."""
    import asymmetry_rating
    src = inspect.getsource(asymmetry_rating._directive)
    seen, out = set(), []
    for d in re.findall(r'return\s+"([^"]*)"', src):
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


@unittest.skipUnless(HAVE_TUI, "textual not installed")
class DirectiveActionTests(unittest.TestCase):
    def test_known_directives_map_to_expected_tokens(self):
        import commodityex_tui as t
        expected = {
            "FORENSIC DECAY — AVOID / DE-RISK": "AVOID",
            "QUALITY — CORE HOLD": "HOLD",
            "BELOW FAIR VALUE — ACCUMULATE": "ACCUM",
            "RICH — TRIM": "TRIM",
            "FAIR VALUE — HOLD": "HOLD",
            "WEAK SETUP — STAND ASIDE": "STAND",
            "BELOW FLOOR — ACCUMULATE · watch closely": "ACCUM",   # accumulate wins over "watch"
            "STRONG ASYMMETRY — WATCH CLOSELY": "WATCH",
            "UPSIDE SPENT — HOLD / TRIM": "TRIM",                  # the de-risk signal wins over hold
            "THESIS INTACT — MONITOR": "MON",
            "BELOW PROXY FLOOR — VERIFY · floor unsourced": "VERIFY",  # φ≥1 on a proxy floor: verify, never ACCUM
        }
        for directive, token in expected.items():
            got, colour = t._directive_action(directive)
            self.assertEqual(got, token, f"{directive!r} -> {got!r}, expected {token!r}")
            self.assertTrue(colour, "a colour must be returned")

    def test_every_emitted_directive_gets_a_nonblank_token(self):
        """No directive _directive can emit should render the bare em-dash fallback — that would be a
        blank chip on a live holding. Fails if a future rename outruns the token map."""
        import commodityex_tui as t
        blank = [d for d in _emitted_directives() if t._directive_action(d)[0] in ("—", "")]
        self.assertEqual(blank, [], f"these directives render a blank stance chip: {blank!r}")

    def test_unknown_and_empty_are_safe(self):
        import commodityex_tui as t
        self.assertEqual(t._directive_action(None)[0], "—")
        self.assertEqual(t._directive_action("")[0], "—")
        # an unknown-but-nonempty directive falls back to its trailing phrase, never crashes
        tok, _ = t._directive_action("SOME NEW STANCE — REBALANCE")
        self.assertTrue(tok)


if __name__ == "__main__":
    unittest.main()
