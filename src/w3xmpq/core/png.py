"""Minimal PNG encoder (RGBA -> PNG bytes).

Pure standard library: zlib for the deflate stream, struct for the
chunk headers.  Used by the BLP decoder to hand images to Qt (or any
other viewer) without pulling in an imaging dependency.
"""

import struct
import zlib

__all__ = ["encode_png", "encode_png_rgb"]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(width: int, height: int, rgba: bytes,
               level: int = 6) -> bytes:
    """Encode raw RGBA bytes (row-major, 4 bytes per pixel) as a PNG.

    `rgba` must be exactly ``width * height * 4`` bytes long.
    """
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError("expected %d bytes of RGBA, got %d"
                         % (expected, len(rgba)))
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)                      # filter type 0 (None)
        raw += rgba[y * stride:(y + 1) * stride]
    out = [b"\x89PNG\r\n\x1a\n"]
    out.append(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                           8, 6, 0, 0, 0)))
    out.append(_chunk(b"IDAT", zlib.compress(bytes(raw), level)))
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def encode_png_rgb(width: int, height: int, rgb: bytes,
                   level: int = 6) -> bytes:
    """Encode 3-bytes-per-pixel RGB data as an opaque PNG."""
    expected = width * height * 3
    if len(rgb) != expected:
        raise ValueError("expected %d bytes of RGB, got %d"
                         % (expected, len(rgb)))
    rgba = bytearray(expected // 3 * 4)
    for i in range(expected // 3):
        rgba[i * 4:i * 4 + 3] = rgb[i * 3:i * 3 + 3]
        rgba[i * 4 + 3] = 255
    return encode_png(width, height, bytes(rgba), level)
