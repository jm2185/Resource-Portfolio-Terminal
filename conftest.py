"""Pytest path bootstrap (mirrors tests/__init__.py for the unittest runner): repo root + mcp_server
on sys.path so `pytest tests/` resolves the top-level modules. Harmless no-op under unittest."""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "mcp_server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
