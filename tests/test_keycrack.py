#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 unit tests: key recovery (core.keycrack).

build_archive() preserves file order in the block table, so block index i
corresponds exactly to sample_file_set()[i].
"""

import os
import random
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402
from w3xmpq.core.extract import open_archive  # noqa: E402
from w3xmpq.core.keycrack import recover_base_key, recover_named_key  # noqa: E402

SPECS = gen_synth.sample_file_set()


class TestRecoverBaseKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls._tmp.name, 'synth.mpq')
        with open(cls.path, 'wb') as f:
            f.write(gen_synth.build_archive(SPECS))
        cls.arch = open_archive(cls.path)
        # Reproduce build_archive's seeded key assignment.
        rng = random.Random(0xC0FFEE)
        cls.keys = []
        for s in SPECS:
            if s['flags'] & gen_synth.F_ENCRYPTED:
                if s.get('use_named_key'):
                    cls.keys.append(gen_synth.named_key(s['name']))
                else:
                    cls.keys.append(rng.getrandbits(32))
            else:
                cls.keys.append(0)

    @classmethod
    def tearDownClass(cls):
        cls.arch.file.close()
        cls._tmp.cleanup()

    def test_block_table_maps_to_specs_in_order(self):
        self.assertEqual(len(self.arch.block_table), len(SPECS))
        for i, (block, spec) in enumerate(zip(self.arch.block_table, SPECS)):
            self.assertEqual(block.size, len(spec['data']),
                             "block %d size mismatch" % i)
            self.assertEqual(block.flags, spec['flags'] | gen_synth.F_EXISTS,
                             "block %d flags mismatch" % i)

    def test_encrypted_multi_sector_keys_recovered(self):
        checked = 0
        for i, (block, spec) in enumerate(zip(self.arch.block_table, SPECS)):
            if not (spec['flags'] & gen_synth.F_ENCRYPTED):
                continue
            if spec['flags'] & gen_synth.F_SINGLE_UNIT:
                continue  # no offset table -> crack N/A (named path)
            fd = self.arch.read_block_data(block)
            key = recover_base_key(self.arch, block, fd)
            self.assertIsNotNone(key, "%s: key not recovered" % spec['name'])
            self.assertEqual(key, self.keys[i],
                             "%s: recovered key %08X != built key %08X"
                             % (spec['name'], key, self.keys[i]))
            checked += 1
        self.assertGreaterEqual(checked, 4, "expected several encrypted files")

    def test_unencrypted_blocks_return_zero(self):
        for i, (block, spec) in enumerate(zip(self.arch.block_table, SPECS)):
            if spec['flags'] & gen_synth.F_ENCRYPTED:
                continue
            fd = self.arch.read_block_data(block)
            self.assertEqual(recover_base_key(self.arch, block, fd), 0,
                             "%s: unencrypted block must yield key 0"
                             % spec['name'])

    def test_named_key_fallback(self):
        # Encrypted SINGLE_UNIT: offset-table crack N/A, named key must work.
        spec = next(s for s in SPECS if s.get('use_named_key'))
        idx = SPECS.index(spec)
        block = self.arch.block_table[idx]
        fd = self.arch.read_block_data(block)
        self.assertIsNone(recover_base_key(self.arch, block, fd),
                          "offset-table crack should N/A on single-unit")
        key = recover_named_key(self.arch, spec['name'], block)
        self.assertEqual(key, self.keys[idx],
                         "named key != builder key")

if __name__ == '__main__':
    unittest.main()
