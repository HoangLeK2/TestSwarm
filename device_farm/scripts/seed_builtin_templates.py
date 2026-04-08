"""
scripts/seed_builtin_templates.py

Upsert built-in scenario templates into the database.
- If a template with the same name exists: update steps/variables/description.
- If it does not exist: create it with is_builtin=True.
- Builtin templates cannot be deleted or modified via the public API.

Run:
    cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
    uv run python scripts/seed_builtin_templates.py [--dry-run]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select, update

from db.database import AsyncSessionLocal
from db.models.scenario_template import ScenarioTemplate
from db.models.utils import _uuid as _make_uuid

# ── Template definitions ───────────────────────────────────────────────────────

_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def _load_steps(filename: str) -> list:
    path = _SCENARIOS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))["steps"]


BUILTIN_TEMPLATES: list[dict] = [
    {
        "name": "fb_group_crawl",
        "description": (
            "Crawl bài viết và bình luận từ một Facebook Group. "
            "Tìm kiếm nhóm theo tên, cuộn feed, lấy toàn văn bài viết dài "
            "(expand 'Xem thêm' nhiều lần), và thu thập comment có kèm parent_post_id."
        ),
        "category": "facebook",
        "tags": "facebook,group,crawl,comment",
        "steps_file": "fb_group_crawl.json",
        "variables": {
            "GROUP_NAME": {
                "type": "string",
                "default": "",
                "description": "Tên nhóm Facebook cần crawl (dùng để search và tap vào kết quả)",
                "required": True,
            },
            "SAVE_COLLECTION": {
                "type": "string",
                "default": "facebook_groups",
                "description": "Tên collection lưu dữ liệu vào DB",
            },
            "MAX_SCROLLS": {
                "type": "integer",
                "default": 20,
                "description": "Số lần cuộn feed tối đa",
                "min": 1,
                "max": 200,
            },
            "MAX_COMMENT_SCROLLS": {
                "type": "integer",
                "default": 5,
                "description": "Số lần cuộn trong section bình luận của mỗi bài",
                "min": 1,
                "max": 30,
            },
            "SCROLL_X_RATIO": {
                "type": "float",
                "default": 0.5,
                "description": "Vị trí ngang khi cuộn feed (0.0–1.0). Dùng 0.1 nếu có sidebar trái",
                "min": 0.0,
                "max": 1.0,
            },
        },
    },
]


# ── Upsert logic ───────────────────────────────────────────────────────────────

async def run(dry_run: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        for tmpl_def in BUILTIN_TEMPLATES:
            name = tmpl_def["name"]
            steps = _load_steps(tmpl_def["steps_file"])

            result = await db.execute(
                select(ScenarioTemplate).where(ScenarioTemplate.name == name)
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  {'[DRY] ' if dry_run else ''}UPDATE  {name!r}")
                if not dry_run:
                    await db.execute(
                        update(ScenarioTemplate)
                        .where(ScenarioTemplate.name == name)
                        .values(
                            description=tmpl_def["description"],
                            category=tmpl_def["category"],
                            tags=tmpl_def["tags"],
                            steps=steps,
                            variables=tmpl_def["variables"],
                            is_builtin=True,
                        )
                    )
            else:
                print(f"  {'[DRY] ' if dry_run else ''}CREATE  {name!r}")
                if not dry_run:
                    db.add(
                        ScenarioTemplate(
                            id=_make_uuid(),
                            name=name,
                            description=tmpl_def["description"],
                            category=tmpl_def["category"],
                            tags=tmpl_def["tags"],
                            steps=steps,
                            variables=tmpl_def["variables"],
                            is_builtin=True,
                            user_id=None,
                        )
                    )

        if not dry_run:
            await db.commit()
            print(f"\nSeeded {len(BUILTIN_TEMPLATES)} template(s).")
        else:
            print(f"\n[DRY RUN] Would seed {len(BUILTIN_TEMPLATES)} template(s). No changes made.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(run(dry_run=dry_run))
