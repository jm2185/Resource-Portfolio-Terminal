"""P1.1 provenance guard (docs/PROVENANCE_REMEDIATION_PLAN.md) — the CEG bear-case lesson encoded:
street/unstamped numbers must be LOUD on the face of the dual-sided output, never invisible."""
import dual_sided


BASE = {
    "ticker": "TEST", "lens": "compounder", "price": 100.0, "shares_out": 1_000_000,
    "fcf": 10_000_000, "stressed_fcf": 7_000_000, "wacc": 0.08, "cap_years": 15,
    "growth": {"p10": 0.0, "p50": 0.05, "p90": 0.10}, "quality": 0.7,
    "management_score": 0.6, "conviction": 0.5,
}

STAMP = {"source": "https://example.com/10-q", "as_of": "2026-08-01",
         "confidence": "high", "basis": "filed"}


def _prov(**overrides):
    p = {f: dict(STAMP) for f in dual_sided.PROVENANCE_LOAD_BEARING}
    p.update(overrides)
    return p


def test_unstamped_payload_is_degraded_with_a_flag_per_input():
    out = dual_sided.value(dict(BASE))
    assert out["provenance"]["degraded"] is True
    # every load-bearing input PRESENT in the payload gets an unstamped flag
    present = [f for f in dual_sided.PROVENANCE_LOAD_BEARING if BASE.get(f) is not None]
    assert sorted(out["provenance"]["flags"]) == sorted(f"unstamped:{f}" for f in present)


def test_fully_stamped_filed_payload_is_clean():
    payload = dict(BASE, provenance=_prov())
    out = dual_sided.value(payload)
    assert out["provenance"]["flags"] == []
    assert out["provenance"]["degraded"] is False
    assert "clean" in out["provenance"]["read"]


def test_street_basis_is_loud_but_does_not_block_the_valuation():
    payload = dict(BASE, provenance=_prov(fcf=dict(STAMP, basis="street")))
    out = dual_sided.value(payload)
    assert out["provenance"]["flags"] == ["street:fcf"]
    assert out["provenance"]["degraded"] is True
    # the valuation itself still runs — best-state-stays-usable
    assert out["lens_available"]["compounder"] is True


def test_bad_basis_vocabulary_is_flagged():
    payload = dict(BASE, provenance=_prov(wacc=dict(STAMP, basis="vibes")))
    out = dual_sided.value(payload)
    assert "bad_basis:wacc" in out["provenance"]["flags"]


def test_absent_inputs_are_not_provenance_flags():
    payload = dict(BASE, provenance=_prov())
    payload.pop("stressed_fcf")            # completeness issue, not provenance
    out = dual_sided.value(payload)
    assert all("stressed_fcf" not in f for f in out["provenance"]["flags"])
