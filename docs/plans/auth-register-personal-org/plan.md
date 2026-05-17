---
title: "Register Account With Default Organization"
description: "Create a default owner organization during account registration without changing the current user-scoped resource model."
status: in_progress
progress: 93%
priority: P1
effort: 7h
issue: null
branch: feat/extra-data
tags: [feature, backend, frontend, database, auth]
created: 2026-05-15
---

# Register Account With Default Organization

## Overview

New accounts should always have an organization immediately after signup. The correct first step for this codebase is backend auto-provisioning: `/api/auth/register` creates the user, creates a default organization, and creates an owner membership in the same DB transaction.

Do not migrate the full app to org-level tenancy in this plan. Current devices, campaigns, accounts, schedules, content, notifications, and activity APIs are still mostly scoped by `user_id`. Switching those to `organization_id` is a separate migration plan.

## Current State

- `/api/auth/register` only creates a user and returns `UserOut`.
- `/api/organizations` can create/list organizations for an authenticated user.
- `repo.create_organization(...)` already creates `organizations` plus `organization_members(role=owner)`.
- Frontend sign-up collects `name`, `email`, `password`; it does not ask for organization name.
- `OrganizationProvider` lists organizations after login and chooses the first one.
- Historical pycache hints show earlier work existed for personal orgs, but source files are absent. Only source files are authoritative.
- `docs/development-rules.md` is referenced by the planning skill but is missing in this repo.

## Decision

Use personal/default organization auto-provisioning on registration.

Default org name:

```text
{ascii_fold(user.name or email prefix)}'s Workspace
```

Fallback:

```text
My Workspace
```

Rationale:

- Atomic: no orphan user if org creation fails.
- Minimal API contract change: register can still return `UserOut`.
- Fits current app: org switcher already expects at least one org after login.
- Avoids premature full tenant migration.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Backend Auto-Provisioning | Completed | 3h | [phase-01-backend-auto-provisioning.md](./phase-01-backend-auto-provisioning.md) |
| 2 | Frontend Signup Contract | Completed | 1h | [phase-02-frontend-signup-contract.md](./phase-02-frontend-signup-contract.md) |
| 3 | Tests And Runtime Verification | In Progress | 3h | [phase-03-tests-runtime-verification.md](./phase-03-tests-runtime-verification.md) |

## Dependencies

- Existing SQLAlchemy models: `User`, `Organization`, `OrganizationMember`.
- Existing CRUD: `create_user`, `create_organization`, `list_organizations_for_user`.
- Existing FastAPI DB dependency commits or rolls back request transaction.
- Existing frontend auth flow redirects to sign-in after signup.

## Non-Goals

- Do not add `organization_id` to every resource table in this plan.
- Do not rename existing `user_id` columns.
- Do not change JWT payload to include org claims yet.
- Do not require users to type organization name unless product explicitly asks for it.
- Do not implement invite/team-member flows.

## Open Follow-Up

After this plan lands, create a separate org-tenancy plan if the product goal is shared organization resources. That later work should add `CurrentOrganization`, `X-Organization-Id` or persisted current-org choice, `organization_id` columns, backfill, and route-level org authorization.
