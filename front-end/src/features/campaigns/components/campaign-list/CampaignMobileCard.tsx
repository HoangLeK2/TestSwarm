'use client';

import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { cn } from '@/lib/utils';
import type { CampaignOut } from '../../types';
import { CampaignSetupCell } from './CampaignSetupCell';
import { CampaignRowActions } from './CampaignRowActions';
import { CampaignRunStats } from './CampaignRunStats';
import { CampaignEngineBadge } from './CampaignEngineBadge';
import { CampaignStatusBadge } from './CampaignStatusBadge';
import type { CampaignStatus } from '../../types';

export function CampaignMobileCard({
  campaign,
  statusLabel,
  id,
  className
}: {
  campaign: CampaignOut;
  statusLabel: Record<string, string>;
  id?: string;
  className?: string;
}) {
  const description = (campaign.description ?? '').trim();

  return (
    <article
      id={id}
      className={cn(
        'rounded-xl border border-border bg-card p-3 shadow-sm',
        className
      )}
    >
      <div className='flex items-start justify-between gap-2'>
        <div className='min-w-0 flex-1'>
          <h3 className='truncate text-sm font-semibold leading-snug'>
            {campaign.name}
          </h3>
          {description ? (
            <p className='mt-0.5 line-clamp-2 text-[11px] text-muted-foreground'>
              {description}
            </p>
          ) : null}
        </div>
        <CampaignStatusBadge
          campaignId={campaign.id}
          status={campaign.status}
          statusLabels={statusLabel as Record<CampaignStatus, string>}
          className='shrink-0 text-[10px]'
        />
      </div>

      <div className='mt-1'>
        <CampaignEngineBadge
          campaignId={campaign.id}
          status={campaign.status}
        />
      </div>

      <div className='mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground'>
        <span>
          {formatDistanceToNow(new Date(campaign.created_at), {
            addSuffix: true,
            locale: vi
          })}
        </span>
        <CampaignRunStats campaignId={campaign.id} />
      </div>

      <div className='mt-3 space-y-3 [&_[class*="max-w"]]:max-w-none'>
        <CampaignSetupCell campaign={campaign} />
        <div className='border-t border-border/60 pt-3'>
          <CampaignRowActions campaign={campaign} layout='stacked' />
        </div>
      </div>
    </article>
  );
}
