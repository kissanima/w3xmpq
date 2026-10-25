#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.sectors — sector splitting, keying and decompression.

MPQ format-0/1 multi-sector files (empirically validated on vanilla maps):

  * the sector offset table is encrypted with the file's BASE key;
  * data sector i is encrypted with (base + i + 1) — the offset table
    occupies key slot 0.

Whole-block single-key decryption is WRONG; per-sector (key + i) is WRONG.

Compression-mask rules (StormLib-compatible):
  * ENCRYPTED + COMPRESS files carry a mask byte on EVERY sector, including
    the short final one (proven byte-exact on 1,854 real map files);
  * unencrypted COMPRESS files store the short final sector RAW, without a
    mask byte;
  * SECTOR_CRC adds one extra offset-table entry (the CRC dword) which is
    NOT a data sector and must not be emitted.
"""

import bz2
import struct
import zlib

from . import codecs as _codecs
from .keycrack import (SECTOR_SHIFT_DEFAULT, dec_full, recover_base_key,
                       recover_named_key)

MPQ_FILE_COMPRESS     = 0x00000200
MPQ_FILE_ENCRYPTED    = 0x00010000
MPQ_FILE_FIX_KEY      = 0x00020000
MPQ_FILE_SPARSE       = 0x00040000
MPQ_FILE_SINGLE_UNIT  = 0x01000000
MPQ_FILE_SECTOR_CRC   = 0x04000000


def decompress_masked(mask, body, expected=None):
    """Decompress a sector given its compression-method byte.

    `expected` (when known) enables the PKWARE codec, whose output length
    must be checked to bound decoding.
    """
    if mask == 0x00:
        return body
    if mask == 0x02:
        return zlib.decompress(body, 15)
    if mask == 0x10:
        return bz2.decompress(body)
    if mask == 0x08:
        if expected is None:
            raise ValueError("pkware codec needs the expected output size")
        return _codecs.pkware_explode(body, expected)
    raise ValueError("unsupported compression mask 0x%02x" % mask)


def sparse_decode(data):
    """Decode an MPQ SPARSE-compressed buffer (StormLib algorithm).

    Layout: 4-byte big-endian total (uncompressed) size, then chunks:
    a byte with the 0x80 flag means a literal run of (b & 0x7F) + 1 bytes,
    otherwise a zero run of (b & 0x7F) + 3 zero bytes.
    """
    if len(data) < 4:
        raise ValueError("sparse buffer too short")
    total = struct.unpack('>I', data[:4])[0]
    out = bytearray()
    i = 4
    while i < len(data):
        b = data[i]
        i += 1
        if b & 0x80:
            n = (b & 0x7F) + 1
            out += data[i:i + n]
            i += n
        else:
            out += b'\x00' * ((b & 0x7F) + 3)
    if len(out) != total:
        raise ValueError("sparse size mismatch (%d != %d)" % (len(out), total))
    return bytes(out)


def _decode_sector(sec, compress, sparse, expected):
    """Interpret one decrypted sector and return its plaintext.

    `expected` is the sector's true plaintext length — the ground truth for
    choosing between the two possible storages:
      A) compression-mask byte + body (zlib/bzip2/stored), optionally
         holding a sparse stream;
      B) raw content, no mask byte (unencrypted short final sectors; also
         uncompressed sparse sectors).
    Returns bytes or None if neither interpretation fits.
    """
    def _post(body):
        return sparse_decode(body) if sparse else body

    if compress:
        try:
            cand = _post(decompress_masked(sec[0], sec[1:], expected=expected))
            if len(cand) == expected:
                return cand
        except Exception:
            pass
        try:
            cand = _post(sec)
            if len(cand) == expected:
                return cand
        except Exception:
            pass
        return None
    try:
        cand = _post(sec)
    except Exception:
        return None
    return cand if len(cand) == expected else None


def extract_block(arch, block, fd, name=None):
    """Decrypt + decompress one file block. Returns plaintext bytes or None.

    `name` (when known from the hash probe) enables the named-key fallback
    for encrypted files that carry no sector offset table (SINGLE_UNIT).
    """
    encrypted = bool(block.flags & MPQ_FILE_ENCRYPTED)
    compress = bool(block.flags & MPQ_FILE_COMPRESS)
    sparse = bool(block.flags & MPQ_FILE_SPARSE)
    ss = 512 << arch.header.get('sector_size_shift', SECTOR_SHIFT_DEFAULT)

    base = 0
    if encrypted:
        base = recover_base_key(arch, block, fd)
        if base is None and name is not None:
            base = recover_named_key(arch, name, block)
        if base is None:
            return None

    if block.flags & MPQ_FILE_SINGLE_UNIT:
        candidates = (base, (base + 1) & 0xFFFFFFFF) if encrypted else (base,)
        for k in candidates:
            try:
                d = dec_full(arch, fd, k) if encrypted else fd
                if compress:
                    d = decompress_masked(d[0], d[1:])
                if sparse:
                    d = sparse_decode(d)
                d = bytes(d)
                # Size verification: a wrong key must never be accepted.
                if len(d) == block.size:
                    return d
            except Exception:
                continue
        return None

    # --- multi-sector -----------------------------------------------------
    nsect = block.size // ss + 1                        # data sectors
    ntab = nsect + 1 + (1 if block.flags & MPQ_FILE_SECTOR_CRC else 0)
    tbl = fd[:4 * ntab]
    if encrypted:
        tbl = dec_full(arch, tbl, base)
    try:
        pos = struct.unpack('<%dI' % ntab, tbl)
    except struct.error:
        return None

    out = bytearray()
    for i in range(nsect):
        sec = fd[pos[i]:pos[i + 1]]
        if not sec:
            continue
        if encrypted:
            sec = dec_full(arch, sec, (base + i + 1) & 0xFFFFFFFF)
        # Expected plaintext length of this sector — the ground truth for
        # choosing between mask-byte and raw interpretations.
        expected = ss if i < nsect - 1 else block.size - i * ss
        if compress or sparse:
            plain = _decode_sector(sec, compress, sparse, expected)
            if plain is None:
                return None
        else:
            # No compression: content is stored raw, no interpretation
            # ambiguity. (Some protected maps carry decoy blocks whose size
            # metadata contradicts the stored data — accept what's stored.)
            plain = sec
        out += plain
    return bytes(out)
