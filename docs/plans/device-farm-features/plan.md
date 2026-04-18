# Device Farm Features — Implementation Plan

**Created:** 2026-04-15  
**Branch:** feat/upload-img  
**Status:** Ready for implementation

---

## Reality Check: What's Already Built

Before implementing, note that most "needed features" are **already present**:

| Feature | Status | Location |
|---------|--------|----------|
| Task result + artifact storage | ✅ | `db/models/execution.py`, `services/minio_store.py` |
| Device pool locking | ✅ | `runtime/core/device_pool.py`, `common/session_lock.py` |
| Device tagging + routing | ✅ | `runtime/core/device_pool.py` (`wait_for_device(tags=[...])`) |
| Task scheduling (cron) | ✅ | `temporal/schedule_workflow.py`, `api/routes/` |
| Multi-tenant auth (JWT + orgs) | ✅ | `api/routes/auth.py`, `db/models/organization.py` |
| APK install + version mgmt | ✅ | `api/routes/device_control/` |
| Rate limiting per device | ✅ | `runtime/core/dispatcher.py` (`max_tasks_per_minute`) |
| Prometheus metrics | ✅ | `web/metrics.py` |
| Redis shared state | ✅ | `services/redis_store.py` (just implemented) |

**Real gaps** requiring implementation (5 phases):

---

## Phase 1: Complete scenario_task.py Refactor

**Priority:** HIGH (blocking testability)  
**Effort:** 2–3 days

### Problem
`tasks/scenario/` package was created but still has circular imports back to `scenario_task.py`:
- `steps/interaction.py`, `steps/wait.py`, `steps/input.py`, `steps/control_flow.py`, `steps/composition.py` all import helpers from `scenario_task.py`
- `capture.py`, `context.py` also import from `scenario_task`
- The 3168-line `scenario_task.py` still has the legacy `_run_scenario_task_legacy` giant if-elif chain

### Target State
- All helpers moved to `tasks/scenario/utils.py` (or sub-modules)
- Zero imports from `scenario_task` inside the `tasks/scenario/` package
- `scenario_task.py` reduced to a thin shim: just `run_scenario_task()`, `make_scenario_task()`, re-exports
- Unit tests possible for individual step handlers without full device

### Implementation Steps

**Step 1.1 — Extract helpers to `tasks/scenario/utils.py`**

Move from `scenario_task.py`:
```python
# tasks/scenario/utils.py
def _wait_for_element(device, selector, timeout, ...) -> Element | None: ...
def _retry_find_element(sc, selector, ...) -> Element | None: ...
def _evaluate_condition(sc, condition) -> bool: ...
def _eval_ru_condition(sc, condition) -> bool: ...
def _get_implicit_wait_config(sc) -> dict: ...
def _capture_step_screenshot(device, capture_dir, ...) -> str | None: ...
def capture_pre_step_enabled(scenario) -> bool: ...
```

**Step 1.2 — Update step files to import from utils**
```python
# Before (in steps/control_flow.py):
from tasks.scenario_task import _evaluate_condition, _eval_ru_condition, _wait_for_element

# After:
from tasks.scenario.utils import _evaluate_condition, _eval_ru_condition, _wait_for_element
```

Files to update:
- `steps/interaction.py` — remove `from tasks.scenario_task import ...`
- `steps/wait.py` — remove `from tasks.scenario_task import ...`
- `steps/input.py` — remove `from tasks.scenario_task import ...`
- `steps/control_flow.py` — remove `from tasks.scenario_task import ...`
- `steps/composition.py` — change `run_scenario_task` import path
- `capture.py` — remove `from tasks.scenario_task import _capture_step_screenshot`
- `context.py` — remove `from tasks.scenario_task import capture_pre_step_enabled`

**Step 1.3 — Slim down `scenario_task.py`**

```python
# tasks/scenario_task.py — AFTER refactor (thin shim)
"""Public API for scenario execution. Implementation in tasks/scenario/."""
from tasks.scenario.context import ScenarioContext
from tasks.scenario.executor import ScenarioExecutor
from tasks.scenario.utils import (
    _wait_for_element, _retry_find_element,
    _evaluate_condition, _eval_ru_condition,
    _get_implicit_wait_config, _capture_step_screenshot,
    capture_pre_step_enabled,
)

def run_scenario_task(device, scenario, *, context=None, cancel_event=None, ...):
    sc = ScenarioContext.from_args(device, scenario, context=context, cancel_event=cancel_event, ...)
    return ScenarioExecutor(sc).run()

def make_scenario_task(payload, cancel_event=None):
    ...

# Delete: _run_scenario_task_legacy and entire if-elif chain (~2000 lines)
```

**Step 1.4 — Write unit tests**
```
tasks/scenario/tests/
├── test_context.py          # ScenarioContext.from_args()
├── test_executor.py         # executor loop, cancellation, depth limit
├── test_steps_navigation.py # launch_app, open_url, key, scroll
├── test_steps_interaction.py # tap, long_press, swipe
├── test_steps_wait.py        # wait_for_element, wait_ms
└── test_steps_control_flow.py # if/else, loop, foreach
```

Mock pattern (no real device needed):
```python
from unittest.mock import MagicMock, AsyncMock
device = MagicMock()
device.serial = "test_serial"
device.screen_width = 1080
device.screen_height = 1920
```

---

## Phase 2: Artifact Browser UI

**Priority:** HIGH (biggest usability gap)  
**Effort:** 2 days

### Problem
Screenshots captured per step are stored in MinIO/S3, but there's no web UI to browse them. Users can't review what happened during a task run.

### Target State
- Web page: `/executions/{id}/artifacts`  
- Timeline: per-step screenshots in order
- Filter: device, date range, pass/fail
- Download: bulk ZIP per execution

### Implementation

**Step 2.1 — API endpoint**
```python
# api/routes/executions.py — add:
@router.get("/{execution_id}/artifacts")
async def list_artifacts(execution_id: int, db: Session = Depends(get_db)):
    """Returns step results with pre-signed MinIO URLs."""
    ...
```

**Step 2.2 — DB: artifact metadata**

Add `artifact_url` to `ExecutionResult` or create `ExecutionArtifact` table:
```python
# db/models/execution_artifact.py
class ExecutionArtifact(Base):
    id: int
    execution_id: int
    device_serial: str
    step_index: int
    step_type: str
    phase: Literal["pre", "post"]
    minio_key: str
    captured_at: datetime
```

**Step 2.3 — Frontend page**

Add to `web/templates/` (Jinja2 + HTMX or vanilla JS):
```html
<!-- /executions/123/artifacts -->
<div class="artifact-timeline">
  {% for step in steps %}
  <div class="step {{ 'pass' if step.ok else 'fail' }}">
    <div class="step-meta">Step {{ step.index }}: {{ step.type }}</div>
    {% if step.screenshot_url %}
    <img src="{{ step.screenshot_url }}" loading="lazy">
    {% endif %}
  </div>
  {% endfor %}
</div>
```

**Step 2.4 — Link from dashboard**
- Execution list → each row has "View Artifacts" link
- Device card → "Last Run" thumbnail preview

---

## Phase 3: Dead-Letter Queue + Webhook Notifications

**Priority:** MEDIUM  
**Effort:** 1.5 days

### Problem
Tasks that fail after all Temporal retries are silently dropped. No notification to team.

### Target State
- DLQ: `execution_dlq` table — failed executions with error detail, retry count
- Webhook: per-org config — POST to URL on task complete/fail
- UI: DLQ viewer in dashboard

### Implementation

**Step 3.1 — DLQ model + migration**
```python
# db/models/execution_dlq.py
class ExecutionDLQ(Base):
    id: int
    execution_id: int
    device_serial: str
    error: str
    retry_count: int
    last_attempt_at: datetime
    created_at: datetime
    # FK → Execution
```

Migration: `db/migrations/011_execution_dlq.py`

**Step 3.2 — Webhook config**
```python
# db/models/organization.py — add column:
webhook_url: Optional[str]   # POST target
webhook_secret: Optional[str]  # HMAC signing key
webhook_events: str           # comma-sep: "task.complete,task.failed"
```

**Step 3.3 — Webhook dispatcher service**
```python
# services/webhook_dispatcher.py
import hmac, hashlib, httpx

async def dispatch(org_id: int, event: str, payload: dict):
    org = await get_org(org_id)
    if not org.webhook_url or event not in org.webhook_events:
        return
    body = json.dumps(payload)
    sig = hmac.new(org.webhook_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    async with httpx.AsyncClient() as client:
        await client.post(org.webhook_url, content=body,
                          headers={"X-Signature": sig, "Content-Type": "application/json"},
                          timeout=10)
```

**Step 3.4 — Wire into Temporal activity completion**
```python
# temporal/activities.py — after save_extraction or execution complete:
from services.webhook_dispatcher import dispatch
await dispatch(org_id, "task.complete", {"execution_id": ..., "status": "passed", ...})
```

**Step 3.5 — DLQ API + UI**
```
GET /api/executions/dlq          → list DLQ entries
POST /api/executions/dlq/{id}/retry → re-enqueue
DELETE /api/executions/dlq/{id}  → dismiss
```

---

## Phase 4: Extended Manual Control (Keyboard + Gestures)

**Priority:** MEDIUM  
**Effort:** 1.5 days

### Problem
Web UI supports tap (click) but not keyboard input, swipe gestures, or pinch-zoom.

### Current State
- `api/routes/device_control/scrcpy.py` — has inject_touch, inject_key endpoints
- `runtime/transports/scrcpy_controller.py` — low-level scrcpy control protocol

### Target State
- Web dashboard: keyboard capture → inject key events
- Swipe: mouse drag on device canvas → swipe gesture
- Pinch: two-pointer touch simulation

### Implementation

**Step 4.1 — Keyboard capture in web UI**
```javascript
// web/static/dashboard.js — add:
document.addEventListener('keydown', (e) => {
    if (!activeDeviceSerial) return;
    fetch(`/api/device-control/${activeDeviceSerial}/inject-key`, {
        method: 'POST',
        body: JSON.stringify({ keycode: e.key, modifiers: getModifiers(e) }),
    });
    e.preventDefault();
});
```

**Step 4.2 — Swipe from drag**
```javascript
let dragStart = null;
canvas.addEventListener('mousedown', (e) => { dragStart = { x: e.offsetX, y: e.offsetY }; });
canvas.addEventListener('mouseup', (e) => {
    if (!dragStart) return;
    const dx = Math.abs(e.offsetX - dragStart.x);
    const dy = Math.abs(e.offsetY - dragStart.y);
    if (dx > 10 || dy > 10) {
        injectSwipe(dragStart, { x: e.offsetX, y: e.offsetY });
    } else {
        injectTap(e.offsetX, e.offsetY);
    }
    dragStart = null;
});
```

**Step 4.3 — API endpoint for swipe**
```python
# api/routes/device_control/scrcpy.py — add:
@router.post("/{serial}/inject-swipe")
async def inject_swipe(serial: str, body: SwipeRequest):
    device = get_device(serial)
    await device.scrcpy_controller.inject_swipe(
        body.from_x, body.from_y, body.to_x, body.to_y, body.duration_ms
    )
```

**Step 4.4 — Text input shortcut**
```javascript
// "Type text" modal: user types text → split to chars → inject each as key event
```

---

## Phase 5: Grafana Dashboards + Alerting

**Priority:** LOW  
**Effort:** 0.5 days

### Problem
Prometheus metrics exported but Grafana only has datasource configured — no dashboards.

### Target State
- Dashboard: "Device Farm Overview" with panels:
  - Devices online (gauge)
  - Task queue depth (time series)
  - Tasks dispatched/min (time series)
  - Frame drop rate (time series)
  - Task success rate (stat)
- Alert: task_queue_depth > 50 → Slack/PagerDuty

### Implementation

**Step 5.1 — Grafana dashboard JSON**
```
monitoring/grafana/provisioning/dashboards/
└── device-farm-overview.json
```

Panels:
```json
{
  "panels": [
    { "title": "Devices Online", "type": "stat", "expr": "devices_online" },
    { "title": "Queue Depth", "type": "timeseries", "expr": "task_queue_depth" },
    { "title": "Dispatch Rate", "type": "timeseries", "expr": "rate(tasks_dispatched_total[5m])" },
    { "title": "Frame Drops", "type": "timeseries", "expr": "rate(frame_drops_total[1m])" },
    { "title": "Success Rate", "type": "gauge", "expr": "rate(task_success_total[10m]) / rate(tasks_dispatched_total[10m])" }
  ]
}
```

**Step 5.2 — Add missing metrics to `web/metrics.py`**
```python
task_success_total = Counter("task_success_total", "Tasks completed successfully", ["device_serial"])
task_failed_total  = Counter("task_failed_total", "Tasks failed", ["device_serial", "reason"])
```

**Step 5.3 — Grafana alerts config**
```yaml
# monitoring/grafana/provisioning/alerting/rules.yaml
groups:
  - name: device-farm
    rules:
      - alert: QueueBacklog
        expr: task_queue_depth > 50
        for: 2m
        annotations:
          summary: "Task queue backing up"
```

---

## Execution Order

```
Phase 1 (scenario refactor) → unblocks testability
  ↓ parallel
Phase 2 (artifact UI)      Phase 3 (DLQ/webhook)
  ↓
Phase 4 (extended control)
  ↓
Phase 5 (Grafana)
```

## File Impact Summary

| Phase | New Files | Modified Files |
|-------|-----------|----------------|
| 1 | `tasks/scenario/utils.py`, `tasks/scenario/tests/` (6 files) | 7 step files, `scenario_task.py` |
| 2 | `db/models/execution_artifact.py`, `db/migrations/011_*`, `web/templates/artifacts.html` | `api/routes/executions.py` |
| 3 | `db/models/execution_dlq.py`, `services/webhook_dispatcher.py`, `db/migrations/012_*` | `db/models/organization.py`, `temporal/activities.py` |
| 4 | — | `web/static/dashboard.js`, `api/routes/device_control/scrcpy.py` |
| 5 | `monitoring/grafana/provisioning/dashboards/device-farm-overview.json`, `monitoring/grafana/provisioning/alerting/rules.yaml` | `web/metrics.py` |
