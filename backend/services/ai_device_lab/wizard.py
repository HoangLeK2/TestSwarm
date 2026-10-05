"""Server-authoritative read/write model for the AI Device Lab wizard."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import (
    AiLabIntake,
    AppBuild,
    ScenarioApproval,
    ScenarioGenerationOperation,
    ServiceCampaign,
)
from db.models.ai_device_lab_billing import (
    PaymentIntent,
    ServiceEntitlement,
    ServiceOrder,
)
from db.models.scenario_version import ScenarioVersion
from services.ai_device_lab.funnel import record_server_funnel_event
from services.ai_device_lab.intake import (
    CompleteGeneration,
    ScenarioGenerationRejected,
    complete_generation,
    start_generation,
)
from services.operation_policy import OperationPolicy


log = logging.getLogger(__name__)


class WizardInvariantError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WizardNotFound(WizardInvariantError):
    def __init__(self) -> None:
        super().__init__("WIZARD_NOT_FOUND")


class WizardRevisionConflict(WizardInvariantError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("WIZARD_REVISION_CONFLICT")
        self.current_revision = current_revision


@dataclass(frozen=True, slots=True)
class WizardDraftInput:
    package_name: str
    closed_track_link: str
    test_goal: str
    test_environment: dict[str, Any]
    version_name: str
    version_code: str
    source_kind: str
    source_ref: str | None
    checksum_sha256: str | None


@dataclass(frozen=True, slots=True)
class SaveWizardDraft:
    org_id: str
    owner_id: str
    service_campaign_id: str
    expected_revision: int
    draft: WizardDraftInput


@dataclass(frozen=True, slots=True)
class WizardPaymentState:
    provider_configured: bool
    provider: str | None
    amount_minor: int | None
    currency: str | None
    pricing_version: str | None
    policy_version: str
    quota: dict[str, int]
    order: ServiceOrder | None
    intent: PaymentIntent | None
    entitlement: ServiceEntitlement | None
    blocker_code: str | None


@dataclass(frozen=True, slots=True)
class WizardState:
    campaign: ServiceCampaign
    intake: AiLabIntake | None
    build: AppBuild | None
    generation: ScenarioGenerationOperation | None
    scenario_version: ScenarioVersion | None
    approval: ScenarioApproval | None
    payment: WizardPaymentState
    current_step: str


_SENSITIVE_ENVIRONMENT_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "cookie",
    "credential",
    "otp",
    "auth_code",
)


def _generation_timeout_seconds() -> int:
    try:
        configured = int(os.getenv("AI_DEVICE_LAB_GENERATION_TIMEOUT_SECONDS", "35"))
    except ValueError:
        configured = 35
    return max(1, min(60, configured))


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if any(part in normalized for part in _SENSITIVE_ENVIRONMENT_KEY_PARTS):
                return True
            if _contains_sensitive_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def wizard_operation_policy(package_name: str) -> OperationPolicy:
    """Load the versioned allow-list from server configuration."""
    actions = frozenset(
        item.strip()
        for item in os.getenv(
            "AI_DEVICE_LAB_ALLOWED_ACTIONS",
            "navigation.open",
        ).split(",")
        if item.strip()
    )
    targets = {
        item.strip()
        for item in os.getenv("AI_DEVICE_LAB_ALLOWED_TARGETS", "").split(",")
        if item.strip()
    }
    targets.add(package_name)
    return OperationPolicy(
        version=os.getenv("AI_DEVICE_LAB_OPERATION_POLICY_VERSION", "adl-operations-v1"),
        app_package=package_name,
        allowed_actions=actions,
        allowed_targets=frozenset(targets),
    )


async def run_wizard_generation(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    operation_id: str,
) -> ScenarioGenerationOperation:
    """Persist the operation before invoking the provider and fail closed on errors."""
    state = await load_wizard_state(
        db,
        org_id=org_id,
        service_campaign_id=service_campaign_id,
    )
    if state.intake is None:
        raise WizardInvariantError("INTAKE_REQUIRED")
    existing = (
        await db.execute(
            select(ScenarioGenerationOperation).where(
                ScenarioGenerationOperation.org_id == org_id,
                ScenarioGenerationOperation.operation_id == operation_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.intake_id != state.intake.id:
            raise WizardInvariantError("GENERATION_OPERATION_REUSED")
        return existing

    timeout_seconds = _generation_timeout_seconds()
    current = state.generation
    if current is not None and current.status == "running":
        created_at = current.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created_at <= timedelta(
            seconds=timeout_seconds * 2
        ):
            return current
        current.status = "failed"
        current.error_code = "AI_PROVIDER_ORPHANED"
        current.finished_at = datetime.now(timezone.utc)
        await db.flush()
    recent_attempts = int(
        await db.scalar(
            select(func.count())
            .select_from(ScenarioGenerationOperation)
            .where(
                ScenarioGenerationOperation.org_id == org_id,
                ScenarioGenerationOperation.intake_id == state.intake.id,
                ScenarioGenerationOperation.input_version == state.intake.input_version,
                ScenarioGenerationOperation.created_at
                >= datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        or 0
    )
    if recent_attempts >= 3:
        raise WizardInvariantError("AI_GENERATION_RATE_LIMITED")

    operation = await start_generation(
        db,
        intake_id=state.intake.id,
        org_id=org_id,
        operation_id=operation_id,
    )
    await db.commit()
    try:
        from runtime.ai.ai_client import build_scenario_from_instructions

        scenario = await asyncio.wait_for(
            asyncio.to_thread(
                build_scenario_from_instructions,
                state.intake.test_goal,
                None,
                {
                    **dict(state.intake.test_environment or {}),
                    "package_name": state.intake.package_name,
                },
            ),
            timeout=timeout_seconds,
        )
        await complete_generation(
            db,
            CompleteGeneration(
                org_id=org_id,
                operation_id=operation_id,
                scenario_name=f"AI Device Lab · {state.intake.package_name}",
                scenario=scenario,
                policy=wizard_operation_policy(state.intake.package_name),
            ),
        )
        await db.commit()
    except asyncio.TimeoutError:
        operation.status = "failed"
        operation.error_code = "AI_PROVIDER_TIMEOUT"
        operation.finished_at = datetime.now(timezone.utc)
        await db.commit()
    except ScenarioGenerationRejected:
        await db.commit()
    except Exception as exc:
        log.error(
            "AI Device Lab generation provider failed operation_id=%s error_type=%s",
            operation_id,
            type(exc).__name__,
        )
        operation.status = "failed"
        operation.error_code = "AI_PROVIDER_UNAVAILABLE"
        operation.finished_at = datetime.now(timezone.utc)
        await db.commit()
    await db.refresh(operation)
    return operation


def _canonical_draft(draft: WizardDraftInput, build_id: str) -> str:
    payload = {
        "package_name": draft.package_name,
        "closed_track_link": draft.closed_track_link,
        "test_goal": draft.test_goal.strip(),
        "test_environment": draft.test_environment,
        "requested_build_id": build_id,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_draft(campaign: ServiceCampaign, draft: WizardDraftInput) -> None:
    if draft.package_name != campaign.package_name:
        raise WizardInvariantError("PACKAGE_SCOPE_MISMATCH")
    if not draft.test_goal.strip():
        raise WizardInvariantError("TEST_GOAL_REQUIRED")
    parsed = urlparse(draft.closed_track_link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WizardInvariantError("CLOSED_TRACK_LINK_INVALID")
    if not draft.version_name.strip() or not draft.version_code.strip():
        raise WizardInvariantError("BUILD_VERSION_REQUIRED")
    if draft.source_kind not in {"closed_track", "uploaded_artifact"}:
        raise WizardInvariantError("BUILD_SOURCE_INVALID")
    serialized_environment = json.dumps(
        draft.test_environment,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized_environment.encode("utf-8")) > 4096:
        raise WizardInvariantError("TEST_ENVIRONMENT_TOO_LARGE")
    if _contains_sensitive_key(draft.test_environment):
        raise WizardInvariantError("SENSITIVE_TEST_ENVIRONMENT_REJECTED")
    if draft.checksum_sha256 is not None:
        checksum = draft.checksum_sha256.lower()
        if len(checksum) != 64 or any(
            char not in "0123456789abcdef" for char in checksum
        ):
            raise WizardInvariantError("BUILD_CHECKSUM_INVALID")


async def _resolve_build(
    db: AsyncSession,
    *,
    org_id: str,
    draft: WizardDraftInput,
) -> AppBuild:
    conditions = [
        AppBuild.org_id == org_id,
        AppBuild.package_name == draft.package_name,
        AppBuild.version_name == draft.version_name.strip(),
        AppBuild.version_code == draft.version_code.strip(),
        AppBuild.source_kind == draft.source_kind,
    ]
    conditions.append(
        AppBuild.source_ref.is_(None)
        if draft.source_ref is None
        else AppBuild.source_ref == draft.source_ref
    )
    conditions.append(
        AppBuild.checksum_sha256.is_(None)
        if draft.checksum_sha256 is None
        else AppBuild.checksum_sha256 == draft.checksum_sha256.lower()
    )
    existing = (
        await db.execute(
            select(AppBuild)
            .where(*conditions)
            .order_by(AppBuild.created_at.asc(), AppBuild.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    build = AppBuild(
        org_id=org_id,
        package_name=draft.package_name,
        version_name=draft.version_name.strip(),
        version_code=draft.version_code.strip(),
        source_kind=draft.source_kind,
        source_ref=draft.source_ref,
        checksum_sha256=(draft.checksum_sha256.lower() if draft.checksum_sha256 else None),
    )
    db.add(build)
    await db.flush()
    return build


async def save_wizard_draft(db: AsyncSession, command: SaveWizardDraft) -> AiLabIntake:
    """Persist one campaign draft with optimistic concurrency and semantic replay."""
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise WizardNotFound()
    _validate_draft(campaign, command.draft)

    intake = (
        await db.execute(
            select(AiLabIntake)
            .where(
                AiLabIntake.org_id == command.org_id,
                AiLabIntake.runtime_campaign_id == campaign.runtime_campaign_id,
            )
            .order_by(AiLabIntake.updated_at.desc(), AiLabIntake.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    build = await _resolve_build(db, org_id=command.org_id, draft=command.draft)
    input_hash = _canonical_draft(command.draft, build.id)

    if intake is None:
        if command.expected_revision != 0:
            raise WizardRevisionConflict(0)
        intake = AiLabIntake(
            org_id=command.org_id,
            owner_id=command.owner_id,
            runtime_campaign_id=campaign.runtime_campaign_id,
            requested_build_id=build.id,
            package_name=command.draft.package_name,
            closed_track_link=command.draft.closed_track_link,
            test_goal=command.draft.test_goal.strip(),
            test_environment=command.draft.test_environment,
            status="draft",
            input_version=1,
            input_hash=input_hash,
            lock_version=0,
        )
        db.add(intake)
        await db.flush()
        await record_server_funnel_event(
            db,
            org_id=command.org_id,
            service_campaign_id=campaign.id,
            event_name="app_submitted",
            source_ref=intake.id,
            occurred_at=intake.created_at,
        )
        return intake

    if intake.input_hash == input_hash:
        await record_server_funnel_event(
            db,
            org_id=command.org_id,
            service_campaign_id=campaign.id,
            event_name="app_submitted",
            source_ref=intake.id,
            occurred_at=intake.created_at,
        )
        return intake
    if intake.lock_version != command.expected_revision:
        raise WizardRevisionConflict(intake.lock_version)

    existing_order = await db.scalar(
        select(ServiceOrder.id).where(
            ServiceOrder.org_id == command.org_id,
            ServiceOrder.service_campaign_id == campaign.id,
        )
    )
    if existing_order is not None:
        raise WizardInvariantError("ORDER_EXISTS_REQUIRES_EXPLICIT_CHANGE_POLICY")

    intake.requested_build_id = build.id
    intake.closed_track_link = command.draft.closed_track_link
    intake.test_goal = command.draft.test_goal.strip()
    intake.test_environment = command.draft.test_environment
    intake.input_version += 1
    intake.input_hash = input_hash
    intake.lock_version += 1
    intake.status = "draft"
    await db.flush()
    await record_server_funnel_event(
        db,
        org_id=command.org_id,
        service_campaign_id=campaign.id,
        event_name="app_submitted",
        source_ref=intake.id,
        occurred_at=intake.created_at,
    )
    return intake


def _commercial_state(
    *,
    order: ServiceOrder | None,
    intent: PaymentIntent | None,
    entitlement: ServiceEntitlement | None,
    approval: ScenarioApproval | None,
) -> WizardPaymentState:
    from services.ai_device_lab.billing_checkout import checkout_provider_available

    configured_provider = os.getenv("AI_DEVICE_LAB_PAYMENT_PROVIDER", "").strip() or None
    raw_amount = os.getenv("AI_DEVICE_LAB_PRICE_MINOR", "").strip()
    currency = os.getenv("AI_DEVICE_LAB_CURRENCY", "").strip().upper() or None
    pricing_version = os.getenv("AI_DEVICE_LAB_PRICING_VERSION", "").strip() or None
    try:
        amount = int(raw_amount) if raw_amount else None
    except ValueError:
        amount = None
    configured = bool(
        checkout_provider_available(configured_provider)
        and amount is not None
        and amount > 0
        and currency
        and len(currency) == 3
        and pricing_version
    )
    if approval is None:
        blocker = "APPROVED_SCENARIO_REQUIRED"
    elif entitlement is not None and entitlement.state == "active":
        blocker = None
    elif intent is not None and intent.status == "uncertain":
        blocker = "PAYMENT_RECONCILIATION_PENDING"
    elif intent is not None and intent.status == "failed":
        blocker = "PAYMENT_FAILED"
    elif order is not None:
        blocker = (
            "PAYMENT_PENDING"
            if order.status == "pending"
            else f"PAYMENT_{order.status.upper()}"
        )
    elif not configured:
        blocker = "PAYMENT_PROVIDER_UNAVAILABLE"
    else:
        blocker = None
    return WizardPaymentState(
        provider_configured=configured,
        provider=configured_provider if configured else None,
        amount_minor=amount if configured else None,
        currency=currency if configured else None,
        pricing_version=pricing_version if configured else None,
        policy_version=os.getenv("AI_DEVICE_LAB_BILLING_POLICY_VERSION", "adl-billing-unconfigured-v1"),
        quota={"device_minutes": 12 * 14 * 15, "slots": 12 * 14},
        order=order,
        intent=intent,
        entitlement=entitlement,
        blocker_code=blocker,
    )


async def load_wizard_state(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
) -> WizardState:
    campaign = (
        await db.execute(
            select(ServiceCampaign).where(
                ServiceCampaign.id == service_campaign_id,
                ServiceCampaign.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise WizardNotFound()
    intake = (
        await db.execute(
            select(AiLabIntake).where(
                AiLabIntake.org_id == org_id,
                AiLabIntake.runtime_campaign_id == campaign.runtime_campaign_id,
            )
            .order_by(AiLabIntake.updated_at.desc(), AiLabIntake.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    build = await db.get(AppBuild, intake.requested_build_id) if intake else None
    generation = None
    scenario_version = None
    approval = None
    if intake is not None:
        generation = (
            await db.execute(
                select(ScenarioGenerationOperation)
                .where(
                    ScenarioGenerationOperation.org_id == org_id,
                    ScenarioGenerationOperation.intake_id == intake.id,
                    ScenarioGenerationOperation.input_version == intake.input_version,
                    ScenarioGenerationOperation.input_hash == intake.input_hash,
                )
                .order_by(ScenarioGenerationOperation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if generation and generation.scenario_version_id:
            scenario_version = await db.get(ScenarioVersion, generation.scenario_version_id)
            approval = (
                await db.execute(
                    select(ScenarioApproval)
                    .where(
                        ScenarioApproval.org_id == org_id,
                        ScenarioApproval.intake_id == intake.id,
                        ScenarioApproval.generation_operation_id == generation.id,
                        ScenarioApproval.scenario_version_id == generation.scenario_version_id,
                    )
                    .order_by(ScenarioApproval.approved_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    order = (
        await db.execute(
            select(ServiceOrder)
            .where(
                ServiceOrder.org_id == org_id,
                ServiceOrder.service_campaign_id == campaign.id,
            )
            .order_by(ServiceOrder.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    entitlement = None
    intent = None
    if order is not None:
        intent = (
            await db.execute(
                select(PaymentIntent).where(
                    PaymentIntent.org_id == org_id,
                    PaymentIntent.order_id == order.id,
                )
            )
        ).scalar_one_or_none()
        entitlement = (
            await db.execute(
                select(ServiceEntitlement).where(
                    ServiceEntitlement.org_id == org_id,
                    ServiceEntitlement.order_id == order.id,
                )
            )
        ).scalar_one_or_none()
    payment = _commercial_state(
        order=order,
        intent=intent,
        entitlement=entitlement,
        approval=approval,
    )
    if intake is None:
        current_step = "app"
    elif approval is None:
        current_step = "scenario"
    elif entitlement is None or entitlement.state != "active":
        current_step = "payment"
    else:
        current_step = "readiness"
    return WizardState(
        campaign=campaign,
        intake=intake,
        build=build,
        generation=generation,
        scenario_version=scenario_version,
        approval=approval,
        payment=payment,
        current_step=current_step,
    )
