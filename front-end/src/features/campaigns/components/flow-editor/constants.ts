import type { FlowStep } from '../scenario-steps/types';

export const STEP_COLORS: Record<string, string> = {
  tap: 'border-l-blue-500', tap_ratio: 'border-l-blue-500', tap_position: 'border-l-blue-500',
  tap_selector: 'border-l-blue-500', long_tap_selector: 'border-l-blue-500', swipe_ratio: 'border-l-blue-500',
  input_text: 'border-l-cyan-500', input_selector: 'border-l-cyan-500', key: 'border-l-cyan-500',
  launch_app: 'border-l-indigo-500', open_url: 'border-l-indigo-500',
  scroll_down: 'border-l-indigo-500', scroll_to: 'border-l-indigo-500',
  wait: 'border-l-green-500', wait_element: 'border-l-green-500', wait_stable: 'border-l-green-500', verify_screen: 'border-l-green-500',
  assert_element: 'border-l-green-500', dismiss_popup: 'border-l-green-500',
  double_tap: 'border-l-blue-400', pinch: 'border-l-sky-500', drag: 'border-l-blue-600',
  take_screenshot: 'border-l-violet-500', set_clipboard: 'border-l-teal-500',
  set_variable: 'border-l-purple-500',
  set_var: 'border-l-purple-500',
  loop: 'border-l-teal-500',
  extract: 'border-l-fuchsia-500', save_extraction: 'border-l-fuchsia-600',
  extract_text_hierarchy: 'border-l-fuchsia-500',
  extract_text_ocr: 'border-l-fuchsia-500',
  extract_text_ai: 'border-l-fuchsia-500',
  extract_screen_data: 'border-l-fuchsia-500',
  if: 'border-l-amber-500',
  break_if: 'border-l-amber-500',
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
  if: { border: 'border-amber-400/60', bg: 'bg-amber-50/50 dark:bg-amber-950/20', label: 'text-amber-600 dark:text-amber-400' },
  break_if: { border: 'border-amber-400/60', bg: 'bg-amber-50/50 dark:bg-amber-950/20', label: 'text-amber-600 dark:text-amber-400' },
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
  'extract_screen_data',
]);

export function getInsertMenuForUi(): typeof INSERT_MENU {
  if (INSERT_MENU_SHOW_TEXT_EXTRACT_SHORTCUTS) return INSERT_MENU;
  return INSERT_MENU.map((group) => ({
    ...group,
    items: group.items.filter((item) => !_INSERT_MENU_HIDDEN_TYPES.has(item.type)),
  })).filter((group) => group.items.length > 0);
}

export const INSERT_MENU = [
  {
    group: 'Thu thập dữ liệu',
    description: 'Cào và lưu nội dung từ màn hình (tự động lưu khi bật)',
    items: [
      { type: 'extract', label: 'Trích xuất & Lưu dữ liệu' },
      { type: 'save_extraction', label: 'Lưu dữ liệu riêng (nâng cao)' },
      { type: 'extract_text_hierarchy', label: 'Trích xuất text từ hierarchy' },
      { type: 'extract_text_ocr', label: 'OCR text từ screenshot' },
      { type: 'extract_text_ai', label: 'AI extract text' },
      { type: 'extract_screen_data', label: 'Extract dữ liệu màn hình (auto)' },
    ]
  },
  {
    group: 'Hành động',
    description: 'Thao tác trực tiếp lên màn hình',
    items: [
      { type: 'tap_selector', label: 'Chạm phần tử' },
      { type: 'tap_ratio', label: 'Chạm tọa độ' },
      { type: 'tap_position', label: 'Chạm vị trí cố định' },
      { type: 'long_tap_selector', label: 'Nhấn giữ' },
      { type: 'swipe_ratio', label: 'Vuốt' },
      { type: 'input_text', label: 'Nhập văn bản' },
      { type: 'input_selector', label: 'Nhập vào phần tử' },
      { type: 'key', label: 'Nhấn phím' },
      { type: 'launch_app', label: 'Mở ứng dụng' },
      { type: 'open_url', label: 'Mở URL' },
      { type: 'scroll_down', label: 'Cuộn xuống' },
      { type: 'scroll_to', label: 'Cuộn tới phần tử' },
      { type: 'assert_element', label: 'Kiểm tra phần tử' },
      { type: 'dismiss_popup', label: 'Đóng popup' },
      { type: 'double_tap', label: 'Chạm đúp' },
      { type: 'pinch', label: 'Phóng to/thu nhỏ' },
      { type: 'drag', label: 'Kéo thả' },
      { type: 'take_screenshot', label: 'Chụp màn hình' },
      { type: 'set_clipboard', label: 'Ghi clipboard' },
      { type: 'set_variable', label: 'Gán biến' },
      { type: 'set_var', label: 'Gán biến (legacy)' },
    ]
  },
  {
    group: 'Luồng',
    description: 'Điều kiện, lặp, chờ — kiểm soát luồng chạy',
    items: [
      { type: 'wait', label: 'Chờ (giây)' },
      { type: 'wait_element', label: 'Chờ phần tử xuất hiện' },
      { type: 'wait_stable', label: 'Chờ màn hình ổn định' },
      { type: 'verify_screen', label: 'Xác minh màn hình (SSIM)' },
      { type: 'if_element', label: 'Nếu phần tử tồn tại' },
      { type: 'if_variable', label: 'Nếu biến thỏa điều kiện' },
      { type: 'if', label: 'If tổng quát (condition)' },
      { type: 'break_if', label: 'Break nếu thỏa condition' },
      { type: 'loop', label: 'Vòng lặp (hỗ trợ biến)' },
      { type: 'repeat', label: 'Lặp N lần' },
      { type: 'repeat_until', label: 'Lặp cho đến khi' },
      { type: 'random_pick', label: 'Chọn ngẫu nhiên' },
      { type: 'run_scenario', label: 'Chạy kịch bản con' },
    ]
  },
  {
    group: 'Facebook chuyên biệt',
    description: 'Các bước được làm sẵn cho thao tác trên Facebook',
    items: [
      { type: 'tap_fb_comment_button', label: 'Bấm nút Bình luận (tự chuyển "Tất cả bình luận", có nhánh OK / Không thấy)' },
      { type: 'extract_fb_comments', label: 'Thu thập bình luận (đã preset: cuộn, dedupe, gắn bài cha)' },
      { type: 'extract_fb_posts', label: 'Thu thập bài viết (đã preset: mở rộng "Xem thêm", dedupe)' },
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
    case 'set_var': return `${step.key ?? ''} = ${JSON.stringify(step.value ?? '')}`;
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
    case 'tap_fb_comment_button': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      return `OK: ${thenN} bước${elseN ? ` · Không thấy: ${elseN} bước` : ''} · chờ ${step.timeout ?? 6}s`;
    }
    case 'extract': {
      const base = localizeExtractStrategy(step.strategy);
      return step.collection ? `${base} → ${localizeCollection(step.collection)}` : base;
    }
    case 'save_extraction': return `${localizeDataVar(step.data_var)} → ${localizeCollection(step.collection)}`;
    case 'extract_text_hierarchy': return step.save_as ?? 'texts';
    case 'extract_text_ocr': return step.save_as ?? 'ocr_text';
    case 'extract_text_ai': return step.save_as ?? 'ai_text';
    case 'extract_screen_data': return step.save_as ?? 'screen_data';
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
    case 'verify_screen':
      return { target: step.ssim_threshold != null ? `SSIM ≥ ${step.ssim_threshold}` : 'verify screen' };
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
    case 'set_var':
      return { target: step.key ? `${step.key} = ${JSON.stringify(step.value ?? '')}` : '' };
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
    case 'if':
      return { target: Object.keys(step.condition ?? {}).join(', ') || 'condition' };
    case 'break_if':
      return { target: Object.keys(step.condition ?? {}).join(', ') || 'condition' };
    case 'loop':
      return { target: `×${step.count ?? '?'}` };
    case 'tap_fb_comment_button': {
      const thenN = Array.isArray(step.then) ? step.then.length : 0;
      const elseN = Array.isArray(step.else) ? step.else.length : 0;
      return { target: `Bấm Bình luận · OK ${thenN}${elseN ? ` / Không thấy ${elseN}` : ''}` };
    }
    case 'extract': {
      const base = localizeExtractStrategy(step.strategy);
      return { target: step.collection ? `${base} → ${localizeCollection(step.collection)}` : base };
    }
    case 'save_extraction':
      return { target: `${localizeDataVar(step.data_var)} → ${localizeCollection(step.collection)}` };
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
    'wait', 'wait_element', 'wait_stable', 'verify_screen',
    'loop', 'repeat', 'repeat_until',
    'if_element', 'if_variable',
    'if', 'break_if',
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
    scroll_down: 'Cuộn xuống', scroll_to: 'Cuộn tới',
    wait: 'CHỜ', wait_element: 'CHỜ PHẦN TỬ', wait_stable: 'CHỜ ỔN ĐỊNH', verify_screen: 'VERIFY SCREEN',
    assert_element: 'KIỂM TRA', dismiss_popup: 'ĐÓNG POPUP',
    double_tap: 'CHẠM ĐÚP', pinch: 'PHÓNG TO/THU', drag: 'KÉO THẢ',
    take_screenshot: 'CHỤP MÀN HÌNH', set_clipboard: 'CLIPBOARD',
    set_variable: 'Gán biến',
    set_var: 'Gán biến (legacy)',
    repeat: 'LẶP', repeat_until: 'LẶP CHO ĐẾN KHI',
    if_element: 'NẾU PHẦN TỬ', if_variable: 'NẾU BIẾN', if: 'IF', break_if: 'BREAK IF',
    random_pick: 'Chọn ngẫu nhiên', run_scenario: 'Chạy kịch bản con',
    loop: 'VÒNG LẶP', extract: 'TRÍCH XUẤT', save_extraction: 'LƯU DỮ LIỆU (riêng)',
    tap_fb_comment_button: 'BẤM NÚT BÌNH LUẬN (FB)',
    extract_text_hierarchy: 'EXTRACT TEXT HIERARCHY',
    extract_text_ocr: 'EXTRACT TEXT OCR',
    extract_text_ai: 'EXTRACT TEXT AI',
    extract_screen_data: 'EXTRACT SCREEN DATA',
  };
  return map[type] ?? type.toUpperCase();
}
