import { farmApi } from '@/lib/farm-api';
import type { ProtoOrganization } from '@/features/device-farm';

export async function listOrganizations(): Promise<ProtoOrganization[]> {
  const { data } = await farmApi.get<ProtoOrganization[]>('/organizations');
  return data;
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
