"""Epic 06 content extraction error codes (DF-T-06-001, DF-T-06-007)."""
from __future__ import annotations


class ContentError(Exception):
    def __init__(self, message: str, *, code: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ContentTypeError(ContentError):
    pass


class NormalizationError(ContentError):
    pass


class RawDataSizeError(ContentError):
    pass


GENERIC_CONTENT_TYPES = frozenset({"post", "comment", "video", "thread", "media"})
