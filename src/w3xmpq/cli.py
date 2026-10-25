#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq command-line interface.

Exit codes: 0 = ok, 1 = partial (some files failed), 2 = fatal error.
"""

import argparse
import json
import os
import sys

from . import __version__
from .core.extract import extract_archive, open_archive, scan_archive
from .core.diff import diff_archives
from .core.batch import batch_extract
from .core.w3x_header import is_w3x, parse_header
from .core.report import build_report, render_report
from .core.safety import scan_safety, render_safety

FLAGS_SHORT = [(0x80000000, "E"),      # EXISTS
               (0x00000200, "Z"),      # COMPRESS
               (0x00010000, "K"),      # ENCRYPTED
               (0x01000000, "S"),      # SINGLE_UNIT
               (0x04000000, "C"),      # SECTOR_CRC
               (0x00040000, "P")]      # SPARSE


def _flags_str(flags):
    return "".join(c for bit, c in FLAGS_SHORT if flags & bit) or "-"


def _die(e):
    print("error: %s" % e, file=sys.stderr)
    sys.exit(2)


def _print_json(obj):
    print(json.dumps(obj, indent=1))


def _archive_meta(arch, path):
    h = arch.header
    return dict(path=os.path.abspath(path),
                format_version=h['format_version'],
                sector_size=512 << h['sector_size_shift'],
                hash_table_entries=h['hash_table_entries'],
                block_table_entries=h['block_table_entries'])


def cmd_open(args):
    try:
        arch = open_archive(args.archive)
    except Exception as e:
        _die(e)
    meta = _archive_meta(arch, args.archive)
    meta['files_existing'] = sum(1 for b in arch.block_table
                                 if b.flags & 0x80000000 and b.archived_size)
    arch.file.close()
    if args.json:
        _print_json(meta)
        return 0
    print("MPQ archive: %s" % args.archive)
    print("  format version      %d" % meta['format_version'])
    print("  sector size         %d bytes" % meta['sector_size'])
    print("  hash table entries  %d" % meta['hash_table_entries'])
    print("  block table entries %d" % meta['block_table_entries'])
    print("  files (existing)    %d" % meta['files_existing'])
    return 0


def cmd_list(args):
    try:
        entries = scan_archive(args.archive)
    except Exception as e:
        _die(e)
    rows = [dict(block=e['block'], name=e['name'], size=e['size'],
                 archived=e['archived_size'], flags=_flags_str(e['flags']),
                 sha256=e['sha256'], status=e['status'])
            for e in entries
            if args.failed or e['status'] == 'ok']
    if args.json:
        _print_json(rows)
        return 0
    print("%-6s %-20s %10s %10s %-5s %s"
          % ("BLOCK", "NAME", "SIZE", "ARCHIVED", "FLAGS", "SHA256[:12]"))
    for r in rows:
        print("%-6d %-20s %10d %10d %-5s %s"
              % (r['block'], (r['name'] or "?")[:20], r['size'],
                 r['archived'], r['flags'],
                 (r['sha256'] or "")[:12]))
    return 0


def _banner(path):
    """One-line map header banner for .w3x files (empty for plain MPQs)."""
    if not is_w3x(path):
        return
    try:
        h = parse_header(path)
    except Exception:
        return
    size = os.path.getsize(path)
    print("target : %s (%.2f MB)" % (os.path.basename(path),
                                     size / 1048576.0))
    print('header : "%s" by %s · %s · %dx%d tiles'
          % (h['name'] or "?", h['author'] or "?", h['tileset_name'],
             h['width'], h['height']))
    print()


def cmd_extract(args):
    if not args.quiet:
        _banner(args.archive)
    try:
        manifest = extract_archive(args.archive, args.outdir,
                                   pattern=args.filter,
                                   verbose=not args.quiet)
    except Exception as e:
        _die(e)
    ok = sum(1 for m in manifest if m['status'] == 'ok')
    failed = sum(1 for m in manifest if m['status'] == 'FAILED')
    if args.quiet:
        print("%d/%d" % (ok, len(manifest)))
    if args.json:
        _print_json(manifest)
    return 1 if failed else 0


def cmd_diff(args):
    try:
        result = diff_archives(args.archive_a, args.archive_b)
    except Exception as e:
        _die(e)
    if args.json:
        _print_json(result)
        return 0
    ma, mb = result['meta_a'], result['meta_b']
    print("A: %s  (%d ok, %d failed)" % (ma['path'], ma['ok'], ma['failed']))
    print("B: %s  (%d ok, %d failed)" % (mb['path'], mb['ok'], mb['failed']))
    print()
    print("identical content : %d" % result['common'])
    print("only in B (added) : %d" % len(result['added']))
    for e in result['added'][:20]:
        print("   + %-20s %9d bytes  %s" % ((e['name'] or "?")[:20],
                                            e['size'], e['sha256'][:12]))
    print("only in A (removed): %d" % len(result['removed']))
    for e in result['removed'][:20]:
        print("   - %-20s %9d bytes  %s" % ((e['name'] or "?")[:20],
                                            e['size'], e['sha256'][:12]))
    return 0


def cmd_batch(args):
    try:
        index = batch_extract(args.root, args.outdir, pattern=args.filter)
    except Exception as e:
        _die(e)
    ok = sum(1 for r in index if r['status'] == 'ok')
    partial = sum(1 for r in index if r['status'] == 'partial')
    errors = sum(1 for r in index if r['status'] == 'error')
    if args.json:
        _print_json(index)
    else:
        print("\nBatch complete: %d archives (%d ok, %d partial, %d errors)"
              % (len(index), ok, partial, errors))
        print("index: %s" % os.path.join(args.outdir, 'index.csv'))
    return 1 if (partial or errors) else 0


def cmd_report(args):
    try:
        rep = build_report(args.archive)
    except Exception as e:
        _die(e)
    if args.json:
        _print_json(rep)
    else:
        print(render_report(rep))
    return 0


def cmd_scan(args):
    try:
        res = scan_safety(args.archive)
    except Exception as e:
        _die(e)
    if args.json:
        _print_json(res)
    else:
        print(render_safety(res))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="w3xmpq",
        description="w3xmpq — open any MPQ archive or Warcraft III map. "
                    "Recovers encrypted files without a listfile or keys.")
    ap.add_argument("--version", action="version",
                    version="w3xmpq %s" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("open", help="print archive info (no extraction)")
    po.add_argument("archive")
    po.add_argument("--json", action="store_true", help="machine output")
    po.set_defaults(func=cmd_open)

    pl = sub.add_parser("list", help="list recovered files (no writing)")
    pl.add_argument("archive")
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--failed", action="store_true",
                    help="include FAILED entries")
    pl.set_defaults(func=cmd_list)

    pe = sub.add_parser("extract", help="extract every recoverable file")
    pe.add_argument("archive")
    pe.add_argument("-o", "--outdir", default="w3xmpq_out",
                    help="output directory (default: ./w3xmpq_out)")
    pe.add_argument("-f", "--filter", metavar="REGEX",
                    help="extract only files whose name matches")
    pe.add_argument("-q", "--quiet", action="store_true",
                    help="only print the final count")
    pe.add_argument("--json", action="store_true",
                    help="print manifest as JSON")
    pe.set_defaults(func=cmd_extract)

    pd = sub.add_parser("diff", help="compare two archives by content")
    pd.add_argument("archive_a")
    pd.add_argument("archive_b")
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=cmd_diff)

    pb = sub.add_parser("batch", help="extract every archive under a folder")
    pb.add_argument("root")
    pb.add_argument("-o", "--outdir", default="w3xmpq_batch_out")
    pb.add_argument("-f", "--filter", metavar="REGEX")
    pb.add_argument("--json", action="store_true")
    pb.set_defaults(func=cmd_batch)

    pr = sub.add_parser("report",
                        help="deprotection report: how is this map locked?")
    pr.add_argument("archive")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_report)

    ps = sub.add_parser("scan",
                        help="map safety scan: JASS stats + suspicious "
                             "patterns (for review, not a verdict)")
    ps.add_argument("archive")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_scan)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
