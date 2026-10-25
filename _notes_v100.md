## v1.0.0 — The GUI release

**w3xmpq now has a professional windowed interface — and ships as two apps.**

### New — GUI
- `w3xmpq-gui` binaries for Windows / Linux / macOS (below), or `w3xmpq gui map.w3x` from the CLI package (`pip install PySide6`).
- **Drag & drop** any `.w3x` / `.w3m` / `.mpq` onto the window.
- **File table** — every recovered block with name, original/packed size, flag codes (E=encrypted, Z=compressed, S=single-unit, C=crc, P=sparse) and status.
- **Preview pane** — JASS/script/text files as text, everything else as a hex dump.
- **Map banner** — map name, author, tileset and recovery count at a glance.
- **Tools menu** — deprotection report, safety scan, WorldEdit-ready rebuild, two-archive diff, folder batch extraction — all in dialogs.
- All work runs on background threads; the UI never freezes.

### Changed
- Release workflow now builds and smoke-tests **six** binaries per tag (CLI + GUI × Windows/Linux/macOS).
- Version single-sourced from package metadata.

### Stability
- 48 tests, including offscreen GUI smoke tests (open → scan → table/preview, background extraction).

### Binaries
| | Windows | Linux | macOS |
|---|---|---|---|
| CLI | `w3xmpq.exe` | `w3xmpq-linux` | `w3xmpq-macos` |
| GUI | `w3xmpq-gui.exe` | `w3xmpq-gui-linux` | `w3xmpq-gui-macos` |

**Full changelog**: https://github.com/kissanima/w3xmpq/blob/main/CHANGELOG.md

