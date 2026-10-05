# AI phone-agent service Docker POC evidence - 2026-10-06

## Status

`LOCAL_DOCKER_POC_PASS`.

This is a standalone AI phone-agent service POC. It does not change production
Device Platform Tester routes, scheduler, lease handling, policy enforcement,
device execution or evidence storage.

## Implemented surface

- New service directory: `ai-phone-agent-service/`.
- Docker compose entrypoint: `docker-compose.ai-phone-agent.yml`.
- Health endpoints: `GET /health/live`, `GET /health/ready`.
- Metrics endpoint: `GET /metrics`.
- Compile-mode contract:
  - `POST /v1/plans`
  - `GET /v1/plans/{job_id}`
- Reactive-mode contract:
  - `POST /v1/sessions`
  - `POST /v1/sessions/{session_id}/observations`
  - `POST /v1/sessions/{session_id}/action-results`
  - `POST /v1/sessions/{session_id}/cancel`

The planner is deterministic and provider-free. It exists to prove the service
boundary, typed schema, idempotency and Docker deploy path before wiring
Mobilerun, AutoGLM or a model gateway.

## Verification

| Check | Command | Result |
| --- | --- | --- |
| Unit/API contract tests | `uv run --python 3.12 --with-editable . --extra dev pytest -q` from `ai-phone-agent-service/` | `5 passed, 1 warning in 0.18s` |
| Docker build/deploy | `docker compose -f docker-compose.ai-phone-agent.yml up -d --build` | image `ai-phone-agent-service:local`, container `ai-phone-agent-service` started |
| Docker E2E HTTP | `uv run --python 3.12 ai-phone-agent-service/tests/e2e_http.py` | PASS; returned plan, session and action `launch` |
| Container health | `docker inspect ai-phone-agent-service --format '{{.State.Health.Status}} {{.State.Status}}'` | `healthy running` |
| Ready endpoint | `curl -fsS http://127.0.0.1:8095/health/ready` | `status=ok`, schema `ai-phone-agent.v1` |
| Diff hygiene | `git diff --check -- ai-phone-agent-service docker-compose.ai-phone-agent.yml` | PASS |
| GitNexus scope check | `node .gitnexus/run.cjs detect_changes --repo device-farm --scope all` | `No changes detected`; new files are not in the existing indexed graph |

## Runtime evidence

Docker E2E output:

```json
{"plan_id":"plan_780bc1e8a297443f93a4eb072c0cce0e","session_id":"sess_faee75417bf045b28f939e32e2f7766d","action":"launch"}
```

Container state after E2E:

```text
healthy running
```

Metrics after E2E:

```text
ai_phone_agent_plans_total 1
ai_phone_agent_sessions_active 1
```

## Boundaries and next steps

- No third-party repo code was vendored.
- No raw ADB, tenant database or production credential access is present.
- The current in-memory store is for local POC only; production requires durable
  outbox/session state.
- Next integration step is a platform client/outbox feature flag that calls this
  service for compile mode while keeping scenario approval, policy validation and
  dispatch in Device Platform Tester.
