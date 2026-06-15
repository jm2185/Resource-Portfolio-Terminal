"""
Byte-exact tests for the anim.bin encoder (matrix/encoder.py) — Forge-Matrix M1.

These pin the CONFIRMED firmware v2.0.8 format hand-checkable against Appendix B: header 40 20 01 00,
a 1000 ms delay E8 03, and 2048 little-endian rgb565 pixels per 64x32 frame. Pure stdlib — no PIL, no
device — so they run in CI off-network.
"""
import struct
import unittest

from matrix import encoder as enc

# Appendix B fixtures: (r, g, b) -> rgb565 -> little-endian byte pair.
COLORS = {
    "red": ((255, 0, 0), 0xF800, b"\x00\xf8"),
    "green": ((0, 255, 0), 0x07E0, b"\xe0\x07"),
    "blue": ((0, 0, 255), 0x001F, b"\x1f\x00"),
    "white": ((255, 255, 255), 0xFFFF, b"\xff\xff"),
}
HEADER_1F = bytes([enc.WIDTH, enc.HEIGHT, 0x01, 0x00])      # dimension-agnostic header
DELAY_1000 = b"\xe8\x03"


class Rgb565Tests(unittest.TestCase):
    def test_fixture_values(self):
        for name, (rgb, val, _) in COLORS.items():
            self.assertEqual(enc.rgb565(*rgb), val, name)

    def test_packed_bytes_little_endian(self):
        for name, (rgb, val, le) in COLORS.items():
            self.assertEqual(struct.pack("<H", enc.rgb565(*rgb)), le, name)


class EncodeAnimTests(unittest.TestCase):
    def test_solid_frame_is_byte_exact(self):
        for name, (rgb, _, le) in COLORS.items():
            payload = enc.encode_anim([enc.solid(*rgb)], [1000])
            expected = HEADER_1F + DELAY_1000 + le * enc.N_PIXELS
            self.assertEqual(payload, expected, name)
            self.assertEqual(len(payload), 4 + 2 + enc.N_PIXELS * 2, name)

    def test_header_and_delay_slice(self):
        payload = enc.encode_anim([enc.solid(255, 0, 0)], [1000])
        self.assertEqual(payload[:4], HEADER_1F)
        self.assertEqual(payload[4:6], DELAY_1000)
        self.assertEqual(payload[6:8], b"\x00\xf8")              # first red pixel

    def test_delay_clamped_to_min(self):
        # firmware floor is max(delay, 20); 5 ms must encode as 20 -> 0x14 0x00
        payload = enc.encode_anim([enc.solid(0, 0, 0)], [5])
        self.assertEqual(payload[4:6], struct.pack("<H", enc.MIN_DELAY_MS))
        self.assertEqual(payload[4:6], b"\x14\x00")

    def test_numframes_byte_and_payload_length(self):
        frames = [enc.solid(0, 0, 0), enc.solid(255, 255, 255), enc.solid(0, 255, 0)]
        payload = enc.encode_anim(frames, [100, 200, 300])
        self.assertEqual(payload[2], 3)                          # numFrames byte
        self.assertEqual(len(payload), 4 + 3 * enc.frame_bytes())

    def test_raw_bytes_and_tuple_seq_agree(self):
        raw = enc.solid(12, 200, 60)
        seq = [(12, 200, 60)] * enc.N_PIXELS
        self.assertEqual(enc.encode_anim([raw], [50]), enc.encode_anim([seq], [50]))

    def test_frame_bytes(self):
        self.assertEqual(enc.frame_bytes(), 2 + enc.WIDTH * enc.HEIGHT * 2)

    def test_guards(self):
        with self.assertRaises(ValueError):
            enc.encode_anim([], [])
        with self.assertRaises(ValueError):
            enc.encode_anim([enc.solid(0, 0, 0)], [10, 20])      # length mismatch
        with self.assertRaises(ValueError):
            enc.encode_anim([enc.solid(0, 0, 0)] * (enc.MAX_FRAMES + 1),
                            [10] * (enc.MAX_FRAMES + 1))         # > 255 frames
        with self.assertRaises(ValueError):
            enc.encode_anim([b"\x00\x00\x00"], [10])             # wrong raw length


if __name__ == "__main__":
    unittest.main()
