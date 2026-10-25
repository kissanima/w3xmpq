#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 unit tests: header parser, deprotection report, safety scan."""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))

import gen_synth  # noqa: E402
from w3xmpq.core.w3x_header import parse_header  # noqa: E402
from w3xmpq.core.report import build_report  # noqa: E402
from w3xmpq.core.safety import scan_safety  # noqa: E402

SPECS = gen_synth.sample_file_set()

STUB = (b"// Disabled Single Player\nfunction main takes nothing returns "
        b"nothing\ncall EndGame(true)\nendfunction\n")
REAL_SCRIPT = (b"function main takes nothing returns nothing\n"
               b"endfunction\n") * 40
DECOY_LISTFILE = bytes(range(256)) * 2


def _write(raw, name):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, name)
    with open(path, 'wb') as f:
        f.write(raw)
    return path


class TestHeader(unittest.TestCase):
    def test_parse_roundtrip(self):
        mpq = gen_synth.build_archive(SPECS)
        path = _write(gen_synth.build_w3x(mpq), 'h.w3x')
        h = parse_header(path)
        self.assertEqual(h['name'], 'SynthMap')
        self.assertEqual(h['author'], 'SynthAuthor')
        self.assertEqual(h['description'], 'Synthetic test map')
        self.assertEqual(h['width'], 64)
        self.assertEqual(h['height'], 64)
        self.assertFalse(h['melee'])
        self.assertEqual(h['tileset_name'], 'Lordaeron Summer')
        self.assertEqual(h['build'], 6072)


def _mpq(files):
    return gen_synth.build_archive(files)


class TestReport(unittest.TestCase):
    def test_clean_map_no_findings(self):
        path = _write(_mpq(SPECS), 'clean.w3x')
        rep = build_report(path)
        titles = [f['title'] for f in rep['findings']]
        self.assertNotIn('Script moved to fallback path', titles)
        self.assertNotIn('Canonical script is an anti-tamper stub', titles)
        self.assertNotIn('Decoy (listfile)', titles)

    def test_protected_map_all_patterns(self):
        files = [
            # canonical script replaced by anti-tamper stub
            dict(name='war3map.j', data=STUB, flags=gen_synth.F_EXISTS),
            # real script at the fallback path
            dict(name='Scripts\\war3map.j', data=REAL_SCRIPT,
                 flags=gen_synth.F_EXISTS),
            # decoy binary listfile
            dict(name='(listfile)', data=DECOY_LISTFILE,
                 flags=gen_synth.F_EXISTS),
            # a data file so the map isn't empty
            dict(name='war3map.w3e', data=b'W3E!' + b'\x00' * 100,
                 flags=gen_synth.F_EXISTS),
        ]
        path = _write(_mpq(files), 'prot.w3x')
        rep = build_report(path)
        titles = [f['title'] for f in rep['findings']]
        self.assertIn('Canonical script is an anti-tamper stub', titles)
        self.assertIn('Authoring files missing (editor-hostile)', titles)
        self.assertIn('Decoy (listfile)', titles)
        # verdict must mention editor-openable impossibility
        self.assertIn('World Editor', rep['verdict'])
        # unknown-block analyzer: unnamed text block may appear
        self.assertIsInstance(rep['unknown'], list)

    def test_stub_without_fallback(self):
        files = [dict(name='war3map.j', data=STUB,
                      flags=gen_synth.F_EXISTS)]
        path = _write(_mpq(files), 'stub.w3x')
        rep = build_report(path)
        titles = [f['title'] for f in rep['findings']]
        self.assertIn('Canonical script is an anti-tamper stub', titles)


class TestSafety(unittest.TestCase):
    def test_suspicious_patterns_detected(self):
        script = (b"function main takes nothing returns nothing\n"
                  b"call Preload(\"backup.lua\")\n"
                  b"set p = GetPlayerName(Player(0))\n"
                  b"call EndGame(true)\n"
                  b"endfunction\n")
        files = [dict(name='war3map.j', data=script,
                      flags=gen_synth.F_EXISTS)]
        path = _write(_mpq(files), 'susp.w3x')
        res = scan_safety(path)
        labels = [f['label'] for f in res['findings']]
        self.assertIn('Preload file I/O', labels)
        self.assertIn('EndGame call', labels)
        self.assertIn('Player-name collection', labels)
        self.assertEqual(res['stats']['Preload'], 1)

    def test_clean_script(self):
        script = (b"function main takes nothing returns nothing\n"
                  b"endfunction\n")
        files = [dict(name='war3map.j', data=script,
                      flags=gen_synth.F_EXISTS)]
        path = _write(_mpq(files), 'ok.w3x')
        res = scan_safety(path)
        self.assertEqual(res['findings'], [])

    def test_no_script(self):
        files = [dict(name='war3map.w3e', data=b'W3E!' + b'\x00' * 10,
                      flags=gen_synth.F_EXISTS)]
        path = _write(_mpq(files), 'noscript.w3x')
        res = scan_safety(path)
        self.assertIsNone(res['script'])
        self.assertIn('note', res)


if __name__ == '__main__':
    unittest.main()
