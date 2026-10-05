from __future__ import annotations

import os
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from tenancy.context import get_current_org_id
from tenancy.models import TenantScopedModel


def _strict_mode_enabled() -> bool:
    raw = str(os.environ.get("TENANCY_STRICT_MODE", "true")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def init_tenant_scoping() -> None:
    """Register ORM-level default tenant filter.

    Notes:
    - Applied on the *sync* Session class, which covers AsyncSession too.
    - Only affects models inheriting `TenantScopedModel` (org_id present).
    - In strict mode, SELECTs outside a tenant context raise to prevent leaks
      in background jobs that forgot to set context.
    """

    if getattr(init_tenant_scoping, "_installed", False):
        return
    setattr(init_tenant_scoping, "_installed", True)

    @event.listens_for(Session, "do_orm_execute")  # type: ignore[misc]
    def _add_tenant_filter(execute_state: Any) -> None:
        if not execute_state.is_select:
            return

        org_id = get_current_org_id()
        if not org_id:
            if _strict_mode_enabled():
                # Raise only when the ORM SELECT targets a tenant-scoped entity.
                try:
                    desc = getattr(execute_state.statement, "column_descriptions", None)
                    if desc:
                        for d in desc:
                            ent = d.get("entity")
                            if ent is not None and issubclass(ent, TenantScopedModel):
                                raise RuntimeError(
                                    "TENANCY_STRICT_MODE: attempted tenant-scoped SELECT without current_org_id"
                                )
                except TypeError:
                    # Non-class entities or non-ORM statements.
                    pass
            return

        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantScopedModel,
                lambda cls: cls.org_id == org_id,
                include_aliases=True,
            )
        )

