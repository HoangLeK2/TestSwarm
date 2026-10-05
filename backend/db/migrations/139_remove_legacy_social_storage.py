"""Remove legacy social-product storage from Android Platform Tester."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    # These catalogs are optional across older installations. Keep the cleanup
    # conditional so the migration is safe on both clean and upgraded databases.
    await conn.execute(
        text(
            """
            DELETE FROM account_import_formats
            WHERE lower(platform) = 'facebook'
               OR lower(slug) LIKE 'facebook%'
            """
        )
    )
    await conn.execute(
        text(
            """
            DELETE FROM content_types
            WHERE lower(platform) = 'facebook'
               OR lower(code) LIKE 'fb_%'
            """
        )
    )
    await conn.execute(
        text(
            """
            DELETE FROM device_platform_sessions
            WHERE lower(platform) = 'facebook'
               OR lower(coalesce(app_package, '')) LIKE 'com.facebook.%'
            """
        )
    )
    await conn.execute(text("DELETE FROM accounts WHERE lower(platform) = 'facebook'"))
    await conn.execute(
        text(
            """
            DELETE FROM content_items
            WHERE lower(platform) = 'facebook'
               OR lower(content_type) LIKE 'fb_%'
            """
        )
    )

    # Candidate ranking tables belonged to the removed integration and have no
    # active ORM model or API consumer in Platform Tester.
    for table in (
        "facebook_candidate_reviews",
        "facebook_candidate_embeddings",
        "facebook_candidate_keywords",
        "facebook_candidate_evidence",
        "facebook_candidate_settings",
        "facebook_candidates",
    ):
        await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
