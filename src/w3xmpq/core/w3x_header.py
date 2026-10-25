#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.w3x_header — Warcraft III map user-data header parser.

A .w3x/.w3m map starts with a fixed 512-byte user-data header before the
embedded MPQ. Layout (post-1.04):

  0x00  char[4]  "HM3W"
  0x04  int32    header format version (11/18/25/28/29/31/70)
  0x08  int32    editor build number (e.g. 6072 = 1.24)
  0x0C  asciiz   map name
  ...   asciiz   author
  ...   asciiz   description
  ...   asciiz   players recommended
  ...   float[8] camera bounds, int32 margin, float[2] camera w/h
  ...   int32    map width (tiles*2), int32 map height (tiles*2)
  ...   int32    flags (bit 0 = melee)
  ...   char     tileset

Only well-documented fields are decoded; unknown flag bits are shown as hex.
"""

import struct

HEADER_SIZE = 512
MAGIC = b'HM3W'

FLAG_MELEE = 0x00000001

TILESETS = {
    'L': "Lordaeron Summer", 'N': "Northrend", 'A': "Ashenvale",
    'S': "Sunken Ruins", 'B': "Lordaeron Fall", 'C': "Lordaeron Winter",
    'D': "Dalaran", 'F': "Felwood", 'G': "Underground", 'W': "Cityscape",
    'Z': "Village", 'V': "Village Fall", 'X': "Village Winter",
    'O': "Lordaeron Winter", 'Y': "Village Winter", 'K': "Reforged Cityscape",
}


def _cstr(buf, off):
    end = buf.find(b'\x00', off)
    if end < 0:
        end = len(buf)
    return buf[off:end].decode('cp1252', 'replace'), end + 1


def is_w3x(path):
    with open(path, 'rb') as f:
        return f.read(4) == MAGIC


def parse_header(path):
    """Parse the 512-byte user-data header of a WC3 map.

    Returns a dict; raises ValueError if the file is not a WC3 map.
    """
    with open(path, 'rb') as f:
        buf = f.read(HEADER_SIZE)
    if buf[:4] != MAGIC:
        raise ValueError("%s: not a WC3 map (magic %r)" % (path, buf[:4]))

    version, build = struct.unpack_from('<2I', buf, 4)
    off = 12
    name, off = _cstr(buf, off)
    author, off = _cstr(buf, off)
    description, off = _cstr(buf, off)
    players_recommended, off = _cstr(buf, off)

    # Camera block: 8 float bounds + int32 margin + 2 float camera w/h.
    off += 4 * 8 + 4 + 4 * 2

    width = height = flags = 0
    tileset = '?'
    try:
        width, height, flags = struct.unpack_from('<3I', buf, off)
        off += 12
        if off < len(buf):
            tileset = chr(buf[off])
    except struct.error:
        pass  # truncated header — tolerate, decoys exist

    return dict(
        version=version, build=build, name=name, author=author,
        description=description, players_recommended=players_recommended,
        width=width // 2, height=height // 2, raw_width=width,
        raw_height=height, flags=flags, melee=bool(flags & FLAG_MELEE),
        tileset=tileset,
        tileset_name=TILESETS.get(tileset, "unknown (%r)" % tileset),
    )
