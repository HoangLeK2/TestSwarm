'use client';

import { Loader2, User } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuthContext } from '@/features/auth/providers/auth-provider';

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className='text-xs text-muted-foreground'>{label}</p>
      <p className='mt-0.5 text-sm font-medium'>{value || '—'}</p>
    </div>
  );
}

export function ProfileView() {
  const t = useTranslations('settingsFeature.profile');
  const { pending, user } = useAuthContext();

  if (pending) {
    return (
      <div className='flex items-center gap-2 py-12 text-sm text-muted-foreground'>
        <Loader2 size={16} className='animate-spin' />
        {t('loading')}
      </div>
    );
  }

  if (!user) {
    return <p className='text-sm text-muted-foreground'>{t('notSignedIn')}</p>;
  }

  return (
    <div className='mx-auto max-w-lg space-y-4'>
      <Card>
        <CardHeader className='flex flex-row items-center gap-3 space-y-0'>
          <div className='flex size-10 items-center justify-center rounded-full bg-muted'>
            <User size={20} className='text-muted-foreground' />
          </div>
          <div>
            <CardTitle className='text-base'>{t('title')}</CardTitle>
            <p className='text-xs text-muted-foreground'>{t('subtitle')}</p>
          </div>
        </CardHeader>
        <CardContent className='grid gap-4 sm:grid-cols-2'>
          <Field label={t('email')} value={user.email ?? ''} />
          <Field label={t('name')} value={user.givenName ?? ''} />
          <Field label={t('platformRole')} value={user.role ?? ''} />
          <Field label={t('orgRole')} value={user.orgRole ?? ''} />
        </CardContent>
      </Card>
      <p className='text-xs text-muted-foreground'>{t('twoFactorNote')}</p>
    </div>
  );
}
