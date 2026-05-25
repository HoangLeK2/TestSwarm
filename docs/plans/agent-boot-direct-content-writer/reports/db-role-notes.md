# Agent Boot DB Role Notes

## Goal

`agent-boot` should only persist parsed rows into `content_items`. It must not read or mutate campaign, organization, account, device, or user domain tables.

## Suggested Role

```sql
CREATE ROLE agent_boot_writer LOGIN PASSWORD '<rotate-me>';
GRANT USAGE ON SCHEMA public TO agent_boot_writer;
GRANT INSERT ON content_items TO agent_boot_writer;
```

Do not grant:

```sql
GRANT SELECT, UPDATE, DELETE ON content_items TO agent_boot_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON campaigns, organizations, accounts, devices, users TO agent_boot_writer;
```

## Required Verification

Run these checks in staging with the actual role:

```sql
SET ROLE agent_boot_writer;

-- Must succeed for a valid row and must be idempotent with ON CONFLICT DO NOTHING.
INSERT INTO content_items (...) VALUES (...) ON CONFLICT DO NOTHING;

-- Must fail.
SELECT * FROM users LIMIT 1;
UPDATE content_items SET title = title WHERE false;
DELETE FROM content_items WHERE false;
INSERT INTO campaigns DEFAULT VALUES;
```

Also test an invalid `campaign_id`, `user_id`, or `device_serial` if foreign keys are enabled. Classify FK errors as context/config errors, not parser errors.

## Current Implementation Status

The local implementation uses persisted ack semantics: `agent-boot` only returns success to the APK/device_farm after the DB insert attempt finishes without error. Duplicate rows are accepted via `ON CONFLICT DO NOTHING`; transient DB errors retry with jitter before returning failure.

The XML ingest endpoint also requires `AGENT_BOOT_EXTRA_TOKEN` by default. Only use `AGENT_BOOT_EXTRA_ALLOW_UNAUTH=1` for isolated local debugging.
