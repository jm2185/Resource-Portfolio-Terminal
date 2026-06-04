"""
Engine-owned Financial Modeling Prep client — free-tier aware, hard-cached, budget-capped.

The free tier allows ~250 calls/day and only a handful of endpoints (profile / treasury-rates /
search; news, calendar and quote are paid). So this client is deliberately frugal:

* every call is cached to disk with a per-endpoint TTL (a repeat inside the TTL costs nothing);
* a daily budget guard refuses live calls past a cap (default 200, leaving headroom under 250)
  and serves stale cache instead — the cockpit can never burn the quota by accident;
* it is **on-demand only** — never wired into the engine's eval loop (that would exhaust the
  quota in minutes). Agents/cockpit pull it explicitly through the engine's /fmp/* routes.

Stdlib only, so it is unit-testable on its own and the engine stays the single hub. The API key
is read from FMP_API_KEY (or a gitignored .env) and is never logged or persisted to the cache.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://financialmodelingprep.com/stable"


def _load_key() -> str:
    key = os.environ.get("FMP_API_KEY", "").strip()
    if key:
        return key
    # fall back to a gitignored .env in the repo root (KEY=value lines)
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("FMP_API_KEY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


class FMPClient:
    """Frugal FMP reader. Methods return {data, cached, ...meta}; data is None on hard failure."""

    def __init__(self, key: str | None = None, cache_path: str | None = None, daily_budget: int = 200):
        self.key = key if key is not None else _load_key()
        self.daily_budget = int(os.environ.get("FMP_DAILY_BUDGET", daily_budget))
        self.cache_path = cache_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "fmp_cache.json")
        self._cache = self._load_cache()

    # ---- cache + budget persistence (one small JSON file) ------------------
    def _load_cache(self) -> dict:
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"_budget": {"date": "", "count": 0}}

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _budget(self) -> dict:
        b = self._cache.setdefault("_budget", {"date": "", "count": 0})
        if b.get("date") != self._today():          # new UTC day -> reset the counter
            b["date"], b["count"] = self._today(), 0
        return b

    def calls_remaining(self) -> int:
        return max(0, self.daily_budget - self._budget()["count"])

    # ---- the one guarded fetch --------------------------------------------
    def _get(self, path: str, params: dict, ttl: int) -> dict:
        if not self.key:
            return {"data": None, "cached": False, "error": "no FMP_API_KEY set (.env / environment)"}
        ckey = path + "?" + urllib.parse.urlencode(sorted(params.items()))
        entry = self._cache.get(ckey)
        now = time.time()
        if entry and (now - entry.get("ts", 0)) < ttl:
            return {"data": entry["data"], "cached": True, "age_s": int(now - entry["ts"])}
        budget = self._budget()
        if budget["count"] >= self.daily_budget:     # quota guard: serve stale, never overspend
            return {"data": entry["data"] if entry else None, "cached": bool(entry),
                    "budget_exhausted": True, "calls_remaining": 0}
        url = f"{BASE}/{path}?{urllib.parse.urlencode({**params, 'apikey': self.key})}"
        try:
            with urllib.request.urlopen(url, timeout=8) as r:      # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            return {"data": entry["data"] if entry else None, "cached": bool(entry), "error": str(exc)[:120]}
        if isinstance(data, dict) and ("Error Message" in data or "Restricted" in str(data)[:40] or "Premium" in str(data)[:40]):
            return {"data": None, "cached": False, "error": str(data)[:140], "paid_endpoint": True}
        budget["count"] += 1
        self._cache[ckey] = {"ts": now, "data": data}
        self._save_cache()
        return {"data": data, "cached": False, "calls_remaining": self.calls_remaining()}

    # ---- the free-tier surface we actually use ----------------------------
    def profile(self, symbol: str) -> dict:
        """Fundamentals snapshot: price, market cap, beta, 52-wk range, volume, sector, exchange."""
        r = self._get("profile", {"symbol": symbol.upper()}, ttl=3600)            # 1h
        d = r.get("data")
        if isinstance(d, list) and d:
            r["data"] = d[0]
        return r

    def treasury(self) -> dict:
        """The latest US Treasury curve (1mo … 30yr). One call covers every tenor; cached 6h."""
        to = datetime.now(timezone.utc).date()
        frm = to - timedelta(days=7)
        r = self._get("treasury-rates", {"from": frm.isoformat(), "to": to.isoformat()}, ttl=6 * 3600)
        d = r.get("data")
        if isinstance(d, list) and d:
            r["data"] = d[0]                          # most recent day
        return r

    def search(self, query: str) -> dict:
        """Resolve a name/ticker to FMP's symbol + exchange. Cached 24h."""
        return self._get("search-symbol", {"query": query}, ttl=24 * 3600)
