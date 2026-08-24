"""Regression tests for the SNAG / GMX.TO bug class: a ticker that resolves to the WRONG issuer.

On 2026-08-21 Silver North Resources was promoted to the eval set registered as bare ``SNAG``.
No such symbol exists — the only listing is ``SNAG.V`` (TSXV, CAD, C$0.265). Vendors resolved the
bare root to an unrelated USD security at $5.209, and that ~20x-wrong price reached
``data/price_history.json``, ``data/market_cache.json`` and two ``valuation_ledger`` rows before
anyone noticed. The engine's degraded-input guard fired (both ledger rows read
"BROKEN / AVOID - DEGRADED INPUTS, directive suspended") but could not name the cause: a wrong
price is still a well-formed price. Only an identity check catches this.
"""
import json
import os

import pytest

import book_invariants as bi

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Real FMP payload for the CORRECT symbol (2026-08-24).
SNAG_V_QUOTE = {
    "symbol": "SNAG.V", "companyName": "Silver North Resources Ltd.",
    "currency": "CAD", "price": 0.265, "exchange": "TSXV",
}

# The observed mis-resolution, from data/market_cache.json under key "yh:SNAG". The vendor's
# price/currency are verbatim; the issuer name is a STAND-IN — the actual company bare ``SNAG``
# resolves to was never identified (Yahoo was unreachable from the session that found this), and
# the test asserts the mechanism, not that particular issuer's name.
WRONG_ISSUER_QUOTE = {
    "companyName": "Stag Industrial, Inc.", "currency": "USD",
    "price": 5.209, "previous_close": 5.59,
}


class TestNameAgreement:
    def test_tolerates_corporate_form_and_punctuation(self):
        assert bi.names_agree("Silver North Resources", "Silver North Resources Ltd.")
        assert bi.names_agree("Gold Royalty Corp", "Gold Royalty Corp.")
        assert bi.names_agree("Silver47 Exploration Corp", "Silver47 Exploration Corp.")

    def test_rejects_distinct_issuers(self):
        assert not bi.names_agree("Silver North Resources", "Stag Industrial, Inc.")
        assert not bi.names_agree("Gold Royalty Corp", "GoldMining Inc.")

    def test_empty_side_never_vouches(self):
        assert not bi.names_agree("", "Silver North Resources")
        assert not bi.names_agree("Silver North Resources", None)


class TestTickerIdentityConflict:
    def test_correct_symbol_is_clean(self):
        assert bi.ticker_identity_conflict(
            "SNAG.V", "Silver North Resources", SNAG_V_QUOTE) is None

    def test_catches_the_snag_misresolution(self):
        reason = bi.ticker_identity_conflict("SNAG", "Silver North Resources", WRONG_ISSUER_QUOTE)
        assert reason is not None
        assert "wrong issuer" in reason

    def test_canadian_suffix_must_price_in_cad(self):
        reason = bi.ticker_identity_conflict("SNAG.V", None, {"currency": "USD", "price": 5.209})
        assert reason is not None and "Canadian suffix" in reason

    @pytest.mark.parametrize("quote", [None, {}, "not-a-dict", 0])
    def test_unresolved_quote_is_not_a_conflict(self, quote):
        assert bi.ticker_identity_conflict("SNAG.V", "Silver North Resources", quote) is None

    def test_nameless_price_payload_is_unjudgeable(self):
        """Documents the guard's limit: the yh cache shape carries no companyName, so a bare
        ticker cannot be judged from a price tick. The check belongs at REGISTRATION, where a
        profile lookup supplies the issuer name — not on every price refresh."""
        assert bi.ticker_identity_conflict(
            "SNAG", "Silver North Resources", {"currency": "USD", "price": 5.209}) is None

    def test_real_book_names_do_not_false_positive(self):
        assert bi.ticker_identity_conflict("AGA.V", "Silver47 Exploration Corp", {
            "companyName": "Silver47 Exploration Corp", "currency": "CAD"}) is None
        assert bi.ticker_identity_conflict("GROY", "Gold Royalty Corp", {
            "companyName": "Gold Royalty Corp.", "currency": "USD"}) is None


class TestConfigRegistration:
    """Locks the fix itself: the book must register Silver North by its real symbol."""

    @staticmethod
    def _portfolio_metadata():
        with open(os.path.join(REPO, "v5_config.json")) as fh:
            return json.load(fh)["portfolio_metadata"]

    def test_snag_registered_with_exchange_suffix(self):
        pm = self._portfolio_metadata()
        assert "SNAG.V" in pm, "Silver North must be registered as SNAG.V"
        assert "SNAG" not in pm, "bare SNAG resolves to a different issuer"

    def test_candidate_universe_agrees_with_config(self):
        with open(os.path.join(REPO, "data", "candidate_universe.json")) as fh:
            universe = json.load(fh)
        rows = universe if isinstance(universe, list) else universe.get("candidates", [])
        tickers = {r.get("ticker") for r in rows if isinstance(r, dict)}
        assert "SNAG" not in tickers, "candidate universe still carries the bare symbol"
        assert "SNAG.V" in tickers

    def test_no_cached_quote_under_the_bare_symbol(self):
        """The poisoned $5.209 quote must not survive in a regenerable cache."""
        path = os.path.join(REPO, "data", "market_cache.json")
        if not os.path.exists(path):
            pytest.skip("no market cache in this checkout")
        with open(path) as fh:
            cache = json.load(fh)
        assert not [k for k in cache if k.split(":", 1)[-1] == "SNAG"]
