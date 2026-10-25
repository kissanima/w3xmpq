#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller entry point for the w3xmpq GUI (w3xmpq-gui.exe).

Use this file (not a __main__.py) for frozen builds — same reason as
_launch.py: running package files directly breaks relative imports.
"""

import sys

from w3xmpq.gui.main_window import main

if __name__ == "__main__":
    sys.exit(main())
