'use client';

import { useEffect } from 'react';
import { useParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

/** Legacy URL: /dashboard/org/:id → organization settings */
export default function LegacyOrgSettingsRedirectPage() {
  const router = useRouter();
  const params = useParams();

  useEffect(() => {
    router.replace(ROUTES.DASHBOARD.ORGANIZATION);
  }, [router, params.id]);

  return null;
}
