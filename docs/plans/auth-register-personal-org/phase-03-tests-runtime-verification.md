# Phase 3: Tests And Runtime Verification

## Context Links

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/__init__.py`
- `/Users/hoanglcpila.vn/deviceFarmer/docker-compose.yml`
- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/config.yaml`

## Overview

Priority: P1  
Status: In Progress  
Effort: 3h

Add focused tests for registration auto-provisioning and verify the runtime-visible contract against the active database.

## Key Insights

- Migration runner applies source files matching `[0-9]*.py`.
- Existing pycache-only migration artifacts do not count.
- This repo often needs runtime DB verification after source changes.
- `pytest` may need `uv run pytest` from `device_farm`.

## Requirements

- Unit tests cover name generation.
- Route or CRUD test covers `register -> user + org + owner membership`.
- Migration test or direct migration check covers existing users without memberships.
- Runtime DB check confirms a real registered user has a real organization row.

## Related Code Files

Create:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/test_personal_org.py`

Modify:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/conftest.py` only if a fixture is needed.

No frontend test required unless Phase 2 adds UI fields.

## Implementation Steps

1. Add pure unit tests:
   - `"Hoang"` -> `"Hoang's Workspace"`.
   - `"Hoang"` with Vietnamese diacritics folds correctly.
   - non-ASCII-only name falls back to email prefix.
   - blank name and blank email fall back to `My Workspace`.
2. Add CRUD tests:
   - user with no membership creates org.
   - user with existing membership skips creation.
3. Add route test:
   - mock or in-memory DB path posts `/api/auth/register`.
   - assert `create_user` and `create_personal_org_for_user` are called in order, or assert persisted rows if using DB fixture.
4. Add migration verification:
   - seed user without membership.
   - run migration.
   - assert one org and owner membership.
   - rerun migration and assert no duplicates.
5. Run targeted backend tests:

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_personal_org.py -q
```

6. Run compile/import check:

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run python -m py_compile api/routes/auth.py db/crud/organization.py db/migrations/037_personal_org_backfill.py
```

7. Runtime verification:
   - start or reuse the app DB.
   - call `POST /api/auth/register` with a unique test email.
   - query DB:

```sql
SELECT u.email, o.business_name, m.role
FROM users u
JOIN organization_members m ON m.user_id = u.id
JOIN organizations o ON o.id = m.organization_id
WHERE u.email = '<test email>';
```

Expected: one row, role `owner`.

## Todo List

- [x] Add tests for name generation.
- [x] Add tests for idempotent org creation.
- [x] Add register route test.
- [x] Add migration/backfill verification.
- [x] Run targeted test commands.
- [ ] Verify live DB row after registering a real account.

## Success Criteria

- Tests pass.
- New account registration is runtime-visible as user + org + owner membership.
- Existing account backfill is idempotent.
- No unrelated resource scoping behavior changes.

## Risk Assessment

- Risk: test setup imports app config and hits local Postgres.
  Mitigation: prefer CRUD-level mocks or existing async DB fixtures.
- Risk: live DB has existing dirty test user.
  Mitigation: use timestamped unique email.

## Security Considerations

- Do not log plaintext password in tests or runtime verification.
- Use throwaway test email and cleanup if needed.

## Next Steps

After validation, implementation can run with:

```bash
/ck:cook --auto /Users/hoanglcpila.vn/deviceFarmer/docs/plans/auth-register-personal-org/plan.md
```
