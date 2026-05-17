# Phase 01: Contract and DB Safety

## Overview

Define the context payload, XML ingestion contract, persistence contract, and DB permissions before any runtime changes.

Priority: P1  
Status: Partial  
Effort: 4h

## Context Links

- [Codebase analysis](./reports/codebase-analysis.md)
- [Performance/data review](./reports/performance-data-correctness-review.md)
- `device_farm/db/models/content.py`
- `device_farm/db/migrations/023_content_items_tenant_dedup_index.py`
- `device_farm/services/content_store.py`

## Requirements

- Agent receives all context IDs from `device_farm`; agent does not discover tenant/domain context by querying DB.
- Phone/APK sends hierarchy XML to `agent-boot` with the current context/session identifier.
- Agent DB role can insert into `content_items` only.
- Agent does not use `RETURNING *`.
- Agent generates UUID and timestamps itself.
- Agent write path handles FK violation as context/config error, not parser error.

## Proposed Context Payload

```json
{
  "schema_version": 1,
  "context_id": "uuid",
  "execution_id": "uuid-or-null",
  "campaign_id": "uuid-or-null",
  "user_id": "uuid-or-null",
  "device_serial": "serial",
  "collection": "fb_group_1h",
  "platform": "facebook",
  "scenario_name": "fb_group_extract",
  "hash_scope": "execution-id-or-run-scope",
  "dedupe_field": "post_key"
}
```

## DB Permission Model

Create a dedicated DB user, for example `agent_boot_writer`.

Minimum grants:

```sql
GRANT INSERT ON content_items TO agent_boot_writer;
```

Avoid:

```sql
GRANT SELECT, UPDATE, DELETE ON content_items TO agent_boot_writer;
GRANT ANYTHING ON campaigns, organizations, accounts, devices, users TO agent_boot_writer;
```

If operationally useful, allow `SELECT 1` only via a health-check function, not broad table SELECT.

## XML Ingestion Contract

Phone/APK sends:

```json
{
  "schema_version": 1,
  "context_id": "uuid",
  "serial": "device-serial",
  "strategy": "fb_posts",
  "xml": "<hierarchy ...>",
  "xml_sha256": "hex",
  "captured_at_ms": 1778716800000
}
```

Agent validates:

- `context_id` exists in memory or can be resolved from `device_farm`.
- `serial` matches the attached/registered device.
- `xml` size is under configured max.
- `xml_sha256` matches the XML body when provided.
- `captured_at_ms` is present and within accepted skew. Agent code also accepts `captured_at` for compatibility.
- `strategy` is supported.

## Insert Contract

Agent insert must set:

- `id`
- `collection`
- `platform`
- `content_type`
- `title`
- `body`
- `author`
- `author_id`
- `url`
- `likes_count`
- `comments_count`
- `shares_count`
- `views_count`
- `media_urls`
- `raw_data`
- `tags`
- `content_hash`
- `parent_id`
- `item_level`
- `device_serial`
- `campaign_id`
- `execution_id`
- `scenario_name`
- `user_id`
- `extracted_at`
- `created_at`

Use:

```sql
INSERT INTO content_items (...)
VALUES (...)
ON CONFLICT DO NOTHING;
```

Use `ON CONFLICT DO NOTHING` without a conflict target unless tests prove the
target works with both the tenant index and the null-user partial index.

## Reliability Contract

Choose one before implementation:

- Durable outbox: agent writes parsed rows to local SQLite, then flushes to Postgres.
- Persisted ack: phone/APK retries XML until agent confirms DB insert completed.

The implementation must not parse XML, fail DB insert, and return success.

## Related Code Files

- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/db/migrations/*`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/.env.example`
- Create: `/Users/hoanglcpila.vn/deviceFarmer/docs/plans/agent-boot-direct-content-writer/reports/db-role-notes.md`

## Implementation Steps

1. [ ] Add a migration or deployment SQL note for `agent_boot_writer`.
2. [x] Document required agent DB env vars: `AGENT_BOOT_CONTENT_DATABASE_URL`, pool size, command timeout, retry settings.
3. [ ] Confirm FK behavior with insert-only role in staging.
4. [ ] Decide `content_collections` behavior:
   - preferred short term: dashboard counts from `content_items`
   - later: background reconciliation or DB trigger
5. [ ] Add a compatibility matrix for schema versions.
6. [ ] Verify whether insert-only role can use `ON CONFLICT DO NOTHING` in the target Postgres version.
7. [x] Define outbox-vs-persisted-ack behavior and document it in agent config.

## Success Criteria

- Agent role can insert valid content row.
- Agent role cannot select or modify domain tables.
- Duplicate insert returns success-equivalent behavior through `ON CONFLICT DO NOTHING`.
- FK failure is observable and classified.
- DB failure cannot produce a false success ack.

## Risks

- Some dashboards rely on `content_collections.item_count`.
- Existing migrations may assume service-only writes.
- DB role rollout differs between local Docker and production.
