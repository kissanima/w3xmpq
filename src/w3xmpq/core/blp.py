"""BLP texture reader — the format Warcraft III uses for .blp images.

Three families exist in the wild:

``BLP1 classic``
    Uncompressed BGRA, or 8-bit palettised with a 256-entry palette.
    Header is 156 bytes, palette follows, pixel data after that.

``BLP2 classic``
    Uncompressed BGRA or DXT1/DXT3/DXT5 (DirectX block compression).
    Header is 160 bytes.

``BLP1 JPEG`` (Warcraft III 1.22 and newer)
    The interesting one.  Blizzard stores the texture as a *four
    component* JPEG (CMYK) and — to make the file self-describing —
    splits the JPEG frame header in two: the ``FF C0`` marker lives at
    the end of the shared header block, while the frame length and
    body live at the start of every mipmap.  A decoder therefore has
    to stitch the two halves back together before handing the result
    to a JPEG decoder.

Everything in this module is pure Python and dependency free.  For the
JPEG variant the module does *not* decode pixels itself; it returns a
valid JPEG stream (:meth:`Blp.jpeg_bytes`) which any JPEG decoder can
read.  The classic variants are decoded to raw RGBA here.
"""

import struct

from .png import encode_png

__all__ = ["BlpError", "Blp", "open_blp", "read_blp"]

BLP1 = b"BLP1"
BLP2 = b"BLP2"

#: Header size / mipmap-table layout per family.
_HEADER_SIZE = {BLP1: 0x9C, BLP2: 0xA0}

#: Candidate (offsets_at, sizes_at) pairs.  BLP2 files produced by
#: different tools disagree on whether the mipmap table starts at
#: 0x20 or at 0x1C, so both are tried and the one whose offset/size
#: chain validates against the file length wins.
_MIPMAP_LAYOUTS = {
    BLP1: ((0x1C, 0x5C),),
    BLP2: ((0x20, 0x60), (0x1C, 0x5C)),
}

#: Where the JPEG header block starts inside a JPEG-flavoured BLP1.
_JPEG_HEADER_AT = 0xA0


class BlpError(Exception):
    """Raised when a BLP file cannot be understood."""


# --------------------------------------------------------------------------
# DXT decoders
# --------------------------------------------------------------------------

def _rgb565(value: int):
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _dxt_colors(c0: int, c1: int, dxt1: bool):
    """Return the 4-entry colour table of a DXT1 colour block."""
    r0, g0, b0 = _rgb565(c0)
    r1, g1, b1 = _rgb565(c1)
    if dxt1 and c0 <= c1:
        # 3-colour mode: c2 is transparent black.
        return [(r0, g0, b0), (r1, g1, b1), (0, 0, 0), (0, 0, 0)]
    r2 = (2 * r0 + r1) // 3
    g2 = (2 * g0 + g1) // 3
    b2 = (2 * b0 + b1) // 3
    r3 = (r0 + 2 * r1) // 3
    g3 = (g0 + 2 * g1) // 3
    b3 = (b0 + 2 * b1) // 3
    return [(r0, g0, b0), (r1, g1, b1), (r2, g2, b2), (r3, g3, b3)]


def _decode_dxt1_block(block: bytes, out: bytearray, ox: int, oy: int,
                       width: int, height: int):
    c0, c1 = struct.unpack_from("<HH", block, 0)
    table = _dxt_colors(c0, c1, dxt1=True)
    for row in range(4):
        bits = block[4 + row]
        for col in range(4):
            index = (bits >> (col * 2)) & 0x3
            r, g, b = table[index]
            if c0 <= c1 and index == 2:
                a = 0
            elif c0 <= c1 and index == 3:
                a = 0
            else:
                a = 255
            _put_pixel(out, ox + col, oy + row, width, height, r, g, b, a)


def _decode_dxt3_block(block: bytes, out: bytearray, ox: int, oy: int,
                       width: int, height: int):
    alphas = block[0:8]
    c0, c1 = struct.unpack_from("<HH", block, 8)
    table = _dxt_colors(c0, c1, dxt1=False)
    for row in range(4):
        bits = block[4 + row]
        for col in range(4):
            index = (bits >> (col * 2)) & 0x3
            r, g, b = table[index]
            a = alphas[row * 2 + col // 2]
            # Each alpha byte holds two pixels: high nibble first.
            nib = (a >> 4) & 0x0F if col % 2 == 0 else a & 0x0F
            if nib == 0xF:
                a = 255
            else:
                a = nib * 17
            _put_pixel(out, ox + col, oy + row, width, height, r, g, b, a)


def _decode_dxt5_block(block: bytes, out: bytearray, ox: int, oy: int,
                       width: int, height: int):
    # Alpha: two reference values, six interpolated ones and sixteen
    # 3-bit indices packed into six bytes.
    a0, a1 = block[0], block[1]
    alpha = [0] * 16
    alpha[0] = a0
    alpha[1] = a1
    if a0 > a1:
        for i in range(6):
            alpha[2 + i] = ((6 - i) * a0 + (i + 1) * a1) // 7
    else:
        for i in range(4):
            alpha[2 + i] = ((4 - i) * a0 + (i + 1) * a1) // 5
        alpha[6] = 0
        alpha[7] = 255
    c0, c1 = struct.unpack_from("<HH", block, 8)
    table = _dxt_colors(c0, c1, dxt1=False)
    for row in range(4):
        bits = block[12 + row]
        for col in range(4):
            index = (bits >> (col * 2)) & 0x3
            r, g, b = table[index]
            bit = row * 4 + col
            byte_index = (bit * 3) // 8
            shift = (bit * 3) % 8
            value = (block[2 + byte_index] >> shift) & 0x7
            if shift > 5 and 2 + byte_index + 1 < len(block):
                value |= (block[3 + byte_index] << (8 - shift)) & 0x7
            a = alpha[value]
            _put_pixel(out, ox + col, oy + row, width, height, r, g, b, a)


def _put_pixel(out: bytearray, x: int, y: int, width: int, height: int,
               r: int, g: int, b: int, a: int):
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 4
        out[i] = r
        out[i + 1] = g
        out[i + 2] = b
        out[i + 3] = a


def _decode_dxt(data: bytes, width: int, height: int, block_bytes: int,
                decoder) -> bytearray:
    out = bytearray(width * height * 4)
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            if pos + block_bytes > len(data):
                return out
            decoder(data[pos:pos + block_bytes], out, bx * 4, by * 4,
                    width, height)
            pos += block_bytes
    return out


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------

class Mipmap:
    """One level of the mipmap chain."""

    __slots__ = ("level", "width", "height", "offset", "size")

    def __init__(self, level, width, height, offset, size):
        self.level = level
        self.width = width
        self.height = height
        self.offset = offset
        self.size = size

    def __repr__(self):                                  # pragma: no cover
        return ("Mipmap(level=%d, %dx%d, offset=%d, size=%d)"
                % (self.level, self.width, self.height, self.offset, self.size))


class Blp:
    """A parsed BLP texture."""

    def __init__(self, data: bytes):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("BLP data must be bytes")
        self.data = bytes(data)
        if len(self.data) < 0x9C:
            raise BlpError("file is too small to be a BLP (%d bytes)"
                           % len(self.data))
        self.magic = self.data[:4]
        if self.magic not in (BLP1, BLP2):
            raise BlpError("not a BLP file (magic %r)" % (self.magic,))
        self.encoding = self._u32(0x04)
        self.alpha = self._u32(0x08)
        self.width = self._u32(0x0C)
        self.height = self._u32(0x10)
        self.extra = self._u32(0x14)
        self.alpha_encoding = self._u32(0x18)
        self.jpeg = self._detect_jpeg()
        self._jpeg_header_size = 0
        self._jpeg_header = b""
        if self.jpeg:
            self._jpeg_header_size = self._u32(0x9C)
            start = _JPEG_HEADER_AT
            end = min(len(self.data), start + self._jpeg_header_size)
            self._jpeg_header = self.data[start:end]
        self.mipmaps = self._read_mipmaps()

    # ------------------------------------------------------------------
    def _u32(self, at: int) -> int:
        if at + 4 > len(self.data):
            return 0
        return struct.unpack_from("<I", self.data, at)[0]

    def _detect_jpeg(self) -> bool:
        """Warcraft III 1.22+ BLP1 files hold a JPEG, not pixels."""
        if self.magic != BLP1:
            return False
        if self.data[_JPEG_HEADER_AT:_JPEG_HEADER_AT + 2] != b"\xff\xd8":
            return False
        return True

    def _read_mipmaps(self):
        total = len(self.data)
        for off_at, size_at in _MIPMAP_LAYOUTS[self.magic]:
            offs = struct.unpack_from("<16I", self.data, off_at) \
                if off_at + 64 <= total else ()
            sizes = struct.unpack_from("<16I", self.data, size_at) \
                if size_at + 64 <= total else ()
            levels = []
            for i in range(16):
                off, size = offs[i], sizes[i]
                if size == 0:
                    break
                if off + size > total or off >= total:
                    break
                levels.append(Mipmap(i, 0, 0, off, size))
            if not levels:
                continue
            # The chain must tile the file exactly: the last level ends
            # at the end of the data region.
            end = levels[-1].offset + levels[-1].size
            consistent = all(
                levels[i].offset + levels[i].size == levels[i + 1].offset
                for i in range(len(levels) - 1))
            if consistent and end <= total:
                for m in levels:
                    m.width = max(1, self.width >> m.level)
                    m.height = max(1, self.height >> m.level)
                if self.jpeg:
                    self._jpeg_dimensions(levels)
                return levels
        return []

    def _jpeg_dimensions(self, levels):
        """Read each level's real size out of its JPEG frame header."""
        for m in levels:
            body = self.data[m.offset:m.offset + m.size]
            # frame length (2 bytes) + precision (1) + height (2) + width (2)
            if len(body) < 7:
                continue
            try:
                _length = struct.unpack_from(">H", body, 0)[0]
                _prec = body[2]
                h, w = struct.unpack_from(">HH", body, 3)
            except struct.error:
                continue
            if 0 < w < 32768 and 0 < h < 32768:
                m.width = w
                m.height = h

    # ------------------------------------------------------------------
    @property
    def is_jpeg(self) -> bool:
        return self.jpeg

    @property
    def kind(self) -> str:
        """Human readable name of the pixel format."""
        if self.jpeg:
            return "jpeg"
        if self.magic == BLP2:
            return {0: "rgba", 1: "dxt1", 2: "dxt3",
                    3: "dxt5"}.get(self.encoding, "unknown")
        return {0: "rgba", 1: "palettized"}.get(self.encoding, "unknown")

    @property
    def has_alpha(self) -> bool:
        if self.jpeg:
            return False
        if self.magic == BLP2:
            return bool(self.alpha)
        return self.alpha != 0

    def __len__(self):
        return len(self.mipmaps)

    # ------------------------------------------------------------------
    def jpeg_bytes(self, level: int = 0) -> bytes:
        """Return a valid JPEG stream for `level` (JPEG flavour only).

        The frame header is split in the file: the ``FF C0`` marker
        closes the shared header block, the frame length and body
        start every mipmap.  Stitching them back together yields a
        stream that any standard JPEG decoder accepts.
        """
        if not self.jpeg:
            raise BlpError("this BLP does not contain a JPEG")
        if level >= len(self.mipmaps):
            raise IndexError("no mipmap level %d" % level)
        m = self.mipmaps[level]
        return self._jpeg_header + self.data[m.offset:m.offset + m.size]

    def rgba(self, level: int = 0):
        """Decode a level to ``(width, height, rgba_bytes)``.

        Only the classic (non-JPEG) flavours can be decoded without a
        JPEG decoder; the JPEG flavour raises :class:`BlpError`.
        """
        if self.jpeg:
            raise BlpError("this BLP is JPEG encoded — use jpeg_bytes()")
        if level >= len(self.mipmaps):
            raise IndexError("no mipmap level %d" % level)
        m = self.mipmaps[level]
        chunk = self.data[m.offset:m.offset + m.size]
        w, h = m.width, m.height
        if self.kind == "rgba":
            return w, h, self._decode_bgra(chunk, w, h)
        if self.kind == "palettized":
            return w, h, self._decode_palettized(chunk, w, h)
        if self.kind == "dxt1":
            return w, h, _decode_dxt(chunk, w, h, 8, _decode_dxt1_block)
        if self.kind == "dxt3":
            return w, h, _decode_dxt(chunk, w, h, 16, _decode_dxt3_block)
        if self.kind == "dxt5":
            return w, h, _decode_dxt(chunk, w, h, 16, _decode_dxt5_block)
        raise BlpError("unsupported BLP encoding %d" % self.encoding)

    def _decode_bgra(self, chunk: bytes, w: int, h: int) -> bytearray:
        out = bytearray(w * h * 4)
        stride = w * 4
        for y in range(h):
            src = (h - 1 - y) * stride          # BLP stores bottom-up
            if src + stride > len(chunk):
                break
            row = chunk[src:src + stride]
            for x in range(w):
                b, g, r, a = row[x * 4:x * 4 + 4]
                i = (y * w + x) * 4
                out[i] = r
                out[i + 1] = g
                out[i + 2] = b
                out[i + 3] = a
        return out

    def _decode_palettized(self, chunk: bytes, w: int, h: int) -> bytearray:
        palette_at = 0x9C
        out = bytearray(w * h * 4)
        for y in range(h):
            src = (h - 1 - y) * w
            if src + w > len(chunk):
                break
            for x in range(w):
                index = chunk[src + x]
                r, g, b, a = self._palette_entry(index)
                i = (y * w + x) * 4
                out[i] = r
                out[i + 1] = g
                out[i + 2] = b
                out[i + 3] = a
        return out

    def _palette_entry(self, index: int):
        at = 0x9C + index * 4
        if at + 4 > len(self.data):
            return (0, 0, 0, 255)
        b, g, r, a = self.data[at:at + 4]
        return (r, g, b, a)

    def png_bytes(self, level: int = 0) -> bytes:
        """Encode a level as a PNG (classic flavours only)."""
        w, h, rgba = self.rgba(level)
        return encode_png(w, h, bytes(rgba))


def open_blp(data: bytes) -> Blp:
    """Parse BLP data."""
    return Blp(data)


def read_blp(path: str) -> Blp:
    """Read and parse a BLP file from disk."""
    with open(path, "rb") as fh:
        return Blp(fh.read())
