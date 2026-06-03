'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { FileText } from 'lucide-react';
import { useCampaigns } from '../../hooks/use-campaigns';
import { useCampaignListFocus } from '../../hooks/use-campaign-list-focus';
import type { CampaignOut } from '../../types';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateCampaignDialog } from '../create-campaign-dialog';
import { Can } from '@/features/auth';
import { getCampaignColumns } from './columns';
import { CampaignMobileList } from './CampaignMobileList';
import { CampaignExecutionRuntimeBanner } from './CampaignExecutionRuntimeBanner';
import { buildCampaignStatusLabels } from '../../campaign-status-ui';
import { CoreEmptyState } from '@/components/core-empty-state';
import { useCampaignFocusFromDeepLink } from '../campaign-deep-link';
import {
  campaignRowAnchorId,
  campaignRowHighlightClass
} from '../../lib/campaign-row-anchor';
import { cn } from '@/lib/utils';

function useIsLgUp() {
  const [isLgUp, setIsLgUp] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    setIsLgUp(mq.matches);
    const onChange = () => setIsLgUp(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return isLgUp;
}

export function CampaignList({
  attachScenarioId,
  openCreateCampaign = false
}: {
  attachScenarioId?: string | null;
  openCreateCampaign?: boolean;
} = {}) {
  const t = useTranslations('campaignsFeature.list');
  const createDialogProps = {
    initialOpen: openCreateCampaign && Boolean(attachScenarioId),
    preselectedScenarioIds: attachScenarioId ? [attachScenarioId] : []
  };
  const tEmpty = useTranslations('coreEmptyState');
  const { data: campaigns, isLoading, error } = useCampaigns();
  const { focusCampaignId, onFocusCampaignHandled } =
    useCampaignFocusFromDeepLink();
  const isLgUp = useIsLgUp();
  const highlightCampaignId = useCampaignListFocus(
    focusCampaignId,
    campaigns,
    onFocusCampaignHandled
  );

  const data: CampaignOut[] = campaigns ?? [];

  const getRowProps = useCallback(
    (row: { original: CampaignOut }) => ({
      ...(isLgUp ? { id: campaignRowAnchorId(row.original.id) } : {}),
      className: cn(
        highlightCampaignId === row.original.id && campaignRowHighlightClass
      )
    }),
    [highlightCampaignId, isLgUp]
  );

  const statusLabel = useMemo(
    () => buildCampaignStatusLabels((key) => t(key)),
    [t]
  );

  const columns = useMemo(() => {
    return getCampaignColumns(t, statusLabel);
  }, [t, statusLabel]);

  const { table } = useDataTable<CampaignOut>({
    data,
    columns,
    pageCount: 1
  });

  return (
    <div className='space-y-3'>
      <CampaignExecutionRuntimeBanner />
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
              <CreateCampaignDialog {...createDialogProps} />
            </Can>
          </div>

          {!campaigns?.length && (
            <Can
              object='campaigns'
              action='create'
              fallback={
                <CoreEmptyState
                  icon={FileText}
                  title={tEmpty('campaigns.title')}
                  description={tEmpty('campaigns.description')}
                  readOnlyHint={tEmpty('readOnlyHint')}
                  trackingKey='campaigns-empty-readonly'
                />
              }
            >
              <div className='space-y-4'>
                <CoreEmptyState
                  icon={FileText}
                  title={tEmpty('campaigns.title')}
                  description={tEmpty('campaigns.description')}
                  trackingKey='campaigns-empty'
                />
                <div className='flex justify-center'>
                  <CreateCampaignDialog {...createDialogProps} />
                </div>
              </div>
            </Can>
          )}

          {campaigns?.length ? (
            <>
              <CampaignMobileList
                campaigns={campaigns}
                statusLabel={statusLabel}
                highlightCampaignId={highlightCampaignId}
                withRowAnchor={!isLgUp}
              />
              <div className='hidden lg:block'>
                <DataTable
                  table={table}
                  total={campaigns.length}
                  getRowProps={getRowProps}
                />
              </div>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
