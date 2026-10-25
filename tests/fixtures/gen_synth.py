#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_synth — generate synthetic encrypted MPQ fixtures for w3xmpq tests.

Builds complete, valid MPQ v0 archives from scratch — including encrypted
hash/block tables and per-file encryption — so the crack engine can be
regression-tested WITHOUT any copyrighted game data. Also supports the WC3
.w3x wrapper (HM3W user-data header + embedded MPQ).

This module is test-only code; it is not part of the shipped package.
"""

import bz2
import os
import random
import struct
import sys
import zlib

_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from w3xmpq.core.mpq import MPQArchive  # noqa: E402

# File flags (mirror of core.mpq constants, for builder readability).
F_EXISTS       = 0x80000000
F_COMPRESS     = 0x00000200
F_ENCRYPTED    = 0x00010000
F_FIX_KEY      = 0x00020000
F_SPARSE       = 0x00040000
F_SINGLE_UNIT  = 0x01000000
F_SECTOR_CRC   = 0x04000000


# ----------------------------------------------------------------------
# MPQ encryptor — the exact inverse of MPQArchive._decrypt (core/mpq.py).
# The cipher is self-synchronizing on plaintext: the seed update consumes
# the *plaintext* dword, so encryption mirrors decryption step for step.
# Trailing sub-word bytes stay plaintext, same as decryption.
# ----------------------------------------------------------------------
def mpq_encrypt(data, key):
    T = MPQArchive.encryption_table
    seed1 = key & 0xFFFFFFFF
    seed2 = 0xEEEEEEEE
    out = bytearray()
    n = (len(data) // 4) * 4
    for i in range(n // 4):
        p = struct.unpack_from('<I', data, i * 4)[0]
        seed2 = (seed2 + T[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        c = p ^ ((seed1 + seed2) & 0xFFFFFFFF)
        seed1 = (((~seed1 << 0x15) + 0x11111111) | (seed1 >> 0x0B)) & 0xFFFFFFFF
        seed2 = (p + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
        out += struct.pack('<I', c)
    return bytes(out) + data[n:]


def _hasher():
    """A stand-in object so we can call MPQArchive._hash without an archive."""
    class _T(object):
        pass
    t = _T()
    t.encryption_table = MPQArchive.encryption_table
    return t


def mpq_hash(string, hash_type):
    return MPQArchive._hash(_hasher(), string, hash_type)


def named_key(name, fix_key=True):
    """The MPQ file key for a known filename (FIX_KEY variant only)."""
    key = mpq_hash(name, 'TABLE')
    if not fix_key:
        raise ValueError("non-FIX_KEY named keys depend on block offsets; "
                         "the builder only supports FIX_KEY files")
    return key


# ----------------------------------------------------------------------
# SPARSE encoding (inverse of core.sectors.sparse_decode, StormLib algo).
# ----------------------------------------------------------------------
def sparse_encode(data):
    out = bytearray(struct.pack('>I', len(data)))
    i, n = 0, len(data)
    while i < n:
        if data[i] == 0:
            j = i
            while j < n and data[j] == 0 and (j - i) < 130:
                j += 1
            run = j - i
            if run >= 3:
                out.append(run - 3)          # zero run of (b&0x7F)+3
                i = j
                continue
        j = i
        while j < min(n, i + 128) and data[j] != 0:
            j += 1
        if j == i:
            j = i + 1                        # lone zero byte as literal
        out.append(0x80 | (j - i - 1))
        out += data[i:j]
        i = j
    return bytes(out)


# ----------------------------------------------------------------------
# File payload construction (mirrors core.sectors.extract_block's rules).
# ----------------------------------------------------------------------
def _compress_best(data):
    z = zlib.compress(data, 9)
    if len(z) + 1 < len(data):
        return b'\x02' + z
    try:
        b = bz2.compress(data, 9)
        if len(b) + 1 < len(data):
            return b'\x10' + b
    except Exception:
        pass
    return b'\x00' + data


def build_file_payload(data, flags, key, sector_size):
    single = bool(flags & F_SINGLE_UNIT)
    compress = bool(flags & F_COMPRESS)
    encrypted = bool(flags & F_ENCRYPTED)
    sparse = bool(flags & F_SPARSE)
    crc = bool(flags & F_SECTOR_CRC)

    if single:
        payload = data
        if sparse:
            payload = sparse_encode(payload)
        if compress:
            payload = _compress_best(payload)
        if encrypted:
            payload = mpq_encrypt(payload, key)
        return payload

    sectors = [data[i:i + sector_size] for i in range(0, len(data), sector_size)]
    if not sectors:
        sectors = [b'']
    nsect = len(sectors)
    ntab = nsect + 1 + (1 if crc else 0)

    bodies = []
    for i, sec in enumerate(sectors):
        s = sec
        if sparse:
            s = sparse_encode(s)
        if compress:
            # Same mask-byte rules as normal compression: mask present on
            # every sector of encrypted files and all but a short raw final
            # sector of unencrypted files. A FULL final sector (len ==
            # sector_size) is compressed like any other.
            if encrypted or i < nsect - 1 or len(sec) >= sector_size:
                s = _compress_best(s)
        bodies.append(s)

    pos = [4 * ntab]
    for s in bodies:
        pos.append(pos[-1] + len(s))
    if crc:
        pos.append(pos[-1] + 4)
    tbl = struct.pack('<%dI' % ntab, *pos)

    out = bytearray()
    if encrypted:
        out += mpq_encrypt(tbl, key)
        for i, s in enumerate(bodies):
            out += mpq_encrypt(s, (key + i + 1) & 0xFFFFFFFF)
    else:
        out += tbl
        for s in bodies:
            out += s
    if crc:
        out += b'\xDE\xAD\xBE\xEF'   # CRC dword — never read by the extractor
    return bytes(out)


# ----------------------------------------------------------------------
# Archive assembly.
# ----------------------------------------------------------------------
def build_archive(files, sector_shift=3, hash_entries=32, seed=0xC0FFEE):
    """Build a complete MPQ v0 archive in memory.

    `files`: list of dicts {name, data, flags, use_named_key?}. Encrypted
    multi-sector files get random keys (from a seeded RNG); encrypted
    SINGLE_UNIT files use the named key and must set F_FIX_KEY.
    Returns the raw archive bytes.
    """
    rng = random.Random(seed)
    ss = 512 << sector_shift
    specs = []
    for f in files:
        flags = f['flags']
        key = 0
        if flags & F_ENCRYPTED:
            if f.get('use_named_key'):
                key = named_key(f['name'], fix_key=True)
            else:
                key = rng.getrandbits(32)
        payload = build_file_payload(f['data'], flags, key, ss)
        specs.append((f['name'], f['data'], flags, key, payload))

    data_start = 32
    data_region = bytearray()
    blocks = []
    for name, data, flags, key, payload in specs:
        blocks.append(dict(offset=data_start + len(data_region),
                           archived_size=len(payload), size=len(data),
                           flags=flags | F_EXISTS, key=key, name=name))
        data_region += payload

    hash_table_offset = data_start + len(data_region)
    ht = bytearray(b'\xFF' * (16 * hash_entries))
    for i, blk in enumerate(blocks):
        ha = mpq_hash(blk['name'], 'HASH_A')
        hb = mpq_hash(blk['name'], 'HASH_B')
        struct.pack_into('<2I2HI', ht, i * 16, ha, hb, 0, 0, i)
    block_table_offset = hash_table_offset + len(ht)

    bt = bytearray()
    for blk in blocks:
        bt += struct.pack('<4I', blk['offset'], blk['archived_size'],
                          blk['size'], blk['flags'])
    ht_enc = mpq_encrypt(bytes(ht), mpq_hash('(hash table)', 'TABLE'))
    bt_enc = mpq_encrypt(bytes(bt), mpq_hash('(block table)', 'TABLE'))

    archive_size = block_table_offset + len(bt_enc)
    header = struct.pack('<4s2I2H4I', b'MPQ\x1a', 32, archive_size, 0,
                         sector_shift, hash_table_offset,
                         block_table_offset, hash_entries, len(blocks))
    return header + bytes(data_region) + ht_enc + bt_enc


def build_w3x(mpq_bytes, map_name=b'SynthMap', author=b'SynthAuthor',
              description=b'Synthetic test map', width=64, height=64,
              flags=0, tileset=ord('L')):
    """Wrap MPQ bytes in a WC3 map container with a realistic 512-byte
    HM3W user-data header (layout per core.w3x_header)."""
    hdr = bytearray(b'\x00' * 512)
    off = 0
    hdr[0:4] = b'HM3W'
    off = 4
    off += struct.pack_into('<2I', hdr, off, 31, 6072) or 8
    for s in (map_name, author, description, b'any'):
        hdr[off:off + len(s)] = s
        off += len(s) + 1                       # asciiz
    off += 4 * 8 + 4 + 4 * 2                    # camera bounds/margin/w/h
    struct.pack_into('<3I', hdr, off, width * 2, height * 2, flags)
    off += 12
    hdr[off] = tileset
    return bytes(hdr) + mpq_bytes


def sample_file_set():
    """The P1 flag-matrix fixture set. Returns a list of file specs."""
    rng = random.Random(0xBEEF)
    ss = 512 << 3          # must match build_archive's default sector_shift=3
    text = (b"function main takes nothing returns nothing\n"
            b"endfunction\n") * 40
    big = bytes(rng.randrange(1, 256) for _ in range(ss * 2 + 1234))
    exact = bytes(rng.randrange(1, 256) for _ in range(ss * 2))
    zeros = b'\x00' * 5000 + b'ABCD' + b'\x00' * 3000
    short_last = bytes(rng.randrange(1, 256) for _ in range(ss + 77))

    return [
        dict(name='stored.bin', data=big, flags=F_EXISTS),
        dict(name='zlib.ms', data=big, flags=F_EXISTS | F_COMPRESS),
        dict(name='shortlast.ms', data=short_last,
             flags=F_EXISTS | F_COMPRESS),
        dict(name='exact.ms', data=exact, flags=F_EXISTS | F_COMPRESS),
        dict(name='bz2.ms', data=big, flags=F_EXISTS | F_COMPRESS),
        dict(name='plain.ms', data=big, flags=F_EXISTS),
        dict(name='enc.ms', data=text, flags=F_EXISTS | F_COMPRESS | F_ENCRYPTED),
        dict(name='enc.raw.ms', data=big,
             flags=F_EXISTS | F_ENCRYPTED),
        dict(name='enc.crc.ms', data=text,
             flags=F_EXISTS | F_COMPRESS | F_ENCRYPTED | F_SECTOR_CRC),
        dict(name='crc.ms', data=big,
             flags=F_EXISTS | F_COMPRESS | F_SECTOR_CRC),
        dict(name='single.stored', data=text, flags=F_EXISTS | F_SINGLE_UNIT),
        dict(name='single.z', data=text,
             flags=F_EXISTS | F_SINGLE_UNIT | F_COMPRESS),
        # Encrypted single-unit files can only be recovered through a known
        # name (hash probe -> named key), so this one uses a canonical
        # WC3 filename that core.names.KNOWN_NAMES probes for.
        dict(name='war3map.dpk', data=text, use_named_key=True,
             flags=F_EXISTS | F_SINGLE_UNIT | F_COMPRESS | F_ENCRYPTED
                   | F_FIX_KEY),
        dict(name='sparse.ms', data=zeros,
             flags=F_EXISTS | F_COMPRESS | F_SPARSE),
        dict(name='sparse.enc.ms', data=zeros, flags=F_EXISTS | F_COMPRESS
             | F_SPARSE | F_ENCRYPTED),
    ]


def write_fixtures(outdir):
    """Write synthetic .mpq and .w3x fixtures. Returns the file paths."""
    os.makedirs(outdir, exist_ok=True)
    mpq_bytes = build_archive(sample_file_set())
    p_mpq = os.path.join(outdir, 'synth.mpq')
    p_w3x = os.path.join(outdir, 'synth.w3x')
    with open(p_mpq, 'wb') as f:
        f.write(mpq_bytes)
    with open(p_w3x, 'wb') as f:
        f.write(build_w3x(mpq_bytes))
    return p_mpq, p_w3x


if __name__ == '__main__':
    import json
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    a, b = write_fixtures(out)
    print(json.dumps([a, b]))
