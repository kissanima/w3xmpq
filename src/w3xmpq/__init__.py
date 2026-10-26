#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq — open, inspect and extract any MPQ archive or Warcraft III map.

No listfile, no filenames, no keys required: w3xmpq recovers every file's
MPQ encryption key from the data itself via a known-plaintext attack on the
sector offset table.
"""

__version__ = None
try:
    from importlib.metadata import version as _version
    __version__ = _version("w3xmpq")
except Exception:
    __version__ = "1.4.0"          # source checkout without installation

from .core.mpq import MPQArchive                      # noqa: F401
from .core.extract import open_archive, extract_archive  # noqa: F401
from .core.keycrack import recover_base_key           # noqa: F401
from .core.sectors import extract_block               # noqa: F401
