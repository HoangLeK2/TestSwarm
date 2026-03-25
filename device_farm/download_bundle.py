#!/usr/bin/env python3
"""Shim — bundle downloader: ``scripts/download_bundle.py``."""

from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from scripts.download_bundle import main

if __name__ == "__main__":
    main()
