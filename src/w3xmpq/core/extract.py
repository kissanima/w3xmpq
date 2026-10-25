#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.extract — archive scanning and extraction.

Opens .w3x/.w3m maps (skipping the 512-byte user-data header) and plain
.mpq/.MPQ archives alike — no temp files, the embedded MPQ is read from a
BytesIO. `scan_archive` is the single decryption pass every consumer
(extract / list / diff / batch / GUI) shares.

Read-only guarantee: the source path is only ever opened 'rb'.
"""

import hashlib
import io
import json
import os
import re

from .mpq import MPQArchive
from .names import KNOWN_NAMES, NAME_REMAP, guess_name
from .sectors import extract_block

W3X_MAGICS = (b'HM3W',)                 # Warcraft III map user-data header
MPQ_MAGICS = (b'MPQ\x1a', b'MPQ\x1b')   # bare MPQ (also wrapped 'MPQ\x1b')
W3X_HEADER_SIZE = 512


def open_archive(path):
    """Open a .w3x/.w3m map or a plain .mpq archive. Returns MPQArchive.

    The caller is responsible for closing `arch.file` when done
    (scan_archive does it automatically).
    """
    with open(path, 'rb') as f:
        magic = f.read(4)
    if magic in W3X_MAGICS:
        with open(path, 'rb') as f:
            f.seek(W3X_HEADER_SIZE)
            data = f.read()
        return MPQArchive(io.BytesIO(data))
    if magic in MPQ_MAGICS:
        return MPQArchive(path)
    raise ValueError("%s: not a WC3 map (.w3x/.w3m) or MPQ archive "
                     "(magic %r)" % (path, magic))


def _probe_known_names(arch):
    """Hash-probe KNOWN_NAMES -> block index."""
    by_block = {}
    for name in KNOWN_NAMES:
        he = arch.get_hash_table_entry(name)
        if he is not None:
            by_block[he.block_table_index] = name
    return by_block


def scan_archive(path):
    """Decrypt every recoverable file in `path`.

    Returns a list of entry dicts:
      block, flags, size, archived_size, status ("ok"/"FAILED"),
      name, sha256, and `data` (bytes, "ok" entries only).
    The archive file handle is closed before returning.
    """
    arch = open_archive(path)
    by_block = _probe_known_names(arch)
    entries = []
    try:
        for i, b in enumerate(arch.block_table):
            if not (b.flags & 0x80000000) or b.archived_size == 0:
                continue
            fd = arch.read_block_data(b)
            probed = by_block.get(i)
            data = extract_block(arch, b, fd, name=probed)
            if data is None:
                entries.append(dict(block=i, name=None, size=0,
                                    archived_size=b.archived_size,
                                    flags=b.flags, status="FAILED",
                                    sha256=None))
                continue
            if probed is not None:
                name = probed
            elif data[:1] == b'\x00':
                name = "block_%03d" % i
            else:
                name = guess_name(data, i)
            name = NAME_REMAP.get(name, name)
            entries.append(dict(block=i, name=name, size=len(data),
                                archived_size=b.archived_size,
                                flags=b.flags, status="ok",
                                sha256=hashlib.sha256(data).hexdigest(),
                                data=data))
    finally:
        arch.file.close()
    return entries


def extract_archive(path, outdir, pattern=None, verbose=True):
    """Extract every recoverable file from `path` into `outdir`.

    `pattern` (regex, matched against resolved names) limits extraction.
    Returns the manifest (list of dicts; same fields as scan_archive
    entries minus `data`), and writes manifest.json into `outdir`.
    """
    rx = re.compile(pattern) if pattern else None
    os.makedirs(outdir, exist_ok=True)

    got, failed = 0, 0
    used_names = set()
    manifest = []
    for e in scan_archive(path):
        rec = {k: v for k, v in e.items() if k != 'data'}
        if e['status'] != 'ok' or (rx and not rx.search(e['name'] or '')):
            if e['status'] != 'ok':
                failed += 1
            manifest.append(rec)
            continue
        name = e['name']
        base, ext = os.path.splitext(name)
        candidate = name
        n = 1
        while candidate in used_names:
            candidate = "%s.%d%s" % (base, n, ext)
            n += 1
        used_names.add(candidate)

        out_path = os.path.join(outdir, candidate.replace('\\', os.sep))
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, 'wb') as f:
            f.write(e['data'])

        rec['name'] = candidate
        got += 1
        manifest.append(rec)
        if verbose:
            print("  [%3d] %-20s %8d bytes (was %8d)"
                  % (e['block'], candidate, e['size'], e['archived_size']))

    print("\nExtracted %d files, %d failed -> %s" % (got, failed, outdir))
    with open(os.path.join(outdir, "manifest.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1)
    return manifest
