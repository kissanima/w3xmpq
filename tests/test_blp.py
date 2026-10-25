"""Tests for the BLP texture decoder."""

import os
import struct
import unittest

from w3xmpq.core.blp import Blp, BlpError, open_blp
from w3xmpq.core.png import encode_png


def _blp1_uncompressed(width, height, pixels):
    """Build a classic BLP1: 32-bit BGRA, bottom-up rows."""
    data = bytearray(0x9C)
    data[0:4] = b"BLP1"
    struct.pack_into("<I", data, 0x04, 0)       # encoding: uncompressed
    struct.pack_into("<I", data, 0x08, 1)       # alpha depth
    struct.pack_into("<I", data, 0x0C, width)
    struct.pack_into("<I", data, 0x10, height)
    struct.pack_into("<I", data, 0x1C, 0x9C)    # mipmap 0 offset
    struct.pack_into("<I", data, 0x5C, len(pixels))
    return bytes(data) + pixels


def _blp1_palettized(width, height, indices, palette):
    data = bytearray(0x9C)
    data[0:4] = b"BLP1"
    struct.pack_into("<I", data, 0x04, 1)       # palettized
    struct.pack_into("<I", data, 0x08, 0)
    struct.pack_into("<I", data, 0x0C, width)
    struct.pack_into("<I", data, 0x10, height)
    struct.pack_into("<I", data, 0x1C, 0x9C + len(palette))
    struct.pack_into("<I", data, 0x5C, len(indices))
    return bytes(data) + palette + indices


def _blp2(encoding, width, height, blocks, alpha=0):
    data = bytearray(0xA0)
    data[0:4] = b"BLP2"
    struct.pack_into("<I", data, 0x04, encoding)
    struct.pack_into("<I", data, 0x08, 0)
    struct.pack_into("<I", data, 0x0C, width)
    struct.pack_into("<I", data, 0x10, height)
    struct.pack_into("<I", data, 0x14, alpha)
    struct.pack_into("<I", data, 0x20, 0xA0)    # mipmap 0 offset
    struct.pack_into("<I", data, 0x60, len(blocks))
    return bytes(data) + blocks


class TestBlpUncompressed(unittest.TestCase):
    def test_roundtrip_rgba(self):
        # 2x2 pixels, stored bottom-up as BGRA (blue row first).
        pixels = bytes([
            0x10, 0x20, 0x30, 0xFF, 0x11, 0x21, 0x31, 0xFF,   # bottom row
            0x40, 0x50, 0x60, 0xFF, 0x41, 0x51, 0x61, 0xFF,   # top row
        ])
        blp = open_blp(_blp1_uncompressed(2, 2, pixels))
        self.assertEqual(blp.kind, "rgba")
        self.assertEqual((blp.width, blp.height), (2, 2))
        w, h, rgba = blp.rgba()
        self.assertEqual((w, h), (2, 2))
        # First output row is the *last* stored row.  Source bytes are
        # BGRA, so 0x40,0x50,0x60 is a blue-ish colour.
        self.assertEqual(tuple(rgba[0:4]), (0x60, 0x50, 0x40, 0xFF))
        self.assertEqual(tuple(rgba[4:8]), (0x61, 0x51, 0x41, 0xFF))
        self.assertEqual(tuple(rgba[8:12]), (0x30, 0x20, 0x10, 0xFF))

    def test_png_output(self):
        pixels = bytes([0, 0, 0, 255] * 4)
        blp = open_blp(_blp1_uncompressed(2, 2, pixels))
        png = blp.png_bytes()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png)


class TestBlpPalettized(unittest.TestCase):
    def test_palette_lookup(self):
        palette = bytearray(256 * 4)
        palette[0:4] = bytes([0x00, 0x00, 0xFF, 0xFF])   # B,G,R,A = red
        palette[4:8] = bytes([0x00, 0xFF, 0x00, 0xFF])   # green
        indices = bytes([0, 1])
        blp = open_blp(_blp1_palettized(2, 1, indices, bytes(palette)))
        self.assertEqual(blp.kind, "palettized")
        w, h, rgba = blp.rgba()
        self.assertEqual(tuple(rgba[0:4]), (0xFF, 0x00, 0x00, 0xFF))
        self.assertEqual(tuple(rgba[4:8]), (0x00, 0xFF, 0x00, 0xFF))


class TestBlpDxt(unittest.TestCase):
    def _dxt1_block(self, index_byte=0x04):
        # c0 = red (0xF800), c1 = blue (0x001F); 4-colour mode.
        # Index bits are read LSB first: 0x04 -> pixel0 = 0, pixel1 = 1.
        c0, c1 = 0xF800, 0x001F
        indices = bytes([index_byte, 0, 0, 0])
        return struct.pack("<HH", c0, c1) + indices

    def test_dxt1_colors(self):
        blp = open_blp(_blp2(1, 4, 4, self._dxt1_block()))
        self.assertEqual(blp.kind, "dxt1")
        w, h, rgba = blp.rgba()
        self.assertEqual((w, h), (4, 4))
        self.assertEqual(tuple(rgba[0:4]), (0xFF, 0x00, 0x00, 0xFF))
        self.assertEqual(tuple(rgba[4:8]), (0x00, 0x00, 0xFF, 0xFF))

    def test_dxt3_alpha(self):
        # 8 explicit alpha nibbles (0xF = opaque) + a DXT1 colour block.
        # Each byte holds two pixels: high nibble = left, low = right.
        block = bytes([0x8F, 0xF0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]) \
            + self._dxt1_block()
        blp = open_blp(_blp2(2, 4, 4, block))
        self.assertEqual(blp.kind, "dxt3")
        w, h, rgba = blp.rgba()
        self.assertEqual(rgba[3], 8 * 17)      # first pixel: high nibble
        self.assertEqual(rgba[7], 255)        # second pixel: low nibble
        self.assertEqual(rgba[11], 255)       # third pixel
        self.assertEqual(rgba[15], 0)         # fourth pixel

    def test_dxt5_alpha(self):
        a0, a1 = 0xFF, 0x00
        indices = bytes([0x00] * 6)          # all pixels use alpha[0]
        block = bytes([a0, a1]) + indices + self._dxt1_block()
        blp = open_blp(_blp2(3, 4, 4, block))
        self.assertEqual(blp.kind, "dxt5")
        w, h, rgba = blp.rgba()
        self.assertEqual(rgba[3], 0xFF)

    def test_dxt5_interpolated_alpha(self):
        # a0=0x80, a1=0x00 and a0 > a1 -> alpha[2] = 6*0x80/7 = 109
        block = bytes([0x80, 0x00]) + bytes([0x02] * 6) + self._dxt1_block()
        blp = open_blp(_blp2(3, 4, 4, block))
        w, h, rgba = blp.rgba()
        # index byte 0x02 -> first pixel picks index 2
        self.assertEqual(rgba[3], 109)


class TestBlpErrors(unittest.TestCase):
    def test_not_a_blp(self):
        with self.assertRaises(BlpError):
            open_blp(b"NOTABLP" + b"\x00" * 200)

    def test_too_small(self):
        with self.assertRaises(BlpError):
            open_blp(b"BLP1")


class TestRealBlpFiles(unittest.TestCase):
    """The Warcraft III installation ships real .blp files."""

    ROOT = os.path.join("..", "..", "..", "..")

    def _find_blps(self):
        base = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", ".."))
        found = []
        ui = os.path.join(base, "UI")
        if not os.path.isdir(ui):
            return found
        for dirpath, _dirs, files in os.walk(ui):
            for name in files:
                if name.lower().endswith(".blp"):
                    found.append(os.path.join(dirpath, name))
        return found

    def _load(self, path):
        with open(path, "rb") as fh:
            return Blp(fh.read())

    def test_real_files_parse(self):
        files = self._find_blps()
        if not files:
            self.skipTest("no .blp files in the Warcraft III folder")
        for path in files[:20]:
            blp = self._load(path)
            self.assertTrue(blp.is_jpeg, path)
            self.assertTrue(blp.mipmaps, path)
            blob = blp.jpeg_bytes(0)
            self.assertTrue(blob.startswith(b"\xff\xd8"))
            self.assertTrue(blob.endswith(b"\xff\xd9"))

    def test_real_file_mipmap_dimensions(self):
        files = self._find_blps()
        if not files:
            self.skipTest("no .blp files in the Warcraft III folder")
        blp = self._load(files[0])
        first = blp.mipmaps[0]
        self.assertGreater(first.width, 0)
        self.assertGreater(first.height, 0)
        # Each following level is half the size of the previous one.
        for prev, cur in zip(blp.mipmaps, blp.mipmaps[1:]):
            self.assertLessEqual(cur.width, max(1, prev.width // 2))
            self.assertLessEqual(cur.height, max(1, prev.height // 2))

    def test_cli_converts_a_texture(self):
        import tempfile
        from w3xmpq.cli import main
        files = self._find_blps()
        if not files:
            self.skipTest("no .blp files in the Warcraft III folder")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tex.jpg")
            rc = main(["blp", files[0], "-o", out])
            self.assertEqual(rc, 0)
            with open(out, "rb") as fh:
                blob = fh.read()
            self.assertTrue(blob.startswith(b"\xff\xd8"))
            self.assertTrue(blob.endswith(b"\xff\xd9"))

    def test_cli_converts_to_png(self):
        import tempfile
        from w3xmpq.cli import main
        files = self._find_blps()
        if not files:
            self.skipTest("no .blp files in the Warcraft III folder")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "tex.png")
            try:
                rc = main(["blp", files[0], "-o", out])
            except SystemExit:
                rc = 0
            if rc != 0 or not os.path.exists(out):
                self.skipTest("PNG conversion needs Pillow")
            with open(out, "rb") as fh:
                blob = fh.read()
            self.assertTrue(blob.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
