'use client';

import { Badge } from '@/components/ui/badge';
import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { executionsApi } from '../../services/api';
import { useExecutionRuntime } from '../../hooks/use-campaigns';
import { isActiveExecutionStatus } from '../../types';

export function CampaignEngineBadge({
  campaignId,
  status
}: {
  campaignId: string;
  status: string;
}) {
  const t = useTranslations('campaignsFeature.list');
  const active = isActiveExecutionStatus(status);
  const { data: runtime } = useExecutionRuntime();
  const { data } = useQuery({
    queryKey: ['campaign-latest-execution', campaignId],
    queryFn: () => executionsApi.list({ campaignId, limit: 1, offset: 0 }),
    enabled: active,
    staleTime: 10_000,
    refetchInterval: active ? 15_000 : false
  });

  if (!active) {
    return null;
  }

  const dispatchSource = data?.items?.[0]?.meta?.dispatch_source;
  const fallbackGlobal = runtime?.campaign_run?.fallback_mode_active === true;
  const isFallback = dispatchSource === 'fallback' || fallbackGlobal;

  return (
    <Badge variant='outline' className='text-[10px] font-normal'>
      {isFallback ? t('engineTaskQueue') : t('engineTemporal')}
    </Badge>
  );
}
