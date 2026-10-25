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
from .core.extract import (extract_archive, load_listfile, open_archive,
                           scan_archive)
from .core.diff import diff_archives
from .core.batch import batch_extract
from .core.mpq_write import rebuild_map
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
                 sha256=e['sha256'], status=e['status'],
                 name_source=e.get('name_source'),
                 key_method=e.get('key_method'))
            for e in entries
            if args.failed or e['status'] == 'ok']
    if args.json:
        _print_json(rows)
        return 0
    print("%-6s %-20s %10s %10s %-5s %-7s %-7s %s"
          % ("BLOCK", "NAME", "SIZE", "ARCHIVED", "FLAGS", "NAME-SRC",
             "KEY", "SHA256[:12]"))
    for r in rows:
        print("%-6d %-20s %10d %10d %-5s %-7s %-7s %s"
              % (r['block'], (r['name'] or "?")[:20], r['size'],
                 r['archived'], r['flags'],
                 (r['name_source'] or "-")[:7],
                 (r['key_method'] or "-")[:7],
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
    listfile = load_listfile(args.listfile) if args.listfile else None
    try:
        manifest = extract_archive(args.archive, args.outdir,
                                   pattern=args.filter,
                                   verbose=not args.quiet,
                                   listfile=listfile)
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


def cmd_rebuild(args):
    try:
        names = rebuild_map(args.archive, args.out)
    except Exception as e:
        _die(e)
    print("Rebuilt %s — %d files, standard unencrypted MPQ" %
          (args.out, len(names)))
    print("World Editor should now be able to open it.")
    return 0


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


def cmd_blp(args):
    """Convert a Warcraft III texture to an image file."""
    from .core.blp import BlpError, open_blp
    try:
        with open(args.texture, "rb") as fh:
            blp = open_blp(fh.read())
    except (OSError, BlpError) as e:
        _die(e)
    out = args.out
    ext = os.path.splitext(out)[1].lower()
    try:
        if blp.is_jpeg:
            if ext in (".jpg", ".jpeg"):
                # The JPEG flavour is stored as a real JPEG stream once
                # the split frame header is stitched back together.
                blob = blp.jpeg_bytes(args.level)
            else:
                blob = _jpeg_to_png(blp.jpeg_bytes(args.level), args.level)
        else:
            blob = blp.png_bytes(args.level)
        with open(out, "wb") as fh:
            fh.write(blob)
    except (OSError, BlpError, ValueError) as e:
        _die(e)
    mip = blp.mipmaps[args.level] if blp.mipmaps else None
    size = "%dx%d" % (mip.width, mip.height) if mip else "?"
    print("Wrote %s — %s, %d mipmap level(s), %s encoding"
          % (out, size, len(blp.mipmaps), blp.kind.upper()))
    return 0


def _jpeg_to_png(jpeg_bytes, level=0):
    """Convert a JPEG stream to PNG (needs Pillow)."""
    try:
        import io
        from PIL import Image
    except ImportError:
        raise ValueError(
            "converting this texture to PNG needs Pillow "
            "(pip install Pillow) — or save it as .jpg instead")
    im = Image.open(io.BytesIO(jpeg_bytes))
    if im.mode == "CMYK":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


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
    pe.add_argument("--listfile", metavar="FILE",
                    help="extra known filenames (one per line) for "
                         "hash-probing non-WC3 archives")
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

    pb2 = sub.add_parser("rebuild",
                         help="rewrite a (protected) map as a standard, "
                              "unencrypted MPQ World Editor can open")
    pb2.add_argument("archive")
    pb2.add_argument("-o", "--out", required=True,
                     help="output .w3x path")
    pb2.set_defaults(func=cmd_rebuild)

    pblp = sub.add_parser("blp",
                          help="convert a Warcraft III .blp texture to PNG/JPEG")
    pblp.add_argument("texture", help="path to a .blp file")
    pblp.add_argument("-o", "--out", required=True,
                      help="output image path (.png or .jpg)")
    pblp.add_argument("--level", type=int, default=0,
                      help="mipmap level to export (0 = full size)")
    pblp.set_defaults(func=cmd_blp)

    pg = sub.add_parser("gui",
                        help="launch the graphical interface (needs PySide6)")
    pg.add_argument("archive", nargs="?", help="archive to open on start")
    pg.set_defaults(func=cmd_gui)

    return ap


def cmd_gui(args):
    try:
        from .gui.main_window import main as gui_main
    except ImportError:
        _die("the GUI needs PySide6:  pip install PySide6")
    argv = [args.archive] if args.archive else []
    return gui_main(argv)


def _no_args_welcome():
    """Friendly screen when launched without arguments (e.g. double-click).

    Instead of argparse's error + instant exit (the console window just
    flashes), show what the tool can do and pause so the window stays open.
    """
    print("w3xmpq %s — open any MPQ archive or Warcraft III map" % __version__)
    print("No listfile, no keys, no editor required.")
    print()
    print("This is a command-line tool. Open a terminal (cmd or PowerShell),")
    print("then run it from that folder, for example:")
    print()
    print('  w3xmpq open   "C:\\path\\to\\map.w3x"          # archive info')
    print('  w3xmpq list   "C:\\path\\to\\map.w3x"          # file table')
    print('  w3xmpq extract "C:\\path\\to\\map.w3x" -o out/  # extract all')
    print('  w3xmpq report "C:\\path\\to\\map.w3x"          # how is it locked?')
    print('  w3xmpq scan   "C:\\path\\to\\map.w3x"          # safety scan')
    print('  w3xmpq diff   old.w3x new.w3x               # compare versions')
    print('  w3xmpq batch  "C:\\path\\to\\maps\\" -o out/     # bulk extraction')
    print('  w3xmpq gui    "C:\\path\\to\\map.w3x"          # graphical UI')
    print()
    print("Prefer a window over a terminal? Get the GUI binary from the")
    print("releases page (w3xmpq-gui.exe) or run:  w3xmpq gui")
    print("Or drag a .w3x/.mpq file onto w3xmpq.exe in File Explorer while")
    print("holding nothing — Windows passes the file path as an argument.")
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("Press Enter to exit...")
    except Exception:
        pass
    return 0


def main(argv=None):
    if argv is None and len(sys.argv) == 1:
        return _no_args_welcome()
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
