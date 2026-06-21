"""Lightweight observability for SWALLOWED exceptions — lose the blindness, keep never-crash.

The engine guards its data/compute paths with ``except Exception: pass`` so a flaky feed never crashes
the desk. The cost the evaluation flagged: a quietly-broken module looks identical to a missing feed —
the desk is honest about DATA (stale flags, coverage gaps) but blind to CODE faults. ``swallow()``
closes that gap: call it from an ``except`` block and the fault is LOGGED (with traceback) whenever
``CEX_DEBUG`` is set, while the default stays silent and non-crashing. Opt-in, ~zero overhead when off,
and it never raises — so adopting it can't regress the never-crash property it's protecting.

Usage — turn ``except Exception:\\n    pass`` into::

    except Exception:
        obs.swallow("prices_worker.aga")   # silent unless CEX_DEBUG; then logged with the traceback

Pure stdlib, fully unit-testable.
"""
import logging
import os
import sys
import traceback

_log = logging.getLogger("cex")
_FALSEY = ("", "0", "false", "no", "off")


def enabled() -> bool:
    """Is fault logging on? Driven by ``CEX_DEBUG`` (any truthy value)."""
    return str(os.environ.get("CEX_DEBUG", "")).strip().lower() not in _FALSEY


def _ensure_handler() -> None:
    """Wire a stderr handler the first time we actually log, so the operator SEES swallowed faults
    without us hijacking the root logger on import."""
    if not _log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s [cex] %(levelname)s %(message)s"))
        _log.addHandler(h)
        _log.setLevel(logging.DEBUG)


def swallow(context: str = "") -> None:
    """Record the exception currently being handled, then return — the caller proceeds exactly as if it
    had ``pass``ed. Logs a one-line WARNING (+ the traceback at DEBUG) when ``CEX_DEBUG`` is set;
    otherwise a no-op. Safe to call with no active exception (records nothing). NEVER raises."""
    if not enabled():
        return
    try:
        exc = sys.exc_info()[1]
        if exc is None:
            return
        _ensure_handler()
        _log.warning("swallowed in %s: %r", context or "?", exc)
        _log.debug("traceback for %s:\n%s", context or "?", traceback.format_exc())
    except Exception:
        pass            # observability must never become the thing that crashes the desk
