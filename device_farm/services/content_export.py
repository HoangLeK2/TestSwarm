"""DF-010: Content Export — CSV/JSON export with background processing."""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")

CSV_FIELDS = [
    "id", "collection", "platform", "content_type", "author", "title", "body",
    "url", "likes_count", "comments_count", "shares_count", "views_count",
    "tags", "device_serial", "campaign_id", "extracted_at",
]


async def process_export(export_id: str) -> None:
    from db.database import AsyncSessionLocal
    from db.crud.content import get_export, update_export, query_content

    async with AsyncSessionLocal() as db:
        export = await get_export(db, export_id)
        if not export:
            log.error(f"Export {export_id} not found")
            return

        await update_export(db, export_id, status="processing")
        await db.commit()

    try:
        os.makedirs(EXPORT_DIR, exist_ok=True)

        async with AsyncSessionLocal() as db:
            filters = export.filters or {}
            items, total = await query_content(
                db,
                collection=filters.get("collection") or export.collection,
                platform=filters.get("platform"),
                content_type=filters.get("content_type"),
                search=filters.get("search"),
                device_serial=filters.get("device_serial"),
                campaign_id=filters.get("campaign_id"),
                limit=100_000,  # cap for safety
                offset=0,
            )

        fmt = export.format or "csv"
        ext = fmt
        file_path = os.path.join(EXPORT_DIR, f"{export_id}.{ext}")

        if fmt == "csv":
            _write_csv(file_path, items)
        elif fmt == "json":
            _write_json(file_path, items)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        file_size = os.path.getsize(file_path)

        async with AsyncSessionLocal() as db:
            await update_export(
                db, export_id,
                status="ready",
                file_path=file_path,
                file_size_bytes=file_size,
                item_count=len(items),
                completed_at=datetime.utcnow(),
            )
            await db.commit()

        log.info(f"Export {export_id} ready: {len(items)} items, {file_size} bytes")

    except Exception as exc:
        log.error(f"Export {export_id} failed: {exc}")
        async with AsyncSessionLocal() as db:
            await update_export(db, export_id, status="failed")
            await db.commit()


def _write_csv(path: str, items: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            writer.writerow(item.to_dict())


def _write_json(path: str, items: list) -> None:
    data = [item.to_dict() for item in items]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
