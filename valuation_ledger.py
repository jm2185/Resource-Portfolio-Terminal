"""
Valuation Ledger — the validation flywheel's keystone (Phase 1 of docs/VALIDATION_FLYWHEEL_PLAN.md).

The calibration loop grades *decisions* (verdict + frozen ρ/φ + price); the valuations themselves —
intrinsic, the ladder, the REP floor, the band, the inputs they rested on — were never stamped
point-in-time, so they could never be graded. This module is that stamp: every name's full
valuation state, recorded append-only, input-attributed, regime-stamped. The replay harness
(``replay.py``) grades these records against subsequent reality; until they exist there is no
track record to grade.

Design (same discipline as ``living_memory.py``, deliberately a SEPARATE file):
  * **Append-only.** Records are never edited. A restatement is a new record (the cadence rules
    catch it as a ``material_change``). ``data/valuation_ledger.jsonl``.
  * **Separate from Living Memory.** Memory is the human/agent research stream and loads fully
    into RAM on query; machine-cadence snapshots would pollute its recall. Cross-link by id.
  * **Engine-sourced only (Goodhart guard).** ``snapshot_from_basket`` reads fixed engine paths
    (pillars/ladder/gate/ribbon) — free-form agent-supplied ``rho``/``legs`` keys never leak in,
    same rule as ``calibration.decision_from_rating``.
  * **Point-in-time inputs.** The swing inputs are copied BY VALUE from the research cache's
    provenance at stamp time, so a later cache restatement can never rewrite what a valuation
    rested on.
  * **Cadence, not firehose.** ``maybe_record`` writes on the UTC date roll (one guaranteed
    gradeable mark/day/name), on a material change (intrinsic/band/directive/gate/inputs
    fingerprint moved), or on an explicit decision/manual trigger — never every eval cycle.

Pure stdlib; no engine import. Unit-testable on a temp JSONL.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import date, datetime
from typing import Any, Optional

DEFAULT_PATH = "data/valuation_ledger.jsonl"
SCHEMA_VERSION = 1

#: why a record was written. ``seed`` = first-ever record for a name; ``daily`` = the UTC date-roll
#: mark; ``material_change`` = the fingerprint moved between daily marks; ``decision`` = a frozen
#: calibration decision joined to this snapshot; ``manual`` = operator/agent-requested stamp.
TRIGGERS: frozenset = frozenset({"seed", "daily", "material_change", "decision", "manual"})

#: snapshot fields folded into the material-change fingerprint. Intrinsic is rounded so price
#: noise inside the ribbon's precision doesn't masquerade as a material change.
_FP_INTRINSIC_DECIMALS = 3


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _gen_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]


def _num(x) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _sha1(text: str) -> str:
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:12]


def config_hash(cfg: dict) -> str:
    """Stable fingerprint of the effective config a valuation ran under (file defaults + confirmed
    overrides) — needed for honest counterfactual replay (Phase 2 Mode B)."""
    try:
        return _sha1(json.dumps(cfg or {}, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return "unhashable"


_GIT_SHA_CACHE: Optional[str] = None


def git_sha() -> Optional[str]:
    """Short git sha of the running code (cached; None outside a repo) — stamps which code
    produced a snapshot, so the golden-ledger regression can name drift."""
    global _GIT_SHA_CACHE
    if _GIT_SHA_CACHE is not None:
        return _GIT_SHA_CACHE or None
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5,
                             cwd=os.path.dirname(os.path.abspath(__file__)))
        _GIT_SHA_CACHE = out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        _GIT_SHA_CACHE = ""
    return _GIT_SHA_CACHE or None


def _age_days(as_of: Optional[str]) -> Optional[int]:
    if not as_of:
        return None
    try:
        d = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except (ValueError, TypeError):
        return None


def inputs_from_provenance(provenance: dict, fields: Optional[list] = None) -> dict:
    """Copy the swing inputs BY VALUE from a research-cache ``provenance(ticker)`` dict — the
    point-in-time spine. Each input keeps its value, as_of, confidence, a short hash of its source
    (full URLs stay in the cache), and its age at stamp time. ``fields`` limits which inputs are
    embedded; default = all sourced fields (the 4-name book's caches are small)."""
    out: dict = {}
    for field, entry in (provenance or {}).items():
        if fields is not None and field not in fields:
            continue
        if not isinstance(entry, dict):
            continue
        rec = {
            "value": entry.get("value"),
            "as_of": entry.get("as_of"),
            "confidence": entry.get("confidence"),
            "source_sha1": _sha1(entry.get("source") or ""),
            "age_days": _age_days(entry.get("as_of")),
        }
        if isinstance(rec["value"], dict):
            rec["value"] = dict(rec["value"])          # by-value copy, never a live reference
        out[field] = rec
    return out


def method_spread(legs: Optional[dict], weights: Optional[dict] = None) -> Optional[dict]:
    """Ensemble dispersion across the triangulation legs (Phase 5 ③): each leg (cost / market /
    income) is an independent valuation method; their disagreement is itself a signal. Returns
    ``{values, spread_pct, n_methods}`` over the legs that actually participate (positive value,
    non-zero weight), or None when fewer than two methods speak. spread_pct = (max−min)/median."""
    legs = legs or {}
    weights = weights or {}
    vals = {}
    for k, v in legs.items():
        fv = _num(v)
        if fv is None or fv <= 0:
            continue
        w = _num(weights.get(k))
        if weights and (w is None or w <= 0):
            continue                                   # a zero-weight leg isn't a live method
        vals[k] = fv
    if len(vals) < 2:
        return None
    ordered = sorted(vals.values())
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else \
        (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2.0
    spread = (ordered[-1] - ordered[0]) / median if median > 0 else None
    return {"values": {k: round(v, 4) for k, v in vals.items()},
            "spread_pct": round(spread * 100.0, 1) if spread is not None else None,
            "n_methods": len(vals)}


def snapshot_from_basket(basket: dict, *, inputs: Optional[dict] = None,
                         regime: Optional[dict] = None, legs: Optional[dict] = None,
                         rep_floor: Optional[dict] = None, config_hash: Optional[str] = None,
                         engine_git_sha: Optional[str] = None,
                         peer_set_hash: Optional[str] = None,
                         lens: Optional[str] = None, divergence_spread: Optional[dict] = None,
                         swing_variable: Optional[dict] = None) -> dict:
    """Build one snapshot from an ENGINE conviction basket (raw ``compute_asymmetry_rating`` output
    or the MCP ``_project_conviction_basket`` projection — both shapes tolerated).

    GOODHART GUARD: ρ/φ/ladder/gate are read from the engine's fixed paths (``pillars.V`` /
    ``asymmetry`` / ``ladder`` / ``gate``) ONLY. Free-form top-level ``rho``/``legs`` keys in the
    payload are ignored — an agent cannot move the measuring stick the replay harness grades
    against (same rule as ``calibration.decision_from_rating``; guarded by tests)."""
    basket = basket or {}
    pillars = basket.get("pillars") or {}
    Vp = pillars.get("V") or {}
    asym = basket.get("asymmetry") or {}               # MCP projection shape
    ladder = dict(basket.get("ladder") or {})
    gate = basket.get("gate") or {}
    ribbon = basket.get("confidence_ribbon") or {}
    price = _num(ladder.get("price"))
    intrinsic = _num(ladder.get("base"))               # the engine's central estimate leg
    snap = {
        "ticker": basket.get("ticker"),
        "archetype": basket.get("archetype"),
        "price": price,
        "intrinsic": intrinsic,
        "ladder": {k: _num(ladder.get(k)) for k in ("floor", "bear", "base", "bull")},
        "asymmetry": {
            "rho": _num(Vp.get("rho")) if Vp.get("rho") is not None else _num(asym.get("rho")),
            "phi": (_num(Vp.get("floor_coverage")) if Vp.get("floor_coverage") is not None
                    else _num(asym.get("floor_coverage"))),
        },
        "rating": _num(basket.get("rating")),
        "band": basket.get("band"),
        "directive": basket.get("directive"),
        "pillars": {k: _num((pillars.get(k) or {}).get("score", basket.get(k)))
                    for k in ("T", "Q", "V")},
        "gate": {"cap": _num(gate.get("cap")), "reason": gate.get("reason")},
        "ribbon": {k: ribbon.get(k) for k in ("plus_minus", "quality", "p10", "p50", "p90")
                   if ribbon.get(k) is not None},
        "regime": dict(regime) if isinstance(regime, dict) else None,
        "inputs": dict(inputs or {}),
    }
    if legs:
        snap["legs"] = {k: legs.get(k) for k in ("values", "weights", "confidence")
                        if legs.get(k) is not None}
        ms = method_spread(legs.get("values"), legs.get("weights"))
        if ms:
            snap["method_spread"] = ms
    if rep_floor:
        snap["rep_floor"] = dict(rep_floor)
    # Dual-sided (conventional-core) extension: which lens led, the cross-LENS divergence spread
    # (distinct from method_spread above, which is cross-METHOD within one lens), and the single
    # load-bearing swing variable — so the replay harness can grade conventional valuations too.
    if lens:
        snap["lens"] = lens
    if divergence_spread:
        snap["divergence_spread"] = {k: divergence_spread.get(k) for k in
                                     ("shape", "leader", "lead_lens", "spread_pct",
                                      "compounder_intrinsic", "deep_value_intrinsic")
                                     if divergence_spread.get(k) is not None}
    if swing_variable:
        snap["swing_variable"] = {k: swing_variable.get(k) for k in
                                  ("name", "value", "base_rate_name", "probability", "asserted", "segment")
                                  if swing_variable.get(k) is not None}
    if config_hash:
        snap["config_hash"] = config_hash
    if engine_git_sha:
        snap["engine_git_sha"] = engine_git_sha
    if peer_set_hash:
        snap["peer_set_hash"] = peer_set_hash
    return snap


def valuation_failed(snap: dict) -> bool:
    """A snapshot whose central estimate did not compute — intrinsic missing or EXACTLY 0.0. A real
    fair value is never exactly zero, so stamping such a row with a real band (SOLID / FAIR) records
    a valuation the engine did not make: the 80-phantom GROY zeros the 2026-07-02 reassessment flagged
    (`intrinsic=0.0` banded SOLID/FAIR, immutable). Guarded on write (auto-cadence never stamps one;
    an explicit write is flagged), excluded on grade."""
    iv = _num(snap.get("intrinsic"))
    return iv is None or iv == 0.0


def fingerprint(snap: dict) -> str:
    """Material-change fingerprint: intrinsic (rounded), band, directive, gate cap, and the input
    attribution (value + as_of per input). A restatement, a directive flip, a gate event, or an
    intrinsic move all change it; eval-cycle price jitter does not."""
    iv = _num(snap.get("intrinsic"))
    inputs_sig = {k: (str((v or {}).get("value"))[:64], (v or {}).get("as_of"))
                  for k, v in (snap.get("inputs") or {}).items()}
    basis = {
        "ticker": snap.get("ticker"),
        "intrinsic": round(iv, _FP_INTRINSIC_DECIMALS) if iv is not None else None,
        "band": snap.get("band"),
        "directive": snap.get("directive"),
        "gate_cap": ((snap.get("gate") or {}).get("cap")),
        "inputs": inputs_sig,
    }
    # Dual-sided extension (added ONLY when present, so resource fingerprints are byte-identical): a
    # lens shape flip (premium-franchise → mispricing-flag) or a swing-variable restatement is material.
    if snap.get("lens"):
        basis["lens"] = snap.get("lens")
    if snap.get("divergence_spread"):
        basis["shape"] = (snap.get("divergence_spread") or {}).get("shape")
    if snap.get("swing_variable"):
        basis["swing"] = str((snap.get("swing_variable") or {}).get("value"))[:64]
    return _sha1(json.dumps(basis, sort_keys=True, default=str))


class ValuationLedger:
    """Append-only point-in-time valuation store over a JSONL file (living_memory mechanics:
    O_APPEND + advisory flock, torn-line tolerance, mtime-invalidated read cache)."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._cache: Optional[list] = None
        self._mtime: Optional[float] = None

    # ------------------------------------------------------------------ write
    def record(self, snapshot: dict, *, trigger: str = "manual",
               ts: Optional[str] = None) -> dict:
        """Append one snapshot (assigning id/ts/schema_version/fingerprint) and return it.
        ``trigger`` must be in TRIGGERS; a snapshot without a ticker fails fast — bad data never
        silently enters the track record."""
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown ledger trigger {trigger!r}; expected one of {sorted(TRIGGERS)}")
        if not snapshot.get("ticker"):
            raise ValueError("snapshot has no ticker")
        rec = dict(snapshot)
        rec.update({"id": _gen_id(), "ts": ts or _now_iso(),
                    "schema_version": SCHEMA_VERSION, "trigger": trigger,
                    "fingerprint": fingerprint(snapshot)})
        if valuation_failed(snapshot):
            rec["valuation_failed"] = True              # honest flag: not a real valuation, band is not graded
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with open(self.path, "a", encoding="utf-8") as fh:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass                                    # non-POSIX: O_APPEND ordering only
            fh.write(line + "\n")
            fh.flush()
        self._cache, self._mtime = None, None           # see living_memory.write for why
        return rec

    def maybe_record(self, snapshot: dict, *, trigger: Optional[str] = None) -> Optional[dict]:
        """The cadence gate: write when (1) the name has no record yet (``seed``), (2) the first
        stamp after a UTC date roll (``daily``), (3) the fingerprint moved (``material_change``),
        or (4) an explicit ``decision``/``manual`` trigger. Otherwise return None — the ~10s eval
        loop must not flood the track record."""
        if trigger in ("decision", "manual", "seed"):
            return self.record(snapshot, trigger=trigger)
        if valuation_failed(snapshot):
            return None                                 # auto-cadence never stamps a failed valuation
        last = self.last_for(snapshot.get("ticker"))
        if last is None:
            return self.record(snapshot, trigger="seed")
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if str(last.get("ts") or "")[:10] < today:
            return self.record(snapshot, trigger="daily")
        if fingerprint(snapshot) != last.get("fingerprint"):
            return self.record(snapshot, trigger="material_change")
        return None

    # ------------------------------------------------------------------ read
    def all(self) -> list:
        """Every record, oldest-first. Cache-first; reloads only when the file changed on disk."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._cache, self._mtime = [], None
            return []
        if self._cache is not None and self._mtime == mtime:
            return self._cache
        out, skipped = [], 0
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        out.append(json.loads(ln))
                    except (ValueError, json.JSONDecodeError):
                        skipped += 1                    # tolerate a torn line, never crash
        except OSError:
            return self._cache or []
        self._cache, self._mtime = out, mtime
        self._skipped_lines = skipped
        return out

    def query(self, *, ticker: Optional[str] = None, since: Optional[str] = None,
              trigger: Optional[str] = None, limit: int = 50,
              newest_first: bool = True) -> list:
        rows = []
        for r in self.all():
            if ticker and str(r.get("ticker") or "").upper() != str(ticker).upper():
                continue
            if since and str(r.get("ts") or "") < str(since):
                continue
            if trigger and r.get("trigger") != trigger:
                continue
            rows.append(r)
        rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=newest_first)
        return rows[:limit] if limit else rows

    def last_for(self, ticker: Optional[str]) -> Optional[dict]:
        hits = self.query(ticker=ticker, limit=1, newest_first=True)
        return hits[0] if hits else None

    def get(self, record_id: str) -> Optional[dict]:
        for r in self.all():
            if r.get("id") == record_id:
                return r
        return None

    def stats(self) -> dict:
        """Ledger depth — records, names, span — so the operator sees the track record accruing.
        ``skipped_lines`` > 0 means torn lines were dropped on read (visible, never silent)."""
        rows = self.all()
        names: dict = {}
        for r in rows:
            k = r.get("ticker") or "_unknown"
            names[k] = names.get(k, 0) + 1
        ts = sorted(str(r.get("ts") or "") for r in rows if r.get("ts"))
        return {"records": len(rows), "by_ticker": names,
                "first_ts": ts[0] if ts else None, "last_ts": ts[-1] if ts else None,
                "path": self.path, "skipped_lines": getattr(self, "_skipped_lines", 0)}
