"""coherence_check + conclusion_decay (F3 of docs/FABLE_INTEGRATION.md).

Seeded contradiction fixtures for every pattern, the zero-false-positive check on a clean state,
and the decay sweep's holds/dead/unknown discipline (absence of evidence never kills a thesis).
"""
import coherence_check as cc
import conclusion_decay as cd
from living_memory import LivingMemory


def _state(*, mri=48.0, posture_code="balanced", cap=1.0, baskets=None):
    return {"mri": mri,
            "posture": {"code": posture_code, "label": posture_code.upper(), "cap": cap},
            "conviction_mode": {"baskets": baskets or []}}


def _basket(tk="AGA.V", directive="ACCUMULATE", price=10.0, floor=6.0,
            gate_applied=False, gate_cap=None, rho=2.0, phi=1.2):
    return {"ticker": tk, "directive": directive,
            "ladder": {"price": price, "floor": floor, "base": price * 1.3, "bull": price * 2},
            "gate": {"applied": gate_applied, "cap": gate_cap, "reason": "test"},
            "pillars": {"V": {"rho": rho, "floor_coverage": phi, "upside_pct": 80}}}


# ------------------------------------------------------------------ clean state: no false positives
def test_clean_state_is_coherent():
    st = _state(baskets=[_basket(), _basket(tk="GROY", directive="CORE HOLD", price=5, floor=3)])
    verdicts = [{"ticker": "AGA.V", "stance": "HOLD", "engine_directive": "ACCUMULATE",
                 "tension": "bear names dilution", "caveats": ["floor at 6"]}]
    out = cc.check_state(st, verdicts=verdicts, pinned_entries=[], superseded_ids=set())
    assert out["findings"] == [] and "coherent" in out["read"]


def test_empty_state_checks_nothing():
    out = cc.check_state(None)
    assert out["findings"] == []
    assert cc.check_delta(None, cc.snapshot(None)) == []


# ------------------------------------------------------------------ diversifier_cut_on_narrative
# The GMX lesson (2026-09-04): the desk measured a holding at the LOWEST ρ to the spear and then cut
# it arguing it "duplicates diversification". A taxonomy claim must never silently outrank a number
# the desk already computed.
def _book_factor(spear_corr, avg, spear="AGA.V"):
    return {"concentration": {"available": True, "spear": spear, "avg_pairwise": avg,
                              "spear_corr": spear_corr, "single_factor": avg >= 0.60,
                              "flags": [], "read": "test"}}


def test_diversifier_cut_on_narrative_fires_on_the_least_correlated_name():
    st = _state(baskets=[_basket(tk="GMX.TO", directive="RICH — TRIM", price=1.89, floor=0.71),
                         _basket(tk="GROY", directive="CORE HOLD", price=5, floor=3)])
    st["book_factor"] = _book_factor({"GMX.TO": 0.387, "GROY": 0.72}, 0.60)
    out = cc.check_state(st)
    f = [x for x in out["findings"] if x["id"] == "diversifier_cut_on_narrative"]
    assert len(f) == 1 and f[0]["ticker"] == "GMX.TO"
    assert f[0]["signals"]["rank"] == 1 and f[0]["signals"]["of"] == 2
    assert "must outrank the desk's own number" in f[0]["why"]


def test_diversifier_not_flagged_when_held_or_accumulated():
    st = _state(baskets=[_basket(tk="GMX.TO", directive="CORE HOLD", price=1.89, floor=0.71)])
    st["book_factor"] = _book_factor({"GMX.TO": 0.387, "GROY": 0.72}, 0.60)
    assert [f for f in cc.check_state(st)["findings"] if f["id"] == "diversifier_cut_on_narrative"] == []


def test_diversifier_needs_a_real_margin_below_the_book_average():
    # lowest pair, but only a hair below average — "lowest" inside a tight cluster means nothing
    st = _state(baskets=[_basket(tk="GMX.TO", directive="RICH — TRIM", price=1.89, floor=0.71)])
    st["book_factor"] = _book_factor({"GMX.TO": 0.78, "GROY": 0.82}, 0.80)
    assert [f for f in cc.check_state(st)["findings"] if f["id"] == "diversifier_cut_on_narrative"] == []


def test_diversifier_check_needs_two_measured_names():
    st = _state(baskets=[_basket(tk="GMX.TO", directive="RICH — TRIM", price=1.89, floor=0.71)])
    st["book_factor"] = _book_factor({"GMX.TO": 0.20}, 0.60)
    assert [f for f in cc.check_state(st)["findings"] if f["id"] == "diversifier_cut_on_narrative"] == []


def test_diversifier_check_is_total_on_a_missing_or_junk_block():
    st = _state(baskets=[_basket(tk="GMX.TO", directive="RICH — TRIM", price=1.89, floor=0.71)])
    assert cc.check_state(st)["findings"] is not None            # no book_factor at all
    for junk in ({"concentration": None}, {"concentration": {"spear_corr": "nope"}},
                 {"concentration": {"spear_corr": {"A": "x", "B": None}, "avg_pairwise": None}}):
        st["book_factor"] = junk
        assert [f for f in cc.check_state(st)["findings"]
                if f["id"] == "diversifier_cut_on_narrative"] == []


# ------------------------------------------------------------------ each contradiction pattern
def test_rich_below_floor_fires_only_on_avoid_side():
    below = _basket(directive="TRIM — RICH", price=4.0, floor=6.0)
    st = _state(baskets=[below])
    out = cc.check_state(st)
    assert [f["id"] for f in out["findings"]] == ["rich_below_floor"]
    # the same price/floor with an accumulate directive is fine (below floor = deep value)
    st2 = _state(baskets=[_basket(directive="ACCUMULATE — BELOW FLOOR", price=4.0, floor=6.0)])
    assert cc.check_state(st2)["findings"] == []


def test_severe_gate_beside_accumulate_is_risk():
    st = _state(baskets=[_basket(directive="ACCUMULATE", gate_applied=True, gate_cap=3.0)])
    f = cc.check_state(st)["findings"]
    assert [x["id"] for x in f] == ["severe_gate_bullish"] and f[0]["level"] == "risk"
    # a mild gate (cap above the severe bar) does not fire
    st2 = _state(baskets=[_basket(directive="ACCUMULATE", gate_applied=True, gate_cap=8.0)])
    assert cc.check_state(st2)["findings"] == []


def test_press_verdict_under_tight_posture_needs_the_cap_note():
    st = _state(posture_code="defensive", cap=0.75)
    naked = [{"ticker": "AGA.V", "stance": "PRESS", "engine_directive": "ACCUMULATE",
              "tension": "t", "caveats": ["c"]}]
    out = cc.check_state(st, verdicts=naked)
    assert [f["id"] for f in out["findings"]] == ["press_missing_cap_note"]
    stamped = [dict(naked[0], posture_note="regime posture DEFENSIVE caps size to 0.75x")]
    assert cc.check_state(st, verdicts=stamped)["findings"] == []


def test_verdict_flip_without_named_dissent():
    st = _state()
    flip = [{"ticker": "GROY", "stance": "EXIT / DE-RISK", "engine_directive": "ACCUMULATE",
             "tension": None, "caveats": []}]
    out = cc.check_state(st, verdicts=flip)
    assert [f["id"] for f in out["findings"]] == ["verdict_flip_unnamed"]
    named = [dict(flip[0], tension="grounded dilution claim")]
    assert cc.check_state(st, verdicts=named)["findings"] == []


def test_stale_pin_detected_via_memory_adapter(tmp_path):
    mem = LivingMemory(path=str(tmp_path / "lm.jsonl"))
    old = mem.write("note", text="original claim", ticker="URC.TO", source="user")
    mem.pin(old["id"])
    mem.supersede(old["id"], "note", text="corrected claim", ticker="URC.TO", source="user")
    pinned, sup = cc.memory_inputs(mem)
    out = cc.check_state(_state(), pinned_entries=pinned, superseded_ids=sup)
    assert [f["id"] for f in out["findings"]] == ["stale_pinned_memory"]
    assert out["findings"][0]["signals"]["entry_id"] == old["id"]


def test_cap_loosened_as_mri_rose_delta():
    prev = cc.snapshot(_state(mri=50, cap=0.9))
    worse_but_looser = cc.snapshot(_state(mri=56, cap=1.1))
    f = cc.check_delta(prev, worse_but_looser)
    assert [x["id"] for x in f] == ["cap_loosened_as_mri_rose"]
    # loosening while MRI improves is fine; tightening while MRI rises is fine
    assert cc.check_delta(prev, cc.snapshot(_state(mri=45, cap=1.1))) == []
    assert cc.check_delta(prev, cc.snapshot(_state(mri=56, cap=0.8))) == []


# ------------------------------------------------------------------ conclusion decay
def _facts():
    return cd.facts_from_state(_state(
        mri=55, posture_code="defensive", cap=0.8,
        baskets=[_basket(tk="AGA.V", price=8.0, floor=6.0, rho=2.5, phi=1.1)]))


def test_facts_from_state_shapes_book_and_names():
    f = _facts()
    assert f["book"]["mri"] == 55 and f["book"]["posture"] == "defensive"
    assert f["AGA.V"]["price"] == 8.0 and f["AGA.V"]["phi"] == 1.1


def test_claim_holds_dead_unknown():
    f = _facts()
    holds = cd.evaluate_claim({"metric": "phi", "op": ">=", "value": 1.0}, f, ticker="AGA.V")
    dead = cd.evaluate_claim({"metric": "phi", "op": ">=", "value": 1.5}, f, ticker="AGA.V")
    unknown = cd.evaluate_claim({"metric": "runway_months", "op": ">", "value": 12}, f, ticker="AGA.V")
    assert (holds["status"], dead["status"], unknown["status"]) == ("holds", "dead", "unknown")
    assert dead["observed"] == 1.1


def test_claim_resolves_book_scope_and_string_equality():
    f = _facts()
    assert cd.evaluate_claim({"metric": "mri", "op": "<", "value": 60}, f,
                             ticker="AGA.V")["status"] == "holds"
    assert cd.evaluate_claim({"metric": "posture", "op": "==", "value": "DEFENSIVE"},
                             f)["status"] == "holds"
    # an ordered op on a label is unknown, not a crash and not a kill
    assert cd.evaluate_claim({"metric": "posture", "op": ">", "value": 1}, f)["status"] == "unknown"


def test_sweep_decays_only_on_a_dead_claim():
    f = _facts()
    entries = [
        {"id": "e1", "ticker": "AGA.V", "type": "verdict", "text": "accumulate thesis",
         "meta": {"assumptions": [{"claim": "above floor", "metric": "phi", "op": ">=", "value": 1.0}]}},
        {"id": "e2", "ticker": "AGA.V", "type": "verdict", "text": "needs deep value",
         "meta": {"assumptions": [{"claim": "price under 7", "metric": "price", "op": "<", "value": 7.0}]}},
        {"id": "e3", "ticker": "AGA.V", "type": "note", "text": "runway claim",
         "meta": {"assumptions": [{"claim": "runway > 12", "metric": "runway_months", "op": ">", "value": 12}]}},
        {"id": "e4", "ticker": "AGA.V", "type": "note", "text": "no assumptions"},
    ]
    out = cd.sweep(entries, f)
    assert [r["entry_id"] for r in out["decayed"]] == ["e2"]
    assert [r["entry_id"] for r in out["holding"]] == ["e1"]
    assert [r["entry_id"] for r in out["unchecked"]] == ["e3"]     # unanswerable ≠ dead
    assert out["n_swept"] == 3 and "DECAYED" in out["read"]


def test_sweep_round_trips_through_living_memory(tmp_path):
    """The intended flow: a verdict written with structured assumptions decays when the engine
    facts move, and the supersede (caller's job) clears it from the next sweep."""
    mem = LivingMemory(path=str(tmp_path / "lm.jsonl"))
    v = mem.write("council_verdict", text="ACCUMULATE — floor holds", ticker="AGA.V", source="arbiter",
                  meta={"assumptions": [{"claim": "still above the stressed floor",
                                         "metric": "phi", "op": ">=", "value": 1.0}]})
    facts_bad = cd.facts_from_state(_state(
        baskets=[_basket(tk="AGA.V", phi=0.8)]))                   # the floor leg died
    out = cd.sweep(mem.query(ticker="AGA.V"), facts_bad)
    assert [r["entry_id"] for r in out["decayed"]] == [v["id"]]
    mem.supersede(v["id"], "council_verdict", text="DECAYED — φ fell under 1.0; re-underwrite",
                  ticker="AGA.V", source="engine")
    out2 = cd.sweep(mem.query(ticker="AGA.V"), facts_bad)
    assert out2["decayed"] == []                                    # successor carries no dead claim
