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
export { ACCOUNTS_PAGE_LIMIT } from '../lib/account-query';

export const ACCOUNTS_LIST_KEY = ['accounts'] as const;
const ACCOUNTS_STALE_MS = 30_000;

export function accountsListQueryKey(
  orgId: string | null | undefined,
  query?: {
    platform?: string;
    status?: string;
    state?: string;
    tags?: string;
    search?: string;
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
  availableDevices: (
    id: string,
    params: { q?: string; limit?: number; offset?: number }
  ) => ['accounts', id, 'available-devices', params] as const,
  availableDevicesBase: (id: string) =>
    ['accounts', id, 'available-devices'] as const,
  deviceAccounts: (id: string) => ['devices', id, 'accounts'] as const,
  events: (id: string, cursor?: string) =>
    ['accounts', id, 'events', cursor] as const,
  actions: (id: string, cursor?: string) =>
    ['accounts', id, 'actions', cursor] as const,
  actionSummary: (id: string) => ['accounts', id, 'action-summary'] as const,
  runs: (id: string) => ['accounts', id, 'runs'] as const,
  runSteps: (executionId: string) =>
    ['executions', executionId, 'steps'] as const,
  runTaskLog: (executionId: string) =>
    ['executions', executionId, 'task-log'] as const,
  importFormats: ['accounts', 'import-formats'] as const
};

export function useAccounts(query?: {
  platform?: string;
  status?: string;
  state?: string;
  tags?: string;
  search?: string;
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

export function useAccountActions(
  accountId: string,
  opts?: { enabled?: boolean; cursor?: string; limit?: number }
) {
  return useQuery({
    queryKey: KEYS.actions(accountId, opts?.cursor),
    queryFn: () =>
      accountsApi.listActions(accountId, {
        limit: opts?.limit ?? 25,
        cursor: opts?.cursor
      }),
    enabled: !!accountId && (opts?.enabled ?? true)
  });
}

/** Runs this account performed, newest first. Hop one of a ban trace. */
export function useAccountRuns(
  accountId: string,
  opts?: { enabled?: boolean; limit?: number }
) {
  return useQuery({
    queryKey: KEYS.runs(accountId),
    queryFn: () => accountsApi.listRuns(accountId, opts?.limit ?? 50),
    enabled: !!accountId && (opts?.enabled ?? true)
  });
}

/** Every persisted step of one run. Hop two: what the account actually did. */
export function useAccountRunSteps(
  executionId: string | null,
  opts?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: KEYS.runSteps(executionId ?? ''),
    queryFn: () => accountsApi.listRunSteps(executionId as string),
    // Finished runs never change; only a live one is worth refetching.
    staleTime: 60_000,
    enabled: !!executionId && (opts?.enabled ?? true)
  });
}

/** The full trace of one run — every depth. See accountsApi.getRunTaskLog. */
export function useAccountRunTaskLog(
  executionId: string | null,
  opts?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: KEYS.runTaskLog(executionId ?? ''),
    queryFn: () => accountsApi.getRunTaskLog(executionId as string),
    staleTime: 60_000,
    enabled: !!executionId && (opts?.enabled ?? true)
  });
}

export function useAccountActionSummary(
  accountId: string,
  opts?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: KEYS.actionSummary(accountId),
    queryFn: () => accountsApi.getActionSummary(accountId),
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

export function useAccountImportFormats() {
  return useQuery({
    queryKey: KEYS.importFormats,
    queryFn: () => accountsApi.listImportFormats(),
    staleTime: 60_000
  });
}

export function useBulkImportAccountsTxt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, formatSlug }: { file: File; formatSlug: string }) =>
      accountsApi.bulkImportTxt(file, formatSlug),
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

export function useAvailableAccountDevices(
  accountId: string,
  params: { q?: string; limit?: number; offset?: number },
  opts?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: KEYS.availableDevices(accountId, params),
    queryFn: () => accountsApi.listAvailableDevices(accountId, params),
    enabled: !!accountId && (opts?.enabled ?? true),
    placeholderData: (previous) => previous
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
      qc.invalidateQueries({ queryKey: KEYS.availableDevicesBase(accountId) });
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
    onSuccess: (_, { accountId, deviceId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(accountId) });
      qc.invalidateQueries({ queryKey: KEYS.availableDevicesBase(accountId) });
      qc.invalidateQueries({ queryKey: KEYS.deviceAccounts(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useDeviceAccounts(deviceId: string) {
  return useQuery({
    queryKey: KEYS.deviceAccounts(deviceId),
    queryFn: () => accountsApi.listDeviceAccounts(deviceId),
    enabled: !!deviceId
  });
}

export function useAssignAccountsToDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      deviceId,
      accountIds
    }: {
      deviceId: string;
      accountIds: string[];
    }) =>
      Promise.all(
        accountIds.map((accountId) =>
          accountsApi.assignAccount(deviceId, accountId)
        )
      ),
    onSuccess: (_, { deviceId, accountIds }) => {
      qc.invalidateQueries({ queryKey: KEYS.deviceAccounts(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
      accountIds.forEach((accountId) =>
        qc.invalidateQueries({ queryKey: KEYS.devices(accountId) })
      );
    }
  });
}

export function useSetPrimaryDeviceAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      accountId
    }: {
      deviceId: string;
      accountId: string;
    }) => accountsApi.setPrimaryAccount(deviceId, accountId),
    onSuccess: (_, { deviceId, accountId }) => {
      qc.invalidateQueries({ queryKey: KEYS.deviceAccounts(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.devices(accountId) });
    }
  });
}

export function useVerifyDeviceAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      accountId
    }: {
      deviceId: string;
      accountId: string;
    }) => accountsApi.verifyDeviceAccount(deviceId, accountId),
    onSuccess: (_, { deviceId }) =>
      qc.invalidateQueries({ queryKey: KEYS.deviceAccounts(deviceId) })
  });
}
