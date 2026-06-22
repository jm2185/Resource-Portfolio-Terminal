"""Pytest path bootstrap (mirrors tests/__init__.py for the unittest runner): repo root + mcp_server
on sys.path so `pytest tests/` resolves the top-level modules. Harmless no-op under unittest."""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, os.path.join(_ROOT, "mcp_server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Mirror tests/__init__: redirect default-path LivingMemory to a temp file so a pytest run never
# pollutes the tracked data/living_memory.jsonl audit trail.
os.environ.setdefault("CEX_MEMORY_PATH", os.path.join(tempfile.gettempdir(), "cex_test_living_memory.jsonl"))
os.environ.setdefault("CEX_CONV_PATH", os.path.join(tempfile.gettempdir(), "cex_test_conversations.json"))
