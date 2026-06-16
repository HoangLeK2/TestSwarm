import { nanoid } from 'nanoid';
import { generateKeyBetween } from 'fractional-indexing';
import {
  type LucideIcon,
  Repeat,
  Repeat1,
  RefreshCw,
  Search,
  Save,
  GitBranch,
  Dices,
  Package,
  Smartphone,
  Globe,
  Hourglass,
  MousePointerClick,
  MoveRight,
  Keyboard,
  Terminal,
  ArrowDownToLine,
  Hand,
  XCircle,
  Variable,
  Timer,
  Scan,
  ZoomIn,
  HandMetal,
  Camera,
  Clipboard,
  Zap,
  ShieldCheck,
  SquareX,
  Eraser,
  AppWindow,
  Upload,
  Download,
  PackagePlus
} from 'lucide-react';

/** Generate a unique step ID. */
export function stepId(): string {
  return nanoid(10);
}

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
  | 'if'
  | 'break_if'
  | 'random_pick'
  | 'run_scenario'
  | 'loop'
  | 'fb_tap_comment_button'
  | 'tap_fb_comment_button';

export type ActionType =
  | 'launch_app'
  | 'stop_app'
  | 'clear_app'
  | 'wait_app'
  | 'push_file'
  | 'pull_file'
  | 'open_url'
  | 'install_apk'
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
  | 'verify_screen'
  | 'dismiss_popup'
  | 'input_text'
  | 'key'
  | 'adb_shell'
  | 'scroll_down'
  | 'set_variable'
  | 'set_var'
  | 'double_tap'
  | 'pinch'
  | 'drag'
  | 'take_screenshot'
  | 'set_clipboard'
  | 'extract'
  | 'save_extraction'
  | 'extract_text_hierarchy'
  | 'extract_text_ocr'
  | 'extract_text_ai'
  | 'extract_screen_data';

export type AnyStepType = ControlFlowType | ActionType;

/** A generic step — may contain nested `steps`, `then`, `else`, `branches`. */
export type FlowStep = {
  type: string;
  [key: string]: any;
};

export function isControlFlow(type: string): type is ControlFlowType {
  return [
    'repeat',
    'repeat_until',
    'if_element',
    'if_variable',
    'if',
    'break_if',
    'random_pick',
    'run_scenario',
    'loop',
    'fb_tap_comment_button',
    'tap_fb_comment_button'
  ].includes(type);
}

export function getStepIcon(type: string): LucideIcon {
  switch (type) {
    case 'repeat':
      return Repeat;
    case 'repeat_until':
      return Repeat1;
    case 'loop':
      return RefreshCw;
    case 'extract':
    case 'extract_text_hierarchy':
    case 'extract_text_ocr':
    case 'extract_text_ai':
    case 'extract_screen_data':
      return Search;
    case 'save_extraction':
      return Save;
    case 'if_element':
    case 'if_variable':
    case 'if':
    case 'break_if':
      return GitBranch;
    case 'random_pick':
      return Dices;
    case 'run_scenario':
      return Package;
    case 'launch_app':
      return Smartphone;
    case 'stop_app':
      return SquareX;
    case 'clear_app':
      return Eraser;
    case 'wait_app':
      return AppWindow;
    case 'push_file':
      return Upload;
    case 'pull_file':
      return Download;
    case 'open_url':
      return Globe;
    case 'install_apk':
      return PackagePlus;
    case 'wait':
      return Hourglass;
    case 'tap':
    case 'tap_ratio':
    case 'tap_position':
    case 'tap_selector':
    case 'double_tap':
      return MousePointerClick;
    case 'fb_tap_comment_button':
    case 'tap_fb_comment_button':
      return GitBranch;
    case 'swipe_ratio':
      return MoveRight;
    case 'input_text':
    case 'input_selector':
    case 'key':
    case 'key_back':
      return Keyboard;
    case 'adb_shell':
      return Terminal;
    case 'wait_element':
    case 'assert_element':
      return Scan;
    case 'scroll_down':
    case 'scroll_to':
      return ArrowDownToLine;
    case 'long_tap_selector':
      return Hand;
    case 'dismiss_popup':
      return XCircle;
    case 'set_variable':
    case 'set_var':
      return Variable;
    case 'wait_stable':
      return Timer;
    case 'verify_screen':
      return ShieldCheck;
    case 'pinch':
      return ZoomIn;
    case 'drag':
      return HandMetal;
    case 'take_screenshot':
      return Camera;
    case 'set_clipboard':
      return Clipboard;
    default:
      return Zap;
  }
}

export function getStepLabel(step: FlowStep): string {
  switch (step.type) {
    case 'repeat':
      return `repeat ×${step.count ?? '?'}`;
    case 'repeat_until':
      return `repeat_until (max ${step.max_iterations ?? 100})`;
    case 'if':
      return `if (${Object.keys(step.condition ?? {}).join(', ') || '?'})`;
    case 'if_element':
      return `if_element [${step.by}="${step.value}"]`;
    case 'if_variable': {
      const op =
        step.equals != null
          ? `=="${step.equals}"`
          : step.not_equals != null
            ? `!="${step.not_equals}"`
            : step.contains != null
              ? `contains "${step.contains}"`
              : step.greater_than != null
                ? `>${step.greater_than}`
                : '?';
      return `if ${step.name} ${op}`;
    }
    case 'break_if':
      return `break_if (${Object.keys(step.condition ?? {}).join(', ') || '?'})`;
    case 'random_pick':
      return `random_pick (${step.branches?.length ?? 0} branches)`;
    case 'run_scenario':
      return `run_scenario "${step.scenario_name || step.scenario_id || '?'}"`;
    case 'loop':
      return `loop ×${step.count ?? '?'}`;
    case 'extract': {
      const label = `extract [${step.strategy ?? 'fb_posts'}]`;
      return step.collection ? `${label} → ${step.collection}` : label;
    }
    case 'save_extraction':
      return `save_extraction → ${step.collection ?? 'default'}`;

    case 'launch_app':
      return `launch_app ${step.package || ''}`;
    case 'stop_app':
      return `stop_app ${step.package || ''}`;
    case 'clear_app':
      return `clear_app ${step.package || ''}`;
    case 'wait_app':
      return `wait_app ${step.package || ''}`;
    case 'push_file':
      return `push ${step.local_path || ''} → ${step.remote_path || ''}`;
    case 'pull_file':
      return `pull ${step.remote_path || ''} → ${step.local_path || ''}`;
    case 'open_url':
      return `open_url ${step.url || ''}`;
    case 'install_apk':
      return `install_apk ${step.url || ''}`;
    case 'wait':
      return `wait ${step.seconds ?? 0}s`;
    case 'tap_ratio':
      return `tap (${step.x}, ${step.y})`;
    case 'tap_selector':
      return `tap [${step.by}="${step.value}"]`;
    case 'fb_tap_comment_button':
    case 'tap_fb_comment_button': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      return `Bấm Bình luận (OK: ${thenN} bước${elseN ? `, Không thấy: ${elseN} bước` : ''})`;
    }
    case 'input_selector':
      return `input [${step.by}="${step.value}"] "${step.text}"`;
    case 'input_text':
      return `input_text "${step.text}"`;
    case 'adb_shell':
      return `adb shell ${step.command || step.cmd || ''}`;
    case 'set_variable':
      return `set ${step.name}=${(step.value ?? step.from_list) ? 'list' : '?'}`;
    case 'set_var':
      return `set_var ${step.key ?? '?'}=${JSON.stringify(step.value ?? '')}`;
    case 'scroll_down': {
      const x = step.start_x_ratio != null ? ` x@${step.start_x_ratio}` : '';
      return `scroll_down ×${step.repeats ?? 1}${x}`;
    }
    case 'extract_text_hierarchy':
      return `extract_text_hierarchy → ${step.save_as ?? 'texts'}`;
    case 'extract_text_ocr':
      return `extract_text_ocr → ${step.save_as ?? 'ocr_text'}`;
    case 'extract_text_ai':
      return `extract_text_ai → ${step.save_as ?? 'ai_text'}`;
    case 'extract_screen_data':
      return `extract_screen_data → ${step.save_as ?? 'screen_data'}`;
    default:
      return step.type;
  }
}

/** All step types for the dropdown. */
export const ALL_STEP_TYPES: {
  value: string;
  label: string;
  group: 'action' | 'control' | 'variable';
}[] = [
  { value: 'launch_app', label: 'launch_app', group: 'action' },
  { value: 'stop_app', label: 'stop_app', group: 'action' },
  { value: 'clear_app', label: 'clear_app', group: 'action' },
  { value: 'wait_app', label: 'wait_app', group: 'action' },
  { value: 'push_file', label: 'push_file', group: 'action' },
  { value: 'pull_file', label: 'pull_file', group: 'action' },
  { value: 'open_url', label: 'open_url', group: 'action' },
  { value: 'install_apk', label: 'install_apk', group: 'action' },
  { value: 'wait', label: 'wait', group: 'action' },
  { value: 'tap_ratio', label: 'tap_ratio', group: 'action' },
  { value: 'tap_selector', label: 'tap_selector', group: 'action' },
  {
    value: 'fb_tap_comment_button',
    label: 'Bấm nút Bình luận (FB) — có nhánh OK / Không thấy',
    group: 'control'
  },
  { value: 'tap_position', label: 'tap_position', group: 'action' },
  { value: 'swipe_ratio', label: 'swipe_ratio', group: 'action' },
  { value: 'input_text', label: 'input_text', group: 'action' },
  { value: 'input_selector', label: 'input_selector', group: 'action' },
  { value: 'adb_shell', label: 'adb_shell', group: 'action' },
  { value: 'wait_element', label: 'wait_element', group: 'action' },
  { value: 'assert_element', label: 'assert_element', group: 'action' },
  { value: 'long_tap_selector', label: 'long_tap_selector', group: 'action' },
  { value: 'scroll_down', label: 'scroll_down', group: 'action' },
  { value: 'scroll_to', label: 'scroll_to', group: 'action' },
  { value: 'wait_stable', label: 'wait_stable', group: 'action' },
  { value: 'verify_screen', label: 'verify_screen', group: 'action' },
  { value: 'dismiss_popup', label: 'dismiss_popup', group: 'action' },
  { value: 'key', label: 'key', group: 'action' },
  { value: 'double_tap', label: 'double_tap', group: 'action' },
  { value: 'pinch', label: 'pinch', group: 'action' },
  { value: 'drag', label: 'drag', group: 'action' },
  { value: 'take_screenshot', label: 'take_screenshot', group: 'action' },
  { value: 'set_clipboard', label: 'set_clipboard', group: 'action' },
  { value: 'extract', label: 'extract', group: 'action' },
  { value: 'save_extraction', label: 'save_extraction', group: 'action' },
  {
    value: 'extract_text_hierarchy',
    label: 'extract_text_hierarchy',
    group: 'action'
  },
  { value: 'extract_text_ocr', label: 'extract_text_ocr', group: 'action' },
  { value: 'extract_text_ai', label: 'extract_text_ai', group: 'action' },
  {
    value: 'extract_screen_data',
    label: 'extract_screen_data',
    group: 'action'
  },
  { value: 'set_variable', label: 'set_variable', group: 'variable' },
  { value: 'set_var', label: 'set_var', group: 'variable' },
  { value: 'loop', label: 'loop', group: 'control' },
  { value: 'repeat', label: 'repeat', group: 'control' },
  { value: 'repeat_until', label: 'repeat_until', group: 'control' },
  { value: 'if', label: 'if', group: 'control' },
  { value: 'break_if', label: 'break_if', group: 'control' },
  { value: 'if_element', label: 'if_element', group: 'control' },
  { value: 'if_variable', label: 'if_variable', group: 'control' },
  { value: 'random_pick', label: 'random_pick', group: 'control' },
  { value: 'run_scenario', label: 'run_scenario', group: 'control' }
];

/** Create a default step for a given type (with auto-generated id + order). */
export function createDefaultFbCommentThenSteps(): FlowStep[] {
  const waitForSheet = createDefaultStep('wait');
  const backFromSheet = createDefaultStep('key');
  const waitAfterBack = createDefaultStep('wait');
  const dismissPopup = createDefaultStep('dismiss_popup');
  return [
    { ...waitForSheet, seconds: 0.6 },
    createDefaultStep('extract_fb_comments'),
    { ...backFromSheet, key: 'back' },
    { ...waitAfterBack, seconds: 1 },
    { ...dismissPopup, retries: 1 }
  ];
}

export function createDefaultStep(
  type: string,
  afterOrder?: string | null,
  beforeOrder?: string | null
): FlowStep {
  const base = {
    id: stepId(),
    order: orderBetween(afterOrder ?? null, beforeOrder ?? null)
  };
  switch (type) {
    case 'repeat':
      return { ...base, type: 'repeat', count: 3, delay_between: 0, steps: [] };
    case 'repeat_until':
      return {
        ...base,
        type: 'repeat_until',
        condition: { element_exists: { by: 'text', value: '' } },
        max_iterations: 50,
        steps: []
      };
    case 'if':
      return {
        ...base,
        type: 'if',
        condition: { element_exists: { by: 'text', value: '' } },
        then: [],
        else: []
      };
    case 'break_if':
      return {
        ...base,
        type: 'break_if',
        condition: { element_exists: { by: 'text', value: '' } }
      };
    case 'if_element':
      return {
        ...base,
        type: 'if_element',
        selector: { by: 'text', value: '' },
        by: 'text',
        value: '',
        timeout: 3,
        then: [],
        else: []
      };
    case 'if_variable':
      return {
        ...base,
        type: 'if_variable',
        name: '',
        equals: '',
        then: [],
        else: []
      };
    case 'random_pick':
      return {
        ...base,
        type: 'random_pick',
        branches: [{ weight: 1, steps: [] }]
      };
    case 'run_scenario':
      return {
        ...base,
        type: 'run_scenario',
        scenario_name: '',
        variables: {}
      };
    case 'launch_app':
      return {
        ...base,
        type: 'launch_app',
        package: '',
        wait_after: 2,
        stop_before: false,
        use_monkey: false
      };
    case 'stop_app':
      return { ...base, type: 'stop_app', package: '' };
    case 'clear_app':
      return { ...base, type: 'clear_app', package: '' };
    case 'wait_app':
      return {
        ...base,
        type: 'wait_app',
        package: '',
        timeout: 20,
        front: true
      };
    case 'push_file':
      return {
        ...base,
        type: 'push_file',
        local_path: '',
        remote_path: '/sdcard/'
      };
    case 'pull_file':
      return {
        ...base,
        type: 'pull_file',
        local_path: '',
        remote_path: '/sdcard/'
      };
    case 'open_url':
      return { ...base, type: 'open_url', url: '' };
    case 'install_apk':
      return { ...base, type: 'install_apk', url: '', timeout: 90 };
    case 'wait':
      return { ...base, type: 'wait', seconds: 1 };
    case 'tap_ratio':
      return { ...base, type: 'tap_ratio', x: 0.5, y: 0.5 };
    case 'tap_selector':
      return {
        ...base,
        type: 'tap_selector',
        selector: { by: 'text', value: '' },
        by: 'text',
        value: '',
        timeout: 8,
        fallback: { rx: 0.5, ry: 0.5 },
        fallback_rx: 0.5,
        fallback_ry: 0.5
      };
    case 'fb_tap_comment_button':
    case 'tap_fb_comment_button':
      return {
        ...base,
        type,
        timeout: 6,
        poll: 0.4,
        dedupe_field: 'post_key',
        comment_filter: 'all_comments',
        switch_to_all_comments: true,
        post_tap_wait_s: 0.8,
        ignore_error: true,
        pre_scroll: false,
        pre_scroll_distance: 0.24,
        then: createDefaultFbCommentThenSteps(),
        else: []
      };
    case 'tap_position':
      return { ...base, type: 'tap_position', pos: 'middle_center' };
    case 'swipe_ratio':
      return {
        ...base,
        type: 'swipe_ratio',
        x1: 0.5,
        y1: 0.8,
        x2: 0.5,
        y2: 0.2,
        duration_ms: 300
      };
    case 'input_text':
      return { ...base, type: 'input_text', via: 'u2', text: '' };
    case 'adb_shell':
      return {
        ...base,
        type: 'adb_shell',
        command: '',
        timeout: 30,
        fail_on_error: true,
        max_output_chars: 8000
      };
    case 'input_selector':
      return {
        ...base,
        type: 'input_selector',
        selector: { by: 'resource-id', value: '' },
        by: 'resource-id',
        value: '',
        text: '',
        clear_first: true
      };
    case 'wait_element':
      return {
        ...base,
        type: 'wait_element',
        selector: { by: 'text', value: '' },
        by: 'text',
        value: '',
        timeout: 10,
        poll: 0.5
      };
    case 'assert_element':
      return {
        ...base,
        type: 'assert_element',
        selector: { by: 'text', value: '' },
        by: 'text',
        value: '',
        timeout: 5,
        poll: 0.5
      };
    case 'long_tap_selector':
      return {
        ...base,
        type: 'long_tap_selector',
        selector: { by: 'text', value: '' },
        by: 'text',
        value: '',
        duration_ms: 800
      };
    case 'scroll_down':
      return {
        ...base,
        type: 'scroll_down',
        repeats: 1,
        start_x_ratio: 0.5,
        start_y_ratio: 0.65,
        end_y_ratio: 0.47,
        duration_ms: 520,
        pause_seconds: 0.6
      };
    case 'scroll_to':
      return {
        ...base,
        type: 'scroll_to',
        selector: { by: 'text', value: '' },
        by: 'text',
        value: '',
        direction: 'down',
        max_swipes: 5
      };
    case 'wait_stable':
      return { ...base, type: 'wait_stable', timeout: 5, stable_duration: 0.4 };
    case 'verify_screen':
      return {
        ...base,
        type: 'verify_screen',
        screenshot: '',
        ssim_threshold: 0.75,
        timeout: 8,
        poll: 0.5
      };
    case 'dismiss_popup':
      return { ...base, type: 'dismiss_popup', retries: 3 };
    case 'key':
      return { ...base, type: 'key', key: 'enter' };
    /** Insert-menu alias → Android BACK (same engine step as `key`). */
    case 'key_back':
      return { ...base, type: 'key', key: 'back' };
    case 'double_tap':
      return { ...base, type: 'double_tap', rx: 0.5, ry: 0.5 };
    case 'pinch':
      return { ...base, type: 'pinch', scale: 0.5, rx: 0.5, ry: 0.5 };
    case 'drag':
      return {
        ...base,
        type: 'drag',
        rx1: 0.5,
        ry1: 0.3,
        rx2: 0.5,
        ry2: 0.7,
        duration_ms: 1000
      };
    case 'take_screenshot':
      return { ...base, type: 'take_screenshot' };
    case 'set_clipboard':
      return { ...base, type: 'set_clipboard', text: '' };
    case 'set_variable':
      return { ...base, type: 'set_variable', name: '', value: '' };
    case 'set_var':
      return { ...base, type: 'set_var', key: '', value: '' };
    case 'loop':
      return { ...base, type: 'loop', count: '10', steps: [] };
    case 'extract':
      return {
        ...base,
        type: 'extract',
        strategy: 'fb_posts',
        edge_extra_data: true,
        strategy_version: 'fb_posts:v1',
        expand_see_more: true,
        expand_see_more_max_passes: 4,
        expand_see_more_scroll: true,
        expand_see_more_scroll_distance: 0.25,
        expand_completion_retries: 4,
        extract_profile: 'balanced',
        open_post_before_extract: true,
        open_post_press_back_after_extract: false,
        max_items: 50,
        stop_if_no_new: true,
        no_new_threshold: 30,
        collection: '${SAVE_COLLECTION}',
        platform: 'facebook',
        content_type: 'fb_post',
        dedupe_field: 'post_key'
      };
    // Shortcut — creates an `extract` step preset for FB comments. Mirrors what
    // fb_group_1h templates use inside `fb_tap_comment_button.then`. User can
    // still tweak any field in the detail panel afterwards.
    case 'extract_fb_comments':
      return {
        ...base,
        type: 'extract',
        strategy: 'fb_comments',
        edge_extra_data: true,
        strategy_version: 'fb_comments:v1',
        parent_post_id_var: '_fb_comment_parent_pid',
        max_items: 500,
        comment_scroll_passes: 40,
        comment_swipes_per_dump: 6,
        comment_scroll_distance: 0.52,
        comment_scroll_duration_ms: 120,
        comment_scroll_pause_s: 0.03,
        comment_no_growth_break: 2,
        min_comment_scan_passes: 1,
        stop_if_no_new: false,
        no_new_threshold: 3,
        collection: '${SAVE_COLLECTION}',
        platform: 'facebook',
        content_type: 'fb_comment',
        dedupe_field: 'comment_key',
        tags: 'group,comment,${GROUP_NAME}',
        save_parent_id_var: '_active_comment_parent_hash',
        item_level: 1
      };
    // Shortcut — creates an `extract` step preset for FB posts (group feed).
    case 'extract_fb_posts':
      return {
        ...base,
        type: 'extract',
        strategy: 'fb_posts',
        edge_extra_data: true,
        strategy_version: 'fb_posts:v1',
        expand_see_more: true,
        expand_see_more_max_passes: 4,
        expand_see_more_scroll: true,
        expand_see_more_scroll_distance: 0.25,
        expand_completion_retries: 4,
        extract_profile: 'balanced',
        open_post_before_extract: true,
        open_post_press_back_after_extract: false,
        max_items: 50,
        stop_if_no_new: false,
        collection: '${SAVE_COLLECTION}',
        platform: 'facebook',
        content_type: 'fb_post',
        dedupe_field: 'post_key',
        tags: 'group,crawl,${GROUP_NAME}'
      };
    case 'save_extraction':
      return {
        ...base,
        type: 'save_extraction',
        data_var: 'posts',
        collection: 'default',
        platform: 'facebook',
        content_type: 'fb_post',
        dedupe_field: 'text',
        tags: '',
        item_level: 0
      };
    case 'extract_text_hierarchy':
      return {
        ...base,
        type: 'extract_text_hierarchy',
        save_as: 'texts',
        format: 'text',
        exclude_empty: true
      };
    case 'extract_text_ocr':
      return {
        ...base,
        type: 'extract_text_ocr',
        save_as: 'ocr_text',
        language: 'eng',
        psm: 11,
        preprocess: true,
        scale_factor: 2.0
      };
    case 'extract_text_ai':
      return {
        ...base,
        type: 'extract_text_ai',
        save_as: 'ai_text',
        prompt: 'Extract all visible meaningful text.',
        provider: 'openai',
        format: 'json'
      };
    case 'extract_screen_data':
      return {
        ...base,
        type: 'extract_screen_data',
        save_as: 'screen_data',
        strategy: 'auto'
      };
    default:
      return { ...base, type };
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
  order: string; // fractional index key (lexicographic)
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
  type: 'default' | 'conditional' | 'error' | 'fallback';
  condition?: string;
};

export const CONTAINER_TYPES = new Set([
  'loop',
  'repeat',
  'repeat_until',
  'if',
  'if_element',
  'if_variable',
  'fb_tap_comment_button',
  'tap_fb_comment_button',
  'random_pick'
]);

export function isContainerType(type: string): boolean {
  return CONTAINER_TYPES.has(type);
}

/** Get ordered child nodes for a given parent+branch scope. */
export function getChildNodes(
  nodes: FlowNode[],
  parentId: string,
  branch: string
): FlowNode[] {
  return nodes
    .filter((n) => n.scope?.parentId === parentId && n.scope?.branch === branch)
    .sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
}

/** Get root-level nodes (no parent scope), sorted by order. */
export function getRootNodes(nodes: FlowNode[]): FlowNode[] {
  return nodes
    .filter((n) => !n.scope?.parentId)
    .sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));
}
