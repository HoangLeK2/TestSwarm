
from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from typing import Any

import httpx
from PIL import Image

log = logging.getLogger(__name__)

_last_call: dict[str, float] = {}
_MIN_INTERVAL = 1.0  # seconds


def _rate_limit(provider: str) -> None:
    now = time.monotonic()
    last = _last_call.get(provider, 0)
    wait = _MIN_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[provider] = time.monotonic()


def _image_to_b64(image_bytes: bytes, max_width: int = 1024, quality: int = 85) -> str:
    """Convert image bytes to base64 JPEG, optionally downscaling for API cost control."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode == "RGBA":
        img = img.convert("RGB")

    # Downscale if too wide (saves API tokens for high-DPI screenshots)
    if max_width and img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _strip_markdown_json(content: str) -> str:
    """Strip markdown code fences from AI responses: ```json ... ```"""
    content = content.strip()
    if content.startswith("```"):
        # Remove first line (```json or ```)
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


class AIVisionExtractor:
    """Extract structured data from screenshots using AI Vision APIs."""

    def __init__(self, timeout: float = 60.0, max_retries: int = 3) -> None:
        self._timeout = timeout
        self._max_retries = max_retries

    def extract(
        self,
        image_bytes: bytes,
        prompt: str,
        provider: str = "openai",
        output_format: str = "json",
        model: str | None = None,
        region: dict[str, float] | None = None,
    ) -> dict[str, Any] | str:
        """
        Extract data from screenshot using AI Vision.

        Args:
            image_bytes:    Raw JPEG/PNG bytes
            prompt:         Extraction instruction for the AI
            provider:       "openai" or "gemini"
            output_format:  "json" (parsed dict) or "text" (raw string)
            model:          Override model name
            region:         Crop region {x1, y1, x2, y2} as ratios [0, 1]

        Returns:
            Parsed dict (format=json) or string (format=text)
        """
        if region:
            image_bytes = self._crop_region(image_bytes, region)

        if provider == "openai":
            return self._extract_openai(image_bytes, prompt, output_format, model)
        elif provider == "gemini":
            return self._extract_gemini(image_bytes, prompt, output_format, model)
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'gemini'.")

    # ── OpenAI ────────────────────────────────────────────────────────────────

    def _extract_openai(
        self, image_bytes: bytes, prompt: str, fmt: str, model: str | None,
    ) -> dict[str, Any] | str:
        model = model or os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        b64 = _image_to_b64(image_bytes)
        full_prompt = prompt
        if fmt == "json":
            full_prompt += "\n\nRespond with valid JSON only. No markdown, no explanation."

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": full_prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high",
                }},
            ],
        }]

        body = {
            "model": model,
            "messages": messages,
            "max_tokens": 2000,
            "temperature": 0,
        }

        content = self._call_with_retry(
            "openai",
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json_body=body,
            extract_fn=lambda r: r["choices"][0]["message"]["content"],
        )

        if fmt == "json":
            return json.loads(_strip_markdown_json(content))
        return content

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _extract_gemini(
        self, image_bytes: bytes, prompt: str, fmt: str, model: str | None,
    ) -> dict[str, Any] | str:
        model = model or os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY not set")

        b64 = _image_to_b64(image_bytes)
        full_prompt = prompt
        if fmt == "json":
            full_prompt += "\n\nRespond with valid JSON only. No markdown, no explanation."

        body = {
            "contents": [{
                "parts": [
                    {"text": full_prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                ],
            }],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2000,
            },
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        )

        content = self._call_with_retry(
            "gemini",
            url,
            params={"key": api_key},
            json_body=body,
            extract_fn=lambda r: r["candidates"][0]["content"]["parts"][0]["text"],
        )

        if fmt == "json":
            return json.loads(_strip_markdown_json(content))
        return content

    # ── HTTP with retry ───────────────────────────────────────────────────────

    def _call_with_retry(
        self,
        provider: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any],
        extract_fn: Any,
    ) -> str:
        _rate_limit(provider)
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    )
                    resp.raise_for_status()
                    return extract_fn(resp.json())

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                code = exc.response.status_code
                if code == 429:
                    wait = min(2 ** attempt * 5, 30)
                    log.warning(f"[{provider}] Rate limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                if code >= 500:
                    wait = 2 ** attempt
                    log.warning(f"[{provider}] Server error {code}, retry in {wait}s")
                    time.sleep(wait)
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning(f"[{provider}] Connection error, retry in {wait}s: {exc}")
                time.sleep(wait)
                continue

        raise last_exc or RuntimeError(f"[{provider}] All retries exhausted")

    @staticmethod
    def _crop_region(image_bytes: bytes, region: dict[str, float]) -> bytes:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        box = (
            int(region.get("x1", 0) * w),
            int(region.get("y1", 0) * h),
            int(region.get("x2", 1.0) * w),
            int(region.get("y2", 1.0) * h),
        )
        img = img.crop(box)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    # ── Phase 4: schema-driven universal extraction ──────────────────────────

    # Class-level cost counter (per-process). Reset with AIVisionExtractor.reset_budget().
    _session_cost_usd: float = 0.0
    _COST_PER_CALL = {
        # Approximate prices for a single screenshot at ~1024 wide.
        "gpt-4o": 0.005,
        "gpt-4o-mini": 0.0005,
        "gemini-1.5-pro": 0.002,
        "gemini-2.0-flash": 0.0005,
    }
    # Screen-hash → result cache (stable for same screen within session).
    _cache: dict[str, Any] = {}

    @classmethod
    def reset_budget(cls) -> None:
        cls._session_cost_usd = 0.0

    @classmethod
    def session_cost_usd(cls) -> float:
        return cls._session_cost_usd

    def extract_with_schema(
        self,
        image_bytes: bytes,
        schema: dict,
        *,
        provider: str = "gemini",
        model: str | None = None,
        hierarchy_summary: str | None = None,
        max_cost_usd: float = 5.0,
        use_cache: bool = True,
    ) -> list[dict] | dict:
        """Phase 4 — schema-driven universal extraction.

        schema = {
          "name": "social_post",
          "fields": [{"name": "author", "type": "string", "required": true, "hint": "..."}, ...],
          "multiple": True,
          "container_hint": "each feed post card",
        }

        Returns list[dict] if schema.multiple else dict.
        Caches by screen hash + schema name.
        Raises BudgetExceeded if running cost would exceed max_cost_usd.
        """
        # Cache by (screen bytes hash, schema name)
        import hashlib as _h
        screen_hash = _h.md5(image_bytes).hexdigest()
        cache_key = f"{screen_hash}:{schema.get('name', 'ad-hoc')}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Cost gate
        est_cost = self._COST_PER_CALL.get(model or "", 0.005)
        if self.session_cost_usd() + est_cost > max_cost_usd:
            raise RuntimeError(
                f"LLM budget ${max_cost_usd} reached (current ${self.session_cost_usd():.4f})"
            )

        prompt = self._build_schema_prompt(schema, hierarchy_summary)
        out = self.extract(image_bytes, prompt, provider=provider, output_format="json", model=model)

        # Normalize to list if `multiple=True`.
        if schema.get("multiple", True):
            if isinstance(out, dict):
                # Some models return {"items": [...]} — unwrap.
                if "items" in out and isinstance(out["items"], list):
                    out = out["items"]
                else:
                    out = [out]
            items = out if isinstance(out, list) else []
            result: list[dict] | dict = [
                i for i in items if self._validate_item(i, schema)
            ]
        else:
            result = out if isinstance(out, dict) else {}

        type(self)._session_cost_usd += est_cost
        if use_cache:
            self._cache[cache_key] = result
        return result

    @staticmethod
    def _build_schema_prompt(schema: dict, hierarchy_summary: str | None) -> str:
        fields = schema.get("fields") or []
        lines = []
        for f in fields:
            name = f.get("name", "")
            ftype = f.get("type", "string")
            req = "required" if f.get("required") else "optional"
            hint = f.get("hint", "")
            values = f.get("values")
            extra = f" (one of {values})" if values else ""
            lines.append(f"- {name} ({ftype}, {req}){extra}: {hint}")
        fields_desc = "\n".join(lines) if lines else "- any visible structured data"

        multiple = schema.get("multiple", True)
        container = schema.get("container_hint", "each repeated item visible on screen")
        multi_instr = (
            f"Extract ONE entry per {container}. Return a JSON array."
            if multiple else
            "Extract a single JSON object."
        )

        summary_block = ""
        if hierarchy_summary:
            summary_block = (
                f"\n\nUI hierarchy context (text + content-desc only, truncated):\n"
                f"{hierarchy_summary}\n"
            )

        return (
            f"Extract structured data from this mobile app screenshot.\n\n"
            f"Fields to extract:\n{fields_desc}\n\n"
            f"{multi_instr}{summary_block}\n\n"
            f"Return ONLY valid JSON. If no items match, return []."
        )

    @staticmethod
    def _validate_item(item: dict, schema: dict) -> bool:
        if not isinstance(item, dict):
            return False
        required = [f["name"] for f in (schema.get("fields") or []) if f.get("required")]
        return all(item.get(k) not in (None, "", []) for k in required)
