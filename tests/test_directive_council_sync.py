"""
Phase 0.2 sync-guard: the directive STRING is an inter-module contract.

`asymmetry_rating._directive` emits a human-readable directive string (e.g.
"BELOW FLOOR — ACCUMULATE · watch closely"). `council._directive_prior` then
*keyword-matches* that exact prose to a bull-share prior in [0,1] (council.py
`_DIRECTIVE_PRIOR`), and an UNRECOGNIZED directive falls silently to the neutral
0.50 — no error, no log. So a rename on either side ("BELOW FLOOR" → "SUB-FLOOR",
or a re-ordered/renamed council key) quietly degrades every live Council verdict's
engine prior to neutral, with nothing to catch it.

These tests pin the contract:
  1. extraction is not vacuous (guards a refactor that hides the literals);
  2. EVERY directive `_directive` can emit resolves to a *recognized* prior, not
     the silent 0.50 fallback (the charter's "fails the moment any falls to 0.50");
  3. a snapshot of the full directive→prior mapping (catches a silent value /
     ordering drift that changes a prior without breaking coverage);
  4. the one latent ambiguity ("FAIR VALUE — HOLD" legitimately resolves to 0.50,
     indistinguishable from the unknown fallback) is documented, so any change to
     either value is a conscious decision, not a silent collision.

Pure stdlib; no engine, no network. The directives are read live from the source
so the guard tracks the real function, not a transcribed copy.
"""
import inspect
import re
import unittest

import asymmetry_rating
import council


def _emitted_directives() -> list[str]:
    """Every string literal `_directive` can `return`, read live from its source.

    Reading from source (rather than a hardcoded copy) means a renamed directive is
    picked up automatically and re-checked against the council mapping — the guard
    tracks drift on the asymmetry_rating side, not a stale transcription."""
    src = inspect.getsource(asymmetry_rating._directive)
    found = re.findall(r'return\s+"([^"]*)"', src)
    # de-dupe, preserve order (WEAK SETUP — STAND ASIDE is returned in two branches)
    seen, out = set(), []
    for d in found:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _is_recognized(directive: str) -> bool:
    """Mirror council._directive_prior's match test: True iff some _DIRECTIVE_PRIOR
    key is a substring of the directive — i.e. it resolves to a REAL prior, not the
    silent 0.50 unknown-fallback. (Value-agnostic: a key whose prior happens to be
    0.50 still counts as recognized; see the collision test below.)"""
    up = directive.upper()
    return any(key in up for key, _ in council._DIRECTIVE_PRIOR)


# Snapshot of the current directive → prior mapping. This is the pin: a silent
# re-order or value edit on either side trips it, forcing a conscious update.
# (Values are floats, so the exotic unicode in the directive text is never
# transcribed here — only the resolved priors are asserted.)
_EXPECTED_DISTINCT_PRIORS = sorted(
    [0.15, 0.30, 0.33, 0.38, 0.50, 0.55, 0.62, 0.68, 0.70, 0.72]
)


class DirectiveCouncilSyncTests(unittest.TestCase):
    def test_extraction_is_not_vacuous(self):
        """If a refactor stops _directive from returning string literals, the regex
        would yield nothing and every other test here would pass vacuously. Guard it."""
        directives = _emitted_directives()
        self.assertGreaterEqual(
            len(directives), 8,
            f"Extracted only {len(directives)} directive literals from _directive — "
            "the source shape changed; update this guard before trusting it.",
        )

    def test_every_directive_maps_to_a_known_prior(self):
        """THE core guard. Each directive _directive can emit must resolve to a
        recognized council prior, never the silent 0.50 unknown-fallback. Fails the
        instant a rename on either side breaks the keyword contract."""
        unrecognized = [d for d in _emitted_directives() if not _is_recognized(d)]
        self.assertEqual(
            unrecognized, [],
            "These directives fall through to council._directive_prior's silent 0.50 "
            f"neutral fallback (no key matches): {unrecognized!r}. Every live Council "
            "verdict on such a name loses its engine prior. Add a _DIRECTIVE_PRIOR key "
            "or fix the directive string.",
        )

    def test_directive_prior_mapping_snapshot(self):
        """Pin the full mapping: the set of distinct priors the directives resolve to.
        Catches a silent value/ordering drift that changes a prior without removing
        coverage (e.g. re-ordering _DIRECTIVE_PRIOR so a directive matches a different
        key first). Currently every directive maps to a distinct prior."""
        priors = sorted({
            council._directive_prior(d) for d in _emitted_directives()
        })
        self.assertEqual(
            priors, _EXPECTED_DISTINCT_PRIORS,
            "The directive→prior mapping drifted. If intentional, update "
            "_EXPECTED_DISTINCT_PRIORS; if not, a rename/re-order silently moved a prior.",
        )

    def test_fair_value_hold_collides_with_unknown_fallback(self):
        """Documented latent ambiguity: 'FAIR VALUE — HOLD' legitimately matches the
        'FAIR VALUE' key whose prior is 0.50 — the SAME value as the unknown-directive
        fallback. So a recognized FAIR-VALUE directive and an unrecognized typo are
        indistinguishable by prior alone. Pinned so any change to either value is
        conscious; a future fix may want to nudge the 'FAIR VALUE' key off 0.50."""
        fair_value_holds = [
            d for d in _emitted_directives() if d.upper().startswith("FAIR VALUE")
        ]
        self.assertTrue(
            fair_value_holds,
            "Expected a 'FAIR VALUE — HOLD'-style directive; the value-mode ladder changed.",
        )
        for d in fair_value_holds:
            self.assertTrue(_is_recognized(d), f"{d!r} should match a real key, not the fallback")
            self.assertEqual(
                council._directive_prior(d), 0.50,
                f"{d!r} resolves to {council._directive_prior(d)}, no longer the 0.50 that "
                "collides with the unknown-directive fallback — update this note if intended.",
            )


if __name__ == "__main__":
    unittest.main()
