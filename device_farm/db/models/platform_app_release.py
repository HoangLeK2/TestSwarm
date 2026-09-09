from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class PlatformAppRelease(Base):
    """Global APK release artifact for a platform app such as Facebook."""

    __tablename__ = "platform_app_releases"
    __table_args__ = (
        UniqueConstraint("platform", "package_name", "sha256", name="uq_platform_app_releases_sha"),
        Index("idx_platform_app_releases_platform_status", "platform", "package_name", "status"),
        Index(
            "uq_platform_app_releases_active",
            "platform",
            "package_name",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    package_name: Mapped[str] = mapped_column(String(128), nullable=False)
    version_name: Mapped[str] = mapped_column(String(128), nullable=False)
    version_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_type_mime: Mapped[str] = mapped_column(
        String(128), nullable=False, default="application/vnd.android.package-archive"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    uploaded_by: Mapped[Optional["User"]] = relationship("User")
