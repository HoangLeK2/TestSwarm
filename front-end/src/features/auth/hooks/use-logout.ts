'use client';

import { tokenStorage } from '@/lib/token-storage';
import { useAuthContext } from '../providers/auth-provider';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

export function useLogout() {
  const { setUser } = useAuthContext();
  const router = useRouter();

  const handleLogout = () => {
    tokenStorage.clearTokens();
    setUser(null);
    router.replace(ROUTES.AUTH.SIGN_IN);
  };

  return { handleLogout };
}
