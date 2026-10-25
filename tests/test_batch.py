#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 unit tests: batch extraction (core.batch)."""

import csv
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402
from w3xmpq.core.batch import batch_extract, find_archives  # noqa: E402

SPECS = gen_synth.sample_file_set()


class TestBatch(unittest.TestCase):
    def test_find_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, 'sub')
            os.makedirs(sub)
            for name, raw in (('a.mpq', gen_synth.build_archive(SPECS)),
                              ('b.w3x', gen_synth.build_w3x(
                                  gen_synth.build_archive(SPECS))),
                              ('notes.txt', b'not an archive')):
                with open(os.path.join(tmp, name), 'wb') as f:
                    f.write(raw)
            with open(os.path.join(sub, 'c.w3m'), 'wb') as f:
                f.write(gen_synth.build_archive(SPECS))
            found = [os.path.basename(p) for p in find_archives(tmp)]
            self.assertEqual(sorted(found), ['a.mpq', 'b.w3x', 'c.w3m'])

    def test_batch_extracts_and_indexes(self):
        with tempfile.TemporaryDirectory() as root, \
             tempfile.TemporaryDirectory() as outdir:
            with open(os.path.join(root, 'a.mpq'), 'wb') as f:
                f.write(gen_synth.build_archive(SPECS))
            with open(os.path.join(root, 'broken.mpq'), 'wb') as f:
                f.write(b'garbage data, not an archive')
            index = batch_extract(root, outdir)
            self.assertEqual(len(index), 2)
            by_status = {r['source'].endswith('a.mpq'): r for r in index}
            good = by_status[True]
            bad = by_status[False]
            self.assertEqual(good['status'], 'ok')
            self.assertEqual(good['ok'], len(SPECS))
            self.assertEqual(bad['status'], 'error')
            self.assertIn('not a WC3 map', bad['error'])
            # index.csv written and well-formed
            with open(os.path.join(outdir, 'index.csv')) as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertTrue(os.path.isfile(
                os.path.join(outdir, 'index.json')))


if __name__ == '__main__':
    unittest.main()
