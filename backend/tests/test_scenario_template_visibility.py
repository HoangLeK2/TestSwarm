"""Scenario template list visibility for org-scoped and system-seeded rows."""

from __future__ import annotations

import pytest

from db.crud.scenario_template import create_template, list_templates


@pytest.mark.asyncio
async def test_list_templates_includes_system_seeded_without_owner(
    tenancy_session_factory,
):
    async with tenancy_session_factory() as session:
        await create_template(
            session,
            name="system-seeded-template",
            category="instagram",
            is_builtin=False,
            user_id=None,
        )
        await create_template(
            session,
            name="other-user-template",
            category="general",
            is_builtin=False,
            user_id="other-user",
        )
        await session.commit()

        visible = await list_templates(session, user_ids=["member-1"])

    names = {t.name for t in visible}
    assert "system-seeded-template" in names
    assert "other-user-template" not in names


@pytest.mark.asyncio
async def test_list_templates_includes_builtin_and_org_member_rows(
    tenancy_session_factory,
):
    async with tenancy_session_factory() as session:
        await create_template(
            session,
            name="builtin-template",
            is_builtin=True,
            user_id=None,
        )
        await create_template(
            session,
            name="member-template",
            is_builtin=False,
            user_id="member-1",
        )
        await session.commit()

        visible = await list_templates(session, user_ids=["member-1"])

    names = {t.name for t in visible}
    assert names == {"builtin-template", "member-template"}
