"""
Sync builtin scenario templates: canonical steps + derived graph mirror.

Use after graph mirror was cleared, or to refresh steps from code specs.

Run from device_farm/:
    uv run python scripts/repair_builtin_templates_sequence.py
"""
from __future__ import annotations

import asyncio
import sys

from db.database import AsyncSessionLocal
from db.seeds.scenario_templates import repair_builtin_templates_to_sequence, seed_builtin_templates


async def run() -> int:
    async with AsyncSessionLocal() as db:
        seeded = await seed_builtin_templates(db)
        await db.commit()
        return seeded


def main() -> None:
    n = asyncio.run(run())
    print(f"Builtin templates synced ({n} row(s) touched): steps + graph mirror.")
    sys.exit(0)


if __name__ == "__main__":
    main()
