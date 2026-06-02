'use client';

import { AlertTriangle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import type { WorkflowInfo } from '../../types';

type Props = {
  workflows: WorkflowInfo[];
  /** Show banner when failure rate is at or above this percent (default 20). */
  thresholdPercent?: number;
};

export function MonitorFailureBanner({
  workflows,
  thresholdPercent = 20
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const total = workflows.length;
  const failed = workflows.filter((w) => w.status === 'FAILED').length;

  if (total === 0 || failed === 0) return null;

  const rate = Math.round((failed / total) * 100);
  if (failed < 1 || rate < thresholdPercent) return null;

  return (
    <div
      role='alert'
      className='flex items-start gap-2 border-b border-destructive/30 bg-destructive/10 px-6 py-3 text-sm text-destructive'
    >
      <AlertTriangle size={16} className='mt-0.5 shrink-0' />
      <p>{t('monitorFailureRateBanner', { failed, total, rate })}</p>
    </div>
  );
}
