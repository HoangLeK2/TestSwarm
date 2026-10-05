from __future__ import annotations

from unittest.mock import patch

from tasks.scenario.context import ScenarioContext
from services.execution.step_runner import execute_step_with_retry


_XML = """
<hierarchy>
  <node text="Update available" class="android.widget.TextView" bounds="[10,10][500,80]" />
  <node text="Later" class="android.widget.Button" bounds="[300,200][500,280]" />
</hierarchy>
"""


class FakeU2:
    def __init__(self) -> None:
        self.clicked: list[str] = []

    def app_current(self) -> dict:
        return {"package": "com.example.app", "activity": ".MainActivity"}

    def find_element_with_bounds_spec(self, spec, timeout=0.5):
        by, value = spec.primary_by_value()
        if by == "text" and value == "Later":
            return {"eid": "text:Later", "bounds": {"left": 300, "top": 200, "right": 500, "bottom": 280}}
        return None

    def element_click(self, eid: str) -> None:
        self.clicked.append(eid)


class FakeDevice:
    serial = "SERIAL1"
    screen_width = 1080
    screen_height = 1920

    def __init__(self, xml: str = _XML) -> None:
        self.u2 = FakeU2()
        self._xml = xml
        self.hierarchy_calls = 0

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        self.hierarchy_calls += 1
        return self._xml

    def ensure_u2_healthy(self) -> None:
        return None


def _profile() -> dict:
    return {
        "package": "com.example.app",
        "popup_watchers": [
            {
                "name": "close_update",
                "when": {"text_contains": ["Update"]},
                "action": {"tap_text_any": ["Later", "Not now"]},
            }
        ],
    }


def _sc(scenario: dict) -> ScenarioContext:
    return ScenarioContext.from_args(FakeDevice(), scenario)


def test_execute_step_runs_app_popup_watcher_before_handler():
    calls: list[str] = []

    def noop(sc, step, idx, result):
        calls.append("handler")
        result["message"] = "ok"

    sc = _sc({
        "app_automation_profile": _profile(),
        "steps": [{"type": "noop"}],
    })

    with patch.dict("tasks.scenario.steps._STEP_HANDLERS", {"noop": noop}):
        result, attempts = execute_step_with_retry(sc, {"type": "noop"}, 0)

    assert attempts == 1
    assert result["ok"] is True
    assert calls == ["handler"]
    assert sc.device.u2.clicked == ["text:Later"]
    assert result["app_popup_watchers"][0]["name"] == "close_update"
    assert result["app_popup_watchers"][0]["executed"] is True


def test_execute_step_skips_watcher_path_without_profile():
    sc = _sc({"steps": [{"type": "noop"}]})

    with patch.dict("tasks.scenario.steps._STEP_HANDLERS", {"noop": lambda sc, step, idx, result: None}):
        result, _ = execute_step_with_retry(sc, {"type": "noop"}, 0)

    assert result["ok"] is True
    assert "app_popup_watchers" not in result
    assert sc.device.hierarchy_calls == 0
