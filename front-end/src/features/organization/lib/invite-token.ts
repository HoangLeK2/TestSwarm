export const ORG_INVITE_TOKEN_KEY = 'org.inviteToken';

export function saveOrgInviteToken(token: string): void {
  if (typeof window === 'undefined') return;
  const cleaned = token.trim();
  if (!cleaned) return;
  sessionStorage.setItem(ORG_INVITE_TOKEN_KEY, cleaned);
}

export function peekOrgInviteToken(): string | null {
  if (typeof window === 'undefined') return null;
  const value = sessionStorage.getItem(ORG_INVITE_TOKEN_KEY);
  return value?.trim() || null;
}

export function consumeOrgInviteToken(): string | null {
  if (typeof window === 'undefined') return null;
  const value = sessionStorage.getItem(ORG_INVITE_TOKEN_KEY);
  if (value) sessionStorage.removeItem(ORG_INVITE_TOKEN_KEY);
  return value?.trim() || null;
}
