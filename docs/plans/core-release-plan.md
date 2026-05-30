# Kế hoạch Core Release

Status: active
Last audited: 2026-05-25

Tài liệu này ghi lại phạm vi, thứ tự release, mục tiêu nghiệm thu và cách chia
ticket cho **core release** của Device Farm. Đây là plan hành động trong
`docs/plans`, không thay thế module contract trong `docs/official_docs`.

## Phạm vi

In-scope:

- `DF-MOD-01` Nền tảng & Bảo mật truy cập
- `DF-MOD-02` Thiết bị & Mặt phẳng điều khiển
- `DF-MOD-03` Agent Boot & Relay
- `DF-MOD-04` Campaign, Scenario & Execution
- `DF-MOD-05` Scheduling
- `DF-MOD-06` Content Extraction & Artifacts
- `DF-MOD-07` Accounts & Account Groups
- `DF-MOD-08` Social Platform Extensions, chỉ trong phạm vi **Facebook L2 Active**
- `DF-MOD-09` Notifications & Analytics
- `DF-MOD-11` Frontend & Dashboard

Out-of-scope cho core release:

- `DF-MOD-10` MCP Agent Tools
- Toàn bộ L3 / MCP / AI-agent production claim
- TikTok, Threads, Instagram ở mức L2
- SSO, vault-backed credentials, HA multi-instance backend, export refactor hoàn
  chỉnh, proactive alerting, BI dashboard, production-grade relay mTLS

Outcome mục tiêu:

- Pilot Facebook L2 end-to-end cho 1 organization.
- 20-50 thiết bị Android trên một cụm host canary.
- 2-3 scenario Facebook chạy lặp lại được.
- Luồng campaign, schedule, account, content, artifact, notification và dashboard
  nối được với nhau, có traceability đầy đủ.

## Chỉ số nghiệm thu cấp release

| Chỉ số | Mục tiêu |
|---|---:|
| Thiết bị xuất hiện online sau pair/bootstrap | < 90 giây |
| Device online rate trong pilot window | >= 99% |
| Execution đạt terminal state | >= 99% |
| Scenario success trên các flow Facebook đã chốt | >= 95% |
| Content item truy vết được tới campaign/scenario/execution/device/account | >= 99% |
| Schedule fail tạo notification | 100% |
| Notification deep link mở đúng tài nguyên | 100% |
| OpenAPI spec và generated client đồng bộ | 100% tại release gate |

## Thứ tự release

| Wave | Module | Mục tiêu | Exit gate |
|---|---|---|---|
| `W0` | Release baseline | Logging tối thiểu, route/client parity, pilot runbook, quyết định mạng private cho relay | Release owner sign-off scope freeze và rollback plan |
| `W1` | `DF-MOD-01`, `03`, `02` | Auth, relay, device inventory, reserve/control/stream foundation | Manual device UAT pass |
| `W2` | `DF-MOD-07`, `04`, `06`, `08` Facebook only | Account intent, scenario execution, content/artifact, Facebook L2 | Facebook campaign UAT pass |
| `W3` | `DF-MOD-05`, `09`, `11` | Schedule, notification/activity, dashboard journeys | Scheduled campaign UAT pass |
| `RC` | Toàn bộ core scope | Release candidate end-to-end | Go/no-go checklist pass |

Critical path:

```text
DF-MOD-01 -> DF-MOD-03 -> DF-MOD-02 -> DF-MOD-04
          -> DF-MOD-08 Facebook L2 -> DF-MOD-05 -> DF-MOD-09 -> DF-MOD-11
```

Nhánh song song:

- `DF-MOD-07` có thể bắt đầu sau `DF-MOD-01`, không cần đợi `DF-MOD-02/03`,
  nhưng phải sẵn sàng trước UAT campaign.
- `DF-MOD-06` bắt đầu khi contract `DF-MOD-02/04` ổn định.
- `DF-MOD-11` có thể làm shell sớm, nhưng không vào RC nếu còn parity gap không
  có owner ở các flow core.

## Breakdown theo module

### `DF-MOD-01` - Nền tảng & Bảo mật truy cập

Mục tiêu:

- Tạo lớp runtime, auth boundary, multi-tenancy, WebSocket entrypoint và kỷ luật
  API contract cho toàn bộ module phía trên.

Nghiệm thu:

- Login và refresh token hoạt động.
- Route `public`, `user-auth`, `admin-auth`, `device-auth` từ chối caller không
  hợp lệ.
- Không truy cập chéo tenant với campaign, content, account, schedule,
  notification.
- WebSocket từ chối JWT thiếu hoặc sai.
- Dashboard thấy trạng thái safe mode.
- OpenAPI spec và generated client đồng bộ.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `01A-auth-boundary-jwt` | Login, refresh, route auth boundary | Negative auth tests pass |
| `01B-org-membership` | Organization/member model và tenant isolation | Cross-tenant tests pass |
| `01C-device-auth` | Device key auth cho runtime API | Device key sai bị reject |
| `01D-safe-mode-status` | Safe-mode route/status cho dashboard | DB-off behavior rõ |
| `01E-openapi-client-parity` | OpenAPI và generated client parity | Client regen gate pass |

### `DF-MOD-03` - Agent Boot & Relay

Mục tiêu:

- Làm agent chạy trên host vật lý đủ ổn định để điều khiển canary fleet.

Nghiệm thu:

- Agent đăng ký backend và hiển thị online.
- Device attach được bootstrap tới `ONLINE`.
- Heartbeat cập nhật đúng chu kỳ.
- Reconnect phục hồi sau gián đoạn mạng ngắn.
- Ưu tiên USB hơn WiFi khi có cả hai.
- Dashboard hiển thị trạng thái relay và device.
- Relay chạy trong overlay/private network hoặc sau TLS reverse proxy; không expose
  gRPC insecure ra public network.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `03A-bootstrap-watch` | Bootstrap u2/ATX và watch attach/detach | Device mới đạt ONLINE |
| `03B-heartbeat-reconnect` | Heartbeat và reconnect loop | Agent hồi phục sau short drop |
| `03C-transport-baseline` | WebSocket/gRPC relay baseline | Command parity smoke pass |
| `03D-device-fsm-usb-first` | Device FSM và USB priority | FSM transition thấy được |
| `03E-relay-ops-view` | Relay agent operations view | Relay dashboard smoke pass |

### `DF-MOD-02` - Thiết bị & Mặt phẳng điều khiển

Mục tiêu:

- Cung cấp primitive L1 cho manual control và automation.

Nghiệm thu:

- Device inventory liệt kê đúng thiết bị theo organization.
- Reserve tạo owner rõ ràng và chặn session xung đột.
- Release trả device về pool.
- Gesture, hierarchy, screenshot, stream hoạt động trong session được sở hữu.
- Device group fan-out trả kết quả per-device.
- Per-device context override sẵn sàng cho execution.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `02A-pairing-inventory` | Pair/list device inventory | Device hiện trên dashboard |
| `02B-session-reserve-release` | Reserve/release và owner state | Double-reserve bị reject |
| `02C-realtime-primitives` | Gesture, hierarchy, screenshot, stream | Manual control UAT pass |
| `02D-device-groups-fanout` | Device groups và fan-out helper | Partial failure báo per-device |
| `02E-per-device-context` | Per-device override support | Effective config test pass |

### `DF-MOD-07` - Accounts & Account Groups

Mục tiêu:

- Resolve account social theo intent tường minh của scenario, đồng thời giữ
  traceability account trong execution/content.

Nghiệm thu:

- Account CRUD và bulk import hoạt động.
- Account status loại account không hợp lệ khỏi round-robin.
- `device_accounts` và `account_groups` tách biệt.
- Scenario resolve được `account_id` cụ thể hoặc `account_group_id`.
- Scenario thiếu account intent bắt buộc phải fail rõ; core template không được
  âm thầm suy diễn primary account của device.
- Content và execution trace được account khi có intent.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `07A-account-model-import` | Account CRUD và bulk import | Import idempotent |
| `07B-device-account-linking` | Link `device_accounts` và primary marker | Xóa link không xóa account |
| `07C-account-group-round-robin` | Group membership và round-robin | Invalid account bị skip |
| `07D-dispatch-account-resolution` | Resolve account intent khi dispatch | Explicit intent resolve đúng |
| `07E-legacy-fallback-audit` | Audit/remove fallback khỏi core template | Không template core nào phụ thuộc fallback |

### `DF-MOD-04` - Campaign, Scenario & Execution

Mục tiêu:

- Thực thi authored scenario flow có thể đoán được, có checkpoint, artifact và DLQ.

Nghiệm thu:

- Scenario tuần tự và graph validate được.
- Variable resolution deterministic.
- Mặc định là stop-on-failure.
- `ignore_error`, `on_error`, retry phải explicit.
- Mỗi device có execution độc lập.
- Checkpoint và pre/post artifact được ghi.
- DLQ retry/close hoạt động.
- Pause, resume, cancel hoạt động nhưng không được hiểu là undo.
- Preview/session/campaign surface tuân thủ cùng semantics stop-on-failure ở core.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `04A-scenario-schema-validation` | Scenario step/graph/nested validation | Invalid schema bị reject |
| `04B-dispatch-runtime-resolution` | Dispatch và variable/account resolution | Effective config được log |
| `04C-execution-checkpoint` | Execution lifecycle và checkpoint | Restart/retry path an toàn |
| `04D-dlq-controls` | DLQ retry/close và pause/resume/cancel | Failure UAT pass |
| `04E-surface-parity` | Cross-surface error policy regression | Stop-on-failure nhất quán |

### `DF-MOD-06` - Content Extraction & Artifacts

Mục tiêu:

- Lưu content chuẩn hóa và artifact debug có traceability.

Nghiệm thu:

- Hierarchy và OCR extraction sẵn sàng cho pilot.
- AI vision là optional/bounded; không là core gate trừ khi scenario pilot phụ
  thuộc vào nó.
- `save_extraction` trong scenario và direct extraction đi qua cùng normalizer.
- Facebook content dùng content type `fb_post`, `fb_comment`.
- `parent_id` và `item_level` biểu diễn comment hierarchy.
- Content trace tới campaign, scenario, execution, device, collection và account
  khi có account intent.
- Artifact mở được từ execution detail.
- Secret provider AI không bị persist vào content/artifact.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `06A-engine-adapters` | Hierarchy/OCR/optional AI adapters | Engine smoke pass |
| `06B-normalizer-persistence` | Shared normalizer và content persistence | `fb_*` content được lưu |
| `06C-artifact-store-retrieval` | Screenshot/hierarchy artifact storage | Artifact mở bằng execution |
| `06D-query-traceability` | Collection/query và traceability | Breadcrumb đủ |
| `06E-dedupe-cost-policy` | Policy tạm cho dedupe và AI cost | Pilot risk được chấp nhận |

### `DF-MOD-08` - Social Platform Extensions, Facebook L2 Only

Mục tiêu:

- Release Facebook như capability L2 platform-specific duy nhất của core release.

Nghiệm thu:

- Strategy `fb_posts` và `fb_comments` hoạt động.
- `fb_post` và `fb_comment` persist đúng.
- Action mở comment context chạy qua scenario executor.
- Parser, persistence, frontend node/template và regression test tồn tại cho
  pilot path Facebook.
- Release note, UI, docs không claim TikTok/Threads/Instagram L2 Active.
- Canonical `fb_tap_comment_button` hoặc được support đầy đủ, hoặc bị ẩn; legacy
  `tap_fb_comment_button` vẫn tương thích với template đang chạy.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `08A-facebook-action-naming` | Quyết định/support legacy và canonical naming | Alias regression pass |
| `08B-facebook-parser-strategy` | Parser/strategy `fb_posts`, `fb_comments` | Parser tests pass |
| `08C-facebook-content-persistence` | Persistence `fb_post`, `fb_comment` | Parent-child content đúng |
| `08D-facebook-frontend-template` | Flow node và reference template | Template dispatch được |
| `08E-facebook-regression-pack` | Facebook L2 test/UAT pack | Campaign UAT pass |

### `DF-MOD-05` - Scheduling

Mục tiêu:

- Trigger campaign Facebook đã duyệt theo lịch và theo `run-now`, có history và
  link tới execution.

Nghiệm thu:

- Schedule create/update/toggle/delete hoạt động theo organization.
- Cron validation reject expression sai ở frontend và backend.
- `run-now` tạo schedule run nhưng không đổi lịch định kỳ.
- Schedule run history link tới child execution.
- Temporal-backed path là normal release path.
- Fallback, nếu có, phải được đánh dấu best-effort rõ ràng và không được trình bày
  như durable mode tương đương Temporal.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `05A-schedule-crud-cron` | CRUD và cron validation | FE/BE cron tests pass |
| `05B-trigger-history` | Temporal tick và run history | Scheduled run được tạo |
| `05C-run-now-deeplink` | Run-now và execution deep link | UAT deep link pass |
| `05D-fallback-marker` | Marker/banner cho fallback behavior | Fallback không silent |

### `DF-MOD-09` - Notifications & Analytics

Mục tiêu:

- Hiển thị hoạt động campaign/schedule/device qua notification, activity history
  và optional webhook.

Nghiệm thu:

- Event campaign dispatch/completed/failed/DLQ tạo notification và activity log.
- Schedule run fail tạo notification.
- Device online/offline event được phản ánh nếu nằm trong core event scope.
- Unread count, mark-read, mark-all-read hoạt động.
- Deep link mở đúng tài nguyên hoặc hiển thị message rõ khi tài nguyên đã xóa.
- Webhook gửi một lần và lưu delivery result.
- Activity log append-style qua user API.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `09A-channel-crud` | Notification channel CRUD | Ownership đúng |
| `09B-inapp-unread` | In-app notification và unread count | Badge update đúng |
| `09C-activity-log` | Append-style activity log và filters | Activity UAT pass |
| `09D-webhook-delivery` | Webhook delivery và status record | Failure status thấy được |
| `09E-domain-event-contract` | Event contract từ campaign/schedule/device | Deep link hợp lệ |

### `DF-MOD-11` - Frontend & Dashboard

Mục tiêu:

- Cung cấp dashboard cho các core journey mà không bị API drift.

Nghiệm thu:

- App shell, auth state, navigation và locale routing hoạt động.
- Generated client là default cho route backend ổn định.
- Next API proxy trong core flow phải có owner, lý do tồn tại và issue gỡ bỏ.
- Devices và relay pages phục vụ fleet UAT.
- Scenario flow editor load/save scenario Facebook đã duyệt.
- Campaign page dispatch được và xem được execution/DLQ.
- Accounts, content, schedules, notifications, activity pages hoàn thành task core.

Ticket gợi ý:

| Ticket | Kết quả cần giao | Gate |
|---|---|---|
| `11A-app-shell-auth-i18n` | Dashboard shell, auth, locale routing | Login route smoke pass |
| `11B-generated-client-parity` | Generated client và proxy audit | Không có proxy thiếu tracking |
| `11C-devices-relay-views` | Devices/live view/relay dashboards | Fleet UAT pass |
| `11D-scenario-flow-editor` | Load/save graph cho Facebook scenario | Template save và chạy được |
| `11E-core-domain-pages` | Campaign/content/schedule/account/notification/activity pages | E2E UAT pass |

## Gate liên module

| Gate | Module | Nghiệm thu |
|---|---|---|
| `G1 Foundation` | `01`, `03`, `02` | Auth, relay, reserve/control/stream smoke pass; không có session ownership ambiguity |
| `G2 Execution` | `04`, `07` | Stop-on-failure và explicit account intent pass; không core template nào phụ thuộc primary account fallback |
| `G3 Facebook L2` | `06`, `08` | Facebook crawl lưu `fb_*`, mở artifact, trace về execution/device/account |
| `G4 Ops` | `05`, `09` | Scheduled run tạo execution, notification, activity log và deep link |
| `G5 RC` | `11` + all | UAT pass; OpenAPI/generated-client parity sign-off |

## UAT matrix

| UAT | Hành trình | Module |
|---|---|---|
| `UAT-01` | Manual device: login -> relay/device online -> reserve -> screenshot/hierarchy/stream -> release | `01`, `03`, `02`, `11` |
| `UAT-02` | Facebook campaign: account intent -> dispatch -> extract `fb_posts/fb_comments` -> content/artifact -> DLQ nếu fail | `07`, `04`, `06`, `08`, `11` |
| `UAT-03` | Failure path: UI-gated step fail -> stop -> artifact -> DLQ -> retry/close | `04`, `06`, `09`, `11` |
| `UAT-04` | Scheduled campaign: schedule run-now -> execution -> notification unread -> activity log -> deep link | `05`, `04`, `09`, `11` |

Chi tiết QC nằm tại `docs/plans/core-release-qc-process.md`.

## Go / No-Go

Go khi:

- `UAT-01` tới `UAT-04` pass trên staging cho pilot organization.
- Không còn P0/P1 cho tenant isolation, double-reserve, content traceability hoặc
  notification deep link.
- OpenAPI/generated client parity đã sign-off.
- Release note ghi rõ: chỉ Facebook L2 Active; TikTok/Threads/Instagram L2 và MCP
  out-of-scope.
- Relay network exposure nằm trong private/controlled network.

No-go khi:

- Cross-tenant negative test fail.
- Device có thể bị double-reserve.
- Campaign failure thiếu DLQ hoặc artifact evidence.
- Facebook content lưu generic `post` hoặc `comment`.
- Schedule run không link được tới execution/notification.
- Core dashboard route vỡ vì client/proxy drift.

## Rollback và contingency

Rollback phải preserve hoặc restore được path sau:

```text
login -> reserve device -> dispatch Facebook scenario -> save content/artifact
      -> run schedule -> receive notification/deep link
```

Contingency:

- Relay unstable theo host: drain device group, block reserve mới trên host đó,
  giữ host khác hoạt động.
- Temporal/schedule unstable: disable schedule mới và `run-now`; giữ manual
  campaign history đọc được.
- Facebook L2 unstable: ẩn node/template mới, giữ template legacy alias-compatible,
  không claim Facebook L2 ra ngoài cho tới khi UAT pass lại.
- Webhook unstable: disable webhook channel, dùng in-app notification và activity
  log làm source of truth.
- Frontend parity vỡ: hide/flag UI route bị ảnh hưởng; không rollback backend nếu
  API backend khỏe và non-UI smoke pass.

## Risk cần theo dõi

| Risk | Module | Giảm thiểu |
|---|---|---|
| gRPC relay chưa TLS và relay key dùng chung | `03` | Bắt buộc private overlay/VPN hoặc TLS reverse proxy cho pilot |
| Error policy lệch giữa execution surface | `04` | Cross-surface regression cho stop-on-failure và explicit continue |
| Legacy account fallback vẫn được dùng | `07` | Audit core template; chỉ giữ compatibility flag nếu bắt buộc |
| Facebook canonical naming chưa fully implemented | `08` | Dùng legacy alias trong pilot nếu schema và FE chưa cùng support canonical |
| Scheduler fallback không durable | `05` | Temporal-first cho core; fallback phải đánh dấu best-effort |
| Dedup/export chưa hoàn chỉnh | `06` | Pilot qua dashboard/API query; không hứa production export |
| Notifications/Analytics/Relay client drift | `09`, `11` | Route-matrix audit và client regeneration trước RC |

## Việc cần làm ngay

- Chỉ định một release owner có quyền quyết định gate cuối.
- Tạo module epic và các ticket slice trong plan này.
- Mở 3 audit ticket trước RC: `SPG-001`, `SPG-002`, `SPG-007`.
- Đặt API freeze và generated-client regeneration trước `G5 RC`.
- Chốt policy cho `DF-MOD-03`: waiver có điều kiện private network hay blocker
  bắt buộc fix trong target environment.

## References

- Official module index: `docs/official_docs/modules/README.md`
- Product overview: `docs/official_docs/01-product-overview.md`
- Capability matrix: `docs/official_docs/03-capability-matrix.md`
- Roadmap and FAQ: `docs/official_docs/99-roadmap-and-faq.md`
- Facebook profile: `docs/official_docs/platforms/facebook.md`
- Existing platform gap plan: `docs/plans/social-platform-extension-gaps.md`
