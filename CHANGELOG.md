# Changelog

## 1.4.0 — 2026-10-26

**Many maps at once, a real diff, and a dark side.**

### New — tabs
- **Every archive opens in its own tab.** Compare a map with the one you
  are editing without losing your place, or drop five maps and get five
  tabs.
- `Ctrl+W` closes a tab, `Ctrl+Tab` / `Ctrl+Shift+Tab` cycle, and a
  middle-click closes — like a browser.
- Opening a path that is already open **focuses its tab** instead of
  scanning it twice.
- Each tab keeps its own entries, folder filter, search and preview;
  closing one tab never disturbs the others.
- Dropping several files on the window opens them all.
- An empty window now shows a welcome page instead of a dead toolbar.

### New — in-app diff
- Comparing two archives opens a **tab**, not a text dialog: a change
  table (status · name · both sizes · delta · both hashes), a name filter,
  a group selector (*differences only* / *changed* / *only in A* /
  *only in B* / *identical*) and the two versions of the selected file
  **side by side**.
- The panes **scroll to the first difference** and the header reports
  `+N −M lines`, so a 4 MB script opens on the line that changed.
- **Files are now paired by name.** An edited script is reported as
  *changed*, with both versions, instead of "one file added, one file
  removed". Unnamed blocks still match by content (SHA-256 multiset).
- `Tools → Compare current with…` starts from the archive you have open.

### New — dark theme
- `View → Dark theme` (`Ctrl+Shift+D`), remembered between sessions. The
  GUI runs on the Fusion style so the palette actually applies on Windows,
  with a hand-tuned dark palette, dark JASS colours, and table colours
  that follow the theme.
- Switching theme keeps the selected file and its preview.

### Changed
- `w3xmpq diff` prints the same grouping the GUI shows: identical ·
  changed · only in A · only in B.
- `core.diff.diff_archives()` gained `changed`, `only_a`, `only_b`,
  `same_named` and a `with_data` option. `added` / `removed` / `common`
  keep their content-based meaning, so existing callers are unaffected.

### Fixed
- The old diff dialog's "Changed" section was always empty — the core
  never produced changed pairs, only added/removed content.
- Switching theme rebuilt the file table, which fired a selection change
  and threw the preview back to the first file.

### Verified
- 95 tests (was 76): tab independence, closing a tab mid-scan, theme
  round-trip, diff grouping, filter, side-by-side panes and
  scroll-to-difference, plus the name-aware core diff.

## 1.3.0 — 2026-10-26

**Textures, decoded. Scripts, coloured.**

### New — BLP texture decoding
- **`.blp` files are now decoded and rendered inline in the GUI** — click a texture and see the picture, not a hex dump.
- New `w3xmpq.core.blp` module: a pure-Python reader for all three Warcraft III texture families —
  - **BLP1 classic** (uncompressed BGRA and 8-bit palettised, bottom-up rows)
  - **BLP2 classic** (uncompressed and **DXT1 / DXT3 / DXT5**, including explicit and interpolated alpha)
  - **BLP1 with a JPEG inside** — the format every texture since WC3 1.22 uses
- **The split JPEG frame header is reassembled.** Blizzard stores the `FF C0` marker at the end of the shared header block and the frame length/body at the start of every mipmap, so no standard decoder can read the file as-is. `w3xmpq` stitches the halves back together and hands out a valid JPEG stream.
- New CLI command: `w3xmpq blp texture.blp -o out.png` (or `-o out.jpg`, which needs no extra dependency; `--level N` picks a mipmap level).
- New `docs/blp-format.md` — the full format write-up, including why these files are CMYK JPEGs that most libraries reject.

### New — script preview
- **JASS syntax highlighting** in the preview pane: keywords, native functions, numbers, strings, comments and `#preprocessor` lines.

### Changed
- The scanner now recognises `BLP1`/`BLP2` magic bytes and names unnamed texture blocks `texture_NNN.blp`, so textures stay identifiable in maps whose file names were destroyed.
- The preview pane is now a stacked view: text/hex on one page, image on the other.

### Stability
- 76 tests (was 57): BLP decoding for every format family, the JPEG reassembly, DXT colour and alpha tables, the CLI conversion, the image preview and the JASS classifier.

## 1.2.0 — 2026-10-25

**Preview power and a session that remembers you.**

### New
- **Find in file** (Ctrl+Shift+F) — search inside the previewed file, with
  match feedback and < > navigation; Escape closes the bar.
- **"Show" filter** next to the filter box: all files / named only /
  unnamed only / failed only / encrypted only.
- **Save preview as…** (Ctrl+S) — save the selected file without
  extracting the whole archive.
- **Export file table…** — write the recovered table to CSV or JSON
  (includes the SHA-256 and the recovery source per file).
- **Open containing folder** — jump to the map in Explorer/Finder.
- **Open recent** — the last 10 archives, remembered between sessions.
- **Session memory** — window geometry, splitter layout and the filter
  mode are restored on the next start; the last used extract folder is
  offered as the default.

### Fixed
- **Crash on closing windows** — the scan worker (a QThread) was released
  from inside its own result handler, destroying the thread while
  `run()` was still on the stack. Workers are now released only after the
  thread has really finished.
- Keyboard shortcuts are kept alive explicitly instead of relying on
  garbage collection, which could tear down a live shortcut.

### Verified
- 57 tests; the GUI suite now runs three times in a row without a crash.

## 1.1.0 — 2026-10-25

**Browsing core: the table behaves like a real file manager.**

### New
- **Multi-select** — ctrl/shift-click to pick several files, so
  "Extract selected…" can now save a whole group at once.
- **Live filter box** (Ctrl+F) above the file table: type to narrow
  1297 blocks down to the ones you care about. Combines with the folder
  tree.
- **Sortable columns** — click any header (size, name, block, flags…).
  Rows stay bound to their data while sorting, so selection and
  extraction never drift.
- **"Src" column** — shows *how* each file was recovered:
  `listfile` (name from the archive's own listfile), `known` (built-in
  WC3 name list), `external` (your `--listfile`), `guess` (content magic),
  `unknown` — plus the key method: `crack` (recovered from the sector
  offset table), `named` (named-key fallback), `plain` (not encrypted).
  The same data is now in `w3xmpq list --json` and the CLI table.
- **Scan progress + Cancel** — a progress bar counts blocks while a big
  map is being cracked, and the scan can be aborted.

### Fixed
- Row filters now follow the sort order (previously the folder filter
  compared the wrong rows once the table was sorted).

### Verified
- Real maps unchanged: DotA 1297/1297, MooMoo 557/559, campaign 17/17.
  Source breakdown on DotA: 1285 files recovered by cracking the key,
  11 named from the built-in list.
- 53 tests.

## 1.0.3 — 2026-10-25

**Screenshots on the repo page + a tighter window.**

- README now shows the GUI (all-files view and folder-tree view) so the
  repo page shows what the tool actually looks like.
- The map banner is capped at two lines, giving the file table and
  preview pane the remaining height.
- New `tools/screenshot_gui.py` renders the screenshots offscreen
  (registering a system font explicitly, since the offscreen platform
  does not load fonts by default).

## 1.0.2 — 2026-10-25

**Folder tree view + real names from the archive's own listfile.**

### New
- **Folder tree pane** in the GUI (7-zip layout): folders recovered from
  file paths are shown on the left; selecting one filters the file table
  to that folder (and its subfolders). Top-level `(all files)` shows
  everything.
- **Internal `(listfile)` is now used** when present: the scanner reads
  the archive's own listfile and probes those names, so files that
  neither the built-in name list nor content guessing can identify are
  shown under their real names instead of `block_NNN`. Applies to the
  CLI too (`extract`, `list`, `diff`).

### Fixed
- **Crash on non-ASCII names** — the MPQ hash now uses the low byte of
  each character (as Storm does) instead of indexing past the encryption
  table. DotA's listfile contains such names, so listing its files
  previously raised `KeyError`.

### Verified
- No regression on the real maps: DotA v6.83dAI PMV 1297/1297 blocks,
  MooMoo v3.19b Generation X 557/559 (2 are ENCRYPTED+FIX_KEY traps by
  design), campaign maps 17/17 with real names.
- 50 tests.

## 1.0.1 — 2026-10-25

**Zip-style browsing in the GUI.**

- **Right-click menu** on the file table: Preview · Extract selected… · Copy name.
- **Extract selected…** (Ctrl+Shift+E, also on the toolbar) — save just the
  files you highlighted, like pulling single files out of a zip.
- The **first recovered file is auto-selected** after opening, so the
  preview pane shows content immediately.
- Double-clicking a row focuses the preview and reports its type (text/hex).
- Friendlier empty state explaining the browse-like-a-zip workflow.
- Core: extraction manifests now mark written entries (`extracted: true`),
  so selective extractions report accurate counts.

## 1.0.0 — 2026-10-25

**The GUI release.** w3xmpq now has a professional windowed interface and
is production-stable.

### New — GUI (`w3xmpq-gui`)
- PySide6/Qt window: drag & drop archives, file table (name / size /
  packed / flags / status), preview pane (text for scripts, hex dump for
  binary), map banner (name, author, tileset, recovery count).
- All tools available in dialogs: deprotection report, safety scan,
  WorldEdit-ready `rebuild`, two-archive diff, folder batch extraction.
- Everything heavy runs on background threads — the UI never freezes.
- Ships as standalone binaries (`w3xmpq-gui.exe` / `-linux` / `-macos`)
  alongside the CLI ones, smoke-tested headless in CI.
- CLI: `w3xmpq gui [archive]` launches the same interface (needs
  `pip install PySide6`).

### Changed
- Release workflow builds and smoke-tests **six** binaries per tag
  (CLI + GUI × Windows/Linux/macOS).
- `w3xmpq.__version__` single-sourced from package metadata.

### Stability
- 48 tests (was 46), including offscreen GUI smoke tests (open → scan →
  table/preview, background extraction).

## 0.3.0 — 2026-10-25

**Round-trip release: w3xmpq can now write archives, not just read them.**

- **`rebuild` command (beta)** — turns a protected map back into a
  standard, WorldEdit-openable archive: strips decoys, resolves the real
  script (prefers `Scripts\war3map.j` over the anti-tamper stub),
  injects minimal `wtg/wct/imp` stubs and a true `(listfile)`.
  One-way and read-only on the original.
- **`--listfile` import** — supply candidate file names (list or text
  file) when an archive has no internal `(listfile)`.
- **PKWARE DCL "explode" codec (beta)** — first step toward full legacy
  compression support (Diablo/StarCraft archives); validated on synthetic
  streams and length-guarded. Real-archive fuzzing on the roadmap.
- **`build_mpq()` library API** — create standard MPQ v0 archives
  programmatically (powers the synthetic test fixtures and `rebuild`).
- Version single-sourced from package metadata (`w3xmpq.__version__`).
- New docs: `docs/library-api.md`.
- 46 tests (was 41).

## 0.2.0 — 2026-10-25

**Analysis layer release.**

- **`report` command** — deprotection report: script-relocation detection,
  anti-tamper stub detection, missing authoring files, decoy listfiles,
  plain-English verdict + unknown-block analyzer (entropy + magic sniffing).
- **`scan` command** — map safety scan: JASS statistics and severity-ranked
  suspicious patterns (Preload file I/O, mass ExecuteFunc, player probing).
  Evidence for review — deliberately no numeric risk score.
- **`.w3x` header parsing** — map name, author, description, tileset and
  size shown as a banner on `extract`.
- Fixed a P0-era bug: the decoy `(listfile)` in protected maps was silently
  truncated by one byte (mask-byte misinterpretation on IMPLODE-flagged
  blocks); sector decoding is now flag-aware with expected-length checks.
- SECTOR_CRC no longer decoded as a data sector; SPARSE compression
  supported; named-key fallback for encrypted single-unit files.
- Archive file handles closed after extraction.

## 0.1.3 — 2026-10-25

- Friendly no-arguments screen: double-clicking `w3xmpq.exe` now shows a
  usage guide and waits for Enter instead of flashing away.

## 0.1.2 — 2026-10-25

- **Working standalone binaries** (first release with functioning .exe).
- Fixed PyInstaller packaging: relative-import crash in the frozen exe.
- Release workflow now smoke-tests built binaries before publishing.

## 0.1.1 — 2026-10-25

- Attempted binary fix (superseded by 0.1.2).

## 0.1.0 — 2026-10-25

- Initial release: MPQ/WC3 map engine, key-recovery crack, CLI
  (`open`/`list`/`extract`/`diff`/`batch`), 41 tests. Standalone binaries
  in this release were broken — use 0.1.2+.
