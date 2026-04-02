import type { FlowStep } from '../scenario-steps/types';

/** Color categories for step cards (Tailwind border-left color). */
export const STEP_COLORS: Record<string, string> = {
  tap: 'border-l-blue-500', tap_ratio: 'border-l-blue-500', tap_position: 'border-l-blue-500',
  tap_selector: 'border-l-blue-500', long_tap_selector: 'border-l-blue-500', swipe_ratio: 'border-l-blue-500',
  input_text: 'border-l-cyan-500', input_selector: 'border-l-cyan-500', key: 'border-l-cyan-500',
  launch_app: 'border-l-indigo-500', open_url: 'border-l-indigo-500',
  scroll_down: 'border-l-indigo-500', scroll_to: 'border-l-indigo-500',
  wait: 'border-l-green-500', wait_element: 'border-l-green-500', wait_stable: 'border-l-green-500',
  assert_element: 'border-l-green-500', dismiss_popup: 'border-l-green-500',
  double_tap: 'border-l-blue-400', pinch: 'border-l-sky-500', drag: 'border-l-blue-600',
  take_screenshot: 'border-l-violet-500', set_clipboard: 'border-l-teal-500',
  set_variable: 'border-l-purple-500',
  loop: 'border-l-teal-500',
  extract: 'border-l-fuchsia-500', save_extraction: 'border-l-fuchsia-600',
  repeat: 'border-l-orange-500', repeat_until: 'border-l-orange-500',
  if_element: 'border-l-amber-500', if_variable: 'border-l-amber-500',
  random_pick: 'border-l-rose-500', run_scenario: 'border-l-pink-500',
};

export const BRACKET_COLORS: Record<string, { border: string; bg: string; label: string }> = {
  repeat: { border: 'border-orange-400/60', bg: 'bg-orange-50/50 dark:bg-orange-950/20', label: 'text-orange-600 dark:text-orange-400' },
  repeat_until: { border: 'border-orange-400/60', bg: 'bg-orange-50/50 dark:bg-orange-950/20', label: 'text-orange-600 dark:text-orange-400' },
  if_element: { border: 'border-amber-400/60', bg: 'bg-amber-50/50 dark:bg-amber-950/20', label: 'text-amber-600 dark:text-amber-400' },
  if_variable: { border: 'border-amber-400/60', bg: 'bg-amber-50/50 dark:bg-amber-950/20', label: 'text-amber-600 dark:text-amber-400' },
  random_pick: { border: 'border-rose-400/60', bg: 'bg-rose-50/50 dark:bg-rose-950/20', label: 'text-rose-600 dark:text-rose-400' },
  run_scenario: { border: 'border-pink-400/60', bg: 'bg-pink-50/50 dark:bg-pink-950/20', label: 'text-pink-600 dark:text-pink-400' },
  loop: { border: 'border-teal-400/60', bg: 'bg-teal-50/50 dark:bg-teal-950/20', label: 'text-teal-600 dark:text-teal-400' },
};

/** Insert menu — Vietnamese. Two top-level categories: Action vs Flow. */
export const INSERT_MENU = [
  {
    group: 'Thu thập dữ liệu',
    description: 'Cào và lưu nội dung từ màn hình',
    items: [
      { type: 'extract', label: 'Trích xuất (extract)', icon: '🔎' },
      { type: 'save_extraction', label: 'Lưu dữ liệu (save_extraction)', icon: '💾' },
    ]
  },
  {
    group: 'Hành động',
    description: 'Thao tác trực tiếp lên màn hình',
    items: [
      { type: 'tap_selector', label: 'Chạm phần tử', icon: '👆' },
      { type: 'tap_ratio', label: 'Chạm tọa độ', icon: '👆' },
      { type: 'tap_position', label: 'Chạm vị trí cố định', icon: '👆' },
      { type: 'long_tap_selector', label: 'Nhấn giữ', icon: '👇' },
      { type: 'swipe_ratio', label: 'Vuốt', icon: '👉' },
      { type: 'input_text', label: 'Nhập văn bản', icon: '⌨️' },
      { type: 'input_selector', label: 'Nhập vào phần tử', icon: '⌨️' },
      { type: 'key', label: 'Nhấn phím', icon: '⌨️' },
      { type: 'launch_app', label: 'Mở ứng dụng', icon: '📱' },
      { type: 'open_url', label: 'Mở URL', icon: '🌐' },
      { type: 'scroll_down', label: 'Cuộn xuống', icon: '⬇️' },
      { type: 'scroll_to', label: 'Cuộn tới phần tử', icon: '⬇️' },
      { type: 'assert_element', label: 'Kiểm tra phần tử', icon: '✅' },
      { type: 'dismiss_popup', label: 'Đóng popup', icon: '❌' },
      { type: 'double_tap', label: 'Chạm đúp', icon: '👆' },
      { type: 'pinch', label: 'Phóng to/thu nhỏ', icon: '🤏' },
      { type: 'drag', label: 'Kéo thả', icon: '✊' },
      { type: 'take_screenshot', label: 'Chụp màn hình', icon: '📸' },
      { type: 'set_clipboard', label: 'Ghi clipboard', icon: '📋' },
      { type: 'set_variable', label: 'Gán biến', icon: '📝' },
    ]
  },
  {
    group: 'Luồng',
    description: 'Điều kiện, lặp, chờ — kiểm soát luồng chạy',
    items: [
      { type: 'wait', label: 'Chờ (giây)', icon: '⏱' },
      { type: 'wait_element', label: 'Chờ phần tử xuất hiện', icon: '🔍' },
      { type: 'wait_stable', label: 'Chờ màn hình ổn định', icon: '⏱' },
      { type: 'if_element', label: 'Nếu phần tử tồn tại', icon: '🔀' },
      { type: 'if_variable', label: 'Nếu biến thỏa điều kiện', icon: '🔀' },
      { type: 'loop', label: 'Vòng lặp (hỗ trợ biến)', icon: '🔃' },
      { type: 'repeat', label: 'Lặp N lần', icon: '🔄' },
      { type: 'repeat_until', label: 'Lặp cho đến khi', icon: '🔁' },
      { type: 'random_pick', label: 'Chọn ngẫu nhiên', icon: '🎲' },
      { type: 'run_scenario', label: 'Chạy kịch bản con', icon: '📦' },
    ]
  },
];

export function getStepSummary(step: FlowStep): string {
  switch (step.type) {
    case 'tap': return step.selector ? `[${step.selector.by}] "${step.selector.value}"` : (step.fallback ? `(${step.fallback.rx}, ${step.fallback.ry})` : '');
    case 'tap_selector': return `[${step.by}] "${step.value}"`;
    case 'tap_ratio': return `(${step.x}, ${step.y})`;
    case 'tap_position': return step.pos;
    case 'long_tap_selector': return `[${step.by}] "${step.value}"`;
    case 'swipe_ratio': return `(${step.x1},${step.y1})→(${step.x2},${step.y2})`;
    case 'input_text': return `"${step.text}"`;
    case 'input_selector': return `"${step.text}" → [${step.by}]`;
    case 'key': return step.key;
    case 'launch_app': return step.package || '';
    case 'open_url': return step.url || '';
    case 'wait': return `${step.seconds}s`;
    case 'wait_element': return `[${step.by}] "${step.value}"`;
    case 'assert_element': return `[${step.by}] "${step.value}"`;
    case 'scroll_down': {
      const x = step.start_x_ratio != null ? ` @${step.start_x_ratio}` : '';
      return `×${step.repeats}${x}`;
    }
    case 'scroll_to': return `[${step.by}] "${step.value}"`;
    case 'dismiss_popup': return '';
    case 'double_tap': return step.rx != null ? `(${step.rx}, ${step.ry})` : (step.x != null ? `(${step.x}, ${step.y})` : '');
    case 'pinch': return `scale=${step.scale ?? 0.5}`;
    case 'drag': return step.rx1 != null ? `(${step.rx1},${step.ry1})→(${step.rx2},${step.ry2})` : `(${step.x1},${step.y1})→(${step.x2},${step.y2})`;
    case 'take_screenshot': return step.save_path ?? '';
    case 'set_clipboard': return `"${step.text ?? ''}"`;
    case 'set_variable': return `${step.name} = ${step.value ?? '…'}`;
    case 'repeat': return `${step.count}×`;
    case 'repeat_until': return `tối đa ${step.max_iterations}`;
    case 'if_element': return `[${step.by}] "${step.value}"`;
    case 'if_variable': {
      const op = step.equals != null ? `== "${step.equals}"` : step.not_equals != null ? `!= "${step.not_equals}"` : step.contains != null ? `⊃ "${step.contains}"` : step.greater_than != null ? `> ${step.greater_than}` : '';
      return `${step.name} ${op}`;
    }
    case 'random_pick': return `${step.branches?.length ?? 0} nhánh`;
    case 'run_scenario': return step.scenario_name || step.scenario_id || '';
    case 'loop': return `×${step.count ?? '?'}`;
    case 'extract': return step.strategy ?? 'fb_posts';
    case 'save_extraction': return `${step.data_var ?? 'posts'} → ${step.collection ?? 'default'}`;
    default: return '';
  }
}

/**
 * Human-readable display for a step card.
 * `target`  — the main value/subject (shown prominently)
 * `selectorBadge` — selector type badge (text / resource-id / xpath …)
 */
export function getStepDisplay(step: FlowStep): { target: string; selectorBadge?: string } {
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  switch (step.type) {
    case 'tap_selector':
    case 'long_tap_selector':
    case 'wait_element':
    case 'assert_element':
    case 'scroll_to':
      return { target: step.value ?? '', selectorBadge: step.by };
    case 'input_selector':
      return { target: step.value ?? '', selectorBadge: step.by };
    case 'tap':
      return step.selector?.value
        ? { target: step.selector.value, selectorBadge: step.selector.by }
        : { target: step.fallback ? `(${pct(step.fallback.rx)}, ${pct(step.fallback.ry)})` : '' };
    case 'tap_ratio':
      return { target: `(${pct(step.x ?? 0.5)}, ${pct(step.y ?? 0.5)})` };
    case 'swipe_ratio':
      return { target: `(${pct(step.x1 ?? 0.5)},${pct(step.y1 ?? 0.5)}) → (${pct(step.x2 ?? 0.5)},${pct(step.y2 ?? 0.5)})` };
    case 'input_text':
      return { target: step.text ?? '' };
    case 'wait':
      return { target: step.seconds != null ? `${step.seconds} giây` : '' };
    case 'key':
      return { target: step.key ?? '' };
    case 'launch_app':
      return { target: step.package ?? '' };
    case 'open_url':
      return { target: step.url ?? '' };
    case 'wait_stable':
      return { target: step.timeout != null ? `timeout ${step.timeout}s` : '' };
    case 'dismiss_popup':
      return { target: step.retries != null ? `×${step.retries}` : '' };
    case 'tap_position':
      return { target: step.pos ?? '' };
    case 'scroll_down': {
      const x = step.start_x_ratio != null ? ` · x=${step.start_x_ratio}` : '';
      return { target: step.repeats != null ? `${step.repeats} lần${x}` : '' };
    }
    case 'set_variable':
      return { target: step.name ? `${step.name} = ${step.value ?? '…'}` : '' };
    case 'repeat':
      return { target: step.count != null ? `${step.count} lần` : '' };
    case 'repeat_until':
      return { target: step.max_iterations != null ? `tối đa ${step.max_iterations} lần` : '' };
    case 'if_element':
      return { target: step.value ?? '', selectorBadge: step.by };
    case 'if_variable':
      return {
        target: step.name
          ? `${step.name} ${step.equals != null ? `= "${step.equals}"` : step.not_equals != null ? `≠ "${step.not_equals}"` : step.contains != null ? `⊃ "${step.contains}"` : step.greater_than != null ? `> ${step.greater_than}` : ''}`
          : '',
      };
    case 'random_pick':
      return { target: `${step.branches?.length ?? 0} nhánh` };
    case 'run_scenario':
      return { target: step.scenario_name || step.scenario_id || '' };
    case 'loop':
      return { target: `×${step.count ?? '?'}` };
    case 'extract':
      return { target: step.strategy ?? 'fb_posts' };
    case 'save_extraction':
      return { target: `${step.data_var ?? 'posts'} → ${step.collection ?? 'default'}` };
    default:
      return { target: getStepSummary(step) };
  }
}

/** Returns which top-level category a step type belongs to. */
export function getStepCategory(type: string): 'action' | 'flow' {
  const flowTypes = new Set([
    'wait', 'wait_element', 'wait_stable',
    'loop', 'repeat', 'repeat_until',
    'if_element', 'if_variable',
    'random_pick', 'run_scenario',
  ]);
  return flowTypes.has(type) ? 'flow' : 'action';
}

/** Vietnamese step type names. */
export function getStepTypeName(type: string): string {
  const map: Record<string, string> = {
    tap_selector: 'CHẠM', tap_ratio: 'CHẠM TỌA ĐỘ', tap_position: 'CHẠM VỊ TRÍ', tap: 'CHẠM',
    long_tap_selector: 'NHẤN GIỮ', swipe_ratio: 'VUỐT',
    input_text: 'NHẬP TEXT', input_selector: 'NHẬP VÀO', key: 'NHẤN PHÍM',
    launch_app: 'MỞ APP', open_url: 'MỞ URL',
    scroll_down: 'CUỘN XUỐNG', scroll_to: 'CUỘN TỚI',
    wait: 'CHỜ', wait_element: 'CHỜ PHẦN TỬ', wait_stable: 'CHỜ ỔN ĐỊNH',
    assert_element: 'KIỂM TRA', dismiss_popup: 'ĐÓNG POPUP',
    double_tap: 'CHẠM ĐÚP', pinch: 'PHÓNG TO/THU', drag: 'KÉO THẢ',
    take_screenshot: 'CHỤP MÀN HÌNH', set_clipboard: 'CLIPBOARD',
    set_variable: 'GÁN BIẾN',
    repeat: 'LẶP', repeat_until: 'LẶP CHO ĐẾN KHI',
    if_element: 'NẾU PHẦN TỬ', if_variable: 'NẾU BIẾN',
    random_pick: 'NGẪU NHIÊN', run_scenario: 'CHẠY KB CON',
    loop: 'VÒNG LẶP', extract: 'TRÍCH XUẤT', save_extraction: 'LƯU DỮ LIỆU',
  };
  return map[type] ?? type.toUpperCase();
}
