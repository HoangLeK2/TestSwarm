"""019 — Merge campaign_runs into executions.

campaign_runs and executions are dual aggregates for the same semantic concept
("one campaign run"). This migration:
  1. Backfills content_items.execution_id from campaign_runs where missing
  2. Copies workflow_ids / scenarios_count into executions.meta
  3. Drops content_items.run_id FK column
  4. Drops campaign_runs table
  5. Removes the campaign_runs CHECK constraint
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    # ── 1. Backfill content_items.execution_id from campaign_runs ────────────
    # Legacy-safe strategy:
    #   A) Ensure one execution exists per campaign_run id (reuse id = run_id)
    #   B) Map run_id -> execution_id directly
    #   C) Fallback by campaign/time for any remaining rows
    await conn.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('campaign_runs') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'content_items' AND column_name = 'run_id'
               ) THEN
                -- A) Create missing executions from campaign_runs (id-stable mapping)
                INSERT INTO executions (
                    id,
                    run_type,
                    status,
                    campaign_id,
                    device_config,
                    loop_config,
                    error_config,
                    meta,
                    created_at,
                    started_at,
                    finished_at
                )
                SELECT
                    cr.id,
                    'campaign_run',
                    CASE
                        WHEN cr.status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
                            THEN cr.status
                        ELSE 'running'
                    END,
                    cr.campaign_id,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    jsonb_build_object(
                        'workflow_ids', COALESCE(cr.workflow_ids, '[]'::json),
                        'scenarios_count', COALESCE(cr.scenarios_count, 0)
                    ),
                    COALESCE(cr.started_at, NOW()),
                    cr.started_at,
                    cr.finished_at
                FROM campaign_runs cr
                WHERE NOT EXISTS (
                    SELECT 1 FROM executions e WHERE e.id = cr.id
                );

                -- B) Direct run_id -> execution_id mapping (canonical)
                UPDATE content_items ci
                SET execution_id = ci.run_id
                WHERE ci.run_id IS NOT NULL
                  AND ci.execution_id IS NULL
                  AND EXISTS (SELECT 1 FROM executions e WHERE e.id = ci.run_id);

                -- C) Time-nearest fallback by campaign (for dirty legacy data)
                UPDATE content_items ci
                SET execution_id = (
                    SELECT e.id FROM executions e
                    WHERE e.campaign_id = ci.campaign_id
                      AND e.run_type = 'campaign_run'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (e.created_at - ci.created_at)))
                    LIMIT 1
                )
                WHERE ci.run_id IS NOT NULL
                  AND ci.execution_id IS NULL
                  AND ci.campaign_id IS NOT NULL;
            END IF;
        END $$;
        """
    )

    # Guardrail (soft): keep a log signal for operators, but do not abort startup.
    await conn.execute(
        """
        DO $$
        DECLARE
            orphan_count BIGINT := 0;
        BEGIN
            IF to_regclass('campaign_runs') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'content_items' AND column_name = 'run_id'
               ) THEN
                SELECT COUNT(*)
                INTO orphan_count
                FROM content_items ci
                WHERE ci.run_id IS NOT NULL
                  AND ci.execution_id IS NULL;

                IF orphan_count > 0 THEN
                    RAISE NOTICE
                        'Migration 019: % legacy content_items rows still unmapped (execution_id IS NULL). Proceeding with drop.',
                        orphan_count;
                END IF;
            END IF;
        END $$;
        """
    )

    # ── 2. Copy workflow_ids + scenarios_count into executions.meta ───────────
    # Match each execution to the nearest campaign_run by timestamp within
    # the same campaign to avoid many-to-many arbitrary updates.
    await conn.execute(
        """
        DO $$
        DECLARE
            meta_type TEXT;
        BEGIN
            IF to_regclass('campaign_runs') IS NOT NULL THEN
                SELECT c.data_type
                INTO meta_type
                FROM information_schema.columns c
                WHERE c.table_name = 'executions'
                  AND c.column_name = 'meta'
                LIMIT 1;

                IF meta_type = 'json' THEN
                    WITH ranked_matches AS (
                        SELECT
                            e.id AS execution_id,
                            cr.workflow_ids,
                            cr.scenarios_count,
                            ROW_NUMBER() OVER (
                                PARTITION BY e.id
                                ORDER BY ABS(EXTRACT(EPOCH FROM (e.created_at - cr.started_at)))
                            ) AS rn
                        FROM executions e
                        JOIN campaign_runs cr
                          ON cr.campaign_id = e.campaign_id
                        WHERE e.run_type = 'campaign_run'
                          AND cr.workflow_ids IS NOT NULL
                    )
                    UPDATE executions e
                    SET meta = (
                        COALESCE(e.meta::jsonb, '{}'::jsonb)
                        || jsonb_build_object('workflow_ids', COALESCE(rm.workflow_ids::jsonb, '[]'::jsonb))
                        || jsonb_build_object('scenarios_count', rm.scenarios_count)
                    )::json
                    FROM ranked_matches rm
                    WHERE rm.execution_id = e.id
                      AND rm.rn = 1;
                ELSE
                    WITH ranked_matches AS (
                        SELECT
                            e.id AS execution_id,
                            cr.workflow_ids,
                            cr.scenarios_count,
                            ROW_NUMBER() OVER (
                                PARTITION BY e.id
                                ORDER BY ABS(EXTRACT(EPOCH FROM (e.created_at - cr.started_at)))
                            ) AS rn
                        FROM executions e
                        JOIN campaign_runs cr
                          ON cr.campaign_id = e.campaign_id
                        WHERE e.run_type = 'campaign_run'
                          AND cr.workflow_ids IS NOT NULL
                    )
                    UPDATE executions e
                    SET meta = COALESCE(e.meta::jsonb, '{}'::jsonb)
                        || jsonb_build_object('workflow_ids', COALESCE(rm.workflow_ids::jsonb, '[]'::jsonb))
                        || jsonb_build_object('scenarios_count', rm.scenarios_count)
                    FROM ranked_matches rm
                    WHERE rm.execution_id = e.id
                      AND rm.rn = 1;
                END IF;
            END IF;
        END $$;
        """
    )

    # ── 3. Drop content_items.run_id FK and column ───────────────────────────
    # First drop FK constraint (name varies, use dynamic lookup)
    await conn.execute(
        """
        DO $$
        DECLARE
            fk_name TEXT;
        BEGIN
            IF to_regclass('campaign_runs') IS NOT NULL THEN
                SELECT conname INTO fk_name
                FROM pg_constraint
                WHERE conrelid = 'content_items'::regclass
                  AND confrelid = to_regclass('campaign_runs')
                LIMIT 1;
            END IF;

            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE content_items DROP CONSTRAINT %I', fk_name);
            END IF;
        END $$;
        """
    )

    await conn.execute(
        "DROP INDEX IF EXISTS ix_content_items_run_id;"
    )

    await conn.execute(
        """
        ALTER TABLE content_items DROP COLUMN IF EXISTS run_id;
        """
    )

    # ── 4. Drop campaign_runs CHECK constraint ───────────────────────────────
    await conn.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('campaign_runs') IS NOT NULL AND EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_campaign_run_status'
            ) THEN
                ALTER TABLE campaign_runs DROP CONSTRAINT check_campaign_run_status;
            END IF;
        END $$;
        """
    )

    # ── 5. Drop campaign_runs table ──────────────────────────────────────────
    await conn.execute("DROP TABLE IF EXISTS campaign_runs CASCADE;")
