"""
Tests for the tiny 3x5 bitmap font (matrix/font.py) — Forge-Matrix M3. Pins glyph geometry, cursor
advance, right-alignment, pixel blitting, the missing-glyph fallback, and off-canvas clipping.
"""
import unittest

from PIL import Image

from matrix import font


class GlyphGeometryTests(unittest.TestCase):
    def test_every_glyph_is_3x5(self):
        for ch, g in font.GLYPHS.items():
            self.assertEqual(len(g), font.GLYPH_H, repr(ch))
            for row in g:
                self.assertEqual(len(row), font.GLYPH_W, repr(ch))
                self.assertTrue(set(row) <= {"#", "."}, repr(ch))

    def test_fallback_for_unknown_char(self):
        self.assertEqual(font.glyph("☃"), font._FALLBACK)   # snowman -> box

    def test_glyph_is_case_insensitive(self):
        self.assertEqual(font.glyph("a"), font.glyph("A"))


class DrawTests(unittest.TestCase):
    def setUp(self):
        self.img = Image.new("RGB", (64, 32))

    def test_text_width(self):
        self.assertEqual(font.text_width("ABC"), 3 * font.ADVANCE)

    def test_draw_text_advances_cursor(self):
        self.assertEqual(font.draw_text(self.img, 0, 0, "AB", (255, 255, 255)), 2 * font.ADVANCE)

    def test_draw_text_sets_expected_pixels(self):
        font.draw_text(self.img, 0, 0, "I", (10, 20, 30))       # 'I' top row "###"
        px = self.img.load()
        self.assertEqual([px[x, 0] for x in range(3)], [(10, 20, 30)] * 3)

    def test_space_draws_nothing_but_advances(self):
        font.draw_text(self.img, 0, 0, " ", (255, 255, 255))
        self.assertEqual(self.img.load()[0, 0], (0, 0, 0))

    def test_draw_text_right_alignment(self):
        start = font.draw_text_right(self.img, 63, 0, "5", (1, 2, 3))
        self.assertEqual(start, 63 - font.text_width("5") + 1)

    def test_offscreen_is_clipped_not_raised(self):
        font.draw_text(self.img, -2, -2, "M", (255, 255, 255))   # must not raise
        font.draw_text(self.img, 62, 30, "M", (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
