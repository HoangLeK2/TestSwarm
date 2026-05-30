'use client';

import { useEffect } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { usePathname, useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { tokenStorage } from '@/lib/token-storage';
import { saveAuthReturnTo } from '@/features/content/lib/permalink';
import { ContentDetailView } from '@/features/content/components/content-detail/content-detail-view';

export default function ContentDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const contentId = typeof params.id === 'string' ? params.id : '';

  useEffect(() => {
    if (tokenStorage.isAuthenticated()) return;
    const query = searchParams.toString();
    const returnTo = query ? `${pathname}?${query}` : pathname;
    saveAuthReturnTo(returnTo || ROUTES.CONTENT.DETAIL(contentId));
    router.replace(ROUTES.AUTH.SIGN_IN);
  }, [contentId, pathname, router, searchParams]);

  if (!tokenStorage.isAuthenticated()) {
    return null;
  }

  const shareToken = searchParams.get('share');

  useEffect(() => {
    if (!contentId && tokenStorage.isAuthenticated()) {
      router.replace(ROUTES.CONTENT.ROOT);
    }
  }, [contentId, router]);

  if (!contentId) {
    return null;
  }

  return (
    <div className='p-4 md:p-6'>
      <ContentDetailView contentId={contentId} shareToken={shareToken} />
    </div>
  );
}
