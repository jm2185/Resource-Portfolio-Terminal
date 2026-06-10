#!/usr/bin/env python3
"""cex_optape.py — POST an operator shell command onto the cockpit DESK TAPE (Forge nervous system #2).

Wired (opt-in, ``CEX_OPERATOR_TAPE=1``) into the cockpit's OPERATOR pane via a shell precmd hook
(``scripts/cex-operator-hook.sh``), so the commands you run in the .venv (git · pip · ingestion ·
python) flow into the dashboard's DESK TAPE as **you**, next to agent work and state events. The
dashboard frames ``agent="operator"`` op-kind events as "you" in teal.

Best-effort and silent — it backgrounds, times out fast, and never blocks or breaks the prompt.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

# commands we never want echoed onto a shared tape (don't leak secrets into the bus / memory)
_REDACT = ("api_key", "apikey", "token", "secret", "password", "passwd", "credential")
_EDITORS = {"vi", "vim", "nano", "emacs", "code", "sed", "tee"}


def classify(cmd: str) -> str:
    head = (cmd.split() or [""])[0]
    if head == "git":
        return "git"
    if head in _EDITORS or ">" in cmd:
        return "edited"
    return "ran"


def main() -> None:
    cmd = " ".join(sys.argv[1:]).strip()
    if not cmd:
        return
    low = cmd.lower()
    if cmd.startswith(("__cex", "cexlog")) or any(s in low for s in _REDACT):
        return
    url = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000").rstrip("/") + "/agent/activity"
    payload = {"agent": "operator", "kind": classify(cmd), "summary": cmd[:140]}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=1.0)  # noqa: S310
    except Exception:
        pass


if __name__ == "__main__":
    main()
