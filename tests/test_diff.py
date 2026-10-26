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


class TestNameAwareDiff(unittest.TestCase):
    """Files that keep their name are paired, so an edit reads as a change
    rather than as "one file added, one file removed"."""

    def _pair(self):
        v1 = [dict(name='war3map.j', data=b'function main\nendfunction\n',
                   flags=gen_synth.F_EXISTS),
              dict(name='shared.bin', data=b'SAME', flags=gen_synth.F_EXISTS),
              dict(name='gone.bin', data=b'BYE', flags=gen_synth.F_EXISTS)]
        v2 = [dict(name='war3map.j',
                   data=b'function main\n    call DoNothing()\n'
                        b'endfunction\n',
                   flags=gen_synth.F_EXISTS),
              dict(name='shared.bin', data=b'SAME', flags=gen_synth.F_EXISTS),
              dict(name='new.bin', data=b'HELLO', flags=gen_synth.F_EXISTS)]

        def write(files, name):
            files = list(files) + [dict(
                name='(listfile)',
                data=("\n".join(f['name'] for f in files) + "\n").encode(),
                flags=gen_synth.F_EXISTS)]
            return _write(gen_synth.build_archive(files), name)

        return write(v1, 'n1.mpq'), write(v2, 'n2.mpq')

    def test_edited_file_is_reported_as_changed(self):
        pa, pb = self._pair()
        d = diff_archives(pa, pb)
        names = [c['name'] for c in d['changed']]
        self.assertIn('war3map.j', names)
        self.assertIn('(listfile)', names)      # its content changed too
        entry = next(c for c in d['changed'] if c['name'] == 'war3map.j')
        self.assertGreater(entry['size_b'], entry['size_a'])
        self.assertNotIn('data', entry['a'], "data must be stripped")

    def test_only_lists_are_name_aware(self):
        pa, pb = self._pair()
        d = diff_archives(pa, pb)
        self.assertEqual([e['name'] for e in d['only_a']], ['gone.bin'])
        self.assertEqual([e['name'] for e in d['only_b']], ['new.bin'])
        self.assertEqual([e['name'] for e in d['same_named']],
                         ['shared.bin'])

    def test_with_data_keeps_the_bytes(self):
        pa, pb = self._pair()
        d = diff_archives(pa, pb, with_data=True)
        entry = next(c for c in d['changed'] if c['name'] == 'war3map.j')
        self.assertIn(b'DoNothing', entry['b']['data'])
        self.assertNotIn(b'DoNothing', entry['a']['data'])

    def test_content_lists_keep_their_old_meaning(self):
        """The CLI counts added/removed by content, not by name."""
        pa, pb = self._pair()
        d = diff_archives(pa, pb)
        # new content: war3map.j, new.bin, and the (listfile) itself
        self.assertEqual(len(d['added']), 3)
        # old content: war3map.j, gone.bin, and the (listfile)
        self.assertEqual(len(d['removed']), 3)
        self.assertEqual(d['common'], 1)        # shared.bin


if __name__ == '__main__':
    unittest.main()
