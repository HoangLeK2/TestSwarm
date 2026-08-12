'use client';

import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { campaignVariables } from '../../services/api';
import type { CampaignOut } from '../../types';
import { isContinuousCrawl } from '../../lib/continuous-crawl-monitor';

export function AutomationBadge({ campaign }: { campaign: CampaignOut }) {
  const t = useTranslations('campaignsFeature.list');
  if (!isContinuousCrawl(campaignVariables(campaign))) return null;
  return (
    <Badge variant='outline' className='text-[10px] font-medium'>
      {t('automationBadge')}
    </Badge>
  );
}
