import type { ProtoOrganization } from '@/features/device-farm';

type PendingOrganizationShellInput = {
  defaultOrgId?: string | null;
  storedOrgId?: string | null;
  userEmail?: string | null;
};

function clean(value: string | null | undefined): string {
  return value?.trim() ?? '';
}

export function createPendingOrganizationShell({
  defaultOrgId,
  storedOrgId,
  userEmail
}: PendingOrganizationShellInput): ProtoOrganization | null {
  const id = clean(defaultOrgId) || clean(storedOrgId);
  if (!id) return null;

  const email = clean(userEmail);
  const label = email || 'Workspace';

  return {
    id,
    businessName: label,
    businessEmail: email || null,
    businessLogo: null,
    created_at: '',
    status: 'loading'
  };
}
