"""Epic 06 DF-T-06-010: external_id dedup + secret scrub."""
from __future__ import annotations

from services.content.secret_scrub import scrub_secrets


class TestSecretScrub:
    def test_scrubs_openai_key(self):
        raw = {"note": "key=sk-abcdefghijklmnopqrstuvwxyz1234567890"}
        out = scrub_secrets(raw)
        assert "sk-" not in out["note"]
        assert "[REDACTED_OPENAI_KEY]" in out["note"]

    def test_scrubs_gemini_key(self):
        raw = {"token": "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567"}
        out = scrub_secrets(raw)
        assert "AIzaSy" not in out["token"]
