'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { tokenStorage } from '@/lib/token-storage';

interface AuthGuardProps {
  children: React.ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const router = useRouter();
  const [canRender, setCanRender] = useState(false);

  useEffect(() => {
    if (!tokenStorage.isAuthenticated()) {
      router.push(ROUTES.AUTH.SIGN_IN);
      return;
    }

    setCanRender(true);
  }, [router]);

  if (!canRender) {
    return null;
  }

  return <>{children}</>;
}

