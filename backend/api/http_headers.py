"""HTTP response header helpers."""

from __future__ import annotations

from urllib.parse import quote


def _ascii_attachment_filename(filename: str) -> str:
    """Latin-1-safe filename for the legacy ``filename=`` parameter."""
    base = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "-_.") else "_"
        for ch in filename
    ).strip("._")
    return base or "download"


def content_disposition_attachment(filename: str) -> dict[str, str]:
    """Build a ``Content-Disposition: attachment`` header supporting UTF-8 names (RFC 5987)."""
    fallback = _ascii_attachment_filename(filename)
    encoded = quote(filename, safe="")
    value = f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
    return {"Content-Disposition": value}
