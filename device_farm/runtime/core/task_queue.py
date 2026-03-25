"""
task_queue.py — Thread-safe priority task queue and Task model.

Priority queue ordering: (priority, created_at_timestamp, task)
Lower priority number = higher urgency (like UNIX nice values).
Tasks with equal priority are ordered FIFO by creation time.

O(1) get_next() via indexed structure:
  _by_target[serial]  → heapq of tasks targeting that specific device
  _by_target[None]    → heapq of tasks that can run on any device
"""
from __future__ import annotations

import heapq
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    REQUEUED = "REQUEUED"
    CANCELLED = "CANCELLED"


@dataclass
class Task:
    fn: Callable[..., Any]              # callable(device_client) → Any
    priority: int = 5                   # lower = higher urgency
    target: Optional[str] = None        # specific serial, None = any device
    timeout: float = 300.0              # seconds before task is killed
    max_retries: int = 2
    name: str = ""                      # human-readable label for UI

    # Auto-populated
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    retry_count: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def __lt__(self, other: "Task") -> bool:
        return (self.priority, self.created_at) < (other.priority, other.created_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or (self.fn.__name__ if callable(self.fn) else "task"),
            "priority": self.priority,
            "target": self.target,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "status": self.status.value,
            "result": str(self.result) if self.result is not None else None,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# Heap item: (priority, timestamp_float, task)
_HeapItem = tuple


class TaskQueue:
    """
    Thread-safe priority queue for Task objects.

    O(1) amortised get_next(serial): uses two heaps —
      _heap_targeted[serial]  items targeting a specific device
      _heap_any               items for any device

    get_next(serial) pops from whichever heap has the higher-priority pending task.
    Stale heap entries (cancelled/running tasks) are skipped lazily.

    Memory: _all dict holds all tasks. Entries older than _TTL_HOURS with a
    terminal status are purged periodically to prevent unbounded growth.
    """

    _TTL_HOURS = 24  # keep completed/failed tasks for 24h then discard

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # All tasks ever created, by ID
        self._all: Dict[str, Task] = {}
        # Heap for "any-device" tasks
        self._heap_any: List[_HeapItem] = []
        # Per-serial heaps for targeted tasks
        self._heap_targeted: Dict[str, List[_HeapItem]] = {}
        # Periodic cleanup counter
        self._ops_since_cleanup = 0
        self._CLEANUP_EVERY = 500

    def put(self, task: Task) -> None:
        """Enqueue a task. O(log n). Thread-safe."""
        item: _HeapItem = (task.priority, task.created_at.timestamp(), task)
        with self._lock:
            task.status = TaskStatus.PENDING
            self._all[task.id] = task
            if task.target is None:
                heapq.heappush(self._heap_any, item)
            else:
                heap = self._heap_targeted.setdefault(task.target, [])
                heapq.heappush(heap, item)
            self._maybe_cleanup()

    def get_next(self, serial: Optional[str] = None) -> Optional[Task]:
        """
        Get highest-priority PENDING task matching serial. O(log n) amortised.
        - Tasks targeting `serial` take priority over any-device tasks of equal priority.
        - serial=None: only returns any-device tasks.
        """
        with self._lock:
            return self._pop_best(serial)

    def _pop_best(self, serial: Optional[str]) -> Optional[Task]:
        """Internal: pop best pending task. Must hold _lock."""
        targeted_task: Optional[Task] = None
        any_task: Optional[Task] = None

        if serial is not None and serial in self._heap_targeted:
            targeted_task = self._peek_pending(self._heap_targeted[serial])

        any_task = self._peek_pending(self._heap_any)

        if targeted_task is None and any_task is None:
            return None

        # Pick whichever has higher priority (lower int); break ties by timestamp
        use_targeted = (
            targeted_task is not None
            and (
                any_task is None
                or (targeted_task.priority, targeted_task.created_at)
                <= (any_task.priority, any_task.created_at)
            )
        )

        if use_targeted:
            chosen = self._pop_pending(self._heap_targeted[serial])  # type: ignore[index]
        else:
            chosen = self._pop_pending(self._heap_any)

        if chosen is not None:
            chosen.status = TaskStatus.RUNNING
            chosen.started_at = datetime.utcnow()
        return chosen

    def _peek_pending(self, heap: List[_HeapItem]) -> Optional[Task]:
        """Peek at the top pending item without removing. Skips stale entries."""
        while heap:
            task: Task = heap[0][2]
            if task.status == TaskStatus.PENDING:
                return task
            heapq.heappop(heap)  # stale — discard
        return None

    def _pop_pending(self, heap: List[_HeapItem]) -> Optional[Task]:
        """Pop top pending item. Skips stale entries."""
        while heap:
            item = heapq.heappop(heap)
            task: Task = item[2]
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def requeue(self, task: Task) -> None:
        """Put a task back into the queue after a transient failure."""
        task.status = TaskStatus.REQUEUED
        task.retry_count += 1
        task.started_at = None
        task.error = None
        self.put(task)

    def cancel(self, task_id: str) -> bool:
        """Mark task as CANCELLED. It will be skipped when next popped. O(1)."""
        with self._lock:
            task = self._all.get(task_id)
            if task and task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                return True
        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._all.get(task_id)

    def all_tasks(self) -> List[Task]:
        with self._lock:
            return list(self._all.values())

    def pending_count(self) -> int:
        with self._lock:
            return sum(
                1 for t in self._all.values() if t.status == TaskStatus.PENDING
            )

    def stats(self) -> Dict[str, int]:
        """Aggregate counts by status. For fleet monitoring."""
        counts: Dict[str, int] = {}
        with self._lock:
            for t in self._all.values():
                counts[t.status.value] = counts.get(t.status.value, 0) + 1
        return counts

    def tasks_by_name(self, name: str) -> List[Task]:
        """Return all tasks whose name starts with `name`. For campaign monitoring."""
        with self._lock:
            return [t for t in self._all.values() if t.name.startswith(name)]

    def _maybe_cleanup(self) -> None:
        """Periodically purge old terminal tasks to cap memory. Must hold _lock."""
        self._ops_since_cleanup += 1
        if self._ops_since_cleanup < self._CLEANUP_EVERY:
            return
        self._ops_since_cleanup = 0
        cutoff = datetime.utcnow() - timedelta(hours=self._TTL_HOURS)
        terminal = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}
        stale = [
            tid for tid, t in self._all.items()
            if t.status in terminal and t.finished_at and t.finished_at < cutoff
        ]
        for tid in stale:
            del self._all[tid]
