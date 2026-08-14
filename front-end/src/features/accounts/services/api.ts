import { farmApi } from '@/lib/farm-api';
import type {
  AccountOut,
  AccountCreate,
  AccountUpdate,
  AccountWithLinksOut,
  AccountStatusUpdate,
  AccountStateTransitionBody,
  AccountStateTransitionOut,
  AccountVerificationOut,
  DeviceAccountOut,
  BulkImportBody,
  BulkImportResult,
  RoundRobinBody
} from '../../device-farm/services/generated/DeviceFarmApi';

export type AccountEventOut = {
  id: string;
  account_id: string;
  event_type: string;
  device_serial: string | null;
  platform: string | null;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type AccountEventListOut = {
  items: AccountEventOut[];
  next_cursor: string | null;
  has_more: boolean;
};

export type AccountActionOut = {
  id: string;
  account_id: string;
  status: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_label?: string | null;
  current_activity: string | null;
  error_code?: string | null;
  error_message: string | null;
  details?: Record<string, unknown>;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type AccountActionListOut = {
  items: AccountActionOut[];
  next_cursor: string | null;
  has_more: boolean;
};

export type AccountActionSummaryOut = {
  total: number;
  pending: number;
  running: number;
  succeeded: number;
  failed: number;
  current_activity: string | null;
};

export type DevicePlatformSessionOut = {
  id: string;
  org_id: string;
  device_id: string;
  platform: string;
  account_id: string | null;
  state: string;
  state_reason: string | null;
  established_at: string | null;
  last_ready_at: string | null;
  last_checked_at: string | null;
  invalidated_at: string | null;
  login_attempt_id: string | null;
  establishment_method: string | null;
  app_package: string;
  app_version: string | null;
  display_name_observed: string | null;
  evidence: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
};

export type DevicePlatformLoginAttemptOut = {
  id: string;
  org_id: string;
  device_id: string;
  platform: string;
  account_id: string;
  state: string;
  reason: string | null;
  reserve_session_id: string | null;
  created_by_user_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  evidence: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
};

export type FacebookCandidateSettings = {
  org_id?: string;
  relationship_weight: number;
  keyword_weight: number;
  semantic_weight: number;
  review_threshold: number;
  auto_ready_enabled: boolean;
  auto_ready_threshold: number;
  auto_ready_min_evidence: number;
  positive_keywords: string[];
  negative_keywords: string[];
  embedding_model: string;
  embedding_dimensions: number;
  updated_at?: string | null;
};

export type FacebookCandidateRecomputeOut = {
  recomputed_count: number;
  next_cursor: string | null;
};

export type {
  AccountOut,
  AccountCreate,
  AccountUpdate,
  AccountWithLinksOut,
  AccountStatusUpdate,
  AccountStateTransitionBody,
  AccountStateTransitionOut,
  AccountVerificationOut,
  DeviceAccountOut,
  BulkImportResult
};

export const accountsApi = {
  list: (query?: {
    platform?: string;
    status?: string;
    state?: string;
    tags?: string;
    limit?: number;
    offset?: number;
  }) =>
    farmApi
      .get<AccountOut[]>('/accounts', { params: query })
      .then((r) => r.data),
  get: (accountId: string) =>
    farmApi
      .get<AccountWithLinksOut>(`/accounts/${accountId}`)
      .then((r) => r.data),
  create: (data: AccountCreate) =>
    farmApi.post<AccountOut>('/accounts', data).then((r) => r.data),
  update: (accountId: string, data: AccountUpdate) =>
    farmApi
      .patch<AccountOut>(`/accounts/${accountId}`, data)
      .then((r) => r.data),
  delete: (accountId: string) =>
    farmApi.delete(`/accounts/${accountId}`).then((r) => r.data),
  /** @deprecated Prefer transitionState — still routed through FSM on the server */
  updateStatus: (accountId: string, status: string, reason?: string) =>
    farmApi
      .patch<AccountOut>(`/accounts/${accountId}/status`, {
        status,
        reason: reason ?? 'UI status change'
      } as AccountStatusUpdate)
      .then((r) => r.data),
  transitionState: (accountId: string, body: AccountStateTransitionBody) =>
    farmApi
      .post<AccountStateTransitionOut>(`/accounts/${accountId}/state`, body)
      .then((r) => r.data),
  bulkImport: (data: BulkImportBody) =>
    farmApi
      .post<BulkImportResult>('/accounts/import', data)
      .then((r) => r.data),
  bulkImportCsv: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return farmApi
      .post<BulkImportResult>('/accounts/import-csv', form, {
        timeout: 120_000
      })
      .then((r) => r.data);
  },
  roundRobin: (data: RoundRobinBody) =>
    farmApi
      .post<Record<string, any>>('/accounts/round-robin', data)
      .then((r) => r.data),
  listDevices: (accountId: string) =>
    farmApi
      .get<DeviceAccountOut[]>(`/accounts/${accountId}/devices`)
      .then((r) => r.data),
  assignDevice: (accountId: string, deviceId: string, isPrimary = false) =>
    farmApi
      .post<DeviceAccountOut>(`/accounts/${accountId}/devices`, {
        device_id: deviceId,
        is_primary: isPrimary
      })
      .then((r) => r.data),
  unassignDevice: (accountId: string, deviceId: string) =>
    farmApi
      .delete(`/accounts/${accountId}/devices/${deviceId}`)
      .then((r) => r.data),
  listDeviceAccounts: (deviceId: string) =>
    farmApi
      .get<DeviceAccountOut[]>(`/devices/${deviceId}/accounts`)
      .then((r) => r.data),
  assignAccount: (deviceId: string, accountId: string, isPrimary = false) =>
    farmApi
      .post<DeviceAccountOut>(`/devices/${deviceId}/accounts`, {
        account_id: accountId,
        is_primary: isPrimary
      })
      .then((r) => r.data),
  setPrimaryAccount: (deviceId: string, accountId: string) =>
    farmApi
      .post<DeviceAccountOut>(`/devices/${deviceId}/accounts/primary`, {
        account_id: accountId
      })
      .then((r) => r.data),
  verifyDeviceAccount: (deviceId: string, accountId: string) =>
    farmApi
      .post<AccountVerificationOut>(
        `/devices/${deviceId}/accounts/${accountId}/verify`
      )
      .then((r) => r.data),
  getFacebookPlatformSession: (deviceId: string) =>
    farmApi
      .get<DevicePlatformSessionOut>(
        `/devices/${deviceId}/platform-sessions/facebook`
      )
      .then((r) => r.data),
  invalidateFacebookPlatformSession: (
    deviceId: string,
    body: {
      reason: string;
      expected_version?: number;
      evidence?: Record<string, unknown>;
    }
  ) =>
    farmApi
      .post<DevicePlatformSessionOut>(
        `/devices/${deviceId}/platform-sessions/facebook/invalidate`,
        body
      )
      .then((r) => r.data),
  listFacebookLoginAttempts: (deviceId: string, query?: { limit?: number }) =>
    farmApi
      .get<
        DevicePlatformLoginAttemptOut[]
      >(`/devices/${deviceId}/platform-sessions/facebook/login-attempts`, { params: query })
      .then((r) => r.data),
  startFacebookLoginAttempt: (
    deviceId: string,
    body: { account_id: string; evidence?: Record<string, unknown> }
  ) =>
    farmApi
      .post<DevicePlatformLoginAttemptOut>(
        `/devices/${deviceId}/platform-sessions/facebook/login-attempts`,
        body
      )
      .then((r) => r.data),
  completeFacebookLoginAttempt: (
    deviceId: string,
    attemptId: string,
    body: { operator_confirmed?: boolean; evidence?: Record<string, unknown> }
  ) =>
    farmApi
      .post<DevicePlatformLoginAttemptOut>(
        `/devices/${deviceId}/platform-sessions/facebook/login-attempts/${attemptId}/complete`,
        body
      )
      .then((r) => r.data),
  cancelFacebookLoginAttempt: (
    deviceId: string,
    attemptId: string,
    body: { reason?: string }
  ) =>
    farmApi
      .post<DevicePlatformLoginAttemptOut>(
        `/devices/${deviceId}/platform-sessions/facebook/login-attempts/${attemptId}/cancel`,
        body
      )
      .then((r) => r.data),
  listEvents: (
    accountId: string,
    query?: { limit?: number; cursor?: string; event_type?: string }
  ) =>
    farmApi
      .get<AccountEventListOut>(`/accounts/${accountId}/events`, {
        params: query
      })
      .then((r) => r.data),
  listActions: (
    accountId: string,
    query?: { limit?: number; cursor?: string }
  ) =>
    farmApi
      .get<AccountActionListOut>(`/accounts/${accountId}/actions`, {
        params: query
      })
      .then((r) => r.data),
  getActionSummary: (accountId: string) =>
    farmApi
      .get<AccountActionSummaryOut>(`/accounts/${accountId}/action-summary`)
      .then((r) => r.data),
  getFacebookCandidateSettings: () =>
    farmApi
      .get<FacebookCandidateSettings>('/facebook-candidate-settings')
      .then((r) => r.data),
  updateFacebookCandidateSettings: (data: FacebookCandidateSettings) =>
    farmApi
      .put<FacebookCandidateSettings>('/facebook-candidate-settings', data)
      .then((r) => r.data),
  recomputeFacebookCandidates: (afterId?: string) =>
    farmApi
      .post<FacebookCandidateRecomputeOut>('/facebook-candidates/recompute', {
        limit: 500,
        after_id: afterId
      })
      .then((r) => r.data)
};
