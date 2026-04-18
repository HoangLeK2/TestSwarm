"""020 — Enforce consistency between executions.scenario_id and scenario_version_id.

Rules:
1) If scenario_version_id is not NULL, scenario_id must not be NULL.
2) If scenario_version_id is not NULL, it must reference a scenario_version
   whose scenario_id equals executions.scenario_id.
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    # Optional auto-heal for historical rows:
    # If scenario_id is missing but scenario_version_id exists, derive scenario_id
    # from scenario_versions to keep data consistent going forward.
    await conn.execute(
        """
        UPDATE executions e
        SET scenario_id = sv.scenario_id
        FROM scenario_versions sv
        WHERE e.scenario_version_id = sv.id
          AND e.scenario_version_id IS NOT NULL
          AND e.scenario_id IS NULL;
        """
    )

    # If mismatched historical rows exist, fail migration explicitly so data
    # corruption is visible and can be repaired intentionally.
    await conn.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM executions e
                JOIN scenario_versions sv ON sv.id = e.scenario_version_id
                WHERE e.scenario_version_id IS NOT NULL
                  AND e.scenario_id IS NOT NULL
                  AND e.scenario_id <> sv.scenario_id
            ) THEN
                RAISE EXCEPTION
                    'Found executions rows where scenario_id mismatches scenario_version_id.scenario_id';
            END IF;
        END $$;
        """
    )

    # Create (or replace) validation trigger function.
    await conn.execute(
        """
        CREATE OR REPLACE FUNCTION validate_execution_scenario_version_consistency()
        RETURNS TRIGGER AS $$
        DECLARE
            sv_scenario_id VARCHAR(36);
        BEGIN
            -- No scenario version => no cross-check needed.
            IF NEW.scenario_version_id IS NULL THEN
                RETURN NEW;
            END IF;

            -- scenario_version_id present => scenario_id must be present.
            IF NEW.scenario_id IS NULL THEN
                RAISE EXCEPTION
                    'executions.scenario_id must be set when scenario_version_id is set';
            END IF;

            SELECT scenario_id
            INTO sv_scenario_id
            FROM scenario_versions
            WHERE id = NEW.scenario_version_id;

            IF sv_scenario_id IS NULL THEN
                RAISE EXCEPTION
                    'Invalid scenario_version_id: % does not exist',
                    NEW.scenario_version_id;
            END IF;

            IF sv_scenario_id <> NEW.scenario_id THEN
                RAISE EXCEPTION
                    'scenario_id (%) does not match scenario_version.scenario_id (%) for scenario_version_id (%)',
                    NEW.scenario_id, sv_scenario_id, NEW.scenario_version_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Recreate trigger idempotently.
    await conn.execute(
        """
        DROP TRIGGER IF EXISTS trg_execution_sv_consistency ON executions;
        """
    )

    await conn.execute(
        """
        CREATE TRIGGER trg_execution_sv_consistency
        BEFORE INSERT OR UPDATE OF scenario_id, scenario_version_id
        ON executions
        FOR EACH ROW
        EXECUTE FUNCTION validate_execution_scenario_version_consistency();
        """
    )
