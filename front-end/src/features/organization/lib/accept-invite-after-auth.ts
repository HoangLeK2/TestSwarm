import { acceptOrganizationInvitation } from '../services/farm-org-api';
import { consumeOrgInviteToken } from './invite-token';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

/** Accept a pending org invite after login/register. Returns org id when accepted. */
export async function acceptPendingOrgInviteAfterAuth(): Promise<string | null> {
  const token = consumeOrgInviteToken();
  if (!token) return null;
  try {
    const result = await acceptOrganizationInvitation(token);
    if (typeof window !== 'undefined' && result.organizationId) {
      localStorage.setItem(CURRENT_ORG_STORAGE_KEY, result.organizationId);
    }
    return result.organizationId;
  } catch {
    return null;
  }
}
