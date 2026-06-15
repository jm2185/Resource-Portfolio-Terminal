"""
anim.bin encoder — the confirmed InfoMatrix framebuffer format (Forge-Matrix M1).

CONFIRMED from the firmware v2.0.8 web-UI source (Appendix A/B of the build spec):

  Header (4 raw bytes):  [width][height][numFrames][0x00]
  Per frame:             delay  uint16 little-endian (ms; firmware uses max(centiseconds*10, 20)),
                         then width*height pixels, each uint16 little-endian, ROW-MAJOR from top-left.
  Pixel (rgb565):        ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3), written LSB then MSB.

This module is intentionally **pure** — stdlib ``struct`` only, no PIL, no ``requests`` — so the
byte-exact fixtures run in CI with zero dependencies and zero device. The drawing (PIL) lives in the
screen renderers (M3) and the offline preview harness; the network I/O lives in ``device.py``.

A frame may be any of:
  * a PIL ``Image`` (duck-typed: ``.load()`` + ``.size``) — what the M3 renderers produce;
  * raw ``bytes``/``bytearray`` of length width*height*3 (RGB, row-major) — see ``solid()``;
  * a sequence of (r, g, b) tuples, length width*height.
All three encode to identical bytes.
"""
from __future__ import annotations

import struct
from typing import Iterable, Iterator, List, Sequence, Tuple, Union

WIDTH, HEIGHT = 64, 32
N_PIXELS = WIDTH * HEIGHT

# A single byte holds numFrames, so the format ceiling is 255 frames; the ~400 KB practical payload
# limit (4096 bytes/frame -> ~97 frames) bites first. Kept here so callers can guard against it.
MAX_FRAMES = 255
MIN_DELAY_MS = 20  # firmware floor: max(centiseconds*10, 20)

Frame = Union["object", bytes, bytearray, Sequence[Tuple[int, int, int]]]


def rgb565(r: int, g: int, b: int) -> int:
    """Pack 8-8-8 RGB into a 16-bit rgb565 value (the device's native pixel)."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def solid(r: int, g: int, b: int) -> bytes:
    """A solid WIDTH*HEIGHT frame as raw RGB bytes (no PIL needed). Handy for fixtures/fills."""
    return bytes((r & 0xFF, g & 0xFF, b & 0xFF)) * N_PIXELS


def _iter_pixels(frame: Frame) -> Iterator[Tuple[int, int, int]]:
    """Yield exactly N_PIXELS (r, g, b) tuples row-major, from any supported frame type."""
    # PIL Image (duck-typed so this module never imports PIL).
    if hasattr(frame, "load") and hasattr(frame, "size"):
        img = frame.convert("RGB") if getattr(frame, "mode", None) != "RGB" else frame  # type: ignore[attr-defined]
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT))
        px = img.load()
        for y in range(HEIGHT):
            for x in range(WIDTH):
                p = px[x, y]
                yield p[0], p[1], p[2]
        return
    # Raw RGB bytes, row-major.
    if isinstance(frame, (bytes, bytearray)):
        if len(frame) != N_PIXELS * 3:
            raise ValueError(f"raw frame must be {N_PIXELS * 3} bytes (W*H*3), got {len(frame)}")
        for i in range(0, len(frame), 3):
            yield frame[i], frame[i + 1], frame[i + 2]
        return
    # Sequence of (r, g, b).
    seq: List[Tuple[int, int, int]] = list(frame)  # type: ignore[arg-type]
    if len(seq) != N_PIXELS:
        raise ValueError(f"pixel sequence must have {N_PIXELS} entries (W*H), got {len(seq)}")
    for t in seq:
        yield t[0], t[1], t[2]


def encode_anim(frames: Sequence[Frame], delays_ms: Sequence[int]) -> bytes:
    """Encode frames + per-frame delays (ms) into the device's anim.bin byte stream.

    Byte-exact to the firmware format: header ``[W][H][n][0]``, then per frame a little-endian uint16
    delay (clamped to >= MIN_DELAY_MS) followed by W*H little-endian rgb565 pixels, row-major.
    """
    n = len(frames)
    if not frames or n != len(delays_ms):
        raise ValueError("frames and delays_ms must be non-empty and equal length")
    if not (1 <= n <= MAX_FRAMES):
        raise ValueError(f"numFrames must be 1..{MAX_FRAMES}, got {n}")
    out = bytearray([WIDTH, HEIGHT, n, 0])
    for frame, delay in zip(frames, delays_ms):
        out += struct.pack("<H", max(int(delay), MIN_DELAY_MS) & 0xFFFF)
        for r, g, b in _iter_pixels(frame):
            out += struct.pack("<H", rgb565(r, g, b))
    return bytes(out)


def frame_bytes() -> int:
    """Bytes one encoded frame occupies (delay + pixels) — for payload-budget guards (M4)."""
    return 2 + N_PIXELS * 2
