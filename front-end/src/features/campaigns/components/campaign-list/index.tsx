'use client';

import { useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { FileText } from 'lucide-react';
import { useCampaigns } from '../../hooks/use-campaigns';
import type { CampaignOut, CampaignStatus } from '../../types';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateCampaignDialog } from '../create-campaign-dialog';
import { Can } from '@/features/auth';
import { getCampaignColumns } from './columns';
import { CampaignMobileList } from './CampaignMobileList';

const STATUS_VARIANT: Record<
  CampaignStatus,
  'secondary' | 'default' | 'outline' | 'destructive'
> = {
  idle: 'outline',
  draft: 'outline',
  running: 'default',
  paused: 'outline',
  completed: 'outline'
};

export function CampaignList() {
  const t = useTranslations('campaignsFeature.list');
  const { data: campaigns, isLoading, error } = useCampaigns();

  const data: CampaignOut[] = campaigns ?? [];

  const statusLabel = useMemo<Record<CampaignStatus, string>>(
    () => ({
      idle: t('statusIdle'),
      draft: t('statusDraft'),
      running: t('statusRunning'),
      paused: t('statusPaused'),
      completed: t('statusCompleted')
    }),
    [t]
  );

  const columns = useMemo(() => {
    return getCampaignColumns(t, statusLabel, STATUS_VARIANT);
  }, [t, statusLabel]);

  const { table } = useDataTable<CampaignOut>({
    data,
    columns,
    pageCount: 1
  });

  return (
    <div className='space-y-3'>
      {isLoading || error ? (
        <div>
          {isLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {error && (
            <p className='text-sm text-destructive'>{t('loadError')}</p>
          )}
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <p className='text-sm text-muted-foreground'>
              <span className='font-medium text-foreground'>
                {campaigns?.length ?? 0}
              </span>{' '}
              {t('campaignCountLabel')}
            </p>
            <Can object='campaigns' action='create'>
              <CreateCampaignDialog />
            </Can>
          </div>

          {!campaigns?.length && (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-12 text-center'>
              <FileText className='mx-auto mb-3 size-10 text-muted-foreground/60' />
              <p className='text-sm font-medium text-foreground'>
                {t('emptyTitle')}
              </p>
              <p className='mt-1 text-xs text-muted-foreground'>
                {t('emptyDescription')}
              </p>
              <div className='mt-4'>
                <Can object='campaigns' action='create'>
                  <CreateCampaignDialog />
                </Can>
              </div>
            </div>
          )}

          {campaigns?.length ? (
            <>
              <CampaignMobileList
                campaigns={campaigns}
                statusLabel={statusLabel}
                statusVariant={STATUS_VARIANT}
              />
              <div className='hidden lg:block'>
                <DataTable table={table} total={campaigns.length} />
              </div>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
