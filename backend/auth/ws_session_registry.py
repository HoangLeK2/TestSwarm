"""In-memory registry mapping auth session_id → frontend WebSocket connections."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

log = logging.getLogger(__name__)


class WsSessionRegistry:
    def __init__(self) -> None:
        self._session_conns: dict[str, set[str]] = {}
        self._conn_session: dict[str, str] = {}
        self._conn_ws: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, conn_id: str, session_id: str | None, ws: WebSocket) -> None:
        if not session_id:
            return
        async with self._lock:
            self._conn_session[conn_id] = session_id
            self._conn_ws[conn_id] = ws
            self._session_conns.setdefault(session_id, set()).add(conn_id)

    async def unregister(self, conn_id: str) -> None:
        async with self._lock:
            session_id = self._conn_session.pop(conn_id, None)
            self._conn_ws.pop(conn_id, None)
            if session_id:
                bucket = self._session_conns.get(session_id)
                if bucket:
                    bucket.discard(conn_id)
                    if not bucket:
                        self._session_conns.pop(session_id, None)

    async def close_session(self, session_id: str, *, code: int = 4403) -> None:
        async with self._lock:
            conn_ids = list(self._session_conns.get(session_id, set()))
            ws_map = {cid: self._conn_ws.get(cid) for cid in conn_ids}

        for conn_id, ws in ws_map.items():
            if ws is None:
                continue
            try:
                await ws.close(code=code)
            except Exception:
                log.debug("ws close failed conn=%s session=%s", conn_id, session_id, exc_info=True)

    async def close_sessions(self, session_ids: list[str], *, code: int = 4403) -> None:
        for sid in session_ids:
            await self.close_session(sid, code=code)


_registry: WsSessionRegistry | None = None


def get_ws_session_registry() -> WsSessionRegistry:
    global _registry
    if _registry is None:
        _registry = WsSessionRegistry()
    return _registry
