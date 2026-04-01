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
# Shared types
# ---------------------------------------------------------------------------

SelectorBy = Literal["resource-id", "text", "xpath", "class name",
                      "description", "descriptionContains", "descriptionStartsWith",
                      "content-desc"]

# Fields that support ${VAR} interpolation at runtime use these types.
# A plain string is accepted (e.g. "${SCROLL_COUNT}"); bounds are only
# enforced for literal numbers.
NumOrVar = Union[float, str]   # float fields (seconds, timeout, …)
IntOrVar = Union[int, str]     # int fields (count, repeats, …)
TagsOrStr = Union[List[str], str]  # tags: list OR comma-separated string


class StepBase(BaseModel):
  
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
# Selector sub-model (for tap step)
# ---------------------------------------------------------------------------

class TapSelector(BaseModel):
    by: SelectorBy
    value: str = Field(min_length=1)

class TapFallback(BaseModel):
    rx: float = Field(ge=0.0, le=1.0)
    ry: float = Field(ge=0.0, le=1.0)

# ---------------------------------------------------------------------------
# Condition sub-models (for control flow steps)
# ---------------------------------------------------------------------------

class ElementCondition(BaseModel):
    by: SelectorBy = "text"
    value: str = Field(min_length=1)

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

class WaitStep(StepBase):
    type: Literal["wait"]
    seconds: NumOrVar = 1.0

class TapStep(StepBase):
    type: Literal["tap"]
    selector: Optional[TapSelector] = None
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
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    fallback_rx: Optional[float] = Field(None, ge=0.0, le=1.0)
    fallback_ry: Optional[float] = Field(None, ge=0.0, le=1.0)
    timeout: float = Field(8.0, ge=0.1, le=60)
    implicit_wait: Optional[ImplicitWait] = None
    element_image: Optional[str] = None  # base64 for visual anchoring

class WaitElementStep(StepBase):
    type: Literal["wait_element"]
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    timeout: float = Field(10.0, ge=0.1, le=120)
    poll: float = Field(0.5, ge=0.1, le=10)

class AssertElementStep(StepBase):
    type: Literal["assert_element"]
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    timeout: float = Field(5.0, ge=0.1, le=60)
    poll: float = Field(0.5, ge=0.1, le=10)

class InputSelectorStep(StepBase):
    type: Literal["input_selector"]
    by: SelectorBy = "resource-id"
    value: str = Field(min_length=1)
    text: str
    clear_first: bool = True
    implicit_wait: Optional[ImplicitWait] = None

class LongTapSelectorStep(StepBase):
    type: Literal["long_tap_selector"]
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    duration_ms: int = Field(800, ge=100, le=10000)
    implicit_wait: Optional[ImplicitWait] = None

class ScrollToStep(StepBase):
    type: Literal["scroll_to"]
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    direction: Literal["down", "up"] = "down"
    max_swipes: int = Field(5, ge=1, le=50)

class InputTextStep(StepBase):
    type: Literal["input_text"]
    text: str
    via: Literal["u2", "a11y_key"] = "u2"

class KeyStep(StepBase):
    type: Literal["key"]
    key: str = Field(min_length=1)

class ScrollDownStep(StepBase):
    type: Literal["scroll_down"]
    repeats: IntOrVar = 1
    start_y_ratio: float = Field(0.72, ge=0.0, le=1.0)
    end_y_ratio: float = Field(0.38, ge=0.0, le=1.0)
    duration_ms: int = Field(520, ge=50, le=5000)
    pause_seconds: float = Field(0.6, ge=0, le=10)

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
    by: SelectorBy = "text"
    value: str = Field(min_length=1)
    then: List[StepModel] = Field(min_length=1)
    timeout: float = Field(3.0, ge=0.1, le=60)
    # pydantic: "else" is a reserved word → alias
    else_steps: Optional[List[StepModel]] = Field(None, alias="else")

class IfVariableStep(StepBase):
    type: Literal["if_variable"]
    name: str = Field(min_length=1)
    then: List[StepModel] = Field(min_length=1)
    equals: Optional[Any] = None
    not_equals: Optional[Any] = None
    contains: Optional[str] = None
    greater_than: Optional[float] = None
    else_steps: Optional[List[StepModel]] = Field(None, alias="else")

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

# ── Extraction steps ──

class ExtractStep(StepBase):
    type: Literal["extract"]
    strategy: Literal["fb_posts", "text_nodes"]
    stop_if_no_new: bool = False
    no_new_threshold: int = Field(3, ge=1, le=50)
    expand_see_more: bool = True

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
        Annotated[OpenUrlStep, Tag("open_url")],
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
        Annotated[KeyStep, Tag("key")],
        Annotated[ScrollDownStep, Tag("scroll_down")],
        Annotated[WaitStableStep, Tag("wait_stable")],
        Annotated[VerifyScreenStep, Tag("verify_screen")],
        Annotated[DismissPopupStep, Tag("dismiss_popup")],
        Annotated[SetVariableStep, Tag("set_variable")],
        Annotated[RepeatStep, Tag("repeat")],
        Annotated[RepeatUntilStep, Tag("repeat_until")],
        Annotated[IfElementStep, Tag("if_element")],
        Annotated[IfVariableStep, Tag("if_variable")],
        Annotated[RandomPickStep, Tag("random_pick")],
        Annotated[LoopStep, Tag("loop")],
        Annotated[BreakIfStep, Tag("break_if")],
        Annotated[RunScenarioStep, Tag("run_scenario")],
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
