# Phase 05: Tests, Rollout, Observability

## Overview

Validate correctness, security, and performance before enabling direct DB writes in production.

Priority: P1  
Status: Partial  
Effort: 3h

## Context Links

- `agent-boot/relay/tests/*`
- `device_farm/tests/test_content_pipeline.py`
- `device_farm/tests/test_captures_parse_persist_accuracy.py`
- `docs/device-farm-canary-rollout.md`
- [Performance/data review](./reports/performance-data-correctness-review.md)

## Requirements

- Compare old and new extract output on same sample XML.
- Compare old and new `content_items` insert payloads, not only parser output.
- Validate DB role permissions.
- Validate duplicate retries.
- Validate parent hash mapping for comments.
- Validate relative date parsing against `captured_at`.
- Canary on one agent and one collection first.
- Keep rollback one env var away.

## Test Plan

Unit tests:

- [x] shared hash helpers match old `content_store` contract.
- [ ] shared parser golden fixtures match current parser output.
- [x] content writer builds valid insert payload.
- [x] content writer uses `ON CONFLICT DO NOTHING`.
- [x] relative timestamps use `captured_at` as base.

Integration tests:

- [ ] insert valid post/comment with agent DB role.
- [ ] duplicate insert does not create duplicate row.
- [ ] same content in different `hash_scope` persists separately.
- [ ] same content in different `user_id` persists separately.
- [x] comments link to scoped parent hash in row builder.
- [ ] FK violation is classified.
- [x] old server path works with feature flag off.
- [x] edge failure does not fall back to server-side Facebook parsing.

Security tests:

- agent role cannot `SELECT * FROM users`.
- agent role cannot update/delete `content_items`.
- agent role cannot insert into domain tables.

Performance checks:

- XML bytes uploaded to server drops on edge route.
- device_farm CPU drops during multi-device extract.
- DB connection count stays bounded.
- agent CPU stays acceptable when managing multiple devices.
- agent relay event-loop lag remains under target during XML parse load.
- XML queue backpressure works under burst load.

## Rollout

1. Local Docker/staging with one agent.
2. Canary one physical device, one collection.
3. Enable for FB posts only.
4. Add comments after parent hash behavior is verified.
5. Enable per agent group.
6. Remove old XML-heavy path only after stable production window.

## Observability

Agent logs:

- `context_id`
- `serial`
- `execution_id`
- `route=agent_boot_xml_extra_content`
- `parsed_count`
- `insert_attempted`
- `xml_bytes`
- `queue_depth`
- `db_elapsed_ms`
- `extract_elapsed_ms`
- `parse_elapsed_ms`
- `error_code`

Server logs:

- context registered
- extract completed
- edge failure reason
- content count by execution

Metrics:

- `agent_content_insert_attempt_total`
- `agent_content_insert_error_total`
- `agent_fb_extract_duration_ms`
- `agent_xml_parse_duration_ms`
- `agent_xml_queue_depth`
- `agent_xml_rejected_total`
- `agent_event_loop_lag_ms`
- `device_farm_edge_extract_error_total`
- `postgres_agent_connections`

## Success Criteria

- No cross-tenant duplicate collapse.
- No raw XML upload for successful FB post extract.
- Rollback via feature flag works.
- Agent DB role is proven narrow.
- Dashboard content queries remain correct.
- Old and new paths produce equivalent persisted data on golden fixtures.
- DB outage does not cause false success or silent data loss.

## Risks

- Production Postgres max connections too low for many agents.
- Agents on poor networks may have intermittent DB failures.
- Exact duplicate count may be unavailable without SELECT.

## Mitigation

- Use pool size 1 by default.
- Use PgBouncer if fleet grows.
- Treat no-error insert batch as accepted, and rely on DB count queries server-side.
