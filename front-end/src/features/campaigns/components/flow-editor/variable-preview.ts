import { normalizeScenarioVariables } from '@/lib/scenario-variables';

const VARIABLE_REF_RE = /\$\{([A-Za-z][A-Za-z0-9_]*)\}/g;

export type VariablePreviewValues = Record<string, unknown>;

function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function resolveVariablePreviewText(
  text: string,
  values?: VariablePreviewValues | null
): string {
  VARIABLE_REF_RE.lastIndex = 0;
  if (!text || !values || !VARIABLE_REF_RE.test(text)) return text;
  VARIABLE_REF_RE.lastIndex = 0;
  const normalized = normalizeScenarioVariables(values);
  return text.replace(VARIABLE_REF_RE, (match, name: string) => {
    if (!Object.prototype.hasOwnProperty.call(normalized, name)) return match;
    return formatPreviewValue(normalized[name]);
  });
}
