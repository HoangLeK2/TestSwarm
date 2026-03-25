from __future__ import annotations

import pytest

from core.security import clear_jwt_cache, jwt_algorithm, jwt_secret_key


def test_jwt_reads_env(monkeypatch: pytest.MonkeyPatch):
    clear_jwt_cache()
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    assert jwt_secret_key() == "x" * 40
    assert jwt_algorithm() == "HS256"


def test_jwt_secret_missing_raises(monkeypatch: pytest.MonkeyPatch):
    clear_jwt_cache()
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        jwt_secret_key()
