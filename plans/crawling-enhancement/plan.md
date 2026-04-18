# Plan: Production Crawling Enhancement for deviceFarmer

> Created: 2026-04-16  
> Branch: feat/upload-img → new branch `feat/crawling-production`  
> Research: `research_web_crawling_2025.md`

---

## Executive Summary

deviceFarmer already has solid foundations: scenario engine, Facebook XML parser, content storage, cron scheduling, and AI vision extraction. The system is **feature-complete for Facebook crawling on a single machine**.

To become production-grade and multi-platform, 5 capability gaps must be closed:

1. **Reliability** — Redis persistent queue (wiring existing `redis_store` + `ExecutionDLQ`), checkpoint/resume
2. **Anti-detection** — delay jitter, account rotation (extend existing `account_manager`), rate limiting
3. **Multi-platform** — Instagram, TikTok, LinkedIn parsers + platform auto-detection
4. **LLM-powered universal extraction** — schema-defined, no hard-coded selectors
5. **Scale & monitoring** — Bloom filter dedup (RedisStack), in-app stats, change detection

**Recommended execution order**: Phase 0 → 1 → 2 → (3 ∥ 4) → 5

---

## Architecture: Current vs Target

### Current
```
[Device Pool] → [In-Memory TaskQueue] → [Dispatcher] → [Scenario Engine]
                                                              ↓
                                              [FB XML Parser] → [PostgreSQL]
                                              [AI Vision]    → [R2/MinIO]
```

### Target
```
[Device Pool] ──────────────────────────────────────────────────────┐
[Account Pool (existing account_manager)] ──────────────────────────┤
                                                                     ↓
[Scheduler] → [Redis Queue] ──────→ [Dispatcher (multi-worker)]
              (redis_store)               ↓
                    ↓          [ExecutionDLQ (existing DB table)]
             [checkpoint/resume]          ↓
                                 [Scenario Engine + jitter]
                                          ↓
                          ┌──────────────┼──────────────┐
                    [FB Parser]  [IG Parser]  [TikTok Parser]
                          └──────────────┼──────────────┘
                                          ↓
                               [LLM Universal Extractor]
                               (fallback: schema-defined)
                                          ↓
                    [Bloom Filter Dedup (RedisStack)] → [PostgreSQL]
                                          ↓
                    [In-app Stats via Execution.meta + API]
```

---

## Phase Overview

| Phase | Name | Priority | Effort | Status |
|-------|------|----------|--------|--------|
| 0 | Dependency Upgrades | P0 | 1-2 days | Not started |
| 1 | Foundation (Reliability) | P0 | 3-4 days | Not started |
| 2 | Anti-Detection & Rate Limiting | P0 | 2-3 days | Not started |
| 3 | Multi-Platform Extraction | P1 | 4-5 days | Not started |
| 4 | LLM Universal Extractor | P1 | 3-4 days | Not started |
| 5 | Scale & Monitoring | P2 | 3-4 days | Not started |

**Total**: ~16-22 days for full implementation

---

## Dependency Graph

```
Phase 0 (Deps Upgrade)   ← làm đầu tiên, unblock mọi phase sau
    ↓
Phase 1 (Foundation)
    ↓
Phase 2 (Anti-Detection) ← bắt đầu sau khi Phase 1 Redis queue xong
    ↓
Phase 3 (Multi-Platform) ← độc lập; cần Phase 1 cho queue
Phase 4 (LLM Universal)  ← độc lập; cần Phase 3 parser interfaces
    ↓
Phase 5 (Monitoring)     ← cần Phases 1-4 xong
```

**Parallel groups**:
- Phase 3 + Phase 4 chạy song song sau Phase 1

---

## File Ownership Matrix

| File / Module | Ph.0 | Ph.1 | Ph.2 | Ph.3 | Ph.4 | Ph.5 |
|---|---|---|---|---|---|---|
| `pyproject.toml` | ✏️ | | | | | |
| `main.py` | ✏️ | | | | | |
| `runtime/extraction/ocr_engine.py` | ✏️ | | | | | |
| `services/content_store.py` | ✏️ | | | | ✏️ | |
| `tasks/fb_extract.py` | ✏️ | | | | | |
| `runtime/core/task_queue.py` | | ✏️ | | | | |
| `runtime/core/dispatcher.py` | | ✏️ | | | | |
| `tasks/scenario_task.py` | | ✏️ | ✏️ | | | |
| `services/rate_limiter.py` | | | ✏️ new | | | |
| `services/account_pool.py` | | | ✏️ new | | | |
| `tasks/ig_extract.py` | | | | ✏️ new | | |
| `tasks/tiktok_extract.py` | | | | ✏️ new | | |
| `tasks/linkedin_extract.py` | | | | ✏️ new | | |
| `tasks/platform_detector.py` | | | | ✏️ new | | |
| `tasks/scenario/steps/extraction.py` | | | | ✏️ | ✏️ | |
| `runtime/extraction/ai_vision.py` | | | | | ✏️ | |
| `monitoring/` | | | | | | ✏️ |

---

## Quick Wins (< 1 day each)

1. **Delay jitter** — Add `random.uniform(min_delay, max_delay)` between steps in `scenario_task.py` (30 min)
2. **Stop-if-no-new threshold** — Already exists in FB parser; expose config param in campaign (1 hr)
3. **Screenshot dedup** — Skip screenshot if previous hash matches (2 hr)
4. **Execution checkpoint log** — Write `last_step_index` to execution record after each step (2 hr)
5. **Per-platform collection auto-naming** — Auto-set collection from app package name (1 hr)
6. **dateparser timestamps** — Parse "5 phút trước" → datetime trong FB parser (1 hr) [Phase 0]
7. **loguru** — Thay stdlib logging, thêm file rotation (1 hr) [Phase 0]
8. **ORJSONResponse** — Thêm 1 dòng vào FastAPI app factory (15 min) [Phase 0]

---

## Phase Files

- [Phase 0: Dependency Upgrades](phase-00-deps-upgrade.md)
- [Phase 1: Foundation](phase-01-foundation.md)
- [Phase 2: Anti-Detection](phase-02-anti-detection.md)
- [Phase 3: Multi-Platform](phase-03-multi-platform.md)
- [Phase 4: LLM Universal Extractor](phase-04-llm-universal.md)
- [Phase 5: Scale & Monitoring](phase-05-scale-monitoring.md)
