#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.diff — compare two archives by recovered content.

Since MPQ block names are often unrecoverable, diffing has to work on
content: files are matched by their SHA-256, so `diff` reports truly
identical content regardless of naming.

Protected maps usually keep *some* names though, and a file that was
edited keeps its name while its bytes change. So there are two passes:

* **by name** — files present in both archives under the same recovered
  name: identical → ``same_named``, different bytes → ``changed`` (with
  both sides, so a viewer can show them next to each other);
* **by content** — everything else, as a SHA-256 multiset: ``added`` /
  ``removed`` / ``common``.

``added`` and ``removed`` keep their original content-based meaning (a
changed file appears in both, as its new and old content), which is what
the CLI reports; the name-aware ``changed`` / ``only_a`` / ``only_b``
lists are what the GUI shows. Unrecovered (FAILED) files are reported
per archive in the metadata.
"""

import os
from collections import Counter

from .extract import scan_archive


def _meta(path, entries):
    return dict(path=os.path.abspath(path),
                blocks=len(entries),
                ok=sum(1 for e in entries if e['status'] == 'ok'),
                failed=sum(1 for e in entries if e['status'] == 'FAILED'))


def _collect(entries, left, with_data):
    """Take entries whose hash still has a quota in `left`."""
    out = []
    for e in entries:
        if e['status'] != 'ok':
            continue
        if left.get(e['sha256'], 0) > 0:
            left[e['sha256']] -= 1
            out.append(dict(e) if with_data
                       else {k: v for k, v in e.items() if k != 'data'})
    return out


def diff_archives(path_a, path_b, with_data=False):
    """Compare the recovered content of two archives.

    Files are matched by SHA-256 as a multiset (multiple files may share
    identical content). Returns a dict with:

    ``common``      number of files with identical content in both
    ``added``       entries only in B (by content)
    ``removed``     entries only in A (by content)
    ``changed``     ``{name, a, b}`` — same name, different content
    ``only_a``      name-aware: entries that only exist in A
    ``only_b``      name-aware: entries that only exist in B
    ``same_named``  names present in both with identical content
    ``meta_a``/``meta_b``  path, block counts, failure counts

    With ``with_data=True`` the returned entries keep their bytes so a
    viewer can render them; the default strips them.
    """
    scans = []
    for p in (path_a, path_b):
        entries = scan_archive(p)
        scans.append((entries, _meta(p, entries)))
    (ea, meta_a), (eb, meta_b) = scans

    ok_a = [e for e in ea if e['status'] == 'ok']
    ok_b = [e for e in eb if e['status'] == 'ok']

    # --- content pass (unchanged semantics: the CLI relies on it) -------
    ca = Counter(e['sha256'] for e in ok_a)
    cb = Counter(e['sha256'] for e in ok_b)
    common = sum((ca & cb).values())
    removed = _collect(ok_a, ca - cb, with_data)
    added = _collect(ok_b, cb - ca, with_data)

    # --- name pass ------------------------------------------------------
    by_name_a, by_name_b = {}, {}
    for e in ok_a:
        if e.get('name'):
            by_name_a.setdefault(e['name'], e)
    for e in ok_b:
        if e.get('name'):
            by_name_b.setdefault(e['name'], e)

    changed, same_named = [], []
    for name, a in by_name_a.items():
        b = by_name_b.get(name)
        if b is None:
            continue
        if a['sha256'] == b['sha256']:
            same_named.append(dict(name=name, size=a['size'],
                                   sha256=a['sha256']))
        else:
            changed.append(dict(
                name=name,
                size_a=a['size'], size_b=b['size'],
                a=dict(a) if with_data else
                {k: v for k, v in a.items() if k != 'data'},
                b=dict(b) if with_data else
                {k: v for k, v in b.items() if k != 'data'}))
    changed.sort(key=lambda c: c['name'].lower())
    same_named.sort(key=lambda c: c['name'].lower())

    # --- leftovers: named files missing on the other side, plus the
    #     unnamed ones that could not be matched by content ------------
    only_a = [dict(e) if with_data else
              {k: v for k, v in e.items() if k != 'data'}
              for e in ok_a
              if e.get('name') and e['name'] not in by_name_b]
    only_b = [dict(e) if with_data else
              {k: v for k, v in e.items() if k != 'data'}
              for e in ok_b
              if e.get('name') and e['name'] not in by_name_a]

    ua = [e for e in ok_a if not e.get('name')]
    ub = [e for e in ok_b if not e.get('name')]
    ua_count = Counter(e['sha256'] for e in ua)
    ub_count = Counter(e['sha256'] for e in ub)
    only_a += _collect(ua, ua_count - ub_count, with_data)
    only_b += _collect(ub, ub_count - ua_count, with_data)

    only_a.sort(key=lambda e: ((e.get('name') or '').lower(), e['block']))
    only_b.sort(key=lambda e: ((e.get('name') or '').lower(), e['block']))

    return dict(common=common,
                added=added,
                removed=removed,
                changed=changed,
                only_a=only_a,
                only_b=only_b,
                same_named=same_named,
                meta_a=meta_a,
                meta_b=meta_b)
