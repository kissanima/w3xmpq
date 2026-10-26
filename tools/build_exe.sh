#!/usr/bin/env bash
# Build the frozen Windows exes.
#
#   ./tools/build_exe.sh          # both
#   ./tools/build_exe.sh cli      # CLI only
#   ./tools/build_exe.sh gui      # GUI only
#
# Runs from the repo root, using the managed Python venv.
#
# IMPORTANT: the CLI must exclude the GUI-only packages. PyInstaller follows
# `w3xmpq/__init__.py`'s lazily-imported names and happily bundles PySide6 +
# numpy into a 65 MB "console" exe. Excluding them brings it back to 7.6 MB.
# The GUI build must NOT exclude PySide6.
set -euo pipefail

PY="C:/Users/AHLAN WA SAHLAN/.workbuddy-ai/binaries/python/envs/default/Scripts/python.exe"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CLI_EXCLUDES=(
    --exclude-module PySide6
    --exclude-module shiboken6
    --exclude-module numpy
    --exclude-module tkinter
    --exclude-module PIL
    --exclude-module matplotlib
    --exclude-module PyQt5
    --exclude-module pytest
)

build_cli() {
    echo "== building w3xmpq.exe =="
    "$PY" -m PyInstaller --noconfirm --clean --onefile --console \
        --name w3xmpq "${CLI_EXCLUDES[@]}" \
        src/w3xmpq/_launch.py
}

build_gui() {
    echo "== building w3xmpq-gui.exe =="
    "$PY" -m PyInstaller --noconfirm --clean --onefile --windowed \
        --name w3xmpq-gui \
        src/w3xmpq/_launch_gui.py
}

case "${1:-both}" in
    cli) build_cli ;;
    gui) build_gui ;;
    both) build_cli; build_gui ;;
    *) echo "usage: $0 [cli|gui|both]" >&2; exit 2 ;;
esac

echo
ls -la dist/*.exe
