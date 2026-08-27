from __future__ import annotations

import pytest


def test_connection_budget_accepts_safe_120_phone_configuration():
    from db.connection_budget import validate_connection_budget

    budget = validate_connection_budget(
        {
            "DB_CONNECTION_LIMIT": "104",
            "DB_CONNECTION_RESERVE": "15",
            "TEMPORAL_DB_MAX_CONNECTIONS": "40",
            "TEMPORAL_WORKER_COUNT": "7",
            "TEMPORAL_CONTROL_WORKER_COUNT": "0",
            "DB_POOL_SIZE": "12",
            "DB_MAX_OVERFLOW": "3",
            "DB_ACTIVITY_POOL_SIZE": "4",
            "DB_ACTIVITY_MAX_OVERFLOW": "0",
        }
    )

    assert budget.web_max == 15
    assert budget.activity_max == 28
    assert budget.edge_ingest_max == 4
    assert budget.configured_demand == 87
    assert budget.total_with_reserve == 102
    assert budget.headroom == 2


def test_control_workers_count_toward_the_activity_pool():
    """Control workers own an activity pool each, exactly like device workers.

    They run in the same process on their own event loop, so db/database.py
    hands each one its own engine. Counting only TEMPORAL_WORKER_COUNT would
    under-report demand and let a config through that exhausts PostgreSQL.
    """
    from db.connection_budget import validate_connection_budget

    common = {
        "DB_CONNECTION_LIMIT": "200",
        "DB_CONNECTION_RESERVE": "15",
        "TEMPORAL_DB_MAX_CONNECTIONS": "40",
        "TEMPORAL_WORKER_COUNT": "6",
        "DB_POOL_SIZE": "12",
        "DB_MAX_OVERFLOW": "3",
        "DB_ACTIVITY_POOL_SIZE": "10",
        "DB_ACTIVITY_MAX_OVERFLOW": "0",
    }

    without = validate_connection_budget({**common, "TEMPORAL_CONTROL_WORKER_COUNT": "0"})
    with_control = validate_connection_budget({**common, "TEMPORAL_CONTROL_WORKER_COUNT": "2"})

    assert without.activity_max == 60
    assert with_control.activity_max == 80
    assert with_control.configured_demand == 139  # 15 web + 4 edge + 80 activity + 40 temporal
    assert with_control.total_with_reserve == 154


def test_connection_budget_defaults_match_recommended_pool_sizes():
    from db.connection_budget import validate_connection_budget

    # 200 is the configured PostgreSQL max_connections (docker-compose.yml).
    # The old 100 no longer fits the defaults once control workers are counted,
    # which is the whole reason max_connections was raised.
    budget = validate_connection_budget(
        {
            "DB_CONNECTION_LIMIT": "200",
            "DB_CONNECTION_RESERVE": "15",
            "TEMPORAL_DB_MAX_CONNECTIONS": "40",
        }
    )

    assert budget.web_max == 15
    assert budget.activity_max == 36  # (7 device + 2 control) x 4
    assert budget.total_with_reserve == 110


def test_connection_budget_rejects_configuration_that_can_exhaust_postgres():
    from db.connection_budget import ConnectionBudgetError, validate_connection_budget

    with pytest.raises(ConnectionBudgetError, match=r"178 configured \+ 15 reserved > 100"):
        validate_connection_budget(
            {
                "DB_CONNECTION_LIMIT": "100",
                "DB_CONNECTION_RESERVE": "15",
                "TEMPORAL_DB_MAX_CONNECTIONS": "0",
                "TEMPORAL_WORKER_COUNT": "6",
                "TEMPORAL_CONTROL_WORKER_COUNT": "0",
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
            "TEMPORAL_CONTROL_WORKER_COUNT": "0",
            "DB_POOL_SIZE": "15",
            "DB_MAX_OVERFLOW": "15",
            "DB_ACTIVITY_POOL_SIZE": "12",
            "DB_ACTIVITY_MAX_OVERFLOW": "12",
        }
    )

    assert budget.limit is None
    assert budget.configured_demand == 178
    assert budget.headroom is None


def test_edge_ingest_pool_counts_toward_connection_budget_once():
    from db.connection_budget import validate_connection_budget

    budget = validate_connection_budget(
        {
            "DB_CONNECTION_LIMIT": "120",
            "DB_CONNECTION_RESERVE": "15",
            "TEMPORAL_DB_MAX_CONNECTIONS": "40",
            "TEMPORAL_WORKER_COUNT": "4",
            "TEMPORAL_CONTROL_WORKER_COUNT": "0",
            "DB_POOL_SIZE": "12",
            "DB_MAX_OVERFLOW": "3",
            "DB_ACTIVITY_POOL_SIZE": "4",
            "DB_ACTIVITY_MAX_OVERFLOW": "0",
            "EDGE_INGEST_POOL_SIZE": "4",
        }
    )

    assert budget.edge_ingest_max == 4
    assert budget.configured_demand == 75
