# Uiautomator2 Production Runbook

## Capability Matrix

| Capability | Device Farm status | Production default |
| --- | --- | --- |
| Persistent u2 sessions | used | `U2SessionPool` keeps one warm session per serial with eviction/recovery. |
| Batched actions | used | `U2Executor.run_batch` is the relay hot path for touch, wait, app ops, screenshot, and hierarchy. |
| Direct HTTP hierarchy | used | `/dump/hierarchy` is tried before Python u2 for low-latency dumps. |
| Direct HTTP touch/RPC | used | Selector/tap fast paths avoid the full Python session lock when supported. |
| XML cache/singleflight | used | Identical dump profiles share in-flight work and short TTL cache entries. |
| Dump profiles | used | `compressed`, `root_in_active`, `max_depth`, and `pretty` are forwarded through the stack. |
| XPath/selector spec | used | Scenario selector spec and XPath fallback are available; prefer identity-scoped specs for social flows. |
| App lifecycle | used | `app_start`, `app_stop`, `app_clear`, `app_wait`, and session-style waits are exposed. |
| IME/text input | used | Fast input and fallback text paths are available. |
| Screenshot | used | Fast base64 JPEG screenshot path avoids needless PNG re-encode. |
| Watcher | intentionally limited | XML snapshot watchers remain default; native global u2 watchers require live-device benchmark first. |
| Recovery | used | Dead session markers, pool eviction, `restart_u2`, and `restart_atx` escalation are supported. |
| Vendor APK source | intentionally limited | Server source changes do not affect runtime until the bundled APKs are rebuilt and replaced. |

## Dump Profile Policy

Use conservative defaults for social extraction:

- Extraction XML defaults to full-enough hierarchy unless the profile explicitly sets `hierarchy_extract_compressed`.
- Verification/control XML may use compressed hierarchy because it only proves UI state.
- `hierarchy_root_in_active` is off by default. Enable it only after node-loss checks on the target app and device family.
- `hierarchy_max_depth`, `hierarchy_extract_max_depth`, and `hierarchy_verify_max_depth` cap traversal cost; validate that target nodes remain present before rollout.

Supported profile keys:

- Global: `hierarchy_compressed`, `hierarchy_root_in_active`, `hierarchy_max_depth`, `hierarchy_pretty`, `hierarchy_dump_timeout_s`.
- Extract: `hierarchy_extract_compressed`, `hierarchy_extract_root_in_active`, `hierarchy_extract_max_depth`.
- Verify: `hierarchy_verify_compressed`, `hierarchy_verify_root_in_active`, `hierarchy_verify_max_depth`.

## Dependency And APK Contract

`agent-boot` pins `uiautomator2==3.5.0`. Upgrade it only with:

- focused unit tests for executor, session pool, relay control-plane, and `U2JsonRpcClient`;
- synthetic scheduler benchmark;
- one to three physical-device smoke runs for hierarchy/tap/wait/app ops;
- confirmation that any changed `android-uiautomator-server-jar` APK is rebuilt and bundled into the runtime image.

## Diagnostics

Check these in order when hierarchy or touch degrades:

- `u2exec` stats: dump p95 symptoms show up as `dump_http_direct`, `dump_pool_fallbacks`, cache hits, breaker opens/drops, and deadline drops.
- `u2pool` stats: session reuse, evictions, cooldowns, hard alive failures, and direct HTTP health marks.
- Device HTTP probes: `/ping`, JSON-RPC `deviceInfo`, and `/dump/hierarchy`.
- Recovery path: reconnect first for transient timeout, then `restart_u2`, then `restart_atx` for hard dead-backend errors.

Do not claim production capacity from synthetic benchmarks alone; use physical-device soak before changing fleet limits.
