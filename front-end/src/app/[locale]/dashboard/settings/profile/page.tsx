'use client';

import { useTranslations } from 'next-intl';
import { Heading } from '@/components/ui/heading';
import { ProfileView } from '@/features/settings/components/profile-view';

export default function ProfileSettingsPage() {
  const t = useTranslations('settingsFeature.profile');

  return (
    <div className='space-y-6 p-4 sm:p-6'>
      <Heading title={t('pageTitle')} description={t('pageDescription')} />
      <ProfileView />
    </div>
  );
}
