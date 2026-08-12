from types import SimpleNamespace

from common.variable_resolver import VariableContext
from tasks.scenario.steps.source_pool import handle_use_source_pool


def test_use_source_pool_reports_target_from_effective_variable_context():
    sc = SimpleNamespace(
        scenario={"variables": {}},
        ctx={},
        var_ctx=VariableContext(scenario_vars={"TARGET_ENTITY_ID": "post-1"}),
    )
    result = {}

    handle_use_source_pool(
        sc,
        {"type": "use_source_pool", "platform": "facebook", "entity_type": "post"},
        0,
        result,
    )

    assert result["target_entity_id"] == "post-1"
