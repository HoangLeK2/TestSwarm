from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Optional

_current_org_id: ContextVar[Optional[str]] = ContextVar("current_org_id", default=None)


def get_current_org_id() -> str | None:
    return _current_org_id.get()


def set_current_org_id(org_id: str | None) -> Token[Optional[str]]:
    return _current_org_id.set(org_id)


def clear_current_org_id(token: Token[Optional[str]] | None = None) -> None:
    if token is None:
        _current_org_id.set(None)
        return
    _current_org_id.reset(token)


@contextmanager
def tenant_context(org_id: str | None) -> Iterator[None]:
    token = set_current_org_id(org_id)
    try:
        yield
    finally:
        clear_current_org_id(token)


@contextmanager
def use_tenant_scope(org_id: str | None) -> Iterator[None]:
    """Apply tenant ORM filter when ``org_id`` is known but context var is unset."""
    if get_current_org_id() or not org_id:
        yield
        return
    with tenant_context(org_id):
        yield

