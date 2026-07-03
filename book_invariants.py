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
