'use client';

import { useEffect } from 'react';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

export function ClientRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.push(ROUTES.DEVICES.ROOT);
  }, [router]);

  return <></>;
}
