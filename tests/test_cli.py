#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 unit tests: CLI smoke tests (w3xmpq.cli via `python -m w3xmpq`)."""

import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, '..', 'src'))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))

import gen_synth  # noqa: E402

SPECS = gen_synth.sample_file_set()


def _run(args, env_extra=None):
    env = dict(os.environ)
    env['PYTHONPATH'] = _SRC + os.pathsep + env.get('PYTHONPATH', '')
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, '-m', 'w3xmpq'] + args,
                          capture_output=True, text=True, env=env)


class TestCli(unittest.TestCase):
    def test_help(self):
        r = _run(['--help'])
        self.assertEqual(r.returncode, 0)
        self.assertIn('w3xmpq', r.stdout)
        self.assertIn('extract', r.stdout)

    def test_version(self):
        r = _run(['--version'])
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r'w3xmpq \d+\.\d+\.\d+')

    def test_extract_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'synth.mpq')
            with open(path, 'wb') as f:
                f.write(gen_synth.build_archive(SPECS))
            outdir = os.path.join(tmp, 'out')
            r = _run(['extract', path, '-o', outdir, '-q'])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('Extracted %d files, 0 failed' % len(SPECS),
                          r.stdout)
            self.assertIn('%d/%d' % (len(SPECS), len(SPECS)), r.stdout)
            self.assertTrue(os.path.isfile(
                os.path.join(outdir, 'manifest.json')))

    def test_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'synth.mpq')
            with open(path, 'wb') as f:
                f.write(gen_synth.build_archive(SPECS))
            r = _run(['open', path])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('block table entries %d' % len(SPECS), r.stdout)

    def test_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'nope.bin')
            with open(path, 'wb') as f:
                f.write(b'garbage')
            r = _run(['extract', path, '-o', os.path.join(tmp, 'o')])
            self.assertEqual(r.returncode, 2)   # fatal error
            self.assertIn('error', r.stderr)

    def test_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'synth.mpq')
            with open(path, 'wb') as f:
                f.write(gen_synth.build_archive(SPECS))
            r = _run(['list', path])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('war3map.dpk', r.stdout)
            r = _run(['list', path, '--json'])
            self.assertEqual(r.returncode, 0, r.stderr)
            import json
            rows = json.loads(r.stdout)
            self.assertEqual(len(rows), len(SPECS))

    def test_diff(self):
        raw = gen_synth.build_archive(SPECS)
        with tempfile.TemporaryDirectory() as tmp:
            pa = os.path.join(tmp, 'a.mpq')
            pb = os.path.join(tmp, 'b.mpq')
            specs2 = [dict(s) for s in SPECS]
            specs2[0]['data'] = specs2[0]['data'] + b'CHANGED'
            with open(pa, 'wb') as f:
                f.write(raw)
            with open(pb, 'wb') as f:
                f.write(gen_synth.build_archive(specs2))
            r = _run(['diff', pa, pb])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('only in B', r.stdout)
            r = _run(['diff', pa, pb, '--json'])
            import json
            d = json.loads(r.stdout)
            self.assertEqual(d['common'], len(SPECS) - 1)

    def test_batch(self):
        with tempfile.TemporaryDirectory() as root, \
             tempfile.TemporaryDirectory() as outdir:
            with open(os.path.join(root, 'a.mpq'), 'wb') as f:
                f.write(gen_synth.build_archive(SPECS))
            r = _run(['batch', root, '-o', outdir])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('Batch complete', r.stdout)
            self.assertTrue(os.path.isfile(
                os.path.join(outdir, 'index.csv')))


if __name__ == '__main__':
    unittest.main()
