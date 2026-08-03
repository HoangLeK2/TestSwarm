"""
scenario.py — Pydantic models for scenario & step validation.

Validates the full scenario JSON structure BEFORE execution so that
type errors (e.g. DURATION_MINUTES is a string instead of float,
LIKE_PROBABILITY > 1.0) are caught at save/dispatch time, not at
runtime 10 minutes into a campaign run.

Usage:
    from api.schemas.scenario import ScenarioModel
    errors = ScenarioModel.validate_dict(raw_dict)
    # errors: list[str]  — empty = valid
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Graph node / edge models (Phase 3 — node-graph refactor)
# ---------------------------------------------------------------------------

class NodeScope(BaseModel):
    parentId: str
    branch: str = "steps"


class FlowNodeModel(BaseModel):
    """Single node in the scenario graph."""
    model_config = {"extra": "allow"}

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    config: Dict[str, Any] = {}
    order: str = Field(min_length=1)          # fractional index key
    scope: Optional[NodeScope] = None         # None = root level
    position: Optional[Dict[str, float]] = None  # {x, y} for future visual editor
    title: Optional[str] = None
    description: Optional[str] = None


class FlowEdgeModel(BaseModel):
    """Directed edge between two nodes."""
    model_config = {"extra": "allow"}  # preserve any UI metadata (e.g. label, color)
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    type: Literal["default", "conditional", "error", "fallback"] = "default"
    condition: Optional[str] = None


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

SelectorBy = Literal["resource-id", "text", "xpath", "class name",
                      "description", "descriptionContains", "descriptionStartsWith",
                      "descriptionStartswith",
                      "content-desc"]

# Fields that support ${VAR} interpolation at runtime use these types.
# A plain string is accepted (e.g. "${SCROLL_COUNT}"); bounds are only
# enforced for literal numbers.
NumOrVar = Union[float, str]   # float fields (seconds, timeout, …)
IntOrVar = Union[int, str]     # int fields (count, repeats, …)
TagsOrStr = Union[List[str], str]  # tags: list OR comma-separated string


class StepBase(BaseModel):
    # ── Node identity (Option B) ──
    id: Optional[str] = None           # nanoid — auto-generated if missing
    order: Optional[str] = None        # fractional index key — auto-generated if missing

    title: Optional[str] = None
    description: Optional[str] = None


class ImplicitWaitDict(BaseModel):
    timeout: float = Field(10.0, ge=0.1, le=60.0)
    poll: float = Field(0.5, ge=0.1, le=10.0)


ImplicitWait = Union[float, ImplicitWaitDict]

# ---------------------------------------------------------------------------
# Screen context (visual anchoring data captured at record time)
# ---------------------------------------------------------------------------

class ScreenshotAnchorRegion(BaseModel):
    """ROI region as ratios of full screen (0-1). Used to crop search area for faster template match."""
    rx: float = Field(0.0, ge=0.0, le=1.0)
    ry: float = Field(0.0, ge=0.0, le=1.0)
    rw: float = Field(1.0, gt=0.0, le=1.0)
    rh: float = Field(1.0, gt=0.0, le=1.0)

class ScreenshotAnchor(BaseModel):
    """ROI crop around tap point for faster image matching during playback."""
    image: Optional[str] = None            # base64 JPEG of the ROI area
    region: Optional[ScreenshotAnchorRegion] = None

class ScreenContext(BaseModel):
    model_config = {"extra": "allow"}
    package: Optional[str] = None
    hash: Optional[str] = None
    texts: Optional[List[str]] = None
    screenshot: Optional[str] = None       # base64 JPEG
    element_image: Optional[str] = None    # base64 JPEG (cropped)
    screenshot_anchor: Optional[ScreenshotAnchor] = None  # ROI for fast image match

# ---------------------------------------------------------------------------
# Selector sub-models (nested ScenarioSelector + chain ops)
# ---------------------------------------------------------------------------

class SelectorConditions(BaseModel):
    """Extra AND conditions (uiautomator2 selector fields)."""
    model_config = {"extra": "allow"}

    text: Optional[str] = None
    textContains: Optional[str] = None
    textMatches: Optional[str] = None
    textStartsWith: Optional[str] = None
    resourceId: Optional[str] = None
    className: Optional[str] = None
    description: Optional[str] = None
    descriptionContains: Optional[str] = None
    descriptionStartsWith: Optional[str] = None
    packageName: Optional[str] = None
    clickable: Optional[bool] = None
    checked: Optional[bool] = None
    checkable: Optional[bool] = None
    enabled: Optional[bool] = None
    scrollable: Optional[bool] = None
    focused: Optional[bool] = None
    selected: Optional[bool] = None
    instance: Optional[int] = Field(None, ge=0)
    index: Optional[int] = Field(None, ge=0)


class ChainTarget(BaseModel):
    by: Optional[SelectorBy] = None
    value: Optional[str] = None
    conditions: Optional[SelectorConditions] = None


class ChainStep(BaseModel):
    """Single uiautomator2 chain op applied after anchor selector."""
    op: Literal[
        "child", "sibling", "relative",
        "child_by_text", "child_by_description",
    ]
    target: Optional[ChainTarget] = None
    direction: Optional[Literal["left", "right", "up", "down"]] = None
    text: Optional[str] = None
    description: Optional[str] = None
    allow_scroll_search: Optional[bool] = None


class ScenarioSelector(BaseModel):
    """Canonical nested selector (tap_selector, wait_element, …)."""
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    conditions: Optional[SelectorConditions] = None
    instance: Optional[int] = Field(None, ge=0)
    index: Optional[int] = Field(None, ge=0)
    xpath: Optional[str] = None
    chain: Optional[ChainStep] = None
    bounds: Optional[List[int]] = None


class TapSelector(BaseModel):
    """Legacy tap nested selector — alias of primary by/value."""
    by: SelectorBy
    value: str = Field(min_length=1)


class SelectorFallback(BaseModel):
    rx: float = Field(ge=0.0, le=1.0)
    ry: float = Field(ge=0.0, le=1.0)


class TapFallback(BaseModel):
    rx: float = Field(ge=0.0, le=1.0)
    ry: float = Field(ge=0.0, le=1.0)


def _selector_step_validate_legacy(model: Any) -> Any:
    """Ensure nested selector or legacy by/value is present on selector steps."""
    sel = getattr(model, "selector", None)
    by = getattr(model, "by", None)
    value = getattr(model, "value", None)
    has_nested = sel is not None and (
        (isinstance(sel, ScenarioSelector) and (sel.value or "").strip())
        or (isinstance(sel, dict) and str(sel.get("value") or "").strip())
    )
    has_legacy = bool(str(by or "").strip() and str(value or "").strip())
    if not has_nested and not has_legacy:
        raise ValueError("selector or by/value required")
    return model

# ---------------------------------------------------------------------------
# Condition sub-models (for control flow steps)
# ---------------------------------------------------------------------------

class ElementCondition(BaseModel):
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    selector: Optional[ScenarioSelector] = None

    @model_validator(mode="after")
    def selector_or_legacy(self):
        if self.selector is not None and (self.selector.value or "").strip():
            return self
        if self.value and str(self.value).strip():
            return self
        raise ValueError("element condition requires selector.value or value")

class ConditionDict(BaseModel):
    """Condition for repeat_until / break_if / loop while."""
    model_config = {"extra": "allow"}
    type: Optional[str] = None
    # element_exists / element_not_exists
    element_exists: Optional[ElementCondition] = None
    element_not_exists: Optional[ElementCondition] = None
    # variable comparison
    variable_equals: Optional[Dict[str, Any]] = None
    # posts count (crawl context)
    count: Optional[int] = Field(None, ge=0)

# ---------------------------------------------------------------------------
# Branch (for random_pick)
# ---------------------------------------------------------------------------

class RandomBranch(BaseModel):
    steps: List[StepModel] = []   # empty = no-op branch (valid for skip probability)
    weight: NumOrVar = 1.0

# ---------------------------------------------------------------------------
# Step models — one per step type
# ---------------------------------------------------------------------------

class LaunchAppStep(StepBase):
    type: Literal["launch_app"]
    package: str = Field(min_length=1)
    wait_after: float = Field(2.0, ge=0, le=30)
    activity: Optional[str] = None
    component: Optional[str] = None
    stop_before: bool = False
    use_monkey: bool = False

class StopAppStep(StepBase):
    type: Literal["stop_app"]
    package: str = Field(min_length=1)

class ClearAppStep(StepBase):
    type: Literal["clear_app"]
    package: str = Field(min_length=1)

class WaitAppStep(StepBase):
    type: Literal["wait_app"]
    package: str = Field(min_length=1)
    timeout: float = Field(20.0, ge=0.1, le=120)
    front: bool = True

class PushFileStep(StepBase):
    type: Literal["push_file"]
    local_path: str = Field(min_length=1)
    remote_path: str = Field(min_length=1)
    mode: Optional[int] = None

class PullFileStep(StepBase):
    type: Literal["pull_file"]
    local_path: str = Field(min_length=1)
    remote_path: str = Field(min_length=1)

class OpenUrlStep(StepBase):
    type: Literal["open_url"]
    url: str = Field(min_length=1)
    package: Optional[str] = None

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        u = v.strip().lower()
        if not (u.startswith("http://") or u.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return v

class InstallApkStep(StepBase):
    type: Literal["install_apk"]
    url: str = Field(min_length=1)
    timeout: float = Field(90.0, ge=10.0, le=600.0)

    @field_validator("url")
    @classmethod
    def url_must_be_install_source(cls, v: str) -> str:
        u = v.strip()
        low = u.lower()
        if low.startswith(("http://", "https://")):
            return v
        if u.startswith("/") or u.startswith("${"):
            return v
        raise ValueError(
            "url must be an http(s) APK URL, absolute local path, or ${VARIABLE}"
        )

class WaitStep(StepBase):
    type: Literal["wait"]
    seconds: NumOrVar = 1.0

class TapStep(StepBase):
    type: Literal["tap"]
    selector: Optional[Union[TapSelector, ScenarioSelector]] = None
    fallback: Optional[TapFallback] = None
    screen: Optional[ScreenContext] = None
    timeout: float = Field(4.0, ge=0.1, le=60)
    wait_after: bool = True
    implicit_wait: Optional[ImplicitWait] = None

class TapRatioStep(StepBase):
    type: Literal["tap_ratio"]
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)

class TapPositionStep(StepBase):
    type: Literal["tap_position"]
    pos: Literal["top_center", "middle_center", "bottom_center", "search_bar"]

class SwipeRatioStep(StepBase):
    type: Literal["swipe_ratio"]
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)
    duration_ms: int = Field(300, ge=50, le=5000)

class TapSelectorStep(StepBase):
    type: Literal["tap_selector"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    fallback: Optional[SelectorFallback] = None
    fallback_rx: Optional[float] = Field(None, ge=0.0, le=1.0)
    fallback_ry: Optional[float] = Field(None, ge=0.0, le=1.0)
    timeout: float = Field(8.0, ge=0.1, le=60)
    implicit_wait: Optional[ImplicitWait] = None
    element_image: Optional[str] = None  # base64 for visual anchoring

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)


class WaitElementStep(StepBase):
    type: Literal["wait_element"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    timeout: float = Field(10.0, ge=0.1, le=120)
    poll: float = Field(0.5, ge=0.1, le=10)

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)


class AssertElementStep(StepBase):
    type: Literal["assert_element"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    timeout: float = Field(5.0, ge=0.1, le=60)
    poll: float = Field(0.5, ge=0.1, le=10)

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)


class InputSelectorStep(StepBase):
    type: Literal["input_selector"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "resource-id"
    value: Optional[str] = None
    text: str
    clear_first: bool = True
    implicit_wait: Optional[ImplicitWait] = None

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)


class LongTapSelectorStep(StepBase):
    type: Literal["long_tap_selector"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    duration_ms: int = Field(800, ge=100, le=10000)
    implicit_wait: Optional[ImplicitWait] = None

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)


class ScrollToStep(StepBase):
    type: Literal["scroll_to"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    direction: Literal["down", "up"] = "down"
    max_swipes: int = Field(5, ge=1, le=50)

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)

class InputTextStep(StepBase):
    type: Literal["input_text"]
    text: str
    via: Literal["u2", "a11y_key"] = "u2"


class LoginIfNeededStep(StepBase):
    type: Literal["login_if_needed"]
    profile: Dict[str, Any] = Field(default_factory=dict)
    clear_first: bool = True
    implicit_wait: Optional[ImplicitWait] = None


class FillFormStep(StepBase):
    type: Literal["fill_form"]
    profile: Dict[str, Any] = Field(default_factory=dict)
    recipe: Optional[str] = None
    clear_first: bool = True
    implicit_wait: Optional[ImplicitWait] = None


class AssertAppStateStep(StepBase):
    type: Literal["assert_app_state"]
    profile: Dict[str, Any] = Field(default_factory=dict)
    package: Optional[str] = None
    any_text: List[str] = Field(default_factory=list)
    all_text: List[str] = Field(default_factory=list)
    not_text: List[str] = Field(default_factory=list)
    locator: Optional[str] = None


class KeyStep(StepBase):
    type: Literal["key"]
    key: str = Field(min_length=1)

class AdbShellStep(StepBase):
    type: Literal["adb_shell"]
    command: str = Field(min_length=1)
    timeout: float = Field(30.0, ge=1.0, le=120.0)
    fail_on_error: bool = True
    save_as: Optional[str] = None
    max_output_chars: int = Field(8000, ge=1000, le=50000)

class ScrollDownStep(StepBase):
    type: Literal["scroll_down"]
    repeats: IntOrVar = 1
    start_x_ratio: NumOrVar = 0.5
    start_y_ratio: NumOrVar = 0.72
    end_y_ratio: NumOrVar = 0.38
    duration_ms: IntOrVar = 520
    pause_seconds: NumOrVar = 0.6

class WaitStableStep(StepBase):
    type: Literal["wait_stable"]
    timeout: float = Field(5.0, ge=0.1, le=60)
    stable_duration: float = Field(0.4, ge=0.1, le=10)

class VerifyScreenStep(StepBase):
    type: Literal["verify_screen"]
    screenshot: str = Field(min_length=10)  # base64 JPEG
    ssim_threshold: float = Field(0.75, ge=0.0, le=1.0)
    timeout: float = Field(8.0, ge=0.1, le=60)
    poll: float = Field(0.5, ge=0.1, le=10)

class DismissPopupStep(StepBase):
    type: Literal["dismiss_popup"]
    retries: int = Field(3, ge=1, le=20)

class SetVariableStep(StepBase):
    type: Literal["set_variable"]
    name: str = Field(min_length=1)
    value: Optional[Any] = None
    from_list: Optional[Union[List[Any], str]] = None  # str = "${VAR}" interpolation
    increment: Optional[IntOrVar] = None

    @model_validator(mode="after")
    def at_least_one_source(self):
        has = sum(x is not None for x in [self.value, self.from_list, self.increment])
        if has == 0:
            # value=None is allowed (sets variable to None)
            pass
        if has > 1:
            raise ValueError("set_variable: use only ONE of value, from_list, increment")
        return self

# ── Control flow steps ──

class RepeatStep(StepBase):
    type: Literal["repeat"]
    count: IntOrVar
    steps: List[StepModel] = Field(min_length=1)
    delay_between: NumOrVar = 0

class RepeatUntilStep(StepBase):
    type: Literal["repeat_until"]
    condition: ConditionDict
    steps: List[StepModel] = Field(min_length=1)
    max_iterations: IntOrVar = 100

class IfElementStep(StepBase):
    type: Literal["if_element"]
    selector: Optional[ScenarioSelector] = None
    by: Optional[SelectorBy] = "text"
    value: Optional[str] = None
    then: List[StepModel] = Field(min_length=1)
    timeout: float = Field(3.0, ge=0.1, le=60)
    # pydantic: "else" is a reserved word → alias
    else_steps: Optional[List[StepModel]] = Field(None, alias="else")

    @model_validator(mode="after")
    def _sel(self):
        return _selector_step_validate_legacy(self)

class IfVariableStep(StepBase):
    type: Literal["if_variable"]
    name: str = Field(min_length=1)
    then: List[StepModel] = Field(min_length=1)
    equals: Optional[Any] = None
    not_equals: Optional[Any] = None
    contains: Optional[str] = None
    greater_than: Optional[float] = None
    else_steps: Optional[List[StepModel]] = Field(None, alias="else")

class TapFbCommentButtonStep(StepBase):
    type: Literal["tap_fb_comment_button"]
    timeout: NumOrVar = 6.0
    poll: NumOrVar = 0.4
    dedupe_field: str = "post_key"
    ignore_error: bool = True
    switch_to_all_comments: bool = True
    comment_filter: Optional[str] = None
    post_tap_wait_s: NumOrVar = 0.8
    then: List[StepModel] = []
    else_steps: List[StepModel] = Field(default_factory=list, alias="else")

class FbTapCommentButtonStep(TapFbCommentButtonStep):
    type: Literal["fb_tap_comment_button"]

class FbFindCommentButtonStep(StepBase):
    type: Literal["fb_find_comment_button"]
    timeout: NumOrVar = 6.0
    poll: NumOrVar = 0.4
    dedupe_field: str = "post_key"
    ignore_error: bool = True
    switch_to_all_comments: bool = True
    comment_filter: Optional[str] = None

class FbTapCommentTargetStep(StepBase):
    type: Literal["fb_tap_comment_target"]
    ignore_error: bool = True
    post_tap_wait_s: NumOrVar = 0.35

class FbApplyCommentFilterStep(StepBase):
    type: Literal["fb_apply_comment_filter"]
    switch_to_all_comments: bool = True
    comment_filter: Optional[str] = "all_comments"
    comment_filter_settle_s: NumOrVar = 0.45
    comment_filter_step_pause_s: NumOrVar = 0.35
    comment_filter_post_select_s: NumOrVar = 0.85

class RandomPickStep(StepBase):
    type: Literal["random_pick"]
    branches: List[RandomBranch] = Field(min_length=1)

class LoopStep(StepBase):
    type: Literal["loop"]
    steps: List[StepModel] = Field(min_length=1)
    count: Optional[IntOrVar] = None
    max_iterations: IntOrVar = 100
    # "while" is reserved → model_config handles it
    model_config = {"extra": "allow"}

class BreakIfStep(StepBase):
    type: Literal["break_if"]
    condition: ConditionDict

class RunScenarioStep(StepBase):
    type: Literal["run_scenario"]
    scenario_id: Optional[str] = None
    scenario_name: Optional[str] = None
    variables: Dict[str, Any] = {}

    @model_validator(mode="after")
    def need_id_or_name(self):
        if not self.scenario_id and not self.scenario_name:
            raise ValueError("run_scenario requires scenario_id or scenario_name")
        return self


class UseSourcePoolStep(StepBase):
    type: Literal["use_source_pool"]
    platform: str = Field("facebook", min_length=1, max_length=64)
    entity_type: str = Field("group", min_length=1, max_length=64)
    search: Optional[str] = None
    output_prefix: Optional[str] = Field("GROUP", max_length=32)
    statuses: List[str] = Field(
        default_factory=lambda: ["candidate", "active", "available"],
        min_length=1,
        max_length=10,
    )
    allocation_policy: Literal["one_per_device"] = "one_per_device"

# ── Extraction steps ──

class ExtractStep(StepBase):
    type: Literal["extract"]
    strategy: Literal[
        "fb_posts",
        "text_nodes",
        "fb_comments",
        "fb_groups",
        "ig_posts",
        "tiktok_posts",
        "linkedin_posts",
        "auto_posts",
        "ig_comments",
        "tiktok_comments",
        "linkedin_comments",
        "auto_comments",
    ]
    search_query: Optional[str] = None
    stop_if_no_new: bool = False
    no_new_threshold: int = Field(3, ge=1, le=1000)
    # Literal profile or "${VAR}" resolved from scenario variables at runtime.
    extract_profile: Optional[str] = None
    open_post_before_extract: Optional[bool] = None
    open_post_press_back_after_extract: Optional[bool] = None
    expand_see_more: bool = True
    # Progressive expansion (long post/comment hydration)
    # support int/float or "${VAR}" strings resolved at runtime
    expand_see_more_max_passes: Optional[IntOrVar] = None
    expand_see_more_scroll: Optional[bool] = None
    expand_see_more_scroll_distance: Optional[NumOrVar] = None
    expand_completion_retries: Optional[IntOrVar] = None
    # fb_comments-specific
    parent_post_id_var: Optional[str] = None  # ctx var holding parent post id
    # int or "${VAR}" string — resolved at runtime before use
    max_items: Optional[Union[int, str]] = None
    comment_scroll_passes: Optional[IntOrVar] = None
    comment_swipes_per_dump: Optional[IntOrVar] = None
    comment_scroll_distance: Optional[NumOrVar] = None
    comment_scroll_duration_ms: Optional[IntOrVar] = None
    comment_scroll_pause_s: Optional[NumOrVar] = None
    comment_scroll_wall_s: Optional[NumOrVar] = None
    comment_require_complete: Optional[bool] = None
    comment_auto_coverage_target_max: Optional[IntOrVar] = None
    allow_partial_comments: Optional[bool] = None
    comment_no_growth_break: Optional[IntOrVar] = None
    min_comment_scan_passes: Optional[IntOrVar] = None
    comment_max_snapshots: Optional[IntOrVar] = None
    comment_stop_if_no_new: Optional[bool] = None
    comment_no_new_threshold: Optional[IntOrVar] = None
    # ── Inline save (merged extract+save) ──
    # When collection is set, auto-save extracted data after extraction.
    # Replaces the need for a separate save_extraction step.
    collection: Optional[str] = None
    platform: Optional[str] = None
    content_type: Optional[str] = None
    dedupe_field: Optional[str] = None
    tags: Optional[TagsOrStr] = None
    save_parent_id_var: Optional[str] = None
    item_level: int = Field(0, ge=0, le=2)

    @field_validator("extract_profile")
    @classmethod
    def extract_profile_literal_or_var(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = str(v).strip()
        if s in ("balanced", "aggressive", "safe"):
            return s
        if s.startswith("${") and s.endswith("}"):
            return s
        raise ValueError(
            "extract_profile must be 'balanced', 'aggressive', 'safe', or a ${VAR} reference"
        )


class SocialActionStepBase(StepBase):
    platform: str = Field("facebook", min_length=1, max_length=64)
    action: str
    timeout: float = Field(6.0, ge=0.1, le=60.0)
    poll: float = Field(0.4, ge=0.05, le=10.0)
    verify_timeout: float = Field(5.0, ge=0.1, le=60.0)
    settle_seconds: float = Field(0.35, ge=0.0, le=10.0)
    save_as: Optional[str] = Field(None, min_length=1, max_length=128)


class ContentInteractionStep(SocialActionStepBase):
    type: Literal["content_interaction"]
    action: str = Field("like", min_length=1, max_length=64)


class ConnectionRequestStep(SocialActionStepBase):
    type: Literal["connection_request"]
    action: str = Field("request", min_length=1, max_length=64)


class CommunityMembershipStep(SocialActionStepBase):
    type: Literal["community_membership"]
    action: str = Field("join", min_length=1, max_length=64)


class ExtractTextHierarchyStep(StepBase):
    type: Literal["extract_text_hierarchy"]
    save_as: str = Field(min_length=1)
    filter_class: Optional[List[str]] = None
    exclude_empty: bool = True
    format: Literal["text", "json"] = "text"

class ExtractTextOcrStep(StepBase):
    type: Literal["extract_text_ocr"]
    save_as: str = Field(min_length=1)
    region: Optional[Dict[str, float]] = None
    language: str = "eng"
    psm: int = Field(11, ge=0, le=13)
    preprocess: Optional[str] = None
    scale_factor: float = Field(1.0, ge=0.5, le=4.0)

class ExtractTextAiStep(StepBase):
    type: Literal["extract_text_ai"]
    save_as: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    provider: Literal["openai", "gemini"] = "openai"
    format: Literal["json", "text"] = "json"
    model: Optional[str] = None
    region: Optional[Dict[str, float]] = None

class ExtractScreenDataStep(StepBase):
    type: Literal["extract_screen_data"]
    save_as: str = Field(min_length=1)
    output_schema: Optional[Dict[str, Any]] = Field(None, alias="schema")
    strategy: Literal["auto", "hierarchy", "ocr", "ai"] = "auto"
    language: str = "eng"
    model_config = {"populate_by_name": True}

class SaveExtractionStep(StepBase):
    type: Literal["save_extraction"]
    data_var: str = Field(min_length=1)
    collection: str = "default"
    platform: Optional[str] = None
    content_type: Optional[str] = None
    dedupe_field: Optional[str] = None
    tags: Optional[TagsOrStr] = None
    # Hierarchy linking
    # parent_id_var: ctx variable that holds the parent item's content_hash
    #   (set automatically by executor after extract(fb_posts) as "_first_new_post_hash")
    # item_level: 0=post (default), 1=comment, 2=reply
    parent_id_var: Optional[str] = None
    item_level: int = Field(0, ge=0, le=2)


# ---------------------------------------------------------------------------
# Discriminated union of all step types
# ---------------------------------------------------------------------------

from pydantic import Discriminator, Tag

def _step_discriminator(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("type", "")
    return getattr(v, "type", "")

StepModel = Annotated[
    Union[
        Annotated[LaunchAppStep, Tag("launch_app")],
        Annotated[StopAppStep, Tag("stop_app")],
        Annotated[ClearAppStep, Tag("clear_app")],
        Annotated[WaitAppStep, Tag("wait_app")],
        Annotated[PushFileStep, Tag("push_file")],
        Annotated[PullFileStep, Tag("pull_file")],
        Annotated[OpenUrlStep, Tag("open_url")],
        Annotated[InstallApkStep, Tag("install_apk")],
        Annotated[WaitStep, Tag("wait")],
        Annotated[TapStep, Tag("tap")],
        Annotated[TapRatioStep, Tag("tap_ratio")],
        Annotated[TapPositionStep, Tag("tap_position")],
        Annotated[SwipeRatioStep, Tag("swipe_ratio")],
        Annotated[TapSelectorStep, Tag("tap_selector")],
        Annotated[WaitElementStep, Tag("wait_element")],
        Annotated[AssertElementStep, Tag("assert_element")],
        Annotated[InputSelectorStep, Tag("input_selector")],
        Annotated[LongTapSelectorStep, Tag("long_tap_selector")],
        Annotated[ScrollToStep, Tag("scroll_to")],
        Annotated[InputTextStep, Tag("input_text")],
        Annotated[LoginIfNeededStep, Tag("login_if_needed")],
        Annotated[FillFormStep, Tag("fill_form")],
        Annotated[AssertAppStateStep, Tag("assert_app_state")],
        Annotated[KeyStep, Tag("key")],
        Annotated[AdbShellStep, Tag("adb_shell")],
        Annotated[ScrollDownStep, Tag("scroll_down")],
        Annotated[WaitStableStep, Tag("wait_stable")],
        Annotated[VerifyScreenStep, Tag("verify_screen")],
        Annotated[DismissPopupStep, Tag("dismiss_popup")],
        Annotated[SetVariableStep, Tag("set_variable")],
        Annotated[RepeatStep, Tag("repeat")],
        Annotated[RepeatUntilStep, Tag("repeat_until")],
        Annotated[IfElementStep, Tag("if_element")],
        Annotated[IfVariableStep, Tag("if_variable")],
        Annotated[TapFbCommentButtonStep, Tag("tap_fb_comment_button")],
        Annotated[FbTapCommentButtonStep, Tag("fb_tap_comment_button")],
        Annotated[FbFindCommentButtonStep, Tag("fb_find_comment_button")],
        Annotated[FbTapCommentTargetStep, Tag("fb_tap_comment_target")],
        Annotated[FbApplyCommentFilterStep, Tag("fb_apply_comment_filter")],
        Annotated[ContentInteractionStep, Tag("content_interaction")],
        Annotated[ConnectionRequestStep, Tag("connection_request")],
        Annotated[CommunityMembershipStep, Tag("community_membership")],
        Annotated[RandomPickStep, Tag("random_pick")],
        Annotated[LoopStep, Tag("loop")],
        Annotated[BreakIfStep, Tag("break_if")],
        Annotated[RunScenarioStep, Tag("run_scenario")],
        Annotated[UseSourcePoolStep, Tag("use_source_pool")],
        Annotated[ExtractStep, Tag("extract")],
        Annotated[ExtractTextHierarchyStep, Tag("extract_text_hierarchy")],
        Annotated[ExtractTextOcrStep, Tag("extract_text_ocr")],
        Annotated[ExtractTextAiStep, Tag("extract_text_ai")],
        Annotated[ExtractScreenDataStep, Tag("extract_screen_data")],
        Annotated[SaveExtractionStep, Tag("save_extraction")],
    ],
    Discriminator(_step_discriminator),
]

# Rebuild models that use forward ref StepModel
for _m in [RepeatStep, RepeatUntilStep, IfElementStep, IfVariableStep,
           RandomPickStep, LoopStep, RandomBranch]:
    _m.model_rebuild()


# ---------------------------------------------------------------------------
# Visual Anchor config
# ---------------------------------------------------------------------------

class VisualAnchorConfig(BaseModel):
    enabled: bool = True
    ssim_threshold: float = Field(0.75, ge=0.0, le=1.0)
    image_threshold: float = Field(0.7, ge=0.0, le=1.0)
    screen_timeout: float = Field(8.0, ge=0.1, le=60)
    screen_poll: float = Field(0.5, ge=0.1, le=10)


# ---------------------------------------------------------------------------
# Variables — typed validation for known campaign variables
# ---------------------------------------------------------------------------

class ScenarioVariables(BaseModel):
    """
    Validates known scenario/campaign variables with correct types.

    Unknown variables are allowed (extra="allow") since users can define
    custom variables freely. Only listed fields enforce type constraints.
    """
    model_config = {"extra": "allow"}

    # ── Timing ──
    DURATION_MINUTES: Optional[float] = Field(None, ge=0.1, le=1440)
    SCROLL_PAUSE_SECONDS: Optional[float] = Field(None, ge=0, le=60)
    WAIT_SECONDS: Optional[float] = Field(None, ge=0, le=300)
    DELAY_BETWEEN_ACTIONS: Optional[float] = Field(None, ge=0, le=60)

    # ── Probability (0.0 – 1.0) ──
    LIKE_PROBABILITY: Optional[float] = Field(None, ge=0.0, le=1.0)
    COMMENT_PROBABILITY: Optional[float] = Field(None, ge=0.0, le=1.0)
    SHARE_PROBABILITY: Optional[float] = Field(None, ge=0.0, le=1.0)
    FOLLOW_PROBABILITY: Optional[float] = Field(None, ge=0.0, le=1.0)

    # ── Counts ──
    MAX_POSTS: Optional[int] = Field(None, ge=1, le=10000)
    MAX_SCROLLS: Optional[int] = Field(None, ge=1, le=10000)
    MAX_COMMENTS: Optional[int] = Field(None, ge=0, le=1000)
    MAX_LIKES: Optional[int] = Field(None, ge=0, le=10000)
    SCROLL_COUNT: Optional[int] = Field(None, ge=1, le=10000)
    REPEAT_COUNT: Optional[int] = Field(None, ge=1, le=10000)

    # ── Text content ──
    SEARCH_KEYWORD: Optional[str] = None
    COMMENT_TEXT: Optional[Union[str, List[str]]] = None
    TARGET_USERNAME: Optional[str] = None
    TARGET_URL: Optional[str] = None

    # ── Platform / app ──
    APP_PACKAGE: Optional[str] = None
    PLATFORM: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level scenario model
# ---------------------------------------------------------------------------

class ScenarioModel(BaseModel):
    """
    Full scenario JSON validator.

    Validates:
      - steps: array of typed step objects (recursive for repeat/if/loop)
      - variables: type-check known variables (DURATION_MINUTES, LIKE_PROBABILITY, etc.)
      - implicit_wait: global retry config
      - visual_anchor: visual anchoring config
    """
    model_config = {"extra": "allow"}

    instructions: str = ""
    steps: List[StepModel] = Field(min_length=1)
    variables: Optional[ScenarioVariables] = None
    implicit_wait: Optional[ImplicitWait] = None
    visual_anchor: Optional[Union[bool, VisualAnchorConfig]] = None
    capture_steps: bool = False

    @classmethod
    def validate_dict(cls, data: Dict[str, Any]) -> List[str]:
        """
        Validate a raw scenario dict. Returns list of error strings (empty = valid).

        This is the main entry point — replaces the old validate_scenario() function.
        Catches all Pydantic ValidationErrors and returns human-readable messages.
        """
        from pydantic import ValidationError
        errors: List[str] = []

        # ── Validate steps ──
        try:
            cls.model_validate(data)
        except ValidationError as exc:
            for e in exc.errors():
                loc = " → ".join(str(x) for x in e["loc"])
                errors.append(f"{loc}: {e['msg']}")

        return errors
