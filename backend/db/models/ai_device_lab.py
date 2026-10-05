"""Production service-contract entities for AI Device Lab."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from tenancy.models import TenantScopedModel

from .utils import _now, _uuid


class ServiceCampaign(TenantScopedModel, Base):
    """Paid-service lifecycle kept separate from a runtime campaign."""

    __tablename__ = "service_campaigns"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_service_campaigns_org_id"),
        UniqueConstraint(
            "org_id",
            "runtime_campaign_id",
            name="uq_service_campaigns_runtime_campaign",
        ),
        UniqueConstraint(
            "org_id",
            "creation_intent_key",
            name="uq_service_campaigns_creation_intent",
        ),
        Index("idx_service_campaigns_org_status", "org_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    runtime_campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_version: Mapped[str] = mapped_column(String(64), nullable=False)
    creation_intent_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    lanes: Mapped[list["ServiceLane"]] = relationship(
        "ServiceLane",
        back_populates="service_campaign",
        cascade="all, delete-orphan",
        order_by="ServiceLane.ordinal",
    )


class ServiceLane(TenantScopedModel, Base):
    """Stable tester identity; physical assignments live in separate history."""

    __tablename__ = "service_lanes"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "service_campaign_id",
            "ordinal",
            name="uq_service_lanes_campaign_ordinal",
        ),
        UniqueConstraint(
            "org_id",
            "id",
            "service_campaign_id",
            name="uq_service_lanes_org_id_campaign",
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_service_lanes_campaign_org",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    tester_label: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    service_campaign: Mapped[ServiceCampaign] = relationship(
        "ServiceCampaign", back_populates="lanes"
    )


class AppBuild(TenantScopedModel, Base):
    """Immutable declared build identity used by every run attempt."""

    __tablename__ = "app_builds"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_app_builds_org_id"),
        UniqueConstraint(
            "org_id",
            "package_name",
            "checksum_sha256",
            name="uq_app_builds_org_package_checksum",
        ),
        Index("idx_app_builds_org_package", "org_id", "package_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version_name: Mapped[str] = mapped_column(String(128), nullable=False)
    version_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class RunSlot(TenantScopedModel, Base):
    """One planned service opportunity for one logical lane and service day."""

    __tablename__ = "run_slots"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "service_campaign_id",
            "lane_id",
            "service_day",
            name="uq_run_slots_campaign_lane_day",
        ),
        UniqueConstraint(
            "org_id",
            "id",
            "service_campaign_id",
            "lane_id",
            name="uq_run_slots_org_identity",
        ),
        ForeignKeyConstraint(
            ["org_id", "service_campaign_id"],
            ["service_campaigns.org_id", "service_campaigns.id"],
            ondelete="RESTRICT",
            name="fk_run_slots_campaign_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "lane_id", "service_campaign_id"],
            [
                "service_lanes.org_id",
                "service_lanes.id",
                "service_lanes.service_campaign_id",
            ],
            ondelete="RESTRICT",
            name="fk_run_slots_lane_org_campaign",
        ),
        Index(
            "idx_run_slots_campaign_status", "service_campaign_id", "execution_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lane_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_day: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    execution_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planned"
    )
    app_verdict: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    play_participation_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class RunAttempt(TenantScopedModel, Base):
    """Immutable run-level attempt; step retries remain inside one execution."""

    __tablename__ = "run_attempts"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_run_attempts_org_id"),
        UniqueConstraint(
            "org_id", "slot_id", "attempt_no", name="uq_run_attempts_slot_number"
        ),
        UniqueConstraint(
            "org_id", "idempotency_key", name="uq_run_attempts_idempotency"
        ),
        ForeignKeyConstraint(
            ["org_id", "slot_id", "service_campaign_id", "lane_id"],
            [
                "run_slots.org_id",
                "run_slots.id",
                "run_slots.service_campaign_id",
                "run_slots.lane_id",
            ],
            ondelete="RESTRICT",
            name="fk_run_attempts_slot_identity",
        ),
        ForeignKeyConstraint(
            ["org_id", "app_build_id"],
            ["app_builds.org_id", "app_builds.id"],
            ondelete="RESTRICT",
            name="fk_run_attempts_build_org",
        ),
        Index("idx_run_attempts_slot_created", "slot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    service_campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lane_id: Mapped[str] = mapped_column(String(36), nullable=False)
    slot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scenario_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    app_build_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    observed_build: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class AiLabIntake(TenantScopedModel, Base):
    """Persisted customer input whose hash/version anchors AI generation."""

    __tablename__ = "ai_lab_intakes"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_ai_lab_intakes_org_id"),
        ForeignKeyConstraint(
            ["org_id", "requested_build_id"],
            ["app_builds.org_id", "app_builds.id"],
            ondelete="RESTRICT",
            name="fk_ai_lab_intakes_build_org",
        ),
        Index("idx_ai_lab_intakes_org_owner", "org_id", "owner_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    runtime_campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    requested_build_id: Mapped[str] = mapped_column(String(36), nullable=False)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    closed_track_link: Mapped[str] = mapped_column(Text, nullable=False)
    test_goal: Mapped[str] = mapped_column(Text, nullable=False)
    test_environment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    input_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class ScenarioGenerationOperation(TenantScopedModel, Base):
    """Idempotent generation attempt pinned to an intake input version/hash."""

    __tablename__ = "scenario_generation_operations"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "id", name="uq_scenario_generation_operations_org_id"
        ),
        UniqueConstraint(
            "org_id", "operation_id", name="uq_scenario_generation_operation"
        ),
        ForeignKeyConstraint(
            ["org_id", "intake_id"],
            ["ai_lab_intakes.org_id", "ai_lab_intakes.id"],
            ondelete="RESTRICT",
            name="fk_scenario_generation_intake_org",
        ),
        Index("idx_scenario_generation_intake", "intake_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    intake_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    provider_request_ref: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=True
    )
    scenario_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("scenario_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ScenarioApproval(TenantScopedModel, Base):
    """Immutable approval for one exact generated scenario snapshot."""

    __tablename__ = "scenario_approvals"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="uq_scenario_approvals_org_id"),
        UniqueConstraint(
            "org_id",
            "scenario_version_id",
            "content_hash",
            "policy_version",
            name="uq_scenario_approvals_exact_snapshot",
        ),
        ForeignKeyConstraint(
            ["org_id", "intake_id"],
            ["ai_lab_intakes.org_id", "ai_lab_intakes.id"],
            ondelete="RESTRICT",
            name="fk_scenario_approvals_intake_org",
        ),
        ForeignKeyConstraint(
            ["org_id", "generation_operation_id"],
            [
                "scenario_generation_operations.org_id",
                "scenario_generation_operations.id",
            ],
            ondelete="RESTRICT",
            name="fk_scenario_approvals_generation_org",
        ),
        Index("idx_scenario_approvals_intake", "intake_id", "approved_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    intake_id: Mapped[str] = mapped_column(String(36), nullable=False)
    generation_operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scenario_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scenario_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    assertions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    allowed_operations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
