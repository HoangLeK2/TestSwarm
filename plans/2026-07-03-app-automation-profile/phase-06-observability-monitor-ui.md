# Phase 06: Observability, Monitor UI, Artifacts

## Overview

Make automation explain itself in the campaign monitor and artifacts.

## Required Evidence

- screenshot before/after high-risk action
- XML/hierarchy reference
- selected locator candidate and score
- fallback level used
- watcher trigger list
- assertion details
- duration per sub-operation
- account/profile reference IDs, not secret values

## UI Requirements

- Step rows summarize action outcome.
- Expandable detail shows locator decision trace.
- Watcher triggers render as explicit events.
- Assertion failures show expected vs observed.
- Long output is truncated with artifact link.

## Tests

- Activity event payload includes locator/watcher/assertion fields.
- SSE folding preserves new fields.
- Persisted step rows still render after reload.
- Frontend component handles missing optional fields from older runs.

## Review Gate

- `reviewer`: output contract stability.
- `qa-agent`: monitor route checks on locale-prefixed routes.

## Success Criteria

- User can answer: what was tapped, why, and what interrupted the flow.
- Old runs do not break monitor rendering.

## Implementation Progress

- Step result payloads for new handlers include locator traces, assertion details, form field traces, submit traces, and pre-step popup watcher events.
- Frontend flow editor has structured edit support for app automation profiles.
- SSE folding preserves app automation monitor fields in `details`.
- Workflow step rows render popup watcher events, locator trace, submit trace, form field traces, and assertion payloads when present.
- Screenshot/XML artifact links, expanded trace drawer, and live monitor route smoke remain pending.
