import { farmApi } from '@/lib/farm-api';

export type LoginPayload = { email: string; password: string };
export type RegisterPayload = { email: string; name: string; password: string; role?: string };
export type TokenResponse = { access_token: string; refresh_token: string; token_type: string };
export type UserOut = { id: string; email: string; name: string; role: string; api_key: string };

export const authApi = {
  login: (data: LoginPayload) =>
    farmApi.post<TokenResponse>('/auth/login', data).then((r) => r.data),

  register: (data: RegisterPayload) =>
    farmApi.post<UserOut>('/auth/register', data).then((r) => r.data),

  me: () => farmApi.get<UserOut>('/auth/me').then((r) => r.data)
};
