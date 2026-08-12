'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ROUTES } from '@/config/routes';

export default function AccountGroupsPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(ROUTES.ACCOUNTS.ROOT);
  }, [router]);
  return null;
}
