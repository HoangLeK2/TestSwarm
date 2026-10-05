"""Typed relay payloads for hot agent-boot control paths."""

from __future__ import annotations

from typing import Any, TypeAlias

import msgspec

JsonMap: TypeAlias = dict[str, Any]
TimeoutValue: TypeAlias = int | float | str


class TaggedMessage(msgspec.Struct, tag_field="type"):
    pass


class AckMessage(TaggedMessage, tag="ack"):
    message: str = ""


class CommandMessage(TaggedMessage, tag="command"):
    msg_id: str = ""
    serial: str = ""
    cmd: str = ""
    timeout: TimeoutValue = 30
    cmd_type: int | str = 0


class ScrcpyStartMessage(TaggedMessage, tag="scrcpy_start"):
    serial: str = ""
    profile: str | None = None
    stream_profile: str | None = None
    quality: str | None = None
    view_mode: str | None = None
    mode: str | None = None
    focused: bool = False
    max_fps: int | float | str | None = None
    max_width: int | float | str | None = None
    bitrate: int | float | str | None = None
    control: bool = True
    port: int | float | str | None = None
    low_latency: bool = False


class ScrcpyStopMessage(TaggedMessage, tag="scrcpy_stop"):
    serial: str = ""
    reason: str = "manual_stop"


class U2RequestMessage(TaggedMessage, tag="u2_request"):
    msg_id: str = ""
    serial: str = ""
    method: str = "GET"
    path: str = "/"
    body: Any = ""
    content_type: str = ""
    timeout: TimeoutValue = 30
    priority: str | None = None
    visible: bool = False
    focused: bool = False
    deadline_ms: int | float | str | None = None
    timeout_ms: int | float | str | None = None


class U2BatchMessage(TaggedMessage, tag="u2_batch"):
    id: str = ""
    serial: str = ""
    actions: list[Any] | None = None
    early_exit: bool = True
    priority: str | None = None
    visible: bool = False
    focused: bool = False
    deadline_ms: int | float | str | None = None
    timeout_ms: int | float | str | None = None


class U2BatchCancelMessage(TaggedMessage, tag="u2_batch_cancel"):
    id: str = ""


class U2FlowMessage(TaggedMessage, tag="u2_flow"):
    id: str = ""
    serial: str = ""
    flow: str = ""
    params: JsonMap | None = None
    priority: str | None = None
    visible: bool = False
    focused: bool = False
    deadline_ms: int | float | str | None = None
    timeout_ms: int | float | str | None = None


class A11yActionMessage(TaggedMessage, tag="a11y_action"):
    id: str = ""
    serial: str = ""
    action: str = ""
    mode: str = "mutate"
    payload: JsonMap | None = None
    seq: int | str = 0
    session_id: str = ""
    ts: int | str | None = None


class PingMessage(TaggedMessage, tag="ping"):
    pass


ServerMessage: TypeAlias = (
    AckMessage
    | CommandMessage
    | ScrcpyStartMessage
    | ScrcpyStopMessage
    | U2RequestMessage
    | U2BatchMessage
    | U2BatchCancelMessage
    | U2FlowMessage
    | A11yActionMessage
    | PingMessage
)


class RegisterMessage(TaggedMessage, tag="register"):
    relay_id: str
    serials: list[str]
    version: str = "2.0.0"


class HeartbeatMessage(TaggedMessage, tag="heartbeat"):
    serials: list[str]
    capabilities: list[JsonMap]


class CommandQueueFullResult(TaggedMessage, tag="result"):
    msg_id: str
    ok: bool = False
    exit_code: int = -1
    output: str = ""
    error: str = ""


_SERVER_MESSAGE_DECODER = msgspec.json.Decoder(ServerMessage)

_MESSAGE_TYPES: dict[type[Any], str] = {
    AckMessage: "ack",
    CommandMessage: "command",
    ScrcpyStartMessage: "scrcpy_start",
    ScrcpyStopMessage: "scrcpy_stop",
    U2RequestMessage: "u2_request",
    U2BatchMessage: "u2_batch",
    U2BatchCancelMessage: "u2_batch_cancel",
    U2FlowMessage: "u2_flow",
    A11yActionMessage: "a11y_action",
    PingMessage: "ping",
}


def decode_server_message(data: str | bytes | bytearray | memoryview) -> ServerMessage | JsonMap:
    if isinstance(data, memoryview):
        data = data.tobytes()
    try:
        return _SERVER_MESSAGE_DECODER.decode(data)
    except msgspec.ValidationError as exc:
        fallback = msgspec.json.decode(data)
        if isinstance(fallback, dict):
            fallback.setdefault("_schema_error", str(exc))
        return fallback


def message_type(message: ServerMessage | JsonMap) -> str:
    if isinstance(message, dict):
        return str(message.get("type", "") or "")
    return _MESSAGE_TYPES.get(type(message), "")


def message_get(message: ServerMessage | JsonMap, field: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(field, default)
    return getattr(message, field, default)


def message_to_dict(message: ServerMessage | JsonMap) -> JsonMap:
    if isinstance(message, dict):
        return message
    return msgspec.to_builtins(message)
