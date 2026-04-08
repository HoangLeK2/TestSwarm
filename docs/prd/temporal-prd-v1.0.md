# Temporal.io — Product Requirements Document (Research)

---

- **Product Name:** Temporal.io
- **Version:** SDK Python ≥ 1.x (core server written in Go, SDK core in Rust)
- **Author / Maintainer:** Temporal Technologies (founders from Uber Cadence)
- **Last Updated:** 2026-03-28
- **License:** MIT
- **Status:** Active development, production-proven (Uber, Netflix, Snap, Stripe, Datadog)

---

## 1. Executive Summary

### Product Overview

**Temporal** là một **durable execution platform** — cho phép developer viết code như logic tuần tự thông thường, nhưng hệ thống tự động đảm bảo code chạy đến hoàn thành bất kể crash, network failure, hay server restart. Temporal dựa trên **event sourcing** — mọi state transition được ghi lại và có thể replay để khôi phục trạng thái.

### Tại sao quan trọng cho Device Farm

| Vấn đề của Device Farm | Temporal giải quyết |
|------------------------|---------------------|
| Flow automation chạy dài (5-30 phút / device) | Workflow chạy **hours/days/months** — server-side timer, không giữ worker |
| 1000 devices song song, mỗi device 1 flow | **Millions** concurrent workflow executions |
| Device disconnect giữa chừng → flow mất state | **Durable execution** — resume từ đúng step bị interrupt |
| Retry phức tạp: retry step, retry sub-flow, recovery | **Configurable retry policies** per-activity + workflow-level compensation |
| Scheduling: chạy flow lúc 2AM, mỗi ngày | **First-class Schedules API** — cron expression, calendar, interval |
| Monitor: flow nào đang chạy, step nào, bao lâu | **Built-in Web UI** + search attributes + visibility queries |
| Fan-out: cùng 1 flow → 100 devices | **asyncio.gather** + child workflows + worker scaling |

### So sánh nhanh: Temporal vs Celery vs Custom Queue

| Aspect | Temporal | Celery + Redis | Custom (Redis pub/sub) |
|--------|----------|---------------|----------------------|
| Workflow state | Auto-persisted (event sourcing) | Không có | Tự build |
| Long-running (>5 min) | Native | Không thiết kế cho | Tự build |
| Retry + resume từ giữa | Per-activity, auto-resume | Per-task, không resume | Tự build |
| Parallel (fan-out/in) | `asyncio.gather`, child workflows | chord/group (fragile) | Tự build |
| Visibility/monitoring | Web UI + search + history | Flower (basic) | Tự build |
| Learning curve | **Cao** (determinism, replay) | Thấp | Thấp |
| Operational cost | Server + DB + monitoring | Redis only | Redis only |
| Maturity | Uber/Netflix/Snap scale | Battle-tested | Phụ thuộc impl |

---

## 2. Core Concepts

### 2.1 Durable Execution (Event Sourcing + Replay)

```
                        EVENT HISTORY (append-only)
┌─────────────────────────────────────────────────────────────┐
│ 1. WorkflowExecutionStarted { input: "device_001" }        │
│ 2. ActivityTaskScheduled    { activity: "tap_login" }       │
│ 3. ActivityTaskCompleted    { result: { success: true } }   │
│ 4. TimerStarted            { duration: 3s }                 │
│ 5. TimerFired              {}                               │
│ 6. ActivityTaskScheduled    { activity: "input_text" }      │
│ 7. ActivityTaskCompleted    { result: { success: true } }   │
│ ...                                                          │
│ N. WorkflowExecutionCompleted { result: "passed" }          │
└─────────────────────────────────────────────────────────────┘

Worker crash sau event #5 → Worker mới picks up task
→ REPLAY events 1-5 (reconstruct state, KHÔNG re-execute activities)
→ CONTINUE execution từ event #6
```

**Key insight:** Workflow code phải **deterministic** vì replay phải produce kết quả giống hệt. Side effects (device interaction, network, I/O) phải nằm trong **Activities**.

### 2.2 Workflow vs Activity

```
┌─────────────────────────────────────────┐
│            WORKFLOW                       │
│  (deterministic orchestration logic)     │
│                                          │
│  ✓ if/else, loops, variable assignment  │
│  ✓ asyncio.sleep (server-side timer)    │
│  ✓ asyncio.gather (parallel)            │
│  ✓ Signal/Query/Update handlers         │
│  ✓ Child workflows                      │
│                                          │
│  ✗ NO network I/O                       │
│  ✗ NO random (dùng workflow.random())   │
│  ✗ NO datetime.now (dùng workflow.now())│
│  ✗ NO threading                         │
│  ✗ NO global mutable state              │
│  ✗ NO file I/O                          │
└────────────────┬────────────────────────┘
                 │ schedule activities
                 ▼
┌─────────────────────────────────────────┐
│            ACTIVITY                      │
│  (side effects — device interaction)    │
│                                          │
│  ✓ uiautomator2 tap/swipe/input        │
│  ✓ ADB commands                         │
│  ✓ HTTP requests                        │
│  ✓ File I/O, screenshots               │
│  ✓ OCR, AI API calls                   │
│  ✓ Database queries                     │
│                                          │
│  → Must be IDEMPOTENT (safe to retry)   │
│  → Supports heartbeating                │
│  → Configurable retry + timeout         │
└─────────────────────────────────────────┘
```

### 2.3 Worker + Task Queue

```
┌──────────────┐     gRPC poll     ┌─────────────────┐
│   Worker 1   │ ◄────────────────► │                 │
│  (Python)    │                    │  Temporal Server │
│  - workflows │     gRPC poll     │                 │
│  - activities│ ◄────────────────► │  Task Queue:    │
└──────────────┘                    │  "device-farm"  │
                                    │                 │
┌──────────────┐     gRPC poll     │  ┌───────────┐  │
│   Worker 2   │ ◄────────────────► │  │ WF Tasks  │  │
│  (Python)    │                    │  │ Act Tasks │  │
└──────────────┘                    │  └───────────┘  │
                                    │                 │
┌──────────────┐     gRPC poll     │                 │
│   Worker N   │ ◄────────────────► │                 │
└──────────────┘                    └─────────────────┘

Workers scale horizontally → thêm process / machine
Task queue partitioned (default 4) cho throughput
Worker-specific routing cho device-specific tasks
```

### 2.4 Signals, Queries, Updates

| Mechanism | Direction | Mutate State? | Return Value? | Use Case (Device Farm) |
|-----------|-----------|---------------|---------------|----------------------|
| **Signal** | Client → Workflow | Yes | No | Gửi lệnh cancel, pause, inject data giữa flow |
| **Query** | Client → Workflow | No | Yes | Đọc current step, progress %, device state |
| **Update** | Client ↔ Workflow | Yes | Yes | Human approval, modify flow params at runtime |

```python
# Signal: pause/resume flow
@workflow.signal
async def pause(self):
    self.paused = True

@workflow.signal
async def resume(self):
    self.paused = False

# Query: get current progress
@workflow.query
def get_progress(self) -> dict:
    return {"step": self.current_step, "total": self.total_steps, "device": self.device_id}

# Update: inject data mid-flow (e.g., OTP code)
@workflow.update
async def inject_otp(self, code: str) -> bool:
    self.otp_code = code
    return True
```

---

## 3. Python SDK Deep Dive

### 3.1 Installation & Setup

```bash
# Install SDK
pip install temporalio

# Pydantic support
pip install temporalio  # Pydantic v2 built-in via contrib

# OpenTelemetry tracing
pip install 'temporalio[opentelemetry]'

# Local dev server (no Docker needed)
brew install temporal
temporal server start-dev
# → Server: localhost:7233
# → Web UI: localhost:8233
```

**Python 3.9+ required.** SDK core written in **Rust** (compiled native extension).

### 3.2 Defining Workflows

```python
from datetime import timedelta
from temporalio import workflow

# Import activities inside sandbox passthrough
with workflow.unsafe.imports_passed_through():
    from my_activities import tap_element, input_text, take_screenshot, assert_element

@workflow.defn
class DeviceAutomationFlow:
    """Workflow = orchestration logic (deterministic)"""

    def __init__(self) -> None:
        self.current_step = 0
        self.total_steps = 0
        self.paused = False
        self.otp_code: str | None = None

    @workflow.run
    async def run(self, params: FlowParams) -> FlowResult:
        self.total_steps = len(params.steps)

        for i, step in enumerate(params.steps):
            # Check pause signal
            await workflow.wait_condition(lambda: not self.paused)

            self.current_step = i + 1

            if step.type == "tap":
                result = await workflow.execute_activity(
                    tap_element,
                    step.config,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=1),
                        backoff_coefficient=2.0,
                    ),
                )
            elif step.type == "input_text":
                result = await workflow.execute_activity(
                    input_text,
                    step.config,
                    start_to_close_timeout=timedelta(seconds=15),
                )
            elif step.type == "wait_otp":
                # Wait for human signal with timeout
                try:
                    await workflow.wait_condition(
                        lambda: self.otp_code is not None,
                        timeout=timedelta(minutes=2),
                    )
                except asyncio.TimeoutError:
                    return FlowResult(status="failed", error="OTP timeout")
            elif step.type == "assert":
                result = await workflow.execute_activity(
                    assert_element,
                    step.config,
                    start_to_close_timeout=timedelta(seconds=10),
                )

        return FlowResult(status="passed", steps_completed=self.total_steps)

    @workflow.signal
    async def pause(self):
        self.paused = True

    @workflow.signal
    async def resume(self):
        self.paused = False

    @workflow.signal
    async def inject_otp(self, code: str):
        self.otp_code = code

    @workflow.query
    def get_progress(self) -> dict:
        return {
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "paused": self.paused,
        }
```

### 3.3 Defining Activities

```python
from temporalio import activity
import uiautomator2 as u2

# Activities = side effects (device interaction, I/O, network)
# Phải idempotent (safe to retry)

@activity.defn
def tap_element(config: TapConfig) -> TapResult:
    """Tap element on device — runs in thread pool"""
    d = u2.connect(config.device_serial)

    if config.strategy == "element":
        el = d(**{config.selector.type: config.selector.value})
        el.click()
        bounds = el.info.get("bounds", {})
    elif config.strategy == "coordinate":
        d.click(config.x, config.y)
        bounds = {"x": config.x, "y": config.y}

    return TapResult(success=True, bounds=bounds)


@activity.defn
def input_text(config: InputConfig) -> InputResult:
    d = u2.connect(config.device_serial)
    el = d(**{config.selector.type: config.selector.value})

    if config.clear_first:
        el.clear_text()
    el.set_text(config.text)

    return InputResult(success=True, actual_text=config.text)


@activity.defn
def take_screenshot(config: ScreenshotConfig) -> str:
    """Returns base64 screenshot"""
    d = u2.connect(config.device_serial)
    img = d.screenshot()

    # Save to artifacts
    path = f"/data/artifacts/{config.run_id}/step_{config.step}.png"
    img.save(path)

    return path


@activity.defn
def assert_element(config: AssertConfig) -> AssertResult:
    d = u2.connect(config.device_serial)
    el = d(**{config.selector.type: config.selector.value})

    exists = el.exists(timeout=config.timeout_s)

    if not exists and config.screenshot_on_fail:
        activity.heartbeat("taking failure screenshot")
        take_screenshot(ScreenshotConfig(
            device_serial=config.device_serial,
            run_id=config.run_id,
            step=config.step,
        ))

    return AssertResult(passed=exists, element_found=exists)


@activity.defn
async def call_ai_vision(config: AIVisionConfig) -> AIVisionResult:
    """Async activity — calls LLM API"""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            json={"model": "claude-sonnet-4-20250514", "messages": [...]},
            headers={"x-api-key": config.api_key},
        )
    return AIVisionResult(description=response.json()["content"][0]["text"])
```

### 3.4 Running Workers

```python
import asyncio
import concurrent.futures
from temporalio.client import Client
from temporalio.worker import Worker

async def main():
    # Connect to Temporal server
    client = await Client.connect("localhost:7233", namespace="device-farm")

    # Thread pool for synchronous activities (u2, adb, etc.)
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        worker = Worker(
            client,
            task_queue="device-automation",
            workflows=[DeviceAutomationFlow],
            activities=[
                tap_element,
                input_text,
                take_screenshot,
                assert_element,
                call_ai_vision,
            ],
            activity_executor=executor,  # sync activities run here
        )
        await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### 3.5 Starting Workflows (Client / API)

```python
from temporalio.client import Client

async def start_device_flow(device_serial: str, flow_params: FlowParams):
    client = await Client.connect("localhost:7233", namespace="device-farm")

    # Start workflow (non-blocking)
    handle = await client.start_workflow(
        DeviceAutomationFlow.run,
        flow_params,
        id=f"flow-{device_serial}-{uuid4().hex[:8]}",
        task_queue="device-automation",
        search_attributes={
            "device_id": [device_serial],
            "flow_name": [flow_params.flow_name],
        },
    )

    # Query progress
    progress = await handle.query(DeviceAutomationFlow.get_progress)
    print(f"Progress: {progress}")

    # Signal: inject OTP
    await handle.signal(DeviceAutomationFlow.inject_otp, "123456")

    # Signal: pause
    await handle.signal(DeviceAutomationFlow.pause)

    # Wait for result
    result = await handle.result()
    return result
```

### 3.6 Fan-Out: 1 Flow → 100 Devices

```python
@workflow.defn
class BatchDeviceFlow:
    """Run same flow on multiple devices in parallel"""

    @workflow.run
    async def run(self, params: BatchParams) -> BatchResult:
        # Fan-out: start child workflow per device
        handles = []
        for device_id in params.device_ids:
            handle = await workflow.start_child_workflow(
                DeviceAutomationFlow.run,
                FlowParams(device_serial=device_id, steps=params.steps),
                id=f"device-{device_id}-{workflow.info().workflow_id}",
            )
            handles.append(handle)

        # Fan-in: wait for all results
        results = await asyncio.gather(*handles, return_exceptions=True)

        passed = sum(1 for r in results if isinstance(r, FlowResult) and r.status == "passed")
        failed = len(results) - passed

        return BatchResult(total=len(results), passed=passed, failed=failed)
```

### 3.7 Scheduling (Cron)

```python
from temporalio.client import Client, Schedule, ScheduleSpec, ScheduleActionStartWorkflow

async def create_daily_schedule(client: Client):
    await client.create_schedule(
        id="daily-smoke-test",
        schedule=Schedule(
            spec=ScheduleSpec(cron_expressions=["0 2 * * *"]),  # 2AM daily
            action=ScheduleActionStartWorkflow(
                DeviceAutomationFlow.run,
                FlowParams(flow_name="smoke_test", steps=[...]),
                id="smoke-test",
                task_queue="device-automation",
            ),
        ),
    )
```

### 3.8 Pydantic Integration

```python
from pydantic import BaseModel
from temporalio.contrib.pydantic import pydantic_data_converter

class FlowParams(BaseModel):
    flow_name: str
    device_serial: str
    steps: list[StepConfig]
    variables: dict[str, str] = {}

class FlowResult(BaseModel):
    status: str  # "passed" | "failed"
    steps_completed: int = 0
    error: str | None = None

# Connect with Pydantic data converter
client = await Client.connect(
    "localhost:7233",
    data_converter=pydantic_data_converter,
)
```

### 3.9 Testing

```python
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

async def test_device_flow():
    # Time-skipping test environment (auto-advances timers)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DeviceAutomationFlow],
            activities=[tap_element, input_text, assert_element],
        ):
            result = await env.client.execute_workflow(
                DeviceAutomationFlow.run,
                FlowParams(flow_name="test", device_serial="emulator-5554", steps=[...]),
                id="test-wf-1",
                task_queue="test-queue",
            )
            assert result.status == "passed"
            assert result.steps_completed == 3
```

```python
# Mock activities for unit testing
@activity.defn(name="tap_element")
def mock_tap_element(config: TapConfig) -> TapResult:
    return TapResult(success=True, bounds={"x": 100, "y": 200})

async def test_with_mock_activities():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DeviceAutomationFlow],
            activities=[mock_tap_element, ...],  # pass mocks
        ):
            result = await env.client.execute_workflow(...)
```

### 3.10 Workflow Replay (Determinism Check)

```python
from temporalio.worker import Replayer

async def check_determinism():
    replayer = Replayer(workflows=[DeviceAutomationFlow])

    # Replay specific workflow history
    await replayer.replay_workflow(
        WorkflowHistory.from_json(history_json_string)
    )  # raises NonDeterminismError if code changed incompatibly

    # Replay all past executions
    await replayer.replay_workflows(
        await client.list_workflows("WorkflowType = 'DeviceAutomationFlow'")
            .map_histories()
    )
```

---

## 4. Server Architecture

### 4.1 Components

```
┌───────────────────────────────────────────────────────────┐
│                    Temporal Server (Go)                     │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Frontend    │  │   History    │  │    Matching       │  │
│  │  Service     │  │   Service    │  │    Service        │  │
│  │             │  │             │  │                  │  │
│  │ • gRPC API  │  │ • Event     │  │ • Task Queue     │  │
│  │ • Rate limit│  │   sourcing  │  │   management     │  │
│  │ • Auth      │  │ • State     │  │ • Worker poll    │  │
│  │ • Routing   │  │   machine   │  │ • Task dispatch  │  │
│  │             │  │ • History   │  │ • Partitioning   │  │
│  │             │  │   Shards    │  │                  │  │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘  │
│         │                │                   │             │
│         └────────────────┼───────────────────┘             │
│                          │                                  │
│                 ┌────────▼────────┐                        │
│                 │   Persistence    │                        │
│                 │   (PostgreSQL /  │                        │
│                 │    MySQL /       │                        │
│                 │    Cassandra /   │                        │
│                 │    SQLite dev)   │                        │
│                 └─────────────────┘                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Internal Workers (system background workflows)      │  │
│  │  • Archival • Replication • Cleanup                  │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
          ▲                              ▲
          │ gRPC                         │ gRPC
          │                              │
    ┌─────┴──────┐                 ┌─────┴──────┐
    │   Client    │                 │   Workers   │
    │  (FastAPI)  │                 │  (Python)   │
    └────────────┘                 └────────────┘
```

### 4.2 History Service (quan trọng nhất)

- Workflow executions được phân vào **History Shards** (cố định khi tạo cluster)
- Mỗi shard giữ **Mutable State** (in-memory cache) của các workflows thuộc shard đó
- Xử lý: start, cancel, signal, query, update, task completion
- Mỗi request → xác định new events → append to history → tạo transfer/timer tasks
- **Scaling**: thêm History Service instances, mỗi instance own subset of shards

### 4.3 Matching Service

- Quản lý **Task Queues** mà workers poll
- Queue được chia **partitions** (default 4) cho throughput
- **Forwarding**: tasks/pollers forwarded giữa partitions để match nhanh
- Supports worker-specific routing (sticky task queues)

### 4.4 Persistence Options

| Backend | Use Case | Notes |
|---------|----------|-------|
| **SQLite** | Local dev (`temporal server start-dev`) | Zero config, không scale |
| **PostgreSQL** | Self-hosted production (recommended) | Familiar, ecosystem tốt |
| **MySQL** | Self-hosted production | Alternative to PostgreSQL |
| **Cassandra** | Massive scale (Uber, Netflix) | Most battle-tested, complex ops |
| **Temporal Cloud** | Managed service | No DB management needed |

### 4.5 Deployment Options

```bash
# Option 1: Local dev (zero setup)
brew install temporal
temporal server start-dev
# → gRPC: localhost:7233, Web UI: localhost:8233

# Option 2: Docker Compose (self-hosted)
git clone https://github.com/temporalio/docker-compose
cd docker-compose
docker compose up -d
# → gRPC: localhost:7233, Web UI: localhost:8080

# Option 3: Kubernetes (production)
# Helm chart: https://github.com/temporalio/helm-charts

# Option 4: Temporal Cloud (managed)
# → temporal.io/cloud (mTLS, no ops)
```

---

## 5. Device Farm Integration Architecture

### 5.1 Mapping: Node Engine → Temporal

| Node Engine Concept | Temporal Concept |
|--------------------|-----------------|
| Flow definition (DAG) | **Workflow** class |
| Node execution | **Activity** function |
| Control flow (if/loop/retry) | Python code trong Workflow (deterministic) |
| Flow run | **Workflow Execution** |
| Variable store | Workflow instance variables (auto-persisted) |
| Timeout per node | `start_to_close_timeout` per Activity |
| Retry per node | `RetryPolicy` per Activity |
| Flow scheduling | **Schedule** (cron/calendar/interval) |
| Flow cancel/pause | **Signal** |
| Flow progress query | **Query** |
| Inject data mid-flow | **Signal** hoặc **Update** |
| Parallel (fan-out) | `asyncio.gather` + Child Workflows |
| Flow history/audit | **Event History** (built-in) |

### 5.2 Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Server (Python)                      │
│           /api/flows, /api/devices, /api/runs                │
│           WebSocket: /ws/runs/{id}/live                      │
│                                                               │
│  ┌────────────────────┐   ┌──────────────────────────────┐  │
│  │  Flow CRUD (DB)    │   │  Temporal Client              │  │
│  │  • flow definitions│   │  • start_workflow()           │  │
│  │  • device registry │   │  • signal() / query()         │  │
│  │  PostgreSQL        │   │  • list_workflows()           │  │
│  └────────────────────┘   │  • create_schedule()          │  │
│                            └──────────────┬───────────────┘  │
└───────────────────────────────────────────┼──────────────────┘
                                            │ gRPC
                                            ▼
                               ┌─────────────────────┐
                               │   Temporal Server    │
                               │   (Go binary)        │
                               │   + PostgreSQL       │
                               │   + Web UI (:8233)   │
                               └──────────┬──────────┘
                                          │ gRPC poll
                    ┌─────────────────────┼─────────────────┐
                    │                     │                 │
                    ▼                     ▼                 ▼
           ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
           │  Worker 1     │    │  Worker 2     │    │  Worker N     │
           │  (Python)     │    │  (Python)     │    │  (Python)     │
           │               │    │               │    │               │
           │  Workflows:   │    │               │    │  AI Worker:   │
           │  • DeviceFlow │    │               │    │  • OCR        │
           │               │    │               │    │  • VLM        │
           │  Activities:  │    │               │    │  • Auto-heal  │
           │  • tap        │    │               │    │               │
           │  • swipe      │    │               │    │  (GPU machine)│
           │  • input_text │    │               │    │               │
           │  • screenshot │    │               │    │               │
           │  • assert     │    │               │    │               │
           │  • adb_cmd    │    │               │    │               │
           └───────┬───────┘    └───────┬───────┘    └──────────────┘
                   │                    │
                   ▼                    ▼
           ┌──────────────┐    ┌──────────────┐
           │  Devices      │    │  Devices      │
           │  001-050      │    │  051-100      │
           └──────────────┘    └──────────────┘
```

### 5.3 Worker Routing Strategy

```python
# Worker per device rack / group
# Mỗi rack có worker riêng, task queue riêng

# Worker cho rack A (devices 001-050)
worker_a = Worker(
    client,
    task_queue="rack-a",
    workflows=[DeviceAutomationFlow],
    activities=[tap_element, swipe, input_text, ...],
)

# Worker cho rack B (devices 051-100)
worker_b = Worker(
    client,
    task_queue="rack-b",
    workflows=[DeviceAutomationFlow],
    activities=[tap_element, swipe, input_text, ...],
)

# Worker chuyên cho AI tasks (GPU machine)
worker_ai = Worker(
    client,
    task_queue="ai-tasks",
    workflows=[],
    activities=[call_ai_vision, ocr_extract, auto_heal_selector],
)

# Trong workflow, route AI activities tới AI worker
result = await workflow.execute_activity(
    call_ai_vision,
    config,
    task_queue="ai-tasks",  # route to GPU worker
    start_to_close_timeout=timedelta(seconds=30),
)
```

### 5.4 Flow Definition → Temporal Workflow (Dynamic DSL)

```python
@workflow.defn
class DynamicNodeFlow:
    """Execute node-based flow definition dynamically"""

    @workflow.run
    async def run(self, flow_def: FlowDefinition) -> FlowResult:
        context = FlowContext(
            variables=flow_def.initial_variables,
            device_serial=flow_def.device_serial,
        )
        results = {}

        # Walk nodes in order (simplified — real impl uses DAG topo sort)
        node_order = self._topological_sort(flow_def.nodes, flow_def.edges)

        for node_id in node_order:
            node = flow_def.nodes[node_id]

            if node.type.startswith("control."):
                # Control flow: execute in workflow (deterministic)
                next_node = self._eval_control_flow(node, context, results)
                # Skip pruned branches
                continue

            # Action/UI/Data/Device/Network/AI/Debug nodes → Activity
            result = await workflow.execute_activity(
                execute_node,  # generic activity dispatcher
                NodeExecParams(
                    node_type=node.type,
                    config=node.config,
                    inputs=self._resolve_inputs(node_id, flow_def.edges, results),
                    device_serial=context.device_serial,
                ),
                start_to_close_timeout=timedelta(ms=node.timeout_ms),
                retry_policy=RetryPolicy(
                    maximum_attempts=node.retry.get("max", 1) + 1,
                    initial_interval=timedelta(ms=node.retry.get("delay_ms", 1000)),
                ),
            )

            results[node_id] = result
            context.variables.update(result.output_variables)

            if result.status == "failed" and node.on_error == "fail":
                return FlowResult(status="failed", error=result.error, results=results)

        return FlowResult(status="passed", results=results)
```

---

## 6. Determinism Rules (Critical)

### Những gì KHÔNG được làm trong Workflow code

| Violation | Tại sao | Thay thế |
|-----------|---------|----------|
| `import random` | Khác kết quả mỗi replay | `workflow.random()` |
| `datetime.now()` | Khác thời gian mỗi replay | `workflow.now()` |
| `time.sleep(5)` | Blocking, không durable | `await asyncio.sleep(5)` (server-side timer) |
| `requests.get(url)` | Side effect, network I/O | Đưa vào Activity |
| `d.click(x, y)` | Side effect, device I/O | Đưa vào Activity |
| `open("file.txt")` | Side effect, file I/O | Đưa vào Activity |
| `threading.Thread()` | Non-deterministic | `asyncio.create_task()` |
| `os.environ["KEY"]` | Có thể khác giữa replays | Pass as workflow input |
| Iterate `set()` | Ordering không deterministic | Dùng `list` hoặc `sorted()` |
| Global mutable state | Shared giữa workflow instances | Instance variables |

### Sandbox

- Python SDK chạy workflow trong **sandbox** mặc định
- Sandbox detect non-deterministic calls và raise error
- Third-party libraries cần `workflow.unsafe.imports_passed_through()` để bypass sandbox re-import
- Có thể disable: `@workflow.defn(sandboxed=False)` (không recommend cho production)

---

## 7. Observability & Monitoring

### 7.1 Temporal Web UI (built-in)

```
http://localhost:8233
```

- List all workflow executions (filter by type, status, time, search attributes)
- View event history per workflow (every step recorded)
- View workflow input/output/signals/queries
- Cancel/terminate workflows from UI
- Namespace management

### 7.2 Search Attributes

```python
# Define custom search attributes khi start workflow
handle = await client.start_workflow(
    DeviceAutomationFlow.run,
    params,
    id="flow-001",
    task_queue="device-automation",
    search_attributes={
        "device_id": [device_serial],
        "flow_name": ["login_test"],
        "device_model": ["Pixel 7"],
        "priority": [1],
    },
)

# Query workflows by search attributes
async for wf in client.list_workflows(
    'device_id = "device_001" AND flow_name = "login_test" AND ExecutionStatus = "Running"'
):
    print(wf.id, wf.status)
```

### 7.3 Metrics (Prometheus)

```python
from temporalio.runtime import Runtime, TelemetryConfig, PrometheusConfig

# Expose Prometheus metrics endpoint
runtime = Runtime(telemetry=TelemetryConfig(
    metrics=PrometheusConfig(bind_address="0.0.0.0:9090")
))
client = await Client.connect("localhost:7233", runtime=runtime)

# Key metrics:
# temporal_workflow_task_execution_latency
# temporal_activity_execution_latency
# temporal_workflow_completed
# temporal_activity_schedule_to_start_latency (queue congestion indicator)
```

### 7.4 OpenTelemetry Tracing

```python
from temporalio.contrib.opentelemetry import TracingInterceptor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

client = await Client.connect(
    "localhost:7233",
    interceptors=[TracingInterceptor()],
)
# → Traces visible in Jaeger/Zipkin/Datadog
```

---

## 8. Scaling & Performance

### 8.1 Scaling Dimensions

| Dimension | How to Scale | Temporal Mechanism |
|-----------|-------------|-------------------|
| Concurrent workflows | Millions supported | History Shards partition load |
| Worker throughput | Add worker processes/machines | Workers scale horizontally |
| Activity concurrency | `max_concurrent_activities` on Worker | Per-worker throttling |
| Task queue throughput | Increase partitions | `partitions_per_build_id` |
| Long-running workflows | `continue_as_new` | Reset history, fresh start |
| Geographic distribution | Multi-cluster replication | Temporal Cloud multi-region |

### 8.2 Device Farm Scaling Plan

| Scale | Temporal Config | Workers |
|-------|----------------|---------|
| **10 devices** | Local dev server (SQLite) | 1 worker, 10 threads |
| **50 devices** | Docker Compose (PostgreSQL) | 2-3 workers, 20 threads each |
| **200 devices** | K8s deployment, 512 shards | 10 workers (2 per rack) |
| **1000 devices** | K8s HA, 1024+ shards, Temporal Cloud | 50+ workers, sharded by rack + AI workers |

### 8.3 History Size Limits

- Default: **50,000 events** per workflow execution
- Mỗi activity = ~3 events (Scheduled + Started + Completed)
- Flow 50 steps ≈ 150 events → OK
- Flow 1000 steps → cần `continue_as_new` mỗi ~500 steps

```python
@workflow.defn
class LongRunningFlow:
    @workflow.run
    async def run(self, params: FlowParams, start_index: int = 0) -> FlowResult:
        for i in range(start_index, len(params.steps)):
            # Execute step...
            await workflow.execute_activity(...)

            # Every 500 steps, continue-as-new to reset history
            if (i - start_index) >= 500 and i < len(params.steps) - 1:
                workflow.continue_as_new(params, i + 1)

        return FlowResult(status="passed")
```

---

## 9. Limitations & Trade-offs

### 9.1 Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **Determinism constraint** | Steep learning curve, workflow code restricted | Activities cho mọi side effects, sandbox helps catch issues |
| **History shard count immutable** | Phải plan capacity upfront | Start with 512-1024 shards cho production |
| **Sandbox overhead** | CPU/memory cho module re-import | `imports_passed_through()` cho heavy libraries |
| **50K event limit** | Long flows cần split | `continue_as_new` pattern |
| **Operational complexity** | Server + DB + monitoring | Temporal Cloud eliminates, hoặc Docker Compose cho small scale |
| **gRPC only** | Workers phải có gRPC connectivity to server | Same network / VPN |
| **Workflow code evolution** | Changing workflow logic affects running executions | Patching API, versioning |
| **gevent incompatibility** | Conflict với asyncio event loop | Dùng asyncio native |

### 9.2 Temporal vs Celery Decision Matrix (cho Device Farm)

| Criteria | Temporal Wins | Celery Wins |
|----------|-------------|-------------|
| Flow chạy > 5 phút | ✓ Durable, server-side timers | |
| Resume sau crash | ✓ Auto-resume từ exact step | |
| Complex control flow (if/loop/retry) | ✓ Native Python code | |
| Fan-out 100 devices | ✓ Child workflows + gather | |
| Visibility (đang chạy gì, step nào) | ✓ Web UI + queries | |
| Signal mid-flow (inject OTP, pause) | ✓ First-class signals | |
| Scheduling (cron) | ✓ First-class Schedules | |
| Simple fire-and-forget tasks | | ✓ Simpler model |
| Minimal infrastructure | | ✓ Redis only |
| Learning curve | | ✓ Much simpler |
| Team already knows Celery | | ✓ No retraining |

**Recommendation:** Temporal cho orchestration (flow execution), có thể giữ Celery cho simple background tasks (screenshot cleanup, report generation).

---

## 10. Getting Started Checklist

### Phase 1: Local Development

```bash
# 1. Install Temporal server
brew install temporal
temporal server start-dev
# Web UI: http://localhost:8233

# 2. Install Python SDK
pip install temporalio

# 3. Create first workflow + activity
# → See Section 3.2 and 3.3

# 4. Run worker
python worker.py

# 5. Start workflow from FastAPI
python -c "
import asyncio
from temporalio.client import Client
async def main():
    client = await Client.connect('localhost:7233')
    result = await client.execute_workflow(...)
asyncio.run(main())
"
```

### Phase 2: Integration với Device Farm

1. Define Activity functions wrapping existing device interaction code (u2, adb)
2. Create Workflow classes cho từng flow type (login_test, smoke_test, etc.)
3. Add Temporal Client vào FastAPI server
4. Add Worker startup vào `main.py`
5. Replace Celery dispatch with Temporal `start_workflow`

### Phase 3: Production

1. Deploy Temporal Server (Docker Compose hoặc K8s)
2. PostgreSQL cho persistence
3. Configure History Shards (512+ cho growth)
4. Add Prometheus metrics + Grafana dashboards
5. Setup search attributes cho flow/device filtering
6. Worker-specific task queues per device rack

---

## 11. References

| Resource | URL |
|----------|-----|
| GitHub (Server) | https://github.com/temporalio/temporal |
| GitHub (Python SDK) | https://github.com/temporalio/sdk-python |
| Python SDK Samples | https://github.com/temporalio/samples-python |
| Documentation | https://docs.temporal.io |
| Python SDK API Reference | https://python.temporal.io |
| Web UI | http://localhost:8233 (local dev) |
| Temporal Cloud | https://temporal.io/cloud |

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD — core concepts, Python SDK, architecture, device farm integration | Architect |
