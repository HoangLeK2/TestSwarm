/** Client-side mirror of backend account FSM allowed targets (DF-T-07-005). */

export const ACCOUNT_STATES = [
  'active',
  'cooldown',
  'suspended',
  'banned',
  'retired'
] as const;

export type AccountStateKey = (typeof ACCOUNT_STATES)[number];

const ALLOWED_FROM: Record<AccountStateKey, AccountStateKey[]> = {
  active: ['cooldown', 'suspended', 'banned', 'retired'],
  cooldown: ['active', 'suspended', 'retired'],
  suspended: ['active', 'banned', 'retired'],
  banned: ['retired'],
  retired: []
};

export function normalizeAccountState(
  state: string | null | undefined
): AccountStateKey | string {
  const raw = (state || 'active').toLowerCase();
  if (raw === 'disabled') return 'suspended';
  if ((ACCOUNT_STATES as readonly string[]).includes(raw)) {
    return raw as AccountStateKey;
  }
  return raw;
}

export function allowedTransitionTargets(
  state: string | null | undefined
): AccountStateKey[] {
  const key = normalizeAccountState(state);
  if (typeof key === 'string' && !(key in ALLOWED_FROM)) {
    return [];
  }
  return ALLOWED_FROM[key as AccountStateKey] ?? [];
}
