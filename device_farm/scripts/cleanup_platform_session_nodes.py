"""
Remove user-facing platform session guard nodes from stored scenarios.

Dry-run is the default:
    uv run python scripts/cleanup_platform_session_nodes.py

Apply changes:
    uv run python scripts/cleanup_platform_session_nodes.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from common.graph_compiler import steps_to_graph
from db.database import AsyncSessionLocal
from db.models.org_scenario import OrgScenario, OrgScenarioTag
from db.models.scenario_template import ScenarioTemplate
from services.scenario_migrations.platform_session_cleanup import (
    cleanup_platform_session_body,
)


def _requirement_tag_present(tags: str) -> bool:
    return any(
        token.strip().startswith("requires-platform-session:")
        for token in str(tags or "").split(",")
    )


def _strip_requirement_tag(tags: str) -> tuple[str, bool]:
    tokens = [token.strip() for token in str(tags or "").split(",") if token.strip()]
    kept = [token for token in tokens if not token.startswith("requires-platform-session:")]
    return ",".join(kept), kept != tokens


def _body_for_template(template: ScenarioTemplate) -> dict[str, Any]:
    return {
        "steps": template.steps if isinstance(template.steps, list) else [],
        "requirements": {},
    }


async def _run(*, apply: bool) -> int:
    counters: Counter[str] = Counter()
    async with AsyncSessionLocal() as db:
        template_rows = list(
            (
                await db.execute(
                    select(ScenarioTemplate).where(ScenarioTemplate.steps.is_not(None))
                )
            )
            .scalars()
            .all()
        )
        org_rows = list(
            (
                await db.execute(
                    select(
                        OrgScenario.__table__.c.id,
                        OrgScenario.__table__.c.name,
                        OrgScenario.__table__.c.scenario_version,
                        OrgScenario.__table__.c.body_json,
                    ).where(
                        OrgScenario.__table__.c.deleted_at.is_(None),
                        OrgScenario.__table__.c.body_json.is_not(None),
                    )
                )
            )
            .all()
        )
        scenario_ids = [row.id for row in org_rows]
        tag_rows = []
        if scenario_ids:
            tag_rows = list(
                (
                    await db.execute(
                        select(
                            OrgScenarioTag.__table__.c.org_scenario_id,
                            OrgScenarioTag.__table__.c.tag,
                        ).where(
                            OrgScenarioTag.__table__.c.org_scenario_id.in_(scenario_ids)
                        )
                    )
                ).all()
            )
        tags_by_scenario: dict[str, list[str]] = {}
        for row in tag_rows:
            tags_by_scenario.setdefault(str(row.org_scenario_id), []).append(row.tag)

        for template in template_rows:
            result = cleanup_platform_session_body(
                _body_for_template(template),
                name=template.name,
                tags=template.tags or "",
            )
            steps = (
                result.body.get("steps")
                if isinstance(result.body.get("steps"), list)
                else template.steps
            )
            removed_gate_count = result.removed_gate_count
            removed_ready_count = result.removed_ready_condition_count
            existing_tags = template.tags or ""
            if result.classification == "auth_required_rewrite":
                new_tags = existing_tags
                tag_changed = False
            else:
                new_tags, tag_changed = _strip_requirement_tag(existing_tags)
            should_add_tag = (
                result.classification == "auth_required_rewrite"
                and not _requirement_tag_present(existing_tags)
            )
            if should_add_tag:
                new_tags = ",".join(
                    token
                    for token in [new_tags, "requires-platform-session:facebook"]
                    if token
                )
                tag_changed = True
            changed = bool(removed_gate_count or removed_ready_count or tag_changed)
            if not changed:
                counters["template_unchanged"] += 1
                continue
            classification = (
                "tag_cleanup_only"
                if tag_changed and not (removed_gate_count or removed_ready_count)
                else result.classification
            )
            counters[f"template_{classification}"] += 1
            print(
                f"{'[APPLY]' if apply else '[DRY]'} template {template.id} "
                f"{template.name!r}: {classification}, "
                f"gates={removed_gate_count}, "
                f"ready_if={removed_ready_count}, "
                f"req_add={result.requirement_added}, req_remove={result.requirement_removed}"
            )
            if apply:
                nodes, edges = steps_to_graph(steps)
                await db.execute(
                    update(ScenarioTemplate)
                    .where(ScenarioTemplate.id == template.id)
                    .values(
                        steps=steps,
                        nodes=nodes,
                        edges=edges,
                        tags=new_tags,
                    )
                )

        for scenario in org_rows:
            body = scenario.body_json if isinstance(scenario.body_json, dict) else {}
            result = cleanup_platform_session_body(
                body,
                name=scenario.name,
                tags=",".join(tags_by_scenario.get(str(scenario.id), [])),
            )
            if not result.changed:
                counters["org_unchanged"] += 1
                continue
            counters[f"org_{result.classification}"] += 1
            print(
                f"{'[APPLY]' if apply else '[DRY]'} org_scenario {scenario.id} "
                f"{scenario.name!r}: {result.classification}, "
                f"v{scenario.scenario_version}->{int(scenario.scenario_version or 1) + 1}, "
                f"gates={result.removed_gate_count}, "
                f"ready_if={result.removed_ready_condition_count}, "
                f"req_add={result.requirement_added}, req_remove={result.requirement_removed}"
            )
            if apply:
                await db.execute(
                    update(OrgScenario.__table__)
                    .where(OrgScenario.__table__.c.id == scenario.id)
                    .values(
                        body_json=result.body,
                        scenario_version=int(scenario.scenario_version or 1) + 1,
                        updated_at=datetime.now(timezone.utc),
                        last_validation_summary=None,
                        last_validated_at=None,
                    )
                )

        if apply:
            await db.commit()
        print(json.dumps(dict(counters), ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist cleanup changes")
    args = parser.parse_args()
    return asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
