export type ControlRecordPageSummary = {
  count: number;
  labels: string[];
  label: string;
  targetType: 'group' | 'page';
  targetNoun: string;
  targetInputKind: 'catalog' | 'manual';
  sourceKind: 'campaign' | 'scenario';
  contextLabel: string;
  sourceLabel: string;
  sourceDescription: string;
  bindingKeys: string[];
  usedBindingKeys: string[];
  unusedBindingKeys: string[];
  settingsText: string;
  warning?: string;
  usageWarning?: string;
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

function targetFormSelectedCount(
  variables: Record<string, unknown>,
  targetType: 'group' | 'page'
): number {
  const raw = flattenValue(variables._target_form);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return 0;
  const selected = (raw as Record<string, unknown>).selected;
  if (!selected || typeof selected !== 'object' || Array.isArray(selected)) {
    return 0;
  }
  const rawTargets = (selected as Record<string, unknown>)[targetType];
  return Array.isArray(rawTargets) ? rawTargets.length : 0;
}

function summarizeTargetValues(variables: Record<string, unknown>) {
  const pageTargets = listValue(variables.PAGE_TARGETS);
  const pageRows = listValue(variables.PAGE_ROW_TEXTS);
  const pageTargetIds = listValue(variables.PAGE_TARGET_IDS);
  const pageCatalogCount = Math.max(
    pageTargetIds.length,
    targetFormSelectedCount(variables, 'page')
  );
  const pageFallbackTarget = stringValue(variables.PAGE_SEARCH);
  const pageFallbackRow = stringValue(variables.PAGE_ROW_TEXT);
  const pageDeclaredCount = numberValue(variables.PAGE_COUNT);
  const pageInferredCount = Math.max(
    pageTargets.length,
    pageRows.length,
    pageFallbackTarget || pageFallbackRow ? 1 : 0
  );

  const groupSearches = listValue(variables.GROUP_SEARCHES);
  const groupRows = listValue(variables.GROUP_ROW_TEXTS);
  const groupTargets = listValue(variables.GROUP_TARGETS);
  const groupTargetIds = listValue(variables.GROUP_TARGET_IDS);
  const groupCatalogCount = Math.max(
    groupTargetIds.length,
    targetFormSelectedCount(variables, 'group')
  );
  const groupFallbackTarget =
    stringValue(variables.TARGET_SEARCH_QUERY) ||
    stringValue(variables.TARGET_GROUP_NAME) ||
    stringValue(variables.GROUP_NAME);
  const groupFallbackRow = stringValue(variables.TARGET_GROUP_NAME);
  const groupDeclaredCount = numberValue(variables.GROUP_COUNT);
  const groupInferredCount = Math.max(
    groupSearches.length,
    groupRows.length,
    groupTargets.length,
    groupFallbackTarget || groupFallbackRow ? 1 : 0
  );

  if ((pageDeclaredCount ?? pageInferredCount) > 0) {
    return {
      targetType: 'page' as const,
      targetNoun: 'page',
      targetInputKind:
        pageCatalogCount > 0 ? ('catalog' as const) : ('manual' as const),
      targets: pageTargets,
      rows: pageRows,
      fallbackTarget: pageFallbackTarget,
      fallbackRow: pageFallbackRow,
      declaredCount: pageDeclaredCount,
      inferredCount: pageInferredCount,
      bindingKeys: [
        pageDeclaredCount != null ? 'PAGE_COUNT' : null,
        pageTargets.length > 0 ? 'PAGE_TARGETS' : null,
        pageRows.length > 0 ? 'PAGE_ROW_TEXTS' : null,
        pageFallbackTarget ? 'PAGE_SEARCH' : null,
        pageFallbackRow ? 'PAGE_ROW_TEXT' : null
      ].filter((key): key is string => Boolean(key))
    };
  }

  return {
    targetType: 'group' as const,
    targetNoun: 'group',
    targetInputKind:
      groupCatalogCount > 0 ? ('catalog' as const) : ('manual' as const),
    targets: groupSearches.length > 0 ? groupSearches : groupTargets,
    rows: groupRows.length > 0 ? groupRows : groupTargets,
    fallbackTarget: groupFallbackTarget,
    fallbackRow: groupFallbackRow,
    declaredCount: groupDeclaredCount,
    inferredCount: groupInferredCount,
    bindingKeys: [
      groupDeclaredCount != null ? 'GROUP_COUNT' : null,
      groupSearches.length > 0 ? 'GROUP_SEARCHES' : null,
      groupRows.length > 0 ? 'GROUP_ROW_TEXTS' : null,
      groupTargets.length > 0 ? 'GROUP_TARGETS' : null,
      stringValue(variables.TARGET_SEARCH_QUERY) ? 'TARGET_SEARCH_QUERY' : null,
      stringValue(variables.TARGET_GROUP_NAME) ? 'TARGET_GROUP_NAME' : null,
      stringValue(variables.GROUP_NAME) ? 'GROUP_NAME' : null
    ].filter((key): key is string => Boolean(key))
  };
}

export function buildControlRecordPageSummary(
  variables: Record<string, unknown>,
  campaignScoped: boolean,
  campaignName?: string | null,
  usedVariableNames?: Iterable<string>
): ControlRecordPageSummary | null {
  const target = summarizeTargetValues(variables);
  const { targetType, targetNoun, targets, rows, fallbackTarget, fallbackRow } =
    target;
  const { declaredCount, inferredCount, bindingKeys, targetInputKind } = target;
  const count = declaredCount ?? inferredCount;
  if (count <= 0) return null;

  const labels = Array.from({ length: count }, (_, index) => {
    const label = targets[index] || rows[index];
    if (label) return label;
    if (count === 1)
      return fallbackTarget || fallbackRow || `Chưa cấu hình ${targetNoun}`;
    return `Chưa cấu hình ${targetNoun} ${index + 1}`;
  });
  const missing = labels.filter((label) => label.startsWith('Chưa cấu hình'));
  const label = `${count} ${targetNoun}: ${labels.join(', ')}`;
  const sourceLabel =
    campaignScoped && campaignName?.trim()
      ? `Campaign: ${campaignName.trim()}`
      : campaignScoped
        ? 'Campaign đang áp dụng'
        : 'Scenario mặc định';
  const sourceKind = campaignScoped ? 'campaign' : 'scenario';
  const usedNameSet = usedVariableNames ? new Set(usedVariableNames) : null;
  const usedBindingKeys = usedNameSet
    ? bindingKeys.filter((key) => usedNameSet.has(key))
    : [];
  const unusedBindingKeys = usedNameSet
    ? bindingKeys.filter((key) => !usedNameSet.has(key))
    : [];
  const usageWarning =
    usedNameSet && bindingKeys.length > 0 && usedBindingKeys.length === 0
      ? 'Đã cấu hình target nhưng flow hiện tại chưa dùng các biến này'
      : undefined;
  return {
    count,
    labels,
    label,
    targetType,
    targetNoun,
    targetInputKind,
    sourceKind,
    contextLabel: `${sourceLabel}: ${label}`,
    sourceLabel,
    sourceDescription: campaignScoped
      ? `Các ${targetNoun} này lấy từ biến của campaign và ghi đè giá trị mặc định khi chạy kịch bản trong campaign này.`
      : `Các ${targetNoun} này lấy từ biến mặc định lưu trong kịch bản.`,
    bindingKeys,
    usedBindingKeys,
    unusedBindingKeys,
    settingsText: label,
    warning:
      missing.length > 0 ? `Thiếu cấu hình ${missing.length} page` : undefined,
    usageWarning
  };
}
