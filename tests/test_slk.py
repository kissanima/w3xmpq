#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests: SLK tables and WorldEditStrings (core.slk)."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'src')))

from w3xmpq.core.slk import (METADATA_FILES, SlkError,  # noqa: E402
                             load_field_names, load_westrings, read_slk)

SLK = '''ID;PWXL;N;E
B;X3;Y3;D0
C;X1;Y1;K"ID"
C;X2;K"field"
C;X3;K"displayName"
C;X1;Y2;K"aran"
C;X2;K"Cast Range"
C;X3;K"WESTRING_AEVAL_ARAN"
C;X1;Y3;K"anam"
C;X2;K"Name"
C;X3;K"WESTRING_AEVAL_ANAM"
E
'''

STRINGS = '''[WorldEditStrings]
// a comment
WESTRING_AEVAL_ARAN=Cast Range
WESTRING_AEVAL_ANAM="Name"
WESTRING_UNUSED="quoted ""inner"" quotes"
'''


class TestReadSlk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "AbilityMetaData.slk")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(SLK)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_header_and_rows(self):
        rows = read_slk(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(list(rows[0].keys()), ["ID", "field", "displayName"])

    def test_values(self):
        rows = read_slk(self.path)
        self.assertEqual(rows[0]["ID"], "aran")
        self.assertEqual(rows[0]["field"], "Cast Range")
        self.assertEqual(rows[1]["ID"], "anam")

    def test_missing_file(self):
        with self.assertRaises(SlkError):
            read_slk(os.path.join(self.tmp, "nope.slk"))


class TestLoadWestrings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "WorldEditStrings.txt")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(STRINGS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parses_pairs(self):
        strings = load_westrings(self.path)
        self.assertEqual(strings["WESTRING_AEVAL_ARAN"], "Cast Range")
        self.assertEqual(strings["WESTRING_AEVAL_ANAM"], "Name")

    def test_strips_quotes(self):
        strings = load_westrings(self.path)
        self.assertEqual(strings["WESTRING_UNUSED"], 'quoted "inner" quotes')

    def test_missing_file_is_empty(self):
        self.assertEqual(load_westrings(os.path.join(self.tmp, "no.txt")), {})


class TestLoadFieldNames(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        units = os.path.join(self.root, "Units")
        os.makedirs(units)
        with open(os.path.join(units, "AbilityMetaData.slk"), "w",
                  encoding="utf-8") as fh:
            fh.write(SLK)
        self.strings = {"WESTRING_AEVAL_ARAN": "Cast Range",
                        "WESTRING_AEVAL_ANAM": "Name"}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_resolves_display_names(self):
        names = load_field_names(self.root, "w3a", strings=self.strings)
        self.assertEqual(names["aran"], "Cast Range")
        self.assertEqual(names["anam"], "Name")

    def test_falls_back_to_field_column(self):
        names = load_field_names(self.root, "w3a")
        self.assertEqual(names["aran"], "Cast Range")

    def test_unresolved_key_falls_back_to_field(self):
        names = load_field_names(self.root, "w3a", strings={})
        self.assertEqual(names["aran"], "Cast Range")

    def test_unknown_kind_is_empty(self):
        self.assertEqual(load_field_names(self.root, "w3i"), {})

    def test_every_kind_has_a_metadata_file(self):
        for kind in ("w3u", "w3t", "w3a", "w3b", "w3d", "w3q", "w3h"):
            self.assertIn(kind, METADATA_FILES)
            self.assertTrue(METADATA_FILES[kind])


if __name__ == "__main__":
    unittest.main()
