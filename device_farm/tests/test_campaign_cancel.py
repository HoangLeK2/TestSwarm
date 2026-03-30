"""Unit tests for campaign stop/cancel flow.

Tests cover:
  - Task.cancel_event existence and behavior
  - TaskQueue.cancel() for PENDING and RUNNING tasks
  - TaskQueue.cancel_by_name_prefix()
  - Scenario executor cancellation at step boundary
  - make_scenario_task wiring cancel_event
  - Campaign status endpoint cancelling tasks
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from runtime.core.task_queue import Task, TaskQueue, TaskStatus
from tasks.scenario_task import make_scenario_task, run_scenario_task


# ── Helpers ──────────────────────────────────────────────────────────────────


def _noop(device):
    return {"ok": True}


def _make_device() -> MagicMock:
    d = MagicMock()
    d.serial = "test-device"
    d.screen_width = 1080
    d.screen_height = 1920
    d.model = "TestPhone"
    return d


# ── Task.cancel_event ────────────────────────────────────────────────────────


class TestTaskCancelEvent:
    def test_task_has_cancel_event(self):
        t = Task(fn=_noop)
        assert isinstance(t.cancel_event, threading.Event)
        assert not t.cancel_event.is_set()

    def test_each_task_gets_unique_event(self):
        t1 = Task(fn=_noop)
        t2 = Task(fn=_noop)
        assert t1.cancel_event is not t2.cancel_event


# ── TaskQueue.cancel() ───────────────────────────────────────────────────────


class TestTaskQueueCancel:
    def test_cancel_pending_task(self):
        q = TaskQueue()
        t = Task(fn=_noop, name="test-task")
        q.put(t)
        assert t.status == TaskStatus.PENDING

        result = q.cancel(t.id)
        assert result is True
        assert t.status == TaskStatus.CANCELLED
        assert t.cancel_event.is_set()

    def test_cancel_running_task_sets_event(self):
        q = TaskQueue()
        t = Task(fn=_noop, name="test-task")
        q.put(t)
        t.status = TaskStatus.RUNNING  # simulate dispatcher picked it up

        result = q.cancel(t.id)
        assert result is True
        assert t.cancel_event.is_set()
        # Status stays RUNNING — the task itself will handle the cancellation
        assert t.status == TaskStatus.RUNNING

    def test_cancel_done_task_returns_false(self):
        q = TaskQueue()
        t = Task(fn=_noop, name="test-task")
        q.put(t)
        t.status = TaskStatus.DONE

        result = q.cancel(t.id)
        assert result is False
        assert not t.cancel_event.is_set()

    def test_cancel_nonexistent_task(self):
        q = TaskQueue()
        assert q.cancel("nonexistent-id") is False

    def test_cancel_already_cancelled(self):
        q = TaskQueue()
        t = Task(fn=_noop, name="test-task")
        q.put(t)
        q.cancel(t.id)
        # Second cancel should return False (already CANCELLED)
        assert q.cancel(t.id) is False


# ── TaskQueue.cancel_by_name_prefix() ────────────────────────────────────────


class TestCancelByNamePrefix:
    def test_cancels_matching_tasks(self):
        q = TaskQueue()
        t1 = Task(fn=_noop, name="campaign:abc:scenario:1")
        t2 = Task(fn=_noop, name="campaign:abc:scenario:2")
        t3 = Task(fn=_noop, name="campaign:xyz:scenario:1")  # different campaign
        q.put(t1)
        q.put(t2)
        q.put(t3)

        count = q.cancel_by_name_prefix("campaign:abc:")
        assert count == 2
        assert t1.cancel_event.is_set()
        assert t2.cancel_event.is_set()
        assert not t3.cancel_event.is_set()

    def test_cancels_running_and_pending(self):
        q = TaskQueue()
        t_pending = Task(fn=_noop, name="campaign:abc:s1")
        t_running = Task(fn=_noop, name="campaign:abc:s2")
        q.put(t_pending)
        q.put(t_running)
        t_running.status = TaskStatus.RUNNING

        count = q.cancel_by_name_prefix("campaign:abc:")
        assert count == 2
        assert t_pending.status == TaskStatus.CANCELLED
        assert t_running.status == TaskStatus.RUNNING  # stays RUNNING, but event set
        assert t_running.cancel_event.is_set()

    def test_skips_done_tasks(self):
        q = TaskQueue()
        t_done = Task(fn=_noop, name="campaign:abc:done")
        q.put(t_done)
        t_done.status = TaskStatus.DONE

        count = q.cancel_by_name_prefix("campaign:abc:")
        assert count == 0

    def test_no_match_returns_zero(self):
        q = TaskQueue()
        t = Task(fn=_noop, name="campaign:abc:s1")
        q.put(t)
        assert q.cancel_by_name_prefix("campaign:xyz:") == 0

    def test_empty_queue(self):
        q = TaskQueue()
        assert q.cancel_by_name_prefix("anything:") == 0


# ── Scenario Executor Cancellation ───────────────────────────────────────────


class TestScenarioTaskCancellation:
    def test_cancel_before_first_step(self):
        device = _make_device()
        cancel = threading.Event()
        cancel.set()  # pre-cancel

        result = run_scenario_task(
            device,
            {"steps": [
                {"type": "wait", "seconds": 10},
                {"type": "tap", "x": 100, "y": 200},
            ]},
            cancel_event=cancel,
        )
        assert result["success"] is False
        assert result["steps_executed"] == 0
        assert "Cancelled" in result["failed_message"]

    def test_cancel_between_steps(self):
        device = _make_device()
        cancel = threading.Event()

        # Step 1 is quick, then many slow steps that should NOT run
        scenario = {
            "steps": [
                {"type": "wait", "seconds": 0.05},
                {"type": "wait", "seconds": 0.05},
                {"type": "wait", "seconds": 0.05},
            ]
        }

        result_holder = [None]

        def _thread():
            result_holder[0] = run_scenario_task(device, scenario, cancel_event=cancel)

        t = threading.Thread(target=_thread)
        t.start()

        # Wait for step 1 to finish, then cancel before step 2 or 3
        time.sleep(0.08)
        cancel.set()
        t.join(timeout=5)

        result = result_holder[0]
        assert result is not None
        assert result["success"] is False
        assert result["steps_executed"] < 3
        assert "Cancelled" in result["failed_message"]

    def test_no_cancel_event_runs_normally(self):
        device = _make_device()
        result = run_scenario_task(
            device,
            {"steps": [
                {"type": "wait", "seconds": 0.01},
            ]},
            cancel_event=None,  # no cancellation
        )
        assert result["success"] is True
        assert result["steps_executed"] == 1

    def test_empty_steps_with_cancel(self):
        device = _make_device()
        cancel = threading.Event()
        cancel.set()
        result = run_scenario_task(
            device,
            {"steps": []},
            cancel_event=cancel,
        )
        # No steps → success (cancel check is before each step)
        assert result["success"] is True


# ── make_scenario_task wiring ─────────────────────────────────────────────────


class TestMakeScenarioTaskWiring:
    def test_cancel_event_passed_through(self):
        cancel = threading.Event()
        fn = make_scenario_task(
            {"steps": [{"type": "wait", "seconds": 10}]},
            cancel_event=cancel,
        )

        # Pre-cancel, then run
        cancel.set()
        device = _make_device()
        result = fn(device)
        assert result["success"] is False
        assert "Cancelled" in result["failed_message"]

    def test_without_cancel_event(self):
        fn = make_scenario_task({"steps": [{"type": "wait", "seconds": 0.01}]})
        device = _make_device()
        result = fn(device)
        assert result["success"] is True


# ── Integration: Task + Scenario Cancel ───────────────────────────────────────


class TestIntegrationTaskScenarioCancel:
    def test_full_flow_cancel_running_task(self):
        """Simulate: dispatch task → start running → cancel → scenario stops."""
        q = TaskQueue()

        task = Task(
            fn=lambda dev: None,  # placeholder
            name="campaign:test123:scenario:s1",
            target="test-device",
            timeout=30,
        )
        task.fn = make_scenario_task(
            {"steps": [
                {"type": "wait", "seconds": 0.05},
                {"type": "wait", "seconds": 0.05},
                {"type": "wait", "seconds": 0.05},
                {"type": "wait", "seconds": 0.05},
            ]},
            cancel_event=task.cancel_event,
        )
        q.put(task)
        task.status = TaskStatus.RUNNING

        device = _make_device()
        result_holder = [None]

        def _run():
            result_holder[0] = task.fn(device)

        t = threading.Thread(target=_run)
        t.start()

        # Wait for step 1, then cancel via queue
        time.sleep(0.08)
        cancelled = q.cancel_by_name_prefix("campaign:test123:")
        assert cancelled == 1

        t.join(timeout=5)
        result = result_holder[0]
        assert result is not None
        assert result["success"] is False
        assert "Cancelled" in result["failed_message"]
        assert result["steps_executed"] < 4
