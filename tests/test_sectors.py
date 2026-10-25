#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 unit tests: sector handling and decompression (core.sectors)."""

import os
import sys
import unittest
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'src')))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'fixtures'))

import gen_synth  # noqa: E402
from w3xmpq.core.sectors import decompress_masked, sparse_decode  # noqa: E402


class TestDecompressMasked(unittest.TestCase):
    def test_stored(self):
        self.assertEqual(decompress_masked(0x00, b'hello'), b'hello')

    def test_zlib(self):
        blob = zlib.compress(b'hello world' * 10)
        self.assertEqual(decompress_masked(0x02, blob), b'hello world' * 10)

    def test_bzip2(self):
        import bz2
        blob = bz2.compress(b'hello world' * 10)
        self.assertEqual(decompress_masked(0x10, blob), b'hello world' * 10)

    def test_unknown_mask_raises(self):
        with self.assertRaises(ValueError):
            decompress_masked(0x42, b'x')


class TestSparse(unittest.TestCase):
    def _roundtrip(self, data):
        self.assertEqual(sparse_decode(gen_synth.sparse_encode(data)), data)

    def test_all_zeros(self):
        self._roundtrip(b'\x00' * 1000)

    def test_mixed(self):
        self._roundtrip(b'\x00' * 500 + b'ABCD' + b'\x00' * 130 + b'xy'
                        + b'\x00' * 2 + b'\x00' * 3)

    def test_no_zeros(self):
        self._roundtrip(bytes(range(1, 256)) * 2)

    def test_run_boundaries(self):
        # Zero runs of exactly 3 (min) and 130 (max) must encode/decode.
        for run in (3, 130, 131, 260):
            self._roundtrip(b'\x00' * run + b'Z')

    def test_single_zero_literals(self):
        # Zero runs shorter than 3 must become literals.
        self._roundtrip(b'A\x00B\x00\x00CD')

    def test_size_header(self):
        enc = gen_synth.sparse_encode(b'\x00' * 10)
        import struct
        self.assertEqual(struct.unpack('>I', enc[:4])[0], 10)

    def test_truncated_raises(self):
        with self.assertRaises(ValueError):
            sparse_decode(b'\x01')

    def test_size_mismatch_raises(self):
        with self.assertRaises(ValueError):
            sparse_decode(b'\x00\x00\x00\x09' + b'\x00')


if __name__ == '__main__':
    unittest.main()
