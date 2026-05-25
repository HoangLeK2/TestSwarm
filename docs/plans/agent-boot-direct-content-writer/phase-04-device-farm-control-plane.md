# Phase 04: device_farm Control Plane

## Overview

Make `device_farm` provide extraction context and consume summaries while removing server-side Facebook parsing from the hot path.

Priority: P1  
Status: Partial  
Effort: 4h

## Context Links

- `device_farm/tasks/scenario/steps/extraction.py`
- `device_farm/runtime/transports/adb_relay_server.py`
- `device_farm/runtime/transports/grpc_relay_server.py`
- `device_farm/runtime/core/device_client.py`
- `device_farm/api/routes/content.py`
- [Performance/data review](./reports/performance-data-correctness-review.md)

## Requirements

- Feature flag controls edge extraction.
- Context payload includes all IDs required for `content_items`.
- Phone/APK sends XML directly to `agent-boot`; `device_farm` is not in the XML data path on success.
- Server-side extraction remains available.
- Server receives progress/error summaries for dashboard and audit.
- Server has timeout/error behavior when agent context is registered but XML summary never arrives.
- Existing scenario templates require minimal changes.

## Architecture

Feature flags:

```yaml
edge_extract:
  enabled: false
  fb_direct_content_writer: false
  fail_without_agent_summary: true
```

Runtime decision:

```text
if edge_extract enabled and relay agent supports schema:
    send/refresh extract context on agent-boot
    phone/APK sends XML to agent-boot
    wait for summary or poll DB count
    update scenario result counters
else:
    run current handle_extract path
```

## Related Code Files

- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/config.yaml`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/core/config.py`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/runtime/transports/adb_relay_server.py`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tasks/scenario/steps/extraction.py`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/front-end/messages/en.json`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/front-end/messages/vi.json`

## Implementation Steps

1. [x] Add env/step flags.
2. [x] Add APK command `extra_data_xml` via existing device agent WebSocket.
3. [ ] Agent heartbeat advertises capabilities:
   - `fb_xml_extra_schema=1`
   - `content_direct_writer=true`
4. [x] Update `handle_extract()`:
   - derive context payload
   - register agent context when enabled
   - map summary to current `result` fields
   - fail clearly on unsupported/no relay/feature disabled
5. [ ] Add extract summary log event:
   - serial
   - execution_id
   - collection
   - parsed_count
   - inserted_attempted
   - xml_bytes
   - parse_ms
   - db_ms
   - queue_depth
   - elapsed_ms
   - route=`agent_boot_xml_extra_content`
6. [ ] Add UI/admin indicator later if needed.

## Success Criteria

- Existing scenarios work unchanged with flag off.
- With flag on, `device_farm` does not receive raw XML on successful extract.
- Older agent-boot versions fail clearly instead of silently using server-side Facebook parsing.
- Execution dashboard can still show content item counts by existing DB queries.
- Scenario step result cannot report success unless agent summary confirms persisted rows or zero extracted rows with valid diagnostic.

## Risks

- Scenario context currently expects `ctx["posts"]` / `ctx["comments"]`.
- Some downstream steps may need extracted items in memory after save.
- Agent-only save means server may not know exact inserted IDs.
- Summary timeout can leave scenario state ambiguous.

## Mitigation

- Agent returns compact items or item hashes only when downstream steps need them.
- Start with templates where extraction is terminal/save-focused.
- Keep server extraction for workflows requiring in-memory post/comment state.
- On summary timeout, mark step as failed/retryable, not successful.
