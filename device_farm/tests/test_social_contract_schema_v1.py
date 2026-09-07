"""Schema v1 is the contract between social capability nodes.

The chain a nurture scenario runs is `content_scan` → open commenter →
`profile_verify` → `connection_action`, and each link reads the variable the
previous one wrote. These tests pin what crosses each link, so a second platform
can fill the same shape instead of copying Facebook's field names — and so a
run that started before v1 keeps working while it finishes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.social_actions.schema import (
    SOCIAL_SCHEMA_VERSION,
    content_scan_payload,
    people_target_payload,
    read_actions,
    read_identity,
    read_proof,
    read_schema_version,
    read_verified,
)


class _FakeVarContext:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set(self, name: str, value: object) -> None:
        self.values[name] = value

    def lookup_raw(self, name: str, step_index: int = 0) -> object:
        del step_index
        return self.values.get(name)

    def resolve(self, value: object, step_index: int = 0) -> object:
        del step_index
        if not isinstance(value, str) or not value.startswith("${"):
            return value
        resolved = self.values.get(value[2:-1], value)
        if isinstance(resolved, list):
            return resolved[0]
        return resolved


class _FlowDevice:
    """Answers each agent-boot flow by name; screens are served in order."""

    def __init__(self, *hierarchies: str) -> None:
        self._hierarchies = list(hierarchies) or ["<hierarchy></hierarchy>"]
        self.flow_results: dict[str, dict[str, object]] = {}
        self.flows: list[tuple[str, dict]] = []
        self.taps: list[tuple[int, int]] = []
        self.keys: list[str] = []

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        del force_refresh
        if len(self._hierarchies) > 1:
            return self._hierarchies.pop(0)
        return self._hierarchies[0]

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def key(self, name: str) -> None:
        self.keys.append(name)

    def u2_flow(
        self,
        name: str,
        params: dict,
        timeout: float = 30.0,
        priority: object = None,
        deadline_ms: object = None,
    ) -> dict[str, object]:
        del timeout, priority, deadline_ms
        self.flows.append((name, params))
        if name not in self.flow_results:
            raise RuntimeError(f"u2 flow {name!r} not configured")
        return self.flow_results[name]


def _context(device: _FlowDevice) -> SimpleNamespace:
    return SimpleNamespace(
        serial="PHONE-01",
        device=device,
        cancel_event=None,
        ctx={"vars": {}},
        var_ctx=_FakeVarContext(),
        capture_dir=None,
        scenario={},
        execution_id=None,
    )


def _node(label: str, *, bounds: str = "[10,20][110,70]") -> str:
    return (
        f'<node text="{label}" content-desc="{label}" clickable="true" '
        f'selected="false" bounds="{bounds}" />'
    )


def _xml(*nodes: str) -> str:
    return f"<hierarchy>{''.join(nodes)}</hierarchy>"


# --- envelope shape ----------------------------------------------------------


def test_content_scan_payload_declares_version_platform_actions_and_proof() -> None:
    payload = content_scan_payload(
        {
            "verified": True,
            "interacted_count": 2,
            "liked_count": 2,
            "commented_count": 2,
            "candidate_count": 3,
            "screens_scanned": 2,
            "scrolls": 1,
            "actions": [{"target_id": "ui_post:1", "verified": True}],
        },
        platform="facebook",
    )

    assert payload["schema_version"] == SOCIAL_SCHEMA_VERSION
    assert payload["platform"] == "facebook"
    assert payload["actions"] == [{"target_id": "ui_post:1", "verified": True}]
    assert payload["proof"]["verified"] is True
    assert payload["proof"]["interacted_count"] == 2
    assert payload["proof"]["commented_count"] == 2
    # Additive: every field the resolver returned is still where it was.
    assert payload["liked_count"] == 2
    assert payload["screens_scanned"] == 2


def test_content_scan_payload_always_offers_an_action_list() -> None:
    """A scan that matched nothing must still answer "no actions", not "no key"."""
    payload = content_scan_payload(
        {"verified": False, "reason": "no_matching_post"}, platform="facebook"
    )

    assert payload["actions"] == []
    assert payload["proof"]["verified"] is False
    assert payload["proof"]["reason"] == "no_matching_post"


def test_people_target_payload_separates_identity_from_proof() -> None:
    payload = people_target_payload(
        {
            "verified": True,
            "target_type": "person",
            "target_id": "ui_commenter:abc",
            "display_name": "Tran Van B",
            "source": "matched_feed_post_commenter",
            "confidence": 92,
            "matched_keywords": ["AI"],
            "action_bounds": [600, 720, 980, 810],
            "profile_opened": True,
        },
        platform="facebook",
    )

    assert payload["schema_version"] == SOCIAL_SCHEMA_VERSION
    assert payload["platform"] == "facebook"
    assert payload["identity"] == {
        "target_type": "person",
        "target_id": "ui_commenter:abc",
        "display_name": "Tran Van B",
        "source": "matched_feed_post_commenter",
    }
    assert payload["proof"]["verified"] is True
    assert payload["proof"]["confidence"] == 92
    assert payload["proof"]["action_bounds"] == [600, 720, 980, 810]
    # The ledger reads these four off the top level; they must not move.
    for key in ("target_type", "target_id", "source", "verified"):
        assert key in payload


def test_people_target_payload_keeps_an_unverified_target_unverified() -> None:
    """`verified` is a decision, not a field to be inherited from a stale dict."""
    payload = people_target_payload(
        {"verified": True, "target_type": "person"},
        platform="facebook",
        verified=False,
    )

    assert payload["verified"] is False
    assert payload["proof"]["verified"] is False
    assert read_verified(payload) is False


# --- transitional readers ----------------------------------------------------


def test_readers_accept_a_payload_written_before_schema_v1() -> None:
    """An execution mid-run holds the old shape; it must not read as unverified."""
    legacy_target = {
        "verified": True,
        "target_type": "person",
        "target_id": "ui_commenter:abc",
        "display_name": "Tran Van B",
        "source": "matched_feed_post_commenter",
        "confidence": 92,
    }

    assert read_schema_version(legacy_target) is None
    assert read_verified(legacy_target) is True
    assert read_identity(legacy_target)["display_name"] == "Tran Van B"
    assert read_proof(legacy_target)["confidence"] == 92

    legacy_scan = {"verified": True, "actions": [{"target_id": "ui_post:1"}]}
    assert read_actions(legacy_scan) == [{"target_id": "ui_post:1"}]
    assert read_proof(legacy_scan)["verified"] is True


def test_read_actions_tells_no_scan_apart_from_an_empty_scan() -> None:
    assert read_actions({"actions": []}) == []
    assert read_actions({"verified": True}) is None
    assert read_actions("not a payload") is None
    assert read_actions(None) is None


def test_read_verified_refuses_anything_that_is_not_a_payload() -> None:
    for value in (None, "", 0, [], "verified"):
        assert read_verified(value) is False


# --- the chain the scenario actually runs ------------------------------------


def _scan_step() -> dict[str, object]:
    return {
        "id": "seed_friends_scan_and_interact",
        "type": "social_scan_posts_interact",
        "platform": "facebook",
        "keywords": ["AI"],
        "comment_text": "Bài viết hữu ích",
        "target_count": 1,
        "max_scrolls": 2,
        "save_as": "_post_scan",
    }


def _open_commenter_step() -> dict[str, object]:
    return {
        "id": "seed_friends_open_0",
        "type": "social_open_commenter_from_post_match",
        "platform": "facebook",
        "source_var": "_post_scan",
        "action_index": 0,
        "required_keywords": ["AI"],
        "save_as": "_people_target",
        "save_success_as": "PEOPLE_PROFILE_SELECTED",
    }


def _connection_step() -> dict[str, object]:
    return {
        "id": "seed_friends_connection_request_0",
        "type": "connection_request",
        "platform": "facebook",
        "action": "request",
        "timeout": 0.1,
        "poll": 0.01,
        "verify_timeout": 0.1,
        "settle_seconds": 0,
        "require_verified_target": "_people_target",
    }


def test_scan_to_commenter_to_target_to_request_runs_on_schema_v1() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FlowDevice(_xml(_node("Thêm bạn bè")), _xml(_node("Hủy lời mời")))
    device.flow_results["social_scan_posts_interact"] = {
        "verified": True,
        "interacted_count": 1,
        "liked_count": 1,
        "commented_count": 1,
        "actions": [
            {
                "verified": True,
                "target_id": "ui_post:abc",
                "comment_bounds": [227, 1505, 457, 1659],
                "matched_keywords": ["AI"],
            }
        ],
    }
    device.flow_results["social_open_commenter_from_post_match"] = {
        "verified": True,
        "target_type": "person",
        "source": "matched_feed_post_commenter",
        "confidence": 92,
        "target_id": "ui_commenter:abc",
        "display_name": "Tran Van B",
        "matched_keywords": ["AI"],
        "action_bounds": [600, 720, 980, 810],
        "profile_opened": True,
        "comment_sheet_opened": True,
    }
    sc = _context(device)

    scan_result = dispatch_step(sc, _scan_step(), 0)
    scan = sc.ctx["vars"]["_post_scan"]
    assert scan_result["ok"] is True
    assert scan["schema_version"] == SOCIAL_SCHEMA_VERSION
    assert scan["platform"] == "facebook"
    assert scan["proof"]["interacted_count"] == 1
    assert len(scan["actions"]) == 1

    open_result = dispatch_step(sc, _open_commenter_step(), 1)
    target = sc.ctx["vars"]["_people_target"]
    assert open_result["outcome"] == "target_verified"
    assert target["schema_version"] == SOCIAL_SCHEMA_VERSION
    assert target["platform"] == "facebook"
    assert target["identity"]["display_name"] == "Tran Van B"
    assert target["proof"]["verified"] is True
    assert sc.ctx["vars"]["PEOPLE_PROFILE_SELECTED"] is True

    request_result = dispatch_step(sc, _connection_step(), 2)
    assert request_result["ok"] is True
    assert request_result["outcome"] == "applied"
    assert request_result["verified_target"]["name"] == "_people_target"
    assert device.taps == [(60, 45)]


def test_connection_request_still_honours_a_pre_v1_verified_target() -> None:
    """A target saved by the previous build must not be refused for its shape."""
    from tasks.scenario.steps import dispatch_step

    device = _FlowDevice(_xml(_node("Thêm bạn bè")), _xml(_node("Hủy lời mời")))
    sc = _context(device)
    sc.ctx["vars"]["_people_target"] = {
        "verified": True,
        "target_type": "person",
        "source": "agent_boot",
        "confidence": 95,
    }

    result = dispatch_step(sc, _connection_step(), 0)

    assert result["ok"] is True
    assert device.taps == [(60, 45)]


def test_open_commenter_reads_a_pre_v1_scan_variable() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FlowDevice(_xml())
    device.flow_results["social_open_commenter_from_post_match"] = {
        "verified": True,
        "target_type": "person",
        "target_id": "ui_commenter:abc",
        "display_name": "Tran Van B",
        "profile_opened": True,
    }
    sc = _context(device)
    # No schema_version, no proof — exactly what the previous build wrote.
    sc.var_ctx.set(
        "_post_scan",
        {"actions": [{"verified": True, "target_id": "ui_post:abc"}]},
    )

    result = dispatch_step(sc, _open_commenter_step(), 0)

    assert result["outcome"] == "target_verified"
    assert sc.ctx["vars"]["_people_target"]["schema_version"] == SOCIAL_SCHEMA_VERSION


def test_connection_request_refuses_an_unverified_target() -> None:
    """The one rule the envelope must never soften: no blind send."""
    from tasks.scenario.steps import dispatch_step

    device = _FlowDevice(_xml(_node("Thêm bạn bè")))
    sc = _context(device)
    sc.ctx["vars"]["_people_target"] = people_target_payload(
        {"target_type": "person", "outcome": "target_not_verified"},
        platform="facebook",
        verified=False,
    )

    result = dispatch_step(sc, _connection_step(), 0)

    assert result["ok"] is False
    assert result["outcome"] == "target_not_verified"
    assert device.taps == []


@pytest.mark.parametrize(
    "missing_source",
    [{"verified": True}, {"actions": "not-a-list"}, None],
)
def test_open_commenter_reports_a_source_that_carries_no_actions(
    missing_source: object,
) -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FlowDevice(_xml())
    sc = _context(device)
    if missing_source is not None:
        sc.var_ctx.set("_post_scan", missing_source)

    result = dispatch_step(sc, _open_commenter_step(), 0)

    assert result["ok"] is True
    assert result["outcome"] == "source_actions_missing"
    assert device.flows == []
    assert read_verified(sc.ctx["vars"]["_people_target"]) is False
