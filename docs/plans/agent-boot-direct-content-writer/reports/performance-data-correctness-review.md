# Review: Performance, Data Correctness, and Operational Risks

## Verdict

The plan is directionally correct after removing login. Moving XML parsing and `content_items` inserts to `agent-boot` removes the server XML hot path. However, production readiness depends on stricter performance controls and data correctness gates.

## P0 Must-Fix Before Implementation

1. XML parse must not block the relay/event loop.
   - Run parsing and heavy normalization in a bounded executor.
   - Add global concurrency limit and per-serial lock.
   - Reject or defer XML when queue is full.

2. Exact data parity with `save_content_item()` is mandatory.
   - Shared helper must cover hash, scoped parent hash, field mapping, safe ints, text cleanup, media URLs, and content date parsing.
   - Golden tests must compare direct agent rows against server `save_content_item()` rows.

3. Date parsing must use `captured_at` as relative base.
   - Current server helper uses `now`.
   - If agent clock differs, strings like "2 hours ago" will persist wrong `content_date`.

4. Comment parent mapping must be explicit.
   - Comments require parent content hash under the same `hash_scope`.
   - Agent must save parent posts before comments or keep a scoped parent-hash cache.
   - Comments without resolved parent should be marked with a diagnostic, not silently linked wrong.

5. DB write must be batched and backpressured.
   - Use one small DB pool per agent.
   - Use batch insert with `ON CONFLICT DO NOTHING`.
   - Apply retry with jitter for transient DB errors.
   - Add a local outbox or explicit re-send contract for DB outage.

## Performance Review

Expected win:
- `device_farm` no longer receives large XML payloads on success.
- `device_farm` no longer parses XML for every extraction step.
- Relay/cloud CPU and bandwidth drop.

New bottlenecks:
- `agent-boot` CPU can spike if multiple phones send XML at once.
- Agent event loop can stall if XML parsing runs inline.
- Postgres can become the new bottleneck if many agents insert directly.
- Local network between phone and agent can still carry large XML, so XML size and cadence must be bounded.

Required controls:
- `AGENT_BOOT_XML_MAX_BYTES`
- `AGENT_BOOT_XML_QUEUE_SIZE`
- `AGENT_BOOT_XML_PARSE_WORKERS`
- `AGENT_BOOT_CONTENT_DB_POOL_SIZE=1`
- `AGENT_BOOT_CONTENT_BATCH_SIZE`
- `AGENT_BOOT_CONTENT_BATCH_MAX_MS`
- `AGENT_BOOT_CONTENT_RETRY_MAX`

Required metrics:
- XML bytes received per serial.
- XML queue depth and dropped/rejected count.
- parse duration p50/p95/p99.
- DB insert batch size and duration p50/p95/p99.
- DB retry/error count by error class.
- agent process CPU/RSS.
- event-loop lag.

## Data Correctness Review

Fields that must match server path:
- `content_hash`
- `parent_id`
- `item_level`
- `body`
- `author`
- `url`
- `likes_count`
- `comments_count`
- `shares_count`
- `views_count`
- `media_urls`
- `content_date`
- `raw_data`
- `user_id`
- `campaign_id`
- `execution_id`
- `device_serial`
- `scenario_name`

High-risk correctness areas:
- Hash drift if agent and server use different normalization.
- Wrong `hash_scope` causing cross-run dedupe collapse or duplicate explosion.
- Wrong `user_id` causing cross-tenant visibility bugs.
- Relative date parsing based on agent clock.
- Comments saved before parent hash is known.
- `ON CONFLICT DO NOTHING` hiding conflict counts.
- `content_collections.item_count` drift because direct insert bypasses `increment_collection_count()`.

Required tests:
- Same XML through old server path and new agent path produces equivalent row payloads.
- Same item with same `hash_scope` dedupes.
- Same item with different `hash_scope` persists separately.
- `user_id` A and `user_id` B do not dedupe against each other.
- Comments link to scoped parent hash.
- Relative timestamp parses from `captured_at`.
- Duplicate retries do not create duplicates.
- Agent DB role cannot read or mutate non-content tables.

## Reliability Review

The current plan assumes DB is reachable from agent. That is acceptable only with a clear failure policy.

Pick one:

1. Local durable outbox, recommended.
   - Agent writes parsed rows to SQLite first.
   - Background flusher inserts to Postgres.
   - Summary reports pending/saved/error counts.

2. No outbox, simpler but lossy.
   - APK/phone must retry XML until agent returns persisted ack.
   - Agent must reject success before DB insert completes.

Do not silently drop parsed rows on DB failure.

## Security Review

Good:
- Agent does not need credentials or account table access.
- Agent DB role can remain insert-only.

Needs tightening:
- `context_id` must be unguessable and short-lived.
- XML message should include `serial`, `context_id`, `strategy`, `captured_at`, and payload hash.
- Agent must reject stale context and serial mismatch.
- Logs must never include full XML or raw post body by default.
- XML parser must enforce max bytes and avoid unsafe entity expansion.

## Rollout Gates

Do not enable beyond canary until:
- p95 parse time is under target.
- p95 DB insert time is under target.
- data parity test passes on captured FB fixtures.
- duplicate retry test passes.
- direct DB role permission test passes.
- edge failure path has been exercised in staging.
