from common.scenario_schema import SCENARIO_STEP_TYPES
from services.operation_policy import _DEVICE_MUTATION_STEP_TYPES


_NON_MUTATING_OR_CONTAINER_TYPES = frozenset(
    {
        "assert_app_state",
        "assert_element",
        "break_if",
        "extract",
        "extract_screen_data",
        "extract_text_ai",
        "extract_text_hierarchy",
        "extract_text_ocr",
        "if_element",
        "if_variable",
        "loop",
        "platform_session_gate",
        "pull_file",
        "random_pick",
        "repeat",
        "repeat_until",
        "save_extraction",
        "set_variable",
        "take_screenshot",
        "verify_screen",
        "wait",
        "wait_app",
        "wait_element",
        "wait_stable",
    }
)


def test_every_shipped_step_has_an_explicit_policy_classification() -> None:
    classified = _DEVICE_MUTATION_STEP_TYPES | _NON_MUTATING_OR_CONTAINER_TYPES

    assert set(SCENARIO_STEP_TYPES) - classified == set()
