from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

AI_MCP_URL = os.getenv("AI_MCP_URL", "http://localhost:4000")


def _is_trivial_wait_scenario(scenario: Dict[str, Any]) -> bool:

    steps = scenario.get("steps")
    if not isinstance(steps, list) or not steps:
        return True
    return all(
        isinstance(step, dict)
        and step.get("type") == "wait"
        and (step.get("seconds") or 0) == 0
        for step in steps
    )


def build_scenario_from_instructions(
    instructions: str,
    ui_xml: Optional[str] = None,
    device_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Ưu tiên gọi AI MCP server (Node+TS). Nếu MCP không chạy (connection refused/timeout)
    HOẶC trả về scenario vô nghĩa (chỉ wait(0)), thì fallback sang LLM tích hợp (OpenAI/Gemini).
    """
    payload: Dict[str, Any] = {"instructions": instructions}
    if ui_xml:
        payload["ui_xml"] = ui_xml
    if device_context:
        payload["device_context"] = device_context
    # Để AI MCP (Node) generate đúng format, gửi kèm URL schema (GET trả về step types + fields).
    base = os.getenv("DEVICE_FARM_URL", "http://localhost:8081").rstrip("/")
    payload["schema_url"] = f"{base}/api/scenario/schema"

    try:
        resp = requests.post(
            f"{AI_MCP_URL}/scenario",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("scenario", data)
        if not isinstance(raw, dict):
            raise RuntimeError("MCP /scenario response missing 'scenario' object")
        if _is_trivial_wait_scenario(raw):
            raise RuntimeError("MCP returned only wait(0) steps")
        return raw
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.warning("AI MCP unreachable (%s), using built-in LLM fallback", e)
    except Exception as e:  # noqa: BLE001
        # MCP chạy nhưng trả về scenario kém chất lượng → log rồi fallback.
        log.warning("AI MCP scenario rejected (%s), using built-in LLM fallback", e)

    from runtime.ai.ai_scenario import build_scenario_from_instructions as _fallback

    return _fallback(instructions, ui_xml=ui_xml, device_context=device_context)

