"""Every field an executor reads must be declared in STEP_SCHEMA.

STEP_SCHEMA is what ``/scenario/schema`` publishes, so an undeclared field is a
field the editor cannot offer and the two validators silently drop. That is how
``loop.stall_after`` — the guard built to stop a 204-iteration runaway — ended up
unreachable from the UI.

The scan is deliberately literal-only: ``step.get("x")``, ``step["x"]``,
``step.pop("x")``. A computed key is invisible to it, so a clean run proves the
declared surface covers the literal reads, not that it covers everything.
"""
from __future__ import annotations

import ast
import pathlib

from common.scenario_schema import STEP_SCHEMA

_STEPS_DIR = pathlib.Path(__file__).resolve().parents[1] / "tasks/scenario/steps"

# Keys the runtime injects or the step contract owns — never node fields.
_INTERNAL = frozenset({
    "id",
    "type",
    "step_id",
    "step_path",
    "retry",
    "config",
    "error_policy",
    "on_error",
    "pre_capture",
    "post_capture",
    "enabled",
    "note",
    "title",
    "label",
    "_id",
    "_scenario_parent_trace",
    "repeat_count",
    "repeat_index",
    "scenario_ref_index",
    "scenario_sequence_index",
})

# Legacy spellings the executor still accepts. Declaring these would not help:
# the canonical name is in `required`, so a step written with the alias is
# rejected by validate_step AND by Pydantic even though the executor runs it.
# Fixing that needs an alias table applied before validation — deferred.
# See navigation.py:166,174,185,258,275,306,341 and extraction.py:1883.
_DEFERRED_ALIASES = {
    "adb_shell": {"cmd"},
    "install_apk": {"apk_url"},
    "push_file": {"src", "dst"},
    "pull_file": {"src", "dst"},
    "launch_app": {"packageFallbacks", "adbFallback", "stop"},
    "extract_text_ocr": {"languages"},
}


def _literal_step_keys(fn: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "step"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "step"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _reads_by_step_type() -> dict[str, set[str]]:
    reads: dict[str, set[str]] = {}
    for path in sorted(_STEPS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in fn.decorator_list:
                if not (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Name)
                    and dec.func.id == "register_step"
                ):
                    continue
                keys = _literal_step_keys(fn)
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        reads.setdefault(arg.value, set()).update(keys)
    return reads


def _declared(step_type: str) -> set[str]:
    schema = STEP_SCHEMA[step_type]
    return (
        set(schema.get("required") or ())
        | set(schema.get("optional") or ())
        | set(schema.get("fields") or ())
        | {name for group in schema.get("required_any") or () for name in group}
    )


def test_executors_only_read_declared_fields():
    undeclared: dict[str, list[str]] = {}
    for step_type, keys in _reads_by_step_type().items():
        if step_type not in STEP_SCHEMA:
            continue  # runtime alias handler (`if`, `set_var`) — covered elsewhere
        extra = keys - _declared(step_type) - _INTERNAL - _DEFERRED_ALIASES.get(step_type, set())
        if extra:
            undeclared[step_type] = sorted(extra)

    assert undeclared == {}, (
        "executors read fields STEP_SCHEMA does not publish; declare them in "
        "`optional`, or add them to _DEFERRED_ALIASES/_INTERNAL with a reason:\n"
        + "\n".join(f"  {t}: {fields}" for t, fields in sorted(undeclared.items()))
    )


def test_deferred_alias_list_stays_honest():
    """An alias that stopped being read should leave the list, not rot in it."""
    reads = _reads_by_step_type()
    stale: dict[str, list[str]] = {}
    for step_type, aliases in _DEFERRED_ALIASES.items():
        gone = sorted(aliases - reads.get(step_type, set()))
        if gone:
            stale[step_type] = gone

    assert stale == {}


def test_scan_actually_finds_handlers():
    """Guard the guard: a decorator rename must not silently empty this test."""
    reads = _reads_by_step_type()

    assert len(reads) > 50
    assert "stall_after" in reads["loop"]
