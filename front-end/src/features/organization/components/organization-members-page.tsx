'use client';

import { Users } from 'lucide-react';
import { useTranslations } from 'next-intl';

export function OrganizationMembersPage() {
  const t = useTranslations('organization.memberManagement');

  return (
    <div className='space-y-6'>
      <div className='flex items-center gap-3'>
        <Users className='size-5 text-muted-foreground' />
        <div>
          <h1 className='text-xl font-semibold'>{t('title')}</h1>
          <p className='text-sm text-muted-foreground'>{t('description')}</p>
        </div>
      </div>

      <div className='rounded-lg border border-dashed border-border p-12 text-center'>
        <Users className='mx-auto mb-3 size-10 text-muted-foreground' />
        <p className='text-sm text-muted-foreground'>{t('noMembersYet')}</p>
      </div>
    </div>
  );
}
