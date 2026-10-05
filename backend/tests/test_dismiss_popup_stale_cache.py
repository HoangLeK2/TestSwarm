"""Guard: popup dismissal must read the screen it is about to tap.

Instagram stacks its post-login popups about a second apart. The hierarchy cache
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
        return "eid" if (by, value) == self._device.current_selector() else None

    def element_click(self, eid):
        self._device.popups.pop(0)


class _FakeDevice:
    """Screen with a queue of popups; hierarchy served from a 2s-style cache."""

    serial = "fake"

    def __init__(self, popups: list[str | tuple[str, str]]) -> None:
        self.popups = list(popups)
        self._cached: str | None = None
        self.invalidations = 0
        self.u2 = _FakeU2(self)

    def current_label(self) -> str | None:
        current = self.popups[0] if self.popups else None
        if isinstance(current, tuple):
            return current[1]
        return current

    def current_selector(self) -> tuple[str, str] | None:
        current = self.popups[0] if self.popups else None
        if isinstance(current, tuple):
            return current
        if isinstance(current, str):
            return ("text", current)
        return None

    def _render(self) -> str:
        selector = self.current_selector()
        if selector is None:
            return "<hierarchy></hierarchy>"
        by, value = selector
        attr = "content-desc" if by == "content-desc" else "text"
        return f'<hierarchy><node {attr}="{value}" /></hierarchy>'

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        if force_refresh or self._cached is None:
            self._cached = self._render()
        return self._cached

    def hierarchy_invalidate_cache(self) -> None:
        self.invalidations += 1
        self._cached = None


class _XmlDevice(_FakeDevice):
    def __init__(self, xml: str, selectors: set[tuple[str, str]]) -> None:
        super().__init__([])
        self.xml = xml
        self.selectors = selectors
        self.clicked: list[tuple[str, str]] = []
        self.u2 = self

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self.xml

    def find_element(self, by, value, timeout=0):
        return (by, value) if (by, value) in self.selectors else None

    def element_click(self, eid):
        self.clicked.append(eid)


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


def test_dismisses_instagram_skip_when_it_is_accessibility_label_only() -> None:
    device = _FakeDevice([("content-desc", "Bỏ qua")])

    assert _auto_dismiss_popup(device) is True
    assert device.popups == []


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


def test_dismisses_google_saved_password_popup_by_semantic_close_label() -> None:
    device = _XmlDevice(
        """<hierarchy>
          <node text="Sign in to Instagram with your saved password" />
          <node text="×" class="android.widget.Button" clickable="true" />
          <node text="Continue" class="android.widget.Button" clickable="true" />
        </hierarchy>""",
        {("text", "×")},
    )

    assert _auto_dismiss_popup(device) is True
    assert device.clicked == [("text", "×")]


def test_dismisses_google_saved_password_popup_from_real_google_hierarchy() -> None:
    device = _XmlDevice(
        """<hierarchy>
          <node class="android.widget.FrameLayout" package="com.google.android.gms">
            <node resource-id="com.google.android.gms:id/design_bottom_sheet">
              <node resource-id="com.google.android.gms:id/cancel"
                    content-desc="Cancel"
                    class="android.widget.ImageView"
                    clickable="true" />
              <node resource-id="com.google.android.gms:id/title"
                    text="Sign in to Instagram with your saved password" />
              <node resource-id="com.google.android.gms:id/continue_button"
                    text="Continue"
                    class="android.widget.Button"
                    clickable="true" />
            </node>
          </node>
        </hierarchy>""",
        {("content-desc", "Cancel")},
    )

    assert _auto_dismiss_popup(device) is True
    assert device.clicked == [("content-desc", "Cancel")]


def test_dismisses_google_account_chooser_from_real_vietnamese_hierarchy() -> None:
    device = _XmlDevice(
        """<hierarchy>
          <node class="android.widget.FrameLayout" package="com.google.android.gms">
            <node text="Dùng tài khoản của bạn cho Instagram" />
            <node content-desc="Đóng"
                  class="android.widget.ImageView"
                  clickable="true" />
            <node text="Tiếp tục"
                  class="android.widget.Button"
                  clickable="true" />
          </node>
        </hierarchy>""",
        {("content-desc", "Đóng")},
    )

    assert _auto_dismiss_popup(device) is True
    assert device.clicked == [("content-desc", "Đóng")]


def test_dismisses_instagram_stop_profile_setup_dialog_from_real_screen() -> None:
    device = _XmlDevice(
        """<hierarchy>
          <node text="Tiếp tục thiết lập trang cá nhân" />
          <node text="Dừng thiết lập trang cá nhân của bạn?" />
          <node text="TIẾP TỤC" class="android.widget.Button" clickable="true" />
          <node text="DỪNG" class="android.widget.Button" clickable="true" />
        </hierarchy>""",
        {("text", "DỪNG")},
    )

    assert _auto_dismiss_popup(device) is True
    assert device.clicked == [("text", "DỪNG")]


def test_does_not_click_unscoped_stop_label() -> None:
    device = _XmlDevice(
        '<hierarchy><node text="DỪNG" clickable="true" /></hierarchy>',
        {("text", "DỪNG")},
    )

    assert _auto_dismiss_popup(device) is False
    assert device.clicked == []


def test_does_not_click_unscoped_or_ambiguous_close_glyph() -> None:
    unscoped = _XmlDevice(
        '<hierarchy><node text="×" clickable="true" /></hierarchy>',
        {("text", "×")},
    )
    ambiguous = _XmlDevice(
        """<hierarchy>
          <node text="Sign in to Instagram with your saved password" />
          <node text="×" clickable="true" />
          <node content-desc="Close" clickable="true" />
        </hierarchy>""",
        {("text", "×"), ("content-desc", "Close")},
    )

    assert _auto_dismiss_popup(unscoped) is False
    assert _auto_dismiss_popup(ambiguous) is False
    assert unscoped.clicked == []
    assert ambiguous.clicked == []
