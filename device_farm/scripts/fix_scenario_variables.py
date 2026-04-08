"""
scripts/fix_scenario_variables.py

One-shot migration: find all Scenario rows with empty variables={} that
reference ${VAR} placeholders in their steps, then backfill variables from
the parent campaign's scenario JSON (which contains the template defaults).

Run:
    cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
    uv run python scripts/fix_scenario_variables.py [--dry-run] [--debug]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

from sqlalchemy import select, update

from db.database import AsyncSessionLocal
from db.models.campaign import Campaign, Scenario


VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _collect_vars(obj: Any) -> set[str]:
    """Recursively collect all ${VAR} names referenced in a JSON structure."""
    found: set[str] = set()
    if isinstance(obj, str):
        found.update(VAR_RE.findall(obj))
    elif isinstance(obj, list):
        for item in obj:
            found |= _collect_vars(item)
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= _collect_vars(v)
    return found


async def run(dry_run: bool = False, debug: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        # NOTE: scenarios.variables is JSON (not JSONB); PostgreSQL does not support
        # direct equality operator for JSON (`json = json`). Query broadly and
        # filter empty/null in Python to keep this script portable/safe.
        result = await db.execute(select(Scenario))
        all_scenarios = list(result.scalars().all())
        scenarios = [s for s in all_scenarios if s.variables is None or s.variables == {}]
        print(
            f"Found {len(scenarios)} scenario(s) with empty variables "
            f"(scanned {len(all_scenarios)} total)"
        )

        # Load campaigns once
        camp_result = await db.execute(select(Campaign))
        campaigns_by_id = {c.id: c for c in camp_result.scalars().all()}

        fixed = 0
        for s in scenarios:
            steps = s.steps or []
            referenced = _collect_vars(steps)
            campaign = campaigns_by_id.get(s.campaign_id)

            if debug:
                print(f"\n  Scenario {s.id!r} ({s.name!r})")
                print(f"    steps count: {len(steps)}")
                print(f"    referenced vars: {referenced}")
                print(f"    campaign found: {campaign is not None}")
                if campaign:
                    sc_json = campaign.scenario or {}
                    tv = (sc_json.get("variables") or {}) if isinstance(sc_json, dict) else {}
                    cv = campaign.variables or {}
                    print(f"    campaign.scenario keys: {list(sc_json.keys()) if isinstance(sc_json, dict) else sc_json}")
                    print(f"    campaign.scenario['variables']: {tv}")
                    print(f"    campaign.variables: {cv}")

            if not referenced:
                if debug:
                    print("    → SKIP: no ${VAR} refs in steps")
                continue

            if not campaign:
                if debug:
                    print("    → SKIP: campaign not found")
                continue

            sc_json = campaign.scenario or {}
            template_vars: dict = (sc_json.get("variables") or {}) if isinstance(sc_json, dict) else {}
            campaign_vars: dict = campaign.variables or {}

            # Merge both sources: campaign.scenario["variables"] + campaign.variables
            all_available = {**template_vars, **campaign_vars}

            if not all_available:
                print(
                    f"  Scenario {s.id!r} ({s.name!r}): references {referenced} "
                    f"but campaign has no vars at all — skipping"
                )
                continue

            # Only inject vars that are actually referenced in steps
            new_vars = {k: v for k, v in all_available.items() if k in referenced}
            if not new_vars:
                if debug:
                    print(f"    → SKIP: referenced {referenced} not in available {set(all_available.keys())}")
                continue

            print(
                f"  {'[DRY] ' if dry_run else ''}Scenario {s.id!r} ({s.name!r}): "
                f"backfilling {json.dumps(new_vars, ensure_ascii=False)}"
            )
            if not dry_run:
                await db.execute(
                    update(Scenario)
                    .where(Scenario.id == s.id)
                    .values(variables=new_vars)
                )
            fixed += 1

        if not dry_run:
            await db.commit()
        print(f"\n{'Would fix' if dry_run else 'Fixed'} {fixed} scenario(s).")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    debug = "--debug" in sys.argv
    asyncio.run(run(dry_run=dry_run, debug=debug))
