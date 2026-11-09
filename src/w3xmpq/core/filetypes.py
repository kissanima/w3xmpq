# -*- coding: utf-8 -*-
"""Content-based file type detection.

Protected Warcraft III maps deliberately destroy the archive's listfile,
so a block's *name* is often a guess (``block_0123``) or missing entirely.
The extension is therefore no longer a reliable signal — the bytes are.

This module is pure stdlib so both the CLI/core (naming files it extracts)
and the GUI (filter chips, preview header, sort-by-type) can share one
answer.  :func:`detect` returns a :class:`FileKind`; magic bytes win over
the extension, and a printable-ratio heuristic wins over both when no
signature matches.
"""

from collections import namedtuple

__all__ = ["FileKind", "KINDS", "CATEGORIES", "detect", "sniff_ext",
           "display_name", "entry_name", "is_named", "is_encrypted",
           "is_failed", "category", "MAGICS", "EXT_KINDS"]

FileKind = namedtuple("FileKind", "key label ext")

#: The five families the filter chips understand.
CATEGORIES = ("script", "texture", "model", "sound", "other")

KINDS = {
    "script":  FileKind("script",  "Script",   ".j"),
    "text":    FileKind("text",    "Text",     ".txt"),
    "texture": FileKind("texture", "Texture",  ".blp"),
    "model":   FileKind("model",   "Model",    ".mdx"),
    "sound":   FileKind("sound",   "Sound",    ".wav"),
    "trigger": FileKind("trigger", "Triggers", ".wtg"),
    "object":  FileKind("object",  "Objects",  ".w3a"),
    "terrain": FileKind("terrain", "Terrain",  ".w3e"),
    "archive": FileKind("archive", "Archive",  ".zip"),
    "binary":  FileKind("binary",  "Binary",   ".bin"),
}

#: (prefix bytes, FileKind).  Order matters: longer/more specific first.
MAGICS = (
    (b"BLP1",         KINDS["texture"]),
    (b"BLP2",         KINDS["texture"]),
    (b"MDLX",         KINDS["model"]),
    (b"W3E!",         KINDS["terrain"]),
    (b"WTG!",         KINDS["trigger"]),
    (b"W3a!",         KINDS["object"]),
    (b"W3u!",         KINDS["object"]),
    (b"W3q!",         KINDS["object"]),
    (b"W3b!",         KINDS["object"]),
    (b"W3d!",         KINDS["object"]),
    (b"W3t!",         KINDS["object"]),
    (b"OggS",         FileKind("sound", "Sound", ".ogg")),
    (b"ID3",          FileKind("sound", "Sound", ".mp3")),
    (b"\xff\xfb",     FileKind("sound", "Sound", ".mp3")),
    (b"\xff\xf3",     FileKind("sound", "Sound", ".mp3")),
    (b"\xff\xf2",     FileKind("sound", "Sound", ".mp3")),
    (b"\x89PNG\r\n\x1a\n", FileKind("texture", "Texture", ".png")),
    (b"\xff\xd8\xff", FileKind("texture", "Texture", ".jpg")),
    (b"GIF87a",       FileKind("texture", "Texture", ".gif")),
    (b"GIF89a",       FileKind("texture", "Texture", ".gif")),
    (b"PK\x03\x04",   KINDS["archive"]),
    (b"HM3W",         FileKind("archive", "WC3 map", ".w3x")),
)

#: Extension -> FileKind, used when the bytes give no signature.
EXT_KINDS = {
    ".j": KINDS["script"], ".jass": KINDS["script"],
    ".txt": KINDS["text"], ".wts": KINDS["text"], ".ai": KINDS["script"],
    ".slk": KINDS["text"], ".ini": KINDS["text"], ".csv": KINDS["text"],
    ".json": KINDS["text"], ".xml": KINDS["text"], ".md": KINDS["text"],
    ".wct": KINDS["trigger"], ".wtg": KINDS["trigger"],
    ".blp": KINDS["texture"], ".tga": KINDS["texture"],
    ".png": KINDS["texture"], ".jpg": KINDS["texture"],
    ".jpeg": KINDS["texture"], ".dds": KINDS["texture"],
    ".gif": KINDS["texture"], ".bmp": KINDS["texture"],
    ".mdx": KINDS["model"], ".mdl": KINDS["model"], ".m3": KINDS["model"],
    ".wav": KINDS["sound"], ".mp3": KINDS["sound"],
    ".ogg": KINDS["sound"], ".flac": KINDS["sound"], ".mid": KINDS["sound"],
    ".w3e": KINDS["terrain"], ".wpm": KINDS["terrain"],
    ".w3a": KINDS["object"], ".w3u": KINDS["object"],
    ".w3q": KINDS["object"], ".w3b": KINDS["object"],
    ".w3t": KINDS["object"], ".w3d": KINDS["object"],
    ".doo": KINDS["object"], ".imp": KINDS["object"],
}

#: MPQ flag: the block's decryption key was derived from its name.
FLAG_ENCRYPTED = 0x00010000


def _kind_from_magic(data):
    for magic, kind in MAGICS:
        if data.startswith(magic):
            return kind
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return KINDS["sound"]
    return None


def _looks_like_text(data):
    if not data:
        return False
    sample = data[:512]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(sample) > 0.85


def detect(name=None, data=b""):
    """Return the :class:`FileKind` for a recovered block.

    `data` may be empty (e.g. a FAILED block); the extension still decides.
    """
    data = data or b""
    kind = _kind_from_magic(data)
    if kind is not None:
        return kind
    ext = _ext(name).lower()
    if ext in EXT_KINDS:
        return EXT_KINDS[ext]
    if _looks_like_text(data):
        head = data[:20000]
        if b"endfunction" in head or b"function " in head or \
                b"globals" in head:
            return KINDS["script"]
        return KINDS["text"]
    if ext:
        return FileKind("other", ext.lstrip(".").upper(), ext)
    return KINDS["binary"]


def _ext(name):
    if not name:
        return ""
    tail = name.replace("/", "\\").rsplit("\\", 1)[-1]
    dot = tail.rfind(".")
    return tail[dot:] if dot >= 0 else ""


def sniff_ext(data):
    """Best-guess extension for a nameless block (for extraction)."""
    return detect(None, data).ext


def is_named(entry):
    """True when the name came from the archive, not from a guess.

    ``scan_archive`` invents ``block_NNN`` / ``texture_NNN.blp`` names for
    blocks whose real name could not be recovered, and tags those entries
    with ``name_source`` = ``guess`` / ``unknown``.  A missing
    ``name_source`` (hand-built fixture entries) counts as a real name.
    """
    if not entry.get("name"):
        return False
    src = entry.get("name_source")
    return src is None or src in ("known", "listfile", "external")


def is_encrypted(entry):
    return bool(entry.get("flags", 0) & FLAG_ENCRYPTED)


def is_failed(entry):
    return entry.get("status") != "ok"


def display_name(entry):
    """A table label: real name, or ``‹texture› block_0123.blp``.

    The guessed type is shown even when the block is unnamed, so a
    protected map's file list is still useful to browse.
    """
    if is_named(entry):
        return entry["name"]
    kind = detect(entry.get("name"), entry.get("data") or b"")
    base = entry.get("name") or "block_%04d" % entry.get("block", 0)
    if base.lower().endswith(kind.ext.lower()):
        return "\u2039%s\u203a %s" % (kind.label.lower(), base)
    return "\u2039%s\u203a %s%s" % (kind.label.lower(), base, kind.ext)


def entry_name(entry):
    """A safe output filename for extraction (never empty, never a path)."""
    if entry.get("name"):
        return entry["name"]
    kind = detect(None, entry.get("data") or b"")
    return "%s_%04d%s" % (kind.key, entry.get("block", 0), kind.ext)


#: Extra families folded into a chip: a trigger database and a plain text
#: file both belong under "Scripts" for browsing purposes.
_CATEGORY_ALIAS = {
    "text": "script", "trigger": "script", "object": "script",
    "terrain": "other", "archive": "other", "binary": "other",
}


def category(entry):
    """Filter-chip family for an entry: one of :data:`CATEGORIES`."""
    kind = detect(entry.get("name"), entry.get("data") or b"")
    if kind.key in CATEGORIES:
        return kind.key
    return _CATEGORY_ALIAS.get(kind.key, "other")
