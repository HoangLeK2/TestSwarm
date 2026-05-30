'use client';

import { useTranslations } from 'next-intl';

export function AcceptInviteLoading() {
  const t = useTranslations('organization.inviteAccept');
  return (
    <div className='relative w-full overflow-hidden rounded-3xl border border-white/40 bg-white/70 p-7 backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 sm:p-9'>
      <p className='text-center text-sm text-muted-foreground'>{t('loading')}</p>
    </div>
  );
}
