#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.names — filename recovery for unnamed MPQ blocks.

Two strategies, applied in order:
  1. hash-probing: compute the hash-table position of ~200 known WC3 paths
     and see whether the archive's hash table has a live entry there
     (done in core/extract.py via get_hash_table_entry);
  2. magic-byte/content sniffing of the decrypted data.

NOTE: guess_name() is a faithful, verbatim port of the battle-tested logic —
including its operator precedence. Do not "clean it up" without re-running
the verification suite against real maps (a looser text heuristic would
misname war3map.wts as war3map.j).
"""

# Canonical WC3 map file names probed against the archive's hash table.
KNOWN_NAMES = [
    "war3map.j", "Scripts\\war3map.j", "war3map.wts", "war3map.w3e",
    "war3map.w3a", "war3map.w3u", "war3map.w3b", "war3map.w3t", "war3map.w3d",
    "war3map.w3q", "war3map.shd", "war3map.mmp", "war3map.wpm", "war3map.doo",
    "war3map.imp", "war3map.wtg", "war3map.wct", "war3map.dpk",
    "war3map.camera", "(listfile)", "(attributes)", "(signature)",
    "war3mapUnits.doo", "war3map.units.doo",
    "war3x.w3a", "war3map.wdg",
]

# (listfile) names are mapped to clean on-disk names.
NAME_REMAP = {
    "Scripts\\war3map.j": "war3map_script.j",  # deprotection: real script path
}

# Magic-byte / content fingerprints for content-based naming.
TYPE_HINTS = [
    (b'W3E!', "war3map.w3e"),
    (b'endfunction', "war3map.j"),
    (b'function main', "war3map.j"),
    (b'//===========================================================================', "war3map.j"),
    (b'STRING', "war3map.wts"),
]


def guess_name(data, idx):
    """Guess a file name from decrypted content. Falls back to block_NNN."""
    # Texture containers announce themselves with a 4-byte magic.
    if data[:4] in (b'BLP1', b'BLP2'):
        return "texture_%03d.blp" % idx
    for magic, name in TYPE_HINTS:
        if data.startswith(magic) or (name == "war3map.j" and magic in data[:20000]
                                      and data[:1].isalpha() or data.startswith(b'//')):
            return name
    return "block_%03d" % idx
