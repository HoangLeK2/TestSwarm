export type ControlRecordPageSummary = {
  count: number;
  labels: string[];
  label: string;
  contextLabel: string;
  settingsText: string;
  warning?: string;
};

function flattenValue(value: unknown): unknown {
  if (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    'type' in value &&
    'default' in value
  ) {
    return (value as { default?: unknown }).default;
  }
  return value;
}

function numberValue(value: unknown): number | null {
  const flattened = flattenValue(value);
  if (typeof flattened === 'number' && Number.isFinite(flattened)) {
    return Math.max(0, Math.floor(flattened));
  }
  if (typeof flattened === 'string' && flattened.trim() !== '') {
    const parsed = Number(flattened.trim());
    if (Number.isFinite(parsed)) return Math.max(0, Math.floor(parsed));
  }
  return null;
}

function listValue(value: unknown): string[] {
  const flattened = flattenValue(value);
  if (Array.isArray(flattened)) {
    return flattened
      .map((item) => String(flattenValue(item) ?? '').trim())
      .filter(Boolean);
  }
  if (typeof flattened !== 'string') return [];
  const trimmed = flattened.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return listValue(parsed);
    } catch {
      return [trimmed];
    }
  }
  return trimmed
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function stringValue(value: unknown): string {
  const flattened = flattenValue(value);
  return typeof flattened === 'string' ? flattened.trim() : '';
}

export function buildControlRecordPageSummary(
  variables: Record<string, unknown>,
  campaignScoped: boolean
): ControlRecordPageSummary | null {
  const pageTargets = listValue(variables.PAGE_TARGETS);
  const rowTexts = listValue(variables.PAGE_ROW_TEXTS);
  const fallbackTarget = stringValue(variables.PAGE_SEARCH);
  const fallbackRow = stringValue(variables.PAGE_ROW_TEXT);
  const declaredCount = numberValue(variables.PAGE_COUNT);
  const inferredCount = Math.max(
    pageTargets.length,
    rowTexts.length,
    fallbackTarget || fallbackRow ? 1 : 0
  );
  const count = declaredCount ?? inferredCount;
  if (count <= 0) return null;

  const labels = Array.from({ length: count }, (_, index) => {
    const target = pageTargets[index] || rowTexts[index];
    if (target) return target;
    if (count === 1)
      return fallbackTarget || fallbackRow || 'Chưa cấu hình page';
    return `Chưa cấu hình page ${index + 1}`;
  });
  const missing = labels.filter((label) => label.startsWith('Chưa cấu hình'));
  const label = `${count} page: ${labels.join(', ')}`;
  return {
    count,
    labels,
    label,
    contextLabel: `${campaignScoped ? 'Campaign đang áp dụng' : 'Scenario mặc định'}: ${label}`,
    settingsText: label,
    warning:
      missing.length > 0 ? `Thiếu cấu hình ${missing.length} page` : undefined
  };
}
