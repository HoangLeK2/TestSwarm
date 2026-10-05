from typing import Any, Dict, Optional
import os

from runtime.ai.ai_scenario import build_scenario_from_instructions as build_scenario_with_llm
from runtime.ai.ai_client import build_scenario_from_instructions as build_scenario_via_mcp


def build_scenario_from_instructions(
    instructions: str,
    ui_xml: Optional[str] = None,
) -> Dict[str, Any]:
    """
    High-level helper to build a scenario from natural language, optionally with
    current UI hierarchy XML from uiautomator2.

    Backend selection:
        SCENARIO_AI_BACKEND = "llm" | "mcp"  (default: "llm")
    """
    backend = os.getenv("SCENARIO_AI_BACKEND", "llm").strip().lower()
    if backend == "mcp":
        return build_scenario_via_mcp(instructions, ui_xml=ui_xml)
    return build_scenario_with_llm(instructions, ui_xml=ui_xml)


__all__ = [
    "build_scenario_with_llm",
    "build_scenario_via_mcp",
    "build_scenario_from_instructions",
]

