"""092 — reusable external entity catalog, history, discovery and assignments."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS external_entities (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL
                REFERENCES organizations(id) ON DELETE RESTRICT,
            platform VARCHAR(32) NOT NULL,
            entity_type VARCHAR(32) NOT NULL,
            identity_key VARCHAR(80) NOT NULL,
            identity_confidence VARCHAR(24) NOT NULL DEFAULT 'name_only',
            external_id VARCHAR(255),
            canonical_url VARCHAR(1000),
            display_name VARCHAR(500) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'candidate',
            current_attributes JSONB NOT NULL DEFAULT '{}',
            current_metrics JSONB NOT NULL DEFAULT '{}',
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_external_entities_identity
                UNIQUE (org_id, platform, entity_type, identity_key),
            CONSTRAINT uq_external_entities_org_id UNIQUE (org_id, id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_external_entities_org_id "
        "ON external_entities (org_id)",
        "CREATE INDEX IF NOT EXISTS idx_external_entities_catalog "
        "ON external_entities (org_id, platform, entity_type, status)",
        "CREATE INDEX IF NOT EXISTS idx_external_entities_last_seen "
        "ON external_entities (org_id, last_seen_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS external_entity_observations (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL
                REFERENCES organizations(id) ON DELETE RESTRICT,
            external_entity_id VARCHAR(36) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            display_name VARCHAR(500) NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            metrics JSONB NOT NULL DEFAULT '{}',
            raw_data JSONB NOT NULL DEFAULT '{}',
            account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
            execution_id VARCHAR(36) REFERENCES executions(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_external_entity_observations_org_entity
                FOREIGN KEY (org_id, external_entity_id)
                REFERENCES external_entities(org_id, id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_external_entity_observations_org_id "
        "ON external_entity_observations (org_id)",
        "CREATE INDEX IF NOT EXISTS idx_external_entity_observations_entity_time "
        "ON external_entity_observations "
        "(org_id, external_entity_id, observed_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_external_entity_observations_execution "
        "ON external_entity_observations (org_id, execution_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_external_entity_observations_execution_entity "
        "ON external_entity_observations "
        "(org_id, external_entity_id, execution_id) "
        "WHERE execution_id IS NOT NULL",
        """
        CREATE TABLE IF NOT EXISTS external_entity_discoveries (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL
                REFERENCES organizations(id) ON DELETE RESTRICT,
            external_entity_id VARCHAR(36) NOT NULL,
            query VARCHAR(500) NOT NULL,
            rank INTEGER,
            context JSONB NOT NULL DEFAULT '{}',
            account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
            execution_id VARCHAR(36) REFERENCES executions(id) ON DELETE SET NULL,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_external_entity_discoveries_org_entity
                FOREIGN KEY (org_id, external_entity_id)
                REFERENCES external_entities(org_id, id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_external_entity_discoveries_org_id "
        "ON external_entity_discoveries (org_id)",
        "CREATE INDEX IF NOT EXISTS idx_external_entity_discoveries_query_time "
        "ON external_entity_discoveries (org_id, query, observed_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_external_entity_discoveries_entity_time "
        "ON external_entity_discoveries "
        "(org_id, external_entity_id, observed_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_external_entity_discoveries_execution_query "
        "ON external_entity_discoveries "
        "(org_id, external_entity_id, execution_id, query) "
        "WHERE execution_id IS NOT NULL",
        """
        CREATE TABLE IF NOT EXISTS execution_entity_assignments (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL
                REFERENCES organizations(id) ON DELETE RESTRICT,
            dispatch_id VARCHAR(36) NOT NULL,
            execution_id VARCHAR(36) NOT NULL
                REFERENCES executions(id) ON DELETE CASCADE,
            device_id VARCHAR(36) NOT NULL
                REFERENCES devices(id) ON DELETE CASCADE,
            external_entity_id VARCHAR(36) NOT NULL,
            assignment_key VARCHAR(64) NOT NULL DEFAULT 'primary',
            status VARCHAR(24) NOT NULL DEFAULT 'assigned',
            snapshot JSONB NOT NULL DEFAULT '{}',
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            CONSTRAINT fk_execution_entity_assignments_org_entity
                FOREIGN KEY (org_id, external_entity_id)
                REFERENCES external_entities(org_id, id) ON DELETE RESTRICT,
            CONSTRAINT uq_execution_entity_assignments_execution_key
                UNIQUE (org_id, execution_id, assignment_key),
            CONSTRAINT uq_execution_entity_assignments_dispatch_entity
                UNIQUE (org_id, dispatch_id, external_entity_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_execution_entity_assignments_org_id "
        "ON execution_entity_assignments (org_id)",
        "CREATE INDEX IF NOT EXISTS idx_execution_entity_assignments_dispatch "
        "ON execution_entity_assignments (org_id, dispatch_id)",
        "CREATE INDEX IF NOT EXISTS idx_execution_entity_assignments_device "
        "ON execution_entity_assignments (org_id, device_id, assigned_at DESC)",
    )
    for statement in statements:
        await conn.execute(text(statement))
