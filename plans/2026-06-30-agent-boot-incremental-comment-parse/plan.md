---
title: "Agent Boot Incremental Comment Parse Plan"
description: "Reduce fb_comments raw XML payload and memory pressure without losing comments from earlier scroll snapshots."
status: pending
priority: P2
effort: 10h
issue: null
branch: fix/sse
tags: [backend, performance, refactor]
created: 2026-06-30
---

# Agent Boot Incremental Comment Parse Plan

## Overview

Goal: reduce `fb_comments` raw XML payload/memory pressure while preserving the current multi-snapshot correctness contract.

Do not start by deleting `xml_snapshots`. Today, ingest uses snapshots as source data: `collector.build_ingest_payload()` sends raw XML snapshots, then `ingest._parse_fb_comment_snapshots()` parses each frame, dedupes comments, keeps latest stats, and returns diagnostics. A direct `last_xml` or items-only switch would lose comments from earlier viewports unless parsing already happened before the XML is discarded.

## Current Contract

Key files:
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/collector.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/ingest.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_extra_data_ingest.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_extra_data_collector.py`

Important invariants:
- `payload["xml"]` is currently the primary snapshot.
- `payload["xml_snapshots"]` currently carries all snapshots when more than one exists.
- Ingest reconstructs snapshots from `xml + xml_snapshots`.
- `fb_comments` must merge comments across frames and dedupe by comment key.
- `snapshot_count`, `comments_returned`, `frame_reason_codes`, parent context, and evidence behavior must remain correct.

## Recommended Design

Implement in phases.

Phase 1 preserves runtime behavior:
- Extract the existing multi-snapshot parse/merge logic into a pure helper.
- Add direct tests around the helper.
- No payload contract change yet.

Phase 2 adds a feature-flagged preparsed path:
- Collector parses each comment snapshot as it is accepted.
- Collector accumulates deduped `preparsed_items` and `preparsed_diagnostic`.
- Payload can include `preparsed_items` for `fb_comments`.
- Ingest uses `preparsed_items` only when an explicit flag/context says it is trusted.
- Existing raw `xml_snapshots` path remains fallback.

Phase 3 reduces XML retention:
- When preparsed path passes tests and live metrics, stop sending full `xml_snapshots` by default.
- Keep `last_xml` as evidence.
- Keep full snapshots only behind debug env/context flag.

Do not gzip in the current in-process path. `agent.py` calls `self._extra_ingest.process_payload(payload)` directly, so gzip would add compression/decompression CPU without solving device-side latency.

## Phases

| # | Phase | Status | Effort | Purpose |
|---|-------|--------|--------|---------|
| 1 | Extract merge helper | Pending | 2h | Make existing behavior reusable and testable |
| 2 | Add preparsed payload support | Pending | 3h | Let ingest accept already-merged comment items safely |
| 3 | Incremental collector parse | Pending | 3h | Reduce raw XML payload after each snapshot is consumed |
| 4 | Metrics, tests, rollout guard | Pending | 2h | Prove benefit and protect rollback |

## Phase 1: Extract Merge Helper

Modify:
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/ingest.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_extra_data_ingest.py`

Steps:
1. Extract `_parse_fb_comment_snapshots()` internals into a helper with a clear signature:
   ```python
   def merge_fb_comment_frames(
       frame_results: list[tuple[list[dict[str, Any]], dict[str, Any]]],
       *,
       max_items: int,
   ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
       ...
   ```
2. Keep `_parse_fb_comment_snapshots()` as wrapper:
   - parse each XML snapshot
   - pass parsed frames into helper
3. Add tests:
   - duplicate comment across frames returns once
   - second frame adds new comment
   - latest `post_stats` wins
   - `max_items` caps comments, not stats
   - `frame_reason_codes` preserved

Success criteria:
- Existing ingest snapshot tests unchanged or minimally updated.
- `uv run pytest relay/tests/test_extra_data_ingest.py -q` passes.

## Phase 2: Add Preparsed Payload Support

Modify:
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/ingest.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_extra_data_ingest.py`

Payload shape:
```python
{
    "strategy": "fb_comments",
    "xml": last_or_primary_xml,
    "preparsed": {
        "items": [...],
        "diagnostic": {...},
        "snapshot_count": 9,
        "xml_bytes": 420000,
    },
    "context": {
        "agent_boot_preparsed_comments": True,
    },
}
```

Rules:
- Only use `preparsed` for `strategy == "fb_comments"`.
- Only trust it when `context["agent_boot_preparsed_comments"] is True`.
- Validate `items` is a list and diagnostic is a dict.
- Preserve parent context handling in `process_payload()` after items are loaded.
- Preserve fallback: if validation fails, parse XML snapshots as today.

Tests:
- trusted preparsed comments bypass `_parse_items`
- invalid preparsed falls back to XML parse
- parent context still injected via `_with_comment_parent_context`
- `return_items` behavior unchanged
- persistence disabled path still works

Success criteria:
- Ingest can accept both old and new payloads.
- No existing backend/front-end contract changes required.

## Phase 3: Incremental Collector Parse

Modify:
- `/Users/hoangle/farm/device-farm/agent-boot/relay/extra_data/collector.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/agent.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_extra_data_collector.py`
- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests/test_extra_data_relay.py`

Design:
- During `_collect_comment_snapshots()`, parse each accepted snapshot after it passes duplicate/XML/cap checks.
- Accumulate parsed frame results in context-private keys:
  - `_preparsed_comment_items`
  - `_preparsed_comment_diagnostic`
  - `_preparsed_comment_snapshot_count`
  - `_preparsed_comment_xml_bytes`
- Keep raw snapshots initially while feature flag is off.
- Add env/context flag:
  - env: `AGENT_BOOT_PREPARSE_FB_COMMENTS=1`
  - context override: `preparse_fb_comments=true`
- When enabled, `build_ingest_payload()` includes `preparsed` and may omit `xml_snapshots`.
- Always keep one XML evidence:
  - `xml`: first or last XML required by ingest validation
  - `evidence["hierarchy_xml"]`: last XML, as current code already does

Important: do not parse the same snapshot twice if no-new detection already parsed it. Reuse parsed items where possible. If reuse makes the patch messy, keep duplicate parse for first rollout and measure before optimizing further.

Tests:
- comments from first/middle/last snapshots all appear in preparsed items
- duplicate comments across snapshots dedupe
- `post_stats` behavior matches ingest helper
- debug flag can still include raw `xml_snapshots`
- cancellation still stops promptly
- XML byte cap and wall-clock cap diagnostics unchanged

Success criteria:
- `collect_xml_snapshots()` behavior remains backward compatible when flag off.
- Flag-on payload carries preparsed comments and omits full snapshots by default.

## Phase 4: Metrics, Verification, Rollout

Add or verify diagnostics:
- raw snapshot count
- raw XML bytes collected
- raw XML bytes sent
- preparsed item count
- parse time in collector
- parse time in ingest
- payload serialization time if easy to measure

Test commands:
```bash
cd /Users/hoangle/farm/device-farm/agent-boot
uv run pytest relay/tests/test_extra_data_ingest.py -q
uv run pytest relay/tests/test_extra_data_collector.py -q
uv run pytest relay/tests/test_extra_data_relay.py -q
uv run pytest relay/tests/test_crawl_loop_simulation_benchmark.py -q
```

Broader repo checks if backend contract touched:
```bash
cd /Users/hoangle/farm/device-farm
uv run pytest device_farm/tests/test_edge_extra_data.py -q
```

GitNexus checks before edits/commit:
```bash
npx gitnexus impact _parse_payload_items --direction upstream
npx gitnexus impact build_ingest_payload --direction upstream
npx gitnexus impact collect_xml_snapshots --direction upstream
npx gitnexus detect_changes
```

Live validation:
- Run one `fb_comments` extraction with flag off. Capture:
  - `snapshot_count`
  - `parsed_count`
  - `xml_bytes`
  - `parse_ms`
  - elapsed total
- Run same profile with flag on. Compare:
  - same or higher parsed comments
  - same parent linkage
  - lower serialized payload/raw XML sent
  - no increase in loop lag

Expected improvement:
- Payload/raw XML sent: 70-95% lower for long comment crawls.
- JSON serialization/payload overhead: 50-90% lower for large crawls.
- End-to-end crawl latency: likely 5-20% lower only when payload/parse overhead is significant.
- Device swipe/dump time: mostly unchanged.

Rollback:
- Disable `AGENT_BOOT_PREPARSE_FB_COMMENTS`.
- Ingest keeps old `xml_snapshots` path.
- Leave helper extraction in place if tests pass; it is internal refactor.

## Risks

High correctness risk:
- Losing comments from earlier snapshots if raw XML is omitted before preparsed merge is correct.

Medium risk:
- Parent context injection could diverge if preparsed items skip ingest-side `_with_comment_parent_context`.
- Diagnostics may drift from existing `snapshot_count/comments_returned/frame_reason_codes`.

Low risk:
- More CPU in collector if parse duplicates no-new probe parse. Measure before tuning.

## Definition of Done

- Flag off: behavior identical to current tests.
- Flag on: long `fb_comments` uses preparsed path and does not require full raw XML snapshots.
- Existing `fb_comments` merge/dedupe tests pass.
- New tests prove first/middle/last comments survive.
- `detect_changes` reports expected files/symbols only.
- Live/benchmark output shows payload reduction and no correctness regression.
