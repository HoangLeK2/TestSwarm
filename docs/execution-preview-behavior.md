# Preview execution vs campaign run

Preview runs use the same Temporal/fallback runtime as campaign dispatch (DF-T-04-010) but are tagged `execution.kind=preview` with `campaign_id=null`. They do not appear in campaign run history or trigger campaign status aggregation.

## When to use preview

- Validate scenario steps on one real device before wide dispatch.
- Inspect step captures and extracted artifacts without affecting a running campaign.
- Debug account binding or variable resolution in isolation.

Preview is **not** a sandbox: it runs on real devices, writes real artifacts to the content store, and may perform real social actions if the scenario includes side-effect steps.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/scenarios/{id}/preview` | Start preview on one device |
| `GET` | `/api/preview?org=&user=&since=` | List preview executions |

### Start preview body

```json
{
  "device_id": "uuid",
  "vars": {},
  "account_id": "uuid (required for login steps)",
  "force": false
}
```

### Guards

- **Side effects** (`fb.post`, `ig.comment`, etc.): rejected with `PREVIEW_HAS_SIDE_EFFECT_REQUIRES_FORCE` unless `force=true`. Response includes warning: *Step social-effect detected; consider test account*.
- **Login / account steps**: rejected with `ACCOUNT_REQUIRED_FOR_PREVIEW` when `account_id` is missing (no primary-account fallback).
- **Device busy**: `409 DEVICE_BUSY` when the device is already claimed.

## Artifacts & retention

- Capture is **on** by default (DF-T-04-014).
- Extracted content is stored in collection `preview:{org_id}` (not the default campaign collection).
- A background job purges preview artifacts after **7 days** (configurable via `DEVICE_FARM_PREVIEW_RETENTION_DAYS`). Execution rows are kept for audit; step `artifacts_json` is cleared and `meta.artifacts_purged=true`.

## Device claim

Preview claims the device with owner type `scenario` and releases it when the execution reaches a terminal state (DF-E-02).
