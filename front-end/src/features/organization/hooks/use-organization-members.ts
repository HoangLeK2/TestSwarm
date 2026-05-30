'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  inviteOrganizationMember,
  listOrganizationMembers,
  removeOrganizationMember,
  updateOrganizationMember,
  type OrganizationMemberOut
} from '../services/farm-org-api';

const KEYS = {
  members: ['organization', 'members'] as const
};

export function useOrganizationMembers() {
  return useQuery({
    queryKey: KEYS.members,
    queryFn: listOrganizationMembers
  });
}

export function useInviteOrganizationMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { email: string; role?: string }) =>
      inviteOrganizationMember(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.members });
    }
  });
}

export function useRemoveOrganizationMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => removeOrganizationMember(userId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.members });
    }
  });
}

export function useUpdateOrganizationMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      updateOrganizationMember(userId, { role }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.members });
    }
  });
}

export type { OrganizationMemberOut };
