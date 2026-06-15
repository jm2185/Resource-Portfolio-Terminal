"""
Offline preview harness (Forge-Matrix M1) — judge layouts with NO device.

Renders any list of frames (the same frames ``encoder.encode_anim`` consumes) to a scaled PNG and a
looping GIF on disk. This is the off-network workhorse: all M3/M4 layout work happens here, eyeballed at
a sane zoom, long before the panel ever sees a byte. PIL lives here (and in the M3 renderers), never in
the pure ``encoder``.

A frame may be a PIL ``Image``, raw RGB ``bytes`` (W*H*3, see ``encoder.solid``), or a sequence of
(r, g, b) — whatever ``encode_anim`` accepts; ``_to_pil`` normalises them.
"""
from __future__ import annotations

from typing import List, Sequence

from PIL import Image

from .encoder import HEIGHT, N_PIXELS, WIDTH, Frame


def _to_pil(frame: Frame) -> Image.Image:
    """Normalise any supported frame type to a 64x32 RGB PIL image."""
    if hasattr(frame, "load") and hasattr(frame, "size"):  # already a PIL image
        img = frame.convert("RGB") if getattr(frame, "mode", None) != "RGB" else frame  # type: ignore[attr-defined]
        return img.resize((WIDTH, HEIGHT)) if img.size != (WIDTH, HEIGHT) else img
    img = Image.new("RGB", (WIDTH, HEIGHT))
    if isinstance(frame, (bytes, bytearray)):
        if len(frame) != N_PIXELS * 3:
            raise ValueError(f"raw frame must be {N_PIXELS * 3} bytes, got {len(frame)}")
        img.frombytes(bytes(frame))
        return img
    seq = list(frame)  # type: ignore[arg-type]
    if len(seq) != N_PIXELS:
        raise ValueError(f"pixel sequence must have {N_PIXELS} entries, got {len(seq)}")
    img.putdata([(int(t[0]), int(t[1]), int(t[2])) for t in seq])
    return img


def to_png(frame: Frame, path: str, scale: int = 10) -> str:
    """Write one frame to a nearest-neighbour-scaled PNG (so 64x32 is legible). Returns the path."""
    img = _to_pil(frame).resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST)
    img.save(path)
    return path


def to_gif(frames: Sequence[Frame], delays_ms: Sequence[int], path: str,
           scale: int = 10, loop: int = 0) -> str:
    """Write a list of frames + per-frame delays to a looping animated GIF. Returns the path."""
    if not frames or len(frames) != len(delays_ms):
        raise ValueError("frames and delays_ms must be non-empty and equal length")
    imgs: List[Image.Image] = [
        _to_pil(f).resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST) for f in frames
    ]
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=[max(int(d), 20) for d in delays_ms], loop=loop, disposal=2)
    return path


def contact_sheet(frames: Sequence[Frame], path: str, scale: int = 6, cols: int = 1,
                  gap: int = 4, bg=(20, 20, 20)) -> str:
    """Stack frames into a single PNG (a static 'film strip') — for comparing screens side by side."""
    imgs = [_to_pil(f).resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST) for f in frames]
    if not imgs:
        raise ValueError("no frames")
    rows = (len(imgs) + cols - 1) // cols
    cw, ch = WIDTH * scale, HEIGHT * scale
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * gap, rows * ch + (rows + 1) * gap), bg)
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        sheet.paste(im, (gap + c * (cw + gap), gap + r * (ch + gap)))
    sheet.save(path)
    return path
