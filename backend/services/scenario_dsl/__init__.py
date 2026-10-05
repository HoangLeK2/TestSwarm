"""Org scenario DSL — step contract, registry, and body validation (DF-T-04-002)."""

from services.scenario_dsl.body_validator import (
    ScenarioBodyValidator,
    get_org_nesting_depth_limit,
    validate_org_scenario_body,
)
from services.scenario_dsl.models import BodyValidationIssue, BodyValidationResult
from services.scenario_dsl.step_contract import (
    assert_no_implicit_recovery,
    effective_error_policy,
    normalize_body_steps,
    normalize_step,
)
from services.scenario_dsl.step_family import (
    CORE_STEP_TYPES,
    DEFAULT_NESTING_DEPTH_LIMIT,
    STEP_FAMILY_VALUES,
    StepFamily,
)
from services.scenario_dsl.step_handler import StepHandler, StepResult
from services.scenario_dsl.step_registry import StepRegistry
from services.scenario_dsl.variable_resolver import EffectiveVariableResolver

__all__ = [
    "CORE_STEP_TYPES",
    "DEFAULT_NESTING_DEPTH_LIMIT",
    "STEP_FAMILY_VALUES",
    "BodyValidationIssue",
    "BodyValidationResult",
    "EffectiveVariableResolver",
    "ScenarioBodyValidator",
    "StepFamily",
    "StepHandler",
    "StepRegistry",
    "StepResult",
    "assert_no_implicit_recovery",
    "effective_error_policy",
    "get_org_nesting_depth_limit",
    "normalize_body_steps",
    "normalize_step",
    "validate_org_scenario_body",
]
