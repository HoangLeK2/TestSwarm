import { nanoid } from 'nanoid';
import { generateKeyBetween } from 'fractional-indexing';

/** Generate a unique step ID. */
export function stepId(): string { return nanoid(10); }

/** Generate a fractional order key between two existing keys (or null for boundaries). */
export function orderBetween(a: string | null, b: string | null): string {
  return generateKeyBetween(a, b);
}

/** All step types supported by the scenario engine (DF-001 + DF-002 + DF-003). */
export type ControlFlowType =
  | 'repeat'
  | 'repeat_until'
  | 'if_element'
  | 'if_variable'
  | 'random_pick'
  | 'run_scenario'
  | 'loop';

export type ActionType =
  | 'launch_app'
  | 'open_url'
  | 'wait'
  | 'tap_position'
  | 'tap'
  | 'tap_ratio'
  | 'swipe_ratio'
  | 'tap_selector'
  | 'wait_element'
  | 'assert_element'
  | 'input_selector'
  | 'long_tap_selector'
  | 'scroll_to'
  | 'wait_stable'
  | 'dismiss_popup'
  | 'input_text'
  | 'key'
  | 'scroll_down'
  | 'set_variable'
  | 'double_tap'
  | 'pinch'
  | 'drag'
  | 'take_screenshot'
  | 'set_clipboard'
  | 'extract'
  | 'save_extraction';

export type AnyStepType = ControlFlowType | ActionType;

/** A generic step — may contain nested `steps`, `then`, `else`, `branches`. */
export type FlowStep = {
  type: string;
  [key: string]: any;
};

export function isControlFlow(type: string): type is ControlFlowType {
  return ['repeat', 'repeat_until', 'if_element', 'if_variable', 'random_pick', 'run_scenario', 'loop'].includes(type);
}

export function getStepIcon(type: string): string {
  switch (type) {
    case 'repeat': return '🔄';
    case 'repeat_until': return '🔁';
    case 'loop': return '🔃';
    case 'extract': return '🔎';
    case 'save_extraction': return '💾';
    case 'if_element': return '🔀';
    case 'if_variable': return '🔀';
    case 'random_pick': return '🎲';
    case 'run_scenario': return '📦';
    case 'launch_app': return '📱';
    case 'open_url': return '🌐';
    case 'wait': return '⏳';
    case 'tap': case 'tap_ratio': case 'tap_position': case 'tap_selector': return '👆';
    case 'swipe_ratio': return '👉';
    case 'input_text': case 'input_selector': return '⌨️';
    case 'wait_element': case 'assert_element': return '🔍';
    case 'scroll_down': case 'scroll_to': return '⬇️';
    case 'long_tap_selector': return '👇';
    case 'dismiss_popup': return '❌';
    case 'set_variable': return '📝';
    case 'key': return '⌨️';
    case 'wait_stable': return '⏱️';
    case 'double_tap': return '👆';
    case 'pinch': return '🤏';
    case 'drag': return '✊';
    case 'take_screenshot': return '📸';
    case 'set_clipboard': return '📋';
    default: return '⚡';
  }
}

export function getStepLabel(step: FlowStep): string {
  switch (step.type) {
    case 'repeat': return `repeat ×${step.count ?? '?'}`;
    case 'repeat_until': return `repeat_until (max ${step.max_iterations ?? 100})`;
    case 'if_element': return `if_element [${step.by}="${step.value}"]`;
    case 'if_variable': {
      const op = step.equals != null ? `=="${step.equals}"` :
        step.not_equals != null ? `!="${step.not_equals}"` :
        step.contains != null ? `contains "${step.contains}"` :
        step.greater_than != null ? `>${step.greater_than}` : '?';
      return `if ${step.name} ${op}`;
    }
    case 'random_pick': return `random_pick (${step.branches?.length ?? 0} branches)`;
    case 'run_scenario': return `run_scenario "${step.scenario_name || step.scenario_id || '?'}"`;
    case 'loop': return `loop ×${step.count ?? '?'}`;
    case 'extract': {
      const label = `extract [${step.strategy ?? 'fb_posts'}]`;
      return step.collection ? `${label} → ${step.collection}` : label;
    }
    case 'save_extraction': return `save_extraction → ${step.collection ?? 'default'}`;

    case 'launch_app': return `launch_app ${step.package || ''}`;
    case 'open_url': return `open_url ${step.url || ''}`;
    case 'wait': return `wait ${step.seconds ?? 0}s`;
    case 'tap_ratio': return `tap (${step.x}, ${step.y})`;
    case 'tap_selector': return `tap [${step.by}="${step.value}"]`;
    case 'input_selector': return `input [${step.by}="${step.value}"] "${step.text}"`;
    case 'input_text': return `input_text "${step.text}"`;
    case 'set_variable': return `set ${step.name}=${step.value ?? step.from_list ? 'list' : '?'}`;
    case 'scroll_down': {
      const x = step.start_x_ratio != null ? ` x@${step.start_x_ratio}` : '';
      return `scroll_down ×${step.repeats ?? 1}${x}`;
    }
    default: return step.type;
  }
}

/** All step types for the dropdown. */
export const ALL_STEP_TYPES: { value: string; label: string; group: 'action' | 'control' | 'variable' }[] = [
  { value: 'launch_app', label: 'launch_app', group: 'action' },
  { value: 'open_url', label: 'open_url', group: 'action' },
  { value: 'wait', label: 'wait', group: 'action' },
  { value: 'tap_ratio', label: 'tap_ratio', group: 'action' },
  { value: 'tap_selector', label: 'tap_selector', group: 'action' },
  { value: 'tap_position', label: 'tap_position', group: 'action' },
  { value: 'swipe_ratio', label: 'swipe_ratio', group: 'action' },
  { value: 'input_text', label: 'input_text', group: 'action' },
  { value: 'input_selector', label: 'input_selector', group: 'action' },
  { value: 'wait_element', label: 'wait_element', group: 'action' },
  { value: 'assert_element', label: 'assert_element', group: 'action' },
  { value: 'long_tap_selector', label: 'long_tap_selector', group: 'action' },
  { value: 'scroll_down', label: 'scroll_down', group: 'action' },
  { value: 'scroll_to', label: 'scroll_to', group: 'action' },
  { value: 'wait_stable', label: 'wait_stable', group: 'action' },
  { value: 'dismiss_popup', label: 'dismiss_popup', group: 'action' },
  { value: 'key', label: 'key', group: 'action' },
  { value: 'double_tap', label: 'double_tap', group: 'action' },
  { value: 'pinch', label: 'pinch', group: 'action' },
  { value: 'drag', label: 'drag', group: 'action' },
  { value: 'take_screenshot', label: 'take_screenshot', group: 'action' },
  { value: 'set_clipboard', label: 'set_clipboard', group: 'action' },
  { value: 'extract', label: 'extract', group: 'action' },
  { value: 'save_extraction', label: 'save_extraction', group: 'action' },
  { value: 'set_variable', label: 'set_variable', group: 'variable' },
  { value: 'loop', label: 'loop', group: 'control' },
  { value: 'repeat', label: 'repeat', group: 'control' },
  { value: 'repeat_until', label: 'repeat_until', group: 'control' },
  { value: 'if_element', label: 'if_element', group: 'control' },
  { value: 'if_variable', label: 'if_variable', group: 'control' },
  { value: 'random_pick', label: 'random_pick', group: 'control' },
  { value: 'run_scenario', label: 'run_scenario', group: 'control' },
];

/** Create a default step for a given type (with auto-generated id + order). */
export function createDefaultStep(type: string, afterOrder?: string | null, beforeOrder?: string | null): FlowStep {
  const base = { id: stepId(), order: orderBetween(afterOrder ?? null, beforeOrder ?? null) };
  switch (type) {
    case 'repeat': return { ...base, type: 'repeat', count: 3, delay_between: 0, steps: [] };
    case 'repeat_until': return { ...base, type: 'repeat_until', condition: { element_exists: { by: 'text', value: '' } }, max_iterations: 50, steps: [] };
    case 'if_element': return { ...base, type: 'if_element', by: 'text', value: '', timeout: 3, then: [], else: [] };
    case 'if_variable': return { ...base, type: 'if_variable', name: '', equals: '', then: [], else: [] };
    case 'random_pick': return { ...base, type: 'random_pick', branches: [{ weight: 1, steps: [] }] };
    case 'run_scenario': return { ...base, type: 'run_scenario', scenario_name: '', variables: {} };
    case 'launch_app': return { ...base, type: 'launch_app', package: '' };
    case 'open_url': return { ...base, type: 'open_url', url: '' };
    case 'wait': return { ...base, type: 'wait', seconds: 1 };
    case 'tap_ratio': return { ...base, type: 'tap_ratio', x: 0.5, y: 0.5 };
    case 'tap_selector': return { ...base, type: 'tap_selector', by: 'text', value: '' };
    case 'tap_position': return { ...base, type: 'tap_position', pos: 'middle_center' };
    case 'swipe_ratio': return { ...base, type: 'swipe_ratio', x1: 0.5, y1: 0.8, x2: 0.5, y2: 0.2, duration_ms: 300 };
    case 'input_text': return { ...base, type: 'input_text', via: 'u2', text: '' };
    case 'input_selector': return { ...base, type: 'input_selector', by: 'resource-id', value: '', text: '', clear_first: true };
    case 'wait_element': return { ...base, type: 'wait_element', by: 'text', value: '', timeout: 10 };
    case 'assert_element': return { ...base, type: 'assert_element', by: 'text', value: '', timeout: 5 };
    case 'long_tap_selector': return { ...base, type: 'long_tap_selector', by: 'text', value: '', duration_ms: 800 };
    case 'scroll_down': return { ...base, type: 'scroll_down', repeats: 1 };
    case 'scroll_to': return { ...base, type: 'scroll_to', by: 'text', value: '', direction: 'down', max_swipes: 5 };
    case 'wait_stable': return { ...base, type: 'wait_stable', timeout: 5, stable_duration: 0.4 };
    case 'dismiss_popup': return { ...base, type: 'dismiss_popup', retries: 3 };
    case 'key': return { ...base, type: 'key', key: 'enter' };
    case 'double_tap': return { ...base, type: 'double_tap', rx: 0.5, ry: 0.5 };
    case 'pinch': return { ...base, type: 'pinch', scale: 0.5, rx: 0.5, ry: 0.5 };
    case 'drag': return { ...base, type: 'drag', rx1: 0.5, ry1: 0.3, rx2: 0.5, ry2: 0.7, duration_ms: 1000 };
    case 'take_screenshot': return { ...base, type: 'take_screenshot' };
    case 'set_clipboard': return { ...base, type: 'set_clipboard', text: '' };
    case 'set_variable': return { ...base, type: 'set_variable', name: '', value: '' };
    case 'loop': return { ...base, type: 'loop', count: '10', steps: [] };
    case 'extract':
      return {
        ...base,
        type: 'extract',
        strategy: 'fb_posts',
        expand_see_more: true,
        expand_see_more_max_passes: 4,
        expand_see_more_scroll: true,
        expand_see_more_scroll_distance: 0.25,
        expand_completion_retries: 4,
        max_items: 50,
        stop_if_no_new: true,
        no_new_threshold: 30,
        collection: '${SAVE_COLLECTION}',
        platform: 'facebook',
        content_type: 'group_post',
        dedupe_field: 'text',
      };
    case 'save_extraction':
      return {
        ...base,
        type: 'save_extraction',
        data_var: 'posts',
        collection: 'default',
        platform: 'facebook',
        content_type: 'post',
        dedupe_field: 'text',
        tags: '',
        item_level: 0,
      };
    default: return { ...base, type };
  }
}

// ── Graph model types (node-graph refactor) ──────────────────────────────────

export type NodeScope = {
  parentId: string;
  branch: string; // "steps" | "then" | "else" | "branch_0" | ...
};

export type FlowNode = {
  id: string;
  type: string;
  config: Record<string, any>;
  order: string;          // fractional index key (lexicographic)
  scope?: NodeScope | null;
  position?: { x: number; y: number };
  title?: string;
  description?: string;
};

export type FlowEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  type: "default" | "conditional" | "error" | "fallback";
  condition?: string;
};

export const CONTAINER_TYPES = new Set([
  "loop", "repeat", "repeat_until",
  "if_element", "if_variable",
  "random_pick",
]);

export function isContainerType(type: string): boolean {
  return CONTAINER_TYPES.has(type);
}

/** Get ordered child nodes for a given parent+branch scope. */
export function getChildNodes(
  nodes: FlowNode[],
  parentId: string,
  branch: string,
): FlowNode[] {
  return nodes
    .filter(n => n.scope?.parentId === parentId && n.scope?.branch === branch)
    .sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
}

/** Get root-level nodes (no parent scope), sorted by order. */
export function getRootNodes(nodes: FlowNode[]): FlowNode[] {
  return nodes
    .filter(n => !n.scope?.parentId)
    .sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
}
