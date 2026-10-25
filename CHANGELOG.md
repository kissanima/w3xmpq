# Changelog

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
