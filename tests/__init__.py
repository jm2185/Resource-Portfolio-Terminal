"""Test-package bootstrap: put the repo root (top-level modules) and mcp_server on sys.path so the
suite runs the same however it's invoked (`python -m unittest discover -s tests -t .`, or a single
`python -m unittest tests.test_x`). Pure path setup — no test logic here."""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "mcp_server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Isolate the audit trail: redirect every default-path LivingMemory to a temp file so running the suite
# (the full app instantiates real memory) never pollutes the tracked data/living_memory.jsonl. setdefault
# so an explicit override still wins. Read at LivingMemory construction, so this just needs to land first.
os.environ.setdefault("CEX_MEMORY_PATH", os.path.join(tempfile.gettempdir(), "cex_test_living_memory.jsonl"))
os.environ.setdefault("CEX_CONV_PATH", os.path.join(tempfile.gettempdir(), "cex_test_conversations.json"))
