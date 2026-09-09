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
  deviceAccounts: (id: string) => ['devices', id, 'accounts'] as const,
  facebookSession: (id: string) =>
    ['devices', id, 'platform-sessions', 'facebook'] as const,
  facebookLoginAttempts: (id: string) =>
    ['devices', id, 'platform-sessions', 'facebook', 'login-attempts'] as const,
  events: (id: string, cursor?: string) =>
    ['accounts', id, 'events', cursor] as const,
  actions: (id: string, cursor?: string) =>
    ['accounts', id, 'actions', cursor] as const,
  actionSummary: (id: string) => ['accounts', id, 'action-summary'] as const,
  candidateSettings: ['accounts', 'candidate-settings'] as const,
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

export function useFacebookCandidateSettings() {
  const { currentOrg } = useOrganization();
  return useQuery({
    queryKey: [...KEYS.candidateSettings, currentOrg?.id],
    queryFn: () => accountsApi.getFacebookCandidateSettings(),
    enabled: Boolean(currentOrg?.id)
  });
}

export function useUpdateFacebookCandidateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      settings: Parameters<
        typeof accountsApi.updateFacebookCandidateSettings
      >[0]
    ) => {
      const updated =
        await accountsApi.updateFacebookCandidateSettings(settings);
      let cursor: string | undefined;
      do {
        const result = await accountsApi.recomputeFacebookCandidates(cursor);
        cursor = result.next_cursor ?? undefined;
      } while (cursor);
      return updated;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.candidateSettings })
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
    onSuccess: (_, { accountId, deviceId }) => {
      qc.invalidateQueries({ queryKey: KEYS.devices(accountId) });
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
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
      qc.invalidateQueries({ queryKey: KEYS.deviceAccounts(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
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
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
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
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
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

export function useFacebookPlatformSession(deviceId: string) {
  return useQuery({
    queryKey: KEYS.facebookSession(deviceId),
    queryFn: () => accountsApi.getFacebookPlatformSession(deviceId),
    enabled: !!deviceId
  });
}

export function useInvalidateFacebookPlatformSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      expectedVersion
    }: {
      deviceId: string;
      expectedVersion?: number;
    }) =>
      accountsApi.invalidateFacebookPlatformSession(deviceId, {
        reason: 'operator_deleted_session',
        expected_version: expectedVersion,
        evidence: { source: 'account_devices_dialog' }
      }),
    onSuccess: (_, { deviceId }) =>
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) })
  });
}

export function useFacebookLoginAttempts(
  deviceId: string,
  opts?: { limit?: number }
) {
  return useQuery({
    queryKey: [
      ...KEYS.facebookLoginAttempts(deviceId),
      opts?.limit ?? 20
    ] as const,
    queryFn: () =>
      accountsApi.listFacebookLoginAttempts(deviceId, {
        limit: opts?.limit ?? 20
      }),
    enabled: !!deviceId
  });
}

export function useStartFacebookLoginAttempt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      accountId,
      evidence
    }: {
      deviceId: string;
      accountId: string;
      evidence?: Record<string, unknown>;
    }) =>
      accountsApi.startFacebookLoginAttempt(deviceId, {
        account_id: accountId,
        evidence
      }),
    onSuccess: (_, { deviceId }) => {
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.facebookLoginAttempts(deviceId) });
    }
  });
}

export function useCompleteFacebookLoginAttempt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      attemptId,
      operatorConfirmed,
      evidence
    }: {
      deviceId: string;
      attemptId: string;
      operatorConfirmed?: boolean;
      evidence?: Record<string, unknown>;
    }) =>
      accountsApi.completeFacebookLoginAttempt(deviceId, attemptId, {
        operator_confirmed: operatorConfirmed,
        evidence
      }),
    onSuccess: (_, { deviceId }) => {
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.facebookLoginAttempts(deviceId) });
    }
  });
}

export function useCancelFacebookLoginAttempt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      deviceId,
      attemptId,
      reason
    }: {
      deviceId: string;
      attemptId: string;
      reason?: string;
    }) =>
      accountsApi.cancelFacebookLoginAttempt(deviceId, attemptId, { reason }),
    onSuccess: (_, { deviceId }) => {
      qc.invalidateQueries({ queryKey: KEYS.facebookSession(deviceId) });
      qc.invalidateQueries({ queryKey: KEYS.facebookLoginAttempts(deviceId) });
    }
  });
}
