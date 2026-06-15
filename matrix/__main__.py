"""
CommodityEx matrix display node — CLI entry point.  ``python -m matrix [options]``

  python -m matrix --host 192.168.250.32 --claim --dry-run   # show the device-claim patch (no write)
  python -m matrix --host 192.168.250.32 --claim             # claim: our anim owns the panel
  python -m matrix --host 192.168.250.32 --once              # render+push one frame (smoke test)
  python -m matrix --host 192.168.250.32                     # daemon: host-driven rotation
  python -m matrix --host 192.168.250.32 --self-loop         # daemon: device-autonomous rotation

Host defaults to $CEX_MATRIX_HOST (else the configured mDNS name); engine to $CEX_ENGINE_*. cockpit.sh
launches this as a background daemon when CEX_MATRIX_HOST is set.
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
    p.add_argument("--once", action="store_true", help="single tick/push then exit (smoke test)")
    p.add_argument("--claim", action="store_true",
                   help="apply the CommodityEx device profile (dGif on, native off) then exit")
    p.add_argument("--dry-run", action="store_true", help="with --claim: print the patch, do not write")
    p.add_argument("-v", "--verbose", action="store_true", help="info logging")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.claim:
        from . import profile
        print(json.dumps(profile.claim_device(args.host, confirm=not args.dry_run), indent=2, default=str))
        return 0

    from .orchestrator import MatrixOrchestrator
    orch = MatrixOrchestrator(host=args.host, engine_url=args.engine_url)
    if args.once:
        print(json.dumps(orch.push_loop() if args.self_loop else orch.tick(), indent=2, default=str))
        return 0
    orch.run(poll_interval=args.poll, self_loop=args.self_loop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
