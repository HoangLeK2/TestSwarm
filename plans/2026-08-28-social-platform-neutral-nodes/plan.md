---
title: "Chuan hoa Node Social Platform-Neutral"
description: "Harden template Facebook hien tai va chuan hoa contract social node de co the ke thua sang platform khac."
status: pending
priority: P1
effort: 2-3 days
branch: fix/relay-registration-scaling
tags: [backend, scenario, social-node, platform-neutral, tech-debt]
created: 2026-08-28
---

# Chuan Hoa Node Social Platform-Neutral

## Summary

Trien khai theo huong staged: harden template Facebook hien tai truoc, sau do chuan hoa contract social node de cac platform khac co the ke thua qua capability adapter thay vi copy flow Facebook.

Muc tieu:

- Template `Nuoi Facebook - Gieo mam ban be tu Group (account moi) copy` khong con nested step thieu `id`.
- Validator/test bat thieu `id` o moi cap nested.
- Public social node giu ten platform-neutral.
- Contract input/output cua `_post_scan` va `_people_target` duoc schema hoa.
- Facebook giu behavior cu, khong pha campaign/template hien co.
- Co nen de them app khac bang adapter capability.

## Key Changes

### 1. Harden Template Hien Tai

- Them stable `id` cho toan bo nested steps trong seed template.
- Ap dung cho cac node con nhu `wait`, `key`, `tap_selector`, `tap_xml_match`, `if_element`, `scroll_down`, `dismiss_popup`, `set_variable`.
- Khong doi behavior business hien tai:
  - launch app
  - session gate
  - search group
  - join group
  - scan post
  - like/comment
  - mo commenter
  - verify profile
  - gui friend request neu enabled

### 2. Recursive Validation

- Validator/test phai duyet toan bo cay step:
  - `steps`
  - `then`
  - `else`
  - nested loop/branch containers
- Fail ro khi:
  - authored node thieu `id`
  - duplicate `id`
  - `id` khong stable
- Khong bat runtime-generated transient objects neu chung khong phai authored scenario step.

### 3. Social Output Schema V1

Chuan hoa `_post_scan`:

```json
{
  "schema_version": 1,
  "platform": "facebook",
  "actions": [],
  "proof": {}
}
```

Chuan hoa `_people_target`:

```json
{
  "schema_version": 1,
  "platform": "facebook",
  "identity": {},
  "proof": {}
}
```

Yeu cau:

- Handler moi phai ghi output theo shape moi.
- Handler van doc duoc shape cu trong giai doan chuyen tiep.
- `connection_request` tiep tuc phu thuoc vao verified target, khong gui request mu.

### 4. Capability Adapter Boundary

Scenario node la capability chung. Platform adapter chiu trach nhiem xu ly UI cu the.

Public capabilities can giu:

- `open_surface`
- `community_membership`
- `content_scan`
- `content_interaction`
- `engagement_source.select`
- `profile_verify`
- `connection_action`

Facebook adapter map cac capability nay vao `_fb_*` implementation hien co.

Khong de template reusable chua truc tiep cac chi tiet:

- label `Nhom`, `Groups`, `Trang chu`
- coordinate fallback
- tab-strip swipe
- Facebook-only navigation choreography

## Implementation Phases

### Phase 1: Template Hardening

File chinh:

- `device_farm/db/seeds/scenario_templates.py`

Viec can lam:

- Them stable `id` cho moi nested step cua scenario gieo mam tu group.
- Giu nguyen selector, timing, keyword, loop budget, action semantics.

Acceptance:

- Template khong con authored step thieu `id`.
- Existing template tests van pass.

### Phase 2: Recursive Authored-Step Validation

Viec can lam:

- Them helper recursive traversal cho scenario step tree.
- Test root va nested authored steps.
- Test duplicate `id`.

Acceptance:

- Test fail khi nested node thieu `id`.
- Template gieo mam tu group pass.

### Phase 3: Social Contract Schema V1

Viec can lam:

- Cap nhat output cua social scan/open commenter.
- Them `schema_version`, `platform`, `proof`.
- Giu backward compatibility voi shape cu.

Acceptance:

- `_post_scan -> social_open_commenter_from_post_match -> _people_target -> connection_request` chay qua test contract.
- Khong pha existing campaign/template.

### Phase 4: Documentation

Viec can lam:

- Document public social node contract.
- Ghi ro adapter responsibility.
- Ghi ro Facebook la adapter dau tien, chua phai template mau cho moi app.

Acceptance:

- Engineer khac co the them platform moi bang capability adapter ma khong clone truc tiep template Facebook.

### Phase 5: Optional DB Sync

Chi lam neu can cap nhat ban copy trong DB ngay.

Viec can lam:

- Export/backup scenario row hien tai.
- Chay seed/update path dang dung trong repo.
- Verify hash/body va validation summary.

Acceptance:

- DB copy match seed moi.
- `last_validation_summary` duoc cap nhat neu validation path ho tro.

## Test Plan

Chay toi thieu:

```bash
cd device_farm
uv run pytest tests/test_template_comment_dedupe_contract.py -k "seed_template"
uv run pytest tasks/scenario/tests/test_interaction_xml_match.py tests/test_template_comment_dedupe_contract.py -k "tap_xml_match or seed_template"
```

Them test moi:

- recursive authored-step ID validation
- duplicate nested ID detection
- `_post_scan` schema v1 output
- `_people_target` schema v1 output
- backward compatibility voi old saved variable shape

Runtime proof rieng:

- Chi claim live-pass khi co campaign/preview execution trace that.
- Khong dung preview-stream don le lam bang chung campaign.

## Assumptions

- Pham vi la staged ca hai: harden Facebook truoc, chuan hoa platform-neutral sau.
- Khong them platform/app moi trong phase nay.
- Khong doi logic gui request ngoai viec lam ro contract va validation.
- Khong dung dirty frontend changes khong lien quan.
- Khong them logic bypass, fingerprint, fake identity/location, hoac ne kiem soat platform.

## Risks

- Recursive validation co the lam lo them template cu thieu `id`.
- Schema output moi can backward compatibility de khong pha campaign dang chay.
- Neu sync DB truc tiep, can backup row truoc.
- Runtime Facebook UI van co the thay doi; can live XML/campaign trace de xac nhan thuc te tren device.
