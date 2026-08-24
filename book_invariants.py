"""Structural book invariants — the single source of truth for constants that MUST stay identical
across every consumer (the sizer, the overlay validator, the add-gate, the book-change surface, and
the MCP mutation path). Pure module: no imports, no dependencies, safe to import from anywhere with
zero cycle risk.

The 60% AGA.V spear ceiling is the book's most important invariant — a HARD, NON-configurable cap,
deliberately absent from the dynamic-config allowlist. It may only ever TIGHTEN (via regime posture
or a guardrail), never loosen. It was previously duplicated as a bare ``0.60`` literal in five
modules, kept in lockstep by comment only; centralizing it here removes the silent-divergence risk
on the single most important number in the book, and ``tests/test_spear_ceiling_central.py`` fails
the instant any consumer drifts from it.
"""

#: The structural 60% spear ceiling — AGA.V's maximum book weight. Non-configurable by design.
SPEAR_CEILING: float = 0.60


# --------------------------------------------------------------------------- ticker identity
#: Exchange suffixes that denote a Canadian listing.
#:
#: A Canadian junior registered WITHOUT its suffix does not fail loudly. Vendors resolve the bare
#: root to a different — usually US-listed — security, and the book silently marks the wrong
#: company. This is the GMX.TO class of bug, and it bit SNAG on 2026-08-21: registered bare as
#: ``SNAG``, it resolved to a USD name at $5.209 while Silver North Resources (``SNAG.V``) traded
#: at C$0.265. The ~20x error reached price_history and two valuation-ledger rows before the
#: rename. The engine's degraded-input guard caught the smell (it suspended the directive) but not
#: the cause, because a wrong price is still a well-formed price.
CANADIAN_SUFFIXES: tuple = (".V", ".TO", ".CN", ".NE")

#: Corporate-form words dropped before comparing a registered name to a vendor's companyName, so
#: "Silver North Resources" and "Silver North Resources Ltd." compare equal.
_CORP_FORMS: frozenset = frozenset({
    "ltd", "ltda", "limited", "inc", "incorporated", "corp", "corporation", "co", "company",
    "plc", "sa", "nv", "ag", "ab", "asa", "oyj", "spa", "llc", "lp", "holding", "holdings",
    "group", "the", "and",
})


def normalize_company_name(name) -> str:
    """Lower-case a company name, drop punctuation and corporate-form words. Pure."""
    if not name:
        return ""
    flat = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in str(name).lower())
    return " ".join(w for w in flat.split() if w not in _CORP_FORMS)


def names_agree(registered, resolved) -> bool:
    """True when a registered name and a vendor-resolved companyName denote the same issuer.

    Tolerant of corporate-form and punctuation differences (prefix containment), so
    "Silver North Resources" matches "Silver North Resources Ltd." but not "Stag Industrial".
    Returns False when either side is empty — an unnameable side cannot be vouched for, and the
    caller decides whether that is a hard stop (see ``ticker_identity_conflict``, which treats a
    missing name as unjudgeable rather than as a conflict). Pure.
    """
    a, b = normalize_company_name(registered), normalize_company_name(resolved)
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def is_canadian_listing(ticker) -> bool:
    """True when a ticker carries an explicit Canadian exchange suffix. Pure."""
    return str(ticker or "").upper().endswith(CANADIAN_SUFFIXES)


def ticker_identity_conflict(ticker, registered_name, quote):
    """Return a short reason string when ``quote`` cannot belong to ``ticker``, else ``None``.

    The registration-time guard for the SNAG/GMX.TO bug class: a symbol that resolves to the wrong
    issuer. Deliberately conservative — it only reports a conflict it can PROVE from the payload,
    so a thin quote (no company name, no currency) is unjudgeable rather than suspect. Pure and
    network-free: callers pass whatever their vendor returned.
    """
    if not isinstance(quote, dict) or not quote:
        return None                                   # nothing resolved — not a conflict
    resolved_name = quote.get("companyName") or quote.get("name")
    if registered_name and resolved_name and not names_agree(registered_name, resolved_name):
        return ("resolves to %r, not %r — wrong issuer for %s"
                % (str(resolved_name), str(registered_name), ticker))
    ccy = str(quote.get("currency") or "").upper()
    if ccy and is_canadian_listing(ticker) and ccy != "CAD":
        return "%s carries a Canadian suffix but resolved in %s" % (ticker, ccy)
    return None
