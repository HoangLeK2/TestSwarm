# Plan: DB Schema Improvements — 6 điểm cải thiện

## Bối cảnh

Schema hiện tại 26 bảng, PostgreSQL async (asyncpg), SQLAlchemy 2.0+ ORM.
Đánh giá 7.5/10 — tốt cho MVP nhưng cần hardening trước khi scale.

## Phạm vi

6 điểm cải thiện từ senior DBA review:

1. **Data Integrity** — CHECK constraints, missing indexes, normalize serial length
2. **Status Enums** — Python StrEnum + DB CHECK cho tất cả status fields
3. **Multi-tenancy org-level** — Thêm `organization_id` vào core tables
4. **Scenario Versioning** — Snapshot scenario tại thời điểm execution
5. **Normalize JSON columns** — Tách JSON relationships ra bảng riêng
6. **Content Items refactor** — Giảm tải god table, thêm `user_id` trực tiếp

---

## Phase 1: Data Integrity — Missing Indexes & Constraints

**Migration:** `015_data_integrity.py`
**Risk:** Thấp — chỉ thêm indexes và constraints, không thay đổi data.
**Downtime:** Không — `CREATE INDEX CONCURRENTLY` trên PostgreSQL.

### 1.1 Missing FK Indexes

```sql
-- schedule.device_group_id — FK nhưng không index
CREATE INDEX CONCURRENTLY idx_schedules_device_group ON schedules(device_group_id);

-- scenario_templates.user_id — FK nhưng không index
CREATE INDEX CONCURRENTLY idx_scenario_templates_user ON scenario_templates(user_id);

-- content_collections.user_id — FK nhưng không index
CREATE INDEX CONCURRENTLY idx_content_collections_user ON content_collections(user_id);

-- content_exports.user_id — FK nhưng không index
CREATE INDEX CONCURRENTLY idx_content_exports_user ON content_exports(user_id);
```

### 1.2 Normalize device_serial length

```sql
-- execution_dlq.device_serial: String(64) → String(128) to match devices.serial
ALTER TABLE execution_dlq ALTER COLUMN device_serial TYPE VARCHAR(128);
```

### 1.3 Range CHECK constraints

```sql
ALTER TABLE devices ADD CONSTRAINT check_adb_port
  CHECK (adb_port >= 1 AND adb_port <= 65535);

ALTER TABLE content_items ADD CONSTRAINT check_item_level
  CHECK (item_level >= 0 AND item_level <= 2);
```

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `db/migrations/015_data_integrity.py` | Migration mới |
| `db/models/execution_dlq.py` | `String(64)` → `String(128)` |
| `db/models/schedule.py` | Thêm `index=True` vào `device_group_id` |
| `db/models/scenario_template.py` | Thêm `index=True` vào `user_id` |
| `db/models/content.py` | Thêm `index=True` vào `ContentCollection.user_id`, `ContentExport.user_id` |

---

## Phase 2: Status Enums — Python StrEnum + DB CHECK

**Migration:** `016_status_check_constraints.py`
**Risk:** Trung bình — cần verify data hiện tại không vi phạm constraints.
**Strategy:** Tạo Python StrEnum → dùng trong model + API validation → thêm DB CHECK.

### 2.1 Tạo `db/models/enums.py`

```python
from enum import StrEnum

class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"

class CampaignStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ExecutionResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"

class AccountStatus(StrEnum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    BANNED = "banned"
    DISABLED = "disabled"

class DLQStatus(StrEnum):
    PENDING = "pending"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"

class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"

class ScheduleTargetType(StrEnum):
    CAMPAIGN = "campaign"
    TEMPLATE = "template"
    FLEET = "fleet"

class McpSessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
```

### 2.2 DB CHECK constraints

```sql
ALTER TABLE users ADD CONSTRAINT check_user_role
  CHECK (role IN ('admin', 'operator'));

ALTER TABLE campaigns ADD CONSTRAINT check_campaign_status
  CHECK (status IN ('idle', 'running', 'paused', 'completed', 'failed'));

ALTER TABLE executions ADD CONSTRAINT check_execution_status
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));

ALTER TABLE execution_results ADD CONSTRAINT check_exec_result_status
  CHECK (status IN ('pending', 'running', 'passed', 'failed', 'error'));

ALTER TABLE accounts ADD CONSTRAINT check_account_status
  CHECK (status IN ('active', 'cooldown', 'banned', 'disabled'));

ALTER TABLE execution_dlq ADD CONSTRAINT check_dlq_status
  CHECK (status IN ('pending', 'retrying', 'resolved', 'dismissed'));

ALTER TABLE campaign_runs ADD CONSTRAINT check_campaign_run_status
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'partial'));

ALTER TABLE schedule_runs ADD CONSTRAINT check_schedule_run_status
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'partial'));

ALTER TABLE schedules ADD CONSTRAINT check_schedule_target_type
  CHECK (target_type IN ('campaign', 'template', 'fleet'));

ALTER TABLE mcp_sessions ADD CONSTRAINT check_mcp_status
  CHECK (status IN ('active', 'ended'));
```

### 2.3 Cập nhật models dùng StrEnum

Thay `default="idle"` → `default=CampaignStatus.IDLE` trong models.
Thay string literals trong CRUD → dùng enum values.

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `db/models/enums.py` | **Mới** — tất cả StrEnum definitions |
| `db/migrations/016_status_check_constraints.py` | Migration mới |
| `db/models/campaign.py` | Import + dùng CampaignStatus, RunStatus |
| `db/models/execution.py` | Import + dùng ExecutionStatus, ExecutionResultStatus |
| `db/models/account.py` | Import + dùng AccountStatus |
| `db/models/execution_dlq.py` | Import + dùng DLQStatus |
| `db/models/schedule.py` | Import + dùng RunStatus, ScheduleTargetType |
| `db/models/mcp_session.py` | Import + dùng McpSessionStatus |
| `db/models/user.py` | Import + dùng UserRole |
| `db/crud/*.py` | Thay string literals → enum values (nhiều file) |
| `api/schemas/*.py` | Thêm enum validation vào Pydantic schemas |

---

## Phase 3: Multi-tenancy Organization-Level

**Migration:** `017_org_multitenancy.py`
**Risk:** Cao — thay đổi auth model, ảnh hưởng tất cả API queries.
**Strategy:** Thêm `organization_id` nullable trước → backfill → enforce NOT NULL sau.

### 3.1 Thêm `organization_id` vào core tables

```sql
-- Step 1: Add nullable column + index
ALTER TABLE devices ADD COLUMN organization_id VARCHAR(36)
  REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_devices_org ON devices(organization_id);

ALTER TABLE campaigns ADD COLUMN organization_id VARCHAR(36)
  REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_campaigns_org ON campaigns(organization_id);

ALTER TABLE executions ADD COLUMN organization_id VARCHAR(36)
  REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_executions_org ON executions(organization_id);

ALTER TABLE accounts ADD COLUMN organization_id VARCHAR(36)
  REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_accounts_org ON accounts(organization_id);

ALTER TABLE schedules ADD COLUMN organization_id VARCHAR(36)
  REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_schedules_org ON schedules(organization_id);

ALTER TABLE scenario_templates ADD COLUMN organization_id VARCHAR(36)
  REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX idx_scenario_templates_org ON scenario_templates(organization_id);
```

### 3.2 Backfill script

```python
# Backfill organization_id from user → organization_members → organization
UPDATE devices d SET organization_id = (
  SELECT om.organization_id FROM organization_members om
  WHERE om.user_id = d.user_id LIMIT 1
) WHERE d.organization_id IS NULL AND d.user_id IS NOT NULL;
-- Repeat for campaigns, executions, accounts, schedules, scenario_templates
```

### 3.3 Auth middleware update

```python
# api/deps.py — thêm CurrentOrganization dependency
async def _get_current_org(user: CurrentUser, db: AsyncSession) -> Organization:
    member = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    return member.scalar_one().organization

CurrentOrganization = Annotated[Organization, Depends(_get_current_org)]
```

### 3.4 Query scoping

Tất cả CRUD list functions thêm `.where(Model.organization_id == org.id)`.

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `db/migrations/017_org_multitenancy.py` | Migration + backfill |
| `db/models/device.py` | Thêm `organization_id` FK |
| `db/models/campaign.py` | Thêm `organization_id` FK |
| `db/models/execution.py` | Thêm `organization_id` FK |
| `db/models/account.py` | Thêm `organization_id` FK |
| `db/models/schedule.py` | Thêm `organization_id` FK |
| `db/models/scenario_template.py` | Thêm `organization_id` FK |
| `api/deps.py` | Thêm `CurrentOrganization` dependency |
| `db/crud/*.py` | Thêm org_id filter vào tất cả list/query functions |
| `api/routes/*.py` | Inject `CurrentOrganization` vào endpoints |

---

## Phase 4: Scenario Versioning

**Migration:** `018_scenario_versioning.py`
**Risk:** Trung bình — thêm bảng mới, thay đổi flow tạo execution.
**Lý do:** Khi edit scenario rồi chạy lại, không biết execution cũ chạy version nào.

### 4.1 Tạo bảng `scenario_versions`

```sql
CREATE TABLE scenario_versions (
    id VARCHAR(36) PRIMARY KEY,
    scenario_id VARCHAR(36) NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    steps JSONB NOT NULL DEFAULT '[]',
    nodes JSONB NOT NULL DEFAULT '[]',
    edges JSONB NOT NULL DEFAULT '[]',
    variables JSONB NOT NULL DEFAULT '{}',
    instructions TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(scenario_id, version)
);
CREATE INDEX idx_sv_scenario ON scenario_versions(scenario_id);
```

### 4.2 Thêm FK vào executions

```sql
ALTER TABLE executions ADD COLUMN scenario_version_id VARCHAR(36)
  REFERENCES scenario_versions(id) ON DELETE SET NULL;
CREATE INDEX idx_executions_sv ON executions(scenario_version_id);
```

### 4.3 Logic tạo version

```python
# db/crud/scenario.py
async def create_scenario_version(db, scenario_id: str) -> ScenarioVersion:
    """Snapshot current scenario state into a new version."""
    scenario = await get_scenario(db, scenario_id)
    latest = await db.execute(
        select(func.coalesce(func.max(ScenarioVersion.version), 0))
        .where(ScenarioVersion.scenario_id == scenario_id)
    )
    next_ver = latest.scalar_one() + 1
    version = ScenarioVersion(
        scenario_id=scenario_id,
        version=next_ver,
        steps=scenario.steps,
        nodes=scenario.nodes,
        edges=scenario.edges,
        variables=scenario.variables,
        instructions=scenario.instructions,
    )
    db.add(version)
    await db.flush()
    return version
```

### 4.4 Hook vào execution creation

Khi tạo Execution với `scenario_id`:
1. Gọi `create_scenario_version(db, scenario_id)`
2. Gán `execution.scenario_version_id = version.id`

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `db/migrations/018_scenario_versioning.py` | Migration mới |
| `db/models/scenario_version.py` | **Mới** — ScenarioVersion model |
| `db/models/__init__.py` | Register ScenarioVersion |
| `db/models/execution.py` | Thêm `scenario_version_id` FK |
| `db/crud/scenario.py` | **Mới** — `create_scenario_version()` |
| `db/crud/execution.py` | Hook version creation vào `create_execution()` |
| `services/campaign_dispatch.py` | Pass version_id khi dispatch |

---

## Phase 5: Normalize JSON Relationship Columns

**Migration:** `019_normalize_json_relationships.py`
**Risk:** Trung bình — cần update code đọc/ghi JSON arrays.
**Mục tiêu:** Tách JSON arrays chứa relationships ra join tables.

### 5.1 `campaign_runs.device_serials` → join table

```sql
-- Đã có execution_devices cho executions.
-- campaign_runs.device_serials chỉ là cache — giữ nguyên JSON nhưng document là denormalized cache.
-- DECISION: Giữ nguyên — campaign_runs đang phase-out, execution_devices là canonical.
```

**Quyết định:** Không tạo bảng mới. `campaign_runs` đang dần thay thế bởi `executions`.
Thêm comment trong model: `# Denormalized cache. Canonical source: execution_devices`.

### 5.2 `campaign_runs.workflow_ids` → giữ JSON

Workflow IDs là Temporal external IDs, không phải FK. JSON phù hợp.

### 5.3 `execution_results.passed_steps` / `failed_steps`

**Option A:** Normalize ra `execution_step_results` table.
**Option B:** Giữ JSON nhưng define schema rõ.

**Quyết định:** Option B — steps là small arrays (10-50 items), không cần query individually.
Thêm Pydantic schema validation khi write.

### 5.4 `content_items.collection` → FK to `content_collections`

```sql
-- Thêm FK constraint (collection name → content_collections.name)
-- Nhưng content_collections.name đã UNIQUE
-- ISSUE: collection field là VARCHAR(100), không phải FK to id
-- DECISION: Thêm check ở app layer, không thêm FK (vì collection có thể tạo on-the-fly)
```

**Quyết định:** Giữ string-based, thêm app-level validation trong `save_content()`.

### Tổng kết Phase 5

Phase này chủ yếu là **documentation + validation**, không tạo migration lớn:
- Comment `campaign_runs.device_serials` là denormalized cache
- Add Pydantic schema cho `passed_steps`/`failed_steps`
- Add app-level validation cho `content_items.collection`

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `db/models/campaign.py` | Thêm comment denormalized |
| `api/schemas/execution.py` | Thêm StepResult Pydantic model |
| `db/crud/execution.py` | Validate passed_steps/failed_steps format |
| `services/content_store.py` | Validate collection name exists |

---

## Phase 6: Content Items — Giảm tải God Table

**Migration:** `020_content_items_user_id.py`
**Risk:** Thấp — thêm column, không thay đổi existing data.

### 6.1 Thêm `user_id` trực tiếp

```sql
ALTER TABLE content_items ADD COLUMN user_id VARCHAR(36)
  REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX idx_content_items_user ON content_items(user_id);

-- Backfill từ execution → user_id hoặc campaign → user_id
UPDATE content_items ci SET user_id = (
  SELECT e.user_id FROM executions e WHERE e.id = ci.execution_id
) WHERE ci.user_id IS NULL AND ci.execution_id IS NOT NULL;

UPDATE content_items ci SET user_id = (
  SELECT c.user_id FROM campaigns c WHERE c.id = ci.campaign_id
) WHERE ci.user_id IS NULL AND ci.campaign_id IS NOT NULL;
```

### 6.2 Content Items — giữ nguyên cấu trúc

**Quyết định:** KHÔNG tách `content_items` ra nhiều bảng vì:
- Tất cả content types (post/comment/reply) share cùng schema
- `item_level` + `parent_id` đủ cho hierarchy
- Tách sẽ phá vỡ tất cả CRUD/API code hiện tại
- Index coverage đã tốt cho các query patterns hiện tại

Thay vào đó:
- Thêm `user_id` cho direct auth queries
- Thêm `organization_id` (Phase 3 sẽ cover)
- Document rõ query patterns và index strategy

### Files thay đổi

| File | Thay đổi |
|------|----------|
| `db/migrations/020_content_items_user_id.py` | Migration + backfill |
| `db/models/content.py` | Thêm `user_id` FK |
| `db/crud/content.py` | Thêm `user_id` filter vào `query_content()` |
| `services/content_store.py` | Populate `user_id` khi save |

---

## Thứ tự triển khai & Dependencies

```
Phase 1 (Data Integrity)
    ↓
Phase 2 (Status Enums)
    ↓
Phase 6 (Content user_id)  ← Độc lập, có thể song song Phase 2
    ↓
Phase 3 (Multi-tenancy)    ← Cần Phase 1+2 xong
    ↓
Phase 4 (Scenario Version) ← Độc lập, có thể song song Phase 3
    ↓
Phase 5 (Normalize JSON)   ← Documentation phase, bất kỳ lúc nào
```

## Ước lượng effort

| Phase | Migrations | Model files | CRUD/API files | Risk |
|-------|-----------|-------------|----------------|------|
| 1 | 1 | 4 | 0 | Thấp |
| 2 | 1 | 9 | ~10 | Trung bình |
| 3 | 1 | 6 | ~15 | Cao |
| 4 | 1 | 3 | 3 | Trung bình |
| 5 | 0 | 1 | 3 | Thấp |
| 6 | 1 | 1 | 2 | Thấp |

## Rollback strategy

- Mỗi migration có `downgrade()` function
- CHECK constraints: `ALTER TABLE x DROP CONSTRAINT y`
- New columns: `ALTER TABLE x DROP COLUMN y`
- New tables: `DROP TABLE IF EXISTS`
- Indexes: `DROP INDEX IF EXISTS`
