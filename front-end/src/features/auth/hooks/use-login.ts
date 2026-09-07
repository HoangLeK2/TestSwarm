'use client';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@/i18n/navigation';
import { tokenStorage } from '@/lib/token-storage';
import { armAuthRefreshTimer } from '@/lib/farm-api';
import { authApi } from '../services/api';
import { ROUTES } from '@/config/routes';
import {
  canUseAdminConsole,
  normalizeNavOrgRole,
  normalizeNavUserRole
} from '@/lib/nav-access';
import { consumeAuthReturnTo } from '@/features/content/lib/permalink';
import { acceptPendingOrgInviteAfterAuth } from '@/features/organization/lib/accept-invite-after-auth';
import { useAuthContext } from '../providers/auth-provider';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

export function useLogin() {
  const router = useRouter();
  const { setUser } = useAuthContext();

  return useMutation({
    mutationFn: authApi.login,
    onSuccess: async (data) => {
      tokenStorage.setTokens({
        idToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000
      });
      if (typeof window !== 'undefined') {
        localStorage.removeItem(CURRENT_ORG_STORAGE_KEY);
      }
      armAuthRefreshTimer(data.expires_in);
      // Fetch user info and store
      const user = await authApi.me();
      const nextUser = {
        id: user.id,
        email: user.email,
        givenName: user.name,
        role: user.role,
        orgRole: user.orgRole ?? null,
        defaultOrgId: user.defaultOrgId ?? null,
        mustChangePassword: Boolean(user.mustChangePassword)
      };
      tokenStorage.setUser(nextUser);
      setUser(nextUser);
      if (typeof window !== 'undefined' && user.defaultOrgId?.trim()) {
        localStorage.setItem(CURRENT_ORG_STORAGE_KEY, user.defaultOrgId.trim());
      }
      await acceptPendingOrgInviteAfterAuth();
      const returnTo = consumeAuthReturnTo();
      if (user.mustChangePassword) {
        const suffix = returnTo
          ? `?returnTo=${encodeURIComponent(returnTo)}`
          : '';
        router.push(`${ROUTES.AUTH.CHANGE_PASSWORD}${suffix}`);
        return;
      }
      // An admin's home is the console, not a workspace they happen to belong
      // to — same rule the sidebar uses to show the console at all.
      const home = canUseAdminConsole({
        userRole: normalizeNavUserRole(user.role),
        orgRole: normalizeNavOrgRole(user.orgRole)
      })
        ? ROUTES.ADMIN.ROOT
        : ROUTES.DEVICES.ROOT;
      router.push(returnTo || home);
    }
  });
}
