# Core Release Scope Validation

Status: active
Last audited: 2026-05-25

Tài liệu này ghi lại kết quả đối chiếu phạm vi **core release Facebook L2**
giữa `docs/official_docs`, codebase và automated smoke test. Đây là trạng thái
thực tế để dùng trước khi chia ticket fix / test / nghiệm thu.

## Verdict

Kết luận: **scope target khớp codebase ở mức tổng thể, nhưng chưa đủ điều kiện
acceptance / release sign-off**.

- `GO` cho bước testing/UAT có điều kiện.
- `NO-GO` cho acceptance cho tới khi xử lý các blocker contract-level bên dưới.
- Không cần mở rộng scope hoặc sửa quá nhiều module; nên khóa scope core và chỉ
  xử lý các gap nhỏ nhưng chạm trực tiếp release gate.

Phạm vi đúng:

- Core modules: `DF-MOD-01`, `02`, `03`, `04`, `05`, `06`, `07`, `09`, `11`.
- `DF-MOD-08` chỉ trong phạm vi **Facebook L2 Active**.
- Out-of-scope vẫn đúng: `DF-MOD-10`, MCP/L3 production claim,
  TikTok/Threads/Instagram L2, SSO, vault, HA, BI, proactive alerting, export
  refactor lớn.

## Module Match Summary

| Module | Match với codebase | Release verdict | Ghi chú |
|---|---|---|---|
| `DF-MOD-01` Platform runtime/auth | Match | Testing/UAT | Auth, JWT, organization, safe-mode, OpenAPI surface đều có code/test footprint. |
| `DF-MOD-02` Devices/control plane | Match | Testing/UAT | Device CRUD/control, reserve/session, hierarchy/screenshot/stream, device groups có code/test footprint. |
| `DF-MOD-03` Agent boot/relay | Match | Testing/UAT | `agent-boot`, relay routes, reconnect/USB preference tests có sẵn. |
| `DF-MOD-04` Campaign/scenario/execution | Match có risk | Testing/UAT + parity gate | Campaign dispatch, execution, checkpoint, DLQ có code/test; vẫn cần test surface parity preview/session/campaign. |
| `DF-MOD-05` Scheduling | Partial | Fix/decision trước RC | Docs/QC nói fallback marker và schedule -> execution/deep link; code path Temporal-off cho campaign còn mâu thuẫn với claim fallback. |
| `DF-MOD-06` Content/artifacts | Partial | P0 trước acceptance | Contract yêu cầu `fb_post`/`fb_comment`; code/template/UI còn generic `post`, `group_post`, `comment` ở vài điểm. |
| `DF-MOD-07` Accounts/groups | Partial | P0 trước acceptance | Contract yêu cầu explicit account intent; dispatch vẫn có legacy fallback sang primary account per device. |
| `DF-MOD-08` Facebook L2 | Partial | P0 trước acceptance | Facebook parser/strategy tồn tại, nhưng content type và canonical/legacy naming cần khóa rõ. |
| `DF-MOD-09` Notifications/analytics | Match có parity risk | Testing/UAT + parity gate | API/UI surface có sẵn; cần OpenAPI/generated-client/proxy audit và deep-link UAT. |
| `DF-MOD-11` Frontend/dashboard | Match có build risk | Fix nhỏ + UAT | Core routes có đủ, nhưng lint/TypeScript hiện chưa pass. |

## Blockers Tối Thiểu

### `P0` - Facebook content type contract

Acceptance của `DF-MOD-06/08` yêu cầu content Facebook lưu bằng
`fb_post` / `fb_comment`, có `parent_id`, `item_level`, trace tới
campaign/scenario/execution/device/account.

Hiện trạng cần xử lý:

- Một số template/default UI/persistence còn dùng `post`, `group_post`,
  `comment`.
- Không nên pass UAT-02 nếu chỉ thấy strategy `fb_posts` / `fb_comments` chạy
  mà DB/API vẫn lưu generic content type.

Ticket nên tách:

- `06B/08C-facebook-content-type-normalization`
- `08E-facebook-contract-regression-pack`

### `P0` - Account intent explicit

Acceptance của `DF-MOD-07` yêu cầu scenario thiếu account intent phải fail rõ,
không âm thầm suy diễn primary account của device cho core templates.

Hiện trạng cần xử lý:

- Dispatch vẫn còn legacy fallback sang primary account per device cho scenario
  không bound account group.
- UI/copy cần tránh hướng dẫn người dùng dựa vào fallback này như behavior chính.

Ticket nên tách:

- `07E-legacy-fallback-audit`
- `07F-core-template-account-intent-enforcement`

### `P0` - Scheduling fallback contract

Acceptance của `UAT-04` yêu cầu schedule `run-now` hoặc cron path tạo execution,
notification, activity log và deep link đúng. Nếu fallback mode tồn tại thì phải
có marker rõ.

Hiện trạng cần chốt:

- Docs mô tả fallback khi Temporal unavailable.
- Code có đường chặn campaign dispatch khi Temporal không khả dụng.

Quyết định cần đưa vào ticket:

- Hoặc sửa code để fallback dispatch đúng claim.
- Hoặc thu hẹp docs/QC/release claim: campaign schedule core yêu cầu Temporal,
  fallback chỉ là degraded marker chứ không tương đương durable path.

Ticket nên tách:

- `05C-schedule-execution-link-and-trigger-source`
- `05D-temporal-fallback-contract-decision`

### `P1 / RC Gate` - OpenAPI/generated client parity

Gate `DF-MOD-01/11` yêu cầu backend OpenAPI và frontend generated client đồng bộ.

Kết quả kiểm tra:

```text
cmp -s device_farm/swagger/openapi.json front-end/generate/openapi.json
openapi_cmp_exit=1
```

Ticket nên tách:

- `01E-openapi-client-parity`
- `11F-generated-client-regeneration-and-proxy-audit`

## Automated Smoke Results

### Backend targeted core suite

Command:

```bash
cd device_farm
uv run pytest tests/test_core_security.py tests/test_auth_security.py tests/test_hardening_regressions.py tests/test_device_groups.py tests/test_device_groups_routes_n2n.py tests/test_relay_agents_routes.py tests/test_agent_reconnect.py tests/test_campaign_dispatch_n2n.py tests/test_execution_integration.py tests/test_scheduler.py tests/test_schedules_routes_n2n.py tests/test_content_pipeline.py tests/test_content_routes_n2n.py tests/test_extraction_usecase.py tests/test_temporal_extract_save_contract.py tests/test_fb_crawl_stability.py tests/test_fb_extract_heuristics.py tests/test_fb_extract_progressive.py tests/test_fb_group_1h_comment_parent.py tests/test_template_comment_dedupe_contract.py
```

Result:

```text
361 collected
340 passed
6 skipped
15 failed
```

Failure groups:

- `test_scheduler.py::TestSchedulerEngine::test_check_due_schedules_dispatches`
  patches `get_due_schedules`, while implementation now calls
  `claim_due_schedules`. This looks like stale test or changed contract, but it
  still blocks green automation.
- `test_content_routes_n2n.py::test_legacy_async_export_endpoints_removed`
  expects `404`, actual is `405`.
- Facebook parser/contract failures in `test_fb_extract_heuristics.py` and
  `test_fb_extract_progressive.py`: badge parsing (`Quan tâm`,
  `visual storyteller`), `tasks.fb_extract.time` patch target missing,
  comment author extraction mismatch.
- `test_template_comment_dedupe_contract.py` expects
  `device_farm/scenarios/fb_group_crawl.json`, but file is absent.

### Agent boot / relay suite

Command:

```bash
cd agent-boot
uv run pytest relay/tests
```

Result:

```text
63 passed
4 warnings
```

### Frontend lint and typecheck

Command:

```bash
cd front-end
pnpm run lint:strict
pnpm exec tsc --noEmit
```

Result:

- `lint:strict`: failed with `15 errors`, `56 warnings`.
- `tsc --noEmit`: failed.

Representative failures:

- Unused imports in campaign/device/scenario flow components.
- Unresolved modules: `react-device-mockup`, `jmuxer`,
  `@flowgram.ai/fixed-layout-editor`.
- Stale Next generated type for missing `crawl-jobs` page.
- Implicit `any` in scenario flow editor callbacks.

## Release Position

Có thể tiếp tục theo hướng:

1. Khóa scope core như hiện tại.
2. Tạo fix tickets tối thiểu cho các P0/P1 gate ở trên.
3. Chạy lại automated smoke đến khi không còn failure liên quan release gate.
4. Chạy UAT-01..04 trên staging/canary với device thật.
5. Chỉ sign-off khi có evidence bundle cho UAT và không còn P0/P1 ở `R1..R6`.

Không nên làm trong core release này:

- Không mở TikTok/Threads/Instagram L2.
- Không biến `DF-MOD-10`/MCP/L3 thành release gate.
- Không refactor lớn export, BI, SSO, vault, HA hoặc frontend redesign.
- Không rename canonical `fb_tap_comment_button` nếu chưa cần cho pilot; có thể
  giữ legacy `tap_fb_comment_button` nhưng phải tránh claim sai trong docs/UI.

## Next Ticket Order

1. `08C/06B-facebook-content-type-normalization`
2. `07E-legacy-fallback-audit`
3. `05D-temporal-fallback-contract-decision`
4. `01E/11F-openapi-client-parity`
5. `11G-frontend-build-lint-release-blockers`
6. `08E-facebook-parser-contract-regression`
7. `UAT-01..04-evidence-bundle`

