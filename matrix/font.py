"""
Tiny 3x5 bitmap font (Forge-Matrix M3) — legible on a 64x32 panel where PIL's default font is far too
large. Glyphs are 3 wide x 5 tall, advanced in a 4x6 cell (1px letter spacing, 1px line gap), giving the
spec's ~16 chars x 5 rows budget. Vendored as inline data (no external BDF dependency, no parsing) so it
is self-contained, version-controlled, and unit-testable; an atlas render is the correctness check.

Uppercase-only by design (the renderer upper()s labels): caps + digits + the handful of symbols a
trading panel needs. Unknown glyphs fall back to a box so a missing char is visible, never silent.
"""
from __future__ import annotations

from typing import Tuple

GLYPH_W, GLYPH_H = 3, 5
ADVANCE = GLYPH_W + 1     # 4px per char
LINE_H = GLYPH_H + 1      # 6px per row

# Each glyph: 5 rows of 3 chars, '#' = lit.
GLYPHS = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", "..#", "..#", "..#"],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    "A": [".#.", "#.#", "###", "#.#", "#.#"],
    "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"],
    "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"],
    "F": ["###", "#..", "##.", "#..", "#.."],
    "G": [".##", "#..", "#.#", "#.#", ".##"],
    "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"],
    "J": ["..#", "..#", "..#", "#.#", ".#."],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"],
    "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#.#", "###", "###", "#.#", "#.#"],
    "N": ["#.#", "##.", "#.#", "#.#", "#.#"],
    "O": ["###", "#.#", "#.#", "#.#", "###"],
    "P": ["##.", "#.#", "##.", "#..", "#.."],
    "Q": ["###", "#.#", "#.#", "###", "..#"],
    "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": ["###", "#..", "###", "..#", "###"],
    "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"],
    "V": ["#.#", "#.#", "#.#", "#.#", ".#."],
    "W": ["#.#", "#.#", "###", "###", "#.#"],
    "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."],
    "Z": ["###", "..#", ".#.", "#..", "###"],
    " ": ["...", "...", "...", "...", "..."],
    ".": ["...", "...", "...", "...", ".#."],
    ",": ["...", "...", "...", ".#.", "#.."],
    ":": ["...", ".#.", "...", ".#.", "..."],
    "/": ["..#", "..#", ".#.", "#..", "#.."],
    "-": ["...", "...", "###", "...", "..."],
    "+": ["...", ".#.", "###", ".#.", "..."],
    "%": ["#.#", "..#", ".#.", "#..", "#.#"],
    "$": [".#.", ".##", "###", "##.", ".#."],
    "!": [".#.", ".#.", ".#.", "...", ".#."],
    "?": ["###", "..#", ".#.", "...", ".#."],
    "*": ["#.#", ".#.", "#.#", "...", "..."],
    "(": [".#.", "#..", "#..", "#..", ".#."],
    ")": [".#.", "..#", "..#", "..#", ".#."],
    "=": ["...", "###", "...", "###", "..."],
}
_FALLBACK = ["###", "#.#", "#.#", "#.#", "###"]


def glyph(ch: str):
    return GLYPHS.get(ch.upper(), _FALLBACK)


def text_width(text: str) -> int:
    """Pixel width of a rendered string (incl. the trailing advance gap)."""
    return len(text) * ADVANCE


def draw_text(img, x: int, y: int, text: str, color: Tuple[int, int, int]) -> int:
    """Blit ``text`` into a PIL image at (x, y) in ``color``. Returns the x cursor after the last glyph.
    Off-canvas pixels are clipped. Spaces advance without drawing."""
    px = img.load()
    w, h = img.size
    cx = x
    for ch in text:
        if ch != " ":
            g = glyph(ch)
            for ry, row in enumerate(g):
                yy = y + ry
                if yy < 0 or yy >= h:
                    continue
                for cxi, c in enumerate(row):
                    if c == "#":
                        xx = cx + cxi
                        if 0 <= xx < w:
                            px[xx, yy] = color
        cx += ADVANCE
    return cx


def draw_text_right(img, right_x: int, y: int, text: str, color: Tuple[int, int, int]) -> int:
    """Right-align: draw so the text ends at ``right_x``. Returns the starting x."""
    start = right_x - text_width(text) + 1
    draw_text(img, start, y, text, color)
    return start
