'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  accountGroupsApi,
  type AccountGroupAddMembersBody,
  type AccountGroupCreate,
  type AccountGroupUpdate
} from '../services/api';

const KEYS = {
  list: ['account-groups'] as const,
  detail: (id: string) => ['account-groups', id] as const,
  members: (id: string) => ['account-groups', id, 'members'] as const
};

export function useAccountGroups(
  query?: { platform?: string },
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: [...KEYS.list, query] as const,
    queryFn: () => accountGroupsApi.list(query),
    enabled: options?.enabled ?? true
  });
}

export function useAccountGroup(groupId: string) {
  return useQuery({
    queryKey: KEYS.detail(groupId),
    queryFn: () => accountGroupsApi.get(groupId),
    enabled: !!groupId
  });
}

export function useCreateAccountGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AccountGroupCreate) => accountGroupsApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useUpdateAccountGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      data
    }: {
      groupId: string;
      data: AccountGroupUpdate;
    }) => accountGroupsApi.update(groupId, data),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
    }
  });
}

export function useDeleteAccountGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => accountGroupsApi.delete(groupId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useAccountGroupMembers(groupId: string) {
  return useQuery({
    queryKey: KEYS.members(groupId),
    queryFn: () => accountGroupsApi.listMembers(groupId),
    enabled: !!groupId
  });
}

export function useAddAccountGroupMembers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      data
    }: {
      groupId: string;
      data: AccountGroupAddMembersBody;
    }) => accountGroupsApi.addMembers(groupId, data),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
      qc.invalidateQueries({ queryKey: KEYS.members(groupId) });
    }
  });
}

export function useRemoveAccountGroupMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      groupId,
      accountId
    }: {
      groupId: string;
      accountId: string;
    }) => accountGroupsApi.removeMember(groupId, accountId),
    onSuccess: (_, { groupId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(groupId) });
      qc.invalidateQueries({ queryKey: KEYS.members(groupId) });
    }
  });
}
