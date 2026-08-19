import type { FlowStep } from '../scenario-steps/types';

export const STEP_COLORS: Record<string, string> = {
  tap: 'border-l-blue-500',
  tap_ratio: 'border-l-blue-500',
  tap_position: 'border-l-blue-500',
  tap_image: 'border-l-blue-500',
  tap_selector: 'border-l-blue-500',
  long_tap_selector: 'border-l-blue-500',
  swipe_ratio: 'border-l-blue-500',
  input_text: 'border-l-cyan-500',
  input_selector: 'border-l-cyan-500',
  key: 'border-l-cyan-500',
  key_back: 'border-l-cyan-500',
  adb_shell: 'border-l-slate-500',
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
  login_if_needed: 'border-l-emerald-500',
  platform_session_gate: 'border-l-emerald-600',
  fill_form: 'border-l-cyan-600',
  assert_app_state: 'border-l-green-600',
  double_tap: 'border-l-blue-400',
  pinch: 'border-l-sky-500',
  drag: 'border-l-blue-600',
  take_screenshot: 'border-l-violet-500',
  set_clipboard: 'border-l-teal-500',
  set_variable: 'border-l-purple-500',
  set_var: 'border-l-purple-500',
  loop: 'border-l-teal-500',
  use_source_pool: 'border-l-teal-600',
  extract: 'border-l-fuchsia-500',
  save_extraction: 'border-l-fuchsia-600',
  social_find_comment_button: 'border-l-sky-500',
  social_tap_comment_target: 'border-l-blue-500',
  social_apply_comment_filter: 'border-l-emerald-500',
  social_select_target: 'border-l-emerald-600',
  social_connect_visible_people: 'border-l-emerald-600',
  social_scan_posts_interact: 'border-l-blue-600',
  social_open_author_from_post_match: 'border-l-emerald-700',
  social_open_commenter_from_post_match: 'border-l-emerald-700',
  content_interaction: 'border-l-blue-500',
  connection_request: 'border-l-sky-500',
  community_membership: 'border-l-emerald-500',
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
  social_open_comments: {
    border: 'border-blue-400/60',
    bg: 'bg-blue-50/50 dark:bg-blue-950/20',
    label: 'text-blue-600 dark:text-blue-400'
  },
  break_if: {
    border: 'border-amber-400/60',
    bg: 'bg-amber-50/50 dark:bg-amber-950/20',
    label: 'text-amber-600 dark:text-amber-400'
  }
};

/** `display.*` lookup; empty string when no translator was supplied. */
function displayText(
  t?: FlowStepTranslator
): (key: string, values?: Record<string, string | number>) => string {
  return (key, values) => (t ? t(`display.${key}`, values) : '');
}

const EXTRACT_ENTITY_KEYS: Record<string, string> = {
  posts: 'extractEntityPost',
  comments: 'extractEntityComment',
  groups: 'extractEntityGroup',
  pages: 'extractEntityPage',
  text_nodes: 'extractEntityVisibleText'
};

function localizeExtractEntity(
  entity?: string,
  t?: FlowStepTranslator
): string {
  const td = displayText(t);
  const key = EXTRACT_ENTITY_KEYS[entity ?? 'posts'];
  if (key) {
    const label = td(key);
    if (label) return label;
  }
  return entity ?? '';
}

const DATA_VAR_KEYS: Record<string, string> = {
  comments: 'dataVarComments',
  posts: 'dataVarPosts',
  text_nodes: 'dataVarTextNodes'
};

function localizeDataVar(dataVar?: string, t?: FlowStepTranslator): string {
  const td = displayText(t);
  const key = DATA_VAR_KEYS[dataVar ?? 'posts'];
  if (key) {
    const label = td(key);
    if (label) return label;
  }
  return dataVar ?? 'posts';
}

function localizeCollection(
  collection?: string,
  t?: FlowStepTranslator
): string {
  if (!collection) return 'default';
  const td = displayText(t);
  const trimmed = collection.trim();
  if (/^\$\{SAVE_COLLECTION\}$/i.test(trimmed)) {
    return td('collectionConfigured') || trimmed;
  }
  if (/^\$\{[^}]+\}$/.test(trimmed)) {
    return td('collectionByVariable') || trimmed;
  }
  return trimmed;
}

const COMMENT_FILTER_I18N_KEYS: Record<string, string> = {
  most_relevant: 'commentFilterMostRelevant',
  newest: 'commentFilterNewest',
  all_comments: 'commentFilterAllComments',
  none: 'commentFilterNone'
};

const COMMENT_FILTER_LABELS_EN: Record<string, string> = {
  most_relevant: 'Most relevant',
  newest: 'Newest',
  all_comments: 'All comments',
  none: 'No change'
};

function localizeCommentFilter(
  filter: string | undefined,
  t?: FlowStepTranslator
): string {
  const key = filter ?? 'all_comments';
  if (t) {
    const i18nKey = COMMENT_FILTER_I18N_KEYS[key];
    if (i18nKey) {
      return t(`display.${i18nKey}`);
    }
  }
  return COMMENT_FILTER_LABELS_EN[key] ?? key;
}

function hasFbCommentExtract(steps: unknown): boolean {
  if (!Array.isArray(steps)) return false;
  return steps.some((raw) => {
    if (!raw || typeof raw !== 'object') return false;
    const step = raw as FlowStep;
    if (step.type === 'extract' && step.entity === 'comments') {
      return true;
    }
    return (
      hasFbCommentExtract(step.steps) ||
      hasFbCommentExtract(step.then) ||
      hasFbCommentExtract(step.else) ||
      (Array.isArray(step.branches) &&
        step.branches.some((branch: unknown) => {
          if (!branch || typeof branch !== 'object') return false;
          return hasFbCommentExtract((branch as { steps?: unknown }).steps);
        }))
    );
  });
}

/** Set `true` to show hierarchy / OCR / AI / auto screen-extract in the "+" insert menu again. */
export const INSERT_MENU_SHOW_TEXT_EXTRACT_SHORTCUTS = false;

/** Quick actions on device control rail (control-record) — not scenario nodes. */
export const DEVICE_RAIL_STEP_TYPES = new Set<string>([
  'adb_shell',
  'clear_app',
  'install_apk'
]);

const _INSERT_MENU_HIDDEN_TYPES = new Set<string>([
  'pull_file',
  'extract_text_hierarchy',
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

const SYSTEM_VARIABLE_LABEL_KEYS: Record<string, string> = {
  PLATFORM_SESSION_READY: 'systemVariable.platformSessionReady'
};

export function getVariableDisplayName(
  name: string,
  t?: FlowStepTranslator
): string {
  const key = SYSTEM_VARIABLE_LABEL_KEYS[name];
  if (!key || !t) return name;
  const label = t(key as 'systemVariable.platformSessionReady');
  return isIntlMissingMessage(key, label) ? name : label;
}

/** Insert menu structure (labels resolved via i18n). */
export const INSERT_MENU_DEF = [
  {
    groupKey: 'dataCollection' as const,
    items: [
      'use_source_pool',
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
      'tap_image',
      'long_tap_selector',
      'swipe_ratio',
      'input_text',
      'input_selector',
      'key',
      'key_back',
      'adb_shell',
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
      'login_if_needed',
      'platform_session_gate',
      'fill_form',
      'assert_app_state',
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
    groupKey: 'social' as const,
    items: [
      'content_interaction',
      'connection_request',
      'lease_source_target',
      'lease_connection_candidate',
      'community_membership',
      'social_select_target',
      'social_connect_visible_people',
      'social_scan_posts_interact',
      'social_open_author_from_post_match',
      'social_open_commenter_from_post_match',
      'social_find_comment_button',
      'social_tap_comment_target',
      'social_apply_comment_filter',
      'extract_comments',
      'extract_posts'
    ]
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

/** i18n slug for adb_shell (avoids ambiguous `items.adb_*` paths in catalogs). */
export function adbShellStepI18nSlug(type: string): string {
  return type === 'adb_shell' ? 'adb' : type;
}

function isIntlMissingMessage(key: string, label: string): boolean {
  return label === key || label.includes('campaignsFeature.');
}

function insertItemDescription(t: FlowInsertTranslator, type: string): string {
  const slug = adbShellStepI18nSlug(type);
  const key = `itemDesc.${slug}`;
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
        label: t(`items.${adbShellStepI18nSlug(type)}` as 'items.launch_app'),
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

export function getStepSummary(step: FlowStep, t?: FlowStepTranslator): string {
  const td = displayText(t);
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
    case 'tap_image':
      return step.template_key ? td('tapImageAttached') : td('tapImageMissing');
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
    case 'login_if_needed':
      return step.profile?.package || '';
    case 'platform_session_gate':
      return step.phase === 'confirm'
        ? td('platformSessionConfirm')
        : td('platformSessionPreflight');
    case 'fill_form':
      return step.recipe || '';
    case 'assert_app_state':
      return step.any_text?.[0] || step.locator || step.package || '';
    case 'key':
      return step.key;
    case 'adb_shell':
      return step.command || step.cmd || '';
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
      return td('repeatUntilMax', { max: step.max_iterations ?? 0 });
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
      return td('randomBranches', { count: step.branches?.length ?? 0 });
    case 'run_scenario':
      return step.scenario_name || step.scenario_id || '';
    case 'loop':
      return `×${step.count ?? '?'}`;
    case 'social_open_comments':
    case 'social_open_comments': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      const commentPart = hasFbCommentExtract(step.then)
        ? td('socialOpenCommentsExtract')
        : '';
      const requirePostPart = step.require_post_before_comment
        ? td('socialOpenCommentsRequirePost')
        : '';
      const elsePart = elseN
        ? td('socialOpenCommentsElse', { elseCount: elseN })
        : '';
      return td('socialOpenCommentsSummary', {
        thenCount: thenN,
        extra: `${commentPart}${requirePostPart}${elsePart}`,
        timeout: step.timeout ?? 6
      });
    }
    case 'social_find_comment_button':
      return td('socialFindCommentTarget', { timeout: step.timeout ?? 6 });
    case 'social_tap_comment_target':
      return td('socialTapCommentTarget', {
        wait: step.post_tap_wait_s ?? 0.35
      });
    case 'social_apply_comment_filter':
      return td('fbApplyCommentFilter', {
        filter: localizeCommentFilter(step.comment_filter, t)
      });
    case 'social_select_target':
      return step.target_type === 'post'
        ? td('socialSelectTargetPost', {
            label:
              step.display_text || step.search || step.save_as || '_post_target'
          })
        : td('socialSelectTargetPeople', {
            label:
              step.display_name ||
              step.search ||
              step.save_as ||
              '_people_target'
          });
    case 'social_connect_visible_people':
      return td('socialConnectVisible', { score: step.min_score ?? 40 });
    case 'social_scan_posts_interact':
      return td('socialScanPosts', {
        count: step.target_count ?? 1,
        scrolls: step.max_scrolls ?? 0
      });
    case 'social_open_author_from_post_match':
      return td('socialOpenAuthor', {
        source: step.source_var ?? '_post_scan',
        index: step.action_index ?? 0,
        platform: step.platform ?? 'facebook'
      });
    case 'social_open_commenter_from_post_match':
      return td('socialOpenCommenter', {
        source: step.source_var ?? '_post_scan',
        index: step.action_index ?? 0,
        platform: step.platform ?? 'facebook'
      });
    case 'content_interaction':
      return `${step.platform ?? 'facebook'} · ${step.action ?? 'like'}`;
    case 'connection_request':
      return td('connectionRequestSend', {
        platform: step.platform ?? 'facebook'
      });
    case 'community_membership':
      return td('communityMembershipJoin', {
        platform: step.platform ?? 'facebook'
      });
    case 'extract': {
      const base = localizeExtractEntity(step.entity, t);
      return step.collection
        ? `${base} → ${localizeCollection(step.collection, t)}`
        : base;
    }
    case 'save_extraction':
      return `${localizeDataVar(step.data_var, t)} → ${localizeCollection(step.collection, t)}`;
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
    case 'adb_shell':
      return { target: step.command || step.cmd || '' };
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
    case 'login_if_needed':
      return { target: step.profile?.package ?? '' };
    case 'platform_session_gate':
      return {
        target:
          step.phase === 'confirm'
            ? t
              ? td('platformSessionConfirm')
              : 'Confirm after login'
            : t
              ? td('platformSessionPreflight')
              : 'Check before continuing'
      };
    case 'fill_form':
      return { target: step.recipe ?? '' };
    case 'assert_app_state':
      return {
        target: step.any_text?.[0] ?? step.locator ?? step.package ?? ''
      };
    case 'tap_position':
      return { target: step.pos ?? '' };
    case 'tap_image':
      return {
        target: step.template_key
          ? td('tapImageAttached')
          : td('tapImageMissing')
      };
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
    case 'use_source_pool':
      return {
        target: `${step.platform ?? 'facebook'} / ${step.entity_type ?? 'group'}`
      };
    case 'lease_source_target':
      return {
        target: `${step.platform ?? 'facebook'} / ${step.entity_type ?? 'post'} / ${step.action ?? 'like'}`
      };
    case 'lease_connection_candidate':
      return { target: `${step.platform ?? 'facebook'} / ready_to_connect` };
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
    case 'social_open_comments':
    case 'social_open_comments': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      const commentPart = hasFbCommentExtract(step.then)
        ? td('socialOpenCommentsExtract')
        : '';
      const requirePostPart = step.require_post_before_comment
        ? td('socialOpenCommentsRequirePost')
        : '';
      if (t) {
        return {
          target: td('fbCommentSummary', {
            thenCount: thenN,
            elsePart: `${commentPart}${requirePostPart}${elseN ? td('fbCommentElse', { elseCount: elseN }) : ''}`
          })
        };
      }
      return {
        target: `Comment · OK ${thenN}${commentPart}${requirePostPart}${elseN ? ` / miss ${elseN}` : ''}`
      };
    }
    case 'social_find_comment_button':
      return {
        target: t
          ? td('fbFindCommentButton', { timeout: step.timeout ?? 6 })
          : `Find comment button · ${step.timeout ?? 6}s`
      };
    case 'social_tap_comment_target':
      return {
        target: t
          ? td('fbTapCommentTarget', {
              wait: step.post_tap_wait_s ?? 0.35
            })
          : `Tap cached target · ${step.post_tap_wait_s ?? 0.35}s`
      };
    case 'social_apply_comment_filter': {
      const filterLabel = localizeCommentFilter(step.comment_filter, t);
      return {
        target: t
          ? td('fbApplyCommentFilter', { filter: filterLabel })
          : `Filter · ${filterLabel}`
      };
    }
    case 'social_select_target':
      return {
        target:
          step.target_type === 'post'
            ? step.display_text || step.search || step.save_as || '_post_target'
            : step.display_name ||
              step.search ||
              step.save_as ||
              '_people_target'
      };
    case 'social_connect_visible_people':
      return {
        target: td('socialConnectVisibleShort', { score: step.min_score ?? 40 })
      };
    case 'social_scan_posts_interact':
      return {
        target: td('socialScanPostsShort', {
          keywords: step.keywords || td('socialScanPostsAnyKeyword'),
          count: step.target_count ?? 1
        })
      };
    case 'social_open_author_from_post_match':
    case 'social_open_commenter_from_post_match':
      return {
        target: `${step.platform ?? 'facebook'} · ${step.source_var ?? '_post_scan'}[${step.action_index ?? 0}]`
      };
    case 'content_interaction':
      return {
        target: `${step.platform ?? 'facebook'} · ${step.action ?? 'like'}`
      };
    case 'connection_request':
      return { target: `${step.platform ?? 'facebook'} · request` };
    case 'lease_source_target':
      return {
        target: `${step.platform ?? 'facebook'} · ${step.entity_type ?? 'post'} · ${step.action ?? 'like'}`
      };
    case 'lease_connection_candidate':
      return { target: `${step.platform ?? 'facebook'} · ready_to_connect` };
    case 'community_membership':
      return { target: `${step.platform ?? 'facebook'} · join` };
    case 'extract': {
      const base = localizeExtractEntity(step.entity);
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
      return { target: getStepSummary(step, t) };
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

const DEFAULT_STEP_TYPE_LABELS: Record<string, string> = {
  adb_shell: 'ADB shell'
};

/** Localized step type badge (flow editor, monitor). */
export function getStepTypeName(type: string, t?: FlowStepTranslator): string {
  if (t) {
    const slug = adbShellStepI18nSlug(type);
    const key = `typeName.${slug}`;
    const label = t(key as 'typeName.tap_selector');
    if (!isIntlMissingMessage(key, label)) return label;
    if (slug !== type) {
      const directKey = `typeName.${type}`;
      const direct = t(directKey as 'typeName.tap_selector');
      if (!isIntlMissingMessage(directKey, direct)) return direct;
    }
  }
  return DEFAULT_STEP_TYPE_LABELS[type] ?? type.toUpperCase();
}

/** Card-friendly label: sentence case when i18n returns ALL CAPS. */
export function formatStepLabelForCard(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) return trimmed;
  const hasLowercase =
    /[a-zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổộơớờởỡùúủũụưứừửữựỳýỷỹỵđ]/.test(
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
