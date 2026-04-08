
export type ScenarioStepsValidation =
  | { ok: true }
  | { ok: false; message: string };

function nonempty(s: unknown): string {
  return String(s ?? '').trim();
}

function validateStepsArray(steps: unknown, path: string): ScenarioStepsValidation {
  if (!Array.isArray(steps)) {
    return { ok: false, message: `${path}: danh sách bước không hợp lệ` };
  }
  for (let i = 0; i < steps.length; i++) {
    const r = validateStep(steps[i], `${path} → bước ${i + 1}`);
    if (!r.ok) return r;
  }
  return { ok: true };
}

function validateConditionDict(cond: unknown, path: string): ScenarioStepsValidation {
  if (!cond || typeof cond !== 'object') return { ok: true };
  const c = cond as Record<string, unknown>;
  const ex = c.element_exists;
  if (ex && typeof ex === 'object') {
    const v = nonempty((ex as { value?: unknown }).value);
    if (!v) {
      return { ok: false, message: `${path}: điều kiện element_exists — value không được để trống` };
    }
  }
  const nex = c.element_not_exists;
  if (nex && typeof nex === 'object') {
    const v = nonempty((nex as { value?: unknown }).value);
    if (!v) {
      return { ok: false, message: `${path}: điều kiện element_not_exists — value không được để trống` };
    }
  }
  return { ok: true };
}

function validateStep(raw: unknown, path: string): ScenarioStepsValidation {
  if (raw === null || typeof raw !== 'object') {
    return { ok: false, message: `${path}: bước không hợp lệ` };
  }
  const s = raw as Record<string, unknown>;
  const t = s.type;

  switch (t) {
    case 'if_element': {
      const v = nonempty(s.value);
      if (!v) {
        return { ok: false, message: `${path} (if_element): giá trị selector (value) không được để trống` };
      }
      const then = s.then;
      if (!Array.isArray(then) || then.length < 1) {
        return { ok: false, message: `${path} (if_element): nhánh "then" cần ít nhất 1 bước` };
      }
      const rThen = validateStepsArray(then, `${path} (if_element) → then`);
      if (!rThen.ok) return rThen;
      const els = s.else;
      if (els != null && Array.isArray(els) && els.length > 0) {
        const rElse = validateStepsArray(els, `${path} (if_element) → else`);
        if (!rElse.ok) return rElse;
      }
      return { ok: true };
    }
    case 'if_variable': {
      const name = nonempty(s.name);
      if (!name) {
        return { ok: false, message: `${path} (if_variable): tên biến không được để trống` };
      }
      const then = s.then;
      if (!Array.isArray(then) || then.length < 1) {
        return { ok: false, message: `${path} (if_variable): nhánh "then" cần ít nhất 1 bước` };
      }
      const rThen = validateStepsArray(then, `${path} (if_variable) → then`);
      if (!rThen.ok) return rThen;
      const els = s.else;
      if (els != null && Array.isArray(els) && els.length > 0) {
        const rElse = validateStepsArray(els, `${path} (if_variable) → else`);
        if (!rElse.ok) return rElse;
      }
      return { ok: true };
    }
    case 'repeat': {
      const count = Number(s.count ?? 0);
      if (!Number.isFinite(count) || count < 1) {
        return { ok: false, message: `${path} (repeat): count phải ≥ 1` };
      }
      const inner = s.steps;
      if (!Array.isArray(inner) || inner.length < 1) {
        return { ok: false, message: `${path} (repeat): cần ít nhất 1 bước bên trong` };
      }
      return validateStepsArray(inner, `${path} (repeat)`);
    }
    case 'repeat_until': {
      const inner = s.steps;
      if (!Array.isArray(inner) || inner.length < 1) {
        return { ok: false, message: `${path} (repeat_until): cần ít nhất 1 bước bên trong` };
      }
      const rc = validateConditionDict(s.condition, `${path} (repeat_until) condition`);
      if (!rc.ok) return rc;
      return validateStepsArray(inner, `${path} (repeat_until)`);
    }
    case 'random_pick': {
      const branches = s.branches;
      if (!Array.isArray(branches) || branches.length < 1) {
        return { ok: false, message: `${path} (random_pick): cần ít nhất 1 nhánh` };
      }
      for (let b = 0; b < branches.length; b++) {
        const br = branches[b] as Record<string, unknown>;
        const inner = br?.steps;
        if (!Array.isArray(inner) || inner.length < 1) {
          return {
            ok: false,
            message: `${path} (random_pick) nhánh ${b + 1}: mỗi nhánh cần ít nhất 1 bước`,
          };
        }
        const r = validateStepsArray(inner, `${path} (random_pick) nhánh ${b + 1}`);
        if (!r.ok) return r;
      }
      return { ok: true };
    }
    case 'run_scenario': {
      const id = nonempty(s.scenario_id);
      const name = nonempty(s.scenario_name);
      if (!id && !name) {
        return { ok: false, message: `${path} (run_scenario): cần scenario_id hoặc scenario_name` };
      }
      return { ok: true };
    }
    case 'launch_app': {
      if (!nonempty(s.package)) {
        return { ok: false, message: `${path} (launch_app): package không được để trống` };
      }
      return { ok: true };
    }
    case 'open_url': {
      const url = nonempty(s.url);
      if (!url) {
        return { ok: false, message: `${path} (open_url): url không được để trống` };
      }
      const u = url.toLowerCase();
      if (!u.startsWith('http://') && !u.startsWith('https://')) {
        return { ok: false, message: `${path} (open_url): url phải bắt đầu bằng http:// hoặc https://` };
      }
      return { ok: true };
    }
    case 'tap': {
      const sel = s.selector;
      if (sel && typeof sel === 'object') {
        const val = nonempty((sel as { value?: unknown }).value);
        if (!val) {
          return { ok: false, message: `${path} (tap): selector.value không được để trống` };
        }
      }
      return { ok: true };
    }
    case 'tap_selector':
    case 'wait_element':
    case 'assert_element':
    case 'long_tap_selector':
    case 'scroll_to': {
      if (!nonempty(s.value)) {
        return { ok: false, message: `${path} (${String(t)}): value không được để trống` };
      }
      return { ok: true };
    }
    case 'input_selector': {
      if (!nonempty(s.value)) {
        return { ok: false, message: `${path} (input_selector): value không được để trống` };
      }
      return { ok: true };
    }
    case 'key': {
      if (!nonempty(s.key)) {
        return { ok: false, message: `${path} (key): key không được để trống` };
      }
      return { ok: true };
    }
    case 'set_variable': {
      if (!nonempty(s.name)) {
        return { ok: false, message: `${path} (set_variable): name không được để trống` };
      }
      return { ok: true };
    }
    default:
      return { ok: true };
  }
}

export function validateScenarioStepsForApi(steps: unknown): ScenarioStepsValidation {
  if (!Array.isArray(steps)) {
    return { ok: false, message: 'Danh sách bước (steps) không hợp lệ' };
  }
  return validateStepsArray(steps, 'Kịch bản');
}

export { formatFarmApiError } from '@/lib/format-farm-api-error';
