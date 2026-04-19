import { farmApi } from '@/lib/farm-api';

export type AccountGroupRotationStrategy = 'round_robin' | 'least_recent';

export interface AccountGroupOut {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  platform: string;
  rotation_strategy: AccountGroupRotationStrategy;
  rotation_cursor: number;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface AccountGroupCreate {
  name: string;
  description?: string | null;
  platform: string;
  rotation_strategy?: AccountGroupRotationStrategy;
}

export interface AccountGroupUpdate {
  name?: string;
  description?: string | null;
  rotation_strategy?: AccountGroupRotationStrategy;
}

export interface AccountGroupMemberOut {
  account_id: string;
  username: string;
  display_name: string;
  status: string;
  position: number;
  last_used_at: string | null;
  added_at: string;
}

export interface AccountGroupAddMembersBody {
  account_ids: string[];
}

export interface AccountGroupAddMembersResult {
  added: number;
  skipped: number;
}

/** Result of picking one account from the group for a test-run session.
 *  Reuse `variables` across subsequent preview calls in the same session so
 *  every step sees the same account (critical for multi-step login flows). */
export interface AccountGroupResolveResult {
  variables: Record<string, string>;
  account_id: string;
}

export const accountGroupsApi = {
  list: (query?: { platform?: string }) =>
    farmApi
      .get<AccountGroupOut[]>('/account-groups', { params: query })
      .then((r) => r.data),
  get: (groupId: string) =>
    farmApi.get<AccountGroupOut>(`/account-groups/${groupId}`).then((r) => r.data),
  create: (data: AccountGroupCreate) =>
    farmApi.post<AccountGroupOut>('/account-groups', data).then((r) => r.data),
  update: (groupId: string, data: AccountGroupUpdate) =>
    farmApi
      .patch<AccountGroupOut>(`/account-groups/${groupId}`, data)
      .then((r) => r.data),
  delete: (groupId: string) =>
    farmApi.delete(`/account-groups/${groupId}`).then((r) => r.data),
  listMembers: (groupId: string) =>
    farmApi
      .get<AccountGroupMemberOut[]>(`/account-groups/${groupId}/members`)
      .then((r) => r.data),
  addMembers: (groupId: string, data: AccountGroupAddMembersBody) =>
    farmApi
      .post<AccountGroupAddMembersResult>(
        `/account-groups/${groupId}/members`,
        data
      )
      .then((r) => r.data),
  removeMember: (groupId: string, accountId: string) =>
    farmApi
      .delete(`/account-groups/${groupId}/members/${accountId}`)
      .then((r) => r.data),
  /** Pick one usable account and return its __ACCOUNT_* variable bundle.
   *  Advances rotation cursor; cache and reuse `variables` during a session. */
  resolve: (groupId: string) =>
    farmApi
      .post<AccountGroupResolveResult>(`/account-groups/${groupId}/resolve`)
      .then((r) => r.data),
};
