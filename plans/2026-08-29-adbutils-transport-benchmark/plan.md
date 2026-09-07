---
title: "ADBUtils Transport Benchmark Plan"
description: "Introduce adbutils behind the existing ADB management layer, benchmark it against binary adb, and migrate only if it proves faster and equally reliable."
status: pending
priority: P1
effort: 18h
issue: null
branch: fix/relay-registration-scaling
tags: [backend, infra, performance, experimental]
created: 2026-08-29
---

# ADBUtils Transport Benchmark Plan

## Goal

Add `adbutils` as a selectable ADB transport inside `agent-boot`, write unit
tests for the new transport contract, benchmark it against the current binary
`adb` implementation, then remove pure binary-ADB execution only if parity and
performance gates pass.

Non-goal: remove ADB as a dependency. ADB remains the host/device transport.

## Current Baseline

- Current production ADB entrypoint is `agent-boot/relay/adb.py`.
- Current implementation intentionally uses `adb` binary subprocesses.
- Existing control protections must survive:
  - remote ADB server flags from env: `ADB_SERVER_SOCKET`, `ADB_HOST`, `ADB_PORT`;
  - per-serial and global admission in `agent-boot/relay/adb_admission.py`;
  - command stats and timeout accounting;
  - forward cache/reconcile;
  - recovery coalescing and circuit breaker.
- `uiautomator2` already depends on `adbutils` transitively, but direct ADB
  helpers do not use it as the primary execution path.

## Architecture

Create a transport boundary under `agent-boot/relay/adb_transport.py`:

```python
class AdbTransport(Protocol):
    def run(self, *args: str, serial: str | None = None, timeout: int = 30) -> tuple[str, int]: ...
    def shell(self, serial: str, cmd: str, timeout: int = 30) -> tuple[str, int]: ...
    def devices(self, timeout: int = 5) -> list[str]: ...
    def forward(self, serial: str, local: str, remote: str, timeout: int = 10) -> tuple[str, int]: ...
    def forward_list(self, timeout: int = 5) -> tuple[str, int]: ...
    def push(self, serial: str, src: str, dst: str, timeout: int = 60) -> tuple[str, int]: ...
    def install(self, serial: str, apk: str, timeout: int = 180) -> tuple[str, int]: ...
```

Implement:

- `BinaryAdbTransport`: wraps current `_adb_command` + subprocess behavior.
- `AdbutilsTransport`: uses `adbutils.AdbClient` / `adb.device(serial=...)`.
- `HybridAdbTransport`: optional transition mode:
  - read-only shell/probe/forward-list via adbutils;
  - install/push/recovery via binary until benchmark proves parity.

Runtime selection:

```text
AGENT_BOOT_ADB_TRANSPORT=binary|adbutils|hybrid
default=binary
```

## Phase 1: Contract Extraction And Implementation

Estimated: 5h

1. Run GitNexus impact analysis before editing symbols in:
   - `agent-boot/relay/adb.py`
   - `agent-boot/relay/device_watcher.py`
   - `agent-boot/relay/adb_admission.py`
2. Extract command construction and execution behind `AdbTransport`.
3. Keep public functions in `adb.py` stable:
   - `_run`
   - `_run_raw`
   - `_adb_shell`
   - `_list_serials`
   - `_adb_connect`
   - forward helpers
   - bootstrap helpers
4. Add `AdbutilsTransport` without changing default behavior.
5. Ensure all transport calls still pass through `adb_admission`.

Success criteria:

- Default `AGENT_BOOT_ADB_TRANSPORT=binary` produces minimal behavior diff.
- `adbutils` path can be enabled without importing it at module import time.
- Remote ADB server config still works.

## Phase 2: Unit Tests After Code

Estimated: 4h

Add focused unit tests after the implementation is in place:

- `agent-boot/relay/tests/test_adb_transport_binary.py`
- `agent-boot/relay/tests/test_adb_transport_adbutils.py`
- extend `agent-boot/relay/tests/test_adb_admission.py`
- extend `agent-boot/relay/tests/test_benchmark_adb_capacity.py`

Test cases:

- binary transport builds exact `adb -H <host> -P <port> -s <serial>` command.
- adbutils transport receives the same host/port/serial selection.
- shell exit code parsing is compatible with current `_adb_shell`.
- timeouts become `(message, -1)` and do not raise through public helpers.
- forward create/list/remove behavior is compatible with cache parsing.
- install/push failures preserve output/error text.
- `adb_admission` still serializes one command per serial for both transports.
- default remains binary when env is unset.

Commands:

```bash
cd agent-boot
uv run pytest -q relay/tests/test_adb_transport_binary.py relay/tests/test_adb_transport_adbutils.py relay/tests/test_adb_admission.py relay/tests/test_benchmark_adb_capacity.py
```

## Phase 3: Benchmark Harness

Estimated: 3h

Create or extend `agent-boot/scripts/benchmark_adb_capacity.py` to compare:

- `binary`
- `adbutils`
- `hybrid`

Benchmark groups:

- `devices`: list/track snapshot.
- `read_shell`: `getprop`, `wm size`, package exists.
- `batch_probe`: current capability probe script.
- `forward`: `forward --list`, create/remove forward.
- `u2_health`: `/ping` and JSON-RPC deviceInfo through existing forward.
- `push_small`: small config file.
- `install_small`: only when test APK/device available.
- `recovery_shell`: force-stop/start u2-related commands in dry-safe mode only.

Metrics:

- p50, p95, p99 latency.
- timeout count.
- non-zero rc count.
- queue wait p50/p95 from admission stats.
- CPU time / process spawn count where available.
- per-device fairness: no serial starves behind another.

Run shape:

```bash
cd agent-boot
AGENT_BOOT_ADB_TRANSPORT=binary   uv run python scripts/benchmark_adb_capacity.py --serials auto --rounds 100
AGENT_BOOT_ADB_TRANSPORT=adbutils uv run python scripts/benchmark_adb_capacity.py --serials auto --rounds 100
AGENT_BOOT_ADB_TRANSPORT=hybrid   uv run python scripts/benchmark_adb_capacity.py --serials auto --rounds 100
```

## Phase 4: Verification Gate

Estimated: 3h

Only proceed beyond hybrid if all gates pass:

- Functional parity:
  - all focused unit tests pass;
  - bootstrap smoke still passes on at least one real device;
  - `track-devices`/device watcher still observes connect, disconnect, offline.
- Reliability:
  - adbutils timeout/error rate is not higher than binary.
  - no stuck Python thread/socket after cancelled timeout.
  - ADB server restart does not leave transport permanently wedged.
- Performance:
  - p95 improves by at least 15% on read/probe/forward workloads, or CPU/process
    spawn reduction is material under 20+ devices.
  - no regression above 10% on install/push/recovery workloads.
- Operations:
  - Docker remote ADB path works with host/port env.
  - Windows bundle smoke still imports and runs.

Verification commands:

```bash
cd agent-boot
uv run python -m py_compile relay/adb.py relay/adb_transport.py relay/device_watcher.py relay/agent.py
uv run pytest -q relay/tests/test_adb_transport_binary.py relay/tests/test_adb_transport_adbutils.py relay/tests/test_adb_admission.py relay/tests/test_benchmark_adb_capacity.py
cd ..
git diff --check
```

Runtime smoke:

```bash
cd agent-boot
AGENT_BOOT_ADB_TRANSPORT=hybrid uv run python main.py --once-status
```

If `--once-status` does not exist, add a non-invasive status/probe mode or use
the existing relay startup smoke in tests.

## Phase 5: Full Migration Or Stop At Hybrid

Estimated: 3h

Decision:

- If adbutils wins all gates: make `AGENT_BOOT_ADB_TRANSPORT=adbutils` default.
- If adbutils only wins read/probe paths: keep `hybrid` default.
- If adbutils regresses reliability: keep `binary` default and leave adbutils
  behind opt-in flag for further testing.

Only delete pure binary ADB execution after:

- full parity tests exist;
- benchmark reports are checked into `plans/2026-08-29-adbutils-transport-benchmark/reports/`;
- one real-device smoke proves bootstrap, u2 health, shell, forward, and command
  timeout behavior;
- `detect_changes()` is run before commit if GitNexus tools are available.

Deletion scope when approved:

- remove direct subprocess execution from normal `adb.py` command path;
- keep a small binary fallback only for emergency host diagnostics if needed;
- update docs and Windows/Docker release notes.

## Risks

- `adbutils` can reduce fork/exec overhead but still hits the same ADB server.
- Long-running shell/logcat behavior may differ from binary adb.
- Timeout cancellation for socket-based clients can be worse than killing a
  subprocess.
- Remote Docker ADB env must be explicitly tested; ambient env behavior is not
  enough.
- Removing binary path too early risks production recovery regressions.

## Implementation Rule

Do not let callers choose transports directly. All callers go through the same
`adb.py` public helpers and the same admission/retry/stats layer.
