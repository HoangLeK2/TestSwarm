"""Copy legacy campaigns.scenario JSON into a Scenario row when the campaign has none."""

from sqlalchemy import text


async def upgrade(conn) -> None:
    chk = await conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'campaigns' AND column_name = 'scenario'"
    ))
    if chk.first() is None:
        return
    await conn.execute(text("""
        INSERT INTO scenarios (
            id, campaign_id, name, instructions, steps, nodes, edges, variables, "order", created_at, updated_at
        )
        SELECT
            gen_random_uuid()::text,
            c.id,
            LEFT(c.name, 255),
            COALESCE(NULLIF(BTRIM(c.scenario::jsonb->>'instructions'), ''), ''),
            COALESCE(c.scenario::jsonb->'steps', '[]'::jsonb),
            COALESCE(c.scenario::jsonb->'nodes', '[]'::jsonb),
            COALESCE(c.scenario::jsonb->'edges', '[]'::jsonb),
            (
                COALESCE(c.scenario::jsonb->'variables', '{}'::jsonb)
                || COALESCE(c.variables::jsonb, '{}'::jsonb)
                || CASE WHEN (c.scenario::jsonb ? 'device_context')
                    THEN jsonb_build_object(
                        '__device_context__',
                        c.scenario::jsonb->'device_context'
                    )
                    ELSE '{}'::jsonb END
            ),
            0,
            NOW(),
            NOW()
        FROM campaigns c
        WHERE NOT EXISTS (SELECT 1 FROM scenarios s WHERE s.campaign_id = c.id)
          AND c.scenario IS NOT NULL
          AND c.scenario::text NOT IN ('null', '{}')
          AND (
            jsonb_array_length(COALESCE(c.scenario::jsonb->'steps', '[]'::jsonb)) > 0
            OR LENGTH(COALESCE(BTRIM(c.scenario::jsonb->>'instructions'), '')) > 0
            OR COALESCE(c.scenario::jsonb->'variables', '{}'::jsonb) <> '{}'::jsonb
            OR (c.scenario::jsonb ? 'device_context')
          )
    """))
