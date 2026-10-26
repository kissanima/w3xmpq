#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests: object-data decoding (core.objectdata)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'src')))

from w3xmpq.core.objectdata import (LEVELED_KINDS, ObjectDataError,  # noqa: E402
                                    parse_object_data)

ZERO = "\x00\x00\x00\x00"


def _mod(mod_id, type_code, value, level=0, column=0, object_id=ZERO):
    """One modification record. level/column are only emitted when leveled."""
    return (mod_id, type_code, level, column, value, object_id)


def _encode_object(obj, leveled):
    original, custom, mods = obj
    out = original.encode("latin-1") + custom.encode("latin-1")
    out += struct.pack("<I", len(mods))
    for mod_id, type_code, level, column, value, object_id in mods:
        out += mod_id.encode("latin-1")
        out += struct.pack("<I", type_code)
        if leveled:
            out += struct.pack("<II", level, column)
        if type_code == 0:
            out += struct.pack("<i", value)
        elif type_code in (1, 2):
            out += struct.pack("<f", value)
        else:
            out += value.encode("utf-8") + b"\x00"
        out += object_id.encode("latin-1")
    return out


def build(original, custom, leveled, version=2):
    out = struct.pack("<I", version)
    out += struct.pack("<I", len(original))
    out += b"".join(_encode_object(o, leveled) for o in original)
    if version >= 2:
        out += struct.pack("<I", len(custom))
        out += b"".join(_encode_object(o, leveled) for o in custom)
    return out


class TestLeveledKind(unittest.TestCase):
    def setUp(self):
        self.blob = build(
            [("A000", ZERO, [
                _mod("aran", 2, 9999.0, level=5),
                _mod("amcs", 0, 0, level=5),
                _mod("atar", 3, "air,ground", level=5),
                _mod("Htb1", 2, 12.5, level=4, column=1),
            ])],
            [("A001", "A00Z", [_mod("anam", 3, "Custom")])],
            leveled=True)
        self.od = parse_object_data(self.blob, kind="w3a")

    def test_counts(self):
        self.assertEqual(len(self.od.original), 1)
        self.assertEqual(len(self.od.custom), 1)
        self.assertEqual(self.od.modification_count, 5)

    def test_complete(self):
        self.assertTrue(self.od.complete)
        self.assertEqual(self.od.trailing, 0)

    def test_level_and_column_present(self):
        mods = self.od.original[0]["mods"]
        self.assertEqual(mods[0]["level"], 5)
        self.assertEqual(mods[3]["level"], 4)
        self.assertEqual(mods[3]["column"], 1)

    def test_values(self):
        mods = self.od.original[0]["mods"]
        self.assertAlmostEqual(mods[0]["value"], 9999.0)
        self.assertEqual(mods[1]["value"], 0)
        self.assertEqual(mods[2]["value"], "air,ground")
        self.assertAlmostEqual(mods[3]["value"], 12.5)

    def test_type_names(self):
        mods = self.od.original[0]["mods"]
        self.assertEqual([m["type"] for m in mods],
                         ["unreal", "int", "string", "unreal"])

    def test_zero_ids_become_none(self):
        self.assertIsNone(self.od.original[0]["custom_id"])
        self.assertIsNone(self.od.original[0]["mods"][0]["object_id"])

    def test_custom_table_carries_object_id(self):
        custom = self.od.custom[0]
        self.assertEqual(custom["original_id"], "A001")
        self.assertEqual(custom["custom_id"], "A00Z")


class TestNonLeveledKind(unittest.TestCase):
    def test_no_level_or_column(self):
        blob = build([("h000", ZERO, [_mod("uhpm", 0, 550),
                                      _mod("unam", 3, "Footman")])],
                     [], leveled=False)
        od = parse_object_data(blob, kind="w3u")
        self.assertTrue(od.complete)
        mods = od.original[0]["mods"]
        self.assertIsNone(mods[0]["level"])
        self.assertIsNone(mods[0]["column"])
        self.assertEqual(mods[0]["value"], 550)
        self.assertEqual(mods[1]["value"], "Footman")

    def test_leveled_bytes_read_as_non_leveled_desync(self):
        """The 8 extra bytes per mod must not silently parse as valid data."""
        blob = build([("A000", ZERO, [_mod("aran", 2, 9999.0, level=5)])],
                     [], leveled=True)
        with self.assertRaises(ObjectDataError):
            parse_object_data(blob, kind="w3u")

    def test_leveled_kinds_are_the_documented_set(self):
        self.assertEqual(LEVELED_KINDS, frozenset(("w3a", "w3d", "w3q")))


class TestVersionOne(unittest.TestCase):
    def test_single_table_only(self):
        blob = build([("h000", ZERO, [_mod("uhpm", 0, 100)])], [],
                     leveled=False, version=1)
        od = parse_object_data(blob, kind="w3u")
        self.assertEqual(od.version, 1)
        self.assertEqual(od.custom, [])
        self.assertTrue(od.complete)


class TestKindInference(unittest.TestCase):
    def test_from_plain_name(self):
        blob = build([("h000", ZERO, [])], [], leveled=False)
        self.assertEqual(parse_object_data(blob, name="war3map.w3u").kind, "w3u")

    def test_from_windows_path(self):
        blob = build([("h000", ZERO, [])], [], leveled=False)
        od = parse_object_data(blob, name=r"Units\war3map.w3u")
        self.assertEqual(od.kind, "w3u")

    def test_from_skin_variant(self):
        blob = build([("h000", ZERO, [])], [], leveled=False)
        od = parse_object_data(blob, name="war3mapSkin.w3u")
        self.assertEqual(od.kind, "w3u")

    def test_unknown_kind_rejected(self):
        blob = build([("h000", ZERO, [])], [], leveled=False)
        with self.assertRaises(ObjectDataError):
            parse_object_data(blob, name="war3map.w3i")


class TestErrors(unittest.TestCase):
    def test_empty(self):
        with self.assertRaises(ObjectDataError):
            parse_object_data(b"", kind="w3a")

    def test_bad_version(self):
        with self.assertRaises(ObjectDataError):
            parse_object_data(struct.pack("<II", 7, 0), kind="w3a")

    def test_truncated(self):
        blob = build([("A000", ZERO, [_mod("anam", 3, "Long name here")])],
                     [], leveled=True)
        with self.assertRaises(ObjectDataError):
            parse_object_data(blob[:-6], kind="w3a")

    def test_unknown_value_type(self):
        blob = (struct.pack("<III", 2, 1, 1) + b"a000" + b"\x00" * 4
                + struct.pack("<I", 1) + b"anam" + struct.pack("<I", 9))
        with self.assertRaises(ObjectDataError):
            parse_object_data(blob, kind="w3u")

    def test_implausible_object_count(self):
        blob = struct.pack("<II", 2, 99999999)
        with self.assertRaises(ObjectDataError):
            parse_object_data(blob, kind="w3u")


class TestFind(unittest.TestCase):
    def test_find_by_original_and_custom(self):
        blob = build([("A000", ZERO, [])], [("A001", "A00Z", [])],
                     leveled=True)
        od = parse_object_data(blob, kind="w3a")
        self.assertEqual(len(od.find("A000")), 1)
        self.assertEqual(len(od.find("A001")), 1)
        self.assertEqual(len(od.find("A00Z")), 1)
        self.assertEqual(od.find("ZZZZ"), [])


if __name__ == "__main__":
    unittest.main()
