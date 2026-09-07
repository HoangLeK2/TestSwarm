'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { tokenStorage } from '@/lib/token-storage';
import { useAuthContext } from '../providers/auth-provider';

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const { pending, user } = useAuthContext();
  const [canRender, setCanRender] = useState(false);

  useEffect(() => {
    if (pending) {
      setCanRender(false);
      return;
    }

    if (!tokenStorage.isAuthenticated()) {
      setCanRender(false);
      router.push(ROUTES.AUTH.SIGN_IN);
      return;
    }

    if (user?.mustChangePassword) {
      setCanRender(false);
      router.replace(ROUTES.AUTH.CHANGE_PASSWORD);
      return;
    }

    setCanRender(true);
  }, [pending, router, user?.mustChangePassword]);

  if (pending || !canRender) {
    return null;
  }

  return <>{children}</>;
}
