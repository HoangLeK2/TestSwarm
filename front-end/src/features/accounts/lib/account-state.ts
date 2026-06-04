/** Mirrors backend FSM (DF-T-07-005). */
export const ACCOUNT_STATES = [
  'active',
  'cooldown',
  'suspended',
  'banned',
  'retired'
] as const;

export type AccountStateKey = (typeof ACCOUNT_STATES)[number];

const TRANSITIONS: Record<AccountStateKey, readonly AccountStateKey[]> = {
  active: ['cooldown', 'suspended', 'banned', 'retired'],
  cooldown: ['active', 'suspended', 'retired'],
  suspended: ['active', 'banned', 'retired'],
  banned: ['retired'],
  retired: []
};

export function accountEffectiveState(account: {
  state?: string;
  status: string;
}): AccountStateKey {
  const raw = (account.state || account.status || 'active').toLowerCase();
  if (raw === 'disabled') return 'suspended';
  if ((ACCOUNT_STATES as readonly string[]).includes(raw)) {
    return raw as AccountStateKey;
  }
  return 'active';
}

export function allowedTransitions(from: AccountStateKey): AccountStateKey[] {
  return [...(TRANSITIONS[from] ?? [])];
}

export function requiresTtl(to: AccountStateKey): boolean {
  return to === 'cooldown';
}
