#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render GUI screenshots (offscreen) for docs/preview.

Usage: python tools/screenshot_gui.py <outdir>
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests", "fixtures"))

from PySide6.QtCore import QEventLoop, QTimer          # noqa: E402
from PySide6.QtGui import QFontDatabase                # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

import gen_synth                                       # noqa: E402
from w3xmpq.gui.main_window import MainWindow          # noqa: E402


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
        lambda: getattr(win, "worker", None) is None and loop.quit())
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


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(outdir, exist_ok=True)
    app = QApplication([])
    load_fonts()

    # 1) A map with folders -> shows the tree in action
    files = [
        dict(name="war3map.j",
             data=b"function main takes nothing returns nothing\n" * 200,
             flags=gen_synth.F_EXISTS),
        dict(name="war3map.w3e", data=b"W3E!" + os.urandom(20000),
             flags=gen_synth.F_EXISTS),
        dict(name="war3map.wtg", data=b"WTG!" + os.urandom(8000),
             flags=gen_synth.F_EXISTS),
        dict(name="war3map.doo", data=b"unit" + os.urandom(12000),
             flags=gen_synth.F_EXISTS),
        dict(name="textures\\cliff.blp", data=os.urandom(30000),
             flags=gen_synth.F_EXISTS),
        dict(name="textures\\trees.blp", data=os.urandom(22000),
             flags=gen_synth.F_EXISTS),
        dict(name="textures\\ui\\button.blp", data=os.urandom(4000),
             flags=gen_synth.F_EXISTS),
        dict(name="Scripts\\war3map.j",
             data=b"// relocated script\n" * 400, flags=gen_synth.F_EXISTS),
    ]
    real_blp = find_real_blp()
    if real_blp:
        with open(real_blp, "rb") as fh:
            files.append(dict(name="war3mapMap.blp", data=fh.read(),
                              flags=gen_synth.F_EXISTS))
    files.append(dict(name="(listfile)",
                      data="\n".join([f["name"] for f in files]).encode(),
                      flags=gen_synth.F_EXISTS))
    demo = os.path.join(tempfile.gettempdir(), "w3xmpq_screenshot_demo.w3x")
    with open(demo, "wb") as f:
        f.write(gen_synth.build_w3x(gen_synth.build_archive(files),
                                    map_name=b"Demo Arena",
                                    author=b"w3xmpq"))

    win = MainWindow()
    win.resize(1200, 700)
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
    win.close()


if __name__ == "__main__":
    main()
