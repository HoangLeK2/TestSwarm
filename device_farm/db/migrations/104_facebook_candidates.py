"""Facebook candidate ranking, evidence, settings, and review history."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)


async def _try_enable_extension(conn, name: str) -> bool:
    available = await conn.execute(
        text("SELECT 1 FROM pg_available_extensions WHERE name = :name"),
        {"name": name},
    )
    if available.scalar_one_or_none() is None:
        return False
    try:
        async with conn.begin_nested():
            await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{name}"'))
    except SQLAlchemyError as exc:
        log.warning(
            "PostgreSQL extension %s is available but could not be enabled: %s",
            name,
            exc,
        )
        return False
    installed = await conn.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = :name"), {"name": name}
    )
    return installed.scalar_one_or_none() is not None


async def upgrade(conn) -> None:
    postgres = conn.dialect.name == "postgresql"
    json_type = "JSONB" if postgres else "JSON"
    timestamp_type = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    now = "NOW()" if postgres else "CURRENT_TIMESTAMP"
    empty_object = "'{}'::jsonb" if postgres else "'{}'"
    empty_array = "'[]'::jsonb" if postgres else "'[]'"

    statements = (
        f"""
        CREATE TABLE IF NOT EXISTS facebook_candidates (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            account_id VARCHAR(36) NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            external_entity_id VARCHAR(36) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'discovered',
            relationship_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            keyword_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            semantic_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            final_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            reasons {json_type} NOT NULL DEFAULT {empty_array},
            matched_keywords {json_type} NOT NULL DEFAULT {empty_array},
            negative_keywords {json_type} NOT NULL DEFAULT {empty_array},
            evidence_count INTEGER NOT NULL DEFAULT 0,
            next_eligible_at {timestamp_type},
            reviewed_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at {timestamp_type},
            review_note TEXT,
            first_observed_at {timestamp_type} NOT NULL DEFAULT {now},
            last_observed_at {timestamp_type} NOT NULL DEFAULT {now},
            created_at {timestamp_type} NOT NULL DEFAULT {now},
            updated_at {timestamp_type} NOT NULL DEFAULT {now},
            CONSTRAINT uq_facebook_candidates_identity
                UNIQUE (org_id, account_id, external_entity_id),
            CONSTRAINT uq_facebook_candidates_org_id UNIQUE (org_id, id),
            CONSTRAINT fk_facebook_candidates_org_entity
                FOREIGN KEY (org_id, external_entity_id)
                REFERENCES external_entities(org_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_facebook_candidates_status CHECK (status IN (
                'discovered', 'review_required', 'approved', 'rejected', 'deferred',
                'warming_up', 'ready_to_connect', 'request_pending', 'connected',
                'blocked'
            ))
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_org_id "
            "ON facebook_candidates (org_id)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_ranking "
            "ON facebook_candidates (org_id, status, final_score DESC, updated_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_account "
            "ON facebook_candidates (org_id, account_id, status)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS facebook_candidate_evidence (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            candidate_id VARCHAR(36) NOT NULL,
            evidence_type VARCHAR(64) NOT NULL,
            source VARCHAR(128) NOT NULL,
            source_hash VARCHAR(64) NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            normalized_text TEXT NOT NULL DEFAULT '',
            payload {json_type} NOT NULL DEFAULT {empty_object},
            observed_at {timestamp_type} NOT NULL DEFAULT {now},
            created_at {timestamp_type} NOT NULL DEFAULT {now},
            CONSTRAINT fk_facebook_candidate_evidence_org_candidate
                FOREIGN KEY (org_id, candidate_id)
                REFERENCES facebook_candidates(org_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_facebook_candidate_evidence_source
                UNIQUE (org_id, candidate_id, source_hash)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_evidence_org_id "
            "ON facebook_candidate_evidence (org_id)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_evidence_candidate_time "
            "ON facebook_candidate_evidence (org_id, candidate_id, observed_at DESC)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS facebook_candidate_keywords (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            candidate_id VARCHAR(36) NOT NULL,
            keyword VARCHAR(255) NOT NULL,
            normalized_keyword VARCHAR(255) NOT NULL,
            keyword_type VARCHAR(16) NOT NULL,
            match_count INTEGER NOT NULL DEFAULT 1,
            first_matched_at {timestamp_type} NOT NULL DEFAULT {now},
            last_matched_at {timestamp_type} NOT NULL DEFAULT {now},
            CONSTRAINT fk_facebook_candidate_keywords_org_candidate
                FOREIGN KEY (org_id, candidate_id)
                REFERENCES facebook_candidates(org_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_facebook_candidate_keywords_match
                UNIQUE (org_id, candidate_id, keyword_type, normalized_keyword),
            CONSTRAINT ck_facebook_candidate_keywords_type
                CHECK (keyword_type IN ('positive', 'negative'))
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_keywords_org_id "
            "ON facebook_candidate_keywords (org_id)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_keywords_lookup "
            "ON facebook_candidate_keywords (org_id, keyword_type, normalized_keyword)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS facebook_candidate_embeddings (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            candidate_id VARCHAR(36) NOT NULL,
            embedding {json_type} NOT NULL DEFAULT {empty_array},
            model VARCHAR(128) NOT NULL,
            dimensions INTEGER NOT NULL,
            source_hash VARCHAR(64) NOT NULL,
            created_at {timestamp_type} NOT NULL DEFAULT {now},
            CONSTRAINT fk_facebook_candidate_embeddings_org_candidate
                FOREIGN KEY (org_id, candidate_id)
                REFERENCES facebook_candidates(org_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_facebook_candidate_embeddings_source
                UNIQUE (org_id, candidate_id, model, source_hash)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_embeddings_org_id "
            "ON facebook_candidate_embeddings (org_id)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_embeddings_candidate "
            "ON facebook_candidate_embeddings (org_id, candidate_id, created_at DESC)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS facebook_candidate_settings (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            relationship_weight DOUBLE PRECISION NOT NULL DEFAULT 0.4,
            keyword_weight DOUBLE PRECISION NOT NULL DEFAULT 0.35,
            semantic_weight DOUBLE PRECISION NOT NULL DEFAULT 0.25,
            review_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.55,
            positive_keywords {json_type} NOT NULL DEFAULT {empty_array},
            negative_keywords {json_type} NOT NULL DEFAULT {empty_array},
            embedding_model VARCHAR(128) NOT NULL DEFAULT 'multilingual-e5-small',
            embedding_dimensions INTEGER NOT NULL DEFAULT 384,
            updated_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            created_at {timestamp_type} NOT NULL DEFAULT {now},
            updated_at {timestamp_type} NOT NULL DEFAULT {now},
            CONSTRAINT uq_facebook_candidate_settings_org UNIQUE (org_id)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_settings_org_id "
            "ON facebook_candidate_settings (org_id)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS facebook_candidate_reviews (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            candidate_id VARCHAR(36) NOT NULL,
            from_status VARCHAR(32) NOT NULL,
            to_status VARCHAR(32) NOT NULL,
            reviewer_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            note TEXT,
            score_snapshot {json_type} NOT NULL DEFAULT {empty_object},
            created_at {timestamp_type} NOT NULL DEFAULT {now},
            CONSTRAINT fk_facebook_candidate_reviews_org_candidate
                FOREIGN KEY (org_id, candidate_id)
                REFERENCES facebook_candidates(org_id, id) ON DELETE CASCADE
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_reviews_org_id "
            "ON facebook_candidate_reviews (org_id)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidate_reviews_candidate_time "
            "ON facebook_candidate_reviews (org_id, candidate_id, created_at DESC)"
        ),
    )
    for statement in statements:
        await conn.execute(text(statement))

    if not postgres:
        return

    if await _try_enable_extension(conn, "pg_trgm"):
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_external_entities_display_name_trgm "
                "ON external_entities USING gin (display_name gin_trgm_ops)"
            )
        )

    if await _try_enable_extension(conn, "vector"):
        await conn.execute(
            text(
                "ALTER TABLE facebook_candidate_embeddings "
                "ADD COLUMN IF NOT EXISTS embedding_vector vector(384)"
            )
        )
        try:
            async with conn.begin_nested():
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "idx_facebook_candidate_embeddings_hnsw "
                        "ON facebook_candidate_embeddings USING hnsw "
                        "(embedding_vector vector_cosine_ops)"
                    )
                )
        except SQLAlchemyError as exc:
            log.warning(
                "pgvector is enabled but HNSW index creation was skipped: %s", exc
            )


async def downgrade(conn) -> None:
    if conn.dialect.name == "postgresql":
        await conn.execute(
            text("DROP INDEX IF EXISTS idx_external_entities_display_name_trgm")
        )
    for table in (
        "facebook_candidate_reviews",
        "facebook_candidate_embeddings",
        "facebook_candidate_keywords",
        "facebook_candidate_evidence",
        "facebook_candidate_settings",
        "facebook_candidates",
    ):
        await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
