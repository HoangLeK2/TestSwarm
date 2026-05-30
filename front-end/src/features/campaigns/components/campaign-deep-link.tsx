'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { useCampaigns } from '../hooks/use-campaigns';
import { CampaignMonitorDialog } from './campaign-monitor';

/**
 * When URL contains ?campaign_id=, auto-open the campaign monitor dialog once.
 */
export function CampaignDeepLink() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const campaignId = searchParams.get('campaign_id');
  const { data: campaigns } = useCampaigns();
  const [open, setOpen] = useState(false);
  const [handled, setHandled] = useState(false);

  const campaign = useMemo(
    () => campaigns?.find((c) => c.id === campaignId) ?? null,
    [campaigns, campaignId]
  );

  useEffect(() => {
    if (!campaignId || handled) return;
    if (campaigns && !campaign) {
      setHandled(true);
      router.replace(ROUTES.CAMPAIGNS.ROOT);
      return;
    }
    if (campaign) {
      setOpen(true);
      setHandled(true);
    }
  }, [campaign, campaignId, campaigns, handled, router]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next && campaignId) {
      router.replace(ROUTES.CAMPAIGNS.ROOT);
    }
  };

  if (!campaign) return null;

  return (
    <CampaignMonitorDialog
      campaign={campaign}
      open={open}
      onOpenChange={handleOpenChange}
    />
  );
}
