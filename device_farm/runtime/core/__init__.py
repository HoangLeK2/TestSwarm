"""
runtime.core — core device-farm domain: devices, manager, queue, dispatcher, watchdog.

This is a logical grouping layer on top of the lower-level modules in
`runtime/`. Prefer importing from here in new code, e.g.:

    from runtime.core import DeviceManager, TaskQueue, Task, Dispatcher, WatchdogThread
"""

from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.device_manager import DeviceManager
from runtime.core.task_queue import Task, TaskQueue, TaskStatus
from runtime.core.dispatcher import Dispatcher
from runtime.core.watchdog import WatchdogThread
from runtime.core.event_recorder import EventRecorder

__all__ = [
    "DeviceClient",
    "DeviceState",
    "DeviceManager",
    "Task",
    "TaskQueue",
    "TaskStatus",
    "Dispatcher",
    "WatchdogThread",
    "EventRecorder",
]

