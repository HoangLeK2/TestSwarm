'use client';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@/i18n/navigation';
import { tokenStorage } from '@/lib/token-storage';
import { authApi } from '../services/api';
import { ROUTES } from '@/config/routes';
import { consumeAuthReturnTo } from '@/features/content/lib/permalink';
import { acceptPendingOrgInviteAfterAuth } from '@/features/organization/lib/accept-invite-after-auth';

export function useLogin() {
  const router = useRouter();

  return useMutation({
    mutationFn: authApi.login,
    onSuccess: async (data) => {
      tokenStorage.setTokens({
        idToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + 60 * 60 * 1000 // access token 1h
      });
      // Fetch user info and store
      const user = await authApi.me();
      tokenStorage.setUser({
        id: user.id,
        email: user.email,
        givenName: user.name,
        role: user.role,
        orgRole: user.orgRole ?? null
      });
      await acceptPendingOrgInviteAfterAuth();
      const returnTo = consumeAuthReturnTo();
      router.push(returnTo || ROUTES.DEVICES.ROOT);
    }
  });
}
