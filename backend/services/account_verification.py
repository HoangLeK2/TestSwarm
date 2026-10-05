from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.account import Account, DeviceAccount
from db.models.device import Device

log = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"(?<![\w.])@?([\w.]{3,255})(?![\w.])", re.UNICODE)
_DEVICE_LOCKS: dict[str, asyncio.Lock] = {}
_DEVICE_LOCKS_GUARD = asyncio.Lock()


class VerificationMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class VerificationTarget:
    assignment_id: str
    device_id: str
    account_id: str
    device_serial: str
    platform: str
    username: str
    provider_id: str | None


@dataclass(frozen=True, slots=True)
class AccountVerificationResult:
    assignment_id: str | None
    status: VerificationStatus
    reason: str
    attempted_at: datetime
    attempt_id: str
    identifier_type: str | None = None
    observed_identifier: str | None = None
    hierarchy_sha256: str | None = None
    duration_ms: float | None = None

    @property
    def allows_enforce(self) -> bool:
        return self.status == VerificationStatus.VERIFIED

    def evidence(self, *, detailed: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["attempted_at"] = self.attempted_at.isoformat()
        if not detailed:
            data.pop("hierarchy_sha256", None)
            data.pop("observed_identifier", None)
        return {key: value for key, value in data.items() if value is not None}


def verification_mode() -> VerificationMode:
    raw = os.environ.get("ACCOUNT_VERIFICATION_MODE", VerificationMode.SHADOW.value).strip().lower()
    try:
        return VerificationMode(raw)
    except ValueError:
        log.warning("invalid ACCOUNT_VERIFICATION_MODE=%r; using shadow", raw)
        return VerificationMode.SHADOW


def _config() -> tuple[str, str, float, int]:
    package = os.environ.get("PLATFORM_VERIFICATION_PACKAGE", "").strip()
    resource_id = os.environ.get("PLATFORM_VERIFICATION_RESOURCE_ID", "").strip()
    try:
        timeout = max(1.0, min(30.0, float(os.environ.get("ACCOUNT_VERIFICATION_TIMEOUT_SECONDS", "6"))))
    except ValueError:
        timeout = 6.0
    try:
        concurrency = max(1, min(32, int(os.environ.get("ACCOUNT_VERIFICATION_CONCURRENCY", "8"))))
    except ValueError:
        concurrency = 8
    return package, resource_id, timeout, concurrency


def _normalized(value: str | None) -> str:
    raw = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return raw.removeprefix("@").rstrip("/")


def resolve_platform_identity(
    hierarchy_xml: str,
    *,
    expected_username: str,
    expected_provider_id: str | None,
    trusted_resource_id: str | None,
    assignment_id: str | None = None,
) -> AccountVerificationResult:
    attempted_at = datetime.now(timezone.utc)
    attempt_id = str(uuid.uuid4())
    digest = hashlib.sha256(hierarchy_xml.encode("utf-8")).hexdigest()

    def result(status: VerificationStatus, reason: str, **kwargs: Any) -> AccountVerificationResult:
        return AccountVerificationResult(assignment_id, status, reason, attempted_at, attempt_id, hierarchy_sha256=digest, **kwargs)

    try:
        root = ET.fromstring(hierarchy_xml)
    except ET.ParseError:
        return result(VerificationStatus.INCONCLUSIVE, "invalid_hierarchy")
    trusted_id = (trusted_resource_id or "").strip()
    if not trusted_id:
        return result(VerificationStatus.INCONCLUSIVE, "trusted_selector_missing")
    trusted_nodes = [node for node in root.iter() if node.attrib.get("resource-id") == trusted_id]
    if len(trusted_nodes) != 1:
        reason = "identifier_not_found" if not trusted_nodes else "ambiguous_identifier"
        return result(VerificationStatus.INCONCLUSIVE, reason)
    labels = " ".join(
        filter(None, (trusted_nodes[0].attrib.get("text"), trusted_nodes[0].attrib.get("content-desc")))
    )
    tokens = {_normalized(match) for match in _TOKEN_RE.findall(labels)}
    expected = [("provider_id", _normalized(expected_provider_id)), ("username", _normalized(expected_username))]
    for identifier_type, identifier in expected:
        if identifier and identifier in tokens:
            return result(
                VerificationStatus.VERIFIED,
                "identifier_matched",
                identifier_type=identifier_type,
                observed_identifier=identifier,
            )
    observed = next(iter(tokens), None) if len(tokens) == 1 else None
    if observed:
        return result(VerificationStatus.MISMATCH, "identifier_mismatch", observed_identifier=observed)
    return result(VerificationStatus.INCONCLUSIVE, "identifier_not_found")


async def load_verification_targets(
    db: AsyncSession,
    *,
    assignments: Iterable[tuple[str, str]],
    org_id: str,
) -> dict[tuple[str, str], VerificationTarget]:
    pairs = list(dict.fromkeys(assignments))
    if not pairs:
        return {}
    clauses = [
        (DeviceAccount.device_id == device_id) & (DeviceAccount.account_id == account_id)
        for device_id, account_id in pairs
    ]
    rows = await db.execute(
        select(DeviceAccount, Account, Device)
        .join(Account, Account.id == DeviceAccount.account_id)
        .join(Device, Device.id == DeviceAccount.device_id)
        .where(or_(*clauses), Account.org_id == org_id, Device.org_id == org_id)
    )
    targets: dict[tuple[str, str], VerificationTarget] = {}
    for link, account, device in rows.all():
        metadata = account.account_metadata or {}
        provider_id = metadata.get("provider_id")
        targets[(link.device_id, link.account_id)] = VerificationTarget(
            assignment_id=link.id,
            device_id=link.device_id,
            account_id=link.account_id,
            device_serial=device.serial,
            platform=account.platform,
            username=account.username,
            provider_id=str(provider_id) if provider_id else None,
        )
    return targets


async def _device_lock(serial: str) -> asyncio.Lock:
    async with _DEVICE_LOCKS_GUARD:
        return _DEVICE_LOCKS.setdefault(serial, asyncio.Lock())


async def observe_account_identity(target: VerificationTarget, manager: Any) -> AccountVerificationResult:
    attempted_at = datetime.now(timezone.utc)
    attempt_id = str(uuid.uuid4())
    started = time.perf_counter()

    def simple(status: VerificationStatus, reason: str) -> AccountVerificationResult:
        return AccountVerificationResult(
            target.assignment_id,
            status,
            reason,
            attempted_at,
            attempt_id,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    client = manager.get_device(target.device_serial) if manager is not None else None
    if client is None:
        return simple(VerificationStatus.INCONCLUSIVE, "device_offline")
    package, resource_id, timeout, _ = _config()
    if not package:
        return simple(VerificationStatus.UNSUPPORTED, "verification_package_missing")
    lock = await _device_lock(target.device_serial)

    def inspect() -> AccountVerificationResult:
        client.launch_app(package)
        hierarchy = client.hierarchy_xml(force_refresh=True) or ""
        if not hierarchy:
            return simple(VerificationStatus.INCONCLUSIVE, "hierarchy_unavailable")
        resolved = resolve_platform_identity(
            hierarchy,
            expected_username=target.username,
            expected_provider_id=target.provider_id,
            trusted_resource_id=resource_id,
            assignment_id=target.assignment_id,
        )
        return AccountVerificationResult(
            **{
                **asdict(resolved),
                "status": resolved.status,
                "duration_ms": (time.perf_counter() - started) * 1000,
            }
        )

    await lock.acquire()
    inspection = asyncio.create_task(asyncio.to_thread(inspect))

    def release_device_lock(_task: asyncio.Task[AccountVerificationResult]) -> None:
        if lock.locked():
            lock.release()

    inspection.add_done_callback(release_device_lock)
    try:
        return await asyncio.wait_for(asyncio.shield(inspection), timeout=timeout)
    except TimeoutError:
        return simple(VerificationStatus.INCONCLUSIVE, "inspection_timeout")
    except Exception as exc:
        log.warning("account verification inspection failed device=%s: %s", target.device_id, exc)
        return simple(VerificationStatus.INCONCLUSIVE, "inspection_failed")


async def verify_targets(
    targets: Iterable[VerificationTarget],
    manager: Any,
) -> dict[str, AccountVerificationResult]:
    _, _, _, concurrency = _config()
    semaphore = asyncio.Semaphore(concurrency)

    async def run(target: VerificationTarget) -> tuple[str, AccountVerificationResult]:
        async with semaphore:
            return target.assignment_id, await observe_account_identity(target, manager)

    return dict(await asyncio.gather(*(run(target) for target in targets)))


async def persist_verification_results(
    db: AsyncSession,
    results: Iterable[AccountVerificationResult],
) -> None:
    rows = [result for result in results if result.assignment_id]
    if not rows:
        return
    loaded = await db.execute(
        select(DeviceAccount).where(DeviceAccount.id.in_([row.assignment_id for row in rows if row.assignment_id]))
    )
    links = {link.id: link for link in loaded.scalars().all()}
    for result in rows:
        link = links.get(result.assignment_id or "")
        if link is None:
            continue
        link.verification_status = result.status.value
        link.verification_attempted_at = result.attempted_at
        if result.status == VerificationStatus.VERIFIED:
            link.verified_at = result.attempted_at
        link.verification_evidence = result.evidence()
    await db.flush()
