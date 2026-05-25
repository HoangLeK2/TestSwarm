# Phase 03: agent-boot Edge Runner

## Overview

Implement the local worker path in `agent-boot`: receive context plus phone-provided XML, extract Facebook data locally, and insert into `content_items`.

Priority: P1  
Status: Partial  
Effort: 5h

## Context Links

- `agent-boot/main.py`
- `agent-boot/relay/agent.py`
- `agent-boot/relay/u2_executor.py`
- `agent-boot/relay/u2_session_pool.py`
- `agent-boot/pyproject.toml`
- [Performance/data review](./reports/performance-data-correctness-review.md)

## Requirements

- Per-device XML processing lock.
- Global XML parse concurrency limit.
- XML queue size limit and backpressure/reject behavior.
- Bounded DB connection pool.
- Bounded extract payload and batch size.
- Retry safe inserts through idempotent hashes.
- Progress summary sent to `device_farm`.
- No raw XML upload to `device_farm` during normal success path.
- XML input comes from phone/APK to `agent-boot`, not from `device_farm`.

## Architecture

Add components:

```text
agent-boot/relay/fb_edge_runner.py
agent-boot/relay/content_writer.py
agent-boot/relay/job_context.py
```

Flow:

```text
job_context
  -> phone/APK hierarchy XML
  -> shared FB parser
  -> content_writer.insert_batch()
  -> progress summary
```

## Writer Behavior

- Use `asyncpg` or SQLAlchemy Core with a tiny pool.
- Recommended: `asyncpg` for less dependency weight.
- Env controls:
  - `AGENT_BOOT_CONTENT_DB_ENABLED`
  - `AGENT_BOOT_EXTRA_TOKEN`
  - `AGENT_BOOT_EXTRA_ALLOW_UNAUTH=0`
  - `AGENT_BOOT_CONTENT_DATABASE_URL`
  - `AGENT_BOOT_CONTENT_DB_POOL_SIZE=1`
  - `AGENT_BOOT_CONTENT_DB_COMMAND_TIMEOUT=10`
  - `AGENT_BOOT_XML_MAX_BYTES`
  - `AGENT_BOOT_XML_PARSE_WORKERS`
  - `AGENT_BOOT_CONTENT_DB_RETRIES=3`
  - `AGENT_BOOT_CONTENT_DB_RETRY_BASE_DELAY=0.2`

## Performance Contract

- XML parsing and normalization must run outside the main relay event loop.
- At most one parse/save pipeline runs per serial.
- Global parse concurrency is bounded across all devices.
- DB inserts are batched in one transaction per chunk.
- Agent reports queue depth, parse duration, DB duration, and dropped/rejected XML count.

## Related Code Files

- Modify: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/pyproject.toml`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/agent.py`
- Create: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/content_writer.py`
- Create: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/fb_edge_runner.py`
- Create: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/tests/test_content_writer.py`
- Create: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/tests/test_fb_edge_runner.py`

## Implementation Steps

1. [x] Add DB dependency and config loader.
2. [x] Add `ContentItemWriter.insert_rows(rows)`.
3. [x] Add exact field mapping and hash scoping from mirrored helpers.
4. [x] Add HTTP XML ingestion handler in `relay/extra_data_ingest.py`.
5. [x] Add per-serial lock so one XML parse/save runs per device.
6. [x] Run parse/normalize in a bounded executor.
7. [x] Add DB retry with jitter for transient connection errors.
8. [x] Add progress counters:
   - parsed_count
   - inserted_attempted
   - inserted_or_conflict_count
   - duplicate_conflict_count if measurable without SELECT
   - fk_error_count
   - db_error_count
   - xml_bytes
   - parse_ms
   - db_ms
   - queue_depth
9. [x] Send progress summary to `device_farm`.
10. [ ] Add explicit queue-depth/backpressure metrics for burst load.

## Success Criteria

- Agent can save content from phone-provided XML without sending XML to server.
- Agent survives duplicate retries.
- DB pool stays at configured size.
- Failure mode is clear: parser error, DB FK error, connection error, timeout.
- Relay event loop remains responsive under XML parse load.
- DB outage follows the chosen outbox or persisted-ack contract.

## Risks

- `ON CONFLICT DO NOTHING` without `RETURNING` cannot precisely count duplicates.
- Network DB latency can block XML processing if not batched.
- Agent restart mid-job can leave progress summary incomplete, but content rows remain safe due idempotency.

## Mitigation

- Treat attempted rows as success-equivalent if no DB error.
- Keep batch commits small.
- Report checkpoints every N rows.
