import type { FlowStep } from '../scenario-steps/types';

export const STEP_COLORS: Record<string, string> = {
  tap: 'border-l-blue-500',
  tap_ratio: 'border-l-blue-500',
  tap_position: 'border-l-blue-500',
  tap_selector: 'border-l-blue-500',
  long_tap_selector: 'border-l-blue-500',
  swipe_ratio: 'border-l-blue-500',
  input_text: 'border-l-cyan-500',
  input_selector: 'border-l-cyan-500',
  key: 'border-l-cyan-500',
  key_back: 'border-l-cyan-500',
  launch_app: 'border-l-indigo-500',
  stop_app: 'border-l-indigo-500',
  clear_app: 'border-l-indigo-500',
  wait_app: 'border-l-indigo-500',
  push_file: 'border-l-indigo-500',
  pull_file: 'border-l-indigo-500',
  open_url: 'border-l-indigo-500',
  install_apk: 'border-l-indigo-500',
  scroll_down: 'border-l-indigo-500',
  scroll_to: 'border-l-indigo-500',
  wait: 'border-l-green-500',
  wait_element: 'border-l-green-500',
  wait_stable: 'border-l-green-500',
  verify_screen: 'border-l-green-500',
  assert_element: 'border-l-green-500',
  dismiss_popup: 'border-l-green-500',
  double_tap: 'border-l-blue-400',
  pinch: 'border-l-sky-500',
  drag: 'border-l-blue-600',
  take_screenshot: 'border-l-violet-500',
  set_clipboard: 'border-l-teal-500',
  set_variable: 'border-l-purple-500',
  set_var: 'border-l-purple-500',
  loop: 'border-l-teal-500',
  extract: 'border-l-fuchsia-500',
  save_extraction: 'border-l-fuchsia-600',
  extract_text_hierarchy: 'border-l-fuchsia-500',
  extract_text_ocr: 'border-l-fuchsia-500',
  extract_text_ai: 'border-l-fuchsia-500',
  extract_screen_data: 'border-l-fuchsia-500',
  if: 'border-l-amber-500',
  break_if: 'border-l-amber-500',
  repeat: 'border-l-orange-500',
  repeat_until: 'border-l-orange-500',
  if_element: 'border-l-amber-500',
  if_variable: 'border-l-amber-500',
  random_pick: 'border-l-rose-500',
  run_scenario: 'border-l-pink-500'
};

export const BRACKET_COLORS: Record<
  string,
  { border: string; bg: string; label: string }
> = {
  repeat: {
    border: 'border-orange-400/60',
    bg: 'bg-orange-50/50 dark:bg-orange-950/20',
    label: 'text-orange-600 dark:text-orange-400'
  },
  repeat_until: {
    border: 'border-orange-400/60',
    bg: 'bg-orange-50/50 dark:bg-orange-950/20',
    label: 'text-orange-600 dark:text-orange-400'
  },
  if_element: {
    border: 'border-amber-400/60',
    bg: 'bg-amber-50/50 dark:bg-amber-950/20',
    label: 'text-amber-600 dark:text-amber-400'
  },
  if_variable: {
    border: 'border-amber-400/60',
    bg: 'bg-amber-50/50 dark:bg-amber-950/20',
    label: 'text-amber-600 dark:text-amber-400'
  },
  random_pick: {
    border: 'border-rose-400/60',
    bg: 'bg-rose-50/50 dark:bg-rose-950/20',
    label: 'text-rose-600 dark:text-rose-400'
  },
  run_scenario: {
    border: 'border-pink-400/60',
    bg: 'bg-pink-50/50 dark:bg-pink-950/20',
    label: 'text-pink-600 dark:text-pink-400'
  },
  loop: {
    border: 'border-teal-400/60',
    bg: 'bg-teal-50/50 dark:bg-teal-950/20',
    label: 'text-teal-600 dark:text-teal-400'
  },
  if: {
    border: 'border-amber-400/60',
    bg: 'bg-amber-50/50 dark:bg-amber-950/20',
    label: 'text-amber-600 dark:text-amber-400'
  },
  break_if: {
    border: 'border-amber-400/60',
    bg: 'bg-amber-50/50 dark:bg-amber-950/20',
    label: 'text-amber-600 dark:text-amber-400'
  }
};

function localizeExtractStrategy(strategy?: string): string {
  switch (strategy) {
    case 'fb_posts':
      return 'Bài viết Facebook';
    case 'fb_comments':
      return 'Bình luận Facebook';
    case 'text_nodes':
      return 'Văn bản hiển thị';
    default:
      return strategy ?? 'fb_posts';
  }
}

function localizeDataVar(dataVar?: string): string {
  switch (dataVar) {
    case 'comments':
      return 'bình luận';
    case 'posts':
      return 'bài viết';
    case 'text_nodes':
      return 'văn bản';
    default:
      return dataVar ?? 'posts';
  }
}

function localizeCollection(collection?: string): string {
  if (!collection) return 'default';
  const trimmed = collection.trim();
  if (/^\$\{SAVE_COLLECTION\}$/i.test(trimmed)) {
    return 'bộ sưu tập đã cấu hình';
  }
  if (/^\$\{[^}]+\}$/.test(trimmed)) {
    return 'bộ sưu tập theo biến';
  }
  return trimmed;
}

/** Set `true` to show hierarchy / OCR / AI / auto screen-extract in the "+" insert menu again. */
export const INSERT_MENU_SHOW_TEXT_EXTRACT_SHORTCUTS = false;

const _INSERT_MENU_HIDDEN_TYPES = new Set<string>([
  'extract_text_hierarchy',
  'extract_text_ocr',
  'extract_text_ai',
  'extract_screen_data'
]);

export type FlowInsertTranslator = (
  key: string,
  values?: Record<string, string | number>
) => string;

export type FlowStepTranslator = (
  key: string,
  values?: Record<string, string | number>
) => string;

/** Insert menu structure (labels resolved via i18n). */
export const INSERT_MENU_DEF = [
  {
    groupKey: 'dataCollection' as const,
    items: [
      'extract',
      'save_extraction',
      'extract_text_hierarchy',
      'extract_text_ocr',
      'extract_text_ai',
      'extract_screen_data'
    ]
  },
  {
    groupKey: 'actions' as const,
    items: [
      'tap_selector',
      'tap_ratio',
      'tap_position',
      'long_tap_selector',
      'swipe_ratio',
      'input_text',
      'input_selector',
      'key',
      'key_back',
      'launch_app',
      'stop_app',
      'clear_app',
      'wait_app',
      'push_file',
      'pull_file',
      'open_url',
      'install_apk',
      'scroll_down',
      'scroll_to',
      'assert_element',
      'dismiss_popup',
      'double_tap',
      'pinch',
      'drag',
      'take_screenshot',
      'set_clipboard',
      'set_variable',
      'set_var'
    ]
  },
  {
    groupKey: 'flow' as const,
    items: [
      'wait',
      'wait_element',
      'wait_stable',
      'verify_screen',
      'if_element',
      'if_variable',
      'if',
      'break_if',
      'loop',
      'repeat',
      'repeat_until',
      'random_pick',
      'run_scenario'
    ]
  },
  {
    groupKey: 'facebook' as const,
    items: ['fb_tap_comment_button', 'tap_fb_comment_button', 'extract_fb_comments', 'extract_fb_posts']
  }
] as const;

export type InsertMenuGroupKey = (typeof INSERT_MENU_DEF)[number]['groupKey'];

export type InsertMenuItem = {
  type: string;
  label: string;
  description: string;
};

export type InsertMenuGroup = {
  groupKey: InsertMenuGroupKey;
  group: string;
  description: string;
  items: InsertMenuItem[];
};

function insertItemDescription(
  t: FlowInsertTranslator,
  type: string
): string {
  const key = `itemDesc.${type}`;
  const value = t(key as 'itemDesc.extract');
  return value === key ? '' : value;
}

export function getInsertMenuForUi(t: FlowInsertTranslator): InsertMenuGroup[] {
  return INSERT_MENU_DEF.map((group) => ({
    groupKey: group.groupKey,
    group: t(`groups.${group.groupKey}.title`),
    description: t(`groups.${group.groupKey}.description`),
    items: group.items
      .filter(
        (type) =>
          INSERT_MENU_SHOW_TEXT_EXTRACT_SHORTCUTS ||
          !_INSERT_MENU_HIDDEN_TYPES.has(type)
      )
      .map((type) => ({
        type,
        label: t(`items.${type}` as 'items.launch_app'),
        description: insertItemDescription(t, type)
      }))
  })).filter((group) => group.items.length > 0);
}

/** Flat lookup for recent-step labels. */
export function findInsertMenuItem(
  menu: InsertMenuGroup[],
  type: string
): (InsertMenuItem & { groupKey: InsertMenuGroupKey; group: string }) | null {
  for (const group of menu) {
    const item = group.items.find((i) => i.type === type);
    if (item) {
      return { ...item, groupKey: group.groupKey, group: group.group };
    }
  }
  return null;
}

export function getStepSummary(step: FlowStep): string {
  switch (step.type) {
    case 'tap':
      return step.selector
        ? `[${step.selector.by}] "${step.selector.value}"`
        : step.fallback
          ? `(${step.fallback.rx}, ${step.fallback.ry})`
          : '';
    case 'tap_selector': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `[${by}] "${val}"`;
    }
    case 'tap_ratio':
      return `(${step.x}, ${step.y})`;
    case 'tap_position':
      return step.pos;
    case 'long_tap_selector': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `[${by}] "${val}"`;
    }
    case 'swipe_ratio':
      return `(${step.x1},${step.y1})→(${step.x2},${step.y2})`;
    case 'input_text':
      return `"${step.text}"`;
    case 'input_selector': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `"${step.text}" → [${by}] "${val}"`;
    }
    case 'key':
      return step.key;
    case 'launch_app':
      return step.package || '';
    case 'stop_app':
    case 'clear_app':
    case 'wait_app':
      return step.package || '';
    case 'push_file':
      return `${step.local_path || ''} → ${step.remote_path || ''}`;
    case 'pull_file':
      return `${step.remote_path || ''} → ${step.local_path || ''}`;
    case 'open_url':
      return step.url || '';
    case 'install_apk':
      return step.url || '';
    case 'wait':
      return `${step.seconds}s`;
    case 'wait_element': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `[${by}] "${val}"`;
    }
    case 'assert_element': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `[${by}] "${val}"`;
    }
    case 'scroll_down': {
      const x = step.start_x_ratio != null ? ` @${step.start_x_ratio}` : '';
      return `×${step.repeats}${x}`;
    }
    case 'scroll_to': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `[${by}] "${val}"`;
    }
    case 'dismiss_popup':
      return '';
    case 'double_tap':
      return step.rx != null
        ? `(${step.rx}, ${step.ry})`
        : step.x != null
          ? `(${step.x}, ${step.y})`
          : '';
    case 'pinch':
      return `scale=${step.scale ?? 0.5}`;
    case 'drag':
      return step.rx1 != null
        ? `(${step.rx1},${step.ry1})→(${step.rx2},${step.ry2})`
        : `(${step.x1},${step.y1})→(${step.x2},${step.y2})`;
    case 'take_screenshot':
      return step.save_path ?? '';
    case 'set_clipboard':
      return `"${step.text ?? ''}"`;
    case 'set_variable':
      return `${step.name} = ${step.value ?? '…'}`;
    case 'set_var':
      return `${step.key ?? ''} = ${JSON.stringify(step.value ?? '')}`;
    case 'repeat':
      return `${step.count}×`;
    case 'repeat_until':
      return `tối đa ${step.max_iterations}`;
    case 'if_element': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return `[${by}] "${val}"`;
    }
    case 'if_variable': {
      const op =
        step.equals != null
          ? `== "${step.equals}"`
          : step.not_equals != null
            ? `!= "${step.not_equals}"`
            : step.contains != null
              ? `⊃ "${step.contains}"`
              : step.greater_than != null
                ? `> ${step.greater_than}`
                : '';
      return `${step.name} ${op}`;
    }
    case 'random_pick':
      return `${step.branches?.length ?? 0} nhánh`;
    case 'run_scenario':
      return step.scenario_name || step.scenario_id || '';
    case 'loop':
      return `×${step.count ?? '?'}`;
    case 'fb_tap_comment_button':
    case 'tap_fb_comment_button': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      return `OK: ${thenN} bước${elseN ? ` · Không thấy: ${elseN} bước` : ''} · chờ ${step.timeout ?? 6}s`;
    }
    case 'extract': {
      const base = localizeExtractStrategy(step.strategy);
      return step.collection
        ? `${base} → ${localizeCollection(step.collection)}`
        : base;
    }
    case 'save_extraction':
      return `${localizeDataVar(step.data_var)} → ${localizeCollection(step.collection)}`;
    case 'extract_text_hierarchy':
      return step.save_as ?? 'texts';
    case 'extract_text_ocr':
      return step.save_as ?? 'ocr_text';
    case 'extract_text_ai':
      return step.save_as ?? 'ai_text';
    case 'extract_screen_data':
      return step.save_as ?? 'screen_data';
    default:
      return '';
  }
}

/**
 * Human-readable display for a step card.
 * `target`  — the main value/subject (shown prominently)
 * `selectorBadge` — selector type badge (text / resource-id / xpath …)
 */
export function getStepDisplay(
  step: FlowStep,
  t?: FlowStepTranslator
): { target: string; selectorBadge?: string } {
  const td = (key: string, values?: Record<string, string | number>) =>
    t ? t(`display.${key}`, values) : '';
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  switch (step.type) {
    case 'tap_selector':
    case 'long_tap_selector':
    case 'wait_element':
    case 'assert_element':
    case 'scroll_to': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return { target: val ?? '', selectorBadge: by };
    }
    case 'input_selector': {
      const by = step.selector?.by ?? step.by;
      const val = step.selector?.value ?? step.value;
      return { target: val ?? '', selectorBadge: by };
    }
    case 'tap':
      return step.selector?.value
        ? { target: step.selector.value, selectorBadge: step.selector.by }
        : {
            target: step.fallback
              ? `(${pct(step.fallback.rx)}, ${pct(step.fallback.ry)})`
              : ''
          };
    case 'tap_ratio':
      return { target: `(${pct(step.x ?? 0.5)}, ${pct(step.y ?? 0.5)})` };
    case 'swipe_ratio':
      return {
        target: `(${pct(step.x1 ?? 0.5)},${pct(step.y1 ?? 0.5)}) → (${pct(step.x2 ?? 0.5)},${pct(step.y2 ?? 0.5)})`
      };
    case 'input_text':
      return { target: step.text ?? '' };
    case 'wait':
      return {
        target:
          step.seconds != null
            ? t
              ? td('waitSeconds', { seconds: step.seconds })
              : `${step.seconds}s`
            : ''
      };
    case 'key':
      return { target: step.key ?? '' };
    case 'launch_app':
      return { target: step.package ?? '' };
    case 'stop_app':
      return { target: step.package ?? '' };
    case 'clear_app':
      return { target: step.package ?? '' };
    case 'wait_app':
      return {
        target: step.package
          ? t
            ? td('waitAppTimeout', {
                package: step.package,
                timeout: step.timeout ?? 20
              })
            : `${step.package} (${step.timeout ?? 20}s)`
          : ''
      };
    case 'push_file':
      return { target: step.remote_path ?? step.local_path ?? '' };
    case 'pull_file':
      return { target: step.local_path ?? step.remote_path ?? '' };
    case 'open_url':
      return { target: step.url ?? '' };
    case 'install_apk':
      return { target: step.url ?? '' };
    case 'wait_stable':
      return {
        target:
          step.timeout != null
            ? t
              ? td('waitStableTimeout', { timeout: step.timeout })
              : `timeout ${step.timeout}s`
            : ''
      };
    case 'verify_screen':
      return {
        target:
          step.ssim_threshold != null
            ? t
              ? td('verifySsim', { threshold: step.ssim_threshold })
              : `SSIM ≥ ${step.ssim_threshold}`
            : t
              ? td('verifyScreenDefault')
              : 'verify screen'
      };
    case 'dismiss_popup':
      return { target: step.retries != null ? `×${step.retries}` : '' };
    case 'tap_position':
      return { target: step.pos ?? '' };
    case 'scroll_down': {
      const x = step.start_x_ratio != null ? ` · x=${step.start_x_ratio}` : '';
      return {
        target:
          step.repeats != null
            ? t
              ? `${td('scrollRepeats', { count: step.repeats })}${x}`
              : `${step.repeats}×${x}`
            : ''
      };
    }
    case 'set_variable':
      return { target: step.name ? `${step.name} = ${step.value ?? '…'}` : '' };
    case 'set_var':
      return {
        target: step.key
          ? `${step.key} = ${JSON.stringify(step.value ?? '')}`
          : ''
      };
    case 'repeat':
      return {
        target:
          step.count != null
            ? t
              ? td('repeatCount', { count: step.count })
              : `${step.count}×`
            : ''
      };
    case 'repeat_until':
      return {
        target:
          step.max_iterations != null
            ? t
              ? td('repeatUntilMax', { max: step.max_iterations })
              : `max ${step.max_iterations}`
            : ''
      };
    case 'if_element':
      return { target: step.value ?? '', selectorBadge: step.by };
    case 'if_variable':
      return {
        target: step.name
          ? `${step.name} ${step.equals != null ? `= "${step.equals}"` : step.not_equals != null ? `≠ "${step.not_equals}"` : step.contains != null ? `⊃ "${step.contains}"` : step.greater_than != null ? `> ${step.greater_than}` : ''}`
          : ''
      };
    case 'random_pick':
      return {
        target: t
          ? td('randomBranches', { count: step.branches?.length ?? 0 })
          : `${step.branches?.length ?? 0}`
      };
    case 'run_scenario':
      return { target: step.scenario_name || step.scenario_id || '' };
    case 'if':
      return {
        target: Object.keys(step.condition ?? {}).join(', ') || 'condition'
      };
    case 'break_if':
      return {
        target: Object.keys(step.condition ?? {}).join(', ') || 'condition'
      };
    case 'loop':
      return { target: `×${step.count ?? '?'}` };
    case 'fb_tap_comment_button':
    case 'tap_fb_comment_button': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      if (t) {
        return {
          target: td('fbCommentSummary', {
            thenCount: thenN,
            elsePart: elseN ? td('fbCommentElse', { elseCount: elseN }) : ''
          })
        };
      }
      return {
        target: `Comment · OK ${thenN}${elseN ? ` / miss ${elseN}` : ''}`
      };
    }
    case 'extract': {
      const base = localizeExtractStrategy(step.strategy);
      return {
        target: step.collection
          ? `${base} → ${localizeCollection(step.collection)}`
          : base
      };
    }
    case 'save_extraction':
      return {
        target: `${localizeDataVar(step.data_var)} → ${localizeCollection(step.collection)}`
      };
    case 'extract_text_hierarchy':
      return { target: step.save_as ?? 'texts' };
    case 'extract_text_ocr':
      return { target: step.save_as ?? 'ocr_text' };
    case 'extract_text_ai':
      return { target: step.save_as ?? 'ai_text' };
    case 'extract_screen_data':
      return { target: step.save_as ?? 'screen_data' };
    default:
      return { target: getStepSummary(step) };
  }
}

/** Returns which top-level category a step type belongs to. */
export function getStepCategory(type: string): 'action' | 'flow' {
  const flowTypes = new Set([
    'wait',
    'wait_element',
    'wait_stable',
    'verify_screen',
    'loop',
    'repeat',
    'repeat_until',
    'if_element',
    'if_variable',
    'if',
    'break_if',
    'random_pick',
    'run_scenario'
  ]);
  return flowTypes.has(type) ? 'flow' : 'action';
}

/** Localized step type badge (flow editor, monitor). */
export function getStepTypeName(type: string, t?: FlowStepTranslator): string {
  if (t) {
    const key = `typeName.${type}`;
    const label = t(key);
    if (label !== key) return label;
  }
  return type.toUpperCase();
}

/** Card-friendly label: sentence case when i18n returns ALL CAPS. */
export function formatStepLabelForCard(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) return trimmed;
  const hasLowercase = /[a-zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổộơớờởỡùúủũụưứừửữựỳýỷỹỵđ]/.test(
    trimmed
  );
  if (hasLowercase) return trimmed;
  return trimmed
    .toLowerCase()
    .split(/\s+/)
    .map((word) =>
      word.length > 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word
    )
    .join(' ');
}
