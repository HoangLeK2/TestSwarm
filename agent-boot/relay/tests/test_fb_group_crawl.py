from __future__ import annotations

import asyncio
from typing import Any

import pytest

from relay.extra_data.collector import collect_xml_snapshots


def _group_page(*cards: tuple[str, str]) -> str:
    nodes = "".join(
        (
            '<node class="android.widget.Button" clickable="true" '
            f'content-desc="{name},{metadata}" />'
        )
        for name, metadata in cards
    )
    return f"<hierarchy>{nodes}</hierarchy>"


class _PagedGroupExecutor:
    def __init__(self, pages: list[str]) -> None:
        self.pages = pages
        self.page_index = 0
        self.swipes = 0

    async def window_size(self, serial: str) -> tuple[int, int]:
        return 1260, 2800

    async def run_batch(
        self,
        serial: str,
        actions: list[dict[str, Any]],
        early_exit: bool = True,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for action in actions:
            if action["op"] == "dump_hierarchy":
                results.append(
                    {
                        "op": "dump_hierarchy",
                        "ok": True,
                        "value": self.pages[self.page_index],
                    }
                )
            elif action["op"] == "swipe":
                self.swipes += 1
                self.page_index = min(self.page_index + 1, len(self.pages) - 1)
                results.append({"op": "swipe", "ok": True})
            else:
                raise AssertionError(f"unexpected action: {action}")
        return {"ok": True, "results": results}


class _CancelAfterSwipeExecutor(_PagedGroupExecutor):
    def __init__(self, pages: list[str], cancel_event: asyncio.Event) -> None:
        super().__init__(pages)
        self.cancel_event = cancel_event

    async def run_batch(
        self,
        serial: str,
        actions: list[dict[str, Any]],
        early_exit: bool = True,
    ) -> dict[str, Any]:
        result = await super().run_batch(serial, actions, early_exit)
        if any(action["op"] == "swipe" for action in actions):
            self.cancel_event.set()
        return result


@pytest.mark.asyncio
async def test_fb_groups_crawl_runs_entire_bounded_session_in_agent_boot() -> None:
    executor = _PagedGroupExecutor(
        [
            _group_page(
                ("Group A", "Công khai · 100 thành viên"),
                ("Group B", "Công khai · 200 thành viên"),
            ),
            _group_page(
                ("Group B", "Công khai · 200 thành viên"),
                ("Group C", "Công khai · 300 thành viên"),
            ),
            _group_page(("Group C", "Công khai · 300 thành viên")),
        ]
    )
    context: dict[str, Any] = {
        "max_pages": 10,
        "max_items": 100,
        "stop_if_no_new": True,
        "no_new_threshold": 1,
        "entity_scroll_pause_s": 0,
    }

    snapshots, error = await collect_xml_snapshots(
        executor,
        "device-groups",
        "fb_groups",
        context,
    )

    assert error is None
    assert len(snapshots) == 1
    assert "Group A" in snapshots[0]
    assert "Group B" in snapshots[0]
    assert "Group C" in snapshots[0]
    assert executor.swipes == 2
    assert context["entity_crawl_pages_scanned"] == 3
    assert context["entity_crawl_items_seen"] == 3
    assert context["entity_crawl_stopped_reason"] == "no_new_items"
    assert context["entity_crawl_payload_bytes"] == len(snapshots[0].encode("utf-8"))


@pytest.mark.asyncio
async def test_fb_groups_crawl_stops_immediately_when_cancelled() -> None:
    cancel_event = asyncio.Event()
    executor = _CancelAfterSwipeExecutor(
        [
            _group_page(("Group A", "Công khai · 100 thành viên")),
            _group_page(("Group B", "Công khai · 200 thành viên")),
        ],
        cancel_event,
    )

    with pytest.raises(asyncio.CancelledError, match="extra_data_cancelled"):
        await collect_xml_snapshots(
            executor,
            "device-groups",
            "fb_groups",
            {
                "max_pages": 10,
                "entity_scroll_pause_s": 0,
                "_cancel_event": cancel_event,
            },
        )

    assert executor.swipes == 1


@pytest.mark.asyncio
async def test_fb_groups_crawl_bounds_compact_payload_bytes() -> None:
    long_name = "G" * 700
    executor = _PagedGroupExecutor(
        [
            _group_page((f"{long_name} A", "Công khai · 100 thành viên")),
            _group_page((f"{long_name} B", "Công khai · 200 thành viên")),
        ]
    )
    context: dict[str, Any] = {
        "max_pages": 10,
        "max_items": 100,
        "max_xml_bytes": 1024,
        "entity_scroll_pause_s": 0,
    }

    snapshots, error = await collect_xml_snapshots(
        executor,
        "device-groups",
        "fb_groups",
        context,
    )

    assert error is None
    assert len(snapshots) == 1
    assert len(snapshots[0].encode("utf-8")) <= 1024
    assert context["entity_crawl_stopped_reason"] == "max_xml_bytes"


@pytest.mark.asyncio
async def test_fb_groups_crawl_enforces_max_items_inside_page() -> None:
    executor = _PagedGroupExecutor(
        [
            _group_page(
                ("Group A", "Công khai · 100 thành viên"),
                ("Group B", "Công khai · 200 thành viên"),
                ("Group C", "Công khai · 300 thành viên"),
            )
        ]
    )
    context: dict[str, Any] = {
        "max_pages": 10,
        "max_items": 2,
        "entity_scroll_pause_s": 0,
    }

    snapshots, error = await collect_xml_snapshots(
        executor,
        "device-groups",
        "fb_groups",
        context,
    )

    assert error is None
    assert "Group A" in snapshots[0]
    assert "Group B" in snapshots[0]
    assert "Group C" not in snapshots[0]
    assert context["entity_crawl_items_seen"] == 2
    assert context["entity_crawl_stopped_reason"] == "max_items"


@pytest.mark.asyncio
async def test_fb_groups_crawl_keeps_richer_duplicate_from_later_page() -> None:
    executor = _PagedGroupExecutor(
        [
            _group_page(("Group A", "Nhóm Công khai")),
            _group_page(("Group A", "Công khai · 200 thành viên")),
        ]
    )
    context: dict[str, Any] = {
        "max_pages": 2,
        "max_items": 10,
        "stop_if_no_new": False,
        "entity_scroll_pause_s": 0,
    }

    snapshots, error = await collect_xml_snapshots(
        executor,
        "device-groups",
        "fb_groups",
        context,
    )

    assert error is None
    assert "200 thành viên" in snapshots[0]
    assert context["entity_crawl_items_seen"] == 1
