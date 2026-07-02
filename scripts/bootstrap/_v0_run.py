"""V0 runner — prime the live data caches (real Yahoo/FRED fetches via the engine's own workers),
then run one real eval cycle and persist a dated terminal_state fixture with per-feed freshness.
A validation tool, not part of the package."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))  # repo root (script lives in scripts/bootstrap/)
import asyncio
import datetime
import json
import time
import traceback

import engine


def _default(o):
    try:
        import numpy as np
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    return str(o)


async def main():
    t0 = time.time()
    mon = engine.CommodityExMonitor()
    # Drive the real data workers (live Yahoo bulk download + FRED macro). These are the same
    # coroutines start_background_tasks() supervises; we run them directly and cancel once primed.
    workers = {}
    for name in ("_prices_worker", "_macro_worker", "_cftc_worker"):
        fn = getattr(mon, name, None)
        if fn:
            workers[name] = asyncio.create_task(fn())
    print(f"started workers: {list(workers)}; waiting for a live price fetch…")

    # Wait until the prices cache is populated AND not the bare fallback (SI=F seed = 74.8).
    primed = False
    for _ in range(75):                       # up to ~150s
        await asyncio.sleep(2)
        pc = mon.state_cache.get("prices") or {}
        if mon.state_cache.get("prices_ts") and pc:
            si = pc.get("SI=F")
            primed = True
            print(f"  prices cache filled: SI=F={si} (seed would be 74.8), n={len(pc)}")
            break
    await asyncio.sleep(6)                     # let macro/real-yield settle one pass

    err = None
    try:
        await asyncio.wait_for(mon.evaluate_master_architecture(force_macro=True), timeout=180)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    for t in workers.values():
        t.cancel()
    elapsed = round(time.time() - t0, 1)

    ts = dict(mon.terminal_state)
    p_blocks = [k for k in ("rates_dashboard", "productivity_monitor", "oil_supply", "sentinel_board",
                            "scenario_engine", "conditionals", "thesis_monitors", "macro_tape",
                            "posture", "treasury_curve", "metrics", "conviction_mode") if k in ts]
    stamp = datetime.date.today().isoformat()
    fixture = {"_meta": {"run_utc": datetime.datetime.utcnow().isoformat() + "Z", "fixture_date": stamp,
                         "elapsed_s": elapsed, "primed_live": primed, "eval_error": err,
                         "present_blocks": p_blocks, "all_keys": sorted(ts.keys())},
               "terminal_state": ts}
    out = f"terminal_state_{stamp}.json"
    with open(out, "w") as f:
        json.dump(fixture, f, default=_default, indent=2)
    print(f"\n=== wrote {out} in {elapsed}s (primed={primed}, err={err}) ===")
    m = ts.get("metrics") or {}
    for k in ("SI=F", "Spot_Ag", "WTI", "DXY", "10Y", "30Y", "VIX"):
        if k in m:
            v = m[k]
            print(f"  metric {k}: {v.get('value') if isinstance(v, dict) else v}")


if __name__ == "__main__":
    asyncio.run(main())
