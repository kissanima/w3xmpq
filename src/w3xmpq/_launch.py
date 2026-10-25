#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller entry point for w3xmpq.

Use this file (not __main__.py) for frozen builds — running __main__.py
directly breaks package-relative imports.
"""

import sys

from w3xmpq.cli import main

if __name__ == "__main__":
    sys.exit(main())
