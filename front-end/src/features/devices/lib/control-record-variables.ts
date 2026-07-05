export const DEVICE_VARIABLE_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

export type DeviceVarsJsonParser = (
  draft: string,
  parseMessages: any
) => Record<string, unknown>;

/**
 * Template variables are stored as metadata dicts:
 *   {"GROUP_NAME": {"type": "string", "default": "foo", "description": "..."}}
 * Flatten them to plain values so they can be used at runtime:
 *   {"GROUP_NAME": "foo"}
 */
export function flattenVarDefs(vars: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(vars)) {
    if (
      v !== null &&
      typeof v === 'object' &&
      !Array.isArray(v) &&
      'type' in v &&
      'default' in v
    ) {
      out[k] = v.default;
    } else {
      out[k] = v;
    }
  }
  return out;
}

export function mergeTemplateVariablesIntoEditor(
  prev: Record<string, any>,
  templateVars: Record<string, any> | undefined
): Record<string, any> {
  if (!templateVars || Object.keys(templateVars).length === 0) return prev;
  return flattenVarDefs({
    ...prev,
    ...flattenVarDefs(templateVars)
  });
}

export function collectDeclaredDeviceVarKeys(
  drafts: Record<string, string>,
  enabledByDevice: Record<string, boolean>,
  parseMessages: unknown,
  parseJson: DeviceVarsJsonParser
): string[] {
  const keys = new Set<string>();
  for (const [deviceId, draft] of Object.entries(drafts)) {
    if (enabledByDevice[deviceId] !== true) continue;
    let parsed: Record<string, unknown>;
    try {
      parsed = parseJson(draft ?? '{}', parseMessages);
    } catch {
      continue;
    }
    for (const key of Object.keys(parsed)) {
      if (DEVICE_VARIABLE_KEY_RE.test(key)) keys.add(key);
    }
  }
  return Array.from(keys).sort();
}

export function mergeDeclaredDeviceVarKeys(
  variables: Record<string, any>,
  keys: string[]
): Record<string, any> {
  let next: Record<string, any> | null = null;
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(variables, key)) continue;
    next ??= { ...variables };
    next[key] = '';
  }
  return next ?? variables;
}
