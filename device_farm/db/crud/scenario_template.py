from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.scenario_template import ScenarioTemplate


async def create_template(
    db: AsyncSession,
    name: str,
    description: str = "",
    category: str = "general",
    steps: list | None = None,
    variables: dict | None = None,
    tags: str = "",
    is_builtin: bool = False,
    user_id: str | None = None,
    nodes: list | None = None,
    edges: list | None = None,
) -> ScenarioTemplate:
    tmpl = ScenarioTemplate(
        name=name,
        description=description,
        category=category,
        steps=steps or [],
        nodes=nodes or [],
        edges=edges or [],
        variables=variables or {},
        tags=tags,
        is_builtin=is_builtin,
        user_id=user_id,
    )
    db.add(tmpl)
    await db.flush()
    return tmpl


async def get_template(db: AsyncSession, template_id: str) -> Optional[ScenarioTemplate]:
    result = await db.execute(
        select(ScenarioTemplate).where(ScenarioTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


async def get_template_by_name(db: AsyncSession, name: str) -> Optional[ScenarioTemplate]:
    result = await db.execute(
        select(ScenarioTemplate).where(ScenarioTemplate.name == name)
    )
    return result.scalar_one_or_none()


async def list_templates(
    db: AsyncSession,
    category: str | None = None,
    tags: str | None = None,
) -> list[ScenarioTemplate]:
    q = select(ScenarioTemplate).order_by(ScenarioTemplate.created_at.desc())
    if category:
        q = q.where(ScenarioTemplate.category == category)
    if tags:
        # tags is comma-separated; filter templates that contain ANY given tag
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            from sqlalchemy import or_
            q = q.where(
                or_(*[ScenarioTemplate.tags.ilike(f"%{tag}%") for tag in tag_list])
            )
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_template(
    db: AsyncSession, template_id: str, **kwargs: Any
) -> None:
    await db.execute(
        update(ScenarioTemplate)
        .where(ScenarioTemplate.id == template_id)
        .values(**kwargs)
    )


async def delete_template(db: AsyncSession, template_id: str) -> None:
    await db.execute(
        delete(ScenarioTemplate).where(ScenarioTemplate.id == template_id)
    )


async def duplicate_template(
    db: AsyncSession,
    template_id: str,
    user_id: str | None = None,
) -> Optional[ScenarioTemplate]:
    """Create a non-builtin copy of a template with a new unique name."""
    src = await get_template(db, template_id)
    if src is None:
        return None
    # Generate a unique name: append _copy, _copy2, _copy3, ...
    base_name = f"{src.name}_copy"
    new_name = base_name
    i = 2
    while await get_template_by_name(db, new_name) is not None:
        new_name = f"{base_name}{i}"
        i += 1
    return await create_template(
        db,
        name=new_name,
        description=src.description,
        category=src.category,
        steps=list(src.steps) if src.steps else [],
        variables=dict(src.variables) if src.variables else {},
        tags=src.tags,
        is_builtin=False,
        user_id=user_id,
        nodes=list(src.nodes) if src.nodes else [],
        edges=list(src.edges) if src.edges else [],
    )
