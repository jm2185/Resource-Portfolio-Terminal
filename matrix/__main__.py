"""
CommodityEx matrix display node — CLI entry point.  ``python -m matrix [options]``

  python -m matrix --host 192.168.250.32 --claim --dry-run   # show the device-claim patch (no write)
  python -m matrix --host 192.168.250.32 --claim             # claim: our anim owns the panel
  python -m matrix --host 192.168.250.32 --once              # render+push one frame (smoke test)
  python -m matrix --host 192.168.250.32                     # daemon: host-driven rotation
  python -m matrix --host 192.168.250.32 --self-loop         # daemon: device-autonomous rotation
  python -m matrix --host 192.168.250.32 --focus-probe       # find which /api/data field the button toggles

Host defaults to $CEX_MATRIX_HOST (else the configured mDNS name); engine to $CEX_ENGINE_*. cockpit.sh
launches this as a background daemon when CEX_MATRIX_HOST is set.

Physical button: it maps to Focus/Pomodoro. To repurpose it to PIN the current screen (no custom
firmware), run --focus-probe to learn which /api/data field a press toggles, then set
$CEX_MATRIX_FOCUS_KEY (or pass --focus-key) to that field — the daemon then holds the view while pressed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import config as cfg


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m matrix",
                                description="Render CommodityEx engine state to the LED panel.")
    p.add_argument("--host", default=os.environ.get("CEX_MATRIX_HOST") or cfg.DEVICE_HOST,
                   help="panel host/IP, e.g. 192.168.250.32 (default: $CEX_MATRIX_HOST)")
    p.add_argument("--engine-url", default=cfg.ENGINE_URL, help="engine base URL")
    p.add_argument("--self-loop", action="store_true",
                   help="device-autonomous rotation (one looping anim; resilient when host is off)")
    p.add_argument("--poll", type=float, default=None, help="poll interval seconds")
    p.add_argument("--cycle", type=float, default=None,
                   help="seconds per board/detail screen (ambient dwells longer; default 15)")
    p.add_argument("--once", action="store_true", help="single tick/push then exit (smoke test)")
    p.add_argument("--claim", action="store_true",
                   help="apply the CommodityEx device profile (dGif on, native off) then exit")
    p.add_argument("--dry-run", action="store_true", help="with --claim: print the patch, do not write")
    p.add_argument("--focus-probe", action="store_true",
                   help="detect which /api/data field the physical button toggles, then exit")
    p.add_argument("--focus-key", default=None,
                   help="the /api/data field the button toggles (sets $CEX_MATRIX_FOCUS_KEY); button PINS the view")
    p.add_argument("-v", "--verbose", action="store_true", help="info logging")
    return p


def _focus_probe(host: str, watch_s: float = 25.0) -> int:
    """Find which /api/data field the physical button toggles: take a 2-sample baseline (to ignore
    auto-changing fields like clocks/sensors), then watch for the one field a button press flips."""
    import time
    from . import device

    def snap():
        try:
            return device.get_data(host) or {}
        except Exception as e:  # noqa: BLE001
            print(f"  read failed: {e}")
            return None

    b1 = snap()
    if b1 is None:
        return 1
    time.sleep(1.5)
    base = snap() or b1
    noisy = {k for k in set(b1) | set(base) if b1.get(k) != base.get(k)}   # auto-changing -> ignore
    if noisy:
        print(f"(ignoring auto-changing fields: {sorted(noisy)})")
    print(f"Baseline: {len(base)} fields. Press the device button now — watching {watch_s:.0f}s...")
    deadline = time.time() + watch_s
    while time.time() < deadline:
        time.sleep(1.0)
        now = snap()
        if now is None:
            continue
        changed = {k for k in set(base) | set(now) if k not in noisy and base.get(k) != now.get(k)}
        if changed:
            for k in sorted(changed):
                print(f"  button toggles {k!r}: {base.get(k)!r} -> {now.get(k)!r}")
            best = sorted(changed)[0]
            print(f"\nWire it:  export CEX_MATRIX_FOCUS_KEY={best}   (or --focus-key {best})")
            print("Then the button PINS the current screen (press again to resume rotation).")
            return 0
    print("No /api/data field changed on press — this firmware doesn't expose the button state.")
    print("Repurposing the physical button will need the Tier-C custom firmware.")
    return 2


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.claim:
        from . import profile
        print(json.dumps(profile.claim_device(args.host, confirm=not args.dry_run), indent=2, default=str))
        return 0

    if args.focus_probe:
        return _focus_probe(args.host)

    if args.focus_key:
        os.environ["CEX_MATRIX_FOCUS_KEY"] = args.focus_key   # picked up by the orchestrator's focus hook

    from .orchestrator import MatrixOrchestrator
    orch = MatrixOrchestrator(host=args.host, engine_url=args.engine_url, cycle_interval=args.cycle)
    if args.once:
        print(json.dumps(orch.push_loop() if args.self_loop else orch.tick(), indent=2, default=str))
        return 0
    orch.run(poll_interval=args.poll, self_loop=args.self_loop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
