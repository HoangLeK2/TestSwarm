"""Step handlers for app automation profile flows."""
from __future__ import annotations

import time
from typing import Any, Dict

from common.totp import generate_totp
from services.app_automation_locator import (
    LocatorResolution,
    build_hierarchy_snapshot,
    resolve_semantic_locator,
)
from services.app_automation_profile import (
    AppAutomationProfile,
    FormRecipe,
    ManualLoginChallenge,
    LoginPostSubmitAction,
    LoginSubmit,
    validate_app_automation_profile,
)
from services.scenario_selector import ScenarioSelectorSpec
from tasks.scenario.context import ScenarioContext
from tasks.scenario.steps import register_step
from tasks.scenario.steps.input import handle_input_selector
from tasks.scenario.utils import _get_implicit_wait_config, _retry_find_element


_ACCOUNT_REF_TO_VAR = {
    "account.id": "__ACCOUNT_ID__",
    "account.username": "__ACCOUNT_USERNAME__",
    "account.display_name": "__ACCOUNT_DISPLAY_NAME__",
    "account.platform": "__ACCOUNT_PLATFORM__",
    "account.password": "__ACCOUNT_PASSWORD__",
    "account.email": "__ACCOUNT_EMAIL__",
    "account.totp_code": "__ACCOUNT_TOTP_CODE__",
    "account.auth_code": "__ACCOUNT_TOTP_CODE__",
}

_SECRET_REF_TO_VAR = {
    # Backward compatibility for cloned login templates created before the
    # Facebook profile switched to the explicit account.password reference.
    "secret.login_password": "__ACCOUNT_PASSWORD__",
}

def _load_profile(sc: ScenarioContext, step: Dict[str, Any]) -> AppAutomationProfile:
    raw = (
        step.get("profile")
        or step.get("app_automation_profile")
        or sc.scenario.get("app_automation_profile")
        or sc.scenario.get("automation_profile")
    )
    if not isinstance(raw, dict):
        raise ValueError("app automation profile is required")
    return validate_app_automation_profile(raw)


def _value_from_ref(sc: ScenarioContext, value_from: str, idx: int) -> str:
    ref = str(value_from or "").strip()
    if ref in {"account.totp_code", "account.auth_code"}:
        secret = sc.var_ctx.resolve("${__ACCOUNT_TOTP_SECRET__}", step_index=idx)
        if secret is not None and str(secret) != "${__ACCOUNT_TOTP_SECRET__}" and str(secret).strip():
            try:
                return generate_totp(str(secret))
            except Exception:
                return ""
        var_name = "__ACCOUNT_TOTP_CODE__"
    elif ref in _ACCOUNT_REF_TO_VAR:
        var_name = _ACCOUNT_REF_TO_VAR[ref]
    elif ref in _SECRET_REF_TO_VAR:
        var_name = _SECRET_REF_TO_VAR[ref]
    elif ref.startswith(("variables.", "scenario.", "secret.")):
        var_name = ref.split(".", 1)[1]
    else:
        raise ValueError(f"unsupported value_from reference: {ref!r}")
    value = sc.var_ctx.resolve(f"${{{var_name}}}", step_index=idx)
    if value is None or str(value) == f"${{{var_name}}}":
        raise ValueError(f"value_from {ref!r} is unresolved")
    return str(value)


def _current_snapshot(sc: ScenarioContext) -> tuple[str, Any]:
    xml = sc.device.hierarchy_xml(force_refresh=True)
    if not xml:
        raise RuntimeError("empty hierarchy XML")
    return xml, build_hierarchy_snapshot(xml)


def _snapshot_has_any_text(snapshot: Any, texts: list[str]) -> bool:
    needles = [str(text).strip().lower() for text in texts if str(text).strip()]
    if not needles:
        return False
    for node in snapshot.nodes:
        haystack = f"{node.text} {node.desc}".lower()
        if any(needle in haystack for needle in needles):
            return True
    return False


def _snapshot_has_any_exact_text(snapshot: Any, texts: list[str]) -> bool:
    needles = {str(text).strip().casefold() for text in texts if str(text).strip()}
    if not needles:
        return False
    for node in snapshot.nodes:
        values = {
            str(node.text or "").strip().casefold(),
            str(node.desc or "").strip().casefold(),
        }
        if needles.intersection(values):
            return True
    return False


def _selector_spec(selector: Dict[str, Any]) -> ScenarioSelectorSpec:
    return ScenarioSelectorSpec(
        by=str(selector.get("by") or "text"),
        value=str(selector.get("value") or ""),
    )


def _resolution_trace(resolution: LocatorResolution) -> Dict[str, Any]:
    return {
        "matched": resolution.matched,
        "locator_name": resolution.locator_name,
        "score": round(float(resolution.score), 3),
        "reason": resolution.reason,
        "fallback_level": resolution.fallback_level,
        "candidate_count": resolution.candidate_count,
        "selector": resolution.selector,
        "bounds": resolution.bounds,
    }


def _locator_uses_ocr(profile: AppAutomationProfile, locator_name: str) -> bool:
    locator = profile.semantic_locators.get(locator_name)
    if locator is None:
        return False
    return any(bool(candidate.ocr_near) for candidate in locator.candidates)


def _ocr_results_for_locator(sc: ScenarioContext) -> list[dict[str, Any]]:
    device = sc.device
    if not getattr(device, "ocr_supported", None) or not device.ocr_supported():
        return []
    request_ocr = getattr(device, "request_ocr", None)
    if request_ocr is None:
        return []
    reply = request_ocr(
        languages=["vi", "en"],
        min_confidence=0.5,
        want_image_on_empty=False,
        timeout=10.0,
        cancel_event=sc.cancel_event,
    )
    if not isinstance(reply, dict) or not reply.get("ok"):
        return []
    results = reply.get("results") or []
    return results if isinstance(results, list) else []


def _resolve_named_locator(
    sc: ScenarioContext,
    profile: AppAutomationProfile,
    locator_name: str,
    xml: str,
    snapshot: Any,
) -> LocatorResolution:
    ocr_results = (
        _ocr_results_for_locator(sc)
        if _locator_uses_ocr(profile, locator_name)
        else None
    )
    return resolve_semantic_locator(
        profile,
        locator_name,
        xml,
        screen=(sc.w, sc.h),
        snapshot=snapshot,
        ocr_results=ocr_results,
    )


def _click_resolution(
    sc: ScenarioContext,
    step: Dict[str, Any],
    resolution: LocatorResolution,
) -> None:
    if not resolution.matched:
        raise RuntimeError(f"locator {resolution.locator_name!r} not resolved: {resolution.reason}")
    u2 = sc.device.u2
    if u2 is None:
        sc.device.ensure_u2_healthy()
        u2 = sc.device.u2
    if u2 is None:
        raise RuntimeError("u2 not available")

    if resolution.selector:
        spec = _selector_spec(resolution.selector)
        by, value = spec.primary_by_value()
        iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
        eid = _retry_find_element(
            u2,
            by,
            value,
            timeout=iw_timeout,
            poll=iw_poll,
            cancel_event=sc.cancel_event,
            spec=spec,
            device=sc.device,
        )
        if isinstance(eid, dict):
            eid = eid.get("eid")
        if not eid:
            raise RuntimeError(f"element not visible after {iw_timeout:.0f}s: {resolution.locator_name}")
        u2.element_click(eid)
        return

    if resolution.bounds:
        left = int(resolution.bounds["left"])
        top = int(resolution.bounds["top"])
        right = int(resolution.bounds["right"])
        bottom = int(resolution.bounds["bottom"])
        sc.device.tap((left + right) // 2, (top + bottom) // 2)
        return

    raise RuntimeError(f"locator {resolution.locator_name!r} has no selector or bounds")


def _input_named_locator(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    profile: AppAutomationProfile,
    locator_name: str,
    text: str,
    xml: str,
    snapshot: Any,
) -> Dict[str, Any]:
    resolution = _resolve_named_locator(sc, profile, locator_name, xml, snapshot)
    if not resolution.matched:
        raise RuntimeError(f"input locator {locator_name!r} failed: {resolution.reason}")
    return _input_resolved_locator(sc, step, idx, locator_name, resolution, text)


def _input_resolved_locator(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    locator_name: str,
    resolution: LocatorResolution,
    text: str,
) -> Dict[str, Any]:
    if _cancelled(sc):
        raise RuntimeError(f"input {locator_name!r} cancelled")
    if resolution.selector:
        input_step = {
            "type": "input_selector",
            "selector": resolution.selector,
            "text": text,
            "clear_first": bool(step.get("clear_first", True)),
            "implicit_wait": step.get("implicit_wait"),
        }
        input_result: Dict[str, Any] = {"index": idx, "type": "input_selector", "ok": True}
        handle_input_selector(sc, input_step, idx, input_result)
        if not input_result.get("ok", True):
            raise RuntimeError(input_result.get("message") or f"input {locator_name!r} failed")
    else:
        _click_resolution(sc, step, resolution)
        if _cancelled(sc):
            raise RuntimeError(f"input {locator_name!r} cancelled")
        u2 = sc.device.u2
        if u2 is None:
            raise RuntimeError("u2 not available after coordinate focus")
        if bool(step.get("clear_first", True)):
            u2.clear_text()
        if _cancelled(sc):
            raise RuntimeError(f"input {locator_name!r} cancelled")
        u2.send_keys(text)
    return _resolution_trace(resolution)


def _field_required(field: Any) -> bool:
    return bool(getattr(field, "required", True))


def _input_login_field_if_present(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    profile: AppAutomationProfile,
    field_name: str,
    field: Any,
    xml: str,
    snapshot: Any,
) -> tuple[bool, Dict[str, Any]]:
    resolution = _resolve_named_locator(sc, profile, field.locator, xml, snapshot)
    if not resolution.matched:
        trace = _resolution_trace(resolution)
        trace["skipped"] = not _field_required(field)
        if not _field_required(field):
            return False, trace
        raise RuntimeError(f"input locator {field.locator!r} failed: {resolution.reason}")

    try:
        value = _value_from_ref(sc, field.value_from, idx)
    except ValueError as exc:
        if field_name in {"auth_code", "totp_code", "two_factor_code"}:
            raise ValueError(f"AUTH_CODE_REQUIRED: {exc}") from exc
        raise
    if field_name in {"auth_code", "totp_code", "two_factor_code"} and not str(value).strip():
        raise ValueError("AUTH_CODE_REQUIRED: auth code value is empty")
    return True, _input_resolved_locator(sc, step, idx, field.locator, resolution, value)


def _click_submit(
    sc: ScenarioContext,
    step: Dict[str, Any],
    profile: AppAutomationProfile,
    submit: LoginSubmit,
    xml: str,
    snapshot: Any,
) -> Dict[str, Any]:
    if submit.locator:
        resolution = _resolve_named_locator(sc, profile, submit.locator, xml, snapshot)
        _click_resolution(sc, step, resolution)
        return _resolution_trace(resolution)

    labels = []
    if submit.tap_text:
        labels.append(submit.tap_text)
    labels.extend(submit.tap_text_any)
    visible_labels = {
        str(value or "").strip().casefold()
        for node in snapshot.nodes
        for value in (node.text, node.desc)
        if str(value or "").strip()
    }
    labels.sort(key=lambda label: str(label).strip().casefold() not in visible_labels)
    errors = []
    for label in labels:
        spec = ScenarioSelectorSpec(by="text", value=str(label))
        by, value = spec.primary_by_value()
        u2 = sc.device.u2
        if u2 is None:
            sc.device.ensure_u2_healthy()
            u2 = sc.device.u2
        if u2 is None:
            raise RuntimeError("u2 not available")
        try:
            iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
            eid = _retry_find_element(
                u2,
                by,
                value,
                timeout=iw_timeout,
                poll=iw_poll,
                cancel_event=sc.cancel_event,
                spec=spec,
                device=sc.device,
            )
            if isinstance(eid, dict):
                eid = eid.get("eid")
            if eid:
                u2.element_click(eid)
                return {
                    "matched": True,
                    "locator_name": "submit_text",
                    "score": 1.0,
                    "reason": f"text={label!r}",
                    "fallback_level": "exact",
                    "candidate_count": 1,
                    "selector": {"by": "text", "value": label},
                    "bounds": None,
                }
            errors.append(f"{label!r} not found")
        except Exception as exc:
            errors.append(f"{label!r}: {exc}")
    raise RuntimeError("login submit failed: " + "; ".join(errors))


def _cancelled(sc: ScenarioContext) -> bool:
    return sc.cancel_event is not None and sc.cancel_event.is_set()


def _wait_or_cancel(sc: ScenarioContext, seconds: float) -> bool:
    if seconds <= 0:
        return _cancelled(sc)
    if sc.cancel_event is not None:
        return bool(sc.cancel_event.wait(seconds))
    time.sleep(seconds)
    return False


def _wait_for_post_submit_action(
    sc: ScenarioContext,
    action: LoginPostSubmitAction,
) -> tuple[str, Any] | None:
    deadline = time.monotonic() + float(action.timeout_s)
    while True:
        xml, snapshot = _current_snapshot(sc)
        if action.skip_text_exact_any and _snapshot_has_any_exact_text(
            snapshot, action.skip_text_exact_any
        ):
            return None
        if action.skip_when_text_any and _snapshot_has_any_text(
            snapshot, action.skip_when_text_any
        ):
            return None
        has_condition = bool(action.when_text_any or action.when_text_exact_any)
        if (
            not has_condition
            or _snapshot_has_any_exact_text(snapshot, action.when_text_exact_any)
            or _snapshot_has_any_text(snapshot, action.when_text_any)
        ):
            return xml, snapshot
        if _cancelled(sc) or time.monotonic() >= deadline:
            return None
        _wait_or_cancel(sc, min(float(action.poll_s), max(0.0, deadline - time.monotonic())))


def _execute_post_submit_actions(
    sc: ScenarioContext,
    step: Dict[str, Any],
    profile: AppAutomationProfile,
    actions: list[LoginPostSubmitAction],
) -> list[Dict[str, Any]]:
    traces: list[Dict[str, Any]] = []
    for index, action in enumerate(actions):
        trace: Dict[str, Any] = {
            "index": index,
            "when_text_any": action.when_text_any,
            "when_text_exact_any": action.when_text_exact_any,
            "skip_when_text_any": action.skip_when_text_any,
            "skip_text_exact_any": action.skip_text_exact_any,
            "matched": False,
            "executed": False,
        }
        found = _wait_for_post_submit_action(sc, action)
        if found is None:
            trace["reason"] = "condition_not_visible"
            traces.append(trace)
            continue
        xml, snapshot = found
        trace["matched"] = True
        submit = LoginSubmit(
            tap_text=action.tap_text,
            tap_text_any=action.tap_text_any,
            locator=action.locator,
        )
        trace["action_trace"] = _click_submit(sc, step, profile, submit, xml, snapshot)
        trace["executed"] = True
        if _wait_or_cancel(sc, float(action.wait_after_s)):
            trace["cancelled"] = True
            traces.append(trace)
            break
        traces.append(trace)
    return traces


def _input_post_submit_fields(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    profile: AppAutomationProfile,
    post_submit_fields: Dict[str, Any],
) -> tuple[Dict[str, Any], bool, str, Any]:
    xml, snapshot = _current_snapshot(sc)
    traces: Dict[str, Any] = {}
    entered_post_submit = False
    for field_name, field in post_submit_fields.items():
        entered, trace = _input_login_field_if_present(
            sc, step, idx, profile, field_name, field, xml, snapshot
        )
        traces[field_name] = trace
        if entered:
            entered_post_submit = True
            xml, snapshot = _current_snapshot(sc)
    return traces, entered_post_submit, xml, snapshot


def _detect_logged_in(profile: AppAutomationProfile, snapshot: Any) -> bool:
    recipe = profile.login_recipe
    if recipe is None:
        return False
    detect = recipe.detect_logged_in or {}
    any_text = detect.get("any_text") if isinstance(detect, dict) else None
    if isinstance(any_text, list) and _snapshot_has_any_text(snapshot, [str(item) for item in any_text]):
        return True
    return False


def _resolution_visible_label(snapshot: Any, resolution: LocatorResolution) -> str:
    """Return the visible label of the node selected by a semantic locator."""
    for node in snapshot.nodes:
        if resolution.bounds and node.bounds != resolution.bounds:
            continue
        visible = str(node.text or node.desc or "").strip()
        if visible:
            return visible
    return ""


def _resolve_manual_challenge_controls(
    sc: ScenarioContext,
    profile: AppAutomationProfile,
    challenge: ManualLoginChallenge,
    xml: str,
    snapshot: Any,
) -> tuple[LocatorResolution, LocatorResolution, LocatorResolution]:
    return (
        _resolve_named_locator(
            sc, profile, challenge.detect_locator, xml, snapshot
        ),
        _resolve_named_locator(
            sc, profile, challenge.input_locator, xml, snapshot
        ),
        _resolve_named_locator(
            sc, profile, challenge.submit_locator, xml, snapshot
        ),
    )


def _find_manual_login_challenge(
    sc: ScenarioContext,
    profile: AppAutomationProfile,
    challenges: list[ManualLoginChallenge],
    xml: str,
    snapshot: Any,
) -> tuple[ManualLoginChallenge, LocatorResolution] | None:
    for challenge in challenges:
        resolution = _resolve_named_locator(
            sc, profile, challenge.detect_locator, xml, snapshot
        )
        if resolution.matched:
            return challenge, resolution
    return None


def _manual_input_platform(sc: ScenarioContext) -> str:
    try:
        value = sc.var_ctx.resolve("${__ACCOUNT_PLATFORM__}")
    except Exception:
        return ""
    platform = str(value or "").strip().casefold()
    if not platform or platform == "${__account_platform__}":
        return ""
    return platform


def _handle_manual_login_challenge(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    profile: AppAutomationProfile,
    challenge: ManualLoginChallenge,
    detection: LocatorResolution,
    xml: str,
    snapshot: Any,
) -> tuple[Dict[str, Any], str, Any]:
    prompt = _resolution_visible_label(snapshot, detection) or challenge.prompt
    handler = sc.scenario.get("_manual_input_handler")
    if not callable(handler):
        raise RuntimeError(
            "MANUAL_INPUT_REQUIRED: operator input is required for "
            f"challenge {challenge.name!r}"
        )

    _, input_resolution, submit_resolution = _resolve_manual_challenge_controls(
        sc, profile, challenge, xml, snapshot
    )
    if not input_resolution.matched:
        raise RuntimeError(
            "MANUAL_INPUT_REQUIRED: challenge input could not be identified safely "
            f"({input_resolution.reason})"
        )
    if not submit_resolution.matched:
        raise RuntimeError(
            "MANUAL_INPUT_REQUIRED: challenge submit control could not be "
            f"identified safely ({submit_resolution.reason})"
        )

    request = {
        "kind": challenge.kind,
        "challenge_id": challenge.name,
        "prompt": prompt,
        "package": profile.package,
    }
    platform = _manual_input_platform(sc)
    if platform:
        request["platform"] = platform
    value = str(handler(request) or "").strip()
    if not value:
        raise RuntimeError("MANUAL_INPUT_REQUIRED: operator input is empty")
    if _cancelled(sc):
        raise RuntimeError("MANUAL_INPUT_REQUIRED: operator input cancelled")

    xml, snapshot = _current_snapshot(sc)
    detection, input_resolution, submit_resolution = (
        _resolve_manual_challenge_controls(
            sc, profile, challenge, xml, snapshot
        )
    )
    if not detection.matched:
        raise RuntimeError(
            "MANUAL_INPUT_REQUIRED: challenge screen changed while awaiting input"
        )
    if not input_resolution.matched or not submit_resolution.matched:
        raise RuntimeError(
            "MANUAL_INPUT_REQUIRED: challenge controls changed while awaiting input"
        )
    if _cancelled(sc):
        raise RuntimeError("MANUAL_INPUT_REQUIRED: operator input cancelled")
    _input_resolved_locator(
        sc,
        step,
        idx,
        challenge.input_locator,
        input_resolution,
        value,
    )

    xml, snapshot = _current_snapshot(sc)
    _, input_resolution, submit_resolution = _resolve_manual_challenge_controls(
        sc, profile, challenge, xml, snapshot
    )
    if not input_resolution.matched or not submit_resolution.matched:
        raise RuntimeError(
            "MANUAL_INPUT_REQUIRED: challenge controls changed before submission"
        )
    if _cancelled(sc):
        raise RuntimeError("MANUAL_INPUT_REQUIRED: operator input cancelled")
    _click_resolution(sc, step, submit_resolution)
    _wait_or_cancel(sc, challenge.wait_after_s)
    next_xml, next_snapshot = _current_snapshot(sc)
    return (
        {
            "challenge_id": challenge.name,
            "kind": challenge.kind,
            "prompt": prompt,
            "package": profile.package,
            **({"platform": platform} if platform else {}),
            "submitted": True,
        },
        next_xml,
        next_snapshot,
    )


def _wait_for_manual_login_challenges(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    profile: AppAutomationProfile,
    xml: str,
    snapshot: Any,
) -> tuple[list[Dict[str, Any]], str, Any]:
    """Wait for delayed, profile-declared challenges and operator input."""
    recipe = profile.login_recipe
    challenges = list(recipe.manual_challenges) if recipe else []
    if not challenges:
        return [], xml, snapshot

    timeout_s, poll_s = _get_implicit_wait_config(step, sc.scenario_iw_config)
    deadline = time.monotonic() + timeout_s
    traces: list[Dict[str, Any]] = []
    attempts: dict[str, int] = {}
    waiting_for_result: str | None = None

    while True:
        if _cancelled(sc):
            raise RuntimeError("MANUAL_INPUT_REQUIRED: operator input cancelled")

        detected = _find_manual_login_challenge(
            sc, profile, challenges, xml, snapshot
        )
        now = time.monotonic()
        detected_name = detected[0].name if detected else None
        if detected is not None and (
            waiting_for_result != detected_name or now >= deadline
        ):
            challenge, resolution = detected
            attempt_count = attempts.get(challenge.name, 0)
            if attempt_count >= challenge.max_attempts:
                raise RuntimeError(
                    "MANUAL_INPUT_REQUIRED: challenge "
                    f"{challenge.name!r} remained visible after the maximum "
                    "number of attempts"
                )
            trace, xml, snapshot = _handle_manual_login_challenge(
                sc,
                step,
                idx,
                profile,
                challenge,
                resolution,
                xml,
                snapshot,
            )
            traces.append(trace)
            attempts[challenge.name] = attempt_count + 1
            waiting_for_result = challenge.name
            deadline = time.monotonic() + timeout_s
            continue

        if detected is None and traces:
            return traces, xml, snapshot
        if now >= deadline:
            if detected is None:
                return traces, xml, snapshot
            waiting_for_result = None
            continue

        if _wait_or_cancel(sc, min(poll_s, max(0.0, deadline - now))):
            raise RuntimeError("MANUAL_INPUT_REQUIRED: operator input cancelled")
        xml, snapshot = _current_snapshot(sc)


@register_step("login_if_needed")
def handle_login_if_needed(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        profile = _load_profile(sc, step)
        recipe = profile.login_recipe
        if recipe is None:
            raise ValueError("login_recipe is required")
        xml, snapshot = _current_snapshot(sc)
        if _detect_logged_in(profile, snapshot):
            result.update({"message": "login_if_needed: already logged in", "login_state": "already_logged_in"})
            return
        traces: Dict[str, Any] = {}
        for field_name, field in recipe.fields.items():
            value = _value_from_ref(sc, field.value_from, idx)
            traces[field_name] = _input_named_locator(
                sc, step, idx, profile, field.locator, value, xml, snapshot,
            )
            xml, snapshot = _current_snapshot(sc)
        submit_trace = _click_submit(sc, step, profile, recipe.submit, xml, snapshot)
        post_submit_action_trace: list[Dict[str, Any]] = []
        post_submit_traces: Dict[str, Any] = {}
        post_submit_trace = None
        manual_input_traces: list[Dict[str, Any]] = []
        xml, snapshot = _current_snapshot(sc)
        challenge_traces, xml, snapshot = _wait_for_manual_login_challenges(
            sc, step, idx, profile, xml, snapshot
        )
        manual_input_traces.extend(challenge_traces)
        post_submit_fields = getattr(recipe, "post_submit_fields", {}) or {}
        entered_post_submit = False
        if post_submit_fields:
            post_submit_traces, entered_post_submit, xml, snapshot = _input_post_submit_fields(
                sc, step, idx, profile, post_submit_fields
            )
        post_submit_actions = getattr(recipe, "post_submit_actions", []) or []
        if post_submit_actions and not entered_post_submit:
            post_submit_action_trace = _execute_post_submit_actions(
                sc, step, profile, list(post_submit_actions)
            )
            xml, snapshot = _current_snapshot(sc)
            challenge_traces, xml, snapshot = _wait_for_manual_login_challenges(
                sc, step, idx, profile, xml, snapshot
            )
            manual_input_traces.extend(challenge_traces)
            if post_submit_fields:
                post_submit_traces, entered_post_submit, xml, snapshot = _input_post_submit_fields(
                    sc, step, idx, profile, post_submit_fields
                )
        if post_submit_fields:
            post_submit = getattr(recipe, "post_submit", None) or recipe.submit
            if entered_post_submit and post_submit is not None:
                post_submit_trace = _click_submit(sc, step, profile, post_submit, xml, snapshot)
                xml, snapshot = _current_snapshot(sc)
                challenge_traces, xml, snapshot = _wait_for_manual_login_challenges(
                    sc, step, idx, profile, xml, snapshot
                )
                manual_input_traces.extend(challenge_traces)
        result.update({
            "message": "login_if_needed: submitted login",
            "login_state": "submitted",
            "locator_trace": traces,
            "submit_trace": submit_trace,
            "post_submit_action_trace": post_submit_action_trace,
            "post_submit_locator_trace": post_submit_traces,
            "post_submit_trace": post_submit_trace,
            "manual_input_trace": manual_input_traces[-1] if manual_input_traces else None,
            "manual_input_traces": manual_input_traces,
        })
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"login_if_needed failed: {exc}"


@register_step("fill_form")
def handle_fill_form(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        profile = _load_profile(sc, step)
        recipe_name = str(step.get("recipe") or step.get("form") or "").strip()
        if not recipe_name and len(profile.form_recipes) == 1:
            recipe_name = next(iter(profile.form_recipes))
        recipe: FormRecipe | None = profile.form_recipes.get(recipe_name)
        if recipe is None:
            raise ValueError(f"form recipe {recipe_name!r} not found")
        xml, snapshot = _current_snapshot(sc)
        field_traces: Dict[str, Any] = {}
        failed_fields: list[str] = []
        for field_name, field in recipe.fields.items():
            try:
                value = _value_from_ref(sc, field.value_from, idx)
                field_traces[field_name] = _input_named_locator(
                    sc, step, idx, profile, field.locator, value, xml, snapshot,
                )
                xml, snapshot = _current_snapshot(sc)
            except Exception as exc:
                field_traces[field_name] = {"matched": False, "reason": str(exc)}
                if field.required or recipe.mode == "strict":
                    failed_fields.append(field_name)
        if failed_fields:
            raise RuntimeError(f"required form fields failed: {', '.join(failed_fields)}")
        submit_trace = None
        if recipe.submit is not None:
            submit_trace = _click_submit(sc, step, profile, recipe.submit, xml, snapshot)
        result.update({
            "message": f"fill_form: completed {recipe_name}",
            "form_recipe": recipe_name,
            "form_fields": field_traces,
            "submit_trace": submit_trace,
        })
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"fill_form failed: {exc}"


@register_step("assert_app_state")
def handle_assert_app_state(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    try:
        profile = _load_profile(sc, step)
        xml, snapshot = _current_snapshot(sc)
        expected_package = str(step.get("package") or profile.package or "").strip()
        if expected_package:
            current = {}
            u2 = sc.device.u2
            if u2 is not None and callable(getattr(u2, "app_current", None)):
                current = u2.app_current() or {}
            current_package = str(current.get("package") or "")
            if current_package and current_package != expected_package:
                raise RuntimeError(f"package mismatch: expected {expected_package}, got {current_package}")
        any_text = [str(item) for item in (step.get("any_text") or [])]
        all_text = [str(item) for item in (step.get("all_text") or [])]
        not_text = [str(item) for item in (step.get("not_text") or [])]
        if any_text and not _snapshot_has_any_text(snapshot, any_text):
            raise RuntimeError(f"none of any_text was visible: {any_text}")
        for text in all_text:
            if not _snapshot_has_any_text(snapshot, [text]):
                raise RuntimeError(f"required text not visible: {text!r}")
        for text in not_text:
            if _snapshot_has_any_text(snapshot, [text]):
                raise RuntimeError(f"forbidden text visible: {text!r}")
        locator_name = str(step.get("locator") or "").strip()
        locator_trace = None
        if locator_name:
            resolution = _resolve_named_locator(sc, profile, locator_name, xml, snapshot)
            locator_trace = _resolution_trace(resolution)
            if not resolution.matched:
                raise RuntimeError(f"locator {locator_name!r} failed: {resolution.reason}")
        result.update({
            "message": "assert_app_state: passed",
            "assertions": {
                "package": expected_package or None,
                "any_text": any_text,
                "all_text": all_text,
                "not_text": not_text,
            },
            "locator_trace": locator_trace,
        })
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"assert_app_state failed: {exc}"
