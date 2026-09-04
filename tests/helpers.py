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
* the ``live_*`` book accessors — ONE place that answers "what does the book hold right now",
  so a test whose subject really is the shipped config derives membership instead of spelling
  it out. Holdings change (URC.TO removed 2026-07-31, GMX.TO exited 2026-08-13) and every
  literal ticker set left in an assertion rots silently into a red suite. The rule this
  encodes: **a test may name a specific ticker only when that ticker IS the subject**; if it
  just needs "the book", or "a ballast", or "some holdco", it takes it from here or builds a
  synthetic fixture.
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import types

import engine

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "v5_config.json")


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


# --------------------------------------------------------------------------- live book accessors
def live_config() -> dict:
    """The shipped ``v5_config.json``, parsed fresh (tests mutate their copies)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def live_barbell(cfg=None) -> dict:
    """``barbell_weights`` with the ``_comment`` key stripped — the book's structural membership."""
    bw = (cfg or live_config()).get("barbell_weights") or {}
    return {k: v for k, v in bw.items() if not str(k).startswith("_")}


def live_spear(cfg=None) -> str:
    """The ticker filling the ``silver-spear`` slot (falls back to the heaviest barbell name)."""
    cfg = cfg or live_config()
    pm = cfg.get("portfolio_metadata") or {}
    for tk, meta in pm.items():
        if isinstance(meta, dict) and meta.get("thesis_slot") == "silver-spear":
            return tk
    bw = live_barbell(cfg)
    return max(bw, key=bw.get) if bw else ""


def live_ballasts(cfg=None) -> set:
    """Barbell names minus the spear — what the sizer averages correlations over."""
    cfg = cfg or live_config()
    return set(live_barbell(cfg)) - {live_spear(cfg)}


def live_resource_names(cfg=None) -> set:
    """Resource-lane ``portfolio_metadata`` names — the set the resource router must cover.
    Conventional-lane entries are priced by ``dual_sided`` and are deliberately NOT routed."""
    import dual_sided
    cfg = cfg or live_config()
    pm = cfg.get("portfolio_metadata") or {}
    return {k for k in pm if not str(k).startswith("_") and not dual_sided.is_conventional(k, pm)}
