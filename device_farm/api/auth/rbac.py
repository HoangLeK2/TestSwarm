from __future__ import annotations

import csv
import contextlib
import inspect
import os
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Any

import casbin
from casbin import persist
from casbin.persist import Adapter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

_MODEL_PATH = Path(__file__).with_name("rbac_model.conf")
_POLICY_PATH = Path(__file__).with_name("rbac_policy.csv")
_CASBIN_RULE_TABLE = "casbin_rule"
_CASBIN_POLICY_REVISION_TABLE = "casbin_policy_revision"
_DEFAULT_DOMAIN = "global"
_SUPERADMIN_ROLE = "superadmin"
_POLICY_COLUMNS = ("ptype", "v0", "v1", "v2", "v3", "v4", "v5")
_POLICY_CACHE_LOCK = threading.RLock()
_POLICY_CACHE: dict[str, Any] = {
    "source_key": None,
    "revision": None,
    "rows": (),
    "checked_at": 0.0,
}
_ENFORCER_CACHE: OrderedDict[
    tuple[Any, int, str, tuple[str, ...], str],
    casbin.Enforcer,
] = OrderedDict()


def permission_domain(user: Any) -> str:
    domain = str(getattr(user, "org_id", "") or "").strip()
    return domain or _DEFAULT_DOMAIN


def roles_for_user(user: Any) -> tuple[str, ...]:
    system_role = str(getattr(user, "role", "") or "").strip().lower() or "system"
    roles: set[str] = set()
    if system_role == _SUPERADMIN_ROLE:
        roles.add(_SUPERADMIN_ROLE)
    elif system_role in {"support", "platform-admin"}:
        roles.add(system_role)
    else:
        roles.add("system")
    if system_role in ("system", "operator", "admin", "support"):
        roles.add("operator")
    org_role = str(getattr(user, "org_role", "") or "").strip().lower()
    if org_role:
        roles.add(org_role)
    return tuple(sorted(roles))


def is_superadmin(user: Any) -> bool:
    return _SUPERADMIN_ROLE in roles_for_user(user)


def build_enforcer_for_user(user: Any, domain: str | None = None) -> casbin.Enforcer:
    """Build an enforcer from the checked-in seed policy.

    This sync helper remains for unit tests and non-request call sites that do
    not have a DB session. HTTP authorization should use
    build_enforcer_for_user_from_db() so production policy is database-backed.
    """
    effective_domain = (domain or permission_domain(user)).strip() or _DEFAULT_DOMAIN
    return _build_enforcer_for_identity(
        str(getattr(user, "id", "") or "").strip(),
        roles_for_user(user),
        effective_domain,
    )


@lru_cache(maxsize=4096)
def _build_enforcer_for_identity(
    user_id: str, roles: tuple[str, ...], domain: str
) -> casbin.Enforcer:
    enforcer = casbin.Enforcer(str(_MODEL_PATH), str(_POLICY_PATH))
    _attach_user_roles(enforcer, user_id, roles, domain)
    return enforcer


async def build_enforcer_for_user_from_db(
    user: Any,
    db: Any,
    domain: str | None = None,
) -> casbin.Enforcer:
    """Build an enforcer from Casbin policies stored in the database."""
    effective_domain = (domain or permission_domain(user)).strip() or _DEFAULT_DOMAIN
    policy_source = _policy_cache_source_key(db)
    revision, rows = await load_policy_snapshot_from_db(db)
    user_id = str(getattr(user, "id", "") or "").strip()
    roles = roles_for_user(user)
    cache_key = (policy_source, revision, user_id, roles, effective_domain)
    with _POLICY_CACHE_LOCK:
        cached = _ENFORCER_CACHE.get(cache_key)
        if cached is not None:
            _ENFORCER_CACHE.move_to_end(cache_key)
            return cached

    enforcer = build_enforcer_from_policy_rows(
        list(rows),
        user_id=user_id,
        roles=roles,
        domain=effective_domain,
    )
    with _POLICY_CACHE_LOCK:
        if _POLICY_CACHE.get("revision") != revision:
            _ENFORCER_CACHE.clear()
        _ENFORCER_CACHE[cache_key] = enforcer
        max_size = _policy_enforcer_cache_size()
        while len(_ENFORCER_CACHE) > max_size:
            _ENFORCER_CACHE.popitem(last=False)
    return enforcer


async def load_policy_snapshot_from_db(
    db: Any,
) -> tuple[int, tuple[tuple[str, ...], ...]]:
    """Read the current policy snapshot, using a revision-aware process cache."""
    if not hasattr(db, "execute"):
        return 0, tuple(_load_seed_policy_rows())

    source_key = _policy_cache_source_key(db)
    now = time.monotonic()
    ttl = _policy_cache_ttl_seconds()
    with _POLICY_CACHE_LOCK:
        cached_rows = _POLICY_CACHE.get("rows") or ()
        cached_source = _POLICY_CACHE.get("source_key")
        checked_at = float(_POLICY_CACHE.get("checked_at") or 0.0)
        if cached_rows and cached_source == source_key and ttl > 0 and now - checked_at < ttl:
            return int(_POLICY_CACHE["revision"]), cached_rows

    revision = await load_policy_revision_from_db(db)
    with _POLICY_CACHE_LOCK:
        cached_source = _POLICY_CACHE.get("source_key")
        cached_revision = _POLICY_CACHE.get("revision")
        cached_rows = _POLICY_CACHE.get("rows") or ()
        if cached_rows and cached_source == source_key and cached_revision == revision:
            _POLICY_CACHE["checked_at"] = now
            return revision, cached_rows

    rows = tuple(await load_policy_rows_from_db(db))
    with _POLICY_CACHE_LOCK:
        if (
            _POLICY_CACHE.get("source_key") != source_key
            or _POLICY_CACHE.get("revision") != revision
        ):
            _ENFORCER_CACHE.clear()
        _POLICY_CACHE.update(
            {
                "source_key": source_key,
                "revision": revision,
                "rows": rows,
                "checked_at": now,
            }
        )
    return revision, rows


async def load_policy_revision_from_db(db: Any) -> int:
    try:
        result = await db.execute(
            text(
                f"""
                SELECT revision
                  FROM {_CASBIN_POLICY_REVISION_TABLE}
                 WHERE id = 1
                """
            )
        )
    except SQLAlchemyError:
        return 0
    row = result.fetchone()
    if inspect.isawaitable(row):
        row = await row
    if row is None:
        return 0
    try:
        return int(row[0] or 0)
    except (KeyError, TypeError, ValueError, IndexError):
        return 0


async def load_policy_rows_from_db(db: Any) -> list[tuple[str, ...]]:
    """Read Casbin policy rows from the canonical DB table."""
    if not hasattr(db, "execute"):
        return _load_seed_policy_rows()
    try:
        result = await db.execute(
            text(
                f"""
                SELECT ptype, v0, v1, v2, v3, v4, v5
                  FROM {_CASBIN_RULE_TABLE}
                 ORDER BY id ASC
                """
            )
        )
    except SQLAlchemyError:
        return _load_seed_policy_rows()
    raw_rows = result.fetchall()
    if inspect.isawaitable(raw_rows):
        raw_rows = await raw_rows
    rows = [
        tuple("" if value is None else str(value) for value in row)
        for row in raw_rows
    ]
    return rows or _load_seed_policy_rows()


def build_enforcer_from_policy_rows(
    rows: list[tuple[str, ...]],
    *,
    user_id: str,
    roles: tuple[str, ...],
    domain: str,
) -> casbin.Enforcer:
    enforcer = casbin.Enforcer(str(_MODEL_PATH), _PolicyRowsAdapter(rows))
    enforcer.enable_auto_save(False)
    _attach_user_roles(enforcer, user_id, roles, domain)
    return enforcer


def _attach_user_roles(
    enforcer: casbin.Enforcer,
    user_id: str,
    roles: tuple[str, ...],
    domain: str,
) -> None:
    if user_id:
        for role in roles:
            enforcer.add_role_for_user_in_domain(user_id, role, domain)


def clear_rbac_cache() -> None:
    _build_enforcer_for_identity.cache_clear()
    with _POLICY_CACHE_LOCK:
        _POLICY_CACHE.update(
            {"source_key": None, "revision": None, "rows": (), "checked_at": 0.0}
        )
        _ENFORCER_CACHE.clear()


def _policy_cache_source_key(db: Any) -> tuple[str, int]:
    get_bind = getattr(db, "get_bind", None)
    if callable(get_bind):
        try:
            bind = get_bind()
        except Exception:
            bind = None
        if inspect.isawaitable(bind):
            with contextlib.suppress(Exception):
                bind.close()
            bind = None
        if bind is not None and not inspect.isawaitable(bind):
            return ("bind", id(bind))
    return ("db", id(db))


def _policy_cache_ttl_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("DEVICE_FARM_RBAC_POLICY_CACHE_TTL_SECONDS", "30")))
    except Exception:
        return 30.0


def _policy_enforcer_cache_size() -> int:
    try:
        return max(1, int(os.environ.get("DEVICE_FARM_RBAC_ENFORCER_CACHE_SIZE", "4096")))
    except Exception:
        return 4096


class _PolicyRowsAdapter(Adapter):
    def __init__(self, rows: list[tuple[str, ...]]) -> None:
        self._rows = rows

    def load_policy(self, model) -> None:
        for row in self._rows:
            persist.load_policy_line(_policy_line_from_row(row), model)

    def save_policy(self, model) -> None:
        raise NotImplementedError("RBAC policy writes must go through DB migrations/admin APIs")

    def add_policy(self, sec, ptype, rule) -> None:
        raise NotImplementedError("RBAC policy writes must go through DB migrations/admin APIs")

    def remove_policy(self, sec, ptype, rule) -> None:
        raise NotImplementedError("RBAC policy writes must go through DB migrations/admin APIs")

    def remove_filtered_policy(self, sec, ptype, field_index, *field_values) -> None:
        raise NotImplementedError("RBAC policy writes must go through DB migrations/admin APIs")


def _policy_line_from_row(row: tuple[str, ...]) -> str:
    ptype, *values = row
    return ", ".join([ptype, *[value for value in values if value != ""]])


def _load_seed_policy_rows() -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    with _POLICY_PATH.open(newline="", encoding="utf-8") as fh:
        for raw in csv.reader(fh):
            if not raw:
                continue
            values = [item.strip() for item in raw]
            if not values or values[0].startswith("#"):
                continue
            padded = values[: len(_POLICY_COLUMNS)] + [""] * (len(_POLICY_COLUMNS) - len(values))
            rows.append(tuple(padded))
    return rows
