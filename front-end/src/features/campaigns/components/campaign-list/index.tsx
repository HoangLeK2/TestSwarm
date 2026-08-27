'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { FileText, Loader2, Plus, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCampaignPage } from '../../hooks/use-campaigns';
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
import { useDebouncedCallback } from '@/hooks/use-debounced-callback';
import { parseAsInteger, useQueryStates } from 'nuqs';

function useIsLgUp() {
  const [isLgUp, setIsLgUp] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)');
    const update = () => setIsLgUp(mq.matches);
    update();
    const onChange = () => update();
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
  const tCreate = useTranslations('campaignsFeature.createDialog');
  const createDialogProps = {
    initialOpen: openCreateCampaign && Boolean(attachScenarioId),
    preselectedScenarioIds: attachScenarioId ? [attachScenarioId] : []
  };
  const tEmpty = useTranslations('coreEmptyState');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [{ page, perPage }, setPagination] = useQueryStates({
    page: parseAsInteger.withDefault(1),
    perPage: parseAsInteger.withDefault(10)
  });
  const updateSearch = useDebouncedCallback((value: string) => {
    setDebouncedSearchQuery(value);
    void setPagination({ page: 1 });
  }, 300);
  const {
    data: campaignPage,
    isLoading,
    isFetching,
    error,
    refetch
  } = useCampaignPage(debouncedSearchQuery, page, perPage);
  const campaigns = campaignPage?.items;
  const total = campaignPage?.total ?? 0;
  const { focusCampaignId, onFocusCampaignHandled } =
    useCampaignFocusFromDeepLink();
  const isLgUp = useIsLgUp();
  const highlightCampaignId = useCampaignListFocus(
    focusCampaignId,
    isLgUp === null ? undefined : campaigns,
    onFocusCampaignHandled
  );

  const data: CampaignOut[] = campaigns ?? [];

  const getRowProps = useCallback(
    (row: { original: CampaignOut }) => ({
      ...(isLgUp === true ? { id: campaignRowAnchorId(row.original.id) } : {}),
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
    pageCount: Math.max(1, Math.ceil(total / perPage)),
    initialState: { pagination: { pageIndex: 0, pageSize: 10 } }
  });

  return (
    <div className='space-y-3'>
      <CampaignExecutionRuntimeBanner />
      {isLoading || error ? (
        <div className='flex min-h-[22rem] items-center justify-center'>
          <div className='flex flex-col items-center text-center'>
            <Loader2 className='size-7 animate-spin text-muted-foreground' />
            <p className='mt-3 text-sm text-muted-foreground'>
              {isLoading ? t('loading') : t('loadError')}
            </p>
            {error ? (
              <Button
                type='button'
                variant='ghost'
                size='sm'
                className='mt-2'
                onClick={() => void refetch()}
              >
                {t('retry')}
              </Button>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-sm text-muted-foreground'>
              <span className='font-medium text-foreground'>{total}</span>{' '}
              {t('campaignCountLabel')}
            </p>
            <div className='flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center'>
              {total || searchQuery ? (
                <div className='relative w-full sm:w-72'>
                  <Search className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
                  <Input
                    type='search'
                    value={searchQuery}
                    onChange={(event) => {
                      setSearchQuery(event.target.value);
                      updateSearch(event.target.value);
                    }}
                    placeholder={t('searchPlaceholder')}
                    aria-label={t('searchLabel')}
                    aria-busy={isFetching}
                    className='pl-9 pr-9'
                  />
                  {isFetching ? (
                    <Loader2 className='pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-muted-foreground' />
                  ) : null}
                </div>
              ) : null}
              <Can object='campaigns' action='create'>
                <CreateCampaignDialog {...createDialogProps} />
              </Can>
            </div>
          </div>

          {!campaigns?.length && !debouncedSearchQuery && (
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
              <CoreEmptyState
                icon={FileText}
                title={tEmpty('campaigns.title')}
                description={tEmpty('campaigns.description')}
                trackingKey='campaigns-empty'
                action={
                  <CreateCampaignDialog
                    {...createDialogProps}
                    trigger={
                      <Button size='sm' className='min-w-[8rem]'>
                        <Plus size={16} className='mr-1' />
                        {tCreate('trigger')}
                      </Button>
                    }
                  />
                }
              />
            </Can>
          )}

          {campaigns?.length && data.length ? (
            <>
              {isLgUp === false ? (
                <CampaignMobileList
                  campaigns={data}
                  statusLabel={statusLabel}
                  highlightCampaignId={highlightCampaignId}
                  withRowAnchor
                />
              ) : null}
              {isLgUp === true ? (
                <DataTable
                  table={table}
                  total={total}
                  getRowProps={getRowProps}
                />
              ) : null}
            </>
          ) : null}

          {debouncedSearchQuery && !data.length ? (
            <div className='rounded-md border border-dashed px-4 py-10 text-center'>
              <p className='text-sm font-medium'>{t('searchEmptyTitle')}</p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('searchEmptyDescription')}
              </p>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
