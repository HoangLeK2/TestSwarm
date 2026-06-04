"""Audit post→comment linking for a content item id (local DB)."""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import func, or_, select

from db.crud.content import get_content_item, query_content_children
from db.database import activity_session
from db.models.content import ContentItem
from services.content.parent_links import parent_link_candidates, parent_post_id_values
from tenancy.context import set_current_org_id


async def audit(post_id: str) -> None:
    async with activity_session() as db:
        # Bootstrap org context (strict tenancy) from the row itself.
        bootstrap = await db.execute(
            select(ContentItem.org_id).where(ContentItem.id == post_id)
        )
        org_id = bootstrap.scalar_one_or_none()
        if org_id:
            set_current_org_id(org_id)

        post = await get_content_item(db, post_id)
        if post is None:
            print(f"POST {post_id}: not found")
            return

        print("=== POST ===")
        print(f"id={post.id}")
        print(f"content_type={post.content_type} collection={post.collection}")
        print(f"content_hash={post.content_hash}")
        print(f"execution_id={post.execution_id} campaign_id={post.campaign_id}")
        print(f"comments_count(col)={post.comments_count}")
        raw = post.raw_data if isinstance(post.raw_data, dict) else {}
        for k in ("post_key", "parent_post_id", "_pid", "stable_post_id", "fb_post_id"):
            if raw.get(k):
                print(f"raw.{k}={raw.get(k)!r}")

        candidates = parent_link_candidates(post)
        pid_values = parent_post_id_values(post)
        print(f"\nparent_link_candidates ({len(candidates)}):")
        for c in candidates[:12]:
            print(f"  - {c}")
        if len(candidates) > 12:
            print(f"  ... +{len(candidates) - 12} more")
        print(f"parent_post_id_values: {pid_values}")

        # Legacy list filter: exact parent_id only
        legacy_stmt = select(func.count()).select_from(
            select(ContentItem)
            .where(
                ContentItem.deleted_at.is_(None),
                ContentItem.content_type == "fb_comment",
                ContentItem.parent_id == post.content_hash,
            )
            .subquery()
        )
        legacy_count = (await db.execute(legacy_stmt)).scalar_one()

        cand_stmt = select(func.count()).select_from(
            select(ContentItem)
            .where(
                ContentItem.deleted_at.is_(None),
                ContentItem.content_type == "fb_comment",
                ContentItem.parent_id.in_(candidates),
            )
            .subquery()
        )
        cand_count = (await db.execute(cand_stmt)).scalar_one()

        children, total = await query_content_children(db, post, limit=500, offset=0)

        camp_stmt = select(func.count()).select_from(
            select(ContentItem)
            .where(
                ContentItem.deleted_at.is_(None),
                ContentItem.content_type == "fb_comment",
                ContentItem.campaign_id == post.campaign_id,
            )
            .subquery()
        )
        camp_count = (await db.execute(camp_stmt)).scalar_one() if post.campaign_id else None

        print("\n=== COUNTS ===")
        print(f"legacy parent_id == content_hash only: {legacy_count}")
        print(f"fb_comment parent_id in candidates:      {cand_count}")
        print(f"query_content_children (API):          {total} (fetched {len(children)})")
        if camp_count is not None:
            print(f"all fb_comment in same campaign:         {camp_count}")

        # How stored parent_ids relate to post
        sample_stmt = (
            select(
                ContentItem.parent_id,
                ContentItem.raw_data["parent_post_id"].as_string(),
                ContentItem.raw_data["post_key"].as_string(),
            )
            .where(
                ContentItem.deleted_at.is_(None),
                ContentItem.content_type == "fb_comment",
                ContentItem.campaign_id == post.campaign_id,
            )
            .limit(8)
        )
        if post.campaign_id:
            rows = (await db.execute(sample_stmt)).all()
            print("\n=== SAMPLE COMMENT LINK FIELDS (same campaign) ===")
            for pid, r_parent_post, r_post_key in rows:
                in_cand = pid in candidates if pid else False
                print(
                    f"parent_id={pid!r} in_candidates={in_cand} "
                    f"raw.parent_post_id={r_parent_post!r} raw.post_key={r_post_key!r}"
                )

        mism = [c for c in children if c.parent_id and c.parent_id not in candidates]
        print(f"\nchildren with parent_id NOT in candidates: {len(mism)}")

        exec_mism = [
            c for c in children if post.execution_id and c.execution_id != post.execution_id
        ]
        print(f"children different execution_id than post: {len(exec_mism)}")


def main() -> None:
    post_id = sys.argv[1] if len(sys.argv) > 1 else "178a29be-cd51-44ef-98c7-a3bb69f83c1f"
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    # Allow bootstrap SELECT by id before org context is known.
    os.environ.setdefault("TENANCY_STRICT_MODE", "false")
    asyncio.run(audit(post_id))


if __name__ == "__main__":
    main()
