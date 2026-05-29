import { farmApi } from '@/lib/farm-api';
import type {
  AccountOut,
  AccountCreate,
  AccountUpdate,
  AccountWithLinksOut,
  AccountStatusUpdate,
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

export type {
  AccountOut,
  AccountCreate,
  AccountUpdate,
  AccountWithLinksOut,
  AccountStatusUpdate,
  DeviceAccountOut,
  BulkImportResult
};

export const accountsApi = {
  list: (query?: {
    platform?: string;
    status?: string;
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
  updateStatus: (accountId: string, status: string) =>
    farmApi
      .patch<AccountOut>(`/accounts/${accountId}/status`, {
        status
      } as AccountStatusUpdate)
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
        headers: { 'Content-Type': 'multipart/form-data' }
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
  listEvents: (
    accountId: string,
    query?: { limit?: number; cursor?: string; event_type?: string }
  ) =>
    farmApi
      .get<AccountEventListOut>(`/accounts/${accountId}/events`, {
        params: query
      })
      .then((r) => r.data)
};
