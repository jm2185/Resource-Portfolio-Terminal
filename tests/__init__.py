"""Test-package bootstrap: put the repo root (top-level modules) and mcp_server on sys.path so the
suite runs the same however it's invoked (`python -m unittest discover -s tests -t .`, or a single
`python -m unittest tests.test_x`). Pure path setup — no test logic here."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "mcp_server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
