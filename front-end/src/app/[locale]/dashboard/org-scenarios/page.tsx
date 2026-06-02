'use client';

import { useTranslations } from 'next-intl';
import { ScenarioLibrary } from '@/features/org-scenarios/components/scenario-library';

export default function OrgScenariosPage() {
  const t = useTranslations('orgScenariosFeature.page');

  return (
    <div className='space-y-5'>
      <div>
        <h1 className='text-2xl font-semibold tracking-tight text-foreground'>
          {t('title')}
        </h1>
        <p className='mt-1 text-sm text-muted-foreground'>{t('subtitle')}</p>
      </div>
      <ScenarioLibrary />
    </div>
  );
}
