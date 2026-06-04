import { formatFarmApiError } from '@/lib/format-farm-api-error';

type ApiDetail = { code?: string };

function extractApiCode(err: unknown): string | undefined {
  const detail = (
    err as { response?: { data?: { detail?: ApiDetail | string } } }
  )?.response?.data?.detail;
  if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
    return detail.code;
  }
  return undefined;
}

/** Maps organization invite/member API error codes to i18n keys under `organization.memberManagement`. */
export function formatOrgMemberInviteError(
  err: unknown,
  t: (key: string) => string,
  fallback: string
): string {
  const code = extractApiCode(err);
  const keyByCode: Record<string, string> = {
    ALREADY_MEMBER: 'alreadyMember',
    INVALID_EMAIL: 'invalidEmail',
    INVALID_ROLE: 'invalidRole',
    NO_ORGANIZATION: 'noOrganization',
    CANNOT_CHANGE_OWN_ROLE: 'cannotChangeOwnRole',
    CANNOT_CHANGE_OWNER: 'cannotEditOwner'
  };
  if (code && keyByCode[code]) {
    return t(keyByCode[code]);
  }
  return formatFarmApiError(err, fallback);
}

/** Maps accept-invitation API codes to `organization.inviteAccept` keys. */
export function formatOrgInviteAcceptError(
  err: unknown,
  t: (key: string) => string,
  fallback: string
): string {
  const code = extractApiCode(err);
  const keyByCode: Record<string, string> = {
    INVITE_NOT_FOUND: 'invalidToken',
    INVITE_EXPIRED: 'expired',
    INVITE_NOT_PENDING: 'expired',
    INVITE_EMAIL_MISMATCH: 'acceptFailed',
    ORG_DISABLED: 'orgDisabled',
    INVALID_TOKEN: 'missingToken'
  };
  if (code && keyByCode[code]) {
    return t(keyByCode[code]);
  }
  return formatFarmApiError(err, fallback);
}
