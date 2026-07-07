# Phase 05: Login, Form Fill, Flow Test Steps

## Overview

Expose profile capabilities as scenario steps, then wire them through backend validation, executor, frontend editor, and monitor.

## New Step Concepts

- `login_if_needed`
- `fill_form`
- `run_app_flow`
- `assert_app_state`
- `assert_no_popup`

## Requirements

- Credentials loaded from account/group/variables by reference.
- `login_if_needed` detects already-logged-in state before typing.
- `fill_form` verifies focus and typed value when possible.
- Flow test steps produce assertion output, not just pass/fail.
- Human-blocking states like captcha/2FA return `blocked`, not infinite retry.

## Expected Files

- Backend scenario schemas.
- Common scenario schema.
- Scenario executor step modules.
- Frontend scenario step defaults.
- Frontend insert menu and step detail panel.
- Monitor event folding/rendering.

## Tests

- Backend schema accepts new steps and rejects invalid payloads.
- Executor unit tests for already-login, login success, login blocked, form fill partial failure.
- Account value resolution tests: missing secret fails clearly.
- Frontend tests for step defaults and editor serialization.
- Monitor tests show assertion/form/login output.

## E2E / Live Smoke

- App A: login screen with normal IDs.
- App B: form screen with weak/missing resourceId.
- App C: popup before login or update prompt.

## Review Gate

- `reviewer`: step semantics and backward compatibility.
- `qa-agent`: user workflow coverage.
- `security-reviewer`: secret handling and logs redaction.

## Success Criteria

- User can create these steps from the flow editor.
- Campaign monitor shows what happened and why.
- Failed login/form flow is diagnosable without opening raw logs.

## Implementation Progress

- Added backend scenario schema models for `login_if_needed`, `fill_form`, and `assert_app_state`.
- Registered runtime handlers in `device_farm/tasks/scenario/steps/app_automation.py`.
- `login_if_needed` detects logged-in text before typing and emits locator/submit trace without resolved credential values.
- `fill_form` supports named recipes, strict vs best-effort field failures, and optional submit.
- `assert_app_state` supports package, text presence/absence, and optional semantic locator checks.
- Frontend insert menu/default step support exists for these three step types.
- Structured detail-panel editing exists for package, semantic locators, login recipes, form recipes, assert fields, and popup watchers.
- `run_app_flow`, `assert_no_popup`, live-device smoke, and richer profile templates remain pending.
