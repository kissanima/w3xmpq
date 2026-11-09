#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.report — deprotection report + unknown-block analysis.

Explains HOW a map is protected, in plain language, with a verdict on what
would be needed to open it in World Editor. Typical "game-lenient,
editor-hostile" protection patterns (documented in docs/deprotection-patterns.md):

  * real script moved to the game's fallback path  Scripts\\war3map.j  while
    the canonical  war3map.j  is deleted or replaced by an anti-tamper stub
  * trigger DB (wtg/wct), imports (imp) and object tables (w3t/w3q/w3u)
    deleted -> script-only map
  * "Disabled Single Player" + EndGame(true) stubs
  * decoy (listfile) (binary junk)

Plus an unknown-block analyzer (entropy + magic sniffing) that helps decide
what unnamed blocks contain. Honest framing: this is evidence, not a verdict
on ownership — only recover maps you have the rights to.
"""

import math
import os
from collections import Counter

from .extract import scan_archive
from .names import NAME_REMAP

FALLBACK_NAME = "war3map_script.j"        # NAME_REMAP product
CANONICAL_NAME = "war3map.j"
STUB_MARKERS = (b"Disabled Single Player", b"EndGame")

AUTHORING_FILES = [
    ("war3map.wtg", "trigger GUI database"),
    ("war3map.wct", "trigger custom text"),
    ("war3map.imp", "imported files list"),
    ("war3map.w3t", "item object data"),
    ("war3map.w3q", "upgrade object data"),
    ("war3map.w3u", "unit object data"),
    ("war3mapUnits.doo", "preplaced units"),
]

# Magic-byte signatures for unknown-block sniffing.
MAGICS = [
    (b'MDLX', "MDX model"),
    (b'BLP1', "BLP texture (v1)"),
    (b'BLP2', "BLP texture (v2)"),
    (b'W3E!', "terrain"),
    (b'RIFF', "WAV audio"),
    (b'ID3', "MP3 audio"),
    (b'\xff\xfb', "MP3 audio"),
    (b'WTG!', "trigger GUI database"),
    (b'W3a!', "ability object data"),
    (b'W3u!', "unit object data"),
]


def shannon_entropy(data, sample=65536):
    """Bits of entropy per byte, sampled from the head of `data`."""
    data = data[:sample]
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def sniff(data):
    for magic, label in MAGICS:
        if data.startswith(magic):
            return label
    if data[:1].isalpha() or data.startswith(b'//'):
        return "text"
    return None


def build_report(path, entries=None):
    """Build the deprotection report for a map/archive. Returns a dict.

    `entries` lets a caller (the GUI) reuse a scan it already performed;
    when omitted the archive is scanned here.
    """
    if entries is None:
        entries = scan_archive(path)
    by_name = {}
    for e in entries:
        if e['name']:
            by_name.setdefault(e['name'], []).append(e)

    findings = []

    canonical = by_name.get(CANONICAL_NAME, [None])[0]
    fallback = by_name.get(FALLBACK_NAME, [None])[0]

    # -- script relocation ------------------------------------------------
    if fallback is not None and canonical is None:
        findings.append(dict(
            severity="high", area="script",
            title="Script moved to fallback path",
            detail=("The main script was found at the game's fallback path "
                    "(Scripts\\war3map.j -> extracted as %s, %d bytes) while "
                    "the canonical war3map.j is absent. World Editor reads "
                    "only the canonical name — this is the classic "
                    "script-relocation protection." % (FALLBACK_NAME,
                                                        fallback['size']))))
    elif fallback is not None and canonical is not None:
        blob = canonical.get('data', b'') if canonical else b''
        if any(m in blob for m in STUB_MARKERS):
            findings.append(dict(
                severity="high", area="script",
                title="Canonical script is an anti-tamper stub",
                detail=("war3map.j (%d bytes) is a stub (contains "
                        "\"Disabled Single Player\" / EndGame markers) while "
                        "the real script (%d bytes) sits at "
                        "Scripts\\war3map.j." % (canonical['size'],
                                                 fallback['size']))))
        else:
            findings.append(dict(
                severity="info", area="script",
                title="Script present at both canonical and fallback paths",
                detail=("canonical war3map.j is %d bytes; fallback copy is "
                        "%d bytes." % (canonical['size'], fallback['size']))))
    elif canonical is not None and any(m in canonical.get('data', b'')
                                       for m in STUB_MARKERS):
        findings.append(dict(
            severity="high", area="script",
            title="Canonical script is an anti-tamper stub",
            detail=("war3map.j is a stub (%d bytes) and no fallback script "
                    "was found — the map may be script-only or empty."
                    % canonical['size'])))

    # -- missing authoring files ------------------------------------------
    missing = [(n, d) for n, d in AUTHORING_FILES if n not in by_name]
    if missing:
        findings.append(dict(
            severity="high" if len(missing) >= 3 else "warning",
            area="authoring",
            title="Authoring files missing (editor-hostile)",
            detail=("World Editor needs these to open/edit a map: %s"
                    % ", ".join(n for n, _ in missing))))

    # -- decoy listfile -----------------------------------------------------
    lf = by_name.get('(listfile)', [None])[0]
    if lf is not None and lf.get('data'):
        printable = sum(32 <= c < 127 or c in (9, 10, 13)
                        for c in lf['data'][:4096])
        ratio = printable / min(len(lf['data']), 4096)
        if ratio < 0.7:
            findings.append(dict(
                severity="warning", area="listfile",
                title="Decoy (listfile)",
                detail=("The (listfile) is binary junk (%.0f%% printable, "
                        "%d bytes) — a decoy meant to confuse naive tools."
                        % (ratio * 100, lf['size']))))

    # -- unknown-block analysis --------------------------------------------
    unknown = []
    for e in entries:
        if e['status'] != 'ok' or not (e['name'] or '').startswith('block_'):
            continue
        data = e.get('data', b'')
        unknown.append(dict(
            block=e['block'], name=e['name'], size=e['size'],
            entropy=round(shannon_entropy(data), 2),
            sniffed=sniff(data) or "unknown"))

    # -- verdict -----------------------------------------------------------
    script_ok = (canonical is not None
                 and not any(m in canonical.get('data', b'')
                             for m in STUB_MARKERS)) or fallback is not None
    has_triggers = 'war3map.wtg' in by_name and 'war3map.wct' in by_name
    if script_ok and has_triggers and not missing:
        verdict = ("No script-only protection detected — this map should "
                   "open in World Editor as-is.")
    elif script_ok and not missing:
        verdict = ("Script recovered; standard files present. This should be "
                   "editor-openable (canonical script in place).")
    elif script_ok:
        verdict = ("Script recovered, but World Editor would refuse this "
                   "map: re-add the missing authoring files (see findings) "
                   "to make it editor-openable.")
    else:
        verdict = ("No usable script found — map is likely empty, corrupted, "
                   "or protected beyond script relocation.")
    if fallback is not None:
        verdict += (" The extracted %s is a ready replacement for the "
                    "canonical war3map.j." % FALLBACK_NAME)

    return dict(
        path=os.path.abspath(path),
        findings=findings,
        verdict=verdict,
        unknown=unknown,
        files_ok=sum(1 for e in entries if e['status'] == 'ok'),
        files_failed=sum(1 for e in entries if e['status'] == 'FAILED'),
    )


def render_report(rep):
    """Plain-text rendering of a report (for CLI and _report.txt)."""
    lines = []
    lines.append("Deprotection report — %s" % rep['path'])
    lines.append("files: %d recovered, %d failed" % (rep['files_ok'],
                                                     rep['files_failed']))
    lines.append("")
    if rep['findings']:
        icons = {"high": "[!]", "warning": "[*]", "info": "[i]"}
        for f in rep['findings']:
            lines.append("%s %s (%s)" % (icons.get(f['severity'], "[?]"),
                                         f['title'], f['severity']))
            lines.append("    %s" % f['detail'])
    else:
        lines.append("[i] No protection patterns detected.")
    lines.append("")
    if rep['unknown']:
        lines.append("Unknown blocks (unnamed; by size):")
        for u in sorted(rep['unknown'], key=lambda x: -x['size'])[:10]:
            lines.append("    %-14s %9d bytes  entropy %.2f b/B  looks: %s"
                         % (u['name'], u['size'], u['entropy'], u['sniffed']))
    lines.append("")
    lines.append("Verdict: %s" % rep['verdict'])
    return "\n".join(lines)
