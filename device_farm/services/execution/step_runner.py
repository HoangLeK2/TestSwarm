"""Shared step execution with DF-T-04-011 retry policy (executor + Temporal activities)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, TYPE_CHECKING

from services.campaign.failure_classification import annotate_step_failure
from services.execution.retry_policy import (
    compute_wait_ms,
    emit_retry_metrics,
    is_step_failure_retryable,
    parse_step_retry_policy,
    record_attempt,
)
from services.execution.reason_codes import (
    HANDLER_EXCEPTION,
    INCIDENT_RECOVERY_FAILED,
    STALE_FRAME,
    STUCK_SCREEN,
)
from tasks.scenario.capture import StaleFrameError, capture_fail_step, capture_pre_step, capture_post_step
from tasks.scenario.steps import dispatch_step

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

_U2_TRANSIENT_AUTO_ATTEMPTS = 3
_U2_TRANSIENT_BACKOFF_MS = 2500
_U2_TRANSIENT_BACKOFF_CAP_MS = 10_000


def _cancel_event(sc: "ScenarioContext") -> Any:
    ev = getattr(sc, "cancel_event", None)
    if ev is not None and callable(getattr(ev, "is_set", None)):
        try:
            state = ev.is_set()
        except Exception:
            return None
        if not isinstance(state, bool):
            return None
        return ev
    return None


class _StepDeadlineEvent:
    def __init__(self, parent: Any, timeout_s: float) -> None:
        self._parent = parent
        self._deadline = threading.Event()
        self._timer = threading.Timer(max(0.001, timeout_s), self._deadline.set)
        self._timer.daemon = True
        self._timer.start()

    def _parent_set(self) -> bool:
        if self._parent is None or not callable(getattr(self._parent, "is_set", None)):
            return False
        try:
            return bool(self._parent.is_set())
        except Exception:
            return False

    def is_set(self) -> bool:
        return self._deadline.is_set() or self._parent_set()

    def wait(self, timeout: float | None = None) -> bool:
        if self.is_set():
            return True
        until = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        while True:
            if self.is_set():
                return True
            if until is None:
                chunk = 0.05
            else:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    return self.is_set()
                chunk = min(remaining, 0.01)
            if self._deadline.wait(chunk):
                return True

    @property
    def deadline_triggered(self) -> bool:
        return self._deadline.is_set() and not self._parent_set()

    def cancel(self) -> None:
        self._timer.cancel()


def _recovery_timeout_ms(sc: "ScenarioContext", step: Dict[str, Any], idx: int) -> int:
    try:
        from services.execution.recovery_runner import recovery_timeout_ms_for_step

        return int(recovery_timeout_ms_for_step(sc, step, idx) or 0)
    except Exception as exc:
        log.debug("[%s] step#%d recovery timeout lookup failed: %s", sc.serial, idx + 1, exc)
        return 0


def _mark_u2_transient(step_result: Dict[str, Any]) -> bool:
    if step_result.get("ok", True):
        return False
    annotate_step_failure(step_result, step_type=str(step_result.get("type") or ""))
    return step_result.get("failure_class") == "u2_transient"


def _u2_transient_wait_ms(attempt: int) -> int:
    raw = _U2_TRANSIENT_BACKOFF_MS * (2 ** max(0, attempt - 1))
    return min(raw, _U2_TRANSIENT_BACKOFF_CAP_MS)


def _trigger_u2_transient_recovery(sc: "ScenarioContext") -> None:
    device = getattr(sc, "device", None)
    recover = getattr(device, "_recover_u2_ws_mode", None)
    if callable(recover):
        try:
            recover()
        except Exception as exc:
            log.debug("[%s] u2 transient recovery trigger failed: %s", sc.serial, exc)


def _record_recovery_failure(
    step_result: Dict[str, Any],
    recovery_message: str | None,
) -> None:
    msg = str(recovery_message or "").strip()
    if not msg:
        return
    step_result["recovery_failed_message"] = msg
    if not str(step_result.get("message") or "").strip():
        step_result["message"] = msg
    step_result.setdefault("reason_code", INCIDENT_RECOVERY_FAILED)


def _carry_capture_evidence(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """Move capture evidence from a previous result dict into the current one.

    Two places used to drop it. The pre-step capture writes into a result dict
    that the handler's `merged` then replaces wholesale, and every retry started
    from a bare dict — so a step that failed twice and then passed left no
    screenshot behind at all, and a step that failed for good kept only the last
    attempt's frame.
    """
    if not isinstance(src, dict) or src is dst:
        return dst
    carried = [a for a in (src.get("artifacts") or []) if isinstance(a, dict)]
    if carried:
        existing = [a for a in (dst.get("artifacts") or []) if isinstance(a, dict)]
        artifacts = carried + [a for a in existing if a not in carried]
        dst["artifacts"] = artifacts
        dst["artifacts_json"] = artifacts
    # screenshot_pre only. capture_error belongs to the attempt that hit it —
    # carrying it forward would leave a stale error on an attempt whose capture
    # actually worked.
    if "screenshot_pre" in src and "screenshot_pre" not in dst:
        dst["screenshot_pre"] = src["screenshot_pre"]
    return dst


_LEDGER_EVIDENCE_FIELDS = (
    "type",
    "step_index",
    "attempt_index",
    "captured_at",
    "screenshot_artifact_id",
    "screenshot_object_key",
    "hierarchy_artifact_id",
    "hierarchy_object_key",
)


def _attach_ledger_evidence(sc: "ScenarioContext", step_result: Dict[str, Any]) -> None:
    """Point the account action at the screenshot of its own failure.

    The ledger row is written by the step handler; the failure screenshot is
    taken here, after the handler returns. Nothing connected the two, so
    ``account_actions.artifact_refs`` was empty on every row that ever existed
    and the log could name an action without showing what went wrong.

    References only — the artifact rows hold the bytes.
    """
    ledger = step_result.get("account_action_ledger")
    if not isinstance(ledger, dict):
        return
    action_id = str(ledger.get("action_id") or "").strip()
    org_id = str(ledger.get("org_id") or "").strip()
    if not action_id or not org_id:
        return
    from services.execution.step_store import extract_artifacts_json

    refs = [
        {k: art[k] for k in _LEDGER_EVIDENCE_FIELDS if art.get(k) is not None}
        for art in extract_artifacts_json(step_result)
    ]
    refs = [ref for ref in refs if ref.get("screenshot_artifact_id") or ref.get("screenshot_object_key")]
    if not refs:
        return
    try:
        from services.account_actions import attach_action_artifacts

        attach_action_artifacts(org_id=org_id, action_id=action_id, artifact_refs=refs)
    except Exception as exc:  # pragma: no cover - evidence is never fatal
        log.debug("[%s] ledger evidence attach skipped: %s", sc.serial, exc)


def _run_app_popup_watchers(sc: "ScenarioContext", step: Dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from tasks.scenario.app_automation_watchers import run_app_popup_watchers

        return run_app_popup_watchers(sc, step)
    except Exception as exc:
        log.debug("[%s] app popup watcher hook failed: %s", sc.serial, exc)
        return [{"executed": False, "message": f"watcher hook failed: {exc}"}]


def execute_step_with_retry(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    idx: int,
    *,
    trace_log: Any = None,
) -> tuple[Dict[str, Any], int]:
    """Run one step with optional per-step retry policy. Returns (step_result, attempts_used)."""
    trace = trace_log or log
    t = step.get("type")
    step_result: Dict[str, Any] = {"index": idx, "type": t, "ok": True}

    capture_pre_step(sc, step, idx, step_result, attempt_index=1)
    step_start_t = time.monotonic()

    retry_policy = parse_step_retry_policy(step)
    max_attempts = retry_policy.max_attempts if retry_policy else 1
    loop_attempt_limit = max(max_attempts, _U2_TRANSIENT_AUTO_ATTEMPTS)

    attempts_used = 0
    attempt_records: list[Dict[str, Any]] = []
    pending_recovery_events: list[Dict[str, Any]] = []
    recovery_incident_key: str | None = None
    u2_transient_recovery_started = False
    attempt = 0
    force_recovery_retry = False
    while attempt < loop_attempt_limit or force_recovery_retry:
        attempt += 1
        force_recovery_retry = False
        step["_account_action_retry_attempt"] = attempt
        cancel_event = _cancel_event(sc)
        if cancel_event is not None and cancel_event.is_set():
            # Same reason as the retry sites: a bare dict here would throw away
            # the screenshots taken while the step was already failing.
            return _carry_capture_evidence(
                {
                    "index": idx,
                    "type": t,
                    "ok": False,
                    "message": f"{t}: cancelled by user",
                    "cancelled": True,
                },
                step_result,
            ), attempts_used
        attempts_used = attempt
        original_cancel_event = getattr(sc, "cancel_event", None)
        deadline_event: _StepDeadlineEvent | None = None
        deadline_ms = _recovery_timeout_ms(sc, step, idx)
        if deadline_ms > 0:
            deadline_event = _StepDeadlineEvent(original_cancel_event, deadline_ms / 1000.0)
            try:
                sc.cancel_event = deadline_event
            except Exception:
                deadline_event.cancel()
                deadline_event = None
        watcher_events = _run_app_popup_watchers(sc, step)
        try:
            handler_result = dispatch_step(sc, step, idx)
        except Exception as exc:
            handler_result = {
                "ok": False,
                "message": f"{t}: handler raised: {exc}",
                "reason_code": HANDLER_EXCEPTION,
            }
            log.exception(f"[{sc.serial}] step#{idx + 1} handler raised")
        finally:
            if deadline_event is not None:
                try:
                    sc.cancel_event = original_cancel_event
                except Exception:
                    pass

        merged: Dict[str, Any] = {"index": idx, "type": t, "ok": True}
        merged.update(handler_result)
        # Carried after update so a handler that sets its own artifacts wins on
        # conflict but does not erase what the pre-capture already recorded.
        _carry_capture_evidence(merged, step_result)
        if watcher_events:
            merged["app_popup_watchers"] = watcher_events
        if deadline_event is not None:
            timed_out = deadline_event.deadline_triggered
            deadline_event.cancel()
            if timed_out:
                merged["ok"] = False
                merged["reason_code"] = STUCK_SCREEN
                merged["timed_out"] = True
                merged["recovery_timeout_ms"] = deadline_ms
                merged["message"] = f"{t}: recovery timeout after {deadline_ms}ms"

        stale_raised = False
        post_sync = not merged.get("ok", True)
        try:
            capture_post_step(
                sc, step, idx, merged, step_start_t,
                attempt_index=attempt, sync=post_sync,
            )
        except StaleFrameError as sfe:
            stale_raised = True
            merged["ok"] = False
            merged["reason_code"] = STALE_FRAME
            merged["retryable"] = True
            merged["message"] = f"{t}: {sfe}"
            log.warning(f"[{sc.serial}] step#{idx + 1}: {sfe}")

        if not merged.get("ok", True):
            annotate_step_failure(merged, step_type=str(t or ""))
        u2_transient = _mark_u2_transient(merged)
        if u2_transient and not u2_transient_recovery_started:
            _trigger_u2_transient_recovery(sc)
            u2_transient_recovery_started = True
        auto_retry_u2_transient = (
            u2_transient
            and retry_policy is None
            and attempt < _U2_TRANSIENT_AUTO_ATTEMPTS
        )
        explicit_retry = (
            retry_policy is not None
            and is_step_failure_retryable(merged, retry_policy)
            and attempt < max_attempts
        )
        will_retry = explicit_retry or auto_retry_u2_transient
        if not merged.get("ok", True) and not auto_retry_u2_transient:
            if recovery_incident_key:
                merged["_recovery_incident_key"] = recovery_incident_key
            try:
                from services.execution.recovery_runner import maybe_recover_step

                recovery = maybe_recover_step(sc, step, idx, merged)
            except Exception as exc:
                recovery = None
                log.exception("[%s] step#%d recovery hook failed: %s", sc.serial, idx + 1, exc)
            if merged.get("_recovery_incident_key"):
                recovery_incident_key = str(merged["_recovery_incident_key"])
            if recovery is not None and recovery.events:
                existing_events = list(merged.get("recovery_events") or [])
                merged["recovery_events"] = [*existing_events, *recovery.events]
                pending_recovery_events.extend(recovery.events)
            cancel_event = _cancel_event(sc)
            if cancel_event is not None and cancel_event.is_set():
                merged["cancelled"] = True
                merged["ok"] = False
                merged["message"] = f"{t}: cancelled by user"
                step_result = merged
                break
            if recovery is not None and recovery.handled:
                merged["recovery_handled"] = True
                if recovery.continue_step:
                    merged["ok"] = True
                    merged["message"] = f"{t}: incident recovered; continuing"
                    will_retry = False
                elif recovery.retry_step:
                    trace.info(
                        "step_recovery_retry",
                        trace_id=sc.trace_id,
                        serial=sc.serial,
                        step_index=idx + 1,
                        step_type=t,
                    )
                    step_result = _carry_capture_evidence(
                        {"index": idx, "type": t, "ok": True}, merged
                    )
                    force_recovery_retry = True
                    capture_pre_step(sc, step, idx, step_result, attempt_index=attempt + 1)
                    step_start_t = time.monotonic()
                    continue
                elif recovery.fail_message:
                    _record_recovery_failure(merged, recovery.fail_message)

        if will_retry:
            if explicit_retry and retry_policy is not None:
                wait = compute_wait_ms(attempt, retry_policy)
                wait_ms = wait.wait_ms
                backoff_capped = wait.backoff_capped
            else:
                wait_ms = _u2_transient_wait_ms(attempt)
                backoff_capped = wait_ms >= _U2_TRANSIENT_BACKOFF_CAP_MS
            emit_retry_metrics(
                step_type=str(t or "unknown"),
                reason_code=merged.get("reason_code"),
                backoff_capped=backoff_capped,
            )
            record_attempt(
                attempt_records,
                attempt=attempt,
                error_reason=str(merged.get("reason_code") or ""),
                wait_ms_before_next=wait_ms,
            )
            trace.info(
                "step_retry",
                trace_id=sc.trace_id,
                serial=sc.serial,
                step_index=idx + 1,
                step_type=t,
                attempt=attempt,
                max_attempts=max_attempts,
                reason_code=merged.get("reason_code"),
                backoff_ms=wait_ms,
                stale_frame=stale_raised,
            )
            wait_s = wait_ms / 1000.0
            cancel_event = _cancel_event(sc)
            if cancel_event is not None:
                if cancel_event.wait(wait_s):
                    merged["cancelled"] = True
                    merged["ok"] = False
                    merged["message"] = f"{t}: cancelled by user"
                    step_result = merged
                    if attempt_records:
                        attempt_records[-1]["wait_ms_before_next"] = None
                        attempt_records[-1]["cancelled"] = True
                    if attempt_records:
                        step_result["retry_attempts"] = attempt_records
                    break
            else:
                time.sleep(wait_s)
            step_result = _carry_capture_evidence(
                {"index": idx, "type": t, "ok": True}, merged
            )
            capture_pre_step(sc, step, idx, step_result, attempt_index=attempt + 1)
            step_start_t = time.monotonic()
            continue

        record_attempt(
            attempt_records,
            attempt=attempt,
            error_reason=str(merged.get("reason_code") or "") if not merged.get("ok", True) else None,
            wait_ms_before_next=None,
        )
        step_result = merged
        if pending_recovery_events:
            current_events = list(step_result.get("recovery_events") or [])
            def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                return (
                    event.get("event_type"),
                    payload.get("incident_key"),
                    payload.get("incident_type"),
                    payload.get("attempt"),
                    payload.get("outcome"),
                )

            seen = {
                _event_key(event)
                for event in current_events
                if isinstance(event, dict)
            }
            for event in pending_recovery_events:
                if not isinstance(event, dict):
                    continue
                key = _event_key(event)
                if key not in seen:
                    current_events.append(event)
                    seen.add(key)
            step_result["recovery_events"] = current_events
        if not step_result.get("ok", True):
            capture_fail_step(sc, step, idx, step_result, attempt_index=attempt)
            _attach_ledger_evidence(sc, step_result)
        if attempt_records:
            step_result["retry_attempts"] = attempt_records
        break

    return step_result, attempts_used
