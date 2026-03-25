from __future__ import annotations

"""
ai_scenario.py — Build scenario DSL from natural language using OpenAI.

Mục tiêu: nhận 1 câu lệnh tự nhiên (tiếng Việt/Anh) và trả về:

{
  "instructions": "<original>",
  "steps": [
    { "type": "launch_app", "package": "com.android.chrome" },
    { "type": "wait", "seconds": 3 },
    { "type": "tap_position", "pos": "top_center" },
    { "type": "input_text", "via": "u2", "text": "latest tech news today" },
    { "type": "key", "key": "enter" },
    { "type": "wait", "seconds": 4 },
    { "type": "tap_position", "pos": "middle_center" },
    { "type": "scroll_down", "repeats": 3 }
  ]
}
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import openai


def _load_prompt() -> str:
    """Load scenario prompt from prompts/scenario_prompt.md."""
    root = Path(__file__).resolve().parent.parent
    prompt_path = root / "prompts" / "scenario_prompt.md"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except Exception:
        # Fallback nội tuyến rất ngắn nếu file bị thiếu
        return (
            "You are a compiler that converts natural language instructions "
            "into a scenario JSON with an 'instructions' string and 'steps' array."
        )


_SCENARIO_PROMPT = _load_prompt()


def _get_provider() -> str:
    """
    Chọn provider LLM: 'openai' (default) hoặc 'gemini'.
    Điều khiển bằng env SCENARIO_AI_PROVIDER.
    """
    return os.environ.get("SCENARIO_AI_PROVIDER", "openai").strip().lower()


def _parse_scenario_from_content(content: str, source: str) -> Dict[str, Any]:
    if not content or not content.strip():
        raise RuntimeError(f"No content from {source}")

    import json
    import re

    raw = content.strip()
    # Strip optional markdown code fence so json.loads works
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse JSON from {source}: {exc}") from exc

    scenario = parsed.get("scenario")
    if not isinstance(scenario, dict):
        raise RuntimeError(f"{source} response missing 'scenario' object")

    steps = scenario.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RuntimeError("scenario.steps must be a non-empty array")

    # Reject useless output: only wait with seconds=0
    if all(
        (s.get("type") == "wait" and (s.get("seconds") or 0) == 0)
        for s in steps
    ):
        raise RuntimeError(
            "scenario.steps are all wait(0); model returned no real actions. "
            "Retry with clearer prompt or richer UI XML."
        )

    return scenario


def _get_openai_client() -> openai.Client:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return openai.OpenAI(api_key=api_key)


# Separator used by frontend when sending multiple screens
_UI_SNAPSHOT_SEP = "\n\n--- UI hierarchy (màn hình "
_MAX_XML_CHARS = int(os.environ.get("SCENARIO_UI_XML_MAX_CHARS", "20000"))
# Per-screen limit when multiple snapshots (so total context stays bounded)
_MAX_XML_CHARS_PER_SCREEN = int(os.environ.get("SCENARIO_UI_XML_MAX_CHARS_PER_SCREEN", "15000"))


def _build_input_context_json(
    instructions: str,
    ui_xml: Optional[str] = None,
    device_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a single JSON object with all context for the LLM.
    When ui_xml contains multiple screens (separator "--- UI hierarchy (màn hình N) ---"),
    split into ui_snapshots[] so the model sees each screen clearly.
    """
    ctx: Dict[str, Any] = {
        "instructions": instructions.strip(),
        "device_context": device_context if (device_context and any(v for v in (device_context or {}).values() if v)) else None,
        "ui_snapshots": [],
    }
    if ui_xml and ui_xml.strip():
        if _UI_SNAPSHOT_SEP in ui_xml:
            # Multiple screens: split by "--- UI hierarchy (màn hình "
            raw_parts = ui_xml.split(_UI_SNAPSHOT_SEP)
            for i, part in enumerate(raw_parts):
                part = part.strip()
                if not part:
                    continue
                # part is "N) ---\n\n<xml>" — drop "N) ---\n\n"
                if ")\n\n" in part:
                    xml_chunk = part.split(")\n\n", 1)[-1].strip()
                else:
                    xml_chunk = part.split("---", 1)[-1].strip()
                xml_chunk = xml_chunk[: _MAX_XML_CHARS_PER_SCREEN]
                screen_num = len(ctx["ui_snapshots"]) + 1
                ctx["ui_snapshots"].append({
                    "screen": screen_num,
                    "description": f"Screen {screen_num} (uiautomator2 hierarchy)",
                    "xml": xml_chunk,
                })
        else:
            ctx["ui_snapshots"].append({
                "screen": 1,
                "description": "Current screen (uiautomator2 hierarchy)",
                "xml": ui_xml.strip()[: _MAX_XML_CHARS],
            })
    return ctx


def _write_debug_json(input_json: Dict[str, Any]) -> None:
    """Nếu set SCENARIO_DEBUG_JSON_PATH (đường dẫn file .json), ghi input gửi AI ra file để debug."""
    path = os.environ.get("SCENARIO_DEBUG_JSON_PATH", "").strip()
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(input_json, f, ensure_ascii=False, indent=2)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Could not write scenario debug JSON to %s: %s", path, e)


_STRICT_STEPS_HINT = (
    " CRITICAL: You MUST output concrete steps (open_url, launch_app, wait 2–5s, tap_position/tap_selector/tap_ratio, input_text, key). "
    "Do NOT output only wait steps or steps with seconds: 0."
)


def _call_openai(
    instructions: str,
    ui_xml: Optional[str] = None,
    device_context: Optional[Dict[str, Any]] = None,
    *,
    retry_strict: bool = False,
) -> Dict[str, Any]:
    client = _get_openai_client()

    input_json = _build_input_context_json(instructions, ui_xml=ui_xml, device_context=device_context)
    _write_debug_json(input_json)
    user_content = (
        "Generate a scenario from the following JSON input. "
        "The JSON contains: instructions (natural language, may be in English or Vietnamese), "
        "optional device_context, and optional ui_snapshots (one or more UI hierarchy XMLs from different screens). "
        "Use the XML to choose accurate selectors (resource-id, text, class) for tap_selector and input_text. "
        "Return ONLY a JSON object with a single top-level key \"scenario\" (with \"instructions\" and \"steps\" array)."
        + (_STRICT_STEPS_HINT if retry_strict else "")
        + "\n\n"
        + json.dumps(input_json, ensure_ascii=False, indent=2)
    )

    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[
            {"role": "system", "content": _SCENARIO_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content
    scenario = _parse_scenario_from_content(content, source="OpenAI")
    return scenario


def _call_gemini(
    instructions: str,
    ui_xml: Optional[str] = None,
    device_context: Optional[Dict[str, Any]] = None,
    *,
    retry_strict: bool = False,
) -> Dict[str, Any]:
    # Ưu tiên GEMINI_API_KEY, fallback GOOGLE_API_KEY
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is not set")

    # NOTE: google.generativeai is deprecated; migrate when switching to google.genai
    import google.generativeai as genai  # type: ignore[import]
    genai.configure(api_key=api_key)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)

    input_json = _build_input_context_json(instructions, ui_xml=ui_xml, device_context=device_context)
    _write_debug_json(input_json)
    user_content = (
        "Generate a full scenario from the following JSON input. "
        "The JSON has: instructions (natural language), optional device_context, and optional ui_snapshots (UI hierarchy XML per screen). "
        "You MUST output a concrete sequence of steps (open_url, wait 2–5s, tap_selector or tap_position, input_text, key, etc.) — never only wait steps or seconds: 0. "
        "Use the XML for selectors when available; if XML has few nodes use tap_position/tap_ratio and class name android.widget.EditText before input_text. "
        "Return ONLY a JSON object with one top-level key \"scenario\" containing \"instructions\" and \"steps\" (non-empty array)."
        + (_STRICT_STEPS_HINT if retry_strict else "")
        + "\n\n"
        + json.dumps(input_json, ensure_ascii=False, indent=2)
    )
    prompt = user_content

    resp = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )

    content = resp.text
    scenario = _parse_scenario_from_content(content, source="Gemini")
    return scenario


def build_scenario_from_instructions(
    instructions: str,
    ui_xml: Optional[str] = None,
    device_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Gọi LLM (OpenAI hoặc Gemini) để biên dịch câu lệnh tự nhiên thành scenario DSL.

    Điều khiển provider bằng env:
      - SCENARIO_AI_PROVIDER=openai|gemini (default: openai)

    Return:
        scenario: dict với keys:
          - instructions: original string
          - steps: list[dict] theo DSL mà run_scenario_task hiểu được.
    """
    if not instructions or not instructions.strip():
        raise ValueError("instructions is empty")

    provider = _get_provider()
    call_kw = {"instructions": instructions, "ui_xml": ui_xml, "device_context": device_context}
    try:
        if provider == "gemini":
            scenario = _call_gemini(**call_kw)
        else:
            scenario = _call_openai(**call_kw)
    except RuntimeError as e:
        if "all wait(0)" not in str(e):
            raise
        # Retry once with strict hint
        if provider == "gemini":
            scenario = _call_gemini(**call_kw, retry_strict=True)
        else:
            scenario = _call_openai(**call_kw, retry_strict=True)

    if not scenario.get("instructions"):
        scenario["instructions"] = instructions

    return scenario

