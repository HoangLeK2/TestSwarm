---
title: "agent-boot XML Extra Data Writer"
description: "Move XML extra-data parsing and content_items persistence to agent-boot."
status: partial
priority: P1
effort: 21h
branch: feat/extra-data
tags: [feature, backend, database, edge-worker]
created: 2026-05-14
---

# agent-boot XML Extra Data Writer

## Overview

Move the XML extra-data hot path from `device_farm` to `agent-boot`: the phone/APK sends XML to `agent-boot`, `agent-boot` parses Facebook content, and inserts directly into `content_items`. Keep `device_farm` as the control plane that assigns context, owns campaign/user/execution metadata, and receives progress summaries.

## Decision

Recommended architecture:

```text
device_farm creates job/context
  -> phone/APK sends hierarchy XML to agent-boot
  -> agent-boot parses extra FB data locally
  -> agent-boot INSERT content_items ON CONFLICT DO NOTHING
  -> agent-boot reports progress/errors to device_farm
```

Not recommended:

```text
agent-boot writes campaigns/accounts/devices/users
```

Agent only needs valid IDs from the context payload.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Contract and DB Safety | Partial | 4h | [phase-01](./phase-01-contract-db-safety.md) |
| 2 | Shared Extract and Hashing | Partial | 5h | [phase-02](./phase-02-shared-extract-hashing.md) |
| 3 | agent-boot Edge Runner | Partial | 5h | [phase-03](./phase-03-agent-boot-edge-runner.md) |
| 4 | device_farm Control Plane | Partial | 4h | [phase-04](./phase-04-device-farm-control-plane.md) |
| 5 | Tests, Rollout, Observability | Partial | 3h | [phase-05](./phase-05-tests-rollout-observability.md) |

## Core Requirements

- `agent-boot` inserts only into `content_items`.
- No agent permission for domain tables except FK validation by Postgres.
- Context payload includes `execution_id`, `campaign_id`, `user_id`, `device_serial`, `collection`, `scenario_name`, `hash_scope`.
- Phone/APK sends XML to `agent-boot`; successful extract does not upload raw XML to `device_farm`.
- Agent writer computes content hash identically to the legacy `device_farm.services.content_store` contract.
- Direct extra-data parsing is owned by `agent-boot/relay/fb_extract`; `device_farm` only sends control/context and receives summaries.
- Agent writer uses bounded DB pool and `ON CONFLICT DO NOTHING`.
- Flow remains feature-flagged, but Facebook server-side parser fallback is removed; misconfigured FB extract fails clearly.

## Dependencies

- PostgreSQL reachable from agent network, preferably via private network/VPN.
- Agent package gains DB driver dependency.
- Parser/hash code is owned by `agent-boot` for the direct path; legacy server-side FB parser has been removed.
- Existing `content_items` unique indexes remain active.

## Risks

- Direct DB write moves failure mode from API overload to DB connection pressure.
- Copying parser/hash code will drift.
- Existing `content_collections` counters may not update.
- Context mistakes can create orphaned or wrong-tenant content.
- Agent XML parsing can block relay work unless it runs in a bounded executor.
- DB outages can lose parsed rows unless the APK retries until persisted ack or the agent has a local outbox.
- Relative timestamps can be wrong if parsed against agent clock instead of XML `captured_at`.

## Review Gates

- [x] Direct path is feature-flagged and falls back to current `device_farm` extraction.
- [x] Agent writer uses bounded pool, persisted ack semantics, idempotent hashes, `ON CONFLICT DO NOTHING`, and DB retry.
- [x] Phone/APK can send XML directly to `agent-boot`; successful path returns summary instead of uploading raw XML to `device_farm`.
- [ ] p95 XML parse time and p95 DB insert batch time are measured in staging.
- [ ] Golden parity test proves old server path and new agent path produce equivalent row payloads on captured XML fixtures.
- [ ] Agent DB role permission test proves insert-only behavior against staging/production-like Postgres.
- [ ] Cross-tenant dedupe test runs against real unique indexes.

## Acceptance Criteria

- Agent can parse phone-provided XML and save posts/comments without uploading raw XML to `device_farm`.
- Agent DB role cannot read/write domain tables.
- Duplicate extraction retries do not create duplicate rows.
- Dashboard can still filter by user/campaign/execution/device.
- Feature flag can instantly fall back to the current `device_farm` path.
- No parsed rows are silently dropped on DB failure.
- Comments link to the correct scoped parent hash.

## Cook Command

```bash
/ck:cook /Users/hoanglcpila.vn/deviceFarmer/docs/plans/agent-boot-direct-content-writer/plan.md
```
