import { farmApi } from '@/lib/farm-api';

export type LoginPayload = { email: string; password: string };
export type RegisterPayload = {
  email: string;
  name: string;
  password: string;
  role?: string;
  inviteToken?: string;
};
export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in?: number;
};
export type UserOut = {
  id: string;
  email: string;
  name: string;
  role: string;
  api_key: string;
  orgRole?: string | null;
  defaultOrgId?: string | null;
};

const AUTH_REQUEST_TIMEOUT_MS = 15_000;

export const authApi = {
  login: (data: LoginPayload) =>
    farmApi
      .post<TokenResponse>('/auth/login', data, {
        timeout: AUTH_REQUEST_TIMEOUT_MS,
        _skip429Retry: true
      })
      .then((r) => r.data),

  register: (data: RegisterPayload) =>
    farmApi
      .post<UserOut>('/auth/register', data, {
        timeout: AUTH_REQUEST_TIMEOUT_MS,
        _skip429Retry: true
      })
      .then((r) => r.data),

  me: () =>
    farmApi
      .get<UserOut>('/auth/me', { timeout: AUTH_REQUEST_TIMEOUT_MS })
      .then((r) => r.data),

  logout: (refreshToken?: string | null) =>
    farmApi
      .post('/auth/logout', { refresh_token: refreshToken ?? null })
      .then((r) => r.data)
};
