from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any, Dict

from runtime.transports.adb_transport import AdbTransport
from runtime.transports.adb_device_bootstrap import AdbDeviceBootstrap


log = logging.getLogger("adb_bootstrap")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )


def _on_frame(_: bytes) -> None:
    pass


def _on_battery(level: int) -> None:
    log.info("Battery level: %s%%", level)


def _on_rotation(degrees: int) -> None:
    log.info("Rotation: %s°", degrees)


def _on_u2_ready(client) -> None:
    try:
        info: Dict[str, Any] = client.device_info()
    except Exception:
        info = {}
    log.info("uiautomator2 ready on %s:%s info=%s", client._host, client._port, info or "<unknown>")


def _on_metadata(meta: Dict[str, Any]) -> None:
    log.info("Metadata: %s", meta)


def main(argv: list[str] | None = None) -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(description="One-off ADB bootstrap for an Android device")
    parser.add_argument("--host", required=True, help="Device IP / host for adb over TCP (e.g. 172.16.0.91)")
    parser.add_argument("--port", type=int, default=5555, help="Device adb TCP port (default: 5555)")

    args = parser.parse_args(argv)

    host = args.host
    port = args.port

    log.info("Connecting AdbTransport to %s:%s …", host, port)
    t = AdbTransport(host, port)
    if not t.connect():
        log.error("ADB connect failed to %s:%s", host, port)
        sys.exit(1)

    try:
        bootstrap = AdbDeviceBootstrap(
            transport=t,
            on_frame=_on_frame,
            on_battery=_on_battery,
            on_rotation=_on_rotation,
            on_u2_ready=_on_u2_ready,
            on_metadata=_on_metadata,
        )
        bootstrap.start()

        log.info("Bootstrap started. Press Ctrl+C to stop.")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("Stopping bootstrap…")
    finally:
        bootstrap.stop()
        t.close()
        log.info("Done.")


if __name__ == "__main__":
    main()

