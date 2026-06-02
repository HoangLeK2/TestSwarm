# Phase 4 - XML Dump Coalescing And Cache

Status: In Progress
Priority: P0
Effort: 4h

## Objective

Reduce scenario latency by avoiding redundant u2 XML dumps.

## Scope

- Treat hierarchy XML as a query operation, not an interactive command.
- Add one active dump per serial.
- Coalesce duplicate refresh requests while a dump is in flight.
- Add short TTL cache with metadata:
  - `cached`
  - `age_ms`
  - `xml_hash`
  - `xml_len`
  - `changed`
- Keep full XML available when required by existing callers.

## Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/device_farm/runtime/core/device_client.py`
- `/Users/hoangle/farm/device-farm/device_farm/api/routes/device_control/device_ui.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests`

## Design

```text
dump_xml request
  -> if fresh cache exists: return cache immediately
  -> if dump in flight: await same task or return superseded/cached result
  -> else start one u2 dump
  -> update cache and hash
```

## Safety Rules

- Mutating actions invalidate or mark cache stale.
- Callers can force full refresh when correctness requires it.
- Cache TTL starts conservatively: 300-800ms.
- Do not hide u2 failures; return cache only with explicit `cached=true`.

## Tests

- Five concurrent dump requests produce one u2 dump.
- Fresh cache avoids a second u2 dump.
- Mutating action invalidates cache.
- Full XML response remains compatible with existing API.

## Success Criteria

- Refresh storms do not create repeated u2 dumps.
- Scenario pattern `dump -> action -> dump` becomes cheaper where safe.
- Logs distinguish cached, coalesced, and real u2 dump latency.

## Implementation Notes

- Added `DeviceClient.hierarchy_xml()` in-flight coalescing so concurrent `force_refresh=True` callers wait for the active dump and reuse its cache.
- Kept `hierarchy_xml()` return type unchanged (`Optional[str]`) to avoid breaking API/scenario callers.
- Added regression coverage for five concurrent refresh calls producing one u2 `page_source()` call.
- Remaining work: expose optional metadata (`cached`, `age_ms`, `xml_hash`, `xml_len`, `changed`) to API callers that can consume it without changing legacy XML responses.
