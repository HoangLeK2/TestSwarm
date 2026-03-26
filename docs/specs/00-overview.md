# Device Farm v2.0 — Development Specs Overview

## Vision

Device Farm v2.0 huong toi mot nen tang automation toan dien cho thiet bi Android, ho tro:
- **Social Media Automation**: Tu dong hoa hanh vi tren Facebook, TikTok (luot feed, like, comment, follow)
- **Content Crawling & OCR**: Trich xuat noi dung tu man hinh thiet bi (bai viet, video, profile)
- **Fleet Management**: Quan ly va dieu phoi hang tram thiet bi dong thoi
- **Dashboard & Monitoring**: Giao dien web de quan ly, theo doi va phan tich

## Architecture Principles

- Mo rong scenario engine hien tai (26 step types) — khong viet lai
- Giu nguyen TaskQueue + Dispatcher pattern
- Database: them bang moi, khong sua bang cu
- Frontend: them page/component moi vao feature folders hien tai
- API: them router moi, mount vao FastAPI app

## Phase Map

| Phase | Version | Focus | Tickets |
|-------|---------|-------|---------|
| Phase 1 | v1.1 | Foundation | DF-001 → DF-004 |
| Phase 2 | v1.2 | Social Automation | DF-005 → DF-008 |
| Phase 3 | v1.3 | Content & Data | DF-009 → DF-012 |
| Phase 4 | v2.0 | Intelligence | DF-013 → DF-016 |

## Ticket Index

### Phase 1 — Foundation

| ID | Title | Priority | Effort | Dependencies |
|----|-------|----------|--------|--------------|
| DF-001 | Variable System & Parameterization | P0 | M | None |
| DF-002 | Conditional Logic & Loops | P0 | M | DF-001 |
| DF-003 | Flow Composition (Sub-scenarios) | P0 | S | DF-001 |
| DF-004 | Device Group & Tag Management | P1 | S | None |

### Phase 2 — Social Media Automation

| ID | Title | Priority | Effort | Dependencies |
|----|-------|----------|--------|--------------|
| DF-005 | Human Behavior Simulation Engine | P0 | M | DF-001, DF-002 |
| DF-006 | Social App Scenario Templates | P0 | L | DF-001 → DF-005 |
| DF-007 | Account & Profile Manager | P1 | L | DF-004 |
| DF-008 | Scheduler & Cron System | P0 | M | DF-004 |

### Phase 3 — Content & Data

| ID | Title | Priority | Effort | Dependencies |
|----|-------|----------|--------|--------------|
| DF-009 | OCR & Screen Text Extraction | P0 | L | None |
| DF-010 | Content Pipeline (Crawl → Store → Export) | P1 | XL | DF-009 |
| DF-011 | Screenshot Archive & Visual Log | P1 | M | None |
| DF-012 | Dashboard Analytics & Reporting | P1 | L | None |

### Phase 4 — Intelligence

| ID | Title | Priority | Effort | Dependencies |
|----|-------|----------|--------|--------------|
| DF-013 | Proxy & Network Config per Device | P1 | M | None |
| DF-014 | Notification & Alert System | P2 | M | None |
| DF-015 | AI Visual Assertions & Screen Verification | P1 | M | DF-009 |
| DF-016 | Auto-Recovery & Self-Healing Scenarios | P2 | L | DF-015 |

## Effort Scale

| Label | Estimate |
|-------|----------|
| XS | 1-2 ngay |
| S | 3-5 ngay |
| M | 1-2 tuan |
| L | 2-4 tuan |
| XL | 4-6 tuan |
