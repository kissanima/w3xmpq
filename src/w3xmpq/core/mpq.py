#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.mpq — self-contained MPQ (MoPaQ) archive reader.

Vendored and adapted for w3xmpq. The header/table parsing, hashing and
decryption logic is derived from `mpyq` 0.2.5 (MIT License, Copyright (c)
Aku Kotkavuo, https://github.com/alanstevens/mpyq) with the following changes:

  * encryption support kept minimal and self-contained (no listfile reads,
    no extraction helpers -- w3xmpq's own sector engine handles those);
  * O(1) filename -> hash-table-entry lookup (hash map instead of linear scan);
  * accepts file-like objects (BytesIO) so embedded archives (WC3 .w3x maps)
    can be opened without temp files.

This module intentionally supports only what w3xmpq needs: MPQ format 0/1
headers, hash/block tables, the MPQ crypt tables, and raw block reading.
"""

import struct
from collections import namedtuple
from io import BytesIO

__all__ = [
    "MPQArchive", "MPQFile", "MPQHashTableEntry", "MPQBlockTableEntry",
    "MPQ_FILE_IMPLODE", "MPQ_FILE_COMPRESS", "MPQ_FILE_ENCRYPTED",
    "MPQ_FILE_FIX_KEY", "MPQ_FILE_SINGLE_UNIT", "MPQ_FILE_DELETE_MARKER",
    "MPQ_FILE_SECTOR_CRC", "MPQ_FILE_EXISTS",
]

MPQ_FILE_IMPLODE        = 0x00000100
MPQ_FILE_COMPRESS       = 0x00000200
MPQ_FILE_ENCRYPTED      = 0x00010000
MPQ_FILE_FIX_KEY        = 0x00020000
MPQ_FILE_SINGLE_UNIT    = 0x01000000
MPQ_FILE_DELETE_MARKER  = 0x02000000
MPQ_FILE_SECTOR_CRC     = 0x04000000
MPQ_FILE_EXISTS         = 0x80000000

MPQFileHeader = namedtuple('MPQFileHeader',
    '''
    magic
    header_size
    archive_size
    format_version
    sector_size_shift
    hash_table_offset
    block_table_offset
    hash_table_entries
    block_table_entries
    '''
)
MPQFileHeader.struct_format = '<4s2I2H4I'

MPQFileHeaderExt = namedtuple('MPQFileHeaderExt',
    '''
    extended_block_table_offset
    hash_table_offset_high
    block_table_offset_high
    '''
)
MPQFileHeaderExt.struct_format = 'q2h'

MPQUserDataHeader = namedtuple('MPQUserDataHeader',
    '''
    magic
    user_data_size
    mpq_header_offset
    user_data_header_size
    '''
)
MPQUserDataHeader.struct_format = '<4s3I'

MPQHashTableEntry = namedtuple('MPQHashTableEntry',
    '''
    hash_a
    hash_b
    locale
    platform
    block_table_index
    '''
)
MPQHashTableEntry.struct_format = '2I2HI'

MPQBlockTableEntry = namedtuple('MPQBlockTableEntry',
    '''
    offset
    archived_size
    size
    flags
    '''
)
MPQBlockTableEntry.struct_format = '4I'

# Alias matching w3xmpq's domain naming.
MPQFile = MPQBlockTableEntry


class MPQArchive(object):
    """Minimal MPQ archive reader (format 0/1).

    Accepts a path or a binary file-like object (with read/seek). The
    listfile is never read automatically -- w3xmpq works without one.
    """

    def __init__(self, filename):
        if hasattr(filename, 'read'):
            self.file = filename
        else:
            self.file = open(filename, 'rb')
        self.header = self.read_header()
        self.hash_table = self.read_table('hash')
        self.block_table = self.read_table('block')
        self._hashmap = None

    # ------------------------------------------------------------------
    # Header & tables
    # ------------------------------------------------------------------
    def read_header(self):
        """Read the header of a MPQ archive."""

        def read_mpq_header(offset=None):
            if offset:
                self.file.seek(offset)
            data = self.file.read(32)
            header = MPQFileHeader._make(
                struct.unpack(MPQFileHeader.struct_format, data))
            header = header._asdict()
            if header['format_version'] == 1:
                data = self.file.read(12)
                extended_header = MPQFileHeaderExt._make(
                    struct.unpack(MPQFileHeaderExt.struct_format, data))
                header.update(extended_header._asdict())
            return header

        def read_mpq_user_data_header():
            data = self.file.read(16)
            header = MPQUserDataHeader._make(
                struct.unpack(MPQUserDataHeader.struct_format, data))
            header = header._asdict()
            header['content'] = self.file.read(header['user_data_header_size'])
            return header

        magic = self.file.read(4)
        self.file.seek(0)

        if magic == b'MPQ\x1a':
            header = read_mpq_header()
            header['offset'] = 0
        elif magic == b'MPQ\x1b':
            user_data_header = read_mpq_user_data_header()
            header = read_mpq_header(user_data_header['mpq_header_offset'])
            header['offset'] = user_data_header['mpq_header_offset']
            header['user_data_header'] = user_data_header
        else:
            raise ValueError("Invalid file header (not an MPQ archive).")

        return header

    def read_table(self, table_type):
        """Read either the hash or block table of a MPQ archive."""

        if table_type == 'hash':
            entry_class = MPQHashTableEntry
        elif table_type == 'block':
            entry_class = MPQBlockTableEntry
        else:
            raise ValueError("Invalid table type.")

        table_offset = self.header['%s_table_offset' % table_type]
        table_entries = self.header['%s_table_entries' % table_type]
        key = self._hash('(%s table)' % table_type, 'TABLE')

        self.file.seek(table_offset + self.header['offset'])
        data = self.file.read(table_entries * 16)
        data = self._decrypt(data, key)

        def unpack_entry(position):
            entry_data = data[position * 16:position * 16 + 16]
            return entry_class._make(
                struct.unpack(entry_class.struct_format, entry_data))

        return [unpack_entry(i) for i in range(table_entries)]

    # ------------------------------------------------------------------
    # Filename lookup
    # ------------------------------------------------------------------
    def _build_hashmap(self):
        self._hashmap = {}
        for i, e in enumerate(self.hash_table):
            if e.block_table_index != 0xFFFFFFFF:
                self._hashmap.setdefault((e.hash_a, e.hash_b), []).append(i)

    def get_hash_table_entry(self, filename):
        """Get the hash table entry corresponding to a given filename (O(1))."""
        if self._hashmap is None:
            self._build_hashmap()
        key = (self._hash(filename, 'HASH_A'), self._hash(filename, 'HASH_B'))
        idxs = self._hashmap.get(key)
        if not idxs:
            return None
        return self.hash_table[idxs[0]]

    def read_block_data(self, block):
        """Read the raw (still encrypted/compressed) bytes of a block."""
        self.file.seek(block.offset + self.header['offset'])
        return self.file.read(block.archived_size)

    # ------------------------------------------------------------------
    # Hashing & decryption
    # ------------------------------------------------------------------
    def _hash(self, string, hash_type):
        """Hash a string using MPQ's hash function."""
        hash_types = {
            'TABLE_OFFSET': 0,
            'HASH_A': 1,
            'HASH_B': 2,
            'TABLE': 3
        }
        seed1 = 0x7FED7FED
        seed2 = 0xEEEEEEEE

        for ch in string.upper():
            if not isinstance(ch, int):
                ch = ord(ch)
            value = self.encryption_table[(hash_types[hash_type] << 8) + ch]
            seed1 = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
            seed2 = ch + seed1 + seed2 + (seed2 << 5) + 3 & 0xFFFFFFFF

        return seed1

    def _decrypt(self, data, key):
        """Decrypt hash or block table or a sector."""
        seed1 = key
        seed2 = 0xEEEEEEEE
        result = BytesIO()

        for i in range(len(data) // 4):
            seed2 += self.encryption_table[0x400 + (seed1 & 0xFF)]
            seed2 &= 0xFFFFFFFF
            value = struct.unpack("<I", data[i * 4:i * 4 + 4])[0]
            value = (value ^ (seed1 + seed2)) & 0xFFFFFFFF

            seed1 = ((~seed1 << 0x15) + 0x11111111) | (seed1 >> 0x0B)
            seed1 &= 0xFFFFFFFF
            seed2 = value + seed2 + (seed2 << 5) + 3 & 0xFFFFFFFF

            result.write(struct.pack("<I", value))

        return result.getvalue()

    def _prepare_encryption_table():
        """Prepare encryption table for MPQ hash function."""
        seed = 0x00100001
        crypt_table = {}

        for i in range(256):
            index = i
            for _ in range(5):
                seed = (seed * 125 + 3) % 0x2AAAAB
                temp1 = (seed & 0xFFFF) << 0x10

                seed = (seed * 125 + 3) % 0x2AAAAB
                temp2 = (seed & 0xFFFF)

                crypt_table[index] = (temp1 | temp2)

                index += 0x100

        return crypt_table

    encryption_table = _prepare_encryption_table()
