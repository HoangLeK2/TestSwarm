'use client';

import { Suspense } from 'react';
import { Mail } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useAuthEmailFromQuery } from '../lib/auth-query-defaults';

function AuthInviteEmailBannerInner() {
  const email = useAuthEmailFromQuery();
  const t = useTranslations('organization.inviteAccept');

  if (!email) return null;

  return (
    <div
      role='status'
      className='flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5 text-sm text-foreground'
    >
      <Mail className='mt-0.5 size-4 shrink-0 text-primary' aria-hidden />
      <p>{t('authEmailBanner', { email })}</p>
    </div>
  );
}

export function AuthInviteEmailBanner() {
  return (
    <Suspense fallback={null}>
      <AuthInviteEmailBannerInner />
    </Suspense>
  );
}
