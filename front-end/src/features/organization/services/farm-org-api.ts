import { farmApi } from '@/lib/farm-api';
import type { ProtoOrganization } from '@/features/device-farm';

export type OrganizationListResponse = {
  items: ProtoOrganization[];
  total: number;
  offset: number;
  limit: number;
};

export type OrganizationListParams = {
  search?: string;
  offset?: number;
  limit?: number;
  ensure_id?: string;
};

export async function listOrganizations(
  params?: OrganizationListParams
): Promise<OrganizationListResponse> {
  const { data } = await farmApi.get<
    OrganizationListResponse | ProtoOrganization[]
  >('/organizations', {
    params
  });
  return normalizeOrganizationListResponse(data, params);
}

/** Supports paginated API and legacy bare array responses. */
export function normalizeOrganizationListResponse(
  data: OrganizationListResponse | ProtoOrganization[] | null | undefined,
  params?: OrganizationListParams
): OrganizationListResponse {
  const offset = params?.offset ?? 0;
  const limit = params?.limit ?? 50;

  if (Array.isArray(data)) {
    return {
      items: data,
      total: data.length,
      offset,
      limit
    };
  }

  const items = data?.items ?? [];
  return {
    items,
    total: data?.total ?? items.length,
    offset: data?.offset ?? offset,
    limit: data?.limit ?? limit
  };
}

export async function createOrganization(payload: {
  businessName: string;
  businessEmail?: string | null;
  businessLogo?: string | null;
}): Promise<ProtoOrganization> {
  const { data } = await farmApi.post<ProtoOrganization>(
    '/organizations',
    payload
  );
  return data;
}

export type OrganizationMemberOut = {
  id: string;
  userId: string;
  email: string;
  name: string;
  role: string;
  created_at: string;
};

export type OrganizationMemberInviteOut = {
  email: string;
  status: string;
  existingUser: boolean;
  emailSent: boolean;
};

export type OrganizationInvitationPreview = {
  organizationName: string;
  email: string;
  status: string;
  expired: boolean;
  existingUser: boolean;
};

export async function listOrganizationMembers(): Promise<
  OrganizationMemberOut[]
> {
  const { data } = await farmApi.get<OrganizationMemberOut[]>(
    '/organizations/members'
  );
  return data;
}

export async function inviteOrganizationMember(payload: {
  email: string;
  role?: string;
}): Promise<OrganizationMemberInviteOut> {
  const { data } = await farmApi.post<OrganizationMemberInviteOut>(
    '/organizations/members',
    payload
  );
  return data;
}

export async function previewOrganizationInvitation(
  token: string
): Promise<OrganizationInvitationPreview> {
  const { data } = await farmApi.get<OrganizationInvitationPreview>(
    `/organizations/invitations/${encodeURIComponent(token)}`
  );
  return data;
}

export async function acceptOrganizationInvitation(
  token: string
): Promise<{ organizationId: string; organizationName: string }> {
  const { data } = await farmApi.post<{
    organizationId: string;
    organizationName: string;
  }>('/organizations/invitations/accept', { token });
  return data;
}

export async function removeOrganizationMember(userId: string): Promise<void> {
  await farmApi.delete(`/organizations/members/${userId}`);
}

export async function updateOrganizationMember(
  userId: string,
  payload: { role: string }
): Promise<OrganizationMemberOut> {
  const { data } = await farmApi.patch<OrganizationMemberOut>(
    `/organizations/members/${userId}`,
    payload
  );
  return data;
}
