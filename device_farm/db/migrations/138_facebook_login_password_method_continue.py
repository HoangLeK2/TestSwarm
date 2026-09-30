"""Sync the Facebook Account Login password-method confirmation step.

Account Login scenarios are cloned into ``org_scenarios``. Updating the
builtin template therefore fixes new workspaces but does not refresh existing
workspace copies. This migration applies the same source change once to those
managed copies.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

log = logging.getLogger(__name__)

_SYSTEM_ACCOUNT_LOGIN_TAG = "system-account-login"
_VI_TITLE = "Chọn cách xác nhận tài khoản"
_EN_TITLE = "Choose a way to confirm your account"
_CONTINUE_ACTION = {
    "when_text_exact_any": [_VI_TITLE, _EN_TITLE],
    "tap_text_any": ["Tiếp tục", "Continue", "Next"],
    "timeout_s": 6,
    "poll_s": 0.5,
    "wait_after_s": 1,
}


def _insert_password_method_continue(value: Any) -> int:
    changed = 0
    if isinstance(value, dict):
        profile = value.get("profile")
        if (
            value.get("type") == "login_if_needed"
            and isinstance(profile, dict)
            and profile.get("package") == "com.facebook.katana"
        ):
            recipe = profile.get("login_recipe")
            actions = recipe.get("post_submit_actions") if isinstance(recipe, dict) else None
            if isinstance(actions, list):
                has_continue = any(
                    isinstance(action, dict)
                    and _VI_TITLE in (action.get("when_text_exact_any") or [])
                    and "Tiếp tục" in (action.get("tap_text_any") or [])
                    for action in actions
                )
                password_indexes = [
                    index
                    for index, action in enumerate(actions)
                    if isinstance(action, dict)
                    and _VI_TITLE in (action.get("when_text_exact_any") or [])
                    and "Mật khẩu" in (action.get("tap_text_any") or [])
                ]
                if not has_continue and len(password_indexes) == 1:
                    actions.insert(password_indexes[0] + 1, dict(_CONTINUE_ACTION))
                    changed += 1
        for child in value.values():
            changed += _insert_password_method_continue(child)
    elif isinstance(value, list):
        for child in value:
            changed += _insert_password_method_continue(child)
    return changed


async def upgrade(conn) -> None:
    result = await conn.execute(
        text(
            """
            SELECT os.id, os.scenario_version, os.body_json
            FROM org_scenarios AS os
            JOIN org_scenario_tags AS tag
              ON tag.org_scenario_id = os.id
             AND tag.tag = :system_tag
            WHERE os.deleted_at IS NULL
              AND os.body_json IS NOT NULL
            """
        ),
        {"system_tag": _SYSTEM_ACCOUNT_LOGIN_TAG},
    )

    updated = 0
    for row in result.fetchall():
        body = json.loads(json.dumps(row.body_json))
        if _insert_password_method_continue(body) != 1:
            continue
        await conn.execute(
            text(
                """
                UPDATE org_scenarios
                SET body_json = CAST(:body_json AS JSONB),
                    scenario_version = :scenario_version,
                    updated_at = NOW(),
                    last_validation_summary = NULL,
                    last_validated_at = NULL
                WHERE id = :scenario_id
                """
            ),
            {
                "body_json": json.dumps(body),
                "scenario_version": int(row.scenario_version or 1) + 1,
                "scenario_id": row.id,
            },
        )
        updated += 1

    log.info("facebook password-method confirmation synced to %d org scenario(s)", updated)
