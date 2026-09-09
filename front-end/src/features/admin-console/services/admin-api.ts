import { farmApi } from '@/lib/farm-api';
import type { AccountOut } from '@/features/accounts/services/api';
import type { ContentItem } from '@/features/content/services/api';

export type AdminOwnerOut = {
  user_id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  mustChangePassword: boolean;
  created_at?: string | null;
};

export type AdminWorkspaceAdminOut = {
  user_id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  created_at?: string | null;
  joined_at?: string | null;
};

export type AdminWorkspaceMemberOut = {
  id: string;
  userId: string;
  email: string;
  name: string;
  role: string;
  created_at: string;
};

export type AdminWorkspaceScopeRef = {
  workspaceId: string;
  workspaceName: string;
};

export type AdminWorkspaceAccessOut = {
  members: Array<AdminWorkspaceMemberOut & AdminWorkspaceScopeRef>;
  admins: Array<AdminWorkspaceAdminOut & AdminWorkspaceScopeRef>;
};

export type AdminWorkspaceMemberInviteOut = {
  email: string;
  status: string;
  existingUser: boolean;
  emailSent: boolean;
};

export type AdminUserWorkspaceOut = {
  id: string;
  businessName: string;
  status: string;
  joined_at?: string | null;
};

export type AdminUserOut = {
  user_id: string;
  email: string;
  name: string;
  platformRole: string;
  is_active: boolean;
  adminWorkspaceCount: number;
  adminWorkspaces: AdminUserWorkspaceOut[];
  created_at?: string | null;
};

export type AdminUserListOut = {
  items: AdminUserOut[];
  total: number;
  offset: number;
  limit: number;
};

export type AdminUserCreate = {
  email: string;
  name: string;
  password?: string;
  workspaceIds?: string[];
};

export type AdminUserCreated = AdminUserOut & {
  temporaryPassword?: string | null;
};

export type AdminUserPasswordResetOut = {
  admin: AdminUserOut;
  temporaryPassword: string;
};

export type AdminUserWorkspaceBulkResult = {
  workspaceId: string;
  workspaceName?: string | null;
  status: string;
  reason?: string | null;
};

export type AdminUserWorkspaceBulkOut = {
  admin: AdminUserOut;
  assigned: AdminUserWorkspaceBulkResult[];
  removed: AdminUserWorkspaceBulkResult[];
  skipped: AdminUserWorkspaceBulkResult[];
};

export type AdminUserUpdate = {
  name?: string;
  is_active?: boolean;
};

export type AdminWorkspaceOut = {
  id: string;
  businessName: string;
  description: string;
  businessEmail?: string | null;
  businessLogo?: string | null;
  slug?: string | null;
  status: string;
  plan: string;
  /** 'pool' workspaces own relay hosts; 'tenant' workspaces receive phones. */
  kind: string;
  owner?: AdminOwnerOut | null;
  workspaceAdmins: AdminWorkspaceAdminOut[];
  agentCount: number;
  deviceCount: number;
  memberCount: number;
  adminCount: number;
  created_at: string;
  updated_at?: string | null;
};

export type AdminWorkspaceListOut = {
  items: AdminWorkspaceOut[];
  total: number;
  offset: number;
  limit: number;
};

export type AdminWorkspaceCreate = {
  businessName: string;
  kind?: string;
  description?: string;
  businessEmail?: string;
  ownerEmail?: string;
  ownerName?: string;
  ownerPassword?: string;
  adminUserIds?: string[];
};

export type AdminWorkspaceUpdate = {
  businessName?: string;
  description?: string;
  businessEmail?: string;
  status?: string;
  plan?: string;
  kind?: string;
};

export type AdminOwnerUpdate = {
  is_active?: boolean;
  mustChangePassword?: boolean;
};

export type AdminWorkspaceCreated = AdminWorkspaceOut & {
  temporaryPassword?: string | null;
};

export type AdminWorkspaceDependenciesOut = {
  agents: number;
  devices: number;
  members: number;
};

export type AdminWorkspaceMetricOut = {
  workspaceId: string;
  workspaceName?: string | null;
  count: number;
};

export type AdminAccountOut = AccountOut & {
  workspaceId: string;
  workspaceName?: string | null;
};

export type AdminAccountListOut = {
  items: AdminAccountOut[];
  total: number;
  offset: number;
  limit: number;
  byWorkspace: AdminWorkspaceMetricOut[];
};

export type AdminContentItemOut = ContentItem & {
  workspaceId: string;
  workspaceName?: string | null;
};

export type AdminContentListOut = {
  items: AdminContentItemOut[];
  total: number;
  offset: number;
  limit: number;
  byWorkspace: AdminWorkspaceMetricOut[];
};

export type AdminDashboardSummaryOut = {
  totalWorkspaces: number;
  activeWorkspaces: number;
  suspendedWorkspaces: number;
  archivedWorkspaces: number;
  totalAgents: number;
  onlineAgents: number;
  offlineAgents: number;
  staleAgents: number;
  totalDevices: number;
  assignedDevices: number;
  unassignedDevices: number;
  devicesByWorkspace: Array<{
    workspaceId: string;
    workspaceName: string;
    count: number;
  }>;
  agentsByWorkspace: Array<{
    workspaceId: string;
    workspaceName: string;
    count: number;
  }>;
};

export type AdminAgentOut = {
  relay_id: string;
  workspaceId: string;
  workspaceName?: string | null;
  user_id?: string | null;
  enrollment_token_id?: string | null;
  name: string;
  hostname: string;
  ip: string;
  version: string;
  serials: string[];
  status: string;
  health: string;
  /** Control stream open right now — intent (`status`) vs fact. */
  connected: boolean;
  deviceCount: number;
  connected_at?: string | null;
  last_heartbeat_at?: string | null;
  disconnected_at?: string | null;
  created_at?: string | null;
};

export type AdminAgentListOut = {
  items: AdminAgentOut[];
  total: number;
  offset: number;
  limit: number;
};

export type AdminAgentPhoneOut = {
  serial: string;
  deviceId?: string | null;
  registered: boolean;
  name: string;
  brand: string;
  model: string;
  status: string;
  state: string;
  last_seen?: string | null;
  managedByWorkspaceId?: string | null;
  managedByWorkspaceName?: string | null;
  assignedWorkspaceId?: string | null;
  assignedWorkspaceName?: string | null;
};

export type AdminAgentPhoneListOut = {
  items: AdminAgentPhoneOut[];
  total: number;
  offset: number;
  limit: number;
};

export type AdminAgentUpdate = {
  name?: string;
  status?: string;
  workspaceId?: string;
};

export type AdminAgentTokenOut = {
  id: string;
  workspaceId: string;
  workspaceName?: string | null;
  user_id: string;
  name: string;
  prefix: string;
  status: string;
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
};

export type AdminAgentTokenCreated = AdminAgentTokenOut & {
  token: string;
};

export type AdminDeviceOut = {
  id: string;
  serial: string;
  device_serial: string;
  name: string;
  workspaceId: string;
  workspaceName?: string | null;
  managedByWorkspaceId?: string | null;
  managedByWorkspaceName?: string | null;
  user_id?: string | null;
  brand: string;
  model: string;
  android_version: string;
  adb_serial?: string | null;
  relay_serial?: string | null;
  adb_ip?: string | null;
  adb_port: number;
  status: string;
  state: string;
  assigned: boolean;
  /** False for phones a tenant registered on its own relay — admin cannot move them. */
  transferable: boolean;
  last_seen?: string | null;
  paired_at?: string | null;
  unpaired_at?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type AdminAssignableWorkspaceOut = {
  id: string;
  businessName: string;
  status: string;
};

export type AdminAssignableWorkspaceListOut = {
  items: AdminAssignableWorkspaceOut[];
  total: number;
  offset: number;
  limit: number;
};

export type AdminDeviceListOut = {
  items: AdminDeviceOut[];
  total: number;
  offset: number;
  limit: number;
};

export type PlatformAppReleaseOut = {
  id: string;
  platform: string;
  package_name: string;
  version_name: string;
  version_code?: string | null;
  sha256: string;
  size_bytes: number;
  object_key: string;
  original_filename?: string | null;
  content_type_mime: string;
  status: string;
  notes?: string | null;
  uploaded_by_user_id?: string | null;
  published_at?: string | null;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type PlatformAppReleaseListOut = {
  items: PlatformAppReleaseOut[];
  total: number;
  offset: number;
  limit: number;
};

export type PlatformAppDownloadOut = {
  release: PlatformAppReleaseOut;
  download_url: string;
  expires_seconds: number;
};

export type AccountImportFormatOut = {
  id: string;
  slug: string;
  name: string;
  description: string;
  delimiter: string;
  platform: string;
  fields: string[];
  is_active: boolean;
  is_builtin: boolean;
  created_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type AccountImportFormatListOut = {
  items: AccountImportFormatOut[];
};

export type AccountImportFormatCreate = {
  slug: string;
  name: string;
  description?: string;
  delimiter?: string;
  platform?: string;
  fields: string[];
  is_active?: boolean;
};

export type AccountImportFormatUpdate = Partial<
  Omit<AccountImportFormatCreate, 'slug'>
>;

export type ActivityLogListOut = {
  activities: Array<{
    id: string;
    action: string;
    user_id?: string | null;
    org_id?: string | null;
    entity_type?: string | null;
    entity_id?: string | null;
    details?: Record<string, unknown> | null;
    created_at: string;
  }>;
  total: number;
  offset: number;
  limit: number;
};

export type PageParams = {
  search?: string;
  status?: string;
  workspaceId?: string;
  offset?: number;
  limit?: number;
};

export type AgentPhoneListParams = {
  search?: string;
  status?: string;
  assignedWorkspaceId?: string;
  offset?: number;
  limit?: number;
};

/** Codes an operator can act on. Everything else still surfaces as its code. */
const ADMIN_ERROR_MESSAGES: Record<string, string> = {
  AGENT_NOT_IN_POOL_WORKSPACE:
    'Workspace quản lý agent này là workspace khách nên phone của nó ở lại đó. Đánh dấu Loại = Pool cho workspace đó trong trang Workspace là phân bổ được ngay, không cần tạo mã mới.',
  INVALID_WORKSPACE_KIND:
    'Loại workspace không hợp lệ (chỉ nhận pool hoặc tenant).',
  SUPERADMIN_ONLY: 'Chỉ superadmin thực hiện được thao tác này.',
  OBJECT_STORAGE_UNAVAILABLE:
    'Object storage chưa sẵn sàng nên chưa thể lưu APK.',
  PLATFORM_APP_UPLOAD_FAILED: 'Upload APK thất bại.',
  PLATFORM_APP_RELEASE_NOT_FOUND: 'Không tìm thấy bản phát hành APK.',
  PLATFORM_APP_RELEASE_OBJECT_NOT_FOUND:
    'Không tìm thấy file APK trong object storage.',
  PLATFORM_APP_RELEASE_ERROR: 'APK không hợp lệ.',
  AGENT_NOT_FOUND:
    'Không tìm thấy agent này (có thể đã bị xoá). Tải lại danh sách rồi thử lại.',
  DEVICE_MANAGED_BY_ANOTHER_WORKSPACE:
    'Phone này đang do workspace khác quản lý — không phân bổ từ agent này được.'
};

export function formatAdminApiError(error: unknown): string {
  const err = error as {
    response?: { status?: number; data?: { detail?: unknown } };
    message?: string;
  };
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = String((detail as { code?: string }).code);
    return ADMIN_ERROR_MESSAGES[code] ?? code;
  }
  if (err.response?.status) return `Request failed (${err.response.status})`;
  return err.message || 'Request failed';
}

export const adminApi = {
  summary: (params?: { workspaceId?: string }) =>
    farmApi
      .get<AdminDashboardSummaryOut>('/admin/dashboard/summary', {
        params
      })
      .then((r) => r.data),
  listWorkspaces: (params: PageParams) =>
    farmApi
      .get<AdminWorkspaceListOut>('/admin/workspaces', { params })
      .then((r) => r.data),
  getWorkspace: (workspaceId: string) =>
    farmApi
      .get<AdminWorkspaceOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}`
      )
      .then((r) => r.data),
  listAssignableWorkspaces: (params: PageParams = {}) =>
    farmApi
      .get<AdminAssignableWorkspaceListOut>('/admin/workspaces/assignable', {
        params
      })
      .then((r) => r.data),
  createWorkspace: (body: AdminWorkspaceCreate) =>
    farmApi
      .post<AdminWorkspaceCreated>('/admin/workspaces', body)
      .then((r) => r.data),
  updateWorkspace: (workspaceId: string, body: AdminWorkspaceUpdate) =>
    farmApi
      .patch<AdminWorkspaceOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}`,
        body
      )
      .then((r) => r.data),
  workspaceDependencies: (workspaceId: string) =>
    farmApi
      .get<AdminWorkspaceDependenciesOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/dependencies`
      )
      .then((r) => r.data),
  listAccounts: (
    params: PageParams & {
      platform?: string;
      state?: string;
    }
  ) =>
    farmApi
      .get<AdminAccountListOut>('/admin/accounts', { params })
      .then((r) => r.data),
  listContent: (
    params: PageParams & {
      collection?: string;
      platform?: string;
      content_type?: string;
      device_serial?: string;
      campaign_id?: string;
      execution_id?: string;
      content_hash?: string;
      parent_id?: string;
    }
  ) =>
    farmApi
      .get<AdminContentListOut>('/admin/content', { params })
      .then((r) => r.data),
  suspendWorkspace: (workspaceId: string) =>
    farmApi
      .post<AdminWorkspaceOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/suspend`
      )
      .then((r) => r.data),
  reactivateWorkspace: (workspaceId: string) =>
    farmApi
      .post<AdminWorkspaceOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/reactivate`
      )
      .then((r) => r.data),
  archiveWorkspace: (workspaceId: string) =>
    farmApi
      .post<AdminWorkspaceOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/archive`
      )
      .then((r) => r.data),
  resetOwnerPassword: (workspaceId: string, password?: string) =>
    farmApi
      .post<{
        owner: AdminOwnerOut;
        temporaryPassword: string;
      }>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/owner/reset-password`,
        { password: password || undefined }
      )
      .then((r) => r.data),
  updateOwner: (workspaceId: string, body: AdminOwnerUpdate) =>
    farmApi
      .patch<AdminOwnerOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/owner`,
        body
      )
      .then((r) => r.data),
  listAdminUsers: (params: PageParams & { status?: string }) =>
    farmApi
      .get<AdminUserListOut>('/admin/workspace-admins', { params })
      .then((r) => r.data),
  createAdminUser: (body: AdminUserCreate) =>
    farmApi
      .post<AdminUserCreated>('/admin/workspace-admins', body)
      .then((r) => r.data),
  updateAdminUser: (adminUserId: string, body: AdminUserUpdate) =>
    farmApi
      .patch<AdminUserOut>(
        `/admin/workspace-admins/${encodeURIComponent(adminUserId)}`,
        body
      )
      .then((r) => r.data),
  resetAdminUserPassword: (adminUserId: string, password?: string) =>
    farmApi
      .post<AdminUserPasswordResetOut>(
        `/admin/workspace-admins/${encodeURIComponent(adminUserId)}/reset-password`,
        { password: password || undefined }
      )
      .then((r) => r.data),
  bulkAssignAdminUserWorkspaces: (
    adminUserId: string,
    body: { workspaceIds: string[] }
  ) =>
    farmApi
      .post<AdminUserWorkspaceBulkOut>(
        `/admin/workspace-admins/${encodeURIComponent(adminUserId)}/workspaces`,
        body
      )
      .then((r) => r.data),
  bulkRemoveAdminUserWorkspaces: (
    adminUserId: string,
    body: { workspaceIds: string[] }
  ) =>
    farmApi
      .post<AdminUserWorkspaceBulkOut>(
        `/admin/workspace-admins/${encodeURIComponent(adminUserId)}/workspaces/remove`,
        body
      )
      .then((r) => r.data),
  workspaceAccess: (workspaceId?: string) =>
    farmApi
      .get<AdminWorkspaceAccessOut>('/admin/workspace-access', {
        params: workspaceId ? { workspaceId } : undefined
      })
      .then((r) => r.data),
  listWorkspaceAdmins: (workspaceId: string) =>
    farmApi
      .get<
        AdminWorkspaceAdminOut[]
      >(`/admin/workspaces/${encodeURIComponent(workspaceId)}/admins`)
      .then((r) => r.data),
  assignWorkspaceAdmin: (workspaceId: string, userId: string) =>
    farmApi
      .post<AdminWorkspaceAdminOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/admins`,
        { userId }
      )
      .then((r) => r.data),
  removeWorkspaceAdmin: (workspaceId: string, userId: string) =>
    farmApi
      .delete(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/admins/${encodeURIComponent(userId)}`
      )
      .then((r) => r.data),
  listWorkspaceMembers: (workspaceId: string) =>
    farmApi
      .get<
        AdminWorkspaceMemberOut[]
      >(`/admin/workspaces/${encodeURIComponent(workspaceId)}/members`)
      .then((r) => r.data),
  inviteWorkspaceMember: (
    workspaceId: string,
    body: { email: string; role?: string }
  ) =>
    farmApi
      .post<AdminWorkspaceMemberInviteOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/members`,
        body
      )
      .then((r) => r.data),
  updateWorkspaceMember: (
    workspaceId: string,
    userId: string,
    body: { role: string }
  ) =>
    farmApi
      .patch<AdminWorkspaceMemberOut>(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`,
        body
      )
      .then((r) => r.data),
  removeWorkspaceMember: (workspaceId: string, userId: string) =>
    farmApi
      .delete(
        `/admin/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`
      )
      .then((r) => r.data),
  listAgents: (params: PageParams) =>
    farmApi
      .get<AdminAgentListOut>('/admin/agents', { params })
      .then((r) => r.data),
  listAgentPhones: (relayId: string, params: AgentPhoneListParams = {}) =>
    farmApi
      .get<AdminAgentPhoneListOut>(
        `/admin/agents/${encodeURIComponent(relayId)}/phone-allocations`,
        { params }
      )
      .then((r) => r.data),
  assignAgentPhones: (
    relayId: string,
    body: { targetWorkspaceId: string; serials: string[] }
  ) =>
    farmApi
      .post<AdminAgentPhoneListOut>(
        `/admin/agents/${encodeURIComponent(relayId)}/phone-allocations`,
        body
      )
      .then((r) => r.data),
  unassignAgentPhones: (relayId: string, body: { serials: string[] }) =>
    farmApi
      .delete<AdminAgentPhoneListOut>(
        `/admin/agents/${encodeURIComponent(relayId)}/phone-allocations`,
        { data: body }
      )
      .then((r) => r.data),
  updateAgent: (relayId: string, body: AdminAgentUpdate) =>
    farmApi
      .patch<AdminAgentOut>(
        `/admin/agents/${encodeURIComponent(relayId)}`,
        body
      )
      .then((r) => r.data),
  disableAgent: (relayId: string) =>
    farmApi
      .post<AdminAgentOut>(
        `/admin/agents/${encodeURIComponent(relayId)}/disable`
      )
      .then((r) => r.data),
  enableAgent: (relayId: string) =>
    farmApi
      .post<AdminAgentOut>(
        `/admin/agents/${encodeURIComponent(relayId)}/enable`
      )
      .then((r) => r.data),
  deleteAgent: (relayId: string) =>
    farmApi
      .delete(`/admin/agents/${encodeURIComponent(relayId)}`)
      .then((r) => r.data),
  listAgentTokens: (workspaceId?: string) =>
    farmApi
      .get<AdminAgentTokenOut[]>('/admin/agent-activation-tokens', {
        params: { workspaceId }
      })
      .then((r) => r.data),
  createAgentToken: (body: { workspaceId: string; name?: string }) =>
    farmApi
      .post<AdminAgentTokenCreated>('/admin/agent-activation-tokens', body)
      .then((r) => r.data),
  revokeAgentToken: (tokenId: string) =>
    farmApi
      .delete(`/admin/agent-activation-tokens/${encodeURIComponent(tokenId)}`)
      .then((r) => r.data),
  replaceAgentToken: (tokenId: string) =>
    farmApi
      .post<AdminAgentTokenCreated>(
        `/admin/agent-activation-tokens/${encodeURIComponent(tokenId)}/replace`
      )
      .then((r) => r.data),
  listDevices: (params: PageParams & { assigned?: boolean }) =>
    farmApi
      .get<AdminDeviceListOut>('/admin/devices', { params })
      .then((r) => r.data),
  transferDevice: (
    deviceId: string,
    body: { workspaceId?: string; userId?: string }
  ) =>
    farmApi
      .put<AdminDeviceOut>(
        `/admin/devices/${encodeURIComponent(deviceId)}/assignment`,
        body
      )
      .then((r) => r.data),
  listFacebookAppReleases: (
    params: PageParams & { status?: string } = {}
  ) =>
    farmApi
      .get<PlatformAppReleaseListOut>('/admin/platform-apps/facebook/releases', {
        params
      })
      .then((r) => r.data),
  uploadFacebookAppRelease: (file: File, notes?: string) => {
    const form = new FormData();
    form.append('file', file, file.name);
    if (notes?.trim()) form.append('notes', notes.trim());
    return farmApi
      .post<PlatformAppReleaseOut>(
        '/admin/platform-apps/facebook/releases',
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      .then((r) => r.data);
  },
  publishFacebookAppRelease: (releaseId: string) =>
    farmApi
      .post<{ release: PlatformAppReleaseOut }>(
        `/admin/platform-apps/facebook/releases/${encodeURIComponent(releaseId)}/publish`
      )
      .then((r) => r.data.release),
  archiveFacebookAppRelease: (releaseId: string) =>
    farmApi
      .post<{ release: PlatformAppReleaseOut }>(
        `/admin/platform-apps/facebook/releases/${encodeURIComponent(releaseId)}/archive`
      )
      .then((r) => r.data.release),
  getFacebookAppReleaseDownloadUrl: (releaseId: string) =>
    farmApi
      .get<PlatformAppDownloadOut>(
        `/admin/platform-apps/facebook/releases/${encodeURIComponent(releaseId)}/download-url`
      )
      .then((r) => r.data),
  listAccountImportFormats: (includeInactive = true) =>
    farmApi
      .get<AccountImportFormatListOut>('/accounts/import-formats', {
        params: { include_inactive: includeInactive }
      })
      .then((r) => r.data),
  createAccountImportFormat: (body: AccountImportFormatCreate) =>
    farmApi
      .post<AccountImportFormatOut>('/admin/account-import-formats', body)
      .then((r) => r.data),
  updateAccountImportFormat: (
    formatId: string,
    body: AccountImportFormatUpdate
  ) =>
    farmApi
      .patch<AccountImportFormatOut>(
        `/admin/account-import-formats/${encodeURIComponent(formatId)}`,
        body
      )
      .then((r) => r.data),
  auditLog: (params: {
    action?: string;
    resourceType?: string;
    resourceId?: string;
    workspaceId?: string;
    actor?: string;
    offset?: number;
    limit?: number;
  }) =>
    farmApi
      .get<ActivityLogListOut>('/admin/audit-log', { params })
      .then((r) => r.data)
};
