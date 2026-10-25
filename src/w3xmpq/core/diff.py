#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.diff — compare two archives by recovered content.

Since MPQ block names are often unrecoverable, diffing is content-based:
files are matched by their SHA-256, so `diff` reports truly identical
content regardless of naming. Unrecovered (FAILED) files are reported
per archive separately.
"""

import os
from collections import Counter

from .extract import scan_archive


def diff_archives(path_a, path_b):
    """Compare the recovered content of two archives.

    Files are matched by SHA-256 as a multiset (multiple files may share
    identical content). Returns a dict with `common`, `added`, `removed`
    (entry dicts, no data) and per-archive metadata + failure counts.
    """
    scans = []
    for p in (path_a, path_b):
        entries = scan_archive(p)
        meta = dict(path=os.path.abspath(p),
                    blocks=len(entries),
                    ok=sum(1 for e in entries if e['status'] == 'ok'),
                    failed=sum(1 for e in entries if e['status'] == 'FAILED'))
        scans.append((entries, meta))

    (ea, meta_a), (eb, meta_b) = scans
    ca = Counter(e['sha256'] for e in ea if e['status'] == 'ok')
    cb = Counter(e['sha256'] for e in eb if e['status'] == 'ok')

    common = sum((ca & cb).values())
    removed_left = ca - cb
    added_left = cb - ca

    def _collect(entries, left):
        out = []
        for e in entries:
            if e['status'] != 'ok':
                continue
            if left.get(e['sha256'], 0) > 0:
                left[e['sha256']] -= 1
                out.append({k: v for k, v in e.items() if k != 'data'})
        return out

    added = _collect(eb, added_left)
    removed = _collect(ea, removed_left)

    return dict(common=common,
                added=added,
                removed=removed,
                meta_a=meta_a,
                meta_b=meta_b)
