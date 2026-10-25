#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 unit tests: end-to-end extraction (core.extract)."""

import hashlib
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402
from w3xmpq.core.extract import extract_archive, open_archive  # noqa: E402

SPECS = gen_synth.sample_file_set()


class TestExtractEndToEnd(unittest.TestCase):
    """Roundtrip: build archive with the flag matrix -> extract -> byte-exact."""

    @classmethod
    def setUpClass(cls):
        cls.expected_sha = sorted(
            hashlib.sha256(s['data']).hexdigest() for s in SPECS)

    def _extract_and_check(self, raw_bytes, suffix):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'synth' + suffix)
            with open(path, 'wb') as f:
                f.write(raw_bytes)
            outdir = os.path.join(tmp, 'out')
            manifest = extract_archive(path, outdir, verbose=False)
            ok = [m for m in manifest if m['status'] == 'ok']
            self.assertEqual(len(ok), len(SPECS),
                             "expected %d files, manifest has %d ok"
                             % (len(SPECS), len(ok)))
            self.assertEqual(
                sorted(m['sha256'] for m in ok), self.expected_sha,
                "extracted contents do not match originals byte-for-byte")
            self.assertTrue(all(m['size'] > 0 for m in ok))
            # Manifest file on disk must agree.
            import json
            with open(os.path.join(outdir, 'manifest.json')) as f:
                disk = json.load(f)
            self.assertEqual(len(disk), len(manifest))

    def test_mpq_container(self):
        self._extract_and_check(gen_synth.build_archive(SPECS), '.mpq')

    def test_w3x_container(self):
        mpq_bytes = gen_synth.build_archive(SPECS)
        self._extract_and_check(gen_synth.build_w3x(mpq_bytes), '.w3x')

    def test_open_archive_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'nope.bin')
            with open(path, 'wb') as f:
                f.write(b'not an archive at all')
            with self.assertRaises(ValueError):
                open_archive(path)

    def test_source_file_untouched(self):
        # Read-only guarantee: extraction must not modify the source.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'synth.mpq')
            raw = gen_synth.build_archive(SPECS)
            with open(path, 'wb') as f:
                f.write(raw)
            extract_archive(path, os.path.join(tmp, 'out'), verbose=False)
            with open(path, 'rb') as f:
                self.assertEqual(f.read(), raw)


if __name__ == '__main__':
    unittest.main()
