# DF-T-06-005 — AI vision extraction pipeline (OpenAI + Gemini)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-005 |
| **Title** | AI vision extraction pipeline (OpenAI + Gemini) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P3 |
| **Story Points** | 8 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `layer:infra`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L2`, `risk:performance` |
| **Truy vết — FR refs** | FR-06-03, FR-06-14 |
| **Truy vết — UC refs** | UC-06-03, UC-06-11, UC-06-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

AI vision là engine bổ sung cho phần UI mà hierarchy + OCR không xử lý nổi — UI thay đổi liên tục, layout phức tạp, hoặc dữ liệu nằm trong cấu trúc visual. Engine gọi OpenAI Vision (GPT-4o / GPT-4.1) hoặc Gemini Pro Vision với screenshot kèm prompt mô tả cấu trúc cần extract. Đặc tả module cam kết: provider secret KHÔNG persist vào content/artifact; mỗi call ghi nhận provider, model, ước tính token để dashboard cost theo dõi (xem DF-T-06-013).

Đây là engine "đắt" nhất — chi phí tăng nhanh nếu dùng diện rộng. Vì thế ticket này phải có timeout, fallback, budget guard nhẹ ở tầng engine (chi tiết guard ở DF-T-06-013).

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** gửi screenshot kèm prompt mô tả schema và nhận về object JSON đã parse
> **Để** xử lý các UI mà hierarchy hoặc OCR không trích xuất nổi (ví dụ feed phức tạp đổi A/B liên tục)

Persona phụ: Social Data Operator (gián tiếp — không mất bài khi UI thay đổi).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `AIVisionService.extract(image, prompt, expected_schema, provider, model)` trả `AIVisionResult(data, raw_response, provider, model, latency_ms, est_tokens_in, est_tokens_out, est_cost_usd)` — trace FR-06-03.
- Hệ thống PHẢI hỗ trợ ít nhất 2 provider: OpenAI (mặc định `gpt-4o`) và Google Gemini (mặc định `gemini-1.5-pro-vision`).
- Hệ thống PHẢI parse response thành JSON theo `expected_schema`; nếu provider trả non-JSON, áp 1 lần re-prompt "Please return strictly JSON matching schema X"; lần 2 fail → raise `AIVisionParseError`.
- Hệ thống PHẢI KHÔNG persist provider API key vào content record, artifact, hay raw_data — trace FR-06-14.
- Hệ thống PHẢI scrub provider response trước khi log: không ghi raw response chứa secret pattern.
- Hệ thống PHẢI emit event `ai_vision_call_completed` với provider, model, est_tokens, latency, success — tiêu thụ ở DF-T-06-013.
- Hệ thống PHẢI hỗ trợ timeout 60 s và retry với exponential backoff (max 2 retry) cho rate limit error 429.
- Hệ thống NÊN cho phép fallback provider: khi OpenAI rate limit → tự chuyển Gemini nếu config cho phép.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Extract một post Facebook qua AI vision**

```
Given screenshot post Facebook 1080×2400 và prompt "Extract author_name, text_content, like_count, comment_count thành JSON"
And provider="openai", model="gpt-4o"
When AIVisionService.extract được gọi
Then result.data có 4 trường tương ứng (cho phép thiếu 1 trường nếu UI không có)
And result.provider="openai", result.model="gpt-4o"
And result.est_tokens_in > 0, result.est_tokens_out > 0
And result.latency_ms < 8000 (đo p50)
```

**AC-2: Provider không persist secret**

```
Given AI vision call hoàn tất
When kiểm tra DB content_items, raw_data, execution_artifacts, log
Then không có chuỗi match pattern "sk-[A-Za-z0-9]{20,}" (OpenAI) hay "AIzaSy[A-Za-z0-9_-]{30,}" (Gemini)
And audit log có entry ghi "ai_vision_call" nhưng KHÔNG có authorization header
```

**AC-3: Rate limit retry**

```
Given provider trả 429 (rate limited) lần 1
When AIVisionService chạy
Then retry sau backoff 2 s
And nếu lần 2 OK → trả result thành công
And metric `ai_vision_rate_limit_retry_total` tăng 1
```

**AC-4: Response không phải JSON hợp lệ**

```
Given provider trả response chứa "Sure! Here is the JSON: ..." kèm explanation
When parse với expected_schema
Then service re-prompt với chỉ thị strict JSON
And nếu lần 2 vẫn fail → raise AIVisionParseError(code="INVALID_JSON", raw_response_excerpt)
And event ghi nhận "ai_vision_parse_failed"
```

**AC-5: Provider outage fallback**

```
Given config fallback chain = [openai, gemini]
And OpenAI trả 503 hoặc connection timeout
When AIVisionService.extract chạy
Then service tự retry với gemini sau khi exhaust retry OpenAI
And result.provider = "gemini" (ghi rõ provider thực sự đã trả)
And event "ai_vision_provider_fallback" emit
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm budget enforcement / hard cap — đó là DF-T-06-013.
- KHÔNG bao gồm dashboard cost — đó là DF-T-06-013.
- KHÔNG bao gồm provider thứ 3 (Anthropic, Mistral) — câu hỏi mở trong đặc tả module, sẽ làm sau nếu có demand.
- KHÔNG bao gồm prompt template library — đó là việc của Automation Builder.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Interface `AIVisionProvider` với 2 implementation: `OpenAIVisionProvider`, `GeminiVisionProvider`.
- [ ] `AIVisionService` chọn provider theo config, gọi `extract`, parse JSON, fallback chain.
- [ ] Retry logic với backoff cho 429 / 503 / connection error.
- [ ] Token estimator (lib `tiktoken` cho OpenAI; Gemini có sẵn count_tokens API).
- [ ] Secret scrubber trước khi log.

**Contract / API** (`layer:contract`)

- [ ] Dataclass `AIVisionResult` (data, provider, model, latency, tokens, cost).
- [ ] Mã lỗi `AIVisionParseError`, `AIVisionProviderError`, `AIVisionTimeout`.
- [ ] Event `ai_vision_call_completed` schema.

**Infra / DevOps** (`layer:infra`)

- [ ] Secret config OpenAI key, Gemini key qua secret manager (env injection).
- [ ] Healthcheck endpoint `/health/ai-vision` ping cả 2 provider mỗi 5 phút (không tính chi phí).
- [ ] Default rate limit per organization 10 req/s.

**Documentation** (`layer:docs`)

- [ ] Hướng dẫn Automation Builder dùng AI vision: khi nào, prompt mẫu, cách giảm chi phí.
- [ ] Cảnh báo budget runaway.

**Test** (`layer:test`)

- [ ] Mock provider response (success, 429, 503, non-JSON).
- [ ] Integration test với sandbox/dev key (limit budget).
- [ ] Secret scrub test: inject dummy "sk-test" trong response và xác nhận không leak vào log.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-005-01 | Positive | OpenAI key valid; screenshot post FB | Extract với prompt schema chuẩn | Result.data đủ field; latency < 8s; tokens > 0 |
| TC-DF-T-06-005-02 | Positive | Gemini key valid; screenshot TikTok video | Extract với provider=gemini | Result.data chuẩn; provider="gemini" |
| TC-DF-T-06-005-03 | Negative | OpenAI key sai | Extract | `AIVisionProviderError(AUTH_FAILED)`; log không chứa key |
| TC-DF-T-06-005-04 | Negative | Provider trả response không phải JSON kể cả lần re-prompt 2 | Extract | `AIVisionParseError`; event "parse_failed"; raw_response excerpt < 200 ký tự |
| TC-DF-T-06-005-05 | Edge | Provider rate limit 429 liên tục 3 lần | Extract | Sau 2 retry vẫn fail → fallback chain → gemini; nếu cả 2 fail → `AIVisionProviderError` |
| TC-DF-T-06-005-06 | Edge | Image 20 MB (oversize) | Extract | Resize xuống < 8 MB trước khi gửi; warning log; không crash |
| TC-DF-T-06-005-07 | Edge | Audit scan log/db sau khi chạy 1000 call | grep pattern secret | 0 match — pass FR-06-14 |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-003 (cần image input).

**Chặn:** DF-T-06-007, DF-T-06-009, DF-T-06-013, DF-T-06-014, DF-T-06-015.

**Phụ thuộc giữa Epic:** Không trực tiếp; nhưng cost tracking sẽ sync với DF-E-09 (Notifications & Analytics) khi cảnh báo budget vượt ngưỡng.

**Rủi ro:**

- **Cost runaway:** giảm thiểu: DF-T-06-013 budget guard; default rate limit 10 req/s.
- **Provider outage chéo (cả OpenAI + Gemini down):** giảm thiểu: fallback chain; metric SLO < 1% scenario fail do AI vision outage.
- **Token estimate sai vì model đổi pricing:** giảm thiểu: cron job sync giá mỗi tuần; tài liệu cost là ước lượng.

**Phụ thuộc bên ngoài:** OpenAI API (v1 vision), Google Gemini API.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Test với mock + sandbox key thật pass.
- [ ] Audit scan secret trên DB + log = 0 match.
- [ ] Latency p50 < 8 s đo trên fixture.
- [ ] `docs/modules/content.md` viết section AI vision.
- [ ] Telemetry: `ai_vision_call_total{provider, model, result}`, `ai_vision_latency_ms`, `ai_vision_tokens_total`, `ai_vision_cost_usd_total`.
- [ ] Code review ≥ 1 approve owner module + 1 approve security reviewer (vì secret handling).
- [ ] Changelog + release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.2, §6 FR-06-03, FR-06-14](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Ma trận năng lực:** [03-capability-matrix.md §4.3 "AI vision extraction"](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** Automation Builder (§3.2).
- **Thuật ngữ:** [AI vision](../../official_docs/00-glossary.md).
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — AI vision budget guardrail.
