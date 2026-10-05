"""135 - Rename the 19 phones in the Mh group to MH1-MH19."""
from __future__ import annotations

import logging

from sqlalchemy import text

log = logging.getLogger(__name__)

MH_GROUP_ID = "954fae14-ae21-4d88-9235-a90cf88f36b7"
EXPECTED_MH_DEVICES = (
    ("e03dec55-09cf-4010-b756-8e3f1fdd9352", "23f4ef70341c7ece", "MH1"),
    ("3a77dd5f-775f-4042-9b5a-a06f0140f3f6", "273a77951c047ece", "MH2"),
    ("9a4663ff-443f-45cf-94eb-b42c301ff55d", "278822e1331c7ece", "MH3"),
    ("a157cd4d-38c6-473f-9453-315f4145cda1", "27ec4ca48c217ece", "MH4"),
    ("4f371304-ef8d-4c54-b71a-4b56ffdf2c9e", "284a96e45d1c7ece", "MH5"),
    ("0094f0be-3eee-4b76-9a06-b59eba568717", "2854879926047ece", "MH6"),
    ("4988a5e6-5e8f-4add-8c86-65bf81a0c3f0", "28c966012c057ece", "MH7"),
    ("2446068d-2e5d-45fb-b3bf-8c86732f5a35", "29e4524a003f7ece", "MH8"),
    ("3747b743-daeb-418f-951c-f22962113e20", "988a1c44514951394f", "MH9"),
    ("f5d7be00-69d8-4b05-83e8-e6fe5251368e", "ce021712734c1a2502", "MH10"),
    ("ed1e52d0-f4c9-4e43-a763-4d9ef913df09", "ce021712a1c67b0a05", "MH11"),
    ("c722b510-7cb2-4dee-a590-b53c1348700c", "ce031713d2aeb0fb0d", "MH12"),
    ("d520ef28-bc98-44eb-8c9b-53cbf3ffa307", "ce04171431e998920d", "MH13"),
    ("b96a1e9f-81d7-420a-a634-b2c82e3df17e", "ce04171432a86c170d", "MH14"),
    ("40082b60-d7c5-49a7-aa24-9ee48273c2b9", "ce0517159db01d1401", "MH15"),
    ("dc98d06e-00dc-451f-9dd1-18de3841a68a", "ce051715d9e3741502", "MH16"),
    ("dfada578-3f7a-4064-b52e-6448dd33c442", "ce0717171c2a64960d", "MH17"),
    ("b10246e6-4e0b-4ec8-949c-f6a059a80a4b", "ce0917199c9b3c550c", "MH18"),
    ("5025b714-0a90-4280-80da-e72d374cc5bc", "ce11171b50cc70010c", "MH19"),
)


async def _table_exists(conn, table: str) -> bool:
    try:
        result = await conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_name = :table
                """
            ),
            {"table": table},
        )
        return result.first() is not None
    except Exception:
        result = await conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name = :table"),
            {"table": table},
        )
        return result.first() is not None


async def _mh_group_exists(conn) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM device_groups WHERE id = :group_id"),
        {"group_id": MH_GROUP_ID},
    )
    return result.first() is not None


async def _validate_expected_members(conn) -> None:
    expected_ids = {device_id for device_id, _, _ in EXPECTED_MH_DEVICES}
    result = await conn.execute(
        text(
            """
            SELECT m.device_id, d.serial
            FROM device_group_members m
            LEFT JOIN devices d ON d.id = m.device_id
            WHERE m.group_id = :group_id
            """
        ),
        {"group_id": MH_GROUP_ID},
    )
    rows = result.fetchall()
    actual_ids = {str(row.device_id) for row in rows}
    actual_serials = {
        str(row.device_id): str(row.serial or "")
        for row in rows
    }

    if len(rows) != len(EXPECTED_MH_DEVICES) or actual_ids != expected_ids:
        raise RuntimeError(
            "Migration 135 expected the Mh device group to contain exactly "
            f"{len(EXPECTED_MH_DEVICES)} known phones; found {len(rows)}."
        )

    for device_id, serial, _ in EXPECTED_MH_DEVICES:
        if actual_serials.get(device_id) != serial:
            raise RuntimeError(
                "Migration 135 found an unexpected serial for a known Mh phone "
                f"({device_id})."
            )


async def upgrade(conn) -> None:
    for table in ("devices", "device_groups", "device_group_members"):
        if not await _table_exists(conn, table):
            return

    if not await _mh_group_exists(conn):
        log.info("migration 135: Mh device group is absent; no-op")
        return

    await _validate_expected_members(conn)

    for device_id, serial, new_name in EXPECTED_MH_DEVICES:
        await conn.execute(
            text(
                """
                UPDATE devices
                   SET name = :new_name,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = :device_id
                   AND serial = :serial
                   AND COALESCE(name, '') <> :new_name
                """
            ),
            {"device_id": device_id, "serial": serial, "new_name": new_name},
        )

    log.info("migration 135: renamed %s Mh phones to MH1-MH19", len(EXPECTED_MH_DEVICES))
