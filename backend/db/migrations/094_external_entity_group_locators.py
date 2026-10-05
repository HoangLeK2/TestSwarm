"""094 — backfill reusable click locators for existing Facebook groups."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            UPDATE external_entities
            SET current_attributes =
                COALESCE(current_attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'locator',
                    jsonb_build_object(
                        'kind', 'facebook_group_search_result',
                        'version', 1,
                        'search_query', display_name,
                        'selector', jsonb_build_object(
                            'by', 'descriptionStartsWith',
                            'value', display_name || ','
                        ),
                        'fallback_selector', jsonb_build_object(
                            'by', 'descriptionContains',
                            'value', display_name
                        )
                    )
                )
            WHERE platform = 'facebook'
              AND entity_type = 'group'
              AND NOT (
                  COALESCE(current_attributes, '{}'::jsonb) ? 'locator'
              );
            """
        )
    )
