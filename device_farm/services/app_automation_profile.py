"""Contracts for app-level mobile automation profiles.

The profile is intentionally executor-agnostic. Runtime code can use it to
drive u2 selectors, popup watchers, login recipes, and form fill recipes
without baking app-specific scripts into scenario steps.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ValueRefPrefix = ("account.", "scenario.", "variables.", "secret.")

_DANGEROUS_ACTION_TEXT = (
    "buy",
    "delete",
    "pay",
    "purchase",
    "remove",
    "uninstall",
    "confirm purchase",
    "thanh toán",
    "xoa",
    "xóa",
    "xoá",
)


def _clean_text(value: str) -> str:
    return " ".join(value.strip().split())


def _has_value(data: dict[str, Any], *keys: str) -> bool:
    return any(data.get(key) not in (None, "", [], {}) for key in keys)


class StrictProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EntryState(StrictProfileModel):
    launch: bool = True
    wait_for_any: list[dict[str, Any]] = Field(default_factory=list)
    timeout_s: float = Field(default=15.0, gt=0)


class WatcherScope(StrictProfileModel):
    package: str | None = None
    activity: str | None = None
    screen: str | None = None


class WatcherCondition(StrictProfileModel):
    text: str | None = None
    text_contains: list[str] = Field(default_factory=list)
    description_contains: list[str] = Field(default_factory=list)
    resource_id_contains: list[str] = Field(default_factory=list)
    class_name: str | None = None

    @model_validator(mode="after")
    def require_condition(self) -> "WatcherCondition":
        data = self.model_dump()
        if not _has_value(
            data,
            "text",
            "text_contains",
            "description_contains",
            "resource_id_contains",
            "class_name",
        ):
            raise ValueError("watcher condition must include at least one matcher")
        return self


class WatcherAction(StrictProfileModel):
    tap_text: str | None = None
    tap_text_any: list[str] = Field(default_factory=list)
    press_key: str | None = None
    noop: bool = False
    allow_unsafe: bool = False

    @model_validator(mode="after")
    def validate_action(self) -> "WatcherAction":
        data = self.model_dump()
        has_action = _has_value(data, "tap_text", "tap_text_any", "press_key") or self.noop
        if not has_action:
            raise ValueError("watcher action must define tap_text, tap_text_any, press_key, or noop")

        labels = []
        if self.tap_text:
            labels.append(self.tap_text)
        labels.extend(self.tap_text_any)
        lowered = [_clean_text(label).lower() for label in labels]
        if not self.allow_unsafe:
            for label in lowered:
                if any(token in label for token in _DANGEROUS_ACTION_TEXT):
                    raise ValueError(f"unsafe watcher action requires allow_unsafe: {label!r}")
        return self


class PopupWatcher(StrictProfileModel):
    name: str
    when: WatcherCondition
    action: WatcherAction
    scope: WatcherScope | None = None
    max_triggers_per_run: int = Field(default=3, ge=1, le=20)
    cooldown_ms: int = Field(default=2000, ge=0)
    enabled: bool = True


class LocatorCandidate(StrictProfileModel):
    by: str | None = None
    value: str | None = None
    resource_id_contains: str | None = None
    text_near: list[str] = Field(default_factory=list)
    target_class: str | None = None
    class_name: str | None = None
    description_contains: str | None = None
    region: Literal["top", "bottom", "left", "right", "center", "form"] | None = None
    ocr_near: str | None = None
    tap_offset: tuple[int, int] | None = None
    allow_coordinate_fallback: bool = False

    @model_validator(mode="after")
    def require_candidate_signal(self) -> "LocatorCandidate":
        data = self.model_dump()
        if bool(self.by) != bool(self.value):
            raise ValueError("locator candidate must define by and value together")
        if self.target_class and not (self.text_near or self.ocr_near):
            raise ValueError("target_class requires text_near or ocr_near")
        if self.region and not (
            self.by
            or self.resource_id_contains
            or self.text_near
            or self.ocr_near
            or self.class_name
            or self.description_contains
        ):
            raise ValueError("region must filter a real selector signal")
        if not _has_value(
            data,
            "by",
            "value",
            "resource_id_contains",
            "text_near",
            "ocr_near",
            "class_name",
            "description_contains",
        ):
            raise ValueError("locator candidate must include at least one selector signal")
        if self.tap_offset and not (self.text_near or self.ocr_near or self.allow_coordinate_fallback):
            raise ValueError("tap_offset requires text_near, ocr_near, or explicit coordinate fallback")
        return self


class SemanticLocator(StrictProfileModel):
    candidates: list[LocatorCandidate] = Field(min_length=1)
    min_score: float = Field(default=0.70, gt=0, le=1)
    allow_ambiguous: bool = False


class LoginField(StrictProfileModel):
    locator: str
    value_from: str
    input_method: Literal["set_text", "type_text", "clipboard"] = "set_text"
    required: bool = True

    @model_validator(mode="after")
    def require_reference_value(self) -> "LoginField":
        if not self.value_from.startswith(ValueRefPrefix):
            raise ValueError("login field value_from must reference account., scenario., variables., or secret.")
        return self


class LoginSubmit(StrictProfileModel):
    tap_text: str | None = None
    tap_text_any: list[str] = Field(default_factory=list)
    locator: str | None = None

    @model_validator(mode="after")
    def require_submit_action(self) -> "LoginSubmit":
        data = self.model_dump()
        if not _has_value(data, "tap_text", "tap_text_any", "locator"):
            raise ValueError("login submit must define tap_text, tap_text_any, or locator")
        return self


class LoginPostSubmitAction(LoginSubmit):
    when_text_any: list[str] = Field(default_factory=list)
    timeout_s: float = Field(default=0.0, ge=0.0, le=30.0)
    poll_s: float = Field(default=0.5, gt=0, le=5.0)
    wait_after_s: float = Field(default=0.5, ge=0.0, le=10.0)


class LoginRecipe(StrictProfileModel):
    detect_logged_in: dict[str, Any]
    fields: dict[str, LoginField] = Field(min_length=1)
    submit: LoginSubmit
    post_submit_actions: list[LoginPostSubmitAction] = Field(default_factory=list)
    post_submit_fields: dict[str, LoginField] = Field(default_factory=dict)
    post_submit: LoginSubmit | None = None
    blocked_text_any: list[str] = Field(default_factory=lambda: ["captcha", "2fa", "verification"])


class FormField(StrictProfileModel):
    locator: str
    value_from: str
    required: bool = True

    @model_validator(mode="after")
    def require_reference_value(self) -> "FormField":
        if not self.value_from.startswith(ValueRefPrefix):
            raise ValueError("form field value_from must reference account., scenario., variables., or secret.")
        return self


class FormRecipe(StrictProfileModel):
    fields: dict[str, FormField] = Field(min_length=1)
    submit: LoginSubmit | None = None
    mode: Literal["strict", "best_effort"] = "strict"


class AppAutomationProfile(StrictProfileModel):
    package: str
    profile_version: int = Field(default=1, ge=1)
    entry_state: EntryState = Field(default_factory=EntryState)
    popup_watchers: list[PopupWatcher] = Field(default_factory=list)
    semantic_locators: dict[str, SemanticLocator] = Field(default_factory=dict)
    login_recipe: LoginRecipe | None = None
    form_recipes: dict[str, FormRecipe] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profile(self) -> "AppAutomationProfile":
        package = _clean_text(self.package)
        if not package:
            raise ValueError("profile package is required")
        self.package = package
        watcher_names: set[str] = set()
        for watcher in self.popup_watchers:
            if watcher.name in watcher_names:
                raise ValueError(f"duplicate watcher name {watcher.name!r}")
            watcher_names.add(watcher.name)
            if watcher.scope and watcher.scope.package:
                continue
            if not self.package:
                raise ValueError(f"watcher {watcher.name!r} has no effective package scope")
        locator_names = set(self.semantic_locators)
        if self.login_recipe:
            for field_name, field in self.login_recipe.fields.items():
                if field.locator not in locator_names:
                    raise ValueError(f"login field {field_name!r} references unknown locator {field.locator!r}")
            if self.login_recipe.submit.locator and self.login_recipe.submit.locator not in locator_names:
                raise ValueError(f"login submit references unknown locator {self.login_recipe.submit.locator!r}")
            for action_index, action in enumerate(self.login_recipe.post_submit_actions):
                if action.locator and action.locator not in locator_names:
                    raise ValueError(
                        f"login post-submit action {action_index} references unknown locator {action.locator!r}"
                    )
            for field_name, field in self.login_recipe.post_submit_fields.items():
                if field.locator not in locator_names:
                    raise ValueError(
                        f"login post-submit field {field_name!r} references unknown locator {field.locator!r}"
                    )
            if (
                self.login_recipe.post_submit
                and self.login_recipe.post_submit.locator
                and self.login_recipe.post_submit.locator not in locator_names
            ):
                raise ValueError(
                    f"login post-submit action references unknown locator {self.login_recipe.post_submit.locator!r}"
                )
        for recipe_name, recipe in self.form_recipes.items():
            for field_name, field in recipe.fields.items():
                if field.locator not in locator_names:
                    raise ValueError(
                        f"form recipe {recipe_name!r} field {field_name!r} references unknown locator {field.locator!r}"
                    )
            if recipe.submit and recipe.submit.locator and recipe.submit.locator not in locator_names:
                raise ValueError(f"form recipe {recipe_name!r} submit references unknown locator {recipe.submit.locator!r}")
        return self


def validate_app_automation_profile(raw: dict[str, Any]) -> AppAutomationProfile:
    """Validate and normalize an app automation profile."""
    return AppAutomationProfile.model_validate(raw)


def watcher_effective_package(profile: AppAutomationProfile, watcher: PopupWatcher) -> str:
    """Return the package scope a watcher should run under."""
    if watcher.scope and watcher.scope.package:
        return watcher.scope.package
    return profile.package


def redacted_profile_dump(profile: AppAutomationProfile) -> dict[str, Any]:
    """Return a JSON-safe profile dump that keeps references but no resolved secrets."""
    return profile.model_dump(mode="json")
