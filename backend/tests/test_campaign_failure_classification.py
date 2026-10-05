"""Campaign failure classifier tests."""
from __future__ import annotations

from services.campaign.failure_classification import (
    annotate_step_failure,
    classify_campaign_failure,
)


def test_classifies_json_rpc_502_as_retryable_u2_transient():
    result = {
        "ok": False,
        "type": "ig_comment",
        "message": "edge extra_data failed: JSON-RPC HTTP 502",
    }

    classified = classify_campaign_failure(result)

    assert classified.failure_class == "u2_transient"
    assert classified.reason_code == "u2_transient_error"
    assert classified.retryable is True
    assert classified.retry_hint == "retry_with_single_recovery"


def test_classifies_uiautomation_disconnect_as_u2_transient():
    classified = classify_campaign_failure(
        message="java.lang.IllegalStateException: UiAutomation not connected",
    )

    assert classified.failure_class == "u2_transient"
    assert classified.retryable is True


def test_classifies_selector_miss_as_business_failure():
    classified = classify_campaign_failure(
        {"ok": False, "reason_code": "post_open_target_not_found", "message": "target missing"}
    )

    assert classified.failure_class == "business_selector_miss"
    assert classified.retryable is False
    assert classified.retry_hint == "operator_review_selector_or_screen_state"


def test_classifies_device_lost_as_non_retryable_isolation():
    classified = classify_campaign_failure(message="CampaignDeviceClaimLostError: claim lost")

    assert classified.failure_class == "device_lost"
    assert classified.retryable is False
    assert classified.retry_hint == "isolate_device_wait_for_reconnect"


def test_classifies_crawl_timeout_without_changing_deep_crawl_budget():
    classified = classify_campaign_failure(
        {"ok": False, "type": "ig_comment", "message": "comment wall-clock cap reached"}
    )

    assert classified.failure_class == "crawl_timeout"
    assert classified.retry_hint == "keep_checkpoint_review_crawl_budget"


def test_annotate_step_failure_sets_operational_metadata_in_place():
    result = {"ok": False, "message": "JSON-RPC HTTP 504"}

    out = annotate_step_failure(result, step_type="ig_comment")

    assert out is result
    assert result["reason_code"] == "u2_transient_error"
    assert result["failure_class"] == "u2_transient"
    assert result["retryable"] is True
    assert result["operator_summary"] == "u2_transient_error"
