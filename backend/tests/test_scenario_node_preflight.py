from __future__ import annotations

from services.scenario_node_preflight import (
    collect_node_capabilities,
    preflight_scenario_registry_node_capabilities,
    preflight_scenario_node_capabilities,
    preflight_scenario_node_capabilities_for_capabilities,
    scenario_from_scenario_registry,
    scenario_node_preflight_error_payload,
    scenario_node_preflight_failure_reason,
)


class _FakeDevice:
    serial = "dev-1"
    u2 = None
    stf = None

    def __init__(self, *, ocr: bool = True, image_match: bool = True) -> None:
        self._ocr = ocr
        self._image_match = image_match

    def ocr_supported(self) -> bool:
        return self._ocr

    def image_match_supported(self) -> bool:
        return self._image_match

    def set_clipboard(self, text: str) -> None:
        return None

    def push_file(self, local_path: str, remote_path: str) -> None:
        return None

    def pull_file(self, remote_path: str, local_path: str) -> None:
        return None

    def install(self, apk_source: str, timeout: float = 90.0) -> None:
        return None

    def take_screenshot(self):
        return None

    def shell(self, cmd: str) -> None:
        return None


def test_preflight_fails_early_for_nested_ocr_node_without_agent_ocr():
    result = preflight_scenario_node_capabilities(
        _FakeDevice(ocr=False),
        {
            "steps": [
                {
                    "type": "repeat",
                    "count": 1,
                    "steps": [{"type": "extract_text_ocr", "save_as": "text"}],
                }
            ]
        },
    )

    assert result.ok is False
    assert result.issues[0].path == "steps[0].steps[0]"
    assert result.issues[0].step_type == "extract_text_ocr"
    assert result.issues[0].missing == ("has_ocr", "has_tesseract")


def test_preflight_does_not_block_ratio_only_tap_without_u2():
    result = preflight_scenario_node_capabilities(
        _FakeDevice(),
        {"steps": [{"type": "tap", "fallback": {"rx": 0.5, "ry": 0.5}}]},
    )

    assert result.ok is True
    assert result.issues == ()


def test_preflight_warns_for_selector_tap_when_u2_is_unknown():
    result = preflight_scenario_node_capabilities(
        _FakeDevice(),
        {"steps": [{"type": "tap", "selector": {"by": "text", "value": "Login"}}]},
    )

    assert result.ok is True
    assert result.warnings[0].unknown == ("has_u2",)


def test_preflight_requires_ocr_for_app_profile_ocr_near():
    result = preflight_scenario_node_capabilities(
        _FakeDevice(ocr=False),
        {
            "steps": [
                {
                    "type": "fill_form",
                    "profile": {
                        "package": "com.example",
                        "semantic_locators": {
                            "login": {"candidates": [{"ocr_near": "Login"}]}
                        },
                    },
                }
            ]
        },
    )

    assert result.ok is False
    assert result.issues[0].step_type == "fill_form"
    assert result.issues[0].missing == ("has_ocr", "has_tesseract")


def test_preflight_accepts_install_apk_when_device_has_install_method():
    result = preflight_scenario_node_capabilities(
        _FakeDevice(),
        {"steps": [{"type": "install_apk", "url": "/tmp/app.apk"}]},
    )

    assert result.ok is True
    assert result.issues == ()


def test_collect_node_capabilities_returns_known_runtime_facts_only():
    result = collect_node_capabilities(_FakeDevice(ocr=True, image_match=False))

    assert result["has_ocr"] is True
    assert result["has_tesseract"] is True
    assert result["has_image_match"] is False
    assert result["has_opencv"] is False
    assert result["supports_clipboard"] is True
    assert result["supports_file_ops"] is True
    assert result["supports_install_apk"] is True
    assert "has_u2" not in result


def test_preflight_can_run_from_capability_snapshot_without_device():
    result = preflight_scenario_node_capabilities_for_capabilities(
        {"has_ocr": True, "has_tesseract": False},
        {"steps": [{"type": "extract_text_ocr", "save_as": "text"}]},
    )

    assert result.ok is False
    assert result.issues[0].missing == ("has_tesseract",)


def test_preflight_flattens_referenced_scenario_registry_steps():
    registry = {
        "by_id": {
            "sc-1": {
                "steps": [{"type": "extract_text_ocr", "save_as": "text"}],
            },
            "sc-2": {
                "steps": [{"type": "image_match", "template": "button.png"}],
            },
        }
    }

    scenario = scenario_from_scenario_registry(
        [{"scenario_id": "sc-1"}, {"scenario_id": "missing"}],
        registry,
    )
    result = preflight_scenario_registry_node_capabilities(
        _FakeDevice(ocr=False),
        [{"scenario_id": "sc-1"}],
        registry,
    )

    assert scenario == {"steps": [{"type": "extract_text_ocr", "save_as": "text"}]}
    assert result.ok is False
    assert result.issues[0].step_type == "extract_text_ocr"
    assert result.issues[0].missing == ("has_ocr", "has_tesseract")


def test_preflight_error_payload_uses_stable_error_contract():
    result = preflight_scenario_node_capabilities(
        _FakeDevice(ocr=False),
        {"steps": [{"type": "extract_text_ocr", "save_as": "text"}]},
    )

    payload = scenario_node_preflight_error_payload(result)

    assert scenario_node_preflight_failure_reason(result) == result.message
    assert payload["error"] == "node_capability_preflight_failed"
    assert payload["message"] == result.message
    assert payload["preflight"]["ok"] is False
    assert payload["preflight"]["issues"][0]["missing"] == ["has_ocr", "has_tesseract"]
