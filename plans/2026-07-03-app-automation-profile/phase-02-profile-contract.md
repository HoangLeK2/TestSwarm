# Phase 02: Profile Contract and Data Model

## Overview

Define the durable contract for app automation profiles before executor work.

## Proposed Contract

```yaml
package: com.example.app
entry_state:
  launch: true
  wait_for_any:
    - text: "Login"
    - text: "Home"
popup_watchers:
  - name: close_update_dialog
    when:
      text_contains: ["Update"]
    action:
      tap_text_any: ["Later", "Not now"]
    max_triggers_per_run: 3
semantic_locators:
  password_field:
    candidates:
      - resource_id_contains: "password"
      - text_near: ["Password", "Mật khẩu"]
        target_class: "android.widget.EditText"
login_recipe:
  detect_logged_in:
    any_text: ["Home", "Profile"]
  fields:
    username:
      locator: username_field
      value_from: account.username
    password:
      locator: password_field
      value_from: secret.login_password
  submit:
    tap_text_any: ["Login", "Sign in"]
```

## Expected Files To Modify/Create

- Create backend schema module for app automation profile.
- Extend scenario schema only after impact analysis confirms best integration point.
- Add fixture examples under tests, not production seed data in this phase.

## Requirements

- Validate profile shape strictly.
- Keep credentials as references, never inline secrets.
- Allow per-package watcher scope.
- Make OCR/image fields extension-ready but disabled by default.
- Support versioning: `profile_version`.

## Tests

- Schema validation accepts minimal valid profile.
- Schema rejects inline secret values for password/token fields.
- Schema rejects unsafe global watcher without package/scope.
- Backward compatibility: existing scenarios still validate.

## Review Gate

- `reviewer` checks schema clarity, backward compatibility, and security.
- `security-reviewer` checks credential handling and unsafe action prevention.

## Success Criteria

- Contract is expressive enough for login, form fill, popup watcher, and weak selector fallback.
- No executor behavior changes yet.

## Implementation Progress

- Added isolated backend contract in `device_farm/services/app_automation_profile.py`.
- Added validation tests in `device_farm/tests/test_app_automation_profile.py`.
- Implemented guardrails for package scope, unsafe watcher actions, duplicate watcher names, credential references, and locator reference integrity.
- Backend scenario wiring now accepts profile-driven steps; runtime handlers validate the profile before action.
- Secrets remain references only. Runtime resolves `secret.*` through scenario/campaign variables in this slice and does not persist resolved values in step output.
