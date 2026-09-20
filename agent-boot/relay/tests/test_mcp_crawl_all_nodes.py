from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_mcp_crawl_all_nodes():
    script = Path(__file__).resolve().parents[2] / "scripts" / "mcp_crawl_all_nodes.py"
    spec = importlib.util.spec_from_file_location("mcp_crawl_all_nodes", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_scenario_schema_nodes_have_mcp_mode():
    module = _load_mcp_crawl_all_nodes()

    missing = [
        step_type
        for step_type in module.SCENARIO_STEP_TYPES
        if module.mcp_mode_for_step_type(step_type) == "unknown"
    ]

    assert missing == []


def test_schema_catalog_reports_no_missing_mcp_types():
    module = _load_mcp_crawl_all_nodes()

    catalog = module.catalog_steps(module.schema_steps())

    assert catalog["schema_coverage"]["missing_mcp_types"] == []
    assert catalog["schema_coverage"]["schema_step_types"] == len(module.SCENARIO_STEP_TYPES)
