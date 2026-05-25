# Phase 02: Shared Extract and Hashing

## Overview

Move Facebook parser ownership for the direct extra-data path into `agent-boot`, while keeping hash behavior aligned with the legacy `content_store` contract.

Priority: P1  
Status: Partial  
Effort: 5h

## Context Links

- `agent-boot/relay/fb_extract/*`
- `device_farm/services/content_store.py`
- `device_farm/tasks/scenario/steps/extraction.py`
- `docs/fb-extract-data-flow.md`
- [Performance/data review](./reports/performance-data-correctness-review.md)

## Requirements

- Agent and server compute identical `content_hash` and `parent_id` scopes.
- Agent parses phone-provided XML locally in `agent-boot`.
- Agent maps normalized rows into `content_items` insert payloads that match the legacy contract.
- Relative date parsing uses XML `captured_at` as the base time, not agent/server wall clock.
- Agent parser code must not import FastAPI, SQLAlchemy session factories, or device manager modules.
- Keep the shared layer small: parser, field mapping, hash helpers, safe int/date parsing.

## Architecture

Current direct-path implementation keeps parser ownership inside `agent-boot`:

```text
agent-boot/relay/fb_extract/
  feed_pipeline.py
  comment_pipeline.py
  post_extractor.py
```

`device_farm` should only act as the control node: it sends context/endpoint/token to the phone/APK and receives a compact summary. It must not upload XML or call agent-boot parsing directly.

Longer term, if another runtime needs the same parser, create a shared package with pure functions:

```text
shared/content_pipeline/
  hashing.py
  normalize.py
  fb_extract/
    feed_pipeline.py
    comment_pipeline.py
    post_extractor.py
```

Then:

```text
agent-boot imports shared package
```

Avoid:

```text
agent-boot imports device_farm.services.content_store directly
```

That would drag server config and DB dependencies into agent runtime.

## Related Code Files

- Own parser at: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/fb_extract/*`
- Move/extract from: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/services/content_store.py`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tasks/scenario/steps/extraction.py`
- Modify: `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/pyproject.toml`
- Create tests in both packages.

## Implementation Steps

1. [x] Identify pure parser functions used by FB posts/comments extraction.
2. [x] Move direct-path parser ownership into `agent-boot/relay/fb_extract`.
3. [x] Remove `device_farm/tasks/fb_extract`; server-side FB parsing now fails clearly unless edge extra-data is used.
4. [x] Mirror hash helpers in agent writer:
   - `compute_content_hash`
   - `scope_content_hash`
   - `_safe_int`
   - content field mapping helpers
5. [ ] Add golden tests:
   - same XML input
   - same parsed rows
   - same content hash
   - same scoped parent hash
   - same `content_date` for relative timestamps
   - same insert payload fields for old and new paths
6. [x] Update agent ingest imports so direct extra-data no longer imports `device_farm.tasks.fb_extract`.
7. [x] Remove legacy `device_farm/tasks/fb_extract` after retiring server-side FB fallback.

## Success Criteria

- Non-legacy `device_farm` tests still pass.
- `agent-boot` can import its parser/hash path without importing server DB/config.
- Golden tests prevent parser/hash drift.
- Comment rows link to the same scoped parent hash as the server path.

## Risks

- Parser modules may have hidden dependencies on scenario context.
- Moving code can break imports in tests or Temporal activities.
- Date parsing dependencies like `dateparser`/`ftfy` may need optional handling.

## Mitigation

- First extract wrappers only; avoid deep refactor.
- Preserve public function names where possible.
- Add compatibility imports in old module locations.
