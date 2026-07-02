"""Shared test helpers (plain unittest — no pytest fixtures, so the CI
``python -m unittest discover -s tests -p 'test_*.py' -t .`` run keeps working).

Two idioms that were copy-pasted across the engine-wiring suites live here once:

* ``TempMemoryMixin`` — a setUp/tearDown pair that points ``CEX_MEMORY_PATH`` at a fresh
  temp ``.jsonl`` so every ``LivingMemory()`` a test fires writes to an isolated file,
  restoring the prior env (and unlinking the temp file) afterwards.
* ``make_engine_stub`` — the lightweight ``types.SimpleNamespace`` stand-in for a live
  ``engine.CommodityExMonitor`` (no network, no boot): the standard attributes
  (``state_cache`` / ``config`` / ``terminal_state`` / ``_agent_seq`` / ``_lm``) plus the
  named engine methods bound onto the stub via ``types.MethodType`` (staticmethods are
  attached unbound, as plain functions).
"""
from __future__ import annotations

import inspect
import os
import tempfile
import types

import engine


class TempMemoryMixin:
    """Mix into a ``unittest.TestCase`` (before it in the MRO) to run every test against an
    isolated temp LivingMemory file. Subclasses that define their own setUp/tearDown must
    call ``super().setUp()`` / ``super().tearDown()``."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self._tmp.close()
        self._prev_mem = os.environ.get("CEX_MEMORY_PATH")
        os.environ["CEX_MEMORY_PATH"] = self._tmp.name

    def tearDown(self):
        if self._prev_mem is None:
            os.environ.pop("CEX_MEMORY_PATH", None)
        else:
            os.environ["CEX_MEMORY_PATH"] = self._prev_mem
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass


def make_engine_stub(*method_names, config=None, state_cache=None, mri=41.0, **attrs):
    """A no-boot ``CommodityExMonitor`` stand-in carrying the standard stub attributes,
    with each named engine method bound to it (``types.MethodType``; staticmethods are
    attached as plain functions). Extra keyword attrs are set verbatim on the stub."""
    s = types.SimpleNamespace()
    s.state_cache = {} if state_cache is None else state_cache
    s.config = {} if config is None else config
    s.terminal_state = {"mri": mri, "posture": {"code": "balanced"}, "agent_annotations": {}}
    s._agent_seq = 0
    s._lm = None
    for k, v in attrs.items():
        setattr(s, k, v)
    cls = engine.CommodityExMonitor
    for nm in method_names:
        if isinstance(inspect.getattr_static(cls, nm), staticmethod):
            setattr(s, nm, getattr(cls, nm))          # unbound: no self
        else:
            setattr(s, nm, types.MethodType(getattr(cls, nm), s))
    return s
