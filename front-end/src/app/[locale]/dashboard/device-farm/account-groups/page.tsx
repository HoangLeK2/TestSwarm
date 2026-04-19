'use client';

import { useTranslations } from 'next-intl';
import { AccountGroupsList } from '@/features/account-groups/components/account-groups-list';

export default function AccountGroupsPage() {
  const t = useTranslations('accountGroupsFeature');
  return (
    <div className='space-y-4'>
      <div className='space-y-1'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('pageTitle')}
        </h1>
        <p className='text-sm text-muted-foreground'>{t('pageSubtitle')}</p>
      </div>
      <AccountGroupsList />
    </div>
  );
}
