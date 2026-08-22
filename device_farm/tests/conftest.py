from __future__ import annotations

import os

import pytest

from core.security import clear_jwt_cache

# Shared tenancy fixtures (engine, session_factory, seed helpers).
pytest_plugins = ["tests.tenancy_test_support"]

os.environ.setdefault(
    "SECRET_KEY",
    "pytest-dev-secret-change-in-ci-32chars!",
)

# Pinned, not defaulted. The ledger reads this at call time, and the suite picks
# up the developer's .env — so turning the ledger on for the farm silently
# rewrote what a dozen step tests asserted, from the step's own outcome to
# `ledger_prepare_failed` against a database no unit test has. Tests that care
# about ledger behaviour set this themselves via monkeypatch.
os.environ["ACCOUNT_ACTION_LEDGER_MODE"] = "disabled"


@pytest.fixture(autouse=True)
def _jwt_cache_reset():
    clear_jwt_cache()
    yield
    clear_jwt_cache()
