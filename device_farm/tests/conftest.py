from __future__ import annotations

import os

import pytest

from core.security import clear_jwt_cache

os.environ.setdefault(
    "SECRET_KEY",
    "pytest-dev-secret-change-in-ci-32chars!",
)


@pytest.fixture(autouse=True)
def _jwt_cache_reset():
    clear_jwt_cache()
    yield
    clear_jwt_cache()
