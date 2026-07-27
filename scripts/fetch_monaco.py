#!/usr/bin/env python3
"""Deprecated alias for scripts/fetch_vendor.py.

The Code tab vendors xterm.js as well as Monaco now, so fetching lives in one
place. Kept because earlier instructions (and the editor's own
"assets missing" message) reference this filename.
"""
from __future__ import annotations

import sys

from fetch_vendor import PACKAGES, fetch_package, is_monaco_available, main  # noqa: F401

if __name__ == "__main__":
    print("Note: scripts/fetch_monaco.py now delegates to scripts/fetch_vendor.py.\n")
    sys.exit(main())
