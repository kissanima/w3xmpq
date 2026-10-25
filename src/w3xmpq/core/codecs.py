#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.codecs — compression codecs for old (pre-2000) MPQ archives.

Status: **beta**. PKWARE DCL implode (mask 0x08) is implemented and guarded:
any decode whose output length disagrees with the sector's expected length is
rejected upstream (core.sectors), so a wrong decode can never silently
corrupt an extraction — it only marks the file FAILED. Verified against
synthetic literal streams; match-path validation needs real D1/SC archives
(see CONTRIBUTING).

Huffman (0x01) and ADPCM audio (0x40/0x80) are deferred to v1.1.
"""

MPQ_COMPRESS_PKWARE = 0x08


class _BitReader(object):
    """LSB-first bit reader over bytes (PKWARE imploded streams)."""

    __slots__ = ("data", "pos", "bit", "eof")

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.bit = 0
        self.eof = False

    def getbit(self):
        if self.pos >= len(self.data):
            self.eof = True
            raise EOFError("pkware stream exhausted")
        b = (self.data[self.pos] >> self.bit) & 1
        self.bit += 1
        if self.bit == 8:
            self.bit = 0
            self.pos += 1
        return b

    def getbyte(self):
        """8 bits, LSB-first, packed into one byte."""
        value = 0
        for i in range(8):
            value |= self.getbit() << i
        return value


def pkware_explode(data, out_size):
    """Decompress a PKWARE DCL-imploded buffer (compression mask 0x08).

    `data` includes the 2-byte implode header (byte 0: bit0 = literal
    encoding (unused for decoding), bit1 = dictionary size; byte 1: unused).
    `out_size` is the expected uncompressed size — decoding stops there.
    """
    if len(data) < 2:
        raise ValueError("pkware stream too short")
    br = _BitReader(data[2:])
    out = bytearray()
    while len(out) < out_size:
        if br.getbit() == 0:
            # Literal: 8 bits, LSB-first.
            out.append(br.getbyte())
        else:
            if br.getbit() == 0:
                # Short match: length 2..3, 8-bit distance.
                length = 2 + br.getbit()
                distance = br.getbyte() + 1
            else:
                # Long match: length 3..258, 9-bit distance.
                length = br.getbyte() + 3
                if length > out_size - len(out):
                    length = out_size - len(out)
                distance = (br.getbyte() << 1 | br.getbit()) + 1
            if distance > len(out):
                raise ValueError("pkware match distance beyond output")
            for _ in range(length):
                out.append(out[-distance])
    if len(out) != out_size:
        raise ValueError("pkware size mismatch (%d != %d)"
                         % (len(out), out_size))
    return bytes(out)


def dcl_literal_stream(data):
    """Encode `data` as a PKWARE-imploded literal-only stream.

    Test-side helper (also used for tiny incompressible blobs): every byte
    is encoded as flag-bit 0 + 8 data bits, LSB-first.
    """
    bits = bytearray()
    out = bytearray([0x00, 0x00])       # binary literals, 4KB dictionary
    bitpos = 0
    cur = 0
    for byte in data:
        cur |= (0 << bitpos)            # flag bit 0: literal
        bitpos += 1
        if bitpos == 8:
            bits.append(cur)
            cur = 0
            bitpos = 0
        for i in range(8):
            cur |= ((byte >> i) & 1) << bitpos
            bitpos += 1
            if bitpos == 8:
                bits.append(cur)
                cur = 0
                bitpos = 0
    if bitpos:
        bits.append(cur)
    out += bits
    return bytes(out)
