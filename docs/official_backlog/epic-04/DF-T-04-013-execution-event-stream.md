# DF-T-04-013 — Execution event stream

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-013 |
| **Title** | Execution event stream (domain events + subscribe API) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `layer:infra`, `type:feature` |
| **Truy vết — FR refs** | FR-04-08 (event-driven downstream), FR-04-19 (chi tiết fail) |
| **Truy vết — UC refs** | UC-04-08, UC-04-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-31 |

## 2. Bối cảnh nghiệp vụ

Module Campaign tạo ra nhiều "biến cố nghiệp vụ": execution started, step started, step finished, step failed, execution completed, DLQ opened. Module 09 (Notifications & Analytics) và Module 11 (Frontend live update) cần subscribe những event này. Hiện tại team đang gọi service trực tiếp gây coupling cao.

Ticket này thiết lập **execution event stream**: schema event nhất quán, channel publish (Kafka/NATS/internal bus), API server-sent events (SSE) hoặc WebSocket cho frontend, snapshot endpoint cho history. Đây là spine event mà DF-E-05, 9, 11 đều dựa vào.

P1, SP 5. Sau khi DF-T-04-010 có execution runtime cơ bản.

## 3. Câu chuyện người dùng

> **Là** developer DF-E-09 / 11
> **Tôi muốn** subscribe event execution và step để build notification và live dashboard
> **Để** không phải poll DB và team có một spine event nhất quán cho mọi consumer

Persona phụ: Social Data Operator (tiêu thụ live update gián tiếp qua UI).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI publish event với schema chuẩn cho mọi state transition execution: `execution.created`, `execution.started`, `execution.completed`, `execution.failed`, `execution.cancelled`, `execution.dlq.opened`, `execution.dlq.replayed`, `execution.dlq.closed`.
- Hệ thống PHẢI publish event step-level: `step.started`, `step.completed`, `step.failed`, `step.retried`.
- Mỗi event PHẢI có: `event_id` (UUID), `event_type`, `occurred_at`, `organization_id`, `campaign_id`, `execution_id`, `step_id` (nếu có), `payload` (specific per event type), `schema_version`.
- Hệ thống PHẢI publish vào broker bền (Kafka hoặc NATS JetStream) — at-least-once delivery.
- Hệ thống PHẢI cung cấp endpoint SSE `GET /executions/{id}/events/stream` cho frontend subscribe live.
- Hệ thống PHẢI cung cấp `GET /executions/{id}/events?since=<event_id>` để consumer catch-up sau disconnect.
- Hệ thống PHẢI tagging event để cross-epic consumer filter dễ (vd DF-E-09 chỉ cần execution.dlq.*).
- Hệ thống PHẢI đảm bảo event publish atomic với DB write (outbox pattern).
- Hệ thống PHẢI persist event trong outbox/event store ≥ 30 ngày cho replay.
- Hệ thống NÊN cung cấp dead-letter cho event consumer (DLQ event riêng).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Lifecycle event đầy đủ một execution luồng thành công**

```
Given execution E chạy 3 step thành công, completed
When subscribe broker
Then thấy events theo order:
  1. execution.created
  2. execution.started
  3. step.started (step1)
  4. step.completed (step1)
  5. step.started (step2)
  6. step.completed (step2)
  7. step.started (step3)
  8. step.completed (step3)
  9. execution.completed
And mỗi event có event_id duy nhất, occurred_at monotonic
```

**AC-2: Retry event**

```
Given step S retry max_attempts=3, 2 attempt fail rồi success
When listen
Then events: step.started → step.retried (reason, attempt=2) → step.retried (attempt=3) → step.completed
```

**AC-3: SSE subscribe live**

```
Given execution E đang chạy
When frontend connect GET /executions/E/events/stream
Then receive event ngay khi publish (latency < 2s)
And reconnect với Last-Event-ID resume từ event cuối nhận
```

**AC-4: Catch-up sau disconnect**

```
Given consumer disconnect lúc event 5, reconnect lúc event 10 phát ra
When GET /executions/E/events?since=5
Then nhận event 6-10 in order
```

**AC-5: At-least-once + idempotent consumer**

```
Given broker re-deliver event do consumer chưa ack
When consumer xử lý lần 2
Then consumer dùng event_id để dedupe — không double-process
And contract doc rõ "consumer phải idempotent"
```

**AC-6: Outbox atomic**

```
Given DB write execution.status=completed
When chưa publish event ra broker mà service crash
Then sau restart, outbox processor pickup row chưa published, publish lại
And không event nào bị mất
```

**AC-7: Cross-org event isolation**

```
Given execution E thuộc OrgA
When user OrgB connect SSE /executions/E/events/stream
Then 403 hoặc 404 (không leak), không event leak qua broker filter
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm event analytics aggregator — DF-E-09.
- KHÔNG bao gồm notification rule engine — DF-E-09.
- KHÔNG bao gồm complex event processing — ngoài scope.
- KHÔNG bao gồm frontend UI consume — DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [x] Event schema constants (typed).
- [x] EventPublisher service với outbox pattern.
- [x] Outbox poller (cron 1s).
- [x] SSE endpoint.
- [x] Catch-up endpoint với pagination by event_id.

**Contract / API** (`layer:contract`)

- [x] OpenAPI/AsyncAPI cho event schema (JSON Schema each event type).
- [x] Document at-least-once contract.

**Database / Migration** (`layer:db`)

- [x] Bảng `event_outbox` (id, event_id, event_type, payload, published_at, attempts).
- [x] Bảng `events_archive` cho 30-day retention.

**Infra / DevOps** (`layer:infra`)

- [x] Kafka topic / NATS subject naming: `df.execution.events.v1`.
- [ ] Consumer group cho DF-E-09 và DF-E-11.
- [x] Monitoring: lag metric.

**Documentation** (`layer:docs`)

- [x] Event catalogue: liệt kê mọi event type + payload schema + example.
- [x] Consumer guide.

**Test** (`layer:test`)

- [x] Unit test outbox atomicity.
- [x] Integration test publish + subscribe.
- [x] Test catch-up + re-delivery.
- [ ] Load test: 1000 event/s sustained.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-013-01 | Positive | Execution E 3 step happy | Run + subscribe | 9 event đúng order, payload đầy đủ |
| TC-DF-T-04-013-02 | Positive | Step retry 3 attempt | Run + subscribe | step.retried event với attempt counter |
| TC-DF-T-04-013-03 | Positive | SSE connect tới execution running | Connect | Event push trong < 2s từ publish |
| TC-DF-T-04-013-04 | Edge | Service crash giữa DB write và broker publish | Restart service | Outbox poll, publish lại, không event mất |
| TC-DF-T-04-013-05 | Edge | Consumer disconnect 30s rồi reconnect with Last-Event-ID | Reconnect | Resume từ event đó, không miss |
| TC-DF-T-04-013-06 | Negative | OrgB user subscribe execution OrgA | Connect SSE | 403/404, không leak event |
| TC-DF-T-04-013-07 | Edge | 1000 event/s load | Load test | p99 publish latency < 100ms, no drop |
| TC-DF-T-04-013-08 | Negative | Broker down 30s | Run execution | Outbox accumulate, sau khi broker up publish hết, không event lost |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-010 (execution runtime), DF-T-04-011 (retry event), DF-T-04-012 (DLQ event).

**Chặn:** DF-E-09 (notification, analytics consumer), DF-E-11 (live dashboard), DF-T-04-015 (audit log có thể subscribe event).

**Rủi ro:**

- **Outbox lag:** monitor lag, alert > 10s.
- **Broker backpressure:** consumer chậm gây accumulate → consumer group + autoscale.
- **Schema evolution phá consumer:** semver event payload + dùng tagged union + DF-E-09/11 phải pin schema_version.

**Phụ thuộc bên ngoài:** Kafka hoặc NATS JetStream.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Event catalogue published.
- [ ] AsyncAPI/JSON Schema cho mỗi event type.
- [ ] Load test 1000/s pass.
- [ ] Telemetry: outbox lag, publish latency, consumer lag.
- [ ] Code review ≥ 2 approve (campaigns + 1 dev DF-E-09 hoặc 11).
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-19, dependency lên Notifications.
- **Module 09:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md) — consumer.
- **Thuật ngữ:** Domain event.
