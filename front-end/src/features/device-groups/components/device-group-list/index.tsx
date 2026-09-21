'use client';

import { useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { FolderOpen } from 'lucide-react';
import { toast } from 'sonner';
import {
  useDeviceGroups,
  useDeleteDeviceGroup
} from '../../hooks/use-device-groups';
import type { DeviceGroupOut } from '../../services/api';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateDeviceGroupDialog } from '../create-device-group-dialog';
import { DeviceGroupDetail } from '../device-group-detail';
import { getDeviceGroupColumns } from './columns';
import { useConfirm } from '@/providers/modal-provider';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ROUTES } from '@/config/routes';
import { Can } from '@/features/auth';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

export function DeviceGroupList() {
  const t = useTranslations('deviceGroupsFeature.list');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const confirm = useConfirm();
  const { data: groups, isLoading, error } = useDeviceGroups();
  const deleteMutation = useDeleteDeviceGroup();
  const [selectedGroup, setSelectedGroup] = useState<DeviceGroupOut | null>(
    null
  );

  const data: DeviceGroupOut[] = groups ?? [];

  const columns = useMemo(
    () =>
      getDeviceGroupColumns(
        t,
        (group) => {
          void (async () => {
            const ok = await confirm({
              description: t('confirmDelete', { name: group.name }),
              confirmText: tCommon('confirm'),
              cancelText: tCommon('cancel'),
              confirmVariant: 'destructive',
              zIndex: 10_000
            });
            if (!ok) return;
            deleteMutation.mutate(group.id, {
              onSuccess: () => toast.success(t('deleteSuccess')),
              onError: (err) => {
                toast.error(formatFarmApiError(err, t('deleteFailed')));
              }
            });
          })();
        },
        (group) => setSelectedGroup(group),
        locale
      ),
    [t, tCommon, confirm, deleteMutation, locale]
  );

  const { table } = useDataTable<DeviceGroupOut>({
    data,
    columns
  });

  if (selectedGroup) {
    return (
      <DeviceGroupDetail
        groupId={selectedGroup.id}
        onBack={() => setSelectedGroup(null)}
      />
    );
  }

  return (
    <div className='space-y-6'>
      <div className='flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between'>
        <div className='max-w-3xl space-y-1.5'>
          <h1 className='text-2xl font-semibold tracking-tight'>
            {t('title')}
          </h1>
          <p className='text-sm leading-6 text-muted-foreground'>
            {t('description')}
          </p>
        </div>
        {!!groups?.length && (
          <Can object='device-groups' action='create'>
            <CreateDeviceGroupDialog />
          </Can>
        )}
      </div>

      <div className='rounded-lg border border-border bg-muted/20 px-4 py-3'>
        <p className='text-sm font-medium text-foreground'>
          {t('operatorCueTitle')}
        </p>
        <p className='mt-1 text-sm leading-6 text-muted-foreground'>
          {t('operatorCueDescription')}
        </p>
      </div>

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
          {!!groups?.length && (
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <p className='text-muted-foreground'>
                <span className='font-medium text-foreground'>
                  {groups?.length ?? 0}
                </span>{' '}
                {t('countLabel')}
              </p>
            </div>
          )}

          {!groups?.length && (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <FolderOpen className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {t('emptyTitle')}
              </p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('emptyDescription')}
              </p>
              <div className='mx-auto mt-6 max-w-[42rem] rounded-lg border border-border/60 bg-background/50 p-4 text-center'>
                <p className='text-xs font-semibold text-foreground'>
                  {t('quickStartTitle')}
                </p>
                <ol className='mx-auto mt-2 list-decimal space-y-1 pl-4 text-left text-xs text-muted-foreground'>
                  <li>{t('quickStartStep1')}</li>
                  <li>{t('quickStartStep2')}</li>
                  <li>{t('quickStartStep3')}</li>
                </ol>
                <div className='mt-3 flex flex-wrap justify-center gap-2'>
                  <Can object='device-groups' action='create'>
                    <CreateDeviceGroupDialog />
                  </Can>
                  <Button asChild size='sm' variant='outline'>
                    <Link href={ROUTES.CAMPAIGNS.ROOT}>
                      {t('quickStartGoCampaigns')}
                    </Link>
                  </Button>
                  <Button asChild size='sm' variant='outline'>
                    <Link href={ROUTES.SCHEDULES.ROOT}>
                      {t('quickStartGoSchedules')}
                    </Link>
                  </Button>
                </div>
              </div>
            </div>
          )}

          {groups?.length ? (
            <DataTable table={table} total={groups.length} />
          ) : null}
        </>
      )}
    </div>
  );
}
