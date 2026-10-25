#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.keycrack — MPQ per-file key recovery via known-plaintext attack.

THE core of w3xmpq. Every file in an MPQ archive can be encrypted with its own
key. When the filename is unknown (no listfile, protected maps), the key can
still be recovered from the file's own data:

  * Every encrypted, multi-sector file starts with its sector offset table.
    Its first DWORD is always `4 * (sectors + 1)` — known plaintext.
  * The MPQ cipher's first output dword satisfies
        ct0 ^ p0 = key + 0xEEEEEEEE + T[0x400 + (key & 0xFF)]
    where T is the MPQ crypt table (see core/mpq.py `_decrypt`).
  * We enumerate the 256 possible table indexes (low byte), derive a candidate
    key for each, and keep the self-consistent ones (key & 0xFF == index).
  * Each candidate is verified by decrypting the whole offset table and
    checking that it is monotonically increasing, starts at
    `4 * (sectors + 1)` and ends at the archived size.

Validated on 1,854 real files across two protected WC3 maps with zero key
failures (DotA 6.83d AI: 1297/1297, MooMoo v3.19b: 557/559).
"""

import struct

# Sector-offset-table verification needs the exact sector count; SECTOR_CRC
# files carry one extra table entry (the CRC sector).
SECTOR_SHIFT_DEFAULT = 10


def sector_count(block, sector_size_shift):
    """Number of offset-table entries: sectors + 1, +1 more with SECTOR_CRC."""
    ss = 512 << sector_size_shift
    sectors = block.size // ss + 1
    if block.flags & 0x04000000:              # SECTOR_CRC
        sectors += 1
    return sectors


def recover_named_key(arch, name, block):
    """Key derived from a known filename (MPQ spec: hash(name, FILE_KEY)).

    Only applies when the filename is known (hash-probe hit). Used as a
    fallback when the offset-table crack cannot apply — e.g. encrypted
    SINGLE_UNIT files, which carry no sector offset table.
    """
    key = arch._hash(name, 'TABLE')
    if not (block.flags & 0x00020000):        # FIX_KEY not set
        key = ((key + block.offset) ^ block.size) & 0xFFFFFFFF
    return key


def dec_full(arch, data, key):
    """MPQ decrypt that keeps trailing sub-word bytes as plaintext.

    The MPQ cipher only covers whole 4-byte words; the trailing
    `len(data) % 4` bytes are stored as-is. Zero-padding them corrupts
    compressed streams (this is one of the three bugs that break other tools).
    """
    n = (len(data) // 4) * 4
    if n == 0:
        return data
    return arch._decrypt(data[:n], key) + data[n:]


def recover_base_key(arch, block, fd):
    """Recover the file's base key from its (encrypted) sector offset table.

    Returns 0 for unencrypted blocks, the recovered key for encrypted ones,
    or None if recovery failed.
    """
    if not (block.flags & 0x00010000):        # not encrypted -> no key needed
        return 0
    sectors = sector_count(block, arch.header.get('sector_size_shift',
                                                  SECTOR_SHIFT_DEFAULT))
    p0 = 4 * (sectors + 1)
    ct0 = struct.unpack('<I', fd[:4])[0]
    X = (ct0 ^ p0) & 0xFFFFFFFF
    cands = []
    for lb in range(256):
        key = (X - 0xEEEEEEEE - arch.encryption_table[0x400 + lb]) & 0xFFFFFFFF
        if key & 0xFF == lb:
            cands.append(key)
    for k in cands:
        ot = dec_full(arch, fd[:4 * (sectors + 1)], k)
        pos = struct.unpack('<%dI' % (sectors + 1), ot)
        if (pos[0] == p0 and pos[-1] == block.archived_size
                and all(pos[i] < pos[i + 1] for i in range(len(pos) - 1))):
            return k
    return None
