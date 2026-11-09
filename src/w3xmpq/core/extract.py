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
from . import filetypes
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


def load_listfile(path):
    """Read an external listfile (one filename per line)."""
    names = []
    with open(path, 'rb') as f:
        for line in f.read().decode('utf-8', 'ignore').splitlines():
            line = line.strip()
            if line:
                names.append(line)
    return names


def _probe_known_names(arch, listfile=None):
    """Hash-probe known names -> block index.

    Returns (by_block, source) where source maps block index to how the
    name was found: 'known' (built-in WC3 name list), 'external' (supplied
    by the user via --listfile).
    """
    by_block = {}
    source = {}
    for name in KNOWN_NAMES:
        he = arch.get_hash_table_entry(name)
        if he is not None:
            by_block.setdefault(he.block_table_index, name)
            source.setdefault(he.block_table_index, "known")
    for name in (list(listfile) if listfile else []):
        he = arch.get_hash_table_entry(name)
        if he is not None:
            by_block.setdefault(he.block_table_index, name)
            source.setdefault(he.block_table_index, "external")
    return by_block, source


def _apply_internal_listfile(arch, by_block, source=None):
    """Recover real file names from the archive's own '(listfile)'.

    MPQs made by normal tools embed a '(listfile)' block listing every
    name. Probing those names recovers names that neither the built-in
    list nor content guessing can find — without it, non-WC3 files show
    up as 'block_NNN'. Purely additive: blocks already named keep their
    first (higher-priority) name.
    """
    lf_index = None
    for idx, name in by_block.items():
        if name == "(listfile)":
            lf_index = idx
            break
    if lf_index is None:
        return
    b = arch.block_table[lf_index]
    if not (b.flags & 0x80000000) or b.archived_size == 0:
        return
    try:
        fd = arch.read_block_data(b)
        data = extract_block(arch, b, fd, name="(listfile)")
    except Exception:
        return
    if not data:
        return
    for line in data.decode("utf-8", "ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            he = arch.get_hash_table_entry(line)
        except Exception:
            continue
        if he is not None:
            by_block.setdefault(he.block_table_index, line)
            if source is not None:
                source.setdefault(he.block_table_index, "listfile")


def scan_archive(path, listfile=None, progress=None, should_stop=None):
    """Decrypt every recoverable file in `path`.

    `listfile`: optional list of known filenames — their hashes are probed
    in addition to the built-in WC3 names (useful for non-WC3 archives).
    `progress`: optional callback invoked as progress(done, total) after
    every block — used by the GUI to show a progress bar.
    `should_stop`: optional callback; when it returns True the scan stops
    early and the entries recovered so far are returned.
    Returns a list of entry dicts:
      block, flags, size, archived_size, status ("ok"/"FAILED"),
      name, name_source, key_method, sha256, and `data` (bytes, "ok"
      entries only).
    The archive file handle is closed before returning.
    """
    arch = open_archive(path)
    by_block, source = _probe_known_names(arch, listfile=listfile)
    _apply_internal_listfile(arch, by_block, source)
    entries = []
    total = len(arch.block_table)
    done = 0
    try:
        for i, b in enumerate(arch.block_table):
            if not (b.flags & 0x80000000) or b.archived_size == 0:
                continue
            if should_stop is not None and should_stop():
                break
            fd = arch.read_block_data(b)
            probed = by_block.get(i)
            info = {}
            data = extract_block(arch, b, fd, name=probed, info=info)
            if data is None:
                entries.append(dict(block=i, name=None, size=0,
                                    archived_size=b.archived_size,
                                    flags=b.flags, status="FAILED",
                                    sha256=None,
                                    name_source=source.get(i, "unknown"),
                                    key_method=info.get("key_method")))
                continue
            if probed is not None:
                name = probed
                name_source = source.get(i, "known")
            elif data[:1] == b'\x00':
                name = "block_%03d" % i
                name_source = "unknown"
            else:
                name = guess_name(data, i)
                name_source = "guess" if name else "unknown"
            name = NAME_REMAP.get(name, name)
            entries.append(dict(block=i, name=name, size=len(data),
                                archived_size=b.archived_size,
                                flags=b.flags, status="ok",
                                sha256=hashlib.sha256(data).hexdigest(),
                                name_source=name_source,
                                key_method=info.get("key_method", "plain"),
                                data=data))
            done += 1
            if progress is not None:
                try:
                    progress(done, total)
                except Exception:
                    pass
    finally:
        arch.file.close()
    return entries


def extract_archive(path, outdir, pattern=None, verbose=True, listfile=None,
                    blocks=None, progress=None, should_stop=None):
    """Extract every recoverable file from `path` into `outdir`.

    `pattern` (regex, matched against resolved names) and `blocks` (an
    iterable of MPQ block indices) both limit extraction; the latter is
    what lets the GUI extract *unnamed* files, whose resolved name is
    empty and therefore cannot be matched by a regex.

    `progress` is an optional ``callback(done, total)`` forwarded to
    `scan_archive`, which emits it once per decrypted block with the real
    block-table total (the expensive part of an extraction).  Returns the
    manifest (list of dicts; same fields as scan_archive entries minus
    `data`) and writes manifest.json.
    """
    rx = re.compile(pattern) if pattern else None
    wanted = set(blocks) if blocks is not None else None
    os.makedirs(outdir, exist_ok=True)

    got, failed = 0, 0
    used_names = set()
    manifest = []
    entries = scan_archive(path, listfile=listfile, progress=progress,
                           should_stop=should_stop)
    for e in entries:
        if should_stop is not None and should_stop():
            break
        rec = {k: v for k, v in e.items() if k != 'data'}
        skip_by_name = rx is not None and not rx.search(e['name'] or '')
        skip_by_block = wanted is not None and e['block'] not in wanted
        if e['status'] != 'ok' or skip_by_name or skip_by_block:
            if e['status'] != 'ok':
                failed += 1
            manifest.append(rec)
            continue
        # A nameless block still needs a real output filename.  The type
        # detector supplies a sensible extension from the magic bytes.
        name = filetypes.entry_name(e)
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
        rec['extracted'] = True      # distinguish from pattern-skipped
        got += 1
        manifest.append(rec)
        if verbose:
            print("  [%3d] %-20s %8d bytes (was %8d)"
                  % (e['block'], candidate, e['size'], e['archived_size']))

    print("\nExtracted %d files, %d failed -> %s" % (got, failed, outdir))
    with open(os.path.join(outdir, "manifest.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1)
    return manifest
