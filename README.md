# w3xmpq

> Open any MPQ. Crack any map. No listfile, no keys, no editor required.

**w3xmpq** is a pure-Python tool that opens `.mpq` archives and Warcraft III
`.w3x`/`.w3m` maps, recovers every file — **including encrypted/protected
ones** — via a known-plaintext attack on the MPQ sector offset table, and
lets you list, extract, diff and batch-process them from a professional CLI.

```text
$ w3xmpq report "DotA v6.83dAI PMV 1.42 EN.w3x"

Deprotection report — DotA v6.83dAI PMV 1.42 EN.w3x
files: 1297 recovered, 0 failed

[!] Script moved to fallback path (high)
    The main script was found at the game's fallback path
    (Scripts\war3map.j -> extracted as war3map_script.j, 4,164,351 bytes)
    while the canonical war3map.j is absent. World Editor reads only the
    canonical name — this is the classic script-relocation protection.
[!] Authoring files missing (editor-hostile) (high)
    World Editor needs these to open/edit a map: war3map.wtg, war3map.wct,
    war3map.imp, war3map.w3t, war3map.w3q, war3map.w3u, war3mapUnits.doo
[*] Decoy (listfile) (warning)
    The (listfile) is binary junk (43% printable) — a decoy meant to
    confuse naive tools.

Verdict: Script recovered, but World Editor would refuse this map:
re-add the missing authoring files to make it editor-openable.
The extracted war3map_script.j is a ready replacement for the
canonical war3map.j.
```

## Why?

Every existing MPQ tool (Ladik's MPQ Editor, `mpyq`, …) needs a listfile and
fails on encrypted files. w3xmpq needs **neither** — it recovers each file's
encryption key from the data itself. Verified on real protected maps:

| Map | Files recovered | Key failures |
|---|---|---|
| DotA v6.83dAI PMV 1.42 EN | **1297/1297** | 0 |
| MooMoo v3.19b Generation X | **557/559** | 0 (2 unreadable-by-design blocks) |

## Who is it for?

- **Players** — peek inside a map: models, skins, music.
- **Map authors** — recover your own locked/lost source: `report` explains exactly how your map is protected.
- **Modders** — extract assets with proper names into typed folders.
- **Reviewers / admins** — `scan` flags suspicious JASS patterns before you host a map.
- **Researchers** — key forensics, entropy analysis, `--json` everywhere.
- **Archivists** — `batch` over thousands of maps with a CSV index.
- **Developers** — a stable pure-Python MPQ engine (`from w3xmpq import …`).

## Install

```bash
pip install .            # from source
```

Requires Python 3.9+. Zero dependencies for the CLI; the GUI needs
`pip install PySide6`. No-Python binaries (CLI **and** GUI) are on the
[releases page](https://github.com/kissanima/w3xmpq/releases).

## GUI (v1.0)

```bash
w3xmpq gui map.w3x       # or download w3xmpq-gui.exe from releases
```

A professional windowed interface built on Qt/PySide6:

- **Drag & drop** any `.w3x` / `.w3m` / `.mpq` onto the window
- **Folder tree** (left) — recovered paths shown as a tree; click a folder
  to filter the file table, like a zip browser
- **File table** (middle) — every recovered block with name, sizes, flags
  and status
- **Preview pane** (right) — script/text files as text, everything else as
  a hex dump
- **Right-click** a file → Preview · Extract selected… · Copy name
- **Map banner** — name, author, tileset, recovery count at a glance
- **Tools** — deprotection report, safety scan, WorldEdit-ready rebuild,
  two-archive diff, folder batch extraction — all in dialogs, all on
  background threads so the UI never freezes

## Quickstart

```bash
w3xmpq open   map.w3x                    # archive info
w3xmpq list   map.w3x                    # recovered file table
w3xmpq extract map.w3x -o out/           # extract everything
w3xmpq extract map.w3x -f "war3map"      # selective extraction
w3xmpq report  map.w3x                   # deprotection report
w3xmpq scan   map.w3x                    # map safety scan
w3xmpq diff   old.w3x new.w3x            # version comparison
w3xmpq batch  ./maps/ -o out/            # bulk processing
w3xmpq rebuild map.w3x -o fixed.w3x      # WorldEdit-ready copy
```

All commands accept `--json` for machine-readable output. Exit codes:
`0` ok, `1` partial, `2` fatal.

## How the crack works

See [docs/how-it-works.md](docs/how-it-works.md) for the full math. In short:

1. Every encrypted MPQ file starts with its sector offset table, whose first
   DWORD is always `4 * (sectors + 1)` — **known plaintext**.
2. The MPQ cipher's first output word is
   `ct0 ^ p0 = key + 0xEEEEEEEE + T[0x400 + (key & 0xFF)]`, so enumerating
   the 256 table indexes yields self-consistent key candidates.
3. Each candidate is verified by decrypting the whole table and checking it
   is monotonic, starts at `4*(sectors+1)` and ends at the archived size.

No listfile, no filenames, no brute force.

## Deprotection patterns

w3xmpq recognizes the classic "game-lenient, editor-hostile" tricks —
see [docs/deprotection-patterns.md](docs/deprotection-patterns.md).

## Ethics

w3xmpq exists for recovering **your own** locked maps, format study, modding,
and game preservation. Don't use it to steal other people's work. The safety
scan provides evidence for review — it is not a verdict.

## Docs

- [docs/how-it-works.md](docs/how-it-works.md) — the key-recovery math
- [docs/deprotection-patterns.md](docs/deprotection-patterns.md) — protection patterns and what the report says about each

## Development

```bash
pip install -e .
python -m unittest discover -s tests -v
```

The test suite builds synthetic encrypted MPQ fixtures from scratch —
no copyrighted game data is ever committed.

## Credits

- [mpyq](https://github.com/alanstevens/mpyq) (MIT, © Aku Kotkavuo) — the MPQ
  reading core is vendored and adapted in `src/w3xmpq/core/mpq.py`.
- StormLib documentation — MPQ format constants.
- Ladik's MPQ Editor — inspiration (and the tool that *can't* do this).
- The WC3 modding community (Hive Workshop) — for keeping the format alive.

## License

MIT — see [LICENSE](LICENSE).
