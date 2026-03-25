/** Scenario step types — match device_farm/tasks/scenario_task.py */

export type SelectorBy = 'resource-id' | 'text' | 'xpath' | 'class name';

/** Screen context captured at record time. Executor uses to verify correct screen. */
export type ScreenContext = {
  package?: string;
  hash?: string;          // FNV-1a of normalized XML
  texts?: string[];       // top visible texts (signature for fuzzy match)
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
  | { type: 'scroll_down'; repeats: number };

export function scenarioToJson(steps: ScenarioStep[]): string {
  return JSON.stringify({ steps }, null, 2);
}
