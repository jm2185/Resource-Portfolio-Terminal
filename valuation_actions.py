"""
Shared what-if action logic (Iteration 2 — the action spine).

Pure helpers (no engine / numpy / fastapi import) so the math is unit-testable on
its own. The engine method ``Engine.run_whatif`` supplies the live router + base
inputs and calls these; the FastAPI route ``POST /action/whatif`` and the MCP tool
``run_valuation_whatif`` are thin wrappers over that one method — so the GUI, the
TUI, the Claude/agy panes and the agents all hit the same implementation.

Override grammar (one string or a dict):
    "silver=+5 ry=-0.5 peer=+20%"
  value forms:  79.8 (absolute) · +5 / -0.5 (delta) · +20% / -10% (percent of base)
  knobs:        silver/ag, gold, ry (real yield), vol, peer (EV/oz), mri, dxy
"""

from __future__ import annotations

# User-facing knob -> canonical engine input key.
ALIASES = {
    "silver": "spot_ag", "ag": "spot_ag", "spot_ag": "spot_ag",
    "gold": "gold", "au": "gold",
    "ry": "real_yield", "real_yield": "real_yield", "yield": "real_yield", "yields": "real_yield",
    "vol": "silver_vol", "silver_vol": "silver_vol",
    "peer": "peer_ev_oz", "ev": "peer_ev_oz", "peer_ev_oz": "peer_ev_oz",
    "mri": "mri", "regime": "mri",
    "dxy": "dxy",
    "capital_discount": "capital_discount",
}

# Canonical keys that feed the regime vector (recompute regime if any of these move).
REGIME_KEYS = {"real_yield", "silver_vol", "mri", "dxy"}
# Canonical keys that live in the payload's macro block.
MACRO_KEYS = {"spot_ag", "gold", "real_yield", "silver_vol", "capital_discount"}


def canonical(key: str):
    return ALIASES.get(str(key).strip().lower())


def parse_override(spec, base):
    """Resolve one override value against its base.

    number / "79.8" -> absolute · "+5"/"-0.5" -> delta from base · "+20%"/"-10%" -> percent of base.
    """
    if isinstance(spec, (int, float)):
        return float(spec)
    s = str(spec).strip()
    if not s:
        raise ValueError("empty override")
    try:
        if s.endswith("%"):
            if base is None:
                raise ValueError("percent override needs a base value")
            return float(base) * (1.0 + float(s[:-1]) / 100.0)
        if s[0] in "+-":
            return (float(base) if base is not None else 0.0) + float(s)
        return float(s)
    except ValueError as exc:
        raise ValueError(f"bad override value {spec!r}: {exc}")


def parse_overrides(text):
    """'silver=+5 ry=-0.5 peer=+20%' (or a dict) -> {canonical_key: raw_spec}, unknown knobs dropped."""
    if isinstance(text, dict):
        pairs = list(text.items())
    else:
        pairs = []
        for tok in str(text or "").replace(",", " ").split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                pairs.append((k, v))
    out = {}
    for k, v in pairs:
        ck = canonical(k)
        if ck is not None:
            out[ck] = v
    return out


def _upside(summary: dict, price):
    iv = summary.get("intrinsic_after_forensic")
    try:
        if price and iv is not None:
            return round((float(iv) / float(price) - 1.0) * 100.0, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


def summarize_delta(base: dict, scenario: dict, price, applied: dict) -> dict:
    """Diff two valuation_summary dicts into a compact base/scenario/delta report."""
    bi = base.get("intrinsic_after_forensic")
    si = scenario.get("intrinsic_after_forensic")
    try:
        intrinsic_pct = round((si / bi - 1.0) * 100.0, 1) if (bi and si) else None
    except (TypeError, ZeroDivisionError):
        intrinsic_pct = None
    bu, su = _upside(base, price), _upside(scenario, price)
    return {
        "price": price,
        "overrides_applied": applied,
        "base": {"intrinsic": bi, "upside_pct": bu, "legs": base.get("legs")},
        "scenario": {"intrinsic": si, "upside_pct": su, "legs": scenario.get("legs")},
        "delta": {
            "intrinsic_pct": intrinsic_pct,
            "upside_pp": (round(su - bu, 1) if (su is not None and bu is not None) else None),
        },
    }
