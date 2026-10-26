#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render GUI screenshots (offscreen) for docs/preview.

Usage: python tools/screenshot_gui.py <outdir>
"""

import os
import random
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests", "fixtures"))

from PySide6.QtCore import QEventLoop, QSettings, QTimer   # noqa: E402
from PySide6.QtGui import QFontDatabase                    # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import gen_synth                                           # noqa: E402
from w3xmpq.gui.main_window import MainWindow              # noqa: E402


def blob(name, size):
    """Deterministic pseudo-random bytes, so both demo builds agree."""
    return random.Random(name).randbytes(size)


def load_fonts():
    """The offscreen platform may not pick up system fonts — register one
    explicitly so the screenshots show real text instead of boxes."""
    for path in (r"C:\Windows\Fonts\segoeui.ttf",
                 r"C:\Windows\Fonts\consola.ttf",
                 r"C:\Windows\Fonts\arial.ttf"):
        if os.path.isfile(path):
            QFontDatabase.addApplicationFont(path)


def wait_for(win, timeout_ms=60000):
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(50)
    poll.timeout.connect(
        lambda: all(getattr(w, "worker", None) is None
                    for w in win._all_views()) and loop.quit())
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()


def shoot(win, path):
    win.grab().save(path)
    print("wrote", path)


def find_real_blp():
    """A genuine Warcraft III texture, if the game is installed."""
    base = os.path.abspath(os.path.join(_ROOT, "..", ".."))
    ui = os.path.join(base, "UI")
    if not os.path.isdir(ui):
        return None
    for dirpath, _dirs, files in os.walk(ui):
        for name in sorted(files):
            if name.lower().endswith(".blp"):
                return os.path.join(dirpath, name)
    return None


def build_demo(path, map_name, script_extra=b"", extra_files=()):
    files = [
        dict(name="war3map.j",
             data=(b"function main takes nothing returns nothing\n" * 40
                   + script_extra + b"endfunction\n" * 20),
             flags=gen_synth.F_EXISTS),
        dict(name="war3map.w3e", data=b"W3E!" + blob("w3e", 20000),
             flags=gen_synth.F_EXISTS),
        dict(name="war3map.wtg", data=b"WTG!" + blob("wtg", 8000),
             flags=gen_synth.F_EXISTS),
        dict(name="war3map.doo", data=b"unit" + blob("doo", 12000),
             flags=gen_synth.F_EXISTS),
        dict(name="textures\\cliff.blp", data=blob("cliff", 30000),
             flags=gen_synth.F_EXISTS),
        dict(name="textures\\trees.blp", data=blob("trees", 22000),
             flags=gen_synth.F_EXISTS),
        dict(name="textures\\ui\\button.blp", data=blob("button", 4000),
             flags=gen_synth.F_EXISTS),
        dict(name="Scripts\\war3map.j",
             data=b"// relocated script\n" * 400, flags=gen_synth.F_EXISTS),
    ]
    real_blp = find_real_blp()
    if real_blp:
        with open(real_blp, "rb") as fh:
            files.append(dict(name="war3mapMap.blp", data=fh.read(),
                              flags=gen_synth.F_EXISTS))
    files.extend(dict(f) for f in extra_files)
    files.append(dict(name="(listfile)",
                      data="\n".join(f["name"] for f in files).encode(),
                      flags=gen_synth.F_EXISTS))
    with open(path, "wb") as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(files),
                                    map_name=map_name.encode(),
                                    author=b"w3xmpq"))


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(outdir, exist_ok=True)
    app = QApplication([])
    load_fonts()
    # Start from a clean slate: a persisted splitter layout from a normal
    # session would otherwise change the screenshots.
    QSettings("w3xmpq", "w3xmpq").clear()

    tmp = tempfile.mkdtemp(prefix="w3xmpq_shots_")
    demo = os.path.join(tmp, "demo_arena.w3x")
    demo2 = os.path.join(tmp, "demo_arena_v2.w3x")
    build_demo(demo, "Demo Arena")
    build_demo(demo2, "Demo Arena",
               script_extra=b"    call DoNothing()\n" * 3,
               extra_files=[dict(name="war3map.w3o",
                                 data=b"W3O!" + blob("w3o", 3000),
                                 flags=gen_synth.F_EXISTS)])

    win = MainWindow()
    win.resize(1200, 720)
    win.show()
    win.open_archive(demo)
    wait_for(win)
    win.apply_folder_filter("textures")
    app.processEvents()
    shoot(win, os.path.join(outdir, "gui_tree.png"))

    win.apply_folder_filter(None)
    app.processEvents()
    win.folders.setCurrentItem(win.folders.topLevelItem(0))
    app.processEvents()
    shoot(win, os.path.join(outdir, "gui_all_files.png"))

    # 3) Texture preview — a real .blp rendered in the preview pane
    for r in range(win.table.rowCount()):
        entry = win.table.entry_at(r)
        if entry and (entry.get("name") or "").endswith("war3mapMap.blp"):
            win.table.selectRow(r)
            app.processEvents()
            shoot(win, os.path.join(outdir, "gui_texture.png"))
            break

    # 4) Script preview with JASS syntax highlighting
    for r in range(win.table.rowCount()):
        entry = win.table.entry_at(r)
        if entry and (entry.get("name") or "") == "war3map.j":
            win.table.selectRow(r)
            app.processEvents()
            shoot(win, os.path.join(outdir, "gui_script.png"))
            break

    # 5) Tabs — two archives open side by side in one window
    win.open_archive(demo2)
    wait_for(win)
    app.processEvents()
    shoot(win, os.path.join(outdir, "gui_tabs.png"))

    # 6) In-app diff — the two versions compared, both sides on screen
    view = win.open_diff(demo, demo2)
    wait_for(win)
    # Show the script change — the most readable pair of panes.
    for r in range(view.table.rowCount()):
        row = view._row_at(r)
        if row and row["kind"] == "changed" and row["name"].endswith(".j"):
            view.table.selectRow(r)
            break
    app.processEvents()
    shoot(win, os.path.join(outdir, "gui_diff.png"))

    # 7) Dark theme, back on a texture
    win.tabs.setCurrentIndex(0)
    win._set_dark(True)
    for r in range(win.table.rowCount()):
        entry = win.table.entry_at(r)
        if entry and (entry.get("name") or "").endswith("war3mapMap.blp"):
            win.table.selectRow(r)
            break
    app.processEvents()
    shoot(win, os.path.join(outdir, "gui_dark.png"))
    win.close()
    # Leave the developer's own settings exactly as they were.
    QSettings("w3xmpq", "w3xmpq").clear()


if __name__ == "__main__":
    main()
