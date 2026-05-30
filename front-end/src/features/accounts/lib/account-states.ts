/** Mirrors backend FSM (DF-T-07-005) for UI validation. */
export const ACCOUNT_STATES = [
  'active',
  'cooldown',
  'suspended',
  'banned',
  'retired'
] as const;

export type AccountStateKey = (typeof ACCOUNT_STATES)[number];

const TRANSITIONS: Record<AccountStateKey, AccountStateKey[]> = {
  active: ['cooldown', 'suspended', 'banned', 'retired'],
  cooldown: ['active', 'suspended', 'retired'],
  suspended: ['active', 'banned', 'retired'],
  banned: ['retired'],
  retired: []
};

export function normalizeAccountState(value: string): AccountStateKey | string {
  if (value === 'disabled') return 'suspended';
  return ACCOUNT_STATES.includes(value as AccountStateKey)
    ? (value as AccountStateKey)
    : value;
}

export function allowedTransitions(from: string): AccountStateKey[] {
  const key = normalizeAccountState(from);
  if (typeof key !== 'string' || !(key in TRANSITIONS)) {
    return [];
  }
  return TRANSITIONS[key as AccountStateKey];
}

export const STATUS_VARIANT: Record<
  string,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  active: 'default',
  cooldown: 'secondary',
  suspended: 'outline',
  banned: 'destructive',
  retired: 'outline',
  disabled: 'outline'
};
