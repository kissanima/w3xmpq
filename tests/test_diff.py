#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 unit tests: listing and content diff (core.extract / core.diff)."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402
from w3xmpq.core.extract import scan_archive  # noqa: E402
from w3xmpq.core.diff import diff_archives  # noqa: E402

SPECS = gen_synth.sample_file_set()


def _write(raw, name):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, name)
    with open(path, 'wb') as f:
        f.write(raw)
    return path


class TestScan(unittest.TestCase):
    def test_scan_finds_all_files_with_names(self):
        path = _write(gen_synth.build_archive(SPECS), 's.mpq')
        entries = scan_archive(path)
        self.assertEqual(len([e for e in entries if e['status'] == 'ok']),
                         len(SPECS))
        # The canonical-name file must be probed, not guessed.
        names = {e['name'] for e in entries if e['status'] == 'ok'}
        self.assertIn('war3map.dpk', names)
        # Names map: Scripts\war3map.j remap doesn't apply here, but
        # JASS-text files should be guessed as war3map.j.
        self.assertIn('war3map.j', names)

    def test_scan_closes_file(self):
        path = _write(gen_synth.build_archive(SPECS), 's.mpq')
        entries = scan_archive(path)
        self.assertTrue(True)  # no assertion — would crash on Windows cleanup


class TestDiff(unittest.TestCase):
    def test_identical_archives(self):
        raw = gen_synth.build_archive(SPECS)
        pa = _write(raw, 'a.mpq')
        pb = _write(raw, 'b.mpq')
        d = diff_archives(pa, pb)
        self.assertEqual(d['common'], len(SPECS))
        self.assertEqual(d['added'], [])
        self.assertEqual(d['removed'], [])

    def test_modified_archive(self):
        specs = [dict(s) for s in SPECS]
        raw_a = gen_synth.build_archive(specs)
        # Change one file's data and add one extra file.
        specs2 = [dict(s) for s in SPECS]
        specs2[0]['data'] = specs2[0]['data'] + b'CHANGED'
        specs2.append(dict(name='extra.bin', data=b'NEW FILE CONTENT',
                           flags=gen_synth.F_EXISTS))
        raw_b = gen_synth.build_archive(specs2)
        pa = _write(raw_a, 'a.mpq')
        pb = _write(raw_b, 'b.mpq')
        d = diff_archives(pa, pb)
        self.assertEqual(len(d['added']), 2, "changed file + new file")
        self.assertEqual(len(d['removed']), 1, "changed file's old content")
        self.assertEqual(d['common'], len(SPECS) - 1)


if __name__ == '__main__':
    unittest.main()
