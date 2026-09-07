import { ActivityFeed } from '@/features/analytics/components/activity-feed';
import { getTranslations } from 'next-intl/server';

export default async function Page() {
  const t = await getTranslations('adminConsole.audit');
  return (
    <ActivityFeed adminMode title={t('title')} description={t('description')} />
  );
}
