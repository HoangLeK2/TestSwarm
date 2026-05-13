'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { FolderOpen } from 'lucide-react';
import { useDeviceGroups, useDeleteDeviceGroup } from '../../hooks/use-device-groups';
import type { DeviceGroupOut } from '../../services/api';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateDeviceGroupDialog } from '../create-device-group-dialog';
import { DeviceGroupDetail } from '../device-group-detail';
import { getDeviceGroupColumns } from './columns';
import { useConfirm } from '@/providers/modal-provider';

export function DeviceGroupList() {
  const t = useTranslations('deviceGroupsFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { data: groups, isLoading, error } = useDeviceGroups();
  const deleteMutation = useDeleteDeviceGroup();
  const [selectedGroup, setSelectedGroup] = useState<DeviceGroupOut | null>(null);

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
            deleteMutation.mutate(group.id);
          })();
        },
        (group) => setSelectedGroup(group)
      ),
    [t, tCommon, confirm, deleteMutation]
  );

  const { table } = useDataTable<DeviceGroupOut>({
    data,
    columns,
    pageCount: 1
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
      {isLoading || error ? (
        <div>
          {isLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {error && <p className='text-sm text-destructive'>{t('loadError')}</p>}
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-muted-foreground'>
              <span className='font-medium text-foreground'>
                {groups?.length ?? 0}
              </span>{' '}
              {t('countLabel')}
            </p>
            <CreateDeviceGroupDialog />
          </div>

          {!groups?.length && (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <FolderOpen className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {t('emptyTitle')}
              </p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('emptyDescription')}
              </p>
              <div className='mt-6'>
                <CreateDeviceGroupDialog />
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
