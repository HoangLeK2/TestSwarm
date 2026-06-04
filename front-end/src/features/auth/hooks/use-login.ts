'use client';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@/i18n/navigation';
import { tokenStorage } from '@/lib/token-storage';
import { armAuthRefreshTimer } from '@/lib/farm-api';
import { authApi } from '../services/api';
import { ROUTES } from '@/config/routes';
import { consumeAuthReturnTo } from '@/features/content/lib/permalink';
import { acceptPendingOrgInviteAfterAuth } from '@/features/organization/lib/accept-invite-after-auth';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

export function useLogin() {
  const router = useRouter();

  return useMutation({
    mutationFn: authApi.login,
    onSuccess: async (data) => {
      tokenStorage.setTokens({
        idToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000
      });
      armAuthRefreshTimer(data.expires_in);
      // Fetch user info and store
      const user = await authApi.me();
      tokenStorage.setUser({
        id: user.id,
        email: user.email,
        givenName: user.name,
        role: user.role,
        orgRole: user.orgRole ?? null,
        defaultOrgId: user.defaultOrgId ?? null
      });
      if (typeof window !== 'undefined' && user.defaultOrgId?.trim()) {
        localStorage.setItem(
          CURRENT_ORG_STORAGE_KEY,
          user.defaultOrgId.trim()
        );
      }
      await acceptPendingOrgInviteAfterAuth();
      const returnTo = consumeAuthReturnTo();
      router.push(returnTo || ROUTES.DEVICES.ROOT);
    }
  });
}
