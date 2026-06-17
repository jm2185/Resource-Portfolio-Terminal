"""
Dynamic configuration overlay — engine-owned (orchestrated by engine.py).

`v5_config.json` stays the static **defaults**; this SQLite-backed manager holds **overrides**
on top, so the engine serves ``effective = deep_merge(defaults, overrides)`` and reloads it each
loop (hot-reload). The goal is to *reduce* hardcoding over time: tunables move into the overlay,
edited from the cockpit, never by adding more constants to the file.

Guardrails baked in:
  * **Allowlist** — only the dotted paths below may be overridden (a typo or an agent can't
    corrupt structural config), each range/type-validated against the default.
  * **propose -> confirm** — agents propose changes *with reasoning*; nothing applies until a
    human confirms (the engine exposes both queues; the MCP tools are thin callers).
  * **audit** — every set/reset/confirm is logged (who/when/why) — the seed of the decision journal.

Pure stdlib (sqlite3 + json), so it is unit-testable on its own.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from copy import deepcopy

DEFAULT_DB = "data/dynamic_config.sqlite"

# Structural book-weights override (a validated VECTOR, distinct from the scalar ALLOWLIST). The
# 60% AGA.V spear ceiling is a hard invariant (mirrors calculate_sizing) — it can only TIGHTEN here.
BARBELL_KEY = "barbell_weights"
SPEAR_CEILING = 0.60


class ConfigError(ValueError):
    """Raised for a non-allowlisted key, a validation failure, or a bad confirm id."""


# Dotted path -> validator. Curated first slice: safe scalars (type inferred; range-checked).
ALLOWLIST: dict[str, dict] = {
    "conservatism_scalar":                                {"type": float, "min": 0.5,  "max": 1.5},
    "discovery_multiple":                                 {"type": float, "min": 0.0,  "max": 1.0},
    "rov_default":                                        {"type": float, "min": 0.5,  "max": 3.0},
    "friction_drag":                                      {"type": float, "min": 0.0,  "max": 0.10},
    "directive_thresholds.spear_upside_high_conviction":  {"type": float, "min": 0.1,  "max": 3.0},
    "directive_thresholds.spear_arbitrage_pct":           {"type": float, "min": 0.0,  "max": 200.0},
    "forensic_thresholds.max_burn_acceleration_pct":      {"type": float, "min": 0.0,  "max": 1.0},
    "forensic_thresholds.max_burn_acceleration_ev_pct":   {"type": float, "min": 0.0,  "max": 0.5},
    "conviction_mode.rho_half":                           {"type": float, "min": 0.1,  "max": 10.0},
    "conviction_mode.delta_floor":                        {"type": float, "min": 0.0,  "max": 1.0},
    "conviction_mode.v_payoff_weight":                    {"type": float, "min": 0.0,  "max": 1.0},
    # --- Forge layer (Sentinel M3 liquidity-runway gate + swap M6 hurdle). The 60% ceiling is NOT
    #     here and is never loosened; liquidity_runway is an ADDITIONAL survival gate. ---
    "forge.sentinel.liq_part":                            {"type": float, "min": 0.05, "max": 0.50},
    "forge.sentinel.liq_k":                               {"type": float, "min": 0.0,  "max": 3.0},
    "forge.sentinel.liq_free":                            {"type": float, "min": 0.0,  "max": 0.20},
    "forge.sentinel.liq_runway_max":                      {"type": float, "min": 1.0,  "max": 30.0},
    "forge.sentinel.integrity_floor":                     {"type": float, "min": 0.0,  "max": 1.0},
    "forge.sentinel.window_open_threshold":               {"type": float, "min": 0.0,  "max": 1.0},
    "forge.sentinel.deathspiral_runway_months":           {"type": float, "min": 0.0,  "max": 24.0},
    "forge.swap.hurdle":                                  {"type": float, "min": 0.0,  "max": 2.0},
    "forge.swap.lock_window":                             {"type": float, "min": 0.0,  "max": 90.0},
}


def _get_path(d: dict, path: str):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set_path(d: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


class DynamicConfigManager:
    def __init__(self, defaults: dict, db_path: str = DEFAULT_DB) -> None:
        self._defaults = defaults or {}
        self._db_path = db_path
        self._lock = threading.Lock()
        self._version = 0
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS overrides(
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL, source TEXT);
                CREATE TABLE IF NOT EXISTS pending(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, value TEXT, reason TEXT,
                    proposed_by TEXT, created_at REAL, status TEXT DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS scenarios(
                    name TEXT PRIMARY KEY, overrides TEXT NOT NULL, created_at REAL, source TEXT);
                CREATE TABLE IF NOT EXISTS audit(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, action TEXT, key TEXT,
                    old_value TEXT, new_value TEXT, source TEXT, reason TEXT);
                """
            )

    @property
    def version(self) -> int:
        return self._version

    def set_defaults(self, defaults: dict) -> None:
        """Refresh the in-memory defaults baseline (the static v5_config layer that ``effective()``
        deep-merges the SQLite overrides onto). The orchestrator calls this once per eval cycle with
        a fresh read of v5_config.json so that BOTH direct file edits (any key — most config is NOT
        in the allowlist and can only change via the file) AND confirmed overrides reach the engines.
        Cheap (a dict swap); the deepcopy happens in ``effective()``."""
        if isinstance(defaults, dict) and defaults:
            with self._lock:
                self._defaults = defaults

    # ---- validation -------------------------------------------------------
    def _validate(self, key: str, value):
        if key == BARBELL_KEY:                            # a validated vector, not a scalar tunable
            return self._validate_barbell(value)
        spec = ALLOWLIST.get(key)
        if spec is None:
            raise ConfigError(f"{key!r} is not in the editable allowlist")
        if _get_path(self._defaults, key) is None:
            raise ConfigError(f"{key!r} has no default to validate against")
        try:
            value = spec["type"](value)
        except (TypeError, ValueError):
            raise ConfigError(f"{key} must be {spec['type'].__name__}")
        if "min" in spec and value < spec["min"]:
            raise ConfigError(f"{key}={value} below min {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ConfigError(f"{key}={value} above max {spec['max']}")
        return value

    def _book_tickers(self) -> set:
        bw = self._defaults.get(BARBELL_KEY, {}) or {}
        return {k for k in bw if k != "_comment"}

    def _validate_barbell(self, weights) -> dict:
        """Validate a book-weights vector: known tickers only, each in [0,1], sums to 1.0, and AGA.V
        within the spear ceiling. Preserves the defaults' ``_comment`` so the audit trail stays intact."""
        if _get_path(self._defaults, BARBELL_KEY) is None:
            raise ConfigError("no barbell_weights default to validate against")
        if not isinstance(weights, dict) or not any(k != "_comment" for k in weights):
            raise ConfigError("barbell_weights must be a non-empty {ticker: weight} map")
        known = self._book_tickers()
        out = {}
        for k, v in weights.items():
            if k == "_comment":
                continue
            if known and k not in known:
                raise ConfigError(f"{k!r} is not a book holding (known: {sorted(known)})")
            try:
                w = float(v)
            except (TypeError, ValueError):
                raise ConfigError(f"weight for {k!r} must be a number")
            if not (0.0 <= w <= 1.0):
                raise ConfigError(f"weight for {k!r} out of [0,1]: {w}")
            out[k] = round(w, 6)
        s = sum(out.values())
        if abs(s - 1.0) > 1e-3:
            raise ConfigError(f"barbell_weights must sum to 1.0 (got {s:.4f})")
        if out.get("AGA.V", 0.0) > SPEAR_CEILING + 1e-9:
            raise ConfigError(f"AGA.V {out['AGA.V']:.2f} exceeds the {SPEAR_CEILING:.0%} spear ceiling (invariant)")
        cmt = (self._defaults.get(BARBELL_KEY, {}) or {}).get("_comment")
        if cmt:
            out["_comment"] = cmt
        return out

    def _redistribute(self, weights: dict, add: float) -> dict:
        """Place ``add`` weight across survivors pro-rata to current weight, capping AGA.V at the
        spear ceiling and spilling the excess to the rest; renormalize. Pure + deterministic."""
        w = {k: float(v) for k, v in weights.items() if k != "_comment"}

        def cap(k):
            return SPEAR_CEILING if k == "AGA.V" else 1.0

        for _ in range(12):
            if add <= 1e-9:
                break
            elig = [k for k in w if cap(k) - w[k] > 1e-9]
            if not elig:
                break
            tot = sum(w[k] for k in elig)
            moved = 0.0
            for k in elig:
                share = add * (w[k] / tot) if tot > 0 else add / len(elig)
                give = min(share, cap(k) - w[k])
                w[k] += give
                moved += give
            add -= moved
            if moved <= 1e-12:
                break
        s = sum(w.values()) or 1.0
        return {k: round(v / s, 6) for k, v in w.items()}

    # ---- effective config (defaults + overrides) --------------------------
    def overrides(self) -> dict:
        with self._conn() as c:
            return {r["key"]: json.loads(r["value"])
                    for r in c.execute("SELECT key, value FROM overrides")}

    def effective(self) -> dict:
        eff = deepcopy(self._defaults)
        for key, value in self.overrides().items():
            _set_path(eff, key, value)
        return eff

    def list_params(self) -> list[dict]:
        ov = self.overrides()
        rows = []
        for key, spec in ALLOWLIST.items():
            default = _get_path(self._defaults, key)
            rows.append({"key": key, "default": default, "value": ov.get(key, default),
                         "overridden": key in ov, "type": spec["type"].__name__,
                         "min": spec.get("min"), "max": spec.get("max")})
        return rows

    def _audit(self, c, action, key, old, new, source, reason):
        c.execute("INSERT INTO audit(ts,action,key,old_value,new_value,source,reason) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (time.time(), action, key, json.dumps(old), json.dumps(new), source, reason))

    # ---- direct set / reset (gated by the caller; logged) -----------------
    def set_param(self, key: str, value, source: str = "cockpit", reason: str | None = None) -> dict:
        value = self._validate(key, value)
        old = _get_path(self.effective(), key)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO overrides(key,value,updated_at,source) VALUES(?,?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                      "updated_at=excluded.updated_at, source=excluded.source",
                      (key, json.dumps(value), time.time(), source))
            self._audit(c, "set", key, old, value, source, reason)
            self._version += 1
        return {"key": key, "value": value, "version": self._version}

    def reset_param(self, key: str, source: str = "cockpit") -> dict:
        old = _get_path(self.effective(), key)
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM overrides WHERE key=?", (key,))
            self._audit(c, "reset", key, old, _get_path(self._defaults, key), source, None)
            self._version += 1
        return {"key": key, "reset_to_default": _get_path(self._defaults, key)}

    def cut_holding(self, ticker: str, source: str = "cockpit", reason: str | None = None) -> dict:
        """Cut a book holding to 0% and redistribute its weight across the survivors (AGA.V capped at
        the spear ceiling), applied via the SAME ``barbell_weights`` overlay the engine reads. (Use
        ``set_param('barbell_weights', {...})`` to set explicit weights instead of auto-redistribute.)"""
        cur = _get_path(self.effective(), BARBELL_KEY) or {}
        tk = str(ticker).strip().upper()
        live = {k: float(v) for k, v in cur.items() if k != "_comment"}
        if tk not in live:
            raise ConfigError(f"{tk!r} is not in barbell_weights (book: {sorted(live)})")
        if len(live) <= 1:
            raise ConfigError("cannot cut the only holding")
        cut_w = live.pop(tk)
        new = self._redistribute(live, cut_w)
        return self.set_param(BARBELL_KEY, new, source=source,
                              reason=reason or f"cut {tk} ({cut_w:.0%}); redistributed pro-rata")

    # ---- propose / confirm (agents propose; humans confirm) ---------------
    def propose(self, key: str, value, reason: str, proposed_by: str = "agent") -> dict:
        if not reason:
            raise ConfigError("a reason is required to propose a change")
        value = self._validate(key, value)          # fail fast on bad proposals
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO pending(key,value,reason,proposed_by,created_at) "
                            "VALUES(?,?,?,?,?)",
                            (key, json.dumps(value), reason, proposed_by, time.time()))
            pid = cur.lastrowid
        return {"id": pid, "key": key, "value": value, "reason": reason, "status": "pending"}

    def pending(self) -> list[dict]:
        with self._conn() as c:
            return [{**dict(r), "value": json.loads(r["value"])}
                    for r in c.execute("SELECT * FROM pending WHERE status='pending' ORDER BY id")]

    def confirm(self, pid: int, source: str = "cockpit") -> dict:
        with self._conn() as c:
            row = c.execute("SELECT * FROM pending WHERE id=? AND status='pending'", (pid,)).fetchone()
        if not row:
            raise ConfigError(f"no pending change #{pid}")
        res = self.set_param(row["key"], json.loads(row["value"]), source=source,
                             reason=f"confirmed #{pid}: {row['reason']}")
        with self._lock, self._conn() as c:
            c.execute("UPDATE pending SET status='applied' WHERE id=?", (pid,))
        return {"applied": pid, **res}

    def reject(self, pid: int) -> dict:
        with self._lock, self._conn() as c:
            c.execute("UPDATE pending SET status='rejected' WHERE id=?", (pid,))
        return {"rejected": pid}

    # ---- named what-if scenarios ------------------------------------------
    def save_scenario(self, name: str, overrides: dict, source: str = "cockpit") -> dict:
        if not name:
            raise ConfigError("scenario name required")
        if not isinstance(overrides, dict) or not overrides:
            raise ConfigError("a non-empty overrides dict is required")
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO scenarios(name,overrides,created_at,source) VALUES(?,?,?,?) "
                      "ON CONFLICT(name) DO UPDATE SET overrides=excluded.overrides, "
                      "created_at=excluded.created_at",
                      (name, json.dumps(overrides), time.time(), source))
        return {"name": name, "overrides": overrides}

    def get_scenario(self, name: str):
        with self._conn() as c:
            row = c.execute("SELECT overrides FROM scenarios WHERE name=?", (name,)).fetchone()
        return json.loads(row["overrides"]) if row else None

    def list_scenarios(self) -> list[dict]:
        with self._conn() as c:
            return [{"name": r["name"], "overrides": json.loads(r["overrides"])}
                    for r in c.execute("SELECT name, overrides FROM scenarios ORDER BY name")]
