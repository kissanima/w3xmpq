# Changelog

## 0.1.0 — 2026-10-25

Initial release.

- Open `.w3x` / `.w3m` maps and plain `.mpq` archives (MPQ format 0/1).
- Key-recovery engine: known-plaintext attack on the sector offset table —
  no listfile, no filenames needed.
- Sector decoding: zlib / bzip2 / stored, SECTOR_CRC, SPARSE, SINGLE_UNIT,
  named-key fallback for encrypted single-unit files.
- Content-based naming: hash-probing of known WC3 paths + magic-byte
  sniffing; `Scripts\war3map.j` → `war3map_script.j` canonical rename.
- Commands: `open`, `list`, `extract` (regex filter, quiet, JSON manifest
  with SHA-256), `report` (deprotection report), `scan` (map safety scan),
  `diff` (content comparison), `batch` (bulk extraction with index).
- Exit codes 0/1/2; `--json` on every command.
- 41 tests with synthetic encrypted fixtures (no copyrighted data).
