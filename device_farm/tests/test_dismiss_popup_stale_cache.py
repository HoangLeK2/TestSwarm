"""Guard: popup dismissal must read the screen it is about to tap.

Facebook stacks its post-login popups about a second apart. The hierarchy cache
is 2s, and clicking through the raw u2 handle does not drop it, so the scan used
to answer "is a popup on screen" from a dump of a screen that was already
dismissed: the stale XML still carries the label, find_element returns None
because the popup is gone, and the scan reports "nothing to dismiss" while the
next popup covers the readiness markers. The gate then fails a login that
worked — which is exactly what the operator sees as "popup vẫn hiện".
"""

from __future__ import annotations

from types import SimpleNamespace

from tasks.scenario.steps.wait import handle_dismiss_popup
from tasks.scenario.utils import _auto_dismiss_popup


class _FakeU2:
    def __init__(self, device: "_FakeDevice") -> None:
        self._device = device

    def find_element(self, by, value, timeout=0):
        return "eid" if value == self._device.current_label() else None

    def element_click(self, eid):
        self._device.popups.pop(0)


class _FakeDevice:
    """Screen with a queue of popups; hierarchy served from a 2s-style cache."""

    serial = "fake"

    def __init__(self, popups: list[str]) -> None:
        self.popups = list(popups)
        self._cached: str | None = None
        self.invalidations = 0
        self.u2 = _FakeU2(self)

    def current_label(self) -> str | None:
        return self.popups[0] if self.popups else None

    def _render(self) -> str:
        label = self.current_label() or ""
        return f'<hierarchy><node text="{label}" /></hierarchy>'

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        if force_refresh or self._cached is None:
            self._cached = self._render()
        return self._cached

    def hierarchy_invalidate_cache(self) -> None:
        self.invalidations += 1
        self._cached = None


def test_popup_that_renders_after_the_last_dump_is_still_seen() -> None:
    """The cache is warm and holds a popup-free screen; the popup is up now."""
    device = _FakeDevice([])
    device.hierarchy_xml()  # a preceding wait_stable warmed the cache
    device.popups.append("Bỏ qua")  # popup renders a beat later

    assert _auto_dismiss_popup(device) is True, (
        "scan answered from the cached pre-popup dump"
    )
    assert device.popups == []


def test_dismiss_drains_a_queue_of_popups() -> None:
    device = _FakeDevice(["Bỏ qua", "Để sau", "Không, cảm ơn"])
    device.hierarchy_xml()  # warm the cache like a preceding wait_stable would

    assert _auto_dismiss_popup(device) is True
    assert _auto_dismiss_popup(device) is True
    assert _auto_dismiss_popup(device) is True
    assert device.popups == []
    assert _auto_dismiss_popup(device) is False


def test_click_invalidates_the_cache_for_later_readers() -> None:
    device = _FakeDevice(["Bỏ qua"])
    assert _auto_dismiss_popup(device) is True
    assert device.invalidations >= 1, (
        "wait_stable and the readiness gate read the cache; leaving it stale "
        "scores the pre-dismiss screen"
    )


def test_dismiss_popup_step_reports_every_popup_it_closed() -> None:
    device = _FakeDevice(["Bỏ qua", "Để sau", "Không, cảm ơn"])
    sc = SimpleNamespace(device=device, cancel_event=None)
    result: dict = {"ok": True}

    handle_dismiss_popup(sc, {"type": "dismiss_popup", "retries": 3}, 0, result)

    assert result.get("dismissed_count") == 3, result
