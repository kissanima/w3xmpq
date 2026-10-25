# w3xmpq — Open-Source Release Plan (v3)

> Plan for turning `Tools/mpq_extract.py` (188 lines of research code) into a
> polished open-source tool: **w3xmpq — open, inspect and extract any MPQ
> archive or Warcraft III map.**
>
> v2 changes: renamed **WarCrack → w3xmpq**; scope widened to **generic MPQ +
> WC3 maps**; UI redesigned **GUI-first**.
> v3 changes: added **§2 Use cases & personas** — every feature is now tagged
> with the use case(s) it serves (`UC-x`); roadmap gained batch mode, map
> safety scan, archive diff, asset export, and a public library API.
>
> Status: **SHIPPED v1.0.0** (2026-10-25) — CLI + GUI + analysis layer +
> rebuild mode, 48 tests, published at github.com/kissanima/w3xmpq.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | **w3xmpq** (repo/package/CLI all lowercase; display "w3xmpq") |
| **Tagline** | *Open any MPQ. Crack any map. No listfile, no keys, no editor required.* |
| **One-liner** | Pure-Python tool that opens `.mpq` archives and Warcraft III `.w3x`/`.w3m` maps, recovers every file — including encrypted/protected ones — via a known-plaintext attack on the MPQ sector offset table, and lets you browse, preview and extract them through a professional GUI. |
| **Why it matters** | Existing tools (Ladik's MPQ Editor, `mpyq`, etc.) need a listfile and fail on encrypted files. w3xmpq needs **neither** — it recovers each file's key from the data itself. Verified: MooMoo v3.19b (557/559 files), DotA 6.83d AI (1297/1297, 0 failures). |
| **License** | MIT (mpyq is MIT-derived; keep permissive). |
| **Core deps** | Python 3.9+, **zero required dependencies** (stdlib zlib/bz2). Optional extras: `w3xmpq[gui]` → PySide6 (Qt6); `w3xmpq[pretty]` → `rich` (fancy CLI/TUI); `w3xmpq[image]` → Pillow (BLP→PNG export). |
| **Two-layer scope** | **Layer 1 — MPQ engine**: format-agnostic MPQ reader/cracker (any MPQ v0/v1 archive). **Layer 2 — WC3 map layer**: `.w3x` header parsing, known filename probing, object-data awareness, deprotection & safety reporting. The GUI sits on top of both. |

**Ethics framing (README + About dialog):** for recovering **your own** locked
maps, format study, modding, and game preservation. Not for stealing other
people's work and re-publishing it.

---

## 2. Use cases & personas

Eight concrete use cases drive the feature list. Every feature in §3 is tagged
with the UC(s) it serves.

| # | Persona | Their situation | Success looks like |
|---|---|---|---|
| **UC-1** | **Curious player** | Downloaded a cool map, wonders what's inside (skins, models, music) — has zero technical skill. | Drag the `.w3x` onto the window → sees a readable file list with previews → clicks "Extract All" → gets organized folders. |
| **UC-2** | **Map author who lost the source** | The classic WC3 tragedy: author protected their map years ago and lost the editor copy. They still own the game-ready `.w3x`. | Runs the deprotection report → understands exactly how their map is locked → uses "Rebuild for WorldEdit" → opens the recovered map in WE and continues development. |
| **UC-3** | **Modder / asset creator** | Wants BLP textures, MDX models, mp3s from maps for their own projects. | Filters by type, previews textures in-app, batch-exports a typed asset tree (BLP→PNG optional), never touches encrypted-file errors. |
| **UC-4** | **Community reviewer / host admin** | Screens user-uploaded maps before hosting: cheats, malicious scripts, hidden imports. | Opens a map → gets a *map safety scan*: suspicious JASS patterns, hidden imports, anti-tamper tricks, full trigger stats — as a shareable report. |
| **UC-5** | **Security researcher** | WC3 map malware is a real genre. Wants raw evidence, not a pretty summary. | Raw sector dumps, key forensics per file, unknown-block entropy analyzer, `--json` output for tooling, read-only guarantee. |
| **UC-6** | **Archivist / preservationist** | Has thousands of maps (EpicWar dumps etc.) to catalogue and preserve. | Headless batch mode over a folder → per-map manifests + SHA-256 index → duplicates identified → failures logged, run continues. |
| **UC-7** | **Developer / tool builder** | Wants to build their own tooling on top (map manager, stat site, patcher). | `pip install w3xmpq` → stable documented library API (`Archive`, `recover_keys()`, `extract()`) with typed returns — the CLIs are thin shells over it. |
| **UC-8** | **Version curator** | Comparing map versions ("what changed between 6.83c and 6.83d?"). | `w3xmpq diff old.map new.map` → per-file table: added / removed / resized / byte-identical (via hashes) → drill into changed files. |
| **UC-9** | **Classic-Blizzard modder / asset extractor** | Works with game *data* archives, not maps: `DIABDAT.MPQ` (Diablo 1), `d2data.mpq`/`d2exp.mpq` (D2), StarCraft archives, `War3.mpq`. Wants sprites/sounds/TBL files for modding and preservation. | `w3xmpq list DIABDAT.MPQ` → real filenames from the (decrypted) listfile → selective extraction of asset types. Engine needs the old codecs: PKWARE DCL implode (0x08), huffman (0x01), ADPCM audio masks (0x40/0x80). WoW MPQ v2–v4 (HET/BET) stays a stretch goal. |

**Anti-use-cases (explicitly out of scope):** editing map contents in place
(we're read-only); running map scripts (no JASS execution — that's a VM
project, ours is static); bypassing Blizzard ToS for online play.

---

## 3. Feature Plan

### MVP — v0.1 (ship first)
1. **Open both formats** *(UC-1…7)*: any `.mpq`/`.w3x`/`.w3m` (MPQ formats 0/1). Drag-and-drop or CLI — same engine underneath.
2. **Key-recovery engine** *(UC-1…6)*: known-plaintext attack on the sector offset table — `p0 = 4*(sectors+1)`, 256×256 candidate search, monotonic-table verification. **No listfile, no filenames needed.**
3. **Correct format-0 sector scheme** *(all)*: offset table = base key; sector *i* = `base + i + 1`; trailing `len % 4` bytes stay plaintext (the three bugs that break every other tool).
4. **Compression**: none (0x00), zlib (0x02), bzip2 (0x10) — full WC3-era coverage.
5. **Content-based naming** *(UC-1, UC-3, UC-6)*: hash-probe ~200 known WC3 paths + magic-byte detection (`W3E!`, `W3a!`, `MDX_`, `BLP1`, generic signatures) → proper names/extensions; leftovers `block_NNN`.
6. **Extraction manifest with SHA-256** *(UC-5, UC-6, UC-8)*: `manifest.json` + `manifest.csv` — name, guessed name, size, flags, key, confidence, **per-file SHA-256** (enables dedupe & version diffing later).
7. **Progress & summary** in every interface (GUI progress bar, CLI progress line).
8. **Read-only guarantee** *(all, esp. UC-4/5)*: source file is never opened for writing — enforced in code, stated in About.

### v0.2 — Analysis layer
9. **Map header parser** *(UC-1, UC-4)*: 512-byte user-data header → map name, author, players, editor version, flags — banner in GUI's info panel.
10. **Deprotection report** *(UC-2, UC-4)* — killer feature: real script at `Scripts\war3map.j` with canonical name deleted; "Disabled Single Player" anti-tamper stubs; deleted authoring files (`wtg`/`wct`/`w3t`/`w3q`/`imp`/`w3u`); decoy `(listfile)`; verdict + what's missing to make it WorldEdit-openable. Shareable text output.
11. **JASS quick-stats + map safety scan** *(UC-4, UC-5)*: trigger/native-call frequency table, custom globals, AI chat commands; **suspicious-pattern scan** (known cheat trigger idioms, `Preload`-style file I/O abuse, mass `ExecuteFunc`, anti-host logic, hidden imports) — findings ranked by severity, "for review" framing (not a verdict).
12. **Unknown-block analyzer** *(UC-5)*: for unnamed blocks — entropy estimate, magic sniffing, sector-structure dump: evidence for deciding what a blob is.

### v0.3 — Reach & scale
13. **Batch mode** *(UC-6)*: `w3xmpq batch <dir> -o out/` — walk a folder of maps, per-archive manifest, global CSV index (map name, file counts, SHA-256 of map), errors logged and skipped, resumable.
14. **Archive diff** *(UC-8)*: `w3xmpq diff A B` — file-table comparison using SHA-256: added / removed / resized / identical; JSON + human table; GUI side-by-side view in v1.0.
15. **MPQ v1 extras** *(all)*: SPARSE compression, SINGLE_UNIT files, sector CRC verification.
16. **Packaging** *(UC-1, UC-7)*: `pipx install w3xmpq`; PyPI; GitHub Release with PyInstaller one-file binaries **including the GUI** — non-technical users never install Python.
17. **Public library API** *(UC-7)*: freeze `w3xmpq.Archive` / `recover_keys()` / `extract()` as the documented stable surface; API docs generated; CLI/TUI/GUI consume only it (keeps shells honest).
18. **Old-MPQ codecs** *(UC-9)*: pure-Python PKWARE DCL implode (mask 0x08) decompressor, huffman (0x01), ADPCM audio masks (0x40/0x80) — the compression used by Diablo 1/2 and StarCraft era archives. Required before the library API freeze.
19. **Listfile workflows** *(UC-9)*: real filenames from decrypted `(listfile)`s (already readable); `--listfile <file>` import for nameless entries; `list` command output with real names.

### v1.0 — Full professional experience
20. **GUI v1** *(UC-1…5, UC-8)* — the primary interface (see §4.2): three-pane main window, hex/text/image/table previews, key forensics details pane, drag-and-drop, diff view side-by-side, batch queue tab.
21. **Rebuild-editor-openable map** *(UC-2)* (`--rebuild` / GUI action): needs an MPQ *writer* — rename `Scripts\war3map.j` → `war3map.j`, inject minimal stubs so WorldEdit opens the recovered map.
    - **WorldEdit integration model (decided):** no API/plugin bridge exists in 1.29-era WorldEdit — connection is a **one-way file hand-off**: w3xmpq writes a new *standard* MPQ (unencrypted, canonical names, restored `(listfile)`, injected stubs) and WorldEdit opens it natively.
22. **Asset export mode** *(UC-3, UC-9)*: extract only textures/models/audio into typed trees; optional **BLP1→PNG** conversion via the `[image]` extra.
23. **Structured viewers** *(UC-1, UC-3, UC-4)*: parsed grids for `w3a`/`w3u`/`w3e`/`wts` ability/unit/terrain/string data, sortable in GUI.

---

## 4. UI Design — three interfaces, one engine

Design principle: **GUI-first for everyone, CLI for automation, TUI as the
power-user middle ground.** All three share the same core (`core/` package) —
UIs are thin shells (this is also the UC-7 library guarantee). A professional
workflow: *open anything instantly → see exactly what's inside (key/flag
transparency) → preview files → extract precisely what you need → get a
machine-readable manifest.*

### 4.1 CLI (automation / power users) *(UC-5, UC-6, UC-7, UC-8)*

```
$ w3xmpq open   "DotA v6.83dAI PMV 1.42 EN.w3x"    # inspect only
$ w3xmpq list   map.mpq --filter "war3map"         # virtual file table
$ w3xmpq extract map.mpq -o out/ --filter REGEX    # full or selective extraction
$ w3xmpq report "MooMoo v3.19b.w3x"                # deprotection report
$ w3xmpq scan   map.w3x                            # map safety scan
$ w3xmpq diff   old.w3x new.w3x                    # version comparison
$ w3xmpq batch  ./maps/ -o out/                    # bulk processing
$ w3xmpq gui                                       # launch the desktop app
```

Plain-text fallback everywhere; `rich` when installed; exit codes 0/1/2
(ok/partial/fatal); `--json` for machine output.

### 4.2 GUI (primary — designed for professional use) *(UC-1…5, UC-8)*

**Toolkit: PySide6 (Qt6)** — the professional desktop standard: native widgets,
docking panels, real tables/trees, fast hex views, dark/light themes, works on
Windows/Linux/macOS. Optional extra; included in the PyInstaller binaries.

**Main window (three-pane + status, docking/resizable):**

```
┌ w3xmpq — DotA v6.83dAI PMV 1.42 EN.w3x ─────────────────────────────────────┐
│ File  Edit  View  Extract  Tools  Help                                      │
│ [Open…] [Extract All…] [Extract Selected] [Report] [Scan] [Rebuild for WE] │
├──────────────────────────────┬──────────────────────────────┬───────────────┤
│ ARCHIVE  (1297 files)        │ PREVIEW                      │ DETAILS       │
│ 🔍 filter: war3map           │ [Hex] [Text] [Image] [Table] │ name: war3map │
│ ▾ war3map_script.j   4.16 MB │ 00000000  57 33 45 21 ...    │  _script.j    │
│   war3map.w3a        1.03 MB │ 00000010  6A 33 4D 61 ...    │ size: 4164351 │
│   war3map.w3e      116 KB    │                              │ key: 0x1A2B.. │
│   …                          │                              │ flags: ENC|   │
│ (columns: name · size ·      │                              │ sectors: 1018 │
│  encrypted · compressed ·    │                              │ compression:  │
│  key confidence · SHA-256)   │                              │  zlib         │
├──────────────────────────────┴──────────────────────────────┴───────────────┤
│ log: recovered 1297/1297 keys · 0 failures            ████████░░ 78%       │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pane behavior:**
- **Archive pane** *(UC-1, UC-3)* — virtual file table (tree when hierarchy known): columns *name/guessed name, size, encrypted, compressed, key confidence, SHA-256*; instant filter; sortable; colored badges for protected/decoy/unknown entries.
- **Preview pane** *(UC-1, UC-3)* — tabbed by type: **Hex** (fast virtual-scroll with ASCII gutter), **Text/JASS** (syntax-highlighted), **Image** (BLP1→PNG live), **Table** (structured `w3*` grids, v1.0).
- **Details pane** *(UC-5)* — selected-file forensics: block index, flags, sizes, sector count, codec, **recovered key**, offset-table verification status.
- **Status/log bar** — live, cancellable progress; dockable full log panel.

**Tool dialogs:**
- **Report dialog** *(UC-2, UC-4)* — deprotection findings in plain English, copyable/exportable.
- **Safety-scan dialog** *(UC-4)* — severity-ranked findings with jump-to-file links.
- **Diff view** *(UC-8)* — two archives side-by-side, changed files highlighted, click to compare previews.
- **Batch queue** *(UC-6)* — folder picker, live per-map progress table, aggregate index summary. (v1.0; until then batch is CLI-only.)

**UX flows (non-technical):** drag & drop opens; "Extract All…" → folder dialog → progress → "Open folder"; Report/Scan buttons produce readable dialogs; read-only by design.
**UX flows (professionals):** selective extraction via filter/context menu; `--json` manifests; key-confidence column makes trust explicit; multi-archive tabs; "Rebuild for WorldEdit" hand-off; theme/hex/naming settings.

### 4.3 TUI (power-user middle ground, `w3xmpq tui`) *(UC-5, UC-7)*

`rich`-based: the same three-pane concept in the terminal — archive table with
vim-ish keys (`j/k` move, `/` filter, `enter` preview, `e` extract, `q` quit).
Optional extra; CLI and GUI never require it.

### 4.4 Output tree (on disk — identical across UIs)

```
out/
  manifest.json / manifest.csv        # incl. SHA-256 per file
  index.csv                           # batch mode: one row per map
  war3map_script.j                    # canonical rename when Scripts\war3map.j found
  war3map.w3e  war3map.w3a  war3map.wts  ...
  textures/  models/  audio/  text/   # typed subfolders (BLP/MDX/mp3)
  unknown/block_1291.bin
  _report.txt                         # deprotection report (+ safety scan when run)
```

---

## 5. GitHub Repo Page

**Repo:** `github.com/<user>/w3xmpq` — description:
*"🔓 Open any MPQ archive or Warcraft III map — recovers encrypted files via a known-plaintext attack, no listfile needed. Pure Python, professional GUI."*
**Topics:** `mpq` `warcraft3` `wc3` `dota` `reverse-engineering` `game-preservation` `jass` `extractor` `python` `qt` `pyside6`

### README layout (top → bottom)
1. **Banner**: wide SVG wordmark `w3xmpq` (dark bg, hex/MPQ aesthetic).
2. **Badges**: CI · PyPI · Python ≥3.9 · License MIT · Downloads.
3. **Screenshots**: GUI hero screenshot first (the #1 conversion asset), then a short CLI GIF.
4. **Who is it for?** — one line per persona from §2 (player · author · modder · reviewer · researcher · archivist · developer), each linking to a use-case demo.
5. **Why?** — other tools need listfiles & fail on encrypted files; w3xmpq recovers keys from the data itself; proven on real protected maps (table: MooMoo 557/559, DotA 6.83d 1297/1297).
6. **Install**: `pipx install "w3xmpq[gui]"` (GUI) / `pipx install w3xmpq` (CLI) / standalone binary / from source.
7. **Quickstart**: drag-and-drop GIF + the CLI one-liners from §4.1.
8. **How the crack works** (short): 3-step diagram + link to `docs/how-it-works.md` (MPQ hash tables, offset-table plaintext `4*(sectors+1)`, 256×256 candidate search, key scheme `sector_i = base+i+1`, plaintext tail rule).
9. **Deprotection patterns** table: script-fallback path, anti-tamper stubs, deleted authoring files, decoy listfiles — with what w3xmpq reports for each.
10. **FAQ**: legal/ethics · Reforged support (roadmap) · rebuild for WorldEdit (v1.0) · "can it edit maps?" (no — read-only by design) · library usage example (UC-7).
11. **Credits**: `mpyq` (metadata), StormLib docs (constants), Ladik's MPQ Editor (inspiration), WC3 modding community (Hive Workshop).
12. **Ethics notice** + **Contributing** + **License**.

### Repo structure
```
w3xmpq/
  pyproject.toml            # src layout, extras: gui / pretty / image
                            # entry points: console w3xmpq ; gui w3xmpq-gui
  LICENSE  README.md  CHANGELOG.md
  src/w3xmpq/
    core/                   # layer 1 + 2, no UI imports — the library (UC-7)
      archive.py            # MPQ open, hash/block tables, hash-probe
      keycrack.py           # known-plaintext key recovery
      sectors.py            # sector split, key scheme, decompression
      names.py              # hash-probe list + magic-byte TYPE_HINTS
      w3x_header.py         # .w3x 512-byte header parser (layer 2)
      report.py             # deprotection report (layer 2)
      safety.py             # JASS stats + suspicious-pattern scan
      diff.py               # manifest-based archive comparison
      batch.py              # folder walker + global index
      manifest.py           # manifest writer (JSON/CSV, SHA-256), output tree
    cli/main.py             # argparse shell
    tui/app.py              # rich shell (optional)
    gui/                    # PySide6 shell (optional)
      main_window.py  archive_model.py  preview.py  details.py
      report_dialog.py  scan_dialog.py  diff_view.py
      workers.py            # key-recovery in QThread, cancellable
  tests/
    fixtures/gen_synth.py   # generates synthetic encrypted MPQ fixtures
                            # (no copyrighted data in the repo!)
    test_keycrack.py test_sectors.py test_archive.py
    test_manifest.py test_safety.py test_diff.py test_batch.py test_cli.py
  docs/
    how-it-works.md  file-formats.md  deprotection-patterns.md
    library-api.md          # UC-7: public API reference + examples
  .github/workflows/ci.yml  release.yml   # test matrix 3.9–3.13; PyPI+binaries on tag
```

**Critical CI detail:** we can't commit real maps (copyright). `gen_synth.py` builds tiny synthetic MPQs with known keys from scratch — regression-testing the crack in pure CI. Optional local `test_real/` hook runs only if the user drops maps in.

### Release strategy
- **Repo contents (decided)**: source in the repo tree; **built `.exe` binaries attached to the GitHub Releases page** (never committed into the source tree — standard OSS pattern); README.md is the description/front page.
- **v0.1.0**: core + CLI, tested, documented. Announce on Hive Workshop + r/WC3.
- **v0.2.0**: deprotection report + safety scan → second wave ("it tells you *how* your map is protected and *what to check*").
- **v0.3.0**: PyPI + **GUI binaries** + batch/diff + library API (bigger audience: non-Python users, archivists, developers).
- **v1.0.0**: full GUI (structured viewers, diff view, batch queue, rebuild mode) → r/programming-adjacent + Hacker News attempt.

### Decisions recommended (2026-10-25, awaiting user confirmation)
- **Safety scan**: static pattern list with severity labels (info/warning/suspicious) — **no numeric "risk score"** for now (false confidence + false-positive drama); risk score only later as opt-in.
- **MVP scope**: ship v0.1 **CLI-only** — the crack engine is the hard part and needs real-user testing early; GUI follows in v0.3 with the binaries.

---

## 6. Build Order (when we implement)

| Phase | Work | Exit criteria |
|---|---|---|
| ~~**P0 — scaffold**~~ ✅ DONE 2026-10-25 | repo folder, `pyproject.toml`, MIT LICENSE, port `mpq_extract.py` into `core/` modules | ~~`w3xmpq --help` runs~~ ✓ (v0.1.0 installed editable in managed venv; `open` + `extract` subcommands live) |
| ~~**P0b — engine salvage (decided)**~~ ✅ DONE 2026-10-25 | **Rebuild the scaffolding, salvage the engine.** Proven core (`recover_base_key`, `extract_block`, `dec_full`, hash-probe, TYPE_HINTS) ported nearly verbatim into `core/` (`mpq.py` vendored from mpyq 0.2.5 MIT — zero deps, no temp files, BytesIO for embedded maps, SHA-256 manifest). | ~~reproduces 1297/1297 + 557/559~~ ✓ verified byte-exact: DotA `war3map_script.j` 4,164,351 B + `w3a` 1,031,633 B; MooMoo script 1,191,011 B + `w3a` 114,045 B (outputs in `_verify/`, gitignored) |
| ~~**P1 — core hardening**~~ ✅ DONE 2026-10-25 | synthetic-fixture tests (`tests/`: gen_synth MPQ writer + encryptor, flag matrix: stored/zlib/bzip2/encrypted/SINGLE_UNIT/SECTOR_CRC/SPARSE/FIX_KEY/named-key, 25 tests, stdlib unittest); engine fixes: flag-aware sector decoding with expected-length verification (`_decode_sector`), SECTOR_CRC loop fix, SPARSE support, named-key fallback (`recover_named_key`), archive file-handle close, no temp files; known limitation: PKWARE DCL implode (flag 0x100 / mask 0x08, very old maps) not decoded. | ~~100 % fixture pass, both real maps 0 failures~~ ✓ 25/25 tests; DotA 1297/1297 (block 1278 IMPLODE decoy now extracted raw & correct — 206 B vs P0's mask-eaten 205 B, a P0 bug fixed); MooMoo 557/559 byte-identical |
| ~~**P2 — CLI**~~ ✅ DONE 2026-10-25 | full argparse surface: `open` / `list` / `extract` (--filter, --json, -q) / `diff` / `batch` (+ `--json`, exit codes 0/1/2); refactored `scan_archive` as the single decryption pass shared by all consumers; content-multiset diff (UC-8); batch with index.csv/json (UC-6) | ~~matches §4.1~~ ✓ 34/34 tests incl. new diff/batch/list CLI tests; `list`+`open` verified on real MooMoo map |
| ~~**P3 — analysis**~~ ✅ DONE 2026-10-25 | `core/w3x_header.py` (HM3W header: name/author/desc/tileset/size/flags), `core/report.py` (deprotection report: script relocation, anti-tamper stubs, missing authoring files, decoy listfile, verdict + unknown-block analyzer with entropy & magic sniffing), `core/safety.py` (JASS stats + severity-ranked suspicious patterns, no risk score per decision), CLI `report`/`scan` + extract banner | ~~reports match known ground truth~~ ✓ verified on real DotA map: all 3 expected findings + verdict correct |
| ~~**P4+P5 — GUI (v1.0)**~~ ✅ DONE 2026-10-25 *(UC-1/3/4/5)* | PySide6 window shipped as `w3xmpq-gui` binaries + `w3xmpq gui` subcommand: drag & drop, file table (name/size/flags/status), text+hex preview, map banner, report/scan/rebuild/diff/batch dialogs, all workers on QThreads; offscreen smoke tests in CI; `--version` headless smoke for frozen binary | ~~usable by a non-technical user end-to-end~~ ✓ 48/48 tests; v1.0.0 released with 6 binaries (CLI+GUI × win/linux/mac) |
| ~~**P6 — docs & CI**~~ ✅ DONE 2026-10-25 | README (full, with real report output), docs/how-it-works.md, docs/deprotection-patterns.md, docs/library-api.md, CHANGELOG, CONTRIBUTING, bug-report template, CI workflow (3.9–3.13 × Ubuntu/Windows matrix), release workflow (CLI+GUI binaries on tag → auto-attach to GitHub Release, per-release patch notes), pyproject URLs | ~~green CI, README complete~~ ✓ published |
| ~~**P7 — release**~~ ✅ DONE 2026-10-25 | `github.com/kissanima/w3xmpq` created (public), main pushed, tags v0.1.0→v1.0.0 → release workflow builds w3xmpq(.exe/-linux/-macos) **and** w3xmpq-gui(.exe/-linux/-macos), attaches them to the auto-created GitHub Release; full patch notes retro-applied to every release | ~~public repo live~~ ✓ |
| **P8+ (post-1.0)** | huffman/ADPCM + real-DCL fuzzing (UC-9), MPQ v2–v4, structured viewers (w3u/wtg), TUI, PyPI publish | per roadmap |

---

## 7. Open decisions (for the user)
1. ~~Name~~ → **w3xmpq** ✔ (2026-10-25)
2. ~~GitHub account~~ → **`kissanima`** ✔ (device-flow login 2026-10-25; gh CLI 2.103.2 authenticated, scopes: repo/workflow/read:org) — repo will be `github.com/kissanima/w3xmpq`
3. ~~License~~ → MIT ✔ (recommended; shout if you prefer GPL-3.0)
4. **MVP scope** → CLI-only v0.1 ✔ recommended (see §5)
5. ~~GUI toolkit~~ → PySide6 ✔ (recommended; alternative: local web UI)
6. **Safety scan scope** → static pattern list + severity labels ✔ recommended, no risk score (see §5)
