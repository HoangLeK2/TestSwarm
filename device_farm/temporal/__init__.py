"""
temporal/ — Temporal workflow orchestration for scenario execution (DF-002)
           and scheduled cron execution (DF-008).

Provides durable, fault-tolerant scenario execution with:
- Automatic retry on device disconnect
- Pause/resume/cancel via signals
- Real-time progress queries
- Nested control flow (repeat, if_element, if_variable, random_pick)
- Cron-based schedule triggering with random delay and device stagger

Import concrete symbols from submodules (temporal.workflows, temporal.worker,
…). Keep this package __init__ free of workflow imports so Temporal's
workflow sandbox does not re-enter temporal.worker during multi-worker boot.
"""

__all__ = [
    "DeviceActivities",
    "RelayOnboardingActivities",
    "RelayOnboardingWorkflow",
    "ScheduleActivities",
    "ScenarioWorkflow",
    "ScenarioStepsWorkflow",
    "ScheduleRunWorkflow",
    "create_temporal_worker",
    "start_temporal_worker",
]


def __getattr__(name: str):
    if name == "DeviceActivities":
        from .activities import DeviceActivities
        return DeviceActivities
    if name == "RelayOnboardingActivities":
        from .relay_onboarding_activities import RelayOnboardingActivities
        return RelayOnboardingActivities
    if name == "RelayOnboardingWorkflow":
        from .relay_onboarding_workflows import RelayOnboardingWorkflow
        return RelayOnboardingWorkflow
    if name == "ScheduleActivities":
        from .schedule_activities import ScheduleActivities
        return ScheduleActivities
    if name in ("ScenarioWorkflow", "ScenarioStepsWorkflow"):
        from .workflows import ScenarioStepsWorkflow, ScenarioWorkflow
        return ScenarioWorkflow if name == "ScenarioWorkflow" else ScenarioStepsWorkflow
    if name == "ScheduleRunWorkflow":
        from .schedule_workflow import ScheduleRunWorkflow
        return ScheduleRunWorkflow
    if name in ("create_temporal_worker", "start_temporal_worker"):
        from .worker import create_temporal_worker, start_temporal_worker
        return create_temporal_worker if name == "create_temporal_worker" else start_temporal_worker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
