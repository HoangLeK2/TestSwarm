"""
relay/ — ADB relay package.

Re-exports used by main.py:
  from relay import RelayAgent
  from relay import start_mdns_discovery, _list_serials
"""
from __future__ import annotations

from relay.agent import RelayAgent              # noqa: F401
from relay.mdns  import start_mdns_discovery   # noqa: F401
from relay.adb   import _list_serials          # noqa: F401

__all__ = ["RelayAgent", "start_mdns_discovery", "_list_serials"]
