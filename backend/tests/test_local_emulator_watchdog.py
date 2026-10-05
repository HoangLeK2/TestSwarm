from __future__ import annotations

import time
from unittest.mock import Mock

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.watchdog import WatchdogThread


def test_registered_local_emulator_stays_ready_when_u2_is_healthy() -> None:
    device = DeviceClient(serial="emulator-5580", index=0, config=Config())
    device.state = DeviceState.READY
    device._local_emulator_adb = True
    device._u2 = Mock()
    device._u2.verify.return_value = {"currentPackageName": "com.android.launcher3"}
    device.reconnect_attempts = 2

    watchdog = WatchdogThread(manager=Mock(), config=Config())
    watchdog._bad_since[device.serial] = time.monotonic()

    watchdog._check_device(device)

    assert device.state == DeviceState.READY
    assert device.serial not in watchdog._bad_since
    assert device.reconnect_attempts == 0


def test_registered_local_emulator_uses_disconnect_grace_after_u2_failure() -> None:
    device = DeviceClient(serial="emulator-5580", index=0, config=Config())
    device.state = DeviceState.READY
    device._local_emulator_adb = True
    device._u2 = Mock()
    device._u2.verify.side_effect = TimeoutError("u2 unavailable")

    watchdog = WatchdogThread(manager=Mock(), config=Config())

    watchdog._check_device(device)

    assert device.state == DeviceState.READY
    assert device.serial in watchdog._bad_since
