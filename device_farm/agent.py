#!/usr/bin/env python3
"""Shim — PC agent: ``scripts/agent_pc.py``."""

from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from scripts.agent_pc import main

if __name__ == "__main__":
    main()
