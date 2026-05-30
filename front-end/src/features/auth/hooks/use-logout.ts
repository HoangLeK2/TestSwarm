'use client';

import { tokenStorage } from '@/lib/token-storage';
import { useAuthContext } from '../providers/auth-provider';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { authApi } from '../services/api';

export function useLogout() {
  const { setUser } = useAuthContext();
  const router = useRouter();

  const handleLogout = async () => {
    const refreshToken = tokenStorage.getRefreshToken();
    try {
      await authApi.logout(refreshToken);
    } catch {
      // Clear local session even if revoke fails (offline / expired access token).
    }
    tokenStorage.clearTokens();
    setUser(null);
    router.replace(ROUTES.AUTH.SIGN_IN);
  };

  return { handleLogout };
}
