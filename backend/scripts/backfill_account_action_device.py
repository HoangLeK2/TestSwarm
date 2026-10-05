#!/usr/bin/env python3
"""Fill in `device` on account actions recorded before the column existed.

The ledger only started recording which phone ran an action recently. Older
rows have NULL device_serial, so the activity feed's device filter cannot find
them — "what did this phone do last week" comes back empty.

`execution_steps` already stores device_id per (execution_id, step_id), which is
exactly the pair `account_actions` keys on, so the history can be recovered.

Run manually — deliberately not part of a migration, because on a large table
this walks every row and a migration holding that long blocks startup.

    uv run python scripts/backfill_account_action_device.py --dry-run
    uv run python scripts/backfill_account_action_device.py --batch-size 500
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

# Match on both execution and step: an execution can span several devices, so
# execution alone would attribute actions to the wrong phone.
_MATCH_SQL = """
WITH resolved AS (
    SELECT a.id                AS action_id,
           s.device_id         AS device_id,
           d.serial            AS device_serial
    FROM account_actions a
    JOIN execution_steps s
      ON s.execution_id = a.execution_id
     AND s.step_id      = a.step_id
    LEFT JOIN devices d ON d.id = s.device_id
    WHERE a.device_serial IS NULL
      AND a.execution_id IS NOT NULL
      AND a.step_id IS NOT NULL
      AND s.device_id IS NOT NULL
    LIMIT :batch
)
UPDATE account_actions AS a
SET device_id     = r.device_id,
    device_serial = r.device_serial
FROM resolved r
WHERE a.id = r.action_id
"""

_COUNT_SQL = """
SELECT count(*) FROM account_actions a
JOIN execution_steps s
  ON s.execution_id = a.execution_id AND s.step_id = a.step_id
WHERE a.device_serial IS NULL
  AND a.execution_id IS NOT NULL
  AND a.step_id IS NOT NULL
  AND s.device_id IS NOT NULL
"""

_REMAINING_SQL = "SELECT count(*) FROM account_actions WHERE device_serial IS NULL"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows could be filled, change nothing.",
    )
    args = parser.parse_args()

    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        recoverable = (await db.execute(text(_COUNT_SQL))).scalar_one()
        missing = (await db.execute(text(_REMAINING_SQL))).scalar_one()
        print(f"Thiếu device: {missing} dòng — có thể khôi phục: {recoverable}")
        if missing and not recoverable:
            print("Không dòng nào tra được execution_steps (có thể đã bị dọn theo retention).")
        if args.dry_run:
            return 0

        updated = 0
        while True:
            result = await db.execute(text(_MATCH_SQL), {"batch": args.batch_size})
            await db.commit()
            if not result.rowcount:
                break
            updated += result.rowcount
            print(f"  đã cập nhật {updated}/{recoverable}")

        still_missing = (await db.execute(text(_REMAINING_SQL))).scalar_one()
        print(f"Xong: cập nhật {updated} dòng, còn {still_missing} dòng không tra được.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
