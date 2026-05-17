# Phase 1: Backend Auto-Provisioning

## Context Links

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/auth.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/auth.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/user.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/organization.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/models/organization.py`

## Overview

Priority: P1  
Status: Completed  
Effort: 3h

Make account registration create a default organization and owner membership in the same DB session. Keep the public register response as `UserOut` unless a caller explicitly needs org data later.

## Key Insights

- `DB` dependency commits at request end and rolls back on exception.
- `repo.create_organization(...)` already creates the membership row.
- `organization_members` has uniqueness on `(organization_id, user_id)`, which protects duplicate membership inside one org but does not prevent a user from owning multiple orgs.
- There is no active `is_personal` source field. Do not rely on pycache-only artifacts.

## Requirements

- Every successful `POST /api/auth/register` creates exactly one default org for the new user.
- The new user is `owner` of that org.
- If org creation fails, user creation must roll back.
- Duplicate email behavior stays unchanged.
- Existing login/token behavior stays unchanged.
- Name generation is deterministic and handles Vietnamese names, non-ASCII names, blank names, and malformed emails.

## Architecture

Flow:

```text
POST /api/auth/register
  -> get_user_by_email
  -> create_user
  -> create_personal_org_for_user
       -> list memberships for user
       -> create_organization(owner_id=user.id, business_name=generated)
  -> return UserOut
```

Recommended helper functions in `db/crud/organization.py`:

```python
def make_personal_org_name(name: str | None, email: str | None) -> str:
    ...

async def create_personal_org_for_user(db, user) -> Organization | None:
    ...
```

`create_personal_org_for_user` should skip creation if the user already has any membership. This gives safe idempotency for future backfill scripts and admin-created users.

## Related Code Files

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/routes/auth.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/crud/organization.py`

Optional modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/api/schemas/auth.py` only if adding org data to response. Default plan does not require it.

Create:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/037_personal_org_backfill.py`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_personal_org.py`

Do not modify:

- Existing historical migrations. The runner checksum-protects applied migrations.
- Resource models for devices/campaigns/accounts in this phase.

## Implementation Steps

1. Add ASCII-folding name helper in `db/crud/organization.py`.
2. Add `make_personal_org_name(name, email)`.
3. Add `user_has_organization_membership(db, user_id)` or inline membership query.
4. Add `create_personal_org_for_user(db, user)`:
   - return `None` if user already has a membership.
   - otherwise call `create_organization(..., business_name=generated_name, business_email=user.email)`.
5. Update `/api/auth/register`:
   - create user as today.
   - immediately call `repo.create_personal_org_for_user(db, user)`.
   - return unchanged `UserOut`.
6. Create migration `037_personal_org_backfill.py`:
   - insert one org + owner membership for existing users with no membership.
   - generate names inside migration without importing app CRUD helpers.
   - make it idempotent.
7. Do not add `is_personal` unless product needs to distinguish personal vs business org in UI. YAGNI for this request.

## Todo List

- [x] Implement name helper.
- [x] Implement idempotent personal-org creation helper.
- [x] Wire helper into register route.
- [x] Add migration for existing orphan users.
- [x] Keep response contract stable.

## Success Criteria

- New registration creates one user, one organization, and one owner membership.
- Register duplicate email still returns 400.
- Simulated org insert failure rolls back the user.
- Existing users without org get one org after migration.
- Existing users with org do not get duplicate orgs after migration.

## Risk Assessment

- Risk: user name contains only non-ASCII characters and folds to empty.
  Mitigation: fallback to email prefix, then `My Workspace`.
- Risk: creating org in route without helper duplicates logic with `/organizations`.
  Mitigation: centralize in CRUD helper.
- Risk: migration imports app code and breaks when app code changes.
  Mitigation: self-contained migration functions.

## Security Considerations

- Do not trust client-supplied role blindly beyond current behavior; consider a later hardening ticket to disallow public role override.
- Do not expose org membership changes in unauthenticated endpoints.
- Keep duplicate email response unchanged to avoid widening behavior in this plan.

## Next Steps

Phase 2 confirms whether frontend needs an org-name field or can keep the current signup UI unchanged.
