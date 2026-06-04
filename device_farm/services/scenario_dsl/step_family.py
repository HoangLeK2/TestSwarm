"""Eight step families and core sub-types for org scenario DSL (DF-T-04-002)."""

from __future__ import annotations

from enum import Enum


class StepFamily(str, Enum):
    NAVIGATION = "navigation"
    INTERACTION = "interaction"
    INPUT_WAIT = "input_wait"
    VERIFICATION = "verification"
    VARIABLES_CONTROL = "variables_control"
    COMPOSITION = "composition"
    EXTRACTION_CONTENT = "extraction_content"
    PLATFORM_SPECIFIC = "platform_specific"


STEP_FAMILY_VALUES: frozenset[str] = frozenset(f.value for f in StepFamily)

# Canonical dotted types shipped with core (family.sub_type).
CORE_STEP_TYPES: frozenset[str] = frozenset(
    {
        # navigation
        "navigation.open_app",
        "navigation.open_url",
        "navigation.stop_app",
        "navigation.clear_app",
        "navigation.wait_app",
        # interaction
        "interaction.tap",
        "interaction.swipe",
        "interaction.long_tap",
        "interaction.double_tap",
        "interaction.scroll",
        "interaction.drag",
        "interaction.pinch",
        # input / wait
        "input_wait.wait",
        "input_wait.wait_element",
        "input_wait.input_text",
        "input_wait.key",
        # verification
        "verification.verify_screen",
        "verification.assert_element",
        # variables / control flow
        "variables_control.set_variable",
        "variables_control.if_variable",
        "variables_control.repeat",
        "variables_control.loop",
        "variables_control.break_if",
        # composition
        "composition.run_scenario",
        # extraction / content
        "extraction_content.extract",
        "extraction_content.extract_text_hierarchy",
        "extraction_content.extract_text_ocr",
        "extraction_content.save_extraction",
    }
)

COMPOSITION_RUN_SCENARIO = "composition.run_scenario"

DEFAULT_NESTING_DEPTH_LIMIT = 5
