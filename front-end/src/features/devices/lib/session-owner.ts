/** Session owner taxonomy — mirrors backend derive_session_owner_type (DF-T-02-013). */

export const SESSION_OWNER_TYPES = [
  'user',
  'execution',
  'campaign',
  'system',
  'unknown'
] as const;

export type SessionOwnerTypeKey = (typeof SESSION_OWNER_TYPES)[number];

export function resolveSessionUserId(
  payload: Record<string, unknown> | null | undefined
): string | null {
  if (!payload) return null;
  const raw = payload.owner_user_id ?? payload.user_id;
  if (raw == null) return null;
  const s = String(raw).trim();
  return s || null;
}

export function deriveSessionOwnerType(
  sessionId: string | null | undefined,
  userId?: string | null
): SessionOwnerTypeKey {
  if (userId?.trim()) return 'user';
  const sid = (sessionId || '').trim().toLowerCase();
  if (sid.startsWith('exec:') || sid.startsWith('execution:')) return 'execution';
  if (sid.startsWith('camp:') || sid.startsWith('campaign:')) return 'campaign';
  if (sid.startsWith('sys:') || sid.startsWith('system:')) return 'system';
  return 'unknown';
}
