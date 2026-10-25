#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.3 unit tests: pkware codec, rebuild mode, listfile import."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402
from w3xmpq.core.codecs import pkware_explode, dcl_literal_stream  # noqa: E402
from w3xmpq.core.extract import scan_archive  # noqa: E402
from w3xmpq.core.mpq_write import build_mpq, rebuild_map  # noqa: E402

SPECS = gen_synth.sample_file_set()


class TestPkware(unittest.TestCase):
    def test_literal_stream_roundtrip(self):
        for blob in (b'', b'A', b'hello world', bytes(range(256)) * 3,
                     os.urandom(1000)):
            enc = dcl_literal_stream(blob)
            self.assertEqual(pkware_explode(enc, len(blob)), blob)

    def test_rejects_short_stream(self):
        with self.assertRaises(ValueError):
            pkware_explode(b'\x00', 10)


class TestMpqWrite(unittest.TestCase):
    def test_build_then_scan_roundtrip(self):
        files = [('war3map.w3e', b'W3E!' + b'\x01' * 100),
                 ('war3map.j', b'function main takes nothing returns '
                               b'nothing\nendfunction\n' * 20),
                 ('textures/tex.blp', os.urandom(5000))]
        raw = build_mpq(files)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'built.mpq')
            with open(path, 'wb') as f:
                f.write(raw)
            entries = scan_archive(path, listfile=['textures/tex.blp'])
        ok = {e['name']: e for e in entries if e['status'] == 'ok'}
        for name, data in files:
            self.assertIn(name, ok, "%s missing" % name)
            self.assertEqual(ok[name]['sha256'],
                             __import__('hashlib').sha256(data).hexdigest(),
                             "%s content mismatch" % name)

    def test_rebuild_protected_map(self):
        # Build a "protected" synth: fallback script + no authoring files.
        stub = (b"// Disabled Single Player\nfunction main takes nothing "
                b"returns nothing\ncall EndGame(true)\nendfunction\n")
        real = b"function main takes nothing returns nothing\n" * 30
        files = [dict(name='war3map.j', data=stub,
                      flags=gen_synth.F_EXISTS),
                 dict(name='Scripts\\war3map.j', data=real,
                      flags=gen_synth.F_EXISTS)]
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'prot.w3x')
            with open(src, 'wb') as f:
                f.write(gen_synth.build_w3x(gen_synth.build_archive(files)))
            out = os.path.join(tmp, 'fixed.w3x')
            names = rebuild_map(src, out)
            # Canonical rename applied
            self.assertIn('war3map.j', names)
            self.assertNotIn('war3map_script.j', names)
            # Stub authoring files injected + real listfile
            self.assertIn('war3map.wtg', names)
            self.assertIn('war3map.wct', names)
            self.assertIn('(listfile)', names)
            # Re-open rebuilt archive: script recovered, unencrypted
            entries = scan_archive(out)
            by = {e['name']: e for e in entries if e['status'] == 'ok'}
            self.assertEqual(by['war3map.j']['size'], len(real))
            self.assertNotIn('Scripts\\war3map.j', by)


class TestListfileImport(unittest.TestCase):
    def test_external_listfile_names(self):
        files = [dict(name='custom/fancy.file', data=b'X' * 300,
                      flags=gen_synth.F_EXISTS)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'a.mpq')
            with open(path, 'wb') as f:
                f.write(gen_synth.build_archive(files))
            self.assertNotIn('custom/fancy.file',
                             [e['name'] for e in scan_archive(path)])
            lf = os.path.join(tmp, 'list.txt')
            with open(lf, 'w') as f:
                f.write('custom/fancy.file\n')
            entries = scan_archive(path, listfile=['custom/fancy.file'])
            self.assertIn('custom/fancy.file',
                          [e['name'] for e in entries if e['status'] == 'ok'])
            self.assertEqual(entries[0]['size'], 300)
            self.assertEqual(entries[0]['data'], b'X' * 300)


if __name__ == '__main__':
    unittest.main()
