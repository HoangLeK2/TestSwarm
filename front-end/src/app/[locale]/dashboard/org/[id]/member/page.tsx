'use client';

import { useEffect } from 'react';
import { useParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

/** Legacy URL: /dashboard/org/:id/member → members settings */
export default function LegacyOrgMembersRedirectPage() {
  const router = useRouter();
  const params = useParams();

  useEffect(() => {
    router.replace(ROUTES.DASHBOARD.ORGANIZATION_MEMBER);
  }, [router, params.id]);

  return null;
}
