from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    import fcntl
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

TokenScope = Literal["device", "user"]
_STORE_LOCK = threading.RLock()


@dataclass(frozen=True)
class McpTokenRecord:
    id: str
    name: str
    hashed_value: str
    scope_type: TokenScope
    scope_ref: str | None
    owner_user_id: str | None
    org_id: str | None
    created_at: float
    revoked_at: float | None = None

    def public_dict(self, *, include_internal: bool = False) -> dict[str, Any]:
        out = {
            "id": self.id,
            "name": self.name,
            "prefix": self.id[:12],
            "scope_type": self.scope_type,
            "scope_ref": self.scope_ref,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
            "status": "revoked" if self.revoked_at else "active",
        }
        if include_internal:
            out["owner_user_id"] = self.owner_user_id
            out["org_id"] = self.org_id
        return out


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_id(token: str) -> str:
    return hash_token(token)[:24]


def _use_file_store() -> bool:
    return bool((os.environ.get("DEVICE_FARM_MCP_TOKEN_STORE") or "").strip())


def token_store_path() -> Path:
    configured = (os.environ.get("DEVICE_FARM_MCP_TOKEN_STORE") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "mcp_tokens.json"


def _token_store_lock_path() -> Path:
    path = token_store_path()
    return path.with_name(f"{path.name}.lock")


@contextmanager
def _locked_store():
    with _STORE_LOCK:
        lock_path = _token_store_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_fh:
            if fcntl is not None:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _run_db(coro):
    from db.database import run_activity_coro_blocking

    return run_activity_coro_blocking(coro)


def _read_records() -> list[McpTokenRecord]:
    path = token_store_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    records: list[McpTokenRecord] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            records.append(McpTokenRecord(**item))
        except Exception:
            continue
    return records


def _write_records(records: list[McpTokenRecord]) -> None:
    path = token_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [record.__dict__ for record in records]
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        try:
            path.chmod(0o600)
        except Exception:
            pass
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


def list_tokens(
    *,
    include_revoked: bool = False,
    org_id: str | None = None,
    owner_user_id: str | None = None,
) -> list[McpTokenRecord]:
    if _use_file_store():
        with _locked_store():
            records = _read_records()
        if org_id is not None:
            records = [
                record
                for record in records
                if record.org_id == org_id
                or (record.org_id is None and owner_user_id and record.owner_user_id == owner_user_id)
            ]
        elif owner_user_id is not None:
            records = [record for record in records if record.owner_user_id == owner_user_id]
        if include_revoked:
            return records
        return [record for record in records if record.revoked_at is None]

    async def _list() -> list[McpTokenRecord]:
        from db.crud.mcp_token import list_mcp_tokens, row_to_record
        from db.database import activity_session

        async with activity_session() as db:
            rows = await list_mcp_tokens(
                db,
                include_revoked=include_revoked,
                org_id=org_id,
                owner_user_id=owner_user_id,
            )
            return [row_to_record(row) for row in rows]

    return _run_db(_list())


def create_token(
    *,
    name: str,
    scope_type: TokenScope,
    scope_ref: str | None = None,
    owner_user_id: str | None = None,
    org_id: str | None = None,
) -> tuple[McpTokenRecord, str]:
    if scope_type not in {"device", "user"}:
        raise ValueError("scope_type must be device or user")

    if _use_file_store():
        plaintext = f"dfmcp_{secrets.token_urlsafe(32)}"
        record = McpTokenRecord(
            id=token_id(plaintext),
            name=name.strip() or f"{scope_type} MCP token",
            hashed_value=hash_token(plaintext),
            scope_type=scope_type,
            scope_ref=str(scope_ref) if scope_ref is not None else None,
            owner_user_id=str(owner_user_id) if owner_user_id is not None else None,
            org_id=str(org_id) if org_id is not None else None,
            created_at=time.time(),
        )
        with _locked_store():
            records = _read_records()
            records.append(record)
            _write_records(records)
        return record, plaintext

    async def _create() -> tuple[McpTokenRecord, str]:
        from db.crud.mcp_token import create_mcp_token, row_to_record
        from db.database import activity_session

        async with activity_session() as db:
            row, plaintext = await create_mcp_token(
                db,
                name=name,
                scope_type=scope_type,
                scope_ref=scope_ref,
                owner_user_id=owner_user_id,
                org_id=org_id,
            )
            await db.commit()
            return row_to_record(row), plaintext

    return _run_db(_create())


def revoke_token(record_id: str, *, org_id: str | None = None) -> bool:
    if _use_file_store():
        now = time.time()
        updated = False
        records: list[McpTokenRecord] = []
        with _locked_store():
            for record in _read_records():
                if (
                    record.id == record_id
                    and record.revoked_at is None
                    and (org_id is None or record.org_id == org_id)
                ):
                    record = McpTokenRecord(**{**record.__dict__, "revoked_at": now})
                    updated = True
                records.append(record)
            if updated:
                _write_records(records)
        return updated

    async def _revoke() -> bool:
        from db.crud.mcp_token import revoke_mcp_token
        from db.database import activity_session

        async with activity_session() as db:
            ok = await revoke_mcp_token(db, record_id, org_id=org_id)
            await db.commit()
            return ok

    return _run_db(_revoke())


async def lookup_token_async(
    token: str,
    *,
    db: Any | None = None,
) -> McpTokenRecord | None:
    hashed = hash_token(token)

    if _use_file_store():
        with _locked_store():
            for record in _read_records():
                if record.hashed_value == hashed and record.revoked_at is None:
                    return record
        return None

    from db.crud.mcp_token import lookup_mcp_token, row_to_record

    if db is not None:
        row = await lookup_mcp_token(db, token)
        return row_to_record(row) if row is not None else None

    from db.database import activity_session

    async with activity_session() as session:
        row = await lookup_mcp_token(session, token)
        return row_to_record(row) if row is not None else None


def lookup_token(token: str) -> McpTokenRecord | None:
    hashed = hash_token(token)

    if _use_file_store():
        with _locked_store():
            for record in _read_records():
                if record.hashed_value == hashed and record.revoked_at is None:
                    return record
        return None

    async def _lookup() -> McpTokenRecord | None:
        return await lookup_token_async(token)

    return _run_db(_lookup())
