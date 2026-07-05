---
title: "App Automation Profile Plan"
description: "Build a u2-first automation layer for app login, form fill, mobile flow testing, popup handling, and weak-selector screens."
status: in-progress
priority: P1
effort: 8-12d
branch: fix/sse
tags: [feature, backend, frontend, api, testing, performance, experimental]
created: 2026-07-03
---

# App Automation Profile Plan

## Overview

Create a `u2`-first automation profile system inspired by LAMDA ideas: watchers, semantic locators, selector fallback, OCR/image-ready extension points, traceable login/form/mobile-test flows, and monitor-visible proof.

Non-goal: import or depend on LAMDA runtime. This repo keeps `u2` as the execution backend.

## Guiding Principles

- Reuse current scenario executor, selector normalization, monitor, and agent-boot relay paths.
- Add profile-driven capability, not app-specific hardcoded scripts.
- Every action must produce evidence: selected locator, hierarchy source, screenshot/XML refs, watcher triggers, timing.
- Avoid OCR/image matching until selector fallback and trace quality are solid.
- Every implementation phase must pass tests, performance checks, and subagent review.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Scout, Research, Impact Map | Completed | 1d | [phase-01](./phase-01-scout-research-impact.md) |
| 2 | Profile Contract and Data Model | Completed | 1-2d | [phase-02](./phase-02-profile-contract.md) |
| 3 | Semantic Locator Runtime | Completed | 2d | [phase-03](./phase-03-semantic-locator-runtime.md) |
| 4 | Popup Watcher Engine | Partial | 1-2d | [phase-04](./phase-04-popup-watcher-engine.md) |
| 5 | Login, Form Fill, Flow Test Steps | Partial | 2-3d | [phase-05](./phase-05-login-form-flow-steps.md) |
| 6 | Observability, Monitor UI, Artifacts | Partial | 1d | [phase-06](./phase-06-observability-monitor-ui.md) |
| 7 | Performance, QA, Review, Rollout | Partial | 1d | [phase-07](./phase-07-performance-qa-review-rollout.md) |

## Subagent Review Model

- `explorer`: read-only code and flow mapping before any implementation.
- `docs-researcher`: verify LAMDA-inspired patterns and `u2`/Android automation edge cases.
- `reviewer`: correctness, security, maintainability review after each implementation phase.
- `performance-reviewer`: benchmark hierarchy dump, locator scoring, watcher loop overhead.
- `qa-agent`: scenario-level regression plan, live-device smoke checklist, Playwright UI checks.

## Required Gates

- GitNexus `impact` before editing each function/class/method.
- Unit tests for selector scoring, profile validation, watcher matching, login/form state machines.
- Integration tests for scenario executor step results and monitor payloads.
- Live-device smoke on at least one app with popup and one weak-resourceId screen.
- Performance budget: watcher scan and locator selection must not add visible latency to normal tap flows.
- GitNexus `detect_changes()` before commit or PR.

## Key Dependencies

- Existing `u2` hierarchy and direct relay HTTP dump path.
- Existing scenario schema/API validation surfaces.
- Existing campaign/scenario flow editor and monitor event rendering.
- Account/group data source for credentials and form values.

## Open Decisions

- First target app/package for live smoke.
- Whether credentials come only from account groups or also scenario variables.
- Whether OCR/image matching is phase 2 or kept as later extension.

## Current Implementation Snapshot

- Backend profile contracts, semantic locator resolver, popup watcher evaluator, pre-step popup watcher hook, and `login_if_needed` / `fill_form` / `assert_app_state` handlers are implemented.
- Backend scenario schema and common scenario schema accept the new step types.
- Frontend flow editor can insert and structurally edit the new app automation step profiles.
- Campaign monitor rows can render app automation watcher/locator/form/assert traces from SSE details.
- Screenshot/XML artifact links, live-device smoke, and formal performance benchmark remain pending.
