"""garage_book — the Boost Book's pure lane logic (status · close_week · transfers · set_ladder).

Everything runs against tmp_path fixtures (injectable config/ledger/today), so the suite exercises
the real contract the /garage/state endpoint, the web view, and the garage_* MCP tools share —
capture-rate honesty, earliest-unclosed targeting, append-only supersede, unlock events, and the
guarded config write — without touching the repo's live files.
"""
import json
from datetime import date, timedelta

import pytest

import garage_book as gb

LADDER = [
    {"name": "Accessport + Stage 1", "price": 950},
    {"name": "Cold-air intake", "price": 550},
    {"name": "Cat-back exhaust", "price": 1600},
]


def make_cfg(tmp_path, start, baseline=110, ladder=None, enabled=True, extra=None):
    block = {"enabled": enabled, "start_date": str(start), "baseline_weekly": baseline,
             "currency": "CAD", "close_day": "sunday", "prices_status": "illustrative",
             "ladder": LADDER if ladder is None else ladder}
    if extra:
        block.update(extra)
    p = tmp_path / "v5_config.json"
    p.write_text(json.dumps({"other_key": 1, "garage": block}, indent=2) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def paths(tmp_path):
    """(config_path, ledger_path, today) with the program starting 15 days ago → week 3 is open."""
    today = date(2026, 9, 16)
    cfg = make_cfg(tmp_path, today - timedelta(days=15))
    return cfg, tmp_path / "garage_ledger.jsonl", today


# --------------------------------------------------------------------------- status

def test_day_zero_status(tmp_path):
    today = date(2026, 9, 1)
    cfg = make_cfg(tmp_path, today)
    s = gb.status(cfg, tmp_path / "ledger.jsonl", today=today)
    assert s["ok"] and s["enabled"]
    assert s["weeks_closed"] == 0 and s["accumulated"] == 0
    assert s["capture"] == 1.0 and s["capture_basis"] == "assumed"
    assert s["runrate_weekly"] == 110 and s["streak"] == 0
    assert s["week_current"] == 0 and s["week_open"]["closed"] is False
    assert s["missed_weeks"] == []
    assert all(not m["unlocked"] for m in s["ladder"])
    # first strike 950 @ 110/wk → 9 whole weeks → 63 days
    assert s["next_unlock"]["name"] == "Accessport + Stage 1"
    assert s["next_unlock"]["eta_days"] == 63
    assert s["ladder_total"] == 3100
    assert s["headline"].startswith("GARAGE — $0 banked")


def test_unconfigured_and_disabled(tmp_path):
    s = gb.status(tmp_path / "missing.json", tmp_path / "ledger.jsonl")
    assert s["ok"] and not s["enabled"]
    cfg = make_cfg(tmp_path, date(2026, 9, 1), enabled=False)
    assert not gb.status(cfg, tmp_path / "ledger.jsonl")["enabled"]
    r = gb.close_week(0, config_path=cfg, ledger_path=tmp_path / "ledger.jsonl")
    assert not r["ok"]


def test_before_start_refuses(tmp_path):
    today = date(2026, 9, 1)
    cfg = make_cfg(tmp_path, today + timedelta(days=3))
    s = gb.status(cfg, tmp_path / "ledger.jsonl", today=today)
    assert s["week_current"] == -1 and s["week_open"] is None
    r = gb.close_week(0, config_path=cfg, ledger_path=tmp_path / "ledger.jsonl", today=today)
    assert not r["ok"] and "starts" in r["error"]


# --------------------------------------------------------------------------- close_week

def test_close_accumulates_and_captures(paths):
    cfg, led, today = paths
    r1 = gb.close_week(0, config_path=cfg, ledger_path=led, today=today)
    assert r1["ok"] and r1["week"] == 0 and r1["banked"] == 110 and not r1["superseded"]
    r2 = gb.close_week(25, config_path=cfg, ledger_path=led, today=today)
    assert r2["week"] == 1 and r2["banked"] == 85
    s = gb.status(cfg, led, today=today)
    assert s["accumulated"] == 195 and s["possible"] == 220
    assert s["capture"] == pytest.approx(195 / 220, abs=1e-4)
    assert s["capture_basis"] == "observed"
    assert s["runrate_weekly"] == pytest.approx(110 * 195 / 220, abs=0.01)


def test_earliest_unclosed_then_refuse_when_done(paths):
    cfg, led, today = paths
    for expect in (0, 1, 2):                      # today is in week 2 (day 15) → three closable weeks
        assert gb.close_week(0, config_path=cfg, ledger_path=led, today=today)["week"] == expect
    r = gb.close_week(0, config_path=cfg, ledger_path=led, today=today)
    assert not r["ok"] and "amend" in r["error"]


def test_explicit_amend_supersedes(paths):
    cfg, led, today = paths
    gb.close_week(0, config_path=cfg, ledger_path=led, today=today)
    r = gb.close_week(80, week=0, config_path=cfg, ledger_path=led, today=today)
    assert r["ok"] and r["superseded"]
    s = gb.status(cfg, led, today=today)
    assert s["weeks_closed"] == 1 and s["accumulated"] == 30       # last write per week wins
    assert len(gb._read_ledger(led)) == 2                          # …but nothing was rewritten


def test_future_week_refused_and_clamping(paths):
    cfg, led, today = paths
    assert not gb.close_week(0, week=9, config_path=cfg, ledger_path=led, today=today)["ok"]
    r = gb.close_week(999, config_path=cfg, ledger_path=led, today=today)
    assert r["ok"] and r["clamped"] and r["banked"] == 0
    r2 = gb.close_week(-5, config_path=cfg, ledger_path=led, today=today)
    assert r2["clamped"] and r2["banked"] == 110
    assert not gb.close_week("not a number", config_path=cfg, ledger_path=led, today=today)["ok"]


def test_unlock_event_and_pull_forward(tmp_path):
    today = date(2026, 9, 16)
    cfg = make_cfg(tmp_path, today - timedelta(days=15),
                   ladder=[{"name": "Tune", "price": 200}, {"name": "Intake", "price": 500}])
    led = tmp_path / "ledger.jsonl"
    r1 = gb.close_week(0, config_path=cfg, ledger_path=led, today=today)
    assert r1["unlocked"] == [] and r1["pulled_forward_days"] is not None
    r2 = gb.close_week(0, config_path=cfg, ledger_path=led, today=today)   # 220 ≥ 200 → Tune unlocks
    assert r2["unlocked"] == ["Tune"]
    s = gb.status(cfg, led, today=today)
    assert s["unlocked_count"] == 1 and s["ladder"][0]["funded_pct"] == 100.0
    assert s["next_unlock"]["name"] == "Intake"


def test_streak_and_missed_weeks(paths):
    cfg, led, today = paths
    gb.close_week(0, week=0, config_path=cfg, ledger_path=led, today=today)
    gb.close_week(0, week=2, config_path=cfg, ledger_path=led, today=today)   # week 1 skipped
    s = gb.status(cfg, led, today=today)
    assert s["missed_weeks"] == [1]
    assert s["streak"] == 1                       # the gap breaks continuity
    gb.close_week(0, week=1, config_path=cfg, ledger_path=led, today=today)   # backfilled clean
    assert gb.status(cfg, led, today=today)["streak"] == 3


# --------------------------------------------------------------------------- transfers

def test_transfers_reconcile(paths):
    cfg, led, today = paths
    gb.close_week(0, config_path=cfg, ledger_path=led, today=today)
    assert not gb.log_transfer(0, config_path=cfg, ledger_path=led)["ok"]
    gb.log_transfer(110, note="weekly sweep", config_path=cfg, ledger_path=led)
    r = gb.log_transfer(-40, note="bought stickers", config_path=cfg, ledger_path=led)
    assert r["ok"] and r["transfers"]["count"] == 2 and r["transfers"]["total"] == 70
    assert r["transfers"]["drift"] == 40          # ledger says 110 banked, only 70 net moved


# --------------------------------------------------------------------------- set_ladder

def test_set_ladder_dry_then_confirm(tmp_path):
    cfg = make_cfg(tmp_path, date(2026, 9, 1))
    plan = gb.set_ladder([{"name": "Coilovers", "price": 2400}], config_path=cfg)
    assert plan["ok"] and not plan["applied"] and plan["total"] == 2400
    assert json.loads(cfg.read_text())["garage"]["ladder"] == LADDER      # dry = untouched
    done = gb.set_ladder([{"name": "Coilovers", "price": 2400}], confirm=True, config_path=cfg)
    assert done["ok"] and done["applied"]
    new = json.loads(cfg.read_text())
    assert new["garage"]["ladder"] == [{"name": "Coilovers", "price": 2400}]
    assert new["garage"]["prices_status"] == "operator"
    assert new["other_key"] == 1                                          # rest of config untouched
    assert (tmp_path / "v5_config.json").exists()
    assert list(tmp_path.glob("v5_config.json.bak.garage.*"))             # timestamped backup


def test_set_ladder_validation(tmp_path):
    cfg = make_cfg(tmp_path, date(2026, 9, 1))
    assert not gb.set_ladder([], config_path=cfg)["ok"]
    assert not gb.set_ladder("not json{", config_path=cfg)["ok"]
    assert not gb.set_ladder([{"name": "", "price": 5}], config_path=cfg)["ok"]
    assert not gb.set_ladder([{"name": "A", "price": -1}], config_path=cfg)["ok"]
    dup = [{"name": "A", "price": 1}, {"name": "a", "price": 2}]
    assert not gb.set_ladder(dup, config_path=cfg)["ok"]
    ok = gb.set_ladder(json.dumps([{"name": "A", "price": 1.5}]), config_path=cfg)
    assert ok["ok"] and ok["proposed"] == [{"name": "A", "price": 1.5}]


# --------------------------------------------------------------------------- weeks_to

def test_weeks_to_math():
    assert gb.weeks_to(950, 110) == 9
    assert gb.weeks_to(100, 110, start_balance=200) == 0
    assert gb.weeks_to(100, 0) is None
    assert gb.weeks_to(10_000_000, 1) is None                 # unreachable inside the horizon
    flat, edged = gb.weeks_to(3000, 50), gb.weeks_to(3000, 50, annual_edge_pct=20)
    assert edged < flat                                        # a positive edge accelerates
