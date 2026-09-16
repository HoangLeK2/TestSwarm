/** Client-side mirror of backend account FSM allowed targets (DF-T-07-005). */

export const ACCOUNT_STATES = [
  'unassigned',
  'assigned',
  'active',
  'suspended',
  'banned',
  'retired'
] as const;

export type AccountStateKey = (typeof ACCOUNT_STATES)[number];

const ALLOWED_FROM: Record<AccountStateKey, AccountStateKey[]> = {
  unassigned: ['assigned', 'banned', 'retired'],
  assigned: ['unassigned', 'active', 'suspended', 'banned', 'retired'],
  active: ['unassigned', 'assigned', 'suspended', 'banned', 'retired'],
  suspended: ['assigned', 'active', 'banned', 'retired'],
  banned: ['retired'],
  retired: []
};

/** Legacy values still present on old rows and in cached API responses. */
const LEGACY_ALIASES: Record<string, AccountStateKey> = {
  disabled: 'suspended',
  // `cooldown` is no longer a state — resting is an eligibility gate on
  // `cooldown_until`, which an active account carries.
  cooldown: 'active'
};

export function normalizeAccountState(
  state: string | null | undefined
): AccountStateKey | string {
  const raw = (state || 'unassigned').toLowerCase();
  if (raw in LEGACY_ALIASES) return LEGACY_ALIASES[raw];
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

/** True while the account is resting off a usage limit — independent of state. */
export function isResting(
  cooldownUntil: string | null | undefined,
  now: Date = new Date()
): boolean {
  if (!cooldownUntil) return false;
  const until = new Date(cooldownUntil);
  return !Number.isNaN(until.getTime()) && until > now;
}
