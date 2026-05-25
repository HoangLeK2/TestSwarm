/** Scenario step types — match device_farm/tasks/scenario_task.py */

export type SelectorBy =
  | 'resource-id'
  | 'text'
  | 'xpath'
  | 'class name'
  | 'content-desc'
  | 'description'
  | 'descriptionContains'
  | 'descriptionStartsWith';

/** Extra AND conditions (uiautomator2 selector fields). */
export type SelectorConditions = {
  className?: string;
  resourceId?: string;
  textContains?: string;
  clickable?: boolean;
  enabled?: boolean;
  instance?: number;
  index?: number;
  [key: string]: string | number | boolean | undefined;
};

export type ChainOp = 'child' | 'sibling' | 'relative' | 'child_by_text' | 'child_by_description';

export type ChainStep = {
  op: ChainOp;
  target?: { by?: SelectorBy; value?: string; conditions?: SelectorConditions; className?: string };
  direction?: 'left' | 'right' | 'up' | 'down';
  text?: string;
  description?: string;
  allow_scroll_search?: boolean;
};

/** Canonical nested selector for tap_selector, wait_element, etc. */
export type ScenarioSelector = {
  by: SelectorBy;
  value: string;
  conditions?: SelectorConditions;
  instance?: number;
  index?: number;
  xpath?: string;
  chain?: ChainStep;
  bounds?: number[];
};

export type SelectorFallback = { rx: number; ry: number };

/** Screen context captured at record time. Executor uses to verify correct screen. */
export type ScreenContext = {
  package?: string;
  hash?: string;          // FNV-1a of normalized XML
  texts?: string[];       // top visible texts (signature for fuzzy match)
  screenshot?: string;    // base64 JPEG — full screen at record time (visual anchoring)
  element_image?: string; // base64 JPEG — cropped element (template matching fallback)
};

/**
 * New unified tap step (recorded by control-record-view).
 * Replaces flat tap_selector + tap_ratio with nested selector/fallback/screen.
 * Executor: try selector → fallback ratio → verify screen signature.
 */
export type TapStep = {
  type: 'tap';
  selector?: ScenarioSelector;
  fallback?: SelectorFallback;
  screen?: ScreenContext;
  timeout?: number;
};

export type ScenarioStep =
  | {
      type: 'launch_app';
      package: string;
      wait_after?: number;
      activity?: string;
      component?: string;
      stop_before?: boolean;
      use_monkey?: boolean;
    }
  | { type: 'stop_app'; package: string }
  | { type: 'clear_app'; package: string }
  | { type: 'wait_app'; package: string; timeout?: number; front?: boolean }
  | { type: 'push_file'; local_path: string; remote_path: string; mode?: number }
  | { type: 'pull_file'; local_path: string; remote_path: string }
  | { type: 'open_url'; url: string; package?: string }
  | { type: 'wait'; seconds: number }
  | { type: 'tap_ratio'; x: number; y: number }
  | { type: 'tap_position'; pos: 'top_left' | 'top_center' | 'top_right' | 'middle_left' | 'middle_center' | 'middle_right' | 'bottom_left' | 'bottom_center' | 'bottom_right' | 'search_bar' }
  | { type: 'swipe_ratio'; x1: number; y1: number; x2: number; y2: number; duration_ms?: number }
  | TapStep
  | {
      type: 'tap_selector';
      selector?: ScenarioSelector;
      by?: SelectorBy;
      value?: string;
      fallback?: SelectorFallback;
      fallback_rx?: number;
      fallback_ry?: number;
      timeout?: number;
    }
  | {
      type: 'wait_element';
      selector?: ScenarioSelector;
      by?: SelectorBy;
      value?: string;
      timeout?: number;
      poll?: number;
    }
  | {
      type: 'assert_element';
      selector?: ScenarioSelector;
      by?: SelectorBy;
      value?: string;
      timeout?: number;
      poll?: number;
    }
  | {
      type: 'input_selector';
      selector?: ScenarioSelector;
      by?: SelectorBy;
      value?: string;
      text: string;
      clear_first?: boolean;
    }
  | {
      type: 'long_tap_selector';
      selector?: ScenarioSelector;
      by?: SelectorBy;
      value?: string;
      duration_ms?: number;
    }
  | {
      type: 'scroll_to';
      selector?: ScenarioSelector;
      by?: SelectorBy;
      value?: string;
      direction?: 'down' | 'up';
      max_swipes?: number;
    }
  | { type: 'input_text'; text: string; via: 'u2' | 'a11y_key' }
  | { type: 'key'; key: string }
  | {
      type: 'scroll_down';
      repeats: number;
      start_x_ratio?: number | string;
      start_y_ratio?: number;
      end_y_ratio?: number;
      duration_ms?: number;
      pause_seconds?: number;
    }
  | { type: 'verify_screen'; screenshot: string; ssim_threshold?: number; timeout?: number; poll?: number }
  | { type: 'double_tap'; rx?: number; ry?: number; x?: number; y?: number; wait_after?: number }
  | { type: 'drag'; rx1?: number; ry1?: number; rx2?: number; ry2?: number; x1?: number; y1?: number; x2?: number; y2?: number; duration_ms?: number }
  | { type: 'pinch'; scale: number; cx?: number; cy?: number; rx?: number; ry?: number; duration_ms?: number }
  | { type: 'take_screenshot'; save_path?: string }
  | { type: 'set_clipboard'; text: string }
  | { type: 'if'; condition: Record<string, unknown>; then?: ScenarioStep[]; else?: ScenarioStep[] }
  | { type: 'break_if'; condition: Record<string, unknown> }
  | { type: 'set_var'; key: string; value: unknown }
  | { type: 'extract_text_hierarchy'; save_as?: string; format?: string; filter_class?: string; exclude_empty?: boolean }
  | { type: 'extract_text_ocr'; save_as?: string; language?: string; region?: Record<string, unknown>; psm?: number; preprocess?: boolean; scale_factor?: number }
  | { type: 'extract_text_ai'; save_as?: string; prompt?: string; provider?: string; format?: string; model?: string; region?: Record<string, unknown> }
  | { type: 'extract_screen_data'; save_as?: string; strategy?: string; schema?: Record<string, unknown> };

export function scenarioToJson(steps: ScenarioStep[]): string {
  return JSON.stringify({ steps }, null, 2);
}
