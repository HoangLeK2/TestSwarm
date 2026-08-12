export type DeviceVarsTargetType = 'group' | 'page' | 'profile';

export type DeviceVarsTargetSnapshot = {
  id: string;
  display_name: string;
  entity_type: DeviceVarsTargetType;
  platform?: string;
  external_id?: string | null;
  canonical_url?: string | null;
};

export type DeviceVarsTargetFormState = {
  platform: 'facebook';
  selected: Record<DeviceVarsTargetType, DeviceVarsTargetSnapshot[]>;
};

export const DEVICE_TARGET_FORM_KEY = '_target_form';

const TARGET_TYPES: DeviceVarsTargetType[] = ['group', 'page', 'profile'];

const CONTROLLED_TARGET_KEYS = new Set([
  DEVICE_TARGET_FORM_KEY,
  'TARGET_ENTITY_ID',
  'TARGET_ENTITY_IDS',
  'TARGET_ENTITY_TYPE',
  'TARGET_ENTITY_TYPES',
  'TARGET_EXTERNAL_ID',
  'TARGET_NAME',
  'TARGET_NAMES',
  'TARGET_PLATFORM',
  'TARGET_URL',
  'TARGET_SEARCH_QUERY',
  'TARGET_SELECTOR_BY',
  'TARGET_SELECTOR_VALUE',
  'TARGET_FALLBACK_SELECTOR_BY',
  'TARGET_FALLBACK_SELECTOR_VALUE',
  'TARGET_LOCATOR',
  'GROUP_NAME',
  'TARGET_GROUP_NAME',
  'GROUP_TARGET_IDS',
  'GROUP_TARGETS',
  'PAGE_TARGET_IDS',
  'PAGE_TARGETS',
  'PROFILE_TARGET_IDS',
  'PROFILE_TARGETS'
]);

export function isDeviceTargetFormControlledKey(key: string): boolean {
  return CONTROLLED_TARGET_KEYS.has(key);
}

export function removeDeviceTargetFormState(
  vars: Record<string, unknown>
): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(vars)) {
    if (!CONTROLLED_TARGET_KEYS.has(key)) next[key] = value;
  }
  return next;
}

function emptySelected(): DeviceVarsTargetFormState['selected'] {
  return {
    group: [],
    page: [],
    profile: []
  };
}

export function emptyDeviceTargetFormState(): DeviceVarsTargetFormState {
  return {
    platform: 'facebook',
    selected: emptySelected()
  };
}

function isTargetType(value: unknown): value is DeviceVarsTargetType {
  return typeof value === 'string' && TARGET_TYPES.includes(value as never);
}

function normalizeSnapshot(
  raw: unknown,
  fallbackType: DeviceVarsTargetType
): DeviceVarsTargetSnapshot | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const id = String(value.id || '').trim();
  const displayName = String(value.display_name || '').trim();
  if (!id || !displayName) return null;
  const entityType = isTargetType(value.entity_type)
    ? value.entity_type
    : fallbackType;
  return {
    id,
    display_name: displayName,
    entity_type: entityType,
    platform: String(value.platform || 'facebook'),
    external_id:
      value.external_id === null || value.external_id === undefined
        ? null
        : String(value.external_id),
    canonical_url:
      value.canonical_url === null || value.canonical_url === undefined
        ? null
        : String(value.canonical_url)
  };
}

function uniqueSnapshots(
  snapshots: DeviceVarsTargetSnapshot[]
): DeviceVarsTargetSnapshot[] {
  const seen = new Set<string>();
  const out: DeviceVarsTargetSnapshot[] = [];
  for (const snapshot of snapshots) {
    const key = `${snapshot.entity_type}:${snapshot.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(snapshot);
  }
  return out;
}

export function readDeviceTargetFormState(
  vars: Record<string, unknown> | null | undefined
): DeviceVarsTargetFormState {
  const raw = vars?.[DEVICE_TARGET_FORM_KEY];
  const out = emptyDeviceTargetFormState();
  if (!raw || typeof raw !== 'object') return out;
  const value = raw as Record<string, unknown>;
  if (value.platform !== 'facebook') return out;
  const selected = value.selected;
  if (!selected || typeof selected !== 'object' || Array.isArray(selected)) {
    return out;
  }
  const byType = selected as Record<string, unknown>;
  for (const type of TARGET_TYPES) {
    const rawList = byType[type];
    if (!Array.isArray(rawList)) continue;
    out.selected[type] = uniqueSnapshots(
      rawList
        .map((item) => normalizeSnapshot(item, type))
        .filter((item): item is DeviceVarsTargetSnapshot => Boolean(item))
    );
  }
  return out;
}

function firstSelected(
  state: DeviceVarsTargetFormState
): DeviceVarsTargetSnapshot | null {
  return (
    state.selected.group[0] ??
    state.selected.page[0] ??
    state.selected.profile[0] ??
    null
  );
}

function locatorVarsForTarget(target: DeviceVarsTargetSnapshot) {
  const name = target.display_name;
  const isGroup =
    target.platform === 'facebook' && target.entity_type === 'group';
  return {
    TARGET_SEARCH_QUERY: name,
    TARGET_SELECTOR_BY: isGroup ? 'descriptionStartsWith' : 'text',
    TARGET_SELECTOR_VALUE: isGroup ? `${name},` : name,
    TARGET_FALLBACK_SELECTOR_BY: isGroup
      ? 'descriptionContains'
      : 'textContains',
    TARGET_FALLBACK_SELECTOR_VALUE: name,
    TARGET_LOCATOR: {
      search_query: name,
      selector: {
        by: isGroup ? 'descriptionStartsWith' : 'text',
        value: isGroup ? `${name},` : name
      },
      fallback_selector: {
        by: isGroup ? 'descriptionContains' : 'textContains',
        value: name
      },
      ...(target.canonical_url ? { canonical_url: target.canonical_url } : {}),
      ...(target.external_id ? { external_id: target.external_id } : {})
    }
  };
}

export function applyDeviceTargetFormState(
  vars: Record<string, unknown>,
  state: DeviceVarsTargetFormState
): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(vars)) {
    if (!CONTROLLED_TARGET_KEYS.has(key)) next[key] = value;
  }

  const selected = {
    group: uniqueSnapshots(state.selected.group),
    page: uniqueSnapshots(state.selected.page),
    profile: uniqueSnapshots(state.selected.profile)
  };
  const allTargets = [...selected.group, ...selected.page, ...selected.profile];

  next[DEVICE_TARGET_FORM_KEY] = {
    platform: 'facebook',
    selected
  };
  next.TARGET_ENTITY_IDS = allTargets.map((target) => target.id);
  next.TARGET_NAMES = allTargets.map((target) => target.display_name);
  next.TARGET_ENTITY_TYPES = allTargets.map((target) => target.entity_type);
  next.GROUP_TARGET_IDS = selected.group.map((target) => target.id);
  next.GROUP_TARGETS = selected.group.map((target) => target.display_name);
  next.PAGE_TARGET_IDS = selected.page.map((target) => target.id);
  next.PAGE_TARGETS = selected.page.map((target) => target.display_name);
  next.PROFILE_TARGET_IDS = selected.profile.map((target) => target.id);
  next.PROFILE_TARGETS = selected.profile.map((target) => target.display_name);

  const first = firstSelected({ platform: 'facebook', selected });
  if (first) {
    next.TARGET_ENTITY_ID = first.id;
    next.TARGET_PLATFORM = first.platform ?? 'facebook';
    next.TARGET_ENTITY_TYPE = first.entity_type;
    next.TARGET_EXTERNAL_ID = first.external_id ?? '';
    next.TARGET_URL = first.canonical_url ?? '';
    next.TARGET_NAME = first.display_name;
    Object.assign(next, locatorVarsForTarget(first));
    if (first.platform === 'facebook' && first.entity_type === 'group') {
      next.GROUP_NAME = first.display_name;
      next.TARGET_GROUP_NAME = first.display_name;
    }
  }

  return next;
}
