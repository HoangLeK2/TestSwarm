'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  accountsApi,
  type AccountCreate,
  type AccountStateTransitionBody,
  type AccountUpdate
} from '../services/api';
import type {
  BulkImportBody,
  RoundRobinBody
} from '../../device-farm/services/generated/DeviceFarmApi';
import { useOrganization } from '@/features/organization/hooks/use-organization';

export const ACCOUNTS_LIST_KEY = ['accounts'] as const;
const ACCOUNTS_STALE_MS = 30_000;

export function accountsListQueryKey(
  orgId: string | null | undefined,
  query?: {
    platform?: string;
    status?: string;
    state?: string;
    tags?: string;
    limit?: number;
    offset?: number;
  }
) {
  return [...ACCOUNTS_LIST_KEY, orgId, query] as const;
}

const KEYS = {
  list: ACCOUNTS_LIST_KEY,
  detail: (id: string) => ['accounts', id] as const,
  devices: (id: string) => ['accounts', id, 'devices'] as const,
  events: (id: string, cursor?: string) =>
    ['accounts', id, 'events', cursor] as const
};

export function useAccounts(query?: {
  platform?: string;
  status?: string;
  state?: string;
  tags?: string;
  limit?: number;
  offset?: number;
}) {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id ?? null;
  return useQuery({
    queryKey: accountsListQueryKey(orgId, query),
    queryFn: () => accountsApi.list(query),
    staleTime: ACCOUNTS_STALE_MS,
    enabled: Boolean(orgId)
  });
}

export function useAccount(accountId: string) {
  return useQuery({
    queryKey: KEYS.detail(accountId),
    queryFn: () => accountsApi.get(accountId),
    enabled: !!accountId
  });
}

export function useAccountEvents(
  accountId: string,
  opts?: { enabled?: boolean; cursor?: string; limit?: number }
) {
  return useQuery({
    queryKey: KEYS.events(accountId, opts?.cursor),
    queryFn: () =>
      accountsApi.listEvents(accountId, {
        limit: opts?.limit ?? 50,
        cursor: opts?.cursor
      }),
    enabled: !!accountId && (opts?.enabled ?? true)
  });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AccountCreate) => accountsApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useUpdateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      data
    }: {
      accountId: string;
      data: AccountUpdate;
    }) => accountsApi.update(accountId, data),
    onSuccess: (_, { accountId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(accountId) });
    }
  });
}

export function useDeleteAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => accountsApi.delete(accountId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useTransitionAccountState() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      body
    }: {
      accountId: string;
      body: AccountStateTransitionBody;
    }) => accountsApi.transitionState(accountId, body),
    onSuccess: (_, { accountId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(accountId) });
      qc.invalidateQueries({ queryKey: KEYS.events(accountId) });
    }
  });
}

export function useBulkImportAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: BulkImportBody) => accountsApi.bulkImport(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useBulkImportAccountsCsv() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => accountsApi.bulkImportCsv(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useRoundRobinAssign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RoundRobinBody) => accountsApi.roundRobin(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: ['devices'] });
    }
  });
}

export function useAccountDevices(accountId: string) {
  return useQuery({
    queryKey: KEYS.devices(accountId),
    queryFn: () => accountsApi.listDevices(accountId),
    enabled: !!accountId
  });
}

export function useAssignDeviceToAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      deviceId,
      isPrimary
    }: {
      accountId: string;
      deviceId: string;
      isPrimary?: boolean;
    }) => accountsApi.assignDevice(accountId, deviceId, isPrimary),
    onSuccess: (_, { accountId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(accountId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useUnassignDeviceFromAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      deviceId
    }: {
      accountId: string;
      deviceId: string;
    }) => accountsApi.unassignDevice(accountId, deviceId),
    onSuccess: (_, { accountId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(accountId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}
