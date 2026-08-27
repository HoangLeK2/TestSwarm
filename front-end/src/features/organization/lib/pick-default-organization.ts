import type { ProtoOrganization } from '@/features/device-farm';

function isPersonalWorkspaceName(name: string | undefined | null): boolean {
  return Boolean(name?.trim().endsWith("'s Workspace"));
}

/** Org the user was invited into (owner email differs from signed-in user). */
function collaborationOrgs(
  organizations: ProtoOrganization[],
  userEmail: string | null | undefined
): ProtoOrganization[] {
  const email = (userEmail ?? '').trim().toLowerCase();
  if (!email) return [];
  return organizations.filter(
    (o) => (o.businessEmail ?? '').trim().toLowerCase() !== email
  );
}

/**
 * Choose active org for API tenancy headers.
 * Priority: server default_org_id → invited workspace → stored → first listed.
 */
export function pickDefaultOrganization(
  organizations: ProtoOrganization[],
  storedId: string | null,
  options?: {
    preferredOrgId?: string | null;
    userEmail?: string | null;
  }
): ProtoOrganization {
  const preferred = (options?.preferredOrgId ?? '').trim();
  if (preferred) {
    const fromDefault = organizations.find((o) => o.id === preferred);
    if (fromDefault) return fromDefault;
  }

  const invited = collaborationOrgs(organizations, options?.userEmail);
  if (invited.length === 1) return invited[0];
  if (invited.length > 1) {
    const nonPersonalInvited = invited.filter(
      (o) => !isPersonalWorkspaceName(o.businessName)
    );
    if (nonPersonalInvited.length === 1) return nonPersonalInvited[0];
    if (nonPersonalInvited.length > 0) return nonPersonalInvited[0];
    return invited[0];
  }

  if (storedId) {
    const fromStorage = organizations.find((o) => o.id === storedId);
    if (fromStorage) return fromStorage;
  }

  const shared = organizations.filter(
    (o) => !isPersonalWorkspaceName(o.businessName)
  );
  return shared[0] ?? organizations[0];
}

export function reconcileCurrentOrganization(
  organizations: ProtoOrganization[],
  current: ProtoOrganization | null,
  storedId: string | null,
  options?: {
    preferredOrgId?: string | null;
    userEmail?: string | null;
  }
): ProtoOrganization {
  if (current) {
    const refreshed = organizations.find((org) => org.id === current.id);
    if (refreshed) return refreshed;
  }
  return pickDefaultOrganization(organizations, storedId, options);
}
