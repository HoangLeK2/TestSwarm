"""Deterministic AI Device Lab PDF rendering and fail-closed private publication."""

from __future__ import annotations

import hashlib
import json
import os
import textwrap
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab_report import ReportSnapshot
from services.ai_device_lab.reporting import attach_pdf_output


class ReportPdfInvariantError(ValueError):
    pass


class PrivateReportStorage(Protocol):
    def put_private(self, *, object_key: str, data: bytes, content_type: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ConfiguredMinioPrivateReportStorage:
    """MinIO adapter enabled only after the bucket policy is explicitly confirmed private."""

    confirmation_env: str = "AI_DEVICE_LAB_PRIVATE_REPORT_STORAGE_CONFIRMED"

    def put_private(self, *, object_key: str, data: bytes, content_type: str) -> bool:
        if os.getenv(self.confirmation_env, "").strip().lower() not in {"1", "true", "yes"}:
            return False
        from services import minio_store

        if not minio_store.enabled():
            return False
        return minio_store.upload(data, object_key, content_type=content_type) is not None


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _report_lines(report: ReportSnapshot) -> list[str]:
    lines = [
        "AI Device Lab Report",
        f"Report: {report.id}",
        f"Campaign: {report.service_campaign_id}",
        f"Version: {report.version}",
        f"Schema: {report.schema_version}",
        f"Cutoff: {report.cutoff_at.isoformat()}",
        f"Manifest SHA-256: {report.manifest_sha256}",
        "",
    ]
    for section in ("service", "app_quality", "play_participation", "evidence", "quota"):
        lines.append(section.replace("_", " ").title())
        payload = report.manifest.get(section, {})
        if isinstance(payload, dict):
            for key in sorted(payload):
                value = json.dumps(payload[key], ensure_ascii=True, sort_keys=True)
                lines.extend(textwrap.wrap(f"  {key}: {value}", width=92) or [""])
        lines.append("")
    lines.append("This PDF is bound to the immutable manifest hash above.")
    return [line.encode("ascii", "replace").decode("ascii") for line in lines]


def render_report_pdf(report: ReportSnapshot) -> bytes:
    """Render a deterministic, bounded summary PDF without embedding source identity lists."""
    lines = _report_lines(report)
    pages = [lines[index : index + 48] for index in range(0, len(lines), 48)] or [[]]
    font_id = 3
    page_ids = [4 + index * 2 for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{item} 0 R' for item in page_ids)}] "
            f"/Count {len(page_ids)} >>"
        ).encode("ascii"),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index, page_lines in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        commands = ["BT", "/F1 10 Tf", "50 792 Td", "14 TL"]
        for line in page_lines:
            commands.append(f"({_pdf_escape(line)}) Tj")
            commands.append("T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, max(objects) + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


async def publish_report_pdf(
    db: AsyncSession,
    *,
    org_id: str,
    report_id: str,
    storage: PrivateReportStorage | None = None,
) -> ReportSnapshot:
    report = (
        await db.execute(
            select(ReportSnapshot)
            .where(ReportSnapshot.id == report_id, ReportSnapshot.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise ReportPdfInvariantError("report not found")
    if report.status == "published":
        if not report.pdf_object_key or not report.pdf_sha256:
            raise ReportPdfInvariantError("published report metadata is incomplete")
        return report
    if report.status != "ready":
        raise ReportPdfInvariantError("report is not ready for PDF publication")

    pdf = render_report_pdf(report)
    pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    object_key = (
        f"ai-device-lab/{org_id}/{report.service_campaign_id}/reports/"
        f"{report.id}/{pdf_sha256}.pdf"
    )
    adapter = storage or ConfiguredMinioPrivateReportStorage()
    if not adapter.put_private(
        object_key=object_key,
        data=pdf,
        content_type="application/pdf",
    ):
        raise ReportPdfInvariantError("private report storage is unavailable or unconfirmed")
    return await attach_pdf_output(
        db,
        org_id=org_id,
        report_id=report.id,
        manifest_sha256=report.manifest_sha256,
        object_key=object_key,
        pdf_sha256=pdf_sha256,
    )
