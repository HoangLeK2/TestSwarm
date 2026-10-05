"""Regression tests for scenario composition steps."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))


def test_run_scenario_bubbles_nested_edge_extra_summary():
    from tasks.scenario.steps.composition import handle_run_scenario

    sc = SimpleNamespace(
        scenario={
            "_scenario_registry": {
                "by_id": {
                    "sub-1": {
                        "steps": [{"type": "loop", "steps": [{"type": "extract"}]}],
                        "variables": {},
                    }
                }
            }
        },
        call_stack=set(),
        serial="SN1",
    )
    nested_failure = {
        "success": False,
        "failed_message": "loop failed: edge extra_data failed",
        "step_results": [
            {
                "index": 0,
                "type": "loop",
                "ok": False,
                "message": "loop failed",
                "sub_result": {
                    "success": False,
                    "step_results": [
                        {
                            "index": 0,
                            "type": "extract",
                            "ok": False,
                            "message": "edge extra_data failed",
                            "edge_extra_summary": {
                                "diagnostic": {
                                    "reason_code": "post_open_target_not_found",
                                    "timing": {"total_ms": 42.0},
                                }
                            },
                            "extra_data_total_ms": 42.0,
                        }
                    ],
                },
            }
        ],
    }
    result = {"index": 0, "type": "run_scenario", "ok": True}

    with patch("tasks.scenario.executor.run_nested_scenario", return_value=nested_failure):
        handle_run_scenario(sc, {"type": "run_scenario", "scenario_id": "sub-1"}, 0, result)

    assert result["ok"] is False
    assert result["edge_extra_summary"]["diagnostic"]["reason_code"] == "post_open_target_not_found"
    assert result["edge_extra_summary"]["diagnostic"]["timing"]["total_ms"] == 42.0
    assert result["extra_data_total_ms"] == 42.0
    assert result["nested_failure"]["step_type"] == "extract"
