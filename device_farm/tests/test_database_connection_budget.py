from __future__ import annotations

import pytest


def test_connection_budget_accepts_safe_120_phone_configuration():
    from db.connection_budget import validate_connection_budget

    budget = validate_connection_budget(
        {
            "DB_CONNECTION_LIMIT": "100",
            "DB_CONNECTION_RESERVE": "15",
            "TEMPORAL_DB_MAX_CONNECTIONS": "40",
            "TEMPORAL_WORKER_COUNT": "7",
            "DB_POOL_SIZE": "12",
            "DB_MAX_OVERFLOW": "3",
            "DB_ACTIVITY_POOL_SIZE": "4",
            "DB_ACTIVITY_MAX_OVERFLOW": "0",
        }
    )

    assert budget.web_max == 15
    assert budget.activity_max == 28
    assert budget.configured_demand == 83
    assert budget.total_with_reserve == 98
    assert budget.headroom == 2


def test_connection_budget_defaults_match_recommended_pool_sizes():
    from db.connection_budget import validate_connection_budget

    budget = validate_connection_budget(
        {
            "DB_CONNECTION_LIMIT": "100",
            "DB_CONNECTION_RESERVE": "15",
            "TEMPORAL_DB_MAX_CONNECTIONS": "40",
        }
    )

    assert budget.web_max == 15
    assert budget.activity_max == 28
    assert budget.total_with_reserve == 98


def test_connection_budget_rejects_configuration_that_can_exhaust_postgres():
    from db.connection_budget import ConnectionBudgetError, validate_connection_budget

    with pytest.raises(ConnectionBudgetError, match=r"174 configured \+ 15 reserved > 100"):
        validate_connection_budget(
            {
                "DB_CONNECTION_LIMIT": "100",
                "DB_CONNECTION_RESERVE": "15",
                "TEMPORAL_DB_MAX_CONNECTIONS": "0",
                "TEMPORAL_WORKER_COUNT": "6",
                "DB_POOL_SIZE": "15",
                "DB_MAX_OVERFLOW": "15",
                "DB_ACTIVITY_POOL_SIZE": "12",
                "DB_ACTIVITY_MAX_OVERFLOW": "12",
            }
        )


def test_connection_budget_is_advisory_when_limit_is_not_configured():
    from db.connection_budget import validate_connection_budget

    budget = validate_connection_budget(
        {
            "TEMPORAL_WORKER_COUNT": "6",
            "DB_POOL_SIZE": "15",
            "DB_MAX_OVERFLOW": "15",
            "DB_ACTIVITY_POOL_SIZE": "12",
            "DB_ACTIVITY_MAX_OVERFLOW": "12",
        }
    )

    assert budget.limit is None
    assert budget.configured_demand == 174
    assert budget.headroom is None
