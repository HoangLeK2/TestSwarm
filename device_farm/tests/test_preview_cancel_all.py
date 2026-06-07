"""Tests for cancel_all_previews_for_serial."""

from __future__ import annotations

import threading

from api.routes.device_control import scenarios as preview_mod


def test_cancel_all_previews_for_serial_sets_events():
    ev1 = threading.Event()
    ev2 = threading.Event()
    other = threading.Event()
    with preview_mod._ACTIVE_PREVIEWS_LOCK:
        preview_mod._ACTIVE_PREVIEWS.clear()
        preview_mod._ACTIVE_PREVIEWS[("dev-a", "t1")] = {"event": ev1, "user_id": None}
        preview_mod._ACTIVE_PREVIEWS[("dev-a", "t2")] = {"event": ev2, "user_id": None}
        preview_mod._ACTIVE_PREVIEWS[("dev-b", "t3")] = {"event": other, "user_id": None}
    try:
        n = preview_mod.cancel_all_previews_for_serial("dev-a")
        assert n == 2
        assert ev1.is_set()
        assert ev2.is_set()
        assert not other.is_set()
    finally:
        with preview_mod._ACTIVE_PREVIEWS_LOCK:
            preview_mod._ACTIVE_PREVIEWS.clear()


def test_cancel_all_previews_respects_owner():
    ev = threading.Event()
    with preview_mod._ACTIVE_PREVIEWS_LOCK:
        preview_mod._ACTIVE_PREVIEWS.clear()
        preview_mod._ACTIVE_PREVIEWS[("dev-a", "t1")] = {"event": ev, "user_id": "user-1"}
    try:
        assert preview_mod.cancel_all_previews_for_serial("dev-a", user_id="user-2") == 0
        assert not ev.is_set()
        assert preview_mod.cancel_all_previews_for_serial("dev-a", user_id="user-1") == 1
        assert ev.is_set()
    finally:
        with preview_mod._ACTIVE_PREVIEWS_LOCK:
            preview_mod._ACTIVE_PREVIEWS.clear()


def test_preview_stream_abort_sets_event_before_unregistering():
    ev = threading.Event()
    worker_done = threading.Event()
    with preview_mod._ACTIVE_PREVIEWS_LOCK:
        preview_mod._ACTIVE_PREVIEWS.clear()
        preview_mod._ACTIVE_PREVIEWS[("dev-a", "t1")] = {"event": ev, "user_id": None}
    try:
        preview_mod._finish_preview_stream(
            "dev-a",
            "t1",
            ev,
            worker_done,
            completed=False,
        )
        assert ev.is_set()
        with preview_mod._ACTIVE_PREVIEWS_LOCK:
            assert ("dev-a", "t1") in preview_mod._ACTIVE_PREVIEWS

        worker_done.set()
        preview_mod._finish_preview_stream(
            "dev-a",
            "t1",
            ev,
            worker_done,
            completed=True,
        )
        with preview_mod._ACTIVE_PREVIEWS_LOCK:
            assert ("dev-a", "t1") not in preview_mod._ACTIVE_PREVIEWS
    finally:
        with preview_mod._ACTIVE_PREVIEWS_LOCK:
            preview_mod._ACTIVE_PREVIEWS.clear()
