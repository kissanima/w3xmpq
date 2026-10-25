#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.mpq_write — minimal MPQ v0 writer.

Used by `rebuild`: writes recovered files into a fresh, standard, *unencrypted*
MPQ archive (format 0) that World Editor and every other tool can read.
The cipher/machinery mirrors the battle-tested builder in tests/fixtures
(gen_synth) — the encryptor is the exact inverse of core.mpq._decrypt.

This is deliberately NOT a general-purpose MPQ packer: it writes standard
4096-byte-sector, zlib-compressed archives with no encryption.
"""

import struct
import zlib

from .mpq import MPQArchive

SECTOR_SHIFT = 3                       # 4096-byte sectors


def mpq_encrypt(data, key):
    """Encrypt whole words with the MPQ cipher (inverse of _decrypt).

    Trailing sub-word bytes stay plaintext, symmetric with decryption.
    """
    table = MPQArchive.encryption_table
    seed1 = key & 0xFFFFFFFF
    seed2 = 0xEEEEEEEE
    out = bytearray()
    n = (len(data) // 4) * 4
    for i in range(n // 4):
        p = struct.unpack_from('<I', data, i * 4)[0]
        seed2 = (seed2 + table[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        c = p ^ ((seed1 + seed2) & 0xFFFFFFFF)
        seed1 = (((~seed1 << 0x15) + 0x11111111) | (seed1 >> 0x0B)) & 0xFFFFFFFF
        seed2 = (p + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
        out += struct.pack('<I', c)
    return bytes(out) + data[n:]


def _hash(string, hash_type):
    class _T(object):
        pass
    t = _T()
    t.encryption_table = MPQArchive.encryption_table
    return MPQArchive._hash(t, string, hash_type)


F_EXISTS    = 0x80000000
F_COMPRESS  = 0x00000200

STUB_FILES = {
    # Minimal authoring stubs so World Editor can open a script-only map.
    "war3map.wtg": b"WTG!\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
    "war3map.wct": b"WCT!\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00",
    "war3map.imp": b"IMP!\x01\x00\x00\x00\x00\x00\x00\x00",
}


def build_mpq(files):
    """Build a standard MPQ v0 archive from [(name, data), ...].

    Files are zlib-compressed per sector with the usual mask byte; the
    final short sector is stored raw. Hash/block tables are encrypted with
    the standard table keys (mandatory — every reader expects that).
    """
    ss = 512 << SECTOR_SHIFT
    data_start = 32
    data_region = bytearray()
    blocks = []
    for name, data in files:
        sectors = [data[i:i + ss] for i in range(0, len(data), ss)]
        if not sectors:
            sectors = [b'']
        bodies = []
        for i, sec in enumerate(sectors):
            z = zlib.compress(sec, 6)
            bodies.append((b'\x02' + z) if (len(z) + 1 < len(sec)
                                            or i < len(sectors) - 1)
                          else sec)
        ntab = len(sectors) + 1
        pos = [4 * ntab]
        for s in bodies:
            pos.append(pos[-1] + len(s))
        payload = struct.pack('<%dI' % ntab, *pos) + b''.join(bodies)
        blocks.append(dict(offset=data_start + len(data_region),
                           archived_size=len(payload), size=len(data),
                           name=name))
        data_region += payload

    hash_table_offset = data_start + len(data_region)
    entries = max(16, 1 << (len(blocks) - 1).bit_length()) if blocks else 16
    ht = bytearray(b'\xFF' * (16 * entries))
    for i, blk in enumerate(blocks):
        struct.pack_into('<2I2HI', ht, i * 16,
                         _hash(blk['name'], 'HASH_A'),
                         _hash(blk['name'], 'HASH_B'), 0, 0, i)
    bt = bytearray()
    for blk in blocks:
        bt += struct.pack('<4I', blk['offset'], blk['archived_size'],
                          blk['size'], F_EXISTS | F_COMPRESS)

    ht_enc = mpq_encrypt(bytes(ht), _hash('(hash table)', 'TABLE'))
    bt_enc = mpq_encrypt(bytes(bt), _hash('(block table)', 'TABLE'))
    archive_size = hash_table_offset + len(ht_enc) + len(bt_enc)
    header = struct.pack('<4s2I2H4I', b'MPQ\x1a', 32, archive_size, 0,
                         SECTOR_SHIFT, hash_table_offset,
                         hash_table_offset + len(ht_enc), entries, len(blocks))
    return header + bytes(data_region) + ht_enc + bt_enc


def rebuild_map(path, out_path, extra_files=None):
    """Write a World-Editor-openable copy of a (protected) map.

    All recovered files are rewritten into a fresh standard MPQ with:
      * the fallback script (Scripts\\war3map.j) renamed to canonical
        war3map.j,
      * minimal stub authoring files injected when missing,
      * a real (listfile),
      * no per-file encryption.

    Returns the list of file names written.
    """
    from .extract import scan_archive
    from .names import NAME_REMAP

    entries = scan_archive(path)
    names = {e['name'] for e in entries if e['name']}

    files = []
    for e in entries:
        if e['status'] != 'ok' or not e['name']:
            continue
        name = NAME_REMAP.get(e['name'], e['name'])
        files.append([name, e['data']])

    # Canonical script resolution: if the fallback script exists and the
    # canonical war3map.j is missing OR is an anti-tamper stub, the real
    # script becomes war3map.j and the stub is dropped.
    def _find(name):
        for f in files:
            if f[0] == name:
                return f
        return None

    STUBS = (b"Disabled Single Player", b"EndGame")
    fallback = _find('war3map_script.j')
    canonical = _find('war3map.j')
    if fallback is not None and (canonical is None
                                 or any(m in canonical[1] for m in STUBS)):
        if canonical is not None:
            files.remove(canonical)
        fallback[0] = 'war3map.j'

    have = {f[0] for f in files}
    for stub, blob in STUB_FILES.items():
        if stub not in have:
            files.append([stub, blob])

    have = {f[0] for f in files}
    listfile = "\r\n".join(sorted(have)) + "\r\n"
    files.append(["(listfile)", listfile.encode('utf-8')])
    if extra_files:
        files.extend([list(x) for x in extra_files])

    with open(out_path, 'wb') as f:
        f.write(build_mpq(files))
    return [n for n, _ in files]
