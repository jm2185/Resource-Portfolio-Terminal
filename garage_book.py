"""The Garage lane — the Boost Book, the desk's personal reallocation book (GARAGE view).

The premise inverts a budget tracker: the weekly alcohol baseline (config ``garage.baseline_weekly``)
is redirected to the WRX build **by default** — the operator never logs savings, only the part that
got away (``close_week(failed=…)``). The book therefore counts what was *stacked*, never what was
burned; a failed week just adds less. Projections and unlock ETAs run off the **observed capture
rate** (banked ÷ possible), so a clean week does double duty — it adds the full baseline *and*
raises the pace every future week is projected at — while a bust visibly slips the next mod's date.
Honest by construction: the ETA reflects the demonstrated track record, not the intention.

Pure, dependency-light, and unit-testable (the ``divergence_monitor.explain_context`` doctrine):
every public function takes injectable ``config_path`` / ``ledger_path`` / ``today``. Consumers are
thin — the engine API serves ``status()`` at ``/garage/state`` (web/garage.html renders it), and the
MCP tools in ``mcp_server/core.py`` pass through here, so chat stays the recording device
("failed $25 this week" → one ``close_week`` call).

Store: ``data/garage_ledger.jsonl`` — append-only, immutable, human-readable (the Living-Memory
discipline). A re-close of the same week is a NEW line that supersedes the old one (last write per
week wins); nothing is ever rewritten. Config: the ``garage`` block of ``v5_config.json`` —
``set_ladder`` is the one guarded writer (dry plan → ``confirm=True``, timestamped backup,
byte-stable dump so the diff stays surgical).

Week semantics: week ``k`` covers the 7-day block ``[start_date + 7k, start_date + 7k + 6]``.
``close_week`` targets the EARLIEST unclosed week up to today by default (the record stays gapless
when the operator catches up in order); an explicit ``week=`` amends a specific one. Closing a
future week is refused. Money moves are ``log_transfer`` entries (deposits > 0, a mod purchase < 0);
``status()["transfers"]["drift"]`` reconciles the ledger against what actually moved — the same
ground-truth-vs-record discipline as the Wealthsimple book snapshot.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "v5_config.json"
LEDGER_PATH = ROOT / "data" / "garage_ledger.jsonl"

# Validation bounds for set_ladder — generous, just there to catch garbage.
MAX_LADDER_ITEMS = 24
MAX_NAME_LEN = 60


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_date(d) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    return date.fromisoformat(str(d).strip()[:10])


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def load_config(config_path: Path | str = CONFIG_PATH) -> dict:
    """The effective ``garage`` block with defaults merged; ``{"enabled": False}`` when absent."""
    try:
        with open(config_path, encoding="utf-8") as f:
            block = (json.load(f) or {}).get("garage") or {}
    except (OSError, ValueError, json.JSONDecodeError):
        block = {}
    if not block:
        return {"enabled": False}
    out = {
        "enabled": bool(block.get("enabled", True)),
        "start_date": str(block.get("start_date") or date.today().isoformat()),
        "baseline_weekly": _num(block.get("baseline_weekly")) or 0.0,
        "currency": str(block.get("currency") or "CAD"),
        "close_day": str(block.get("close_day") or "sunday"),
        "account": str(block.get("account") or ""),
        "prices_status": str(block.get("prices_status") or "illustrative"),
        "ladder": [],
    }
    for m in block.get("ladder") or []:
        name = str((m or {}).get("name") or "").strip()
        price = _num((m or {}).get("price"))
        if name and price and price > 0:
            out["ladder"].append({"name": name, "price": price})
    return out


def _read_ledger(ledger_path: Path | str = LEDGER_PATH) -> list:
    rows = []
    try:
        with open(ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue                       # tolerate a corrupt line, never lose the rest
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _append(ledger_path: Path | str, row: dict) -> None:
    p = Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def effective_closes(rows: list) -> list:
    """Effective week-closes, ascending by week — the LAST entry per week wins (supersede)."""
    by_week: dict[int, dict] = {}
    for r in rows:
        if r.get("type") == "week_close":
            try:
                by_week[int(r.get("week"))] = r
            except (TypeError, ValueError):
                continue
    return [by_week[w] for w in sorted(by_week)]


def weeks_to(amount: float, weekly: float, start_balance: float = 0.0,
             annual_edge_pct: float = 0.0, max_weeks: int = 520):
    """Whole weeks until the balance reaches ``amount`` at ``weekly`` deposits, compounding an
    optional annualized edge — the shared ETA math (mirrored client-side by web/garage.html).
    Returns ``None`` when unreachable inside ``max_weeks``; 0 when already funded."""
    if start_balance >= amount:
        return 0
    if weekly <= 0 and annual_edge_pct <= 0:
        return None
    r = (1.0 + annual_edge_pct / 100.0) ** (1.0 / 52.0) - 1.0
    bal = start_balance
    for w in range(1, max_weeks + 1):
        bal = (bal + weekly) * (1.0 + r)
        if bal >= amount:
            return w
    return None


# --------------------------------------------------------------------------- #
# The read surface
# --------------------------------------------------------------------------- #

def status(config_path: Path | str = CONFIG_PATH, ledger_path: Path | str = LEDGER_PATH,
           today=None) -> dict:
    """The whole GARAGE view as one dict — the contract /garage/state, the web page, the MCP
    ``garage_status`` tool, and the tests all share. Cheap (two small file reads); compute-on-read,
    no cache to go stale."""
    cfg = load_config(config_path)
    if not cfg.get("enabled"):
        return {"ok": True, "enabled": False,
                "note": "garage lane not configured — add the `garage` block to v5_config.json"}
    t = _as_date(today or date.today())
    start = _as_date(cfg["start_date"])
    baseline = float(cfg["baseline_weekly"])

    week_current = (t - start).days // 7 if t >= start else -1
    closes = effective_closes(_read_ledger(ledger_path))
    closes_view = [{"week": int(c["week"]), "failed": float(c.get("failed") or 0.0),
                    "banked": float(c.get("banked") or 0.0), "ts": c.get("ts"),
                    "note": c.get("note") or ""} for c in closes]

    accumulated = sum(c["banked"] for c in closes_view)
    possible = baseline * len(closes_view)
    capture = (accumulated / possible) if possible > 0 else 1.0
    capture_basis = "observed" if closes_view else "assumed"
    runrate = baseline * capture

    # Trailing clean streak — consecutive week numbers, zero failed; a missed week breaks it.
    streak = 0
    expect = closes_view[-1]["week"] if closes_view else None
    for c in reversed(closes_view):
        if c["week"] != expect or c["failed"] > 0:
            break
        streak += 1
        expect -= 1

    closed_weeks = {c["week"] for c in closes_view}
    missed = [w for w in range(0, max(week_current, 0)) if w not in closed_weeks] \
        if week_current >= 0 else []

    week_open = None
    if week_current >= 0:
        ws = start + timedelta(days=7 * week_current)
        week_open = {"index": week_current, "start": ws.isoformat(),
                     "end": (ws + timedelta(days=6)).isoformat(),
                     "closed": week_current in closed_weeks}

    ladder, next_unlock, cum = [], None, 0.0
    for m in cfg["ladder"]:
        cum += m["price"]
        unlocked = accumulated >= cum
        eta_w = None if unlocked else weeks_to(cum, runrate, accumulated)
        eta_days = None if eta_w is None else eta_w * 7
        eta_date = (t + timedelta(days=eta_days)).isoformat() if eta_days is not None else None
        row = {"name": m["name"], "price": m["price"], "cum": cum,
               "funded_pct": round(min(100.0, accumulated / cum * 100.0), 1),
               "unlocked": unlocked, "eta_days": eta_days, "eta_date": eta_date}
        ladder.append(row)
        if next_unlock is None and not unlocked:
            next_unlock = {"name": m["name"], "cum": cum,
                           "remaining": round(cum - accumulated, 2),
                           "eta_days": eta_days, "eta_date": eta_date}

    transfers = [r for r in _read_ledger(ledger_path) if r.get("type") == "transfer"]
    tr_total = sum(_num(r.get("amount")) or 0.0 for r in transfers)

    head = [f"${accumulated:,.0f} banked", f"{capture * 100:.0f}% capture"
            + (" (assumed)" if capture_basis == "assumed" else ""), f"streak {streak}"]
    if next_unlock:
        head.append(f"next: {next_unlock['name']} "
                    + (f"in {next_unlock['eta_days']}d" if next_unlock["eta_days"] is not None else "ETA —"))
    elif ladder:
        head.append("ladder complete")
    if week_open is not None and not week_open["closed"]:
        head.append(f"week {week_open['index'] + 1} open (closes {week_open['end']})")
    if missed:
        head.append(f"{len(missed)} week(s) unclosed")

    return {
        "ok": True, "enabled": True, "asof": _now_iso(), "today": t.isoformat(),
        "start_date": start.isoformat(), "baseline_weekly": baseline,
        "currency": cfg["currency"], "close_day": cfg["close_day"], "account": cfg["account"],
        "prices_status": cfg["prices_status"],
        "week_current": week_current, "week_open": week_open, "missed_weeks": missed,
        "closes": closes_view, "weeks_closed": len(closes_view),
        "accumulated": round(accumulated, 2), "possible": round(possible, 2),
        "capture": round(capture, 4), "capture_basis": capture_basis,
        "runrate_weekly": round(runrate, 2), "streak": streak,
        "ladder": ladder, "next_unlock": next_unlock,
        "unlocked_count": sum(1 for m in ladder if m["unlocked"]),
        "ladder_total": round(cum, 2),
        "transfers": {"count": len(transfers), "total": round(tr_total, 2),
                      "drift": round(accumulated - tr_total, 2)},
        "headline": "GARAGE — " + " · ".join(head),
    }


# --------------------------------------------------------------------------- #
# The write surface (append-only)
# --------------------------------------------------------------------------- #

def close_week(failed, note: str = "", source: str = "operator", week: int | None = None,
               config_path: Path | str = CONFIG_PATH, ledger_path: Path | str = LEDGER_PATH,
               today=None) -> dict:
    """Close a week by designating how much of the baseline got away (``failed`` — 0 = clean).

    Default target is the EARLIEST unclosed week up to today, so catching up after a lapse stays
    in order and gapless; pass ``week`` (0-based) to amend a specific one — the new line supersedes
    the old (append-only correction). Closing a week that hasn't started is refused. Returns the
    close plus what it did to the book: accumulated, capture, any mods it UNLOCKED, and how many
    days the next locked mod pulled forward (negative = it slipped)."""
    cfg = load_config(config_path)
    if not cfg.get("enabled"):
        return {"ok": False, "error": "garage lane not configured (no `garage` block in config)"}
    baseline = float(cfg["baseline_weekly"])
    f = _num(failed)
    if f is None:
        return {"ok": False, "error": "failed must be a number (dollars of the baseline that got away)"}
    clamped = False
    if f < 0 or f > baseline:
        f, clamped = min(max(f, 0.0), baseline), True

    t = _as_date(today or date.today())
    start = _as_date(cfg["start_date"])
    week_current = (t - start).days // 7 if t >= start else -1
    if week_current < 0:
        return {"ok": False, "error": f"the program starts {start.isoformat()} — nothing to close yet"}

    before = status(config_path, ledger_path, today=t)
    closed = {c["week"] for c in before["closes"]}
    superseded = False
    if week is None:
        target = next((w for w in range(0, week_current + 1) if w not in closed), None)
        if target is None:
            return {"ok": False, "error": f"weeks 1–{week_current + 1} are all closed — pass week= to amend one"}
    else:
        target = int(week)
        if target < 0 or target > week_current:
            return {"ok": False, "error": f"week must be 0–{week_current} (can't close a week that hasn't started)"}
        superseded = target in closed

    row = {"type": "week_close", "week": target, "failed": round(f, 2),
           "banked": round(baseline - f, 2), "ts": _now_iso(),
           "note": str(note or ""), "source": str(source or "operator")}
    _append(ledger_path, row)

    after = status(config_path, ledger_path, today=t)
    unlocked = [m["name"] for b, m in zip(before["ladder"], after["ladder"])
                if not b["unlocked"] and m["unlocked"]]
    pulled = None
    nb, na = before.get("next_unlock"), after.get("next_unlock")
    if nb and nb.get("eta_days") is not None:
        if na is None or na["name"] != nb["name"]:
            pulled = nb["eta_days"]                       # it unlocked outright
        elif na.get("eta_days") is not None:
            pulled = nb["eta_days"] - na["eta_days"]

    ws = start + timedelta(days=7 * target)
    return {"ok": True, "week": target, "week_start": ws.isoformat(),
            "week_end": (ws + timedelta(days=6)).isoformat(),
            "failed": row["failed"], "banked": row["banked"], "clamped": clamped,
            "superseded": superseded, "accumulated": after["accumulated"],
            "capture": after["capture"], "streak": after["streak"],
            "unlocked": unlocked, "next_unlock": na,
            "pulled_forward_days": pulled, "headline": after["headline"]}


def log_transfer(amount, note: str = "", source: str = "operator",
                 config_path: Path | str = CONFIG_PATH,
                 ledger_path: Path | str = LEDGER_PATH) -> dict:
    """Record real money moving to/from the dedicated WRX account (deposit > 0; a mod purchase or
    withdrawal < 0). The ledger's banked total is the *record*; transfers are the *ground truth* —
    ``drift`` in the result is the reconciliation between them (the WS-snapshot discipline)."""
    if not load_config(config_path).get("enabled"):
        return {"ok": False, "error": "garage lane not configured (no `garage` block in config)"}
    amt = _num(amount)
    if amt is None or amt == 0:
        return {"ok": False, "error": "amount must be a nonzero number (deposit > 0, withdrawal < 0)"}
    _append(ledger_path, {"type": "transfer", "amount": round(amt, 2), "ts": _now_iso(),
                          "note": str(note or ""), "source": str(source or "operator")})
    s = status(config_path, ledger_path)
    return {"ok": True, "amount": round(amt, 2), "transfers": s["transfers"],
            "note": "drift = banked-in-ledger minus actually-transferred; sweep the difference"}


def set_ladder(ladder, confirm: bool = False, config_path: Path | str = CONFIG_PATH) -> dict:
    """Replace the mod ladder (ordered ``[{name, price}, …]`` — order IS the unlock order).

    The one config writer in this lane, so it follows the house write gate: without ``confirm`` it
    returns the exact write plan (current vs proposed) and touches nothing; ``confirm=True`` applies
    it — timestamped backup, byte-stable dump (indent detected from the file so the diff is only the
    garage block), and ``prices_status`` flips to ``operator`` (the ladder is now the real build
    list, not the illustrative default)."""
    if isinstance(ladder, str):
        try:
            ladder = json.loads(ladder)
        except (ValueError, json.JSONDecodeError):
            return {"ok": False, "error": "ladder is not valid JSON"}
    if not isinstance(ladder, list) or not ladder:
        return {"ok": False, "error": "ladder must be a non-empty list of {name, price}"}
    if len(ladder) > MAX_LADDER_ITEMS:
        return {"ok": False, "error": f"ladder too long (max {MAX_LADDER_ITEMS} mods)"}
    clean, seen = [], set()
    for i, m in enumerate(ladder):
        name = str((m or {}).get("name") or "").strip()[:MAX_NAME_LEN]
        price = _num((m or {}).get("price"))
        if not name:
            return {"ok": False, "error": f"ladder[{i}]: name required"}
        if name.lower() in seen:
            return {"ok": False, "error": f"ladder[{i}]: duplicate name '{name}'"}
        if price is None or price <= 0:
            return {"ok": False, "error": f"ladder[{i}] ('{name}'): price must be > 0"}
        seen.add(name.lower())
        clean.append({"name": name, "price": round(price, 2)})

    try:
        raw = open(config_path, encoding="utf-8").read()
        cfg = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"config unreadable: {e}"}
    if "garage" not in cfg:
        return {"ok": False, "error": "no `garage` block in config — add it first"}

    current = cfg["garage"].get("ladder") or []
    if not confirm:
        return {"ok": True, "applied": False, "current": current, "proposed": clean,
                "total": round(sum(m["price"] for m in clean), 2),
                "note": "dry plan — re-call with confirm=True to apply (timestamped backup taken)"}

    indent = 2 if raw.splitlines()[1:2] and raw.splitlines()[1].startswith("  ") else 1
    backup = f"{config_path}.bak.garage.{time.strftime('%Y%m%d-%H%M%S')}"
    with open(backup, "w", encoding="utf-8") as f:
        f.write(raw)
    cfg["garage"]["ladder"] = clean
    cfg["garage"]["prices_status"] = "operator"
    tmp = f"{config_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, indent=indent, ensure_ascii=False)
                + ("\n" if raw.endswith("\n") else ""))
    os.replace(tmp, config_path)
    return {"ok": True, "applied": True, "ladder": clean,
            "total": round(sum(m["price"] for m in clean), 2), "backup": backup}
