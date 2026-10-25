#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.batch — bulk extraction over a folder of archives.

Walks a directory for .w3x/.w3m/.mpq files and extracts each into its own
subdirectory, writing a global index.csv + index.json. Errors are logged
per archive and never stop the run.
"""

import csv
import json
import os
import re

from .extract import extract_archive

ARCHIVE_EXTS = ('.w3x', '.w3m', '.mpq')


def find_archives(root):
    """Return sorted paths of all archives under `root`."""
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(ARCHIVE_EXTS):
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def batch_extract(root, outdir, pattern=None):
    """Extract every archive under `root` into `outdir`.

    Returns the index records (also written as index.csv/index.json
    inside `outdir`).
    """
    rx = re.compile(pattern) if pattern else None
    paths = find_archives(root)
    os.makedirs(outdir, exist_ok=True)

    index = []
    used_stems = set()
    for n, path in enumerate(paths, 1):
        rel = os.path.relpath(path, root)
        stem = re.sub(r'[^A-Za-z0-9_.-]', '_',
                      os.path.splitext(rel)[0])
        candidate, k = stem, 1
        while candidate in used_stems:
            candidate = "%s.%d" % (stem, k)
            k += 1
        used_stems.add(candidate)
        dest = os.path.join(outdir, candidate)

        rec = dict(n=n, source=os.path.abspath(path), outdir=dest,
                   status='ok', ok=0, failed=0, error=None)
        try:
            manifest = extract_archive(path, dest, pattern=rx, verbose=False)
            rec['ok'] = sum(1 for m in manifest if m['status'] == 'ok')
            rec['failed'] = sum(1 for m in manifest
                                if m['status'] == 'FAILED')
            if rec['failed']:
                rec['status'] = 'partial'
        except Exception as e:
            rec['status'] = 'error'
            rec['error'] = str(e)
        index.append(rec)
        print("[%d/%d] %-14s %s" % (n, len(paths), rec['status'],
                                    os.path.basename(path)))

    with open(os.path.join(outdir, 'index.csv'), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['n', 'source', 'outdir', 'status',
                                          'ok', 'failed', 'error'])
        w.writeheader()
        w.writerows(index)
    with open(os.path.join(outdir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=1)
    return index
