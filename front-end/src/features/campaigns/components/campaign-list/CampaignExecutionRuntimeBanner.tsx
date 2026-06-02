'use client';

import { AlertTriangle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useExecutionRuntime } from '../../hooks/use-campaigns';

export function CampaignExecutionRuntimeBanner() {
  const t = useTranslations('campaignsFeature.list');
  const { data: runtime } = useExecutionRuntime();

  if (!runtime?.campaign_run?.fallback_mode_active) {
    return null;
  }

  return (
    <div
      role='status'
      className='flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-950 dark:text-amber-100'
    >
      <AlertTriangle className='mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400' />
      <div className='min-w-0 space-y-0.5'>
        <p className='font-medium'>{t('fallbackModeTitle')}</p>
        <p className='text-xs leading-relaxed text-amber-900/90 dark:text-amber-100/90'>
          {t('fallbackModeDescription')}
        </p>
      </div>
    </div>
  );
}
