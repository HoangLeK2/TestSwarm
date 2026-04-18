# Plan Review — Issues Found

> Reviewed: 2026-04-16

---

## Critical Issues (Plan mô tả sai so với codebase thực tế)

### ❌ Phase 1 — Foundation

**1. `RedisConfig` đã tồn tại**
- Plan: "Add `RedisConfig` to `core/config.py`"
- Thực tế: `services/redis_store.py` đã import `from core.config import RedisConfig` → config đã có
- Fix: Bỏ bước này khỏi Phase 1. Chỉ cần đảm bảo Redis enabled trong `.env`

**2. `ExecutionDLQ` table đã có sẵn**
- Plan: "Create `api/routes/admin.py` for DLQ"
- Thực tế: `db/models/execution_dlq.py` đã tồn tại với full model (`ExecutionDLQ`, retry_count, status, last_attempt_at). Comment trong file đã ghi "Use the API: GET /api/executions/dlq, POST /api/executions/dlq/{id}/retry"
- Fix: DLQ **đã được thiết kế** — chỉ cần wiring Redis task queue vào `ExecutionDLQ` thay vì Redis list riêng

**3. `redis_store.py` đã có client**
- Plan mô tả Redis client cần tạo mới từ đầu
- Thực tế: `services/redis_store.py` có sẵn `init()`, `client()`, `key()` với prefix
- Fix: Dùng `redis_store.client()` thay vì tạo mới trong `RedisTaskQueue`

---

### ❌ Phase 2 — Anti-Detection

**4. `db/models/account.py` đã rất đầy đủ**
- Plan: "Create db/models/account.py" với model đơn giản
- Thực tế: Model hiện có ĐẦY ĐỦ hơn plan:
  - `cooldown_until`, `status` (active/cooldown/banned/disabled)
  - `usage_today_minutes`, `total_usage_minutes`, `usage_reset_date`
  - `DeviceAccount` join table (device ↔ account many-to-many)
  - `proxy_id` (chuẩn bị cho proxy pool tương lai)
  - Fernet encryption cho password
- Fix: Xóa bước "create account model" — đã xong

**5. `services/account_manager.py` đã cover Account lifecycle**
- Plan: "Create `services/account_pool.py`" với logic cooldown/rotation
- Thực tế: `account_manager.py` đã có:
  - `start_account_usage()` / `end_account_usage()` — tracking usage
  - `check_and_reset_cooldowns()` — background reset
  - `reset_daily_usage()` — midnight reset
  - Configurable qua env: `ACCOUNT_DAILY_USAGE_LIMIT`, `ACCOUNT_COOLDOWN_MINUTES`
- Fix: Không cần `account_pool.py`. Chỉ cần viết `get_available_account(platform)` query vào `db/crud/account.py`

**6. Rate limiter dùng Redis nhưng không check `redis_store.enabled()`**
- `services/rate_limiter.py` plan dùng Redis trực tiếp
- Nếu Redis disabled, sẽ crash
- Fix: Wrap với `if not redis_store.enabled(): return True` (allow all khi không có Redis)

---

### ❌ Phase 5 — Scale & Monitoring

**7. `deduped_count` không có dữ liệu**
- Plan: `crud.content.count_deduped_by_execution(db, id)`
- Thực tế: Dedup xảy ra tại `content_store.save()` — nếu item bị skip (duplicate), nó không được ghi vào DB. Không có cách nào count deduped items từ DB vì chúng không được lưu.
- Fix: Track dedup count trong `Execution.meta` khi skip (tương tự LLM fallback counter). Hoặc bỏ `deduped_skipped` khỏi stats API.

**8. Bloom filter cần RedisStack nhưng phase 1 dùng Redis thường**
- Phase 1 setup Redis, Phase 5 cần RedisStack (khác image)
- Nếu switch image từ `redis:alpine` → `redis/redis-stack`, cần migrate dữ liệu Redis
- Fix: Nên quyết định dùng RedisStack từ đầu (Phase 1), không phải Phase 5

**9. `content_changes` table dùng `hashlib.sha256` trong ChangeDetector**
- Phase 0 đã quyết định bỏ SHA256 → dùng `xxhash`
- `change_detector.py` trong plan vẫn dùng `hashlib.sha256`
- Fix: Dùng `xxhash.xxh64` nhất quán

---

## Minor Issues

### ⚠️ Phase 0

**10. Files table còn sót "Tesseract fallback"**
- `runtime/extraction/ocr_engine.py` | "PaddleOCR primary + Tesseract fallback" — đã quyết định bỏ Tesseract
- Fix: Update dòng này thành "Rewrite với PaddleOCR, xóa pytesseract"

**11. `orjson.dumps()` trả bytes, không phải str**
- Redis `zadd` trong Phase 1 dùng `json.dumps` (str). Khi Phase 0 switch sang `orjson`, `zadd({payload: score})` sẽ nhận bytes key
- Redis sorted set member phải là str hoặc bytes — cả 2 đều OK với redis-py
- Fix: Nhất quán dùng bytes hoặc decode: `orjson.dumps(task).decode()`

### ⚠️ Phase 1

**12. Checkpoint column conflict**
- Plan: "Add `checkpoint_step INT DEFAULT 0` to `executions`"
- `Execution` model đã có `meta: JSON` — có thể lưu checkpoint vào đó thay vì thêm column
- Nhưng `meta` không indexed → query chậm nếu cần filter by checkpoint
- Fix: Vẫn nên thêm column riêng `checkpoint_step` cho performance

**13. `task_id` column trong executions**
- Plan thêm `task_id VARCHAR(36)` vào `executions`
- Nhưng `ExecutionDLQ` đã track `execution_id` + `device_serial` — không cần `task_id` trên `Execution`
- Fix: Lưu `task_id` trong `Execution.meta["task_id"]` thay vì column riêng

### ⚠️ Plan.md — Executive Summary lỗi thời

**14. Executive Summary vẫn đề cập 6 gaps, bao gồm "Web crawling layer"**
- Web crawling đã bỏ ở Phase 6
- Architecture Target diagram vẫn có `[Prometheus Metrics]`, `[Grafana Dashboard]`, `[Crawl4AI Web Layer]`
- Fix: Update Executive Summary + Architecture diagram

---

## Verdict theo Phase

| Phase | Tình trạng | Action |
|---|---|---|
| 0 — Deps | ✅ Mostly OK | Fix minor: table text, orjson bytes |
| 1 — Foundation | ⚠️ Cần chỉnh | Bỏ `RedisConfig` (đã có); wire DLQ vào `ExecutionDLQ` sẵn; dùng `redis_store.client()` |
| 2 — Anti-Detection | ❌ Cần refactor lớn | Bỏ "create account model/crud"; dùng `account_manager.py` sẵn; viết `get_available_account()` thay `AccountPool` mới |
| 3 — Multi-Platform | ✅ OK | Không conflict |
| 4 — LLM Universal | ✅ OK | Không conflict |
| 5 — Scale/Monitoring | ⚠️ Cần chỉnh | Switch RedisStack từ Phase 1; fix dedup counter; fix xxhash trong ChangeDetector |
| plan.md | ⚠️ Stale | Executive Summary + Architecture diagram cần update |
