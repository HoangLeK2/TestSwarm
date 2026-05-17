# Edge Extra Data Runbook

## Enable Agent

Set these on the `agent-boot` host:

```bash
AGENT_BOOT_EXTRA_ENABLED=1
AGENT_BOOT_EXTRA_TOKEN=<shared-secret>
AGENT_BOOT_CONTENT_DB_ENABLED=1
AGENT_BOOT_CONTENT_DATABASE_URL=postgresql://agent_boot_writer:...@db:5432/device_farm
AGENT_BOOT_CONTENT_DB_POOL_SIZE=1
AGENT_BOOT_XML_PARSE_WORKERS=1
AGENT_BOOT_XML_MAX_BYTES=2097152
```

The phone must be able to reach:

```text
http://<agent-host-or-ip>:8765/extra-data/xml
```

## Enable Device Farm Route

Use either scenario step config:

```json
{
  "type": "extract",
  "strategy": "fb_posts",
  "collection": "fb_group_1h",
  "edge_extra_data": true,
  "edge_extra_agent_url": "http://<agent-host-or-ip>:8765",
  "dedupe_field": "post_key"
}
```

Or environment flags:

```bash
EDGE_EXTRA_DATA_ENABLED=1
EDGE_EXTRA_AGENT_URL=http://<agent-host-or-ip>:8765
EDGE_EXTRA_TOKEN=<shared-secret>
EDGE_EXTRA_TIMEOUT_S=45
```

There is no server-side Facebook parser fallback. If the agent/APK request fails, the step fails clearly with the edge summary.

By default, the environment flag alone does not activate arbitrary extract steps. The step must explicitly set `edge_extra_data: true`, or the server must set `EDGE_EXTRA_APPLY_GLOBALLY=1`.

If a scenario step supplies `edge_extra_agent_url`, protect XML exfiltration by setting `EDGE_EXTRA_AGENT_URL_ALLOWLIST` to comma-separated allowed prefixes. Without an env `EDGE_EXTRA_AGENT_URL`, step-provided endpoints are rejected unless `EDGE_EXTRA_ALLOW_STEP_ENDPOINT=1`.

## Expected Success Path

1. `device_farm` sends only the `extra_data_xml` control command plus context/endpoint/token to the APK through the existing device-agent WebSocket.
2. APK dumps accessibility XML locally and POSTs it to `agent-boot`.
3. `agent-boot` validates `xml_sha256`, parses posts/comments with `agent-boot/relay/fb_extract`, writes `content_items`, and returns a compact summary.
4. APK forwards the compact result to `device_farm`.
5. `device_farm` updates step result counters without receiving raw XML.

## Current Observability

The summary contains `parsed_count`, `inserted_attempted`, `inserted_count`, `duplicate_count`, `xml_bytes`, `xml_sha256`, `parse_ms`, `db_ms`, and `elapsed_ms`.

Still missing before broad rollout: staging p95 measurements, DB-role security checks, cross-tenant dedupe integration tests, and explicit metric export for queue depth/rejections.
