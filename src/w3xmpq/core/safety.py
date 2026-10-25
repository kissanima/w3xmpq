#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.safety — map safety scan (JASS stats + suspicious patterns).

Static, evidence-based scanning of the recovered script(s). Findings are
"for review" — a map containing these patterns is not automatically
malicious, and a clean scan is not a guarantee. We deliberately avoid a
numeric "risk score": it would create false confidence.

Requires nothing but stdlib: patterns are regexes over the decoded script.
"""

import re
from collections import Counter

from .extract import scan_archive

SCRIPT_NAMES = ("war3map.j", "war3map_script.j")

# (label, regex, severity, explanation)
PATTERNS = [
    ("Preload file I/O",
     r"\bPreload\s*\(",
     "warning",
     "PreloadGen-style local file I/O. Historically abused to write/read "
     "files outside the map or to fingerprint hosts."),
    ("Export/Import file I/O",
     r"\bExportFile\b|\bImportFile\b|PreloadGenClear|SaveGameCacheExists\b",
     "warning",
     "Game-cache/export calls — same family of local-I/O abuse as Preload."),
    ("Cheat keywords",
     r"(?i)\bcheat",
     "info",
     "Cheat-related strings present (debug menus, cheat commands or "
     "anti-cheat code)."),
    ("Player-state probing",
     r"GetPlayerSlotState|IsPlayerInForce|GetPlayerController|IsPlayerObserver",
     "info",
     "Maps player slot/force/controller state — typical of host detection "
     "or role-based logic."),
    ("Player-name collection",
     r"GetPlayerName",
     "info",
     "Reads player names (also common in benign name-based features)."),
    ("EndGame call",
     r"\bEndGame\b",
     "info",
     "Forces game end — also used by anti-tamper stubs."),
    ("Sync primitives",
     r"\bSyncStoredInteger\b|\bSyncStoredReal\b|\bSyncStoredString\b",
     "info",
     "Game-cache sync calls — used for cross-player communication."),
]

STAT_NATIVES = [
    "TriggerAddAction", "TriggerAddCondition", "TriggerRegisterAnyUnitEventBJ",
    "ExecuteFunc", "CreateNUnitsAtLoc", "CreateItemLoc", "DestroyEffect",
    "Preload", "GetPlayerName", "EndGame", "TriggerSleepAction",
    "PlaySoundFileBJ", "SetCameraPosition", "PanCameraToTimed",
]


def scan_safety(path):
    """Scan the recovered script of a map. Returns a dict."""
    entries = scan_archive(path)
    scripts = [e for e in entries
               if e['status'] == 'ok' and e['name'] in SCRIPT_NAMES]
    scripts.sort(key=lambda e: -e['size'])
    if not scripts:
        return dict(script=None, size=0, stats={}, findings=[],
                    note="No recovered script found.")

    script = scripts[0]
    text = script['data'].decode('cp1252', 'ignore')

    stats = {}
    for native in STAT_NATIVES:
        stats[native] = len(re.findall(r'\b%s\b' % re.escape(native), text))

    findings = []
    for label, pattern, severity, explanation in PATTERNS:
        rx = re.compile(pattern)
        hits = rx.findall(text)
        if not hits:
            continue
        findings.append(dict(label=label, severity=severity,
                             count=len(hits), explanation=explanation))

    # Dynamic heuristic: mass ExecuteFunc = typical obfuscation marker.
    if stats.get('ExecuteFunc', 0) > 100:
        findings.append(dict(
            label="Mass ExecuteFunc (obfuscation indicator)",
            severity="warning", count=stats['ExecuteFunc'],
            explanation="Very high ExecuteFunc count is characteristic of "
                        "deliberately obfuscated or machine-generated code."))

    severity_rank = {"warning": 0, "info": 1}
    findings.sort(key=lambda f: severity_rank.get(f['severity'], 9))
    return dict(script=script['name'], size=script['size'], stats=stats,
                findings=findings)


def render_safety(res):
    lines = []
    if res.get('note'):
        lines.append("Map safety scan: %s" % res['note'])
        return "\n".join(lines)
    lines.append("Map safety scan — script: %s (%d bytes)"
                 % (res['script'], res['size']))
    lines.append("Findings are for review; they are not a verdict.")
    lines.append("")
    if res['findings']:
        icons = {"warning": "[*]", "info": "[i]"}
        for f in res['findings']:
            lines.append("%s %s (%s) — %d hit(s)"
                         % (icons.get(f['severity'], "[?]"), f['label'],
                            f['severity'], f['count']))
            lines.append("    %s" % f['explanation'])
    else:
        lines.append("[i] No suspicious patterns found.")
    lines.append("")
    lines.append("Script statistics:")
    for k, v in sorted(res['stats'].items(), key=lambda kv: -kv[1]):
        if v:
            lines.append("    %-30s %6d" % (k, v))
    return "\n".join(lines)
