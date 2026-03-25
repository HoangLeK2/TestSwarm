"""
device_farm.runtime — runtime device control and streaming.

Layout:

- runtime.core        — DeviceManager, DeviceClient, TaskQueue, Dispatcher, Watchdog
- runtime.transports  — ADB, WebSocket tunnels, scrcpy, u2, STF, minitouch, H.264 helpers
- runtime.ai          — Scenario generation (LLM + MCP)

Prefer namespace imports, e.g.:

    from runtime.core import DeviceManager, TaskQueue
    from runtime.transports import TunnelSet
"""
