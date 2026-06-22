from __future__ import annotations

import re
from html import escape
from typing import Any

_EVENT_EMOJI: dict[str, str] = {
    "campaign.dispatched": "🚀",
    "campaign.completed": "✅",
    "campaign.failed": "❌",
    "campaign.step_warning": "⚠️",
    "campaign.dlq_opened": "🚨",
    "schedule.run_failed": "⏰",
    "device.online": "🟢",
    "device.reconnect": "🟢",
    "device.offline": "🔴",
    "device.disconnect": "🔴",
    "account.rotated": "🔑",
    "account.locked": "🔒",
    "content.milestone": "📊",
    "mcp.action_sensitive": "🛡️",
    "dlq.threshold": "🚨",
    "task.failed": "❌",
}

_LINK_LINE_RE = re.compile(
    r"^(?:Open|Mo chi tiet|Campaign continues\. Open)\s*:\s*(https?://\S+)$",
    re.IGNORECASE,
)
_INLINE_LINK_RE = re.compile(
    r"^(Campaign continues\.|Campaign tiep tuc chay\.)\s*(?:Open|Mo chi tiet):\s*(https?://\S+)$",
    re.IGNORECASE,
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_SHORT_ID_KEYS = frozenset(
    {
        "run",
        "execution",
    }
)
_ERROR_KEYS = frozenset(
    {
        "error",
        "loi",
    }
)
_VI_HINTS = ("trang thai", "thu thap", "that bai", "hoan thanh", "thiet bi", "mo chi tiet", "da ")


def _escape(text: str) -> str:
    return escape(text, quote=False)


def _short_id(value: str) -> str:
    cleaned = value.strip()
    if _UUID_RE.fullmatch(cleaned):
        return f"{cleaned[:8]}…"
    if len(cleaned) > 24:
        return f"{cleaned[:21]}…"
    return cleaned


def _looks_vietnamese(*parts: str | None) -> bool:
    joined = " ".join(part for part in parts if part).lower()
    return any(hint in joined for hint in _VI_HINTS)


def _link_label(*parts: str | None) -> str:
    return "Mo dashboard" if _looks_vietnamese(*parts) else "Open dashboard"


def _format_field(key: str, value: str) -> str:
    key_lower = key.lower()
    if key_lower in _ERROR_KEYS:
        return f"\n<b>{_escape(key)}</b>\n<pre>{_escape(value)}</pre>"
    if key_lower in _SHORT_ID_KEYS:
        return f"• <b>{_escape(key)}:</b> <code>{_escape(_short_id(value))}</code>"
    return f"• <b>{_escape(key)}:</b> {_escape(value)}"


def _extract_deep_link(body: str | None, data: dict[str, Any] | None) -> str:
    if data:
        link = str(data.get("deep_link") or "").strip()
        if link:
            return link
    if not body:
        return ""
    for line in body.splitlines():
        match = _LINK_LINE_RE.match(line.strip())
        if match:
            return match.group(1)
        inline = _INLINE_LINK_RE.match(line.strip())
        if inline:
            return inline.group(2)
    return ""


def format_telegram_message(
    *,
    event: str | None = None,
    title: str,
    body: str | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """Render a Telegram HTML message from the shared notification title/body."""
    emoji = _EVENT_EMOJI.get(event or "", "📢")
    deep_link = _extract_deep_link(body, data)
    lines = [f"{emoji} <b>{_escape(title.strip())}</b>"]

    if body:
        for raw_line in body.strip().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _LINK_LINE_RE.match(line):
                continue
            if _INLINE_LINK_RE.match(line):
                continue

            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key.lower().startswith("open") or key.lower().startswith("mo chi tiet"):
                    continue
                lines.append(_format_field(key, value))
            else:
                lines.append(_escape(line))

    if deep_link:
        label = _link_label(title, body)
        lines.append(f'\n<a href="{escape(deep_link, quote=True)}">📎 {_escape(label)}</a>')

    return "\n".join(lines)
