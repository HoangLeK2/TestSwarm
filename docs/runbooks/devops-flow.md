# DevOps Flow

This runbook defines the default path for shipping Device Farm changes without
breaking workspace administration, account binding, device assignment, or
campaign execution.

## 1. Local Gate

Run the quick gate before handing off a change:

```bash
scripts/devops/quality-gate.sh quick
```

The quick gate verifies:

- backend syntax for recently sensitive modules
- workspace admin and phone allocation regression
- campaign device/account binding regression
- campaign dispatch regression
- frontend typecheck

For campaign-sensitive work, run the larger campaign gate:

```bash
scripts/devops/quality-gate.sh campaign
```

For release candidates, run the full gate:

```bash
scripts/devops/quality-gate.sh full
```

## 2. Pull Request Gate

Every pull request must pass:

- backend regression
- campaign regression
- frontend typecheck and production build
- Docker Compose config preflight

CI must not use production credentials. If CI needs environment values, copy
from `.env.example` and override only non-secret test values.

## 3. Release Candidate

Before staging deploy:

```bash
git diff --check
scripts/devops/quality-gate.sh full
```

Build only the services affected by the change. Backend source changes require
rebuilding and recreating `farm`; frontend environment or source changes require
rebuilding the frontend image because `NEXT_PUBLIC_*` values are baked into the
bundle.

## 4. Staging Deploy

Deploy to staging only after the gates pass.

Recommended checks after deploy:

```bash
curl -f http://localhost:8081/api/live
curl -f http://localhost:8081/api/ready
docker compose ps
```

Then run an authenticated smoke test through the dashboard:

- superadmin can see all workspaces
- workspace admin can manage only assigned workspaces
- workspace admin allocates a phone from its agent pool to another workspace
- target workspace can see allocated phone, claim it, and connect through the
  managed agent
- account import/register works
- account can be assigned to a device
- account group can be selected for a campaign
- page/source target can be selected for a campaign
- phone/device can be assigned to a campaign
- one-device campaign dispatch starts and creates execution records
- DLQ open/close flow still works for failed executions

## 5. Production Deploy

Production deploys require explicit operator approval. Do not deploy directly
from a local dirty worktree.

Minimum production smoke:

- backend `/api/live` and `/api/ready` return success
- frontend dashboard loads with production API URL
- one admin API request succeeds with the expected role scope
- one read-only device inventory request succeeds
- one campaign detail or list request succeeds
- no new error spike appears in logs during the first 15 minutes

## 6. Rollback

Keep the previous image tag and Compose file available before deploying.

Rollback should restore the previous service image and recreate only the affected
service. Do not drop databases, delete volumes, or rotate credentials as part of
normal rollback unless the incident is specifically a credential compromise.

After rollback, repeat the production smoke checks and capture the failing build
tag for investigation.
