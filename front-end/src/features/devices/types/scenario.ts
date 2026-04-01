/** Scenario step types — match device_farm/tasks/scenario_task.py */

export type SelectorBy =
  | 'resource-id'
  | 'text'
  | 'xpath'
  | 'class name'
  | 'description'
  | 'descriptionContains'
  | 'descriptionStartsWith';

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
  selector?: { by: SelectorBy; value: string };
  fallback?: { rx: number; ry: number };
  screen?: ScreenContext;
  timeout?: number;
};

export type ScenarioStep =
  | { type: 'launch_app'; package: string; wait_after?: number }
  | { type: 'open_url'; url: string }
  | { type: 'wait'; seconds: number }
  | { type: 'tap_ratio'; x: number; y: number }
  | { type: 'tap_position'; pos: 'top_center' | 'middle_center' | 'bottom_center' }
  | { type: 'swipe_ratio'; x1: number; y1: number; x2: number; y2: number; duration_ms?: number }
  | TapStep
  | { type: 'tap_selector'; by: SelectorBy; value: string; fallback_rx?: number; fallback_ry?: number; timeout?: number }
  | { type: 'wait_element'; by: SelectorBy; value: string; timeout?: number }
  | { type: 'assert_element'; by: SelectorBy; value: string; timeout?: number }
  | { type: 'input_selector'; by: SelectorBy; value: string; text: string; clear_first?: boolean }
  | { type: 'long_tap_selector'; by: SelectorBy; value: string; duration_ms?: number }
  | { type: 'scroll_to'; by: SelectorBy; value: string; direction?: 'down' | 'up'; max_swipes?: number }
  | { type: 'input_text'; text: string; via: 'u2' | 'a11y_key' }
  | { type: 'key'; key: string }
  | { type: 'scroll_down'; repeats: number }
  | { type: 'verify_screen'; screenshot: string; ssim_threshold?: number; timeout?: number; poll?: number }
  | { type: 'double_tap'; rx?: number; ry?: number; x?: number; y?: number; wait_after?: number }
  | { type: 'drag'; rx1?: number; ry1?: number; rx2?: number; ry2?: number; x1?: number; y1?: number; x2?: number; y2?: number; duration_ms?: number }
  | { type: 'pinch'; scale: number; cx?: number; cy?: number; rx?: number; ry?: number; duration_ms?: number }
  | { type: 'take_screenshot'; save_path?: string }
  | { type: 'set_clipboard'; text: string };

export function scenarioToJson(steps: ScenarioStep[]): string {
  return JSON.stringify({ steps }, null, 2);
}
