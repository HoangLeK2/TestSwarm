'use client';

import { useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { FileText } from 'lucide-react';
import { useCampaigns } from '../../hooks/use-campaigns';
import type { CampaignOut, CampaignStatus } from '../../types';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateCampaignDialog } from '../create-campaign-dialog';
import { getCampaignColumns } from './columns';

const STATUS_VARIANT: Record<CampaignStatus, 'secondary' | 'default' | 'outline' | 'destructive'> = {
  draft: 'outline',
  running: 'default',
  paused: 'secondary',
  completed: 'secondary'
};

export function CampaignList() {
  const t = useTranslations('campaignsFeature.list');
  const { data: campaigns, isLoading, error } = useCampaigns();

  const data: CampaignOut[] = campaigns ?? [];

  const columns = useMemo(() => {
    const statusLabel: Record<CampaignStatus, string> = {
      draft: t('statusDraft'),
      running: t('statusRunning'),
      paused: t('statusPaused'),
      completed: t('statusCompleted')
    };

    return getCampaignColumns(t, statusLabel, STATUS_VARIANT);
  }, [t]);

  const { table } = useDataTable<CampaignOut>({
    data,
    columns,
    pageCount: 1
  });

  return (
    <div className='space-y-6'>
      {isLoading || error ? (
        <div>
          {isLoading && <p className='text-sm text-muted-foreground'>{t('loading')}</p>}
          {error && <p className='text-sm text-destructive'>{t('loadError')}</p>}
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-muted-foreground'>
              <span className='font-medium text-foreground'>{campaigns?.length ?? 0}</span>{' '}
              {t('campaignCountLabel')}
            </p>
            <CreateCampaignDialog />
          </div>

          {!campaigns?.length && (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <FileText className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>{t('emptyTitle')}</p>
              <p className='mt-1 text-sm text-muted-foreground'>{t('emptyDescription')}</p>
              <div className='mt-6'>
                <CreateCampaignDialog />
              </div>
            </div>
          )}

          {campaigns?.length ? <DataTable table={table} total={campaigns.length} /> : null}
        </>
      )}
    </div>
  );
}

