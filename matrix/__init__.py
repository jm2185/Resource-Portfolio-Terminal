"""
CommodityEx × InfoMatrix — display-node package (Forge-Matrix).

The matrix layer is a dumb, network-driven display node: it RENDERS engine state, it never computes a
number, a regime label, a threshold or a sort order (the same render-not-compute invariant FORGE carries
onto the glass). The engine's published /state is the single source of truth.

Import-light by design: this exposes the frozen contract, the pure adapter, and the pure encoder. The
device I/O (``matrix.device``, needs ``requests``) and the preview harness (``matrix.preview``, needs
PIL) are imported explicitly by their callers so the byte-exact fixtures and the contract stay
dependency-free.
"""
from __future__ import annotations

from .adapter import build_matrix_state
from .contract import CatalystRef, MatrixState, StressIndex, WatchItem
from .encoder import HEIGHT, MAX_FRAMES, WIDTH, encode_anim, rgb565, solid

__all__ = [
    "MatrixState", "WatchItem", "StressIndex", "CatalystRef",
    "build_matrix_state",
    "encode_anim", "rgb565", "solid", "WIDTH", "HEIGHT", "MAX_FRAMES",
]
