from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.account_discovery import router as account_discovery_router
from api.routes.facebook_candidates import router
from db.database import Base
from db.models import Account, ContentItem, ExternalEntity, Organization, User
from db.models.facebook_candidate import FacebookCandidateReview
from services.account_discovery import (
    get_account_discovery_state,
    mark_account_discovery_started,
    request_account_discovery,
)
from services.account_candidate_discovery import (
    discover_and_lease_candidate,
    get_discovery_provider,
    register_discovery_provider,
)
from services.facebook_candidates import (
    CandidateLeaseAttempt,
    assert_candidate_action_allowed,
    complete_candidate_lease,
    lease_next_ready_candidate,
    normalize_vietnamese_text,
    release_candidate_leases_for_execution,
    update_candidate_settings,
    _ready_candidate_lease_query,
)
from tenancy.context import set_current_org_id

ORG_A = "org-candidate-a"
ORG_B = "org-candidate-b"
USER_A = "user-candidate-a"
USER_B = "user-candidate-b"
ACCOUNT_A1 = "account-a-1"
ACCOUNT_A2 = "account-a-2"
ACCOUNT_B = "account-b-1"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await _seed(factory)
    yield factory
    set_current_org_id(None)
    await engine.dispose()


async def _seed(session_factory) -> None:
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add_all(
            [
                Organization(
                    id=ORG_A,
                    business_name="Candidate A",
                    business_email="candidate-a@example.com",
                    status="active",
                    plan="standard",
                    created_at=now,
                ),
                Organization(
                    id=ORG_B,
                    business_name="Candidate B",
                    business_email="candidate-b@example.com",
                    status="active",
                    plan="standard",
                    created_at=now,
                ),
                User(
                    id=USER_A,
                    email="candidate-a@example.com",
                    name="Candidate A",
                    hashed_password="hashed",
                    org_id=ORG_A,
                ),
                User(
                    id=USER_B,
                    email="candidate-b@example.com",
                    name="Candidate B",
                    hashed_password="hashed",
                    org_id=ORG_B,
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                Account(
                    id=ACCOUNT_A1,
                    org_id=ORG_A,
                    platform="facebook",
                    username="candidate-a-1",
                ),
                Account(
                    id=ACCOUNT_A2,
                    org_id=ORG_A,
                    platform="facebook",
                    username="candidate-a-2",
                ),
                Account(
                    id=ACCOUNT_B,
                    org_id=ORG_B,
                    platform="facebook",
                    username="candidate-b-1",
                ),
                ExternalEntity(
                    id="entity-a-1",
                    org_id=ORG_A,
                    platform="facebook",
                    entity_type="profile",
                    identity_key="entity-a-1",
                    display_name="Nguyen Van A",
                    status="candidate",
                ),
                ExternalEntity(
                    id="entity-a-2",
                    org_id=ORG_A,
                    platform="facebook",
                    entity_type="profile",
                    identity_key="entity-a-2",
                    display_name="Tran Thi B",
                    status="candidate",
                ),
                ExternalEntity(
                    id="entity-b-1",
                    org_id=ORG_B,
                    platform="facebook",
                    entity_type="profile",
                    identity_key="entity-b-1",
                    display_name="Foreign Candidate",
                    status="candidate",
                ),
            ]
        )
        await db.commit()


def _app(session_factory, *, org_id: str = ORG_A, user_id: str = USER_A) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(account_discovery_router, prefix="/api")

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def user_override():
        set_current_org_id(org_id)
        return SimpleNamespace(id=user_id, org_id=org_id, org_role="owner")

    async def allow_permission():
        return None

    app.dependency_overrides[_get_db] = db_override
    app.dependency_overrides[_get_current_user] = user_override
    for route_entry in app.routes:
        for dependency in getattr(
            getattr(route_entry, "dependant", None), "dependencies", []
        ):
            if getattr(dependency.call, "__name__", "") == "_require_permission":
                app.dependency_overrides[dependency.call] = allow_permission
    return app


def _settings(**overrides):
    values = {
        "relationship_weight": 0.2,
        "keyword_weight": 0.4,
        "semantic_weight": 0.4,
        "review_threshold": 0.55,
        "positive_keywords": ["công nghệ", "khởi nghiệp"],
        "negative_keywords": ["lừa đảo"],
        "embedding_model": "test-multilingual",
        "embedding_dimensions": 3,
    }
    values.update(overrides)
    return values


async def _put_settings(client: AsyncClient, **overrides):
    response = await client.put(
        "/api/facebook-candidate-settings", json=_settings(**overrides)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _observe(
    client: AsyncClient,
    *,
    account_id: str = ACCOUNT_A1,
    entity_id: str = "entity-a-1",
    relationship_score: float = 0.5,
    semantic_score: float = 0.75,
    text_value: str = "Tôi làm về CONG NGHE và khởi nghiệp",
):
    return await client.post(
        "/api/facebook-candidates",
        json={
            "account_id": account_id,
            "external_entity_id": entity_id,
            "relationship_score": relationship_score,
            "semantic_score": semantic_score,
            "evidence": [
                {
                    "evidence_type": "profile_bio",
                    "source": "facebook_profile",
                    "text": text_value,
                    "payload": {"public": True},
                }
            ],
            "embedding": {
                "values": [0.1, 0.2, 0.3],
                "model": "test-multilingual",
                "dimensions": 3,
                "source_hash": "a" * 64,
            },
        },
    )


def _content_item(
    *,
    item_id: str,
    content_hash: str,
    author: str,
    author_id: str | None,
    account_id: str | None,
    body: str,
) -> ContentItem:
    return ContentItem(
        id=item_id,
        org_id=ORG_A,
        user_id=USER_A,
        collection="facebook-discovery-test",
        platform="facebook",
        content_type="fb_post",
        author=author,
        author_id=author_id,
        account_id=account_id,
        body=body,
        content_hash=content_hash,
    )


async def _enable_keyword_auto_ready(
    db: AsyncSession,
    *,
    positive_keywords: list[str],
    min_evidence: int = 2,
) -> None:
    await update_candidate_settings(
        db,
        org_id=ORG_A,
        relationship_weight=0.2,
        keyword_weight=0.8,
        semantic_weight=0,
        review_threshold=0.55,
        auto_ready_enabled=True,
        auto_ready_threshold=0.8,
        auto_ready_min_evidence=min_evidence,
        positive_keywords=positive_keywords,
        negative_keywords=[],
        embedding_model="test-multilingual",
        embedding_dimensions=3,
        updated_by=USER_A,
    )


@pytest.mark.asyncio
async def test_discovery_bootstraps_scores_and_leases_from_account_content(
    session_factory,
):
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await _enable_keyword_auto_ready(db, positive_keywords=["cong nghe"])
        db.add_all(
            [
                _content_item(
                    item_id="content-account-1",
                    content_hash="1" * 64,
                    author="Le Minh",
                    author_id="profile-100",
                    account_id=ACCOUNT_A1,
                    body="Bai viet cong nghe thu nhat",
                ),
                _content_item(
                    item_id="content-account-2",
                    content_hash="2" * 64,
                    author="Le Minh",
                    author_id="profile-100",
                    account_id=ACCOUNT_A1,
                    body="Bai viet cong nghe thu hai",
                ),
            ]
        )
        await db.flush()

        result = await discover_and_lease_candidate(
            db,
            platform="facebook",
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-discovery-account",
        )

        assert result.attempt.outcome == "leased"
        assert result.discovery is not None
        assert result.discovery.source_scope == "account"
        assert result.discovery.observed_count == 1
        assert result.discovery.ready_count == 1
        assert result.attempt.lease is not None
        assert result.attempt.lease.external_entity.external_id == "profile-100"
        assert result.attempt.lease.candidate.evidence_count == 2


@pytest.mark.asyncio
async def test_discovery_uses_org_fallback_for_account_without_history(session_factory):
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await _enable_keyword_auto_ready(db, positive_keywords=["cong nghe"])
        db.add_all(
            [
                _content_item(
                    item_id=f"content-fallback-{index}",
                    content_hash=f"{index + 3:064x}",
                    author="Tran New",
                    author_id="profile-200",
                    account_id=ACCOUNT_A1,
                    body=f"Nguoi dung co cung chu de cong nghe {index}",
                )
                for index in range(5)
            ]
        )
        await db.flush()

        result = await discover_and_lease_candidate(
            db,
            platform="facebook",
            org_id=ORG_A,
            account_id=ACCOUNT_A2,
            execution_id="execution-discovery-fallback",
        )

        assert result.attempt.outcome == "leased"
        assert result.discovery is not None
        assert result.discovery.source_scope == "organization"
        assert result.discovery.ready_count == 1
        assert result.attempt.lease is not None
        assert result.attempt.lease.candidate.account_id == ACCOUNT_A2


@pytest.mark.asyncio
async def test_discovery_does_not_rerun_while_only_ready_candidate_is_leased(
    session_factory,
):
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await _enable_keyword_auto_ready(db, positive_keywords=["evidence"])
        db.add_all(
            [
                _content_item(
                    item_id=f"content-busy-{index}",
                    content_hash=f"{700 + index:064x}",
                    author="Busy Candidate",
                    author_id="profile-busy",
                    account_id=ACCOUNT_A1,
                    body=f"Repeated evidence {index}",
                )
                for index in range(2)
            ]
        )
        await db.flush()

        first = await discover_and_lease_candidate(
            db,
            platform="facebook",
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-first-lease",
        )
        second = await discover_and_lease_candidate(
            db,
            platform="facebook",
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-second-lease",
        )

        assert first.attempt.outcome == "leased"
        assert second.attempt.outcome == "candidate_busy"
        assert second.discovery is None


@pytest.mark.asyncio
async def test_discovery_orchestrator_delegates_lease_to_registered_provider():
    class BusyProvider:
        platform = "test-social"

        def __init__(self):
            self.lease_calls = 0

        async def lease(self, _db, **_kwargs):
            self.lease_calls += 1
            return CandidateLeaseAttempt(
                lease=None,
                outcome="candidate_busy",
                discovery_requested=False,
            )

        async def discover(self, _db, **_kwargs):
            raise AssertionError("busy provider must not run discovery")

    provider = BusyProvider()
    register_discovery_provider(provider)
    result = await discover_and_lease_candidate(
        object(),  # type: ignore[arg-type]
        platform=provider.platform,
        org_id=ORG_A,
        account_id=ACCOUNT_A1,
        execution_id="execution-provider-contract",
    )

    assert result.attempt.outcome == "candidate_busy"
    assert result.discovery is None
    assert provider.lease_calls == 1


@pytest.mark.asyncio
async def test_discovery_failure_is_persisted_as_runtime_outcome(session_factory):
    original = get_discovery_provider("facebook")

    class FailingProvider:
        platform = "facebook"

        async def lease(self, db, **kwargs):
            return await original.lease(db, **kwargs)

        async def discover(self, _db, **_kwargs):
            raise RuntimeError("provider unavailable")

    register_discovery_provider(FailingProvider())
    set_current_org_id(ORG_A)
    try:
        async with session_factory() as db:
            result = await discover_and_lease_candidate(
                db,
                platform="facebook",
                org_id=ORG_A,
                account_id=ACCOUNT_A1,
                execution_id="execution-discovery-error",
            )
            state = await get_account_discovery_state(
                db,
                org_id=ORG_A,
                account_id=ACCOUNT_A1,
                platform="facebook",
            )

            assert result.attempt.outcome == "discovery_failed"
            assert result.error == "provider unavailable"
            assert state is not None
            assert state.status == "error"
            assert state.last_error == "provider unavailable"
    finally:
        register_discovery_provider(original)


@pytest.mark.asyncio
async def test_discovery_query_count_is_bounded_for_many_authors(session_factory):
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        await _enable_keyword_auto_ready(db, positive_keywords=["shared"])
        db.add_all(
            [
                _content_item(
                    item_id=f"content-query-{author_index}-{evidence_index}",
                    content_hash=f"{1000 + author_index * 2 + evidence_index:064x}",
                    author=f"Author {author_index}",
                    author_id=f"profile-query-{author_index}",
                    account_id=ACCOUNT_A1,
                    body=f"Shared topic {evidence_index}",
                )
                for author_index in range(20)
                for evidence_index in range(2)
            ]
        )
        await db.flush()

        engine = session_factory.kw["bind"]
        query_count = 0
        statements: list[str] = []

        def count_query(_conn, _cursor, statement, *_args):
            nonlocal query_count
            query_count += 1
            statements.append(" ".join(statement.split())[:180])

        event.listen(engine.sync_engine, "before_cursor_execute", count_query)
        try:
            result = await discover_and_lease_candidate(
                db,
                platform="facebook",
                org_id=ORG_A,
                account_id=ACCOUNT_A1,
                execution_id="execution-query-budget",
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count_query)

        assert result.attempt.outcome == "leased"
        assert result.discovery is not None
        assert result.discovery.observed_count == 20
        assert query_count <= 24, statements


@pytest.mark.asyncio
async def test_observe_is_idempotent_and_exposes_scoring_reasons_and_settings(
    session_factory,
):
    assert normalize_vietnamese_text("CÔNG nghệ, Đổi mới!") == "cong nghe doi moi"
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        defaults = await client.get("/api/facebook-candidate-settings")
        assert defaults.status_code == 200
        assert defaults.json()["embedding_dimensions"] == 384
        saved = await _put_settings(client)
        assert saved["positive_keywords"] == ["công nghệ", "khởi nghiệp"]

        first = await _observe(client)
        assert first.status_code == 200, first.text
        item = first.json()["candidate"]
        assert first.json()["created"] is True
        assert item["status"] == "review_required"
        assert item["evidence_count"] == 1
        assert item["matched_keywords"] == ["công nghệ", "khởi nghiệp"]
        assert item["final_score"] == pytest.approx(0.8)
        assert [reason["code"] for reason in item["reasons"]] == [
            "relationship_score",
            "keyword_score",
            "semantic_score",
        ]

        second = await _observe(client)
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert second.json()["candidate"]["evidence_count"] == 1
        detail = await client.get(f"/api/facebook-candidates/{item['id']}")
        assert detail.status_code == 200
        assert len(detail.json()["evidence"]) == 1
        assert len(detail.json()["embeddings"]) == 1
        assert len(detail.json()["keyword_matches"]) == 2


@pytest.mark.asyncio
async def test_negative_keyword_blocks_candidate(session_factory):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(client)
        response = await _observe(
            client,
            relationship_score=1.0,
            semantic_score=1.0,
            text_value="Dấu hiệu LUA DAO dù hồ sơ công nghệ tốt",
        )
        assert response.status_code == 200
        candidate = response.json()["candidate"]
        assert candidate["status"] == "blocked"
        assert candidate["negative_keywords"] == ["lừa đảo"]
        assert candidate["reasons"][-1] == {
            "code": "negative_keyword_block",
            "matches": ["lừa đảo"],
        }


@pytest.mark.asyncio
async def test_review_gate_guard_and_append_only_history(session_factory):
    app = _app(session_factory)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await _put_settings(
            client,
            relationship_weight=1,
            keyword_weight=0,
            semantic_weight=0,
            positive_keywords=[],
            negative_keywords=[],
            review_threshold=0.8,
        )
        low = await _observe(
            client,
            relationship_score=0.4,
            semantic_score=0,
            text_value="ordinary profile",
        )
        candidate_id = low.json()["candidate"]["id"]
        denied = await client.patch(
            f"/api/facebook-candidates/{candidate_id}/review",
            json={"status": "approved", "note": "too early"},
        )
        assert denied.status_code == 400

        promoted = await _observe(
            client,
            relationship_score=0.95,
            semantic_score=0,
            text_value="ordinary profile",
        )
        assert promoted.json()["candidate"]["status"] == "review_required"
        approved = await client.patch(
            f"/api/facebook-candidates/{candidate_id}/review",
            json={"status": "approved", "note": "manual review passed"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["external_entity_status"] == "approved"
        ready = await client.patch(
            f"/api/facebook-candidates/{candidate_id}/review",
            json={"status": "ready_to_connect"},
        )
        assert ready.status_code == 200, ready.text
        assert [row["to_status"] for row in ready.json()["reviews"]] == [
            "ready_to_connect",
            "approved",
        ]

    set_current_org_id(ORG_A)
    engine = session_factory.kw["bind"]
    guard_query_count = 0

    def count_guard_query(*_args):
        nonlocal guard_query_count
        guard_query_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_guard_query)
    async with session_factory() as db:
        try:
            allowed = await assert_candidate_action_allowed(
                db, ORG_A, ACCOUNT_A1, "entity-a-1"
            )
        finally:
            event.remove(
                engine.sync_engine, "before_cursor_execute", count_guard_query
            )
        assert allowed.status == "ready_to_connect"
        assert guard_query_count == 1
        with pytest.raises(LookupError):
            await assert_candidate_action_allowed(db, ORG_A, ACCOUNT_A2, "entity-a-1")
        assert (
            await db.scalar(
                select(FacebookCandidateReview).where(
                    FacebookCandidateReview.candidate_id == candidate_id
                )
            )
        ) is not None


@pytest.mark.asyncio
async def test_entity_stays_approved_while_another_account_candidate_is_active(
    session_factory,
):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(
            client,
            relationship_weight=1,
            keyword_weight=0,
            semantic_weight=0,
            positive_keywords=[],
            negative_keywords=[],
            review_threshold=0.5,
        )
        first = await _observe(client, account_id=ACCOUNT_A1, relationship_score=0.9)
        first_id = first.json()["candidate"]["id"]
        await client.patch(
            f"/api/facebook-candidates/{first_id}/review",
            json={"status": "approved"},
        )
        await client.patch(
            f"/api/facebook-candidates/{first_id}/review",
            json={"status": "ready_to_connect"},
        )

        second = await _observe(client, account_id=ACCOUNT_A2, relationship_score=0.8)
        second_id = second.json()["candidate"]["id"]
        await client.patch(
            f"/api/facebook-candidates/{second_id}/review",
            json={"status": "approved"},
        )
        rejected_first = await client.patch(
            f"/api/facebook-candidates/{first_id}/review",
            json={"status": "rejected"},
        )
        assert rejected_first.status_code == 200
        assert rejected_first.json()["external_entity_status"] == "approved"

        rejected_second = await client.patch(
            f"/api/facebook-candidates/{second_id}/review",
            json={"status": "rejected"},
        )
        assert rejected_second.status_code == 200
        assert rejected_second.json()["external_entity_status"] == "candidate"


@pytest.mark.asyncio
async def test_org_isolation_and_ranking_order(session_factory):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(
            client,
            relationship_weight=1,
            keyword_weight=0,
            semantic_weight=0,
            positive_keywords=[],
            negative_keywords=[],
        )
        lower = await _observe(
            client,
            entity_id="entity-a-1",
            relationship_score=0.6,
            semantic_score=0,
        )
        higher = await _observe(
            client,
            entity_id="entity-a-2",
            relationship_score=0.9,
            semantic_score=0,
        )
        listed = await client.get("/api/facebook-candidates")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["items"]] == [
            higher.json()["candidate"]["id"],
            lower.json()["candidate"]["id"],
        ]
        foreign_observe = await client.post(
            "/api/facebook-candidates",
            json={
                "account_id": ACCOUNT_B,
                "external_entity_id": "entity-b-1",
                "relationship_score": 1,
            },
        )
        assert foreign_observe.status_code == 404

    async with AsyncClient(
        transport=ASGITransport(
            app=_app(session_factory, org_id=ORG_B, user_id=USER_B)
        ),
        base_url="http://test",
    ) as foreign_client:
        hidden = await foreign_client.get(
            f"/api/facebook-candidates/{higher.json()['candidate']['id']}"
        )
        assert hidden.status_code == 404
        assert (await foreign_client.get("/api/facebook-candidates")).json()[
            "total"
        ] == 0


@pytest.mark.asyncio
async def test_recompute_uses_updated_settings_and_deferred_requires_date(
    session_factory,
):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(client, review_threshold=0.9)
        observed = await _observe(
            client,
            relationship_score=0.5,
            semantic_score=0.5,
            text_value="Công nghệ",
        )
        candidate_id = observed.json()["candidate"]["id"]
        assert observed.json()["candidate"]["status"] == "discovered"

        await _put_settings(client, review_threshold=0.4)
        recomputed = await client.post(
            "/api/facebook-candidates/recompute",
            json={"candidate_ids": [candidate_id]},
        )
        assert recomputed.status_code == 200, recomputed.text
        assert recomputed.json()["items"][0]["status"] == "review_required"
        missing_date = await client.patch(
            f"/api/facebook-candidates/{candidate_id}/review",
            json={"status": "deferred"},
        )
        assert missing_date.status_code == 400
        deferred_until = datetime.now(UTC) + timedelta(days=7)
        deferred = await client.patch(
            f"/api/facebook-candidates/{candidate_id}/review",
            json={
                "status": "deferred",
                "next_eligible_at": deferred_until.isoformat(),
            },
        )
        assert deferred.status_code == 200
        assert deferred.json()["status"] == "deferred"


@pytest.mark.asyncio
async def test_recompute_auto_ready_requires_keyword_policy(session_factory) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(
            client,
            relationship_weight=0,
            keyword_weight=1,
            semantic_weight=0,
            positive_keywords=["công nghệ"],
            negative_keywords=[],
            review_threshold=0.5,
            auto_ready_enabled=True,
            auto_ready_threshold=1,
            auto_ready_min_evidence=1,
        )
        observed = await _observe(
            client,
            relationship_score=0,
            semantic_score=0,
            text_value="Tôi quan tâm công nghệ và tự động hóa",
        )
        candidate_id = observed.json()["candidate"]["id"]
        assert observed.json()["candidate"]["status"] == "review_required"

        recomputed = await client.post(
            "/api/facebook-candidates/recompute",
            json={"candidate_ids": [candidate_id]},
        )

        assert recomputed.status_code == 200, recomputed.text
        candidate = recomputed.json()["items"][0]
        assert candidate["status"] == "ready_to_connect"
        assert candidate["matched_keywords"] == ["công nghệ"]
        assert candidate["reasons"][-1]["code"] == "automatic_keyword_readiness"


@pytest.mark.asyncio
async def test_candidate_lease_is_account_scoped_and_requests_discovery_when_empty(
    session_factory,
):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(
            client,
            relationship_weight=1,
            keyword_weight=0,
            semantic_weight=0,
            positive_keywords=[],
            negative_keywords=[],
            review_threshold=0.5,
        )
        for entity_id, score in (("entity-a-1", 0.8), ("entity-a-2", 0.9)):
            observed = await _observe(
                client,
                account_id=ACCOUNT_A1,
                entity_id=entity_id,
                relationship_score=score,
            )
            candidate_id = observed.json()["candidate"]["id"]
            await client.patch(
                f"/api/facebook-candidates/{candidate_id}/review",
                json={"status": "approved"},
            )
            await client.patch(
                f"/api/facebook-candidates/{candidate_id}/review",
                json={"status": "ready_to_connect"},
            )

    set_current_org_id(ORG_A)
    async with session_factory() as db:
        first_attempt = await lease_next_ready_candidate(
            db,
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-1",
        )
        second_attempt = await lease_next_ready_candidate(
            db,
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-2",
        )
        first = first_attempt.lease
        second = second_attempt.lease
        assert first is not None
        assert second is not None
        assert first.candidate.id != second.candidate.id
        assert first.candidate.final_score > second.candidate.final_score

        busy = await lease_next_ready_candidate(
            db,
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-busy",
        )
        assert busy.lease is None
        assert busy.outcome == "candidate_busy"
        assert busy.discovery_requested is False

        released = await release_candidate_leases_for_execution(
            db,
            org_id=ORG_A,
            execution_id="execution-1",
        )
        assert released == 1
        replacement_attempt = await lease_next_ready_candidate(
            db,
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            execution_id="execution-4",
        )
        replacement = replacement_attempt.lease
        assert replacement is not None
        assert replacement.candidate.id == first.candidate.id

        await complete_candidate_lease(
            db,
            org_id=ORG_A,
            account_id=ACCOUNT_A1,
            candidate_id=replacement.candidate.id,
            lease_token=replacement.lease_token,
        )
        await db.commit()
        assert first.candidate.status == "request_pending"

    async with session_factory() as db:
        empty = await lease_next_ready_candidate(
            db,
            org_id=ORG_A,
            account_id=ACCOUNT_A2,
            execution_id="execution-3",
        )
        state = await get_account_discovery_state(
            db, org_id=ORG_A, account_id=ACCOUNT_A2, platform="facebook"
        )
        await db.commit()
        assert empty.lease is None
        assert empty.outcome == "no_ready_candidate"
        assert state.status == "discovery_requested"
        assert state.discovery_requested_at is not None

    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        requested = await client.post(
            f"/api/accounts/{ACCOUNT_A2}/discovery/request?platform=facebook"
        )
        assert requested.status_code == 200
        assert requested.json()["request_created"] is False
        started = await client.post(
            f"/api/accounts/{ACCOUNT_A2}/discovery/start?platform=facebook"
        )
        assert started.status_code == 200
        assert started.json()["status"] == "discovering"
        duplicate_start = await client.post(
            f"/api/accounts/{ACCOUNT_A2}/discovery/start?platform=facebook"
        )
        assert duplicate_start.status_code == 400
        completed = await client.post(
            f"/api/accounts/{ACCOUNT_A2}/discovery/complete?platform=facebook",
            json={"candidate_count": 0},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_recompute_query_count_does_not_grow_per_candidate(session_factory):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(client)
        for account_id, entity_id in (
            (ACCOUNT_A1, "entity-a-1"),
            (ACCOUNT_A1, "entity-a-2"),
            (ACCOUNT_A2, "entity-a-1"),
            (ACCOUNT_A2, "entity-a-2"),
        ):
            response = await _observe(
                client, account_id=account_id, entity_id=entity_id
            )
            assert response.status_code == 200

    engine = session_factory.kw["bind"]
    query_count = 0

    def count_query(*_args):
        nonlocal query_count
        query_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_query)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/facebook-candidates/recompute", json={}
            )
            assert response.status_code == 200, response.text
            assert response.json()["recomputed_count"] == 4
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_query)

    assert query_count <= 10


@pytest.mark.asyncio
async def test_stale_discovery_worker_is_requeued(session_factory):
    set_current_org_id(ORG_A)
    async with session_factory() as db:
        state, created = await request_account_discovery(
            db, org_id=ORG_A, account_id=ACCOUNT_A2, platform="facebook"
        )
        assert created is True
        state = await mark_account_discovery_started(
            db, org_id=ORG_A, account_id=ACCOUNT_A2, platform="facebook"
        )
        state.discovery_started_at = datetime.now(UTC) - timedelta(minutes=16)
        await db.flush()
        requeued, created = await request_account_discovery(
            db, org_id=ORG_A, account_id=ACCOUNT_A2, platform="facebook"
        )
        assert created is True
        assert requeued.status == "discovery_requested"
        assert requeued.discovery_started_at is None


@pytest.mark.asyncio
async def test_recompute_is_bounded_and_cursor_paginated(session_factory):
    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as client:
        await _put_settings(client)
        for account_id, entity_id in (
            (ACCOUNT_A1, "entity-a-1"),
            (ACCOUNT_A1, "entity-a-2"),
            (ACCOUNT_A2, "entity-a-1"),
            (ACCOUNT_A2, "entity-a-2"),
        ):
            assert (
                await _observe(
                    client, account_id=account_id, entity_id=entity_id
                )
            ).status_code == 200

        first = await client.post(
            "/api/facebook-candidates/recompute", json={"limit": 2}
        )
        assert first.status_code == 200
        assert first.json()["recomputed_count"] == 2
        assert first.json()["next_cursor"]
        second = await client.post(
            "/api/facebook-candidates/recompute",
            json={"limit": 2, "after_id": first.json()["next_cursor"]},
        )
        assert second.status_code == 200
        assert second.json()["recomputed_count"] == 2


@pytest.mark.asyncio
async def test_migration_104_core_tables_are_sqlite_compatible_without_vector():
    migration = importlib.import_module("db.migrations.104_facebook_candidates")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for statement in (
            "CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY)",
            (
                "CREATE TABLE external_entities ("
                "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL, "
                "display_name VARCHAR(500) NOT NULL, UNIQUE (org_id, id))"
            ),
        ):
            await conn.execute(text(statement))
        await migration.upgrade(conn)
        await migration.upgrade(conn)
        table_names = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name LIKE 'facebook_candidate%'"
                    )
                )
            ).all()
        }
        columns = {
            row[1]
            for row in (
                await conn.execute(
                    text("PRAGMA table_info(facebook_candidate_embeddings)")
                )
            ).all()
        }
    await engine.dispose()
    assert table_names == {
        "facebook_candidates",
        "facebook_candidate_evidence",
        "facebook_candidate_keywords",
        "facebook_candidate_embeddings",
        "facebook_candidate_settings",
        "facebook_candidate_reviews",
    }
    assert "embedding" in columns
    assert "embedding_vector" not in columns


@pytest.mark.asyncio
async def test_migration_105_and_postgres_lease_query_are_index_shaped():
    migration_104 = importlib.import_module("db.migrations.104_facebook_candidates")
    migration_105 = importlib.import_module(
        "db.migrations.105_account_discovery_candidate_leases"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for statement in (
            "CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY)",
            (
                "CREATE TABLE external_entities ("
                "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL, "
                "display_name VARCHAR(500) NOT NULL, UNIQUE (org_id, id))"
            ),
        ):
            await conn.execute(text(statement))
        await migration_104.upgrade(conn)
        await migration_105.upgrade(conn)
        await migration_105.upgrade(conn)
        lease_columns = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(facebook_candidates)"))
            ).all()
        }
        indexes = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA index_list(facebook_candidates)"))
            ).all()
        }
        await migration_105.downgrade(conn)
        downgraded_columns = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(facebook_candidates)"))
            ).all()
        }
        discovery_table = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'account_discovery_states'"
                )
            )
        ).scalar_one_or_none()
    await engine.dispose()

    query = _ready_candidate_lease_query(
        org_id=ORG_A,
        account_id=ACCOUNT_A1,
        now=datetime.now(UTC),
    )
    compiled = str(query.compile(dialect=postgresql.dialect()))
    assert {"lease_token", "leased_at", "lease_expires_at"} <= lease_columns
    assert "idx_facebook_candidates_ready_lease" in indexes
    assert "lease_token" not in downgraded_columns
    assert discovery_table is None
    assert "FOR UPDATE OF facebook_candidates SKIP LOCKED" in compiled
    assert "facebook_candidates.status = 'ready_to_connect'" in compiled
    assert "facebook_candidates.final_score DESC" in compiled


@pytest.mark.asyncio
async def test_migration_106_adds_auto_ready_settings_and_discovery_indexes():
    migration_104 = importlib.import_module("db.migrations.104_facebook_candidates")
    migration_106 = importlib.import_module(
        "db.migrations.106_candidate_discovery_bootstrap"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for statement in (
            "CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)",
            "CREATE TABLE accounts (id VARCHAR(36) PRIMARY KEY)",
            (
                "CREATE TABLE external_entities ("
                "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL, "
                "display_name VARCHAR(500) NOT NULL, UNIQUE (org_id, id))"
            ),
            (
                "CREATE TABLE content_items ("
                "id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL, "
                "account_id VARCHAR(36), platform VARCHAR(50), "
                "extracted_at TIMESTAMP, deleted_at TIMESTAMP, author VARCHAR(255))"
            ),
        ):
            await conn.execute(text(statement))
        await migration_104.upgrade(conn)
        await migration_106.upgrade(conn)
        await migration_106.upgrade(conn)
        settings_columns = {
            row[1]
            for row in (
                await conn.execute(
                    text("PRAGMA table_info(facebook_candidate_settings)")
                )
            ).all()
        }
        content_indexes = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA index_list(content_items)"))
            ).all()
        }
        await migration_106.downgrade(conn)
        downgraded_columns = {
            row[1]
            for row in (
                await conn.execute(
                    text("PRAGMA table_info(facebook_candidate_settings)")
                )
            ).all()
        }
    await engine.dispose()

    assert {
        "auto_ready_enabled",
        "auto_ready_threshold",
        "auto_ready_min_evidence",
    } <= settings_columns
    assert {"idx_ci_discovery_account", "idx_ci_discovery_org"} <= content_indexes
    assert "auto_ready_enabled" not in downgraded_columns
