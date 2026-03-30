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
  set_variable: 'border-l-purple-500',
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
};

/** Insert menu — Vietnamese. */
export const INSERT_MENU = [
  {
    group: 'Thao tác',
    items: [
      { type: 'tap_selector', label: 'Chạm phần tử', icon: '👆' },
      { type: 'tap_ratio', label: 'Chạm tọa độ', icon: '👆' },
      { type: 'long_tap_selector', label: 'Nhấn giữ', icon: '👇' },
      { type: 'swipe_ratio', label: 'Vuốt', icon: '👉' },
      { type: 'input_text', label: 'Nhập văn bản', icon: '⌨️' },
      { type: 'input_selector', label: 'Nhập vào phần tử', icon: '⌨️' },
      { type: 'key', label: 'Nhấn phím', icon: '⌨️' },
      { type: 'launch_app', label: 'Mở ứng dụng', icon: '📱' },
      { type: 'open_url', label: 'Mở URL', icon: '🌐' },
      { type: 'scroll_down', label: 'Cuộn xuống', icon: '⬇️' },
      { type: 'scroll_to', label: 'Cuộn tới phần tử', icon: '⬇️' },
    ]
  },
  {
    group: 'Chờ & Kiểm tra',
    items: [
      { type: 'wait', label: 'Chờ (giây)', icon: '⏳' },
      { type: 'wait_element', label: 'Chờ phần tử', icon: '🔍' },
      { type: 'assert_element', label: 'Kiểm tra phần tử', icon: '✅' },
      { type: 'dismiss_popup', label: 'Đóng popup', icon: '❌' },
    ]
  },
  {
    group: 'Luồng điều khiển',
    items: [
      { type: 'repeat', label: 'Lặp N lần', icon: '🔄' },
      { type: 'repeat_until', label: 'Lặp cho đến khi', icon: '🔁' },
      { type: 'if_element', label: 'Nếu phần tử tồn tại', icon: '🔀' },
      { type: 'if_variable', label: 'Nếu biến', icon: '🔀' },
      { type: 'random_pick', label: 'Chọn ngẫu nhiên', icon: '🎲' },
      { type: 'run_scenario', label: 'Chạy kịch bản con', icon: '📦' },
    ]
  },
  {
    group: 'Dữ liệu',
    items: [
      { type: 'set_variable', label: 'Gán biến', icon: '📝' },
    ]
  }
];

export function getStepSummary(step: FlowStep): string {
  switch (step.type) {
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
    case 'scroll_down': return `×${step.repeats}`;
    case 'scroll_to': return `[${step.by}] "${step.value}"`;
    case 'dismiss_popup': return '';
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
    default: return '';
  }
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
    set_variable: 'GÁN BIẾN',
    repeat: 'LẶP', repeat_until: 'LẶP CHO ĐẾN KHI',
    if_element: 'NẾU PHẦN TỬ', if_variable: 'NẾU BIẾN',
    random_pick: 'NGẪU NHIÊN', run_scenario: 'CHẠY KB CON',
  };
  return map[type] ?? type.toUpperCase();
}
