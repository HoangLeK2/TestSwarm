from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import casbin

_MODEL_PATH = Path(__file__).with_name("rbac_model.conf")
_POLICY_PATH = Path(__file__).with_name("rbac_policy.csv")
_DEFAULT_DOMAIN = "global"
_SUPERADMIN_ROLE = "superadmin"


def permission_domain(user: Any) -> str:
    domain = str(getattr(user, "org_id", "") or "").strip()
    return domain or _DEFAULT_DOMAIN


def roles_for_user(user: Any) -> tuple[str, ...]:
    roles = {
        str(getattr(user, "role", "") or "").strip().lower() or "operator",
    }
    org_role = str(getattr(user, "org_role", "") or "").strip().lower()
    if org_role:
        roles.add(org_role)
    return tuple(sorted(roles))


def is_superadmin(user: Any) -> bool:
    return _SUPERADMIN_ROLE in roles_for_user(user)


def build_enforcer_for_user(user: Any, domain: str | None = None) -> casbin.Enforcer:
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
    if user_id:
        for role in roles:
            enforcer.add_role_for_user_in_domain(user_id, role, domain)
    return enforcer


def clear_rbac_cache() -> None:
    _build_enforcer_for_identity.cache_clear()
