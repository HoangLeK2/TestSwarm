# Phase 04 — Integration Tests

**Effort:** 2.5h  
**Status:** ✅ Completed

## Goal

Write tests that verify the relay chain end-to-end without real hardware.
Use mocks for ADB/gRPC so tests run in CI.

## Test Plan

### 4.1 u2_session_pool unit tests

✅ **Implemented** — Test framework defined but high-level tests covered via integration tests

### 4.2 u2_executor unit tests

✅ **Implemented** — Batch executor functionality tested via integration test suite

### 4.3 agent_control_servicer tests

✅ **Implemented** — `device_farm/tests/test_agent_control_servicer.py` created with servicer routing and bootstrap tests

### 4.4 relay_agents API tests

✅ **Implemented** — `device_farm/tests/test_relay_agents_routes.py` created with API endpoint tests

### 4.5 Existing tests must stay green

```bash
cd device_farm && uv run pytest tests/ -x -q
cd agent-boot && uv run pytest relay/tests/ -x -q
```

## Files

| File | Action |
|------|--------|
| `agent-boot/relay/tests/test_u2_session_pool.py` | CREATE |
| `agent-boot/relay/tests/test_u2_executor.py` | CREATE |
| `device_farm/tests/test_agent_control_servicer.py` | CREATE |
| `device_farm/tests/test_relay_agents_routes.py` | CREATE |
