# Codebase Analysis: agent-boot Direct Content Writer

## Current Hot Path

- `agent-boot`/device obtains UI hierarchy through u2/a11y.
- `device_farm.tasks.scenario.steps.extraction.handle_extract()` calls `device.hierarchy_xml(force_refresh=True)`.
- Legacy `device_farm.tasks.fb_extract` has been removed; direct Facebook parsing now lives in `agent-boot/relay/fb_extract`.
- `_do_inline_auto_save()` calls `services.content_store.save_content_item()`.
- `save_content_item()` computes/scopes hash, maps fields, creates/updates collection counters, inserts `content_items`.

## Relevant Existing Files

- `agent-boot/relay/u2_executor.py`
  - Already supports `dump_hierarchy`, primitive u2 batch actions, and named flows.
- `agent-boot/relay/agent.py`
  - Already dispatches `u2_batch` and `u2_flow` requests.
- `device_farm/runtime/transports/adb_relay_server.py`
  - Already sends `u2_batch` and `u2_flow` requests to agent-boot.
- `device_farm/tasks/scenario/steps/extraction.py`
  - Current extract orchestration and inline save.
- `agent-boot/relay/fb_extract/*`
  - Parser logic used by the direct phone/APK → agent-boot extra-data route.
- `device_farm/services/content_store.py`
  - Canonical hash, text cleanup, field mapping, DB persistence rules.
- `device_farm/db/models/content.py`
  - `content_items` model and indexes.

## Data Contract Facts

- `content_items` has FK columns to `campaigns`, `executions`, and `users`, but the agent does not need to read/write those tables if the context payload provides valid IDs.
- Unique dedup index exists on `(content_hash, collection, user_id)`, with a separate null-user unique index.
- Direct SQL insert must set values usually provided by SQLAlchemy Python defaults: `id`, `created_at`, `extracted_at`, `media_urls`, `raw_data`, `tags`, `content_hash`.
- Existing `save_content_item()` scopes content hash by `execution_id`/`hash_scope`; agent writer must match this exactly or dedupe/reporting will diverge.
- Existing `save_content_item()` creates/increments `content_collections`; direct insert will bypass that unless a DB trigger or async reconciliation is added.

## Recommended Shape

Make `agent-boot` an edge execution worker for Facebook extraction, but keep `device_farm` as control plane.

Agent responsibilities:
- receive run/context metadata from `device_farm`
- receive hierarchy XML from phone/APK
- parse extra FB data locally
- compute the same content hashes
- insert into `content_items` with `ON CONFLICT DO NOTHING`
- report progress summary back to `device_farm`

Device farm responsibilities:
- assign run/context metadata and consume summaries
- provide user/campaign/execution/device context
- show dashboard/progress
- reject server-side FB parsing when edge extra-data is not configured
- reconcile collection counters if still needed

## Main Risks

- Hash drift between `device_farm` and `agent-boot`.
- Parser drift if legacy tests or docs assume a server-side parser still exists.
- DB connection explosion from many agents.
- Credentials leakage if agent gets broad DB permissions.
- FK failures if context contains stale/deleted IDs.
- Collection counters become approximate unless handled explicitly.

## Hard Constraints

- Agent DB role must be narrow: insert-only into `content_items`, optionally execute a single stored function if raw insert cannot stay safe enough.
- No direct agent write to `campaigns`, `organizations`, `accounts`, `devices`, or `users`.
- Server-side FB fallback is intentionally removed; rollback should disable the new route only after an alternative parser is restored.
- Payload schema must be versioned.
