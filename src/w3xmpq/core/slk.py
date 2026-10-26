# -*- coding: utf-8 -*-
"""Minimal reader for Warcraft III's SYLK-style ``.slk`` data tables.

The game stores its object definitions as SLK files (``Units\\UnitData.slk``,
``Units\\AbilityMetaData.slk``, ...). The dialect is a cut-down SYLK::

    ID;PWXL;N;E
    B;X26;Y751;D0
    C;X1;Y1;K"ID"
    C;X2;K"field"
    ...
    E

Only the ``C`` (cell) records carry data. ``X`` is the 1-based column, ``Y``
the 1-based row, and ``K`` the constant value — either a bare number or a
double-quoted string in which ``""`` means a literal quote. ``E`` records hold
expressions and are ignored. A ``C`` record with no ``Y`` continues the
previous row.
"""

import os

__all__ = ["SlkError", "read_slk", "load_field_names", "load_westrings",
           "METADATA_FILES"]

#: Object-data kind -> the metadata table that names its fields.
METADATA_FILES = {
    "w3u": ("Units/UnitMetaData.slk",),
    "w3t": ("Units/UnitMetaData.slk",),
    "w3a": ("Units/AbilityMetaData.slk",),
    "w3b": ("Units/DestructableMetaData.slk",),
    "w3d": ("Doodads/DoodadMetaData.slk",),
    "w3q": ("Units/UpgradeMetaData.slk", "Units/UpgradeEffectMetaData.slk"),
    "w3h": ("Units/AbilityBuffMetaData.slk",),
}


class SlkError(ValueError):
    """The file is not a readable SLK table."""


def _parse_cell_value(raw):
    """Turn the text after ``K`` into a str or float."""
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            raise SlkError("unterminated string %r" % raw)
        return raw[1:-1].replace('""', '"')
    if raw == "":
        return ""
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def read_slk(path):
    """Read an SLK file into a list of row dicts keyed by the header row."""
    if not os.path.exists(path):
        raise SlkError("no such file: %s" % path)
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")

    cells = {}
    row = 0
    for line in text.splitlines():
        if not line or line[0] != "C":
            continue
        col = None
        value = ""
        has_y = False
        for part in line.split(";"):
            if not part:
                continue
            tag, body = part[0], part[1:]
            if tag == "X":
                try:
                    col = int(body)
                except ValueError:
                    col = None
            elif tag == "Y":
                try:
                    row = int(body)
                    has_y = True
                except ValueError:
                    pass
            elif tag == "K":
                value = body
        if col is None:
            continue
        if not has_y and row == 0:
            continue
        try:
            cells[(row, col)] = _parse_cell_value(value)
        except SlkError:
            continue

    if not cells:
        raise SlkError("no cell records in %s" % path)

    max_row = max(r for r, _ in cells)
    max_col = max(c for _, c in cells)
    header = [cells.get((1, c), "") for c in range(1, max_col + 1)]
    while header and header[-1] == "":
        header.pop()

    rows = []
    for r in range(2, max_row + 1):
        values = [cells.get((r, c), "") for c in range(1, len(header) + 1)]
        if all(v == "" for v in values):
            continue
        rows.append(dict(zip(header, values)))
    return rows


def load_westrings(path):
    """Read ``UI/WorldEditStrings.txt`` into a ``{key: text}`` map.

    The metadata tables store display names as localisation keys
    (``WESTRING_AEVAL_ARAN``); this resolves them to real editor labels such as
    ``Cast Range``.
    """
    strings = {}
    if not os.path.exists(path):
        return strings
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line.startswith("//"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('""', '"')
        strings[key.strip()] = value
    return strings


def load_field_names(slk_root, kind, strings=None):
    """Map object-data modification ids to human labels for one kind.

    ``slk_root`` is a directory containing ``Units/`` and ``Doodads/`` — i.e.
    the layout produced by extracting those folders from ``War3x.mpq``.
    ``strings`` is an optional :func:`load_westrings` map used to turn the
    metadata's ``WESTRING_*`` display keys into readable text.
    """
    names = {}
    for rel in METADATA_FILES.get(kind, ()):
        path = os.path.join(slk_root, rel.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        for row in read_slk(path):
            fourcc = row.get("ID")
            if not isinstance(fourcc, str) or len(fourcc) != 4:
                continue
            label = ""
            display = row.get("displayName") or ""
            if strings and isinstance(display, str):
                label = strings.get(display, "")
            if not label:
                field = row.get("field") or ""
                label = field if isinstance(field, str) else ""
            if label:
                names.setdefault(fourcc, label)
    return names
