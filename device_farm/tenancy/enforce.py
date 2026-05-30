from __future__ import annotations

from fastapi import HTTPException, status


def enforce_tenant(record: object, current_user: object) -> None:
    """Raise 403 if a record's org_id does not match current_user.org_id.

    Use this when a route loads a record by ID and wants an explicit guard in
    addition to ORM default scoping (defense in depth + clearer intent).
    """

    rec_org = getattr(record, "org_id", None)
    user_org = getattr(current_user, "org_id", None)
    if not rec_org or not user_org or rec_org != user_org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )

