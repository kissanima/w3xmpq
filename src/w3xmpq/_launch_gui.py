#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller entry point for the w3xmpq GUI (w3xmpq-gui.exe).

Use this file (not a __main__.py) for frozen builds — same reason as
_launch.py: running package files directly breaks relative imports.

`--version` is handled HERE, before anything imports PySide6: loading
Qt requires system GUI libraries (libEGL etc.) which headless machines
and CI runners may not have, and release CI smoke-tests the frozen
binary with this flag.
"""

import sys


def _early_exit(argv):
    if "--version" in argv or "-V" in argv:
        # Read the version without touching the GUI package (which pulls
        # in PySide6).
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(
            os.path.abspath(__file__)), ".."))
        try:
            from importlib.metadata import version as _v
            print("w3xmpq %s (GUI)" % _v("w3xmpq"))
        except Exception:
            from w3xmpq import __version__
            print("w3xmpq %s (GUI)" % __version__)
        return 0
    return None


if __name__ == "__main__":
    code = _early_exit(sys.argv[1:])
    if code is not None:
        sys.exit(code)
    from w3xmpq.gui.main_window import main
    sys.exit(main())
