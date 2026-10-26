# -*- coding: utf-8 -*-
"""Warcraft III object-data files.

Covers ``war3map.w3u`` (units), ``.w3t`` (items), ``.w3a`` (abilities),
``.w3b`` (destructables), ``.w3d`` (doodads), ``.w3q`` (upgrades) and
``.w3h`` (buffs). These are the map's overrides on top of the base SLK
tables: each record says "take object X and change these fields".

Layout (version 2, per the community specification)::

    int version
    Table original
    Table custom

    Table:
        int count
        count x Object:
            char(4) original id
            char(4) custom id
            int     modification count
            modification count x Modification:
                char(4) modification id
                int     value type        (0 int, 1 real, 2 unreal, 3 string)
                int     level             } doodads, abilities and upgrades
                int     column            } only
                value                     (int / float / zero-terminated string)
                char(4) object id         (zero when the entry is in the
                                           original table)

The ``level``/``column`` pair is the trap in this format: it is present for
doodads, abilities and upgrades but **absent** for units, items, destructables
and buffs. Assuming one layout for every kind silently desynchronises the
stream — the reader keeps going and produces plausible-looking garbage.
"""

import struct

__all__ = ["ObjectDataError", "ObjectData", "parse_object_data", "KIND_LABELS"]

KIND_LABELS = {
    "w3u": "units",
    "w3t": "items",
    "w3a": "abilities",
    "w3b": "destructables",
    "w3d": "doodads",
    "w3q": "upgrades",
    "w3h": "buffs",
}

#: Kinds whose modifications carry the level/column pair.
LEVELED_KINDS = frozenset(("w3a", "w3d", "w3q"))

VALUE_TYPES = {0: "int", 1: "real", 2: "unreal", 3: "string"}

_ZERO_ID = "\x00\x00\x00\x00"


class ObjectDataError(ValueError):
    """The file is not valid object data."""


class _Cursor:
    """Bounds-checked little-endian reader."""

    __slots__ = ("data", "off")

    def __init__(self, data):
        self.data = data
        self.off = 0

    def left(self):
        return len(self.data) - self.off

    def _take(self, n):
        if self.off + n > len(self.data):
            raise ObjectDataError(
                "truncated at offset 0x%x: wanted %d byte(s), %d left"
                % (self.off, n, self.left()))
        chunk = self.data[self.off:self.off + n]
        self.off += n
        return chunk

    def u32(self):
        return struct.unpack("<I", self._take(4))[0]

    def i32(self):
        return struct.unpack("<i", self._take(4))[0]

    def f32(self):
        return struct.unpack("<f", self._take(4))[0]

    def fourcc(self):
        return self._take(4).decode("latin-1")

    def cstr(self):
        end = self.data.find(b"\x00", self.off)
        if end < 0:
            raise ObjectDataError(
                "unterminated string at offset 0x%x" % self.off)
        raw = self.data[self.off:end]
        self.off = end + 1
        return raw.decode("utf-8", "replace")


def _clean_id(fourcc):
    """All-zero ids mean 'no id', not a string of NULs."""
    return None if fourcc == _ZERO_ID else fourcc


def _read_modification(cur, leveled):
    mod_id = cur.fourcc()
    type_code = cur.u32()
    type_name = VALUE_TYPES.get(type_code)
    if type_name is None:
        raise ObjectDataError(
            "unknown value type %d for modification %r at offset 0x%x"
            % (type_code, mod_id, cur.off - 4))

    level = column = None
    if leveled:
        level = cur.u32()
        column = cur.u32()

    if type_code == 0:
        value = cur.i32()
    elif type_code in (1, 2):
        value = cur.f32()
    else:
        value = cur.cstr()

    object_id = _clean_id(cur.fourcc())
    return {
        "id": mod_id,
        "type": type_name,
        "level": level,
        "column": column,
        "value": value,
        "object_id": object_id,
    }


def _read_table(cur, leveled):
    count = cur.u32()
    if count > 1000000:
        raise ObjectDataError(
            "implausible object count %d at offset 0x%x" % (count, cur.off - 4))
    objects = []
    for _ in range(count):
        original_id = cur.fourcc()
        custom_id = cur.fourcc()
        mod_count = cur.u32()
        if mod_count > 100000:
            raise ObjectDataError(
                "implausible modification count %d for %r at offset 0x%x"
                % (mod_count, original_id, cur.off - 4))
        mods = [_read_modification(cur, leveled) for _ in range(mod_count)]
        objects.append({
            "original_id": original_id,
            "custom_id": _clean_id(custom_id),
            "mods": mods,
        })
    return objects


class ObjectData:
    """A parsed object-data file."""

    def __init__(self, kind, version, original, custom, trailing):
        self.kind = kind
        self.version = version
        self.original = original
        self.custom = custom
        self.trailing = trailing

    @property
    def objects(self):
        """Every object, originals first, then custom ones."""
        return self.original + self.custom

    @property
    def modification_count(self):
        return sum(len(o["mods"]) for o in self.objects)

    @property
    def complete(self):
        """True when every declared record was read and nothing is left over."""
        return self.trailing == 0

    def verify(self):
        return {
            "kind": self.kind,
            "version": self.version,
            "original_objects": len(self.original),
            "custom_objects": len(self.custom),
            "modifications": self.modification_count,
            "trailing_bytes": self.trailing,
            "complete": self.complete,
        }

    def find(self, object_id):
        """Objects whose original or custom id matches (case-sensitive)."""
        return [o for o in self.objects
                if object_id in (o["original_id"], o["custom_id"])]


def _kind_from_name(name):
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.startswith("war3mapskin."):
        base = "war3map." + base.split(".", 1)[1]
    if "." in base:
        ext = base.rsplit(".", 1)[1]
        if ext in KIND_LABELS:
            return ext
    return None


def parse_object_data(data, kind=None, name=None):
    """Parse object-data bytes.

    ``kind`` is one of the ``KIND_LABELS`` keys; when omitted it is inferred
    from ``name`` (a path or filename such as ``war3map.w3a``).
    """
    if kind is None:
        kind = _kind_from_name(name)
    if kind not in KIND_LABELS:
        raise ObjectDataError(
            "unknown object-data kind %r — pass one of %s"
            % (kind, ", ".join(sorted(KIND_LABELS))))
    if not data:
        raise ObjectDataError("empty file")

    cur = _Cursor(data)
    version = cur.u32()
    if version not in (1, 2):
        raise ObjectDataError(
            "unsupported object-data version %d (expected 1 or 2)" % version)

    leveled = kind in LEVELED_KINDS
    original = _read_table(cur, leveled)
    custom = _read_table(cur, leveled) if version >= 2 else []
    return ObjectData(kind, version, original, custom, cur.left())
