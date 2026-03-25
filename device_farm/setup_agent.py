#!/usr/bin/env python3
"""Shim — Termux/setup: ``scripts/setup_agent.py``."""

from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from scripts.setup_agent import main

if __name__ == "__main__":
    main()
